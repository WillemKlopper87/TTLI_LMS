#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ttli}"
COMPOSE_FILE="${COMPOSE_FILE:-infra/docker-compose.single-vm.yml}"
ENV_FILE="${ENV_FILE:-$APP_DIR/.env.prod}"
VERIFY_TIMEOUT="${DEPLOY_VERIFY_TIMEOUT:-90}"
EVIDENCE_DIR="${DEPLOY_EVIDENCE_DIR:-$APP_DIR/var/deployments}"

log()  { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

[ -f "$ENV_FILE" ] || die "$ENV_FILE not found"
# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a

cd "$APP_DIR"
DC() { docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"; }

: "${REGISTRY:?REGISTRY not set in $ENV_FILE}"
EXPECTED_GIT_SHA="${RELEASE:-$(git rev-parse HEAD 2>/dev/null || true)}"
[ -n "$EXPECTED_GIT_SHA" ] || die "cannot determine expected Git SHA; set RELEASE explicitly"

API_RELEASE_IMAGE="$REGISTRY/ttli-api:sha-$EXPECTED_GIT_SHA"
WEB_RELEASE_IMAGE="$REGISTRY/ttli-web:sha-$EXPECTED_GIT_SHA"

image_id() {
  docker image inspect --format='{{.Id}}' "$1" 2>/dev/null || true
}

container_id() {
  DC ps -q "$1" 2>/dev/null || true
}

container_image_id() {
  local cid="$1"
  docker inspect --format='{{.Image}}' "$cid" 2>/dev/null || true
}

wait_for() {
  local label="$1"; shift
  local waited=0
  printf '  waiting for %s' "$label"
  until "$@" >/dev/null 2>&1; do
    if [ "$waited" -ge "$VERIFY_TIMEOUT" ]; then
      echo " TIMED OUT"
      return 1
    fi
    printf '.'
    sleep 3
    waited=$((waited + 3))
  done
  echo " ok"
}

API_CID="$(container_id api)"
WORKER_CID="$(container_id worker)"
WEB_CID="$(container_id web)"
[ -n "$API_CID" ] || die "api container is not running"
[ -n "$WORKER_CID" ] || die "worker container is not running"
[ -n "$WEB_CID" ] || die "web container is not running"

EXPECTED_API_ID="$(image_id "$API_RELEASE_IMAGE")"
EXPECTED_WEB_ID="$(image_id "$WEB_RELEASE_IMAGE")"
[ -n "$EXPECTED_API_ID" ] || die "release image not present locally: $API_RELEASE_IMAGE"
[ -n "$EXPECTED_WEB_ID" ] || die "release image not present locally: $WEB_RELEASE_IMAGE"

ACTUAL_API_ID="$(container_image_id "$API_CID")"
ACTUAL_WORKER_ID="$(container_image_id "$WORKER_CID")"
ACTUAL_WEB_ID="$(container_image_id "$WEB_CID")"

[ "$ACTUAL_API_ID" = "$EXPECTED_API_ID" ] \
  || die "api is not running the expected release image ($ACTUAL_API_ID != $EXPECTED_API_ID)"
[ "$ACTUAL_WORKER_ID" = "$EXPECTED_API_ID" ] \
  || die "worker is not running the expected release image ($ACTUAL_WORKER_ID != $EXPECTED_API_ID)"
[ "$ACTUAL_WEB_ID" = "$EXPECTED_WEB_ID" ] \
  || die "web is not running the expected release image ($ACTUAL_WEB_ID != $EXPECTED_WEB_ID)"

log "Running active deployment canaries"
wait_for "API readiness" docker exec "$API_CID" curl -fsS http://127.0.0.1:8010/health/ready \
  || die "API readiness canary failed"

# arq writes a short-lived health sentinel into Redis from the worker event
# loop. `arq --check` verifies the worker has actually reached and is
# refreshing that loop, rather than merely proving that its container PID
# exists. This is the deployment canary for the non-HTTP worker.
wait_for "worker heartbeat" docker exec "$WORKER_CID" arq --check src.workers.main.WorkerSettings \
  || die "worker heartbeat canary failed"

wait_for "web HTTP response" docker exec "$WEB_CID" node -e \
  "require('http').get('http://127.0.0.1:3010/', r => process.exit(r.statusCode < 500 ? 0 : 1)).on('error', () => process.exit(1))" \
  || die "web canary failed"

API_VERSION="$(docker exec "$API_CID" printenv APP_VERSION 2>/dev/null || true)"
WORKER_VERSION="$(docker exec "$WORKER_CID" printenv APP_VERSION 2>/dev/null || true)"
[ "$API_VERSION" = "$EXPECTED_GIT_SHA" ] \
  || die "api APP_VERSION does not match release SHA ($API_VERSION != $EXPECTED_GIT_SHA)"
[ "$WORKER_VERSION" = "$EXPECTED_GIT_SHA" ] \
  || die "worker APP_VERSION does not match release SHA ($WORKER_VERSION != $EXPECTED_GIT_SHA)"

mkdir -p "$EVIDENCE_DIR"
chmod 0750 "$EVIDENCE_DIR" 2>/dev/null || true
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_FILE="$EVIDENCE_DIR/$STAMP-$EXPECTED_GIT_SHA.txt"
API_REPO_DIGESTS="$(docker image inspect --format='{{json .RepoDigests}}' "$API_RELEASE_IMAGE")"
WEB_REPO_DIGESTS="$(docker image inspect --format='{{json .RepoDigests}}' "$WEB_RELEASE_IMAGE")"

cat > "$EVIDENCE_FILE" <<EVIDENCE
verified_at_utc=$STAMP
git_sha=$EXPECTED_GIT_SHA
api.release_ref=$API_RELEASE_IMAGE
api.container_id=$API_CID
api.image_id=$ACTUAL_API_ID
api.repo_digests=$API_REPO_DIGESTS
api.app_version=$API_VERSION
api.readiness=pass
worker.release_ref=$API_RELEASE_IMAGE
worker.container_id=$WORKER_CID
worker.image_id=$ACTUAL_WORKER_ID
worker.app_version=$WORKER_VERSION
worker.heartbeat=pass
web.release_ref=$WEB_RELEASE_IMAGE
web.container_id=$WEB_CID
web.image_id=$ACTUAL_WEB_ID
web.repo_digests=$WEB_REPO_DIGESTS
web.http_canary=pass
EVIDENCE

ln -sfn "$(basename "$EVIDENCE_FILE")" "$EVIDENCE_DIR/latest.txt"
log "Deployment verification passed"
printf '  Git SHA:  %s\n' "$EXPECTED_GIT_SHA"
printf '  Evidence: %s\n' "$EVIDENCE_FILE"
