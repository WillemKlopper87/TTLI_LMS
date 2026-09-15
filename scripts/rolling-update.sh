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
# Same variable and default as scripts/backup-production.sh, deliberately —
# a release manifest written here (BACKLOG T10) is picked up and synced
# off-host by that script's next run rather than this script also carrying
# rclone/crypt credentials just to upload one JSON file.
BACKUP_DIR="${BACKUP_DIR:-$APP_DIR/backups}"

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

# Captured from the pulled reference, not re-derived later from the
# :latest tag this script is about to move — a digest is what actually
# proves which registry manifest is running, independent of any local tag.
API_DIGEST="$(docker inspect --format '{{index .RepoDigests 0}}' "$API_IMAGE" 2>/dev/null || echo unknown)"
WEB_DIGEST="$(docker inspect --format '{{index .RepoDigests 0}}' "$WEB_IMAGE" 2>/dev/null || echo unknown)"

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
# BACKLOG T10/F9: wait_healthy, not a "did the process stay running" poll —
# the compose file's worker healthcheck runs `arq --check`, which fails if
# the container boots but can never reach Redis, or its event loop hangs
# without ever crashing the process. A worker that is merely "running" was
# exactly the false-positive T10 set out to close.
if ! wait_healthy worker; then
  # api and worker run the same image and share its migration/schema
  # assumptions — treating this as anything less than a full release
  # failure would leave api on the new version and worker on the old one,
  # an unversioned-skew combination nobody tested. Roll BOTH back to the
  # previous image, matching the same "one compatibility unit" the build
  # step already treats them as.
  warn "New worker container failed its health check — rolling back api and worker together."
  [ -n "$PREV_API" ] && docker tag "$PREV_API" ttli-api:latest
  DC up -d --no-deps --force-recreate api worker
  wait_healthy api || warn "Rollback of api did not report healthy — check logs by hand: docker compose -f $COMPOSE_FILE logs api"
  wait_healthy worker || warn "Rollback of worker did not report healthy either — check logs by hand: docker compose -f $COMPOSE_FILE logs worker"
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
declare -A IMAGE_IDS
for svc in api worker web; do
  cid="$(DC ps -q "$svc")"
  image_id="$(docker inspect -f '{{.Image}}' "$cid" 2>/dev/null || echo unknown)"
  IMAGE_IDS[$svc]="$image_id"
  printf '  %-8s %s\n' "$svc" "$image_id"
done

# --------------------------------------------------------------------
# BACKLOG T10: a release manifest, evidence that this exact deploy
# actually came up — not merely that this script exited 0 — persisted
# off-host by riding scripts/backup-production.sh's next run (same
# BACKUP_DIR, which that script already syncs and prunes). Each check
# below queries the just-swapped containers directly rather than
# trusting the health-check verdicts already used to decide whether to
# roll back; a manifest whose evidence was gathered the same way as the
# gate that already passed proves nothing new.
# --------------------------------------------------------------------
log "Writing release manifest"
READY_BODY="$(DC exec -T api curl -sf http://localhost:8010/health/ready 2>/dev/null || echo '')"
if [ -n "$READY_BODY" ]; then API_READY=ok; else API_READY=failed; fi

if DC exec -T worker arq --check src.workers.main.WorkerSettings >/dev/null 2>&1; then
  WORKER_HEARTBEAT=ok
else
  WORKER_HEARTBEAT=failed
fi

if DC exec -T web node -e "require('http').get('http://localhost:3010/', r => process.exit(r.statusCode < 500 ? 0 : 1)).on('error', () => process.exit(1))" >/dev/null 2>&1; then
  WEB_HTTP=ok
else
  WEB_HTTP=failed
fi

APP_VERSION_RUNNING="$(DC exec -T api printenv APP_VERSION 2>/dev/null | tr -d '\r\n' || echo unknown)"
RELEASE_TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

mkdir -p "$BACKUP_DIR"
RELEASE_MANIFEST="$BACKUP_DIR/release-$GIT_SHA.json"
cat > "$RELEASE_MANIFEST" <<EOF
{
  "timestamp_utc": "$RELEASE_TIMESTAMP",
  "git_sha": "$GIT_SHA",
  "app_version": "$APP_VERSION_RUNNING",
  "registry_digests": {
    "api": "$API_DIGEST",
    "web": "$WEB_DIGEST"
  },
  "running_image_ids": {
    "api": "${IMAGE_IDS[api]}",
    "worker": "${IMAGE_IDS[worker]}",
    "web": "${IMAGE_IDS[web]}"
  },
  "checks": {
    "api_health_ready": "$API_READY",
    "worker_heartbeat": "$WORKER_HEARTBEAT",
    "web_http": "$WEB_HTTP"
  }
}
EOF
log "Release manifest written: $RELEASE_MANIFEST (synced off-host on the next scripts/backup-production.sh run)"

if [ "$API_READY" != ok ] || [ "$WORKER_HEARTBEAT" != ok ] || [ "$WEB_HTTP" != ok ]; then
  warn "Release manifest recorded at least one failed check after the swap completed — see $RELEASE_MANIFEST"
  warn "The deploy itself was not rolled back for this (each service already passed its own health check above);"
  warn "investigate by hand: docker compose -f $COMPOSE_FILE logs"
fi
