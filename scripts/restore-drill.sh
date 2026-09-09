#!/usr/bin/env bash
# Restore the latest encrypted production backup into isolated drill targets.
# Never overwrites the live `ttli` database or any production Garage bucket.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ttli}"
ENV_FILE="${ENV_FILE:-$APP_DIR/.env.prod}"
COMPOSE_FILE="${COMPOSE_FILE:-$APP_DIR/infra/docker-compose.single-vm.yml}"
DRILL_DIR="${DRILL_DIR:-$APP_DIR/backups/drills}"
GARAGE_BACKUP_ENDPOINT="${GARAGE_BACKUP_ENDPOINT:-http://127.0.0.1:9140}"
MAX_RPO_SECONDS="${MAX_RPO_SECONDS:-900}"
MAX_RTO_SECONDS="${MAX_RTO_SECONDS:-28800}"

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
env_value() { awk -F= -v key="$1" '$1 == key {sub(/^[^=]*=/, ""); print; exit}' "$ENV_FILE"; }
need() { command -v "$1" >/dev/null 2>&1 || die "$1 is required"; }
[ -f "$ENV_FILE" ] || die "$ENV_FILE not found"
need docker
need rclone
need sha256sum
need mktemp

BACKUP_RCLONE_REMOTE="${BACKUP_RCLONE_REMOTE:-$(env_value BACKUP_RCLONE_REMOTE)}"
BACKUP_OWNER="${BACKUP_OWNER:-$(env_value BACKUP_OWNER)}"
S3_ACCESS_KEY="${S3_ACCESS_KEY:-$(env_value S3_ACCESS_KEY)}"
S3_SECRET_KEY="${S3_SECRET_KEY:-$(env_value S3_SECRET_KEY)}"
S3_REGION="${S3_REGION:-$(env_value S3_REGION)}"
[ -n "$BACKUP_RCLONE_REMOTE" ] || die "BACKUP_RCLONE_REMOTE is required"
[ -n "$BACKUP_OWNER" ] || die "BACKUP_OWNER is required"
[[ "$BACKUP_RCLONE_REMOTE" =~ ^[^[:space:]=:]+:[^[:space:]=]+$ ]] \
  || die "BACKUP_RCLONE_REMOTE must be remote:path with no whitespace or '='"
[[ "$BACKUP_OWNER" =~ ^[A-Za-z0-9][A-Za-z0-9._@+-]{2,127}$ ]] \
  || die "BACKUP_OWNER must be a 3-128 character operator ID or email without spaces"
[[ "$MAX_RPO_SECONDS" =~ ^[0-9]+$ ]] || die "MAX_RPO_SECONDS must be an integer"
[[ "$MAX_RTO_SECONDS" =~ ^[0-9]+$ ]] || die "MAX_RTO_SECONDS must be an integer"
REMOTE_NAME="${BACKUP_RCLONE_REMOTE%%:*}"
rclone config show "$REMOTE_NAME" | grep -Eq '^type = crypt$' \
  || die "BACKUP_RCLONE_REMOTE must name an rclone crypt remote"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
STARTED="$(date +%s)"
DRILL_DB="ttli_restore_${STAMP,,}"
DRILL_DB="${DRILL_DB//[^a-z0-9_]/_}"
DRILL_BUCKET="ttli-restore-drill-${STAMP,,}"
mkdir -p "$DRILL_DIR"
WORK_DIR="$(mktemp -d "$DRILL_DIR/work-$STAMP-XXXX")"
REPORT="$DRILL_DIR/restore-drill-$STAMP.txt"

