#!/usr/bin/env bash
# Compatibility entry point retained for existing cron installations.
set -euo pipefail
APP_DIR="${APP_DIR:-/opt/ttli}"
exec "$APP_DIR/scripts/backup-production.sh" "$@"
