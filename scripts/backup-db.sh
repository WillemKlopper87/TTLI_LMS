#!/usr/bin/env bash
# Nightly Postgres backup for the single-VM deployment — cron-installed by
# deploy-single-vm.sh. Ships the dump OFF this VM: a backup that lives on
# the same disk as the database it's backing up isn't a backup, it's a
# second copy of the same single point of failure. Configure
# BACKUP_RCLONE_REMOTE (an rclone remote name pointing at Azure Blob, S3,
# Backblaze B2 — anything rclone supports) in /opt/ttli/.env.prod; running
# without it is refused rather than silently keeping local-only copies
# nobody notices are useless until the VM is gone.
#
# 06_OPERATIONS.md §5.4 targets: RPO 15 minutes, retention 7-30 days.
# Nightly cron only gets you a 24h RPO on this tier — say so in the doc,
# don't pretend otherwise.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ttli}"
ENV_FILE="$APP_DIR/.env.prod"
BACKUP_DIR="${BACKUP_DIR:-/opt/ttli/backups}"
KEEP_LOCAL_DAYS="${KEEP_LOCAL_DAYS:-3}"

if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: $ENV_FILE not found" >&2
  exit 1
fi
# Extracted, not sourced: this file also holds SMTP/Payfast credentials a
# human typed in at deploy time, and this script runs unattended every
# night with no one watching stdout for something that looks wrong — not
# the place to eval arbitrary file content for the one value actually
# needed here.
BACKUP_RCLONE_REMOTE="$(grep -E '^BACKUP_RCLONE_REMOTE=' "$ENV_FILE" | head -n1 | cut -d= -f2-)"

if [ -z "${BACKUP_RCLONE_REMOTE:-}" ]; then
  echo "ERROR: BACKUP_RCLONE_REMOTE is not set in $ENV_FILE — refusing to" >&2
  echo "       take a backup that would only ever live on this VM." >&2
  exit 1
fi

if ! command -v rclone >/dev/null 2>&1; then
  echo "ERROR: rclone is not installed. deploy-single-vm.sh installs it;" >&2
  echo "       if you're running this by hand, install rclone first." >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DUMP_FILE="$BACKUP_DIR/ttli-$STAMP.sql.gz"

echo "[$STAMP] dumping database..."
# -Fc would need pg_restore's own tooling on the far end to inspect; a
# plain SQL dump piped through gzip can be eyeballed or restored with
# nothing but psql, which matters more than dump size at this scale.
docker compose -f "$APP_DIR/infra/docker-compose.single-vm.yml" exec -T postgres \
  pg_dump -U ttli -d ttli | gzip > "$DUMP_FILE"

SIZE="$(du -h "$DUMP_FILE" | cut -f1)"
echo "[$STAMP] dumped $SIZE, uploading to $BACKUP_RCLONE_REMOTE..."
rclone copy "$DUMP_FILE" "$BACKUP_RCLONE_REMOTE/ttli-db-backups/"

echo "[$STAMP] pruning local copies older than $KEEP_LOCAL_DAYS days..."
find "$BACKUP_DIR" -name 'ttli-*.sql.gz' -mtime "+$KEEP_LOCAL_DAYS" -delete

echo "[$STAMP] done: $DUMP_FILE ($SIZE) -> $BACKUP_RCLONE_REMOTE/ttli-db-backups/"
