#!/usr/bin/env bash
# Ship a new version to the single-VM deployment without a maintenance
# page and without touching Postgres/Redis/Garage/ClamAV/the mail relay —
# only the four things that ever change on a code push (migrate, api,
# worker, web) are rebuilt, and each of api/web is swapped one at a time
# behind a health check, with an automatic rollback to the previous image
# if the new one doesn't come up healthy. See
# docs/research/single-vm-deployment.md §12 for the full write-up,
# including how this same mechanism handles a Trivy-flagged base-image
# CVE (scripts/../.github/workflows/image-scan-weekly.yml detects it;
# this script is how the fix actually reaches production).
#
# What this is NOT: true zero-dropped-connections blue/green. Each
# service swap is a fast stop-old/start-new (typically 1-3 seconds of
# that ONE service being unavailable, not the whole site, and not a
# maintenance page) — real, but not zero. §12 of the doc names the
# upgrade path if that gap ever matters more than the complexity of
# closing it.
#
# Usage: sudo -E ./scripts/rolling-update.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ttli}"
COMPOSE_FILE="infra/docker-compose.single-vm.yml"
ENV_FILE="$APP_DIR/.env.prod"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-60}"

log()  { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

[ -f "$ENV_FILE" ] || die "$ENV_FILE not found — this isn't a deployed instance (run scripts/deploy-single-vm.sh first)"
# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a

cd "$APP_DIR"
DC() { docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"; }

if [ -d .git ]; then
  log "Pulling latest code"
  git pull --ff-only
fi

# --------------------------------------------------------------------
# Remember what's currently running, in case anything below needs undoing.
# An image ID captured here survives the tag being moved by a later
# `build` — Docker only deletes the old image blob if nothing still
# references it, and this ID is that reference until we're done with it.
# --------------------------------------------------------------------
prev_image() { docker image inspect --format='{{.Id}}' "$1" 2>/dev/null || echo ""; }
PREV_API="$(prev_image ttli-api:latest)"
PREV_WEB="$(prev_image ttli-web:latest)"

# --------------------------------------------------------------------
# Pull the already-built, already-scanned, already-signed release
# instead of building on the production host (TTLI_Audit_Report_2026-09-02.md
# M3) — the image running here must be the exact bytes CI's Trivy pass
# scanned and cosign signed, not a fresh build that could quietly drift
# from what was reviewed (a newer base-layer patch landing between build
# and deploy, a cache miss). RELEASE lets an operator pin to a specific
# known-good commit — e.g. to redeploy an older release after a bad
# rollout emptied the local `ttli-api:latest`/`ttli-web:latest` tags this
# script's own rollback below depends on — and defaults to whatever
# `git pull --ff-only` above just landed on.
# --------------------------------------------------------------------
: "${REGISTRY:?REGISTRY not set in $ENV_FILE -- e.g. ghcr.io/willemklopper87/ttli_lms (see scripts/deploy-single-vm.sh)}"
: "${GHCR_USERNAME:?GHCR_USERNAME not set in $ENV_FILE}"
: "${GHCR_PAT:?GHCR_PAT not set in $ENV_FILE -- a packages:read fine-grained PAT}"
export GIT_SHA="${RELEASE:-$(git rev-parse HEAD)}"

API_IMAGE="$REGISTRY/ttli-api:sha-$GIT_SHA"
WEB_IMAGE="$REGISTRY/ttli-web:sha-$GIT_SHA"

log "Logging in to GHCR"
echo "$GHCR_PAT" | docker login ghcr.io -u "$GHCR_USERNAME" --password-stdin

log "Pulling $API_IMAGE and $WEB_IMAGE"
docker pull "$API_IMAGE"
docker pull "$WEB_IMAGE"

# Keyless-signed in CI (OIDC via id-token: write — no stored signing key
# to rotate or leak). Verifying against this exact workflow's identity
# means a signature alone isn't enough; it must have come from this
# repo's ci.yml running on refs/heads/main, which a forked PR could never
# produce even if it tried. Mandatory, not best-effort (fable5.1_review.md
# C-3): a host with no cosign has no way to tell a real release from an
# unsigned or tampered image, so it must refuse to deploy rather than
# warn and continue — the whole point of signing in CI is defeated if the
# one place that verifies it can be skipped by simply not installing the
# verifier.
command -v cosign >/dev/null 2>&1 \
  || die "cosign is not installed on this host — refusing to deploy an unverified image. Install it first: https://docs.sigstore.dev/cosign/system_config/installation/"
log "Verifying image signatures"
cosign verify \
  --certificate-identity "https://github.com/WillemKlopper87/TTLI_LMS/.github/workflows/ci.yml@refs/heads/main" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
  "$API_IMAGE" "$WEB_IMAGE" >/dev/null \
  || die "signature verification failed — refusing to deploy an unsigned or tampered image"

docker tag "$API_IMAGE" ttli-api:latest
docker tag "$WEB_IMAGE" ttli-web:latest

# --------------------------------------------------------------------
# Migrations run before anything that would use the new schema — and
# must be backward-compatible with the OLD api/web images still running
# at this exact moment (docs/06_OPERATIONS.md §4.5: "add nullable,
# backfill, constrain — never all three in one release"). A migration
# that isn't leaves a window, however short, where old code runs against
# a schema it doesn't expect.
# --------------------------------------------------------------------
log "Running migrations"
if ! DC run --rm migrate; then
  warn "Migration failed — restoring previous image tags and aborting."
  warn "No running container was touched; the site is exactly as it was before this run."
  [ -n "$PREV_API" ] && docker tag "$PREV_API" ttli-api:latest
  [ -n "$PREV_WEB" ] && docker tag "$PREV_WEB" ttli-web:latest
  die "migration failed — see the output above"
fi

# --------------------------------------------------------------------
# Swap one service at a time. --no-deps is the whole trick: it recreates
# only the named service, leaving postgres/redis/garage/clamav/
# postfix-relay (and every OTHER app service) completely untouched.
# --------------------------------------------------------------------
wait_healthy() {
  local svc="$1" waited=0
  printf '  waiting for %s to report healthy' "$svc"
  while [ "$waited" -lt "$HEALTH_TIMEOUT" ]; do
    status="$(DC ps -q "$svc" | xargs -r docker inspect -f '{{.State.Health.Status}}' 2>/dev/null || echo starting)"
    if [ "$status" = "healthy" ]; then echo " ok"; return 0; fi
    printf '.'; sleep 3; waited=$((waited + 3))
  done
  echo " TIMED OUT"
  return 1
}

wait_running() {
  # arq has no HTTP healthcheck, so "running" is polled the same way
  # wait_healthy polls a real health endpoint — over the full timeout
  # window, not a single flat sleep — and a restart-count bump (Docker's
  # own crash-loop signal) fails it even if the container happens to be
  # "running" again at the instant we check.
  local svc="$1" waited=0 cid restarts_before restarts_now status
  cid="$(DC ps -q "$svc")"
  restarts_before="$(docker inspect -f '{{.RestartCount}}' "$cid" 2>/dev/null || echo 0)"
  printf '  waiting for %s to stay running' "$svc"
  while [ "$waited" -lt "$HEALTH_TIMEOUT" ]; do
    status="$(docker inspect -f '{{.State.Status}}' "$cid" 2>/dev/null || echo missing)"
    restarts_now="$(docker inspect -f '{{.RestartCount}}' "$cid" 2>/dev/null || echo 0)"
    if [ "$status" != "running" ] || [ "$restarts_now" -gt "$restarts_before" ]; then
      echo " NOT RUNNING (state: $status, restarts: $restarts_now)"
      return 1
    fi
    printf '.'; sleep 3; waited=$((waited + 3))
  done
  echo " ok"
  return 0
}

log "Swapping api"
DC up -d --no-deps api
if ! wait_healthy api; then
  warn "New api image failed its health check — rolling back to the previous image."
  [ -n "$PREV_API" ] && docker tag "$PREV_API" ttli-api:latest
  DC up -d --no-deps --force-recreate api
  wait_healthy api || warn "Rollback of api did not report healthy either — check logs by hand: docker compose -f $COMPOSE_FILE logs api"
  die "api rollout failed and was rolled back — nothing else in this run proceeded"
fi

log "Swapping worker (same image as api)"
DC up -d --no-deps worker
if ! wait_running worker; then
  # api and worker run the same image and share its migration/schema
  # assumptions — treating this as anything less than a full release
  # failure would leave api on the new version and worker on the old one,
  # an unversioned-skew combination nobody tested. Roll BOTH back to the
  # previous image, matching the same "one compatibility unit" the build
  # step already treats them as.
  warn "New worker container did not stay running — rolling back api and worker together."
  [ -n "$PREV_API" ] && docker tag "$PREV_API" ttli-api:latest
  DC up -d --no-deps --force-recreate api worker
  wait_healthy api || warn "Rollback of api did not report healthy — check logs by hand: docker compose -f $COMPOSE_FILE logs api"
  wait_running worker || warn "Rollback of worker did not stay running either — check logs by hand: docker compose -f $COMPOSE_FILE logs worker"
  die "worker rollout failed — api and worker were both rolled back together; web was never touched"
fi

log "Swapping web"
DC up -d --no-deps web
if ! wait_healthy web; then
  warn "New web image failed its health check — rolling back to the previous image."
  [ -n "$PREV_WEB" ] && docker tag "$PREV_WEB" ttli-web:latest
  DC up -d --no-deps --force-recreate web
  wait_healthy web || warn "Rollback of web did not report healthy either — check logs by hand: docker compose -f $COMPOSE_FILE logs web"
  die "web rollout failed and was rolled back — api/worker are already on the new version"
fi

log "Done — api, worker and web are on the new version. Postgres/Redis/Garage/ClamAV/mail relay were never touched."
log "Running image IDs (compare against \`git log\` / your CI build record, not just the tag):"
for svc in api worker web; do
  cid="$(DC ps -q "$svc")"
  image_id="$(docker inspect -f '{{.Image}}' "$cid" 2>/dev/null || echo unknown)"
  printf '  %-8s %s\n' "$svc" "$image_id"
done
