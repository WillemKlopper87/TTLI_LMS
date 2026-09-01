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
# Build first, while the old containers are still serving traffic —
# the only part of this that takes real time, and it costs zero downtime
# because nothing is swapped yet.
# --------------------------------------------------------------------
log "Building images"
export GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
DC build api web

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
  local svc="$1" waited=0
  printf '  waiting for %s to stay running' "$svc"
  sleep 5  # arq has no HTTP healthcheck; give it a moment to crash-loop if it's going to
  status="$(DC ps -q "$svc" | xargs -r docker inspect -f '{{.State.Status}}' 2>/dev/null || echo missing)"
  if [ "$status" = "running" ]; then echo " ok"; return 0; fi
  echo " NOT RUNNING (state: $status)"
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
if ! wait_running worker; then
  warn "New worker container did not stay running — rolling back to the previous image."
  [ -n "$PREV_API" ] && docker tag "$PREV_API" ttli-api:latest
  DC up -d --no-deps --force-recreate worker
  wait_running worker || warn "Rollback of worker did not stay running either — check logs by hand: docker compose -f $COMPOSE_FILE logs worker"
  warn "worker rollout failed and was rolled back — api is already on the new version; investigate before retrying worker"
  # Not a hard exit: api is genuinely fine and serving on the new version.
  # A broken worker delays background jobs (email, transcode) but doesn't
  # take the site down — surfacing it loudly is more useful than aborting
  # a rollout that's otherwise already succeeded.
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
