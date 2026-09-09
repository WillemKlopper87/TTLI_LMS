#!/usr/bin/env bash
# Encrypted database + Garage backup for the single-VM topology. Cron runs it
# every 10 minutes so a completed backup can stay within the 15-minute RPO.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ttli}"
ENV_FILE="${ENV_FILE:-$APP_DIR/.env.prod}"
COMPOSE_FILE="${COMPOSE_FILE:-$APP_DIR/infra/docker-compose.single-vm.yml}"
BACKUP_DIR="${BACKUP_DIR:-$APP_DIR/backups}"
GARAGE_BACKUP_ENDPOINT="${GARAGE_BACKUP_ENDPOINT:-http://127.0.0.1:9140}"

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
env_value() { awk -F= -v key="$1" '$1 == key {sub(/^[^=]*=/, ""); print; exit}' "$ENV_FILE"; }
need() { command -v "$1" >/dev/null 2>&1 || die "$1 is required"; }

[ -f "$ENV_FILE" ] || die "$ENV_FILE not found"
need docker
need rclone
need sha256sum
need flock

BACKUP_RCLONE_REMOTE="${BACKUP_RCLONE_REMOTE:-$(env_value BACKUP_RCLONE_REMOTE)}"
BACKUP_OWNER="${BACKUP_OWNER:-$(env_value BACKUP_OWNER)}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-$(env_value BACKUP_RETENTION_DAYS)}"
S3_ACCESS_KEY="${S3_ACCESS_KEY:-$(env_value S3_ACCESS_KEY)}"
S3_SECRET_KEY="${S3_SECRET_KEY:-$(env_value S3_SECRET_KEY)}"
S3_REGION="${S3_REGION:-$(env_value S3_REGION)}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"

[ -n "$BACKUP_RCLONE_REMOTE" ] || die "BACKUP_RCLONE_REMOTE is required"
[ -n "$BACKUP_OWNER" ] || die "BACKUP_OWNER is required"
[[ "$BACKUP_RCLONE_REMOTE" =~ ^[^[:space:]=:]+:[^[:space:]=]+$ ]] \
  || die "BACKUP_RCLONE_REMOTE must be remote:path with no whitespace or '='"
[[ "$BACKUP_OWNER" =~ ^[A-Za-z0-9][A-Za-z0-9._@+-]{2,127}$ ]] \
  || die "BACKUP_OWNER must be a 3-128 character operator ID or email without spaces"
[ -n "$S3_ACCESS_KEY" ] || die "S3_ACCESS_KEY is required"
[ -n "$S3_SECRET_KEY" ] || die "S3_SECRET_KEY is required"
[[ "$BACKUP_RETENTION_DAYS" =~ ^[0-9]+$ ]] || die "BACKUP_RETENTION_DAYS must be an integer"
(( BACKUP_RETENTION_DAYS >= 7 && BACKUP_RETENTION_DAYS <= 30 )) \
  || die "BACKUP_RETENTION_DAYS must be between 7 and 30"

# Both database and object backups must traverse an rclone crypt remote.
# This checks the named destination without printing its obscured password.
REMOTE_NAME="${BACKUP_RCLONE_REMOTE%%:*}"
rclone config show "$REMOTE_NAME" | grep -Eq '^type = crypt$' \
  || die "BACKUP_RCLONE_REMOTE must name an rclone crypt remote"

mkdir -p "$BACKUP_DIR"
exec 9>"$BACKUP_DIR/.backup.lock"
flock -n 9 || die "another backup is already running"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
STARTED="$(date +%s)"
DUMP="$BACKUP_DIR/ttli-$STAMP.dump"
CHECKSUM="$DUMP.sha256"
MANIFEST="$BACKUP_DIR/ttli-$STAMP.manifest"
trap 'rm -f "$DUMP.tmp"' EXIT

printf '[%s] creating PostgreSQL custom-format archive\n' "$STAMP"
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T postgres \
  pg_dump -U ttli -d ttli -Fc > "$DUMP.tmp"
[ -s "$DUMP.tmp" ] || die "pg_dump produced an empty archive"
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T postgres \
  pg_restore --list < "$DUMP.tmp" >/dev/null
mv "$DUMP.tmp" "$DUMP"
(cd "$BACKUP_DIR" && sha256sum "$(basename "$DUMP")" > "$(basename "$CHECKSUM")")