cleanup() {
  docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T postgres \
    dropdb -U ttli --if-exists "$DRILL_DB" >/dev/null 2>&1 || true
  rclone purge "garage:$DRILL_BUCKET" >/dev/null 2>&1 || true
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

LATEST="$(rclone lsf "$BACKUP_RCLONE_REMOTE/database" --files-only \
  | grep -E '^ttli-[0-9]{8}T[0-9]{6}Z\.dump$' | sort | tail -n1)"
[ -n "$LATEST" ] || die "no database archive found"
BACKUP_STAMP="${LATEST#ttli-}"
BACKUP_STAMP="${BACKUP_STAMP%.dump}"
BACKUP_EPOCH="$(date -u -d "${BACKUP_STAMP:0:8} ${BACKUP_STAMP:9:2}:${BACKUP_STAMP:11:2}:${BACKUP_STAMP:13:2}Z" +%s)"
RPO_SECONDS="$((STARTED - BACKUP_EPOCH))"
(( RPO_SECONDS >= 0 )) || die "latest backup timestamp is in the future; check host clock"

rclone copyto "$BACKUP_RCLONE_REMOTE/database/$LATEST" "$WORK_DIR/$LATEST"
rclone copyto "$BACKUP_RCLONE_REMOTE/database/$LATEST.sha256" "$WORK_DIR/$LATEST.sha256"
(cd "$WORK_DIR" && sha256sum -c "$LATEST.sha256")

docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T postgres \
  createdb -U ttli -T template0 "$DRILL_DB"
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T postgres \
  pg_restore -U ttli --exit-on-error -d "$DRILL_DB" < "$WORK_DIR/$LATEST"

TABLES="$(docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T postgres \
  psql -U ttli -d "$DRILL_DB" -Atc "SELECT count(*) FROM pg_tables WHERE schemaname='public'")"
RLS_TABLES="$(docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T postgres \
  psql -U ttli -d "$DRILL_DB" -Atc "SELECT count(*) FROM pg_class WHERE relnamespace='public'::regnamespace AND relrowsecurity AND relforcerowsecurity")"
MIGRATION="$(docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T postgres \
  psql -U ttli -d "$DRILL_DB" -Atc 'SELECT version_num FROM alembic_version')"
(( TABLES > 0 )) || die "restored database contains no public tables"
(( RLS_TABLES > 0 )) || die "restored database contains no forced-RLS tables"

export RCLONE_CONFIG_GARAGE_TYPE=s3
export RCLONE_CONFIG_GARAGE_PROVIDER=Other
export RCLONE_CONFIG_GARAGE_ACCESS_KEY_ID="$S3_ACCESS_KEY"
export RCLONE_CONFIG_GARAGE_SECRET_ACCESS_KEY="$S3_SECRET_KEY"
export RCLONE_CONFIG_GARAGE_ENDPOINT="$GARAGE_BACKUP_ENDPOINT"
export RCLONE_CONFIG_GARAGE_REGION="${S3_REGION:-af-south-1}"
rclone mkdir "garage:$DRILL_BUCKET"

SAMPLES=0
for bucket in public-marketing private-content user-uploads generated-documents backups; do
  object="$(rclone lsf "$BACKUP_RCLONE_REMOTE/objects/current/$bucket" --files-only -R | head -n1 || true)"
  [ -n "$object" ] || continue
  rclone copyto "$BACKUP_RCLONE_REMOTE/objects/current/$bucket/$object" \
    "garage:$DRILL_BUCKET/$bucket/$object"
  EXPECTED="$(rclone cat "$BACKUP_RCLONE_REMOTE/objects/current/$bucket/$object" | sha256sum | cut -d' ' -f1)"
  ACTUAL="$(rclone cat "garage:$DRILL_BUCKET/$bucket/$object" | sha256sum | cut -d' ' -f1)"
  [ "$EXPECTED" = "$ACTUAL" ] || die "object restore checksum mismatch for $bucket/$object"
  SAMPLES=$((SAMPLES + 1))
done
(( SAMPLES > 0 )) || die "object backup contains no sample object to restore"

FINISHED="$(date +%s)"
RTO_SECONDS="$((FINISHED - STARTED))"
RPO_RESULT=PASS; (( RPO_SECONDS <= MAX_RPO_SECONDS )) || RPO_RESULT=FAIL
RTO_RESULT=PASS; (( RTO_SECONDS <= MAX_RTO_SECONDS )) || RTO_RESULT=FAIL
cat > "$REPORT" <<EOF
restore_drill_utc=$STAMP
owner=$BACKUP_OWNER
backup_timestamp_utc=$BACKUP_STAMP
rpo_seconds=$RPO_SECONDS
rpo_target_seconds=$MAX_RPO_SECONDS
rpo_result=$RPO_RESULT
rto_seconds=$RTO_SECONDS
rto_target_seconds=$MAX_RTO_SECONDS
rto_result=$RTO_RESULT
database_tables=$TABLES
forced_rls_tables=$RLS_TABLES
alembic_version=$MIGRATION
object_samples_restored=$SAMPLES
database_target=$DRILL_DB
object_target=$DRILL_BUCKET
targets_removed_after_test=true
EOF
rclone copy "$REPORT" "$BACKUP_RCLONE_REMOTE/drills/"
cat "$REPORT"
[ "$RPO_RESULT" = PASS ] || die "RPO target missed"
[ "$RTO_RESULT" = PASS ] || die "RTO target missed"
printf 'Restore drill passed; evidence: %s\n' "$REPORT"
