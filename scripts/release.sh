#!/usr/bin/env bash
# Canonical production release entry point.
#
# rolling-update.sh performs the migration and service swaps/rollback logic.
# verify-deployment.sh then proves the resulting release is actually usable:
# API readiness, worker heartbeat, web response, exact image identity and
# baked Git SHA are all checked and recorded as deployment evidence.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

"$SCRIPT_DIR/rolling-update.sh"
"$SCRIPT_DIR/verify-deployment.sh"