# The host reaches Garage only through its loopback-only production port.
# Environment-defined rclone remotes avoid writing the Garage secret to a
# config file or command-line argument.
export RCLONE_CONFIG_GARAGE_TYPE=s3
export RCLONE_CONFIG_GARAGE_PROVIDER=Other
export RCLONE_CONFIG_GARAGE_ACCESS_KEY_ID="$S3_ACCESS_KEY"
export RCLONE_CONFIG_GARAGE_SECRET_ACCESS_KEY="$S3_SECRET_KEY"
export RCLONE_CONFIG_GARAGE_ENDPOINT="$GARAGE_BACKUP_ENDPOINT"
export RCLONE_CONFIG_GARAGE_REGION="${S3_REGION:-af-south-1}"

BUCKETS=(public-marketing private-content user-uploads generated-documents backups)
for bucket in "${BUCKETS[@]}"; do
  printf '[%s] syncing Garage bucket %s\n' "$STAMP" "$bucket"
  rclone mkdir "garage:$bucket"
  rclone lsd "garage:$bucket" >/dev/null
  rclone sync "garage:$bucket" "$BACKUP_RCLONE_REMOTE/objects/current/$bucket" \
    --backup-dir "$BACKUP_RCLONE_REMOTE/objects/versions/$STAMP/$bucket" \
    --checkers 8 --transfers 4
done

FINISHED="$(date +%s)"
POSTGRES_CONTAINER="$(docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" ps -q postgres)"
[ -n "$POSTGRES_CONTAINER" ] || die "PostgreSQL container is not running"
POSTGRES_IMAGE="$(docker inspect --format '{{if .RepoDigests}}{{index .RepoDigests 0}}{{else}}{{.Config.Image}}{{end}}' "$POSTGRES_CONTAINER")"
cat > "$MANIFEST" <<EOF
timestamp_utc=$STAMP
owner=$BACKUP_OWNER
git_sha=$(git -C "$APP_DIR" rev-parse HEAD 2>/dev/null || printf unknown)
postgres_image=$POSTGRES_IMAGE
database_archive=$(basename "$DUMP")
database_sha256=$(cut -d' ' -f1 "$CHECKSUM")
object_buckets=${BUCKETS[*]}
duration_seconds=$((FINISHED - STARTED))
retention_days=$BACKUP_RETENTION_DAYS
encryption=rclone-crypt
EOF

printf '[%s] uploading database archive, checksum, and manifest\n' "$STAMP"
for artifact in "$DUMP" "$CHECKSUM" "$MANIFEST"; do
  rclone copy "$artifact" "$BACKUP_RCLONE_REMOTE/database/"
done

# Prune by the timestamp embedded in names, not object mtime: rclone's
# --backup-dir preserves the original object's mtime, which may be years old.
CUTOFF="$(date -u -d "$BACKUP_RETENTION_DAYS days ago" +%Y%m%dT%H%M%SZ)"
while IFS= read -r snapshot; do
  snapshot="${snapshot%/}"
  [[ "$snapshot" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || continue
  [[ "$snapshot" < "$CUTOFF" ]] && rclone purge "$BACKUP_RCLONE_REMOTE/objects/versions/$snapshot"
done < <(rclone lsf "$BACKUP_RCLONE_REMOTE/objects/versions" --dirs-only 2>/dev/null || true)

while IFS= read -r file; do
  if [[ "$file" =~ ^ttli-([0-9]{8}T[0-9]{6}Z)\.(dump|dump\.sha256|manifest)$ ]] \
     && [[ "${BASH_REMATCH[1]}" < "$CUTOFF" ]]; then
    rclone deletefile "$BACKUP_RCLONE_REMOTE/database/$file"
  fi
done < <(rclone lsf "$BACKUP_RCLONE_REMOTE/database" --files-only 2>/dev/null || true)

find "$BACKUP_DIR" -type f \( -name 'ttli-*.dump' -o -name 'ttli-*.dump.sha256' -o -name 'ttli-*.manifest' \) -mtime +1 -delete
printf '[%s] backup complete in %ss; encrypted remote: %s; owner: %s\n' \
  "$STAMP" "$((FINISHED - STARTED))" "$BACKUP_RCLONE_REMOTE" "$BACKUP_OWNER"
