#!/usr/bin/env bash
# Bring up the bare-minimum TTLI stack for POC/UAT/MVP click-through
# testing on a Raspberry Pi 3B+ (1GB RAM, quad-core Cortex-A53). Bash
# because that's what Raspberry Pi OS actually ships and runs — no
# assumption you're on the dev machine this repo is otherwise built on.
#
# What this deliberately is NOT:
#   - Not production. It sets ENVIRONMENT=local, keeps HTTP, and skips
#     TLS/observability/S3 entirely. Do not point real users or real
#     payment credentials at it.
#   - Not the full app. No ClamAV (see the printed warning below) means
#     every upload endpoint — course video/audio/captions, PO/payment-
#     proof documents, assignment submissions — returns 503. Everything
#     else (catalogue browsing, login, course/lesson/quiz playback,
#     the admin screens, seeded demo content) works.
#
# Usage:
#   scripts/deploy-pi.sh                 # postgres+redis+mailpit+api+web
#   scripts/deploy-pi.sh --with-worker   # + arq worker (email/push/transcode)
#   scripts/deploy-pi.sh --skip-seed     # migrate only, no demo data/logins
#   scripts/deploy-pi.sh --no-swap-check # skip the swap prompt (CI/repeat runs)
#
# Re-running is safe: secrets in .env.pi are generated once and kept
# (same convention as scripts/deploy-single-vm.sh), and every seed
# script is idempotent.
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE_FILE=infra/docker-compose.pi.yml
ENV_FILE=.env.pi
WITH_WORKER=false
SKIP_SEED=false
SWAP_CHECK=true

for arg in "$@"; do
  case "$arg" in
    --with-worker) WITH_WORKER=true ;;
    --skip-seed) SKIP_SEED=true ;;
    --no-swap-check) SWAP_CHECK=false ;;
    *) echo "Unknown argument: $arg" >&2; exit 1 ;;
  esac
done

COMPOSE=(docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE")

echo "=== 1. Hardware sanity check ==="
ARCH="$(uname -m)"
TOTAL_KB="$(awk '/MemTotal/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)"
TOTAL_MB=$((TOTAL_KB / 1024))
echo "Architecture: $ARCH"
echo "Total RAM:    ${TOTAL_MB}MB"
case "$ARCH" in
  aarch64|arm64) ;;
  armv7l|armv6l)
    echo "WARNING: 32-bit ARM userspace detected. This has only been reasoned" >&2
    echo "about for 64-bit Raspberry Pi OS (aarch64) — the base images this" >&2
    echo "profile builds from (python:3.12-slim, node:24-slim) may not publish" >&2
    echo "armv7 variants at all. Strongly prefer 64-bit Raspberry Pi OS." >&2
    read -rp "Continue anyway? [y/N] " reply
    [[ "$reply" =~ ^[Yy]$ ]] || exit 1
    ;;
  *)
    echo "This script targets a Raspberry Pi (aarch64). Detected: $ARCH — not refusing," >&2
    echo "since the same profile runs fine on any small amd64 box too, but the RAM" >&2
    echo "budgeting below assumes a 1GB Pi 3B+ specifically." >&2
    ;;
esac
if [ "$TOTAL_MB" -gt 0 ] && [ "$TOTAL_MB" -lt 900 ]; then
  echo "WARNING: less than 900MB total RAM. This profile budgets ~870MB across" >&2
  echo "containers already; expect swap pressure or OOM kills. See step 2." >&2
fi

echo ""
echo "=== 2. Swap ==="
if [ "$SWAP_CHECK" = true ]; then
  CURRENT_SWAP_KB="$(awk '/SwapTotal/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)"
  CURRENT_SWAP_MB=$((CURRENT_SWAP_KB / 1024))
  echo "Current swap: ${CURRENT_SWAP_MB}MB"
  if [ "$CURRENT_SWAP_MB" -lt 1024 ]; then
    cat <<'NOTE'
Under 1GB of swap on a 1GB board. Six containers sharing 1GB with no
swap will OOM-kill something (most likely Postgres, mid-transaction)
the first time you do anything beyond idling. Two ways to add swap:

  A) dphys-swapfile (Raspberry Pi OS's own tool, if installed):
       sudo dphys-swapfile swapoff
       sudo sed -i 's/^CONF_SWAPSIZE=.*/CONF_SWAPSIZE=2048/' /etc/dphys-swapfile
       sudo dphys-swapfile setup && sudo dphys-swapfile swapon

  B) A plain swapfile, anywhere dphys-swapfile isn't set up:
       sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
       sudo mkswap /swapfile && sudo swapon /swapfile
       echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

Prefer a USB SSD over the SD card for either, if you have one attached
— swapping to an SD card works but wears it out faster, and SD cards are
already this board's slowest component. This script does not do either
of these for you (they need sudo and touch persistent system files);
run one, then re-run this script.
NOTE
    read -rp "Continue without adequate swap anyway? [y/N] " reply
    [[ "$reply" =~ ^[Yy]$ ]] || exit 1
  fi
else
  echo "(skipped: --no-swap-check)"
fi

echo ""
echo "=== 3. Docker ==="
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker not found."
  read -rp "Install it now via https://get.docker.com ? [y/N] " reply
  if [[ "$reply" =~ ^[Yy]$ ]]; then
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker "$USER"
    echo "Docker installed. Log out and back in (or run 'newgrp docker'), then re-run this script."
    exit 0
  else
    echo "Docker is required. Exiting." >&2
    exit 1
  fi
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "docker compose (the v2 plugin) is required but not found. Raspberry Pi OS's" >&2
  echo "own Docker packages include it; get.docker.com's convenience script does too." >&2
  exit 1
fi
echo "docker: $(docker --version)"
echo "compose: $(docker compose version --short 2>/dev/null || docker compose version)"

echo ""
echo "=== 4. Secrets (.env.pi) ==="
b64rand() { openssl rand -base64 "$1" | tr -d '\n'; }
if [ -f "$ENV_FILE" ]; then
  echo "$ENV_FILE already exists — keeping it as-is (never regenerated once written,"
  echo "same rule scripts/deploy-single-vm.sh follows: a rotated FIELD_ENCRYPTION_KEY"
  echo "makes every previously-encrypted row unreadable)."
  # shellcheck disable=SC1090
  source "$ENV_FILE"
else
  SECRET_KEY="$(b64rand 48)"
  FIELD_ENCRYPTION_KEY="$(b64rand 32)"
  BLIND_INDEX_KEY="$(b64rand 32)"
  while [ "$FIELD_ENCRYPTION_KEY" = "$BLIND_INDEX_KEY" ]; do
    BLIND_INDEX_KEY="$(b64rand 32)"
  done
  APP_DB_PASSWORD="$(b64rand 24 | tr -d '=+/')"
  POSTGRES_SUPERUSER_PASSWORD="$(b64rand 24 | tr -d '=+/')"
  BREAK_GLASS_ADMIN_PASSWORD="$(b64rand 18 | tr -d '=+/')"
  cat > "$ENV_FILE" <<EOF
# Generated by scripts/deploy-pi.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ). Not
# meant to be hand-edited beyond CLAMAV_HOST/PUBLIC_WEB_URL/API_PUBLIC_URL
# (see infra/docker-compose.pi.yml's own comments) — everything else here
# is a generated secret this script will not overwrite on a re-run.
SECRET_KEY=$SECRET_KEY
FIELD_ENCRYPTION_KEY=$FIELD_ENCRYPTION_KEY
BLIND_INDEX_KEY=$BLIND_INDEX_KEY
APP_DB_PASSWORD=$APP_DB_PASSWORD
POSTGRES_SUPERUSER_PASSWORD=$POSTGRES_SUPERUSER_PASSWORD
BREAK_GLASS_ADMIN_EMAIL=admin@ttli.example
BREAK_GLASS_ADMIN_PASSWORD=$BREAK_GLASS_ADMIN_PASSWORD
# Uncomment and point at a real host if upload-dependent flows matter for
# your UAT pass and you're running ClamAV somewhere else on the LAN:
# CLAMAV_HOST=192.168.1.x
EOF
  chmod 600 "$ENV_FILE"
  echo "Wrote $ENV_FILE (mode 600). Break-glass admin: admin@ttli.example / $BREAK_GLASS_ADMIN_PASSWORD"
fi

echo ""
echo "=== 5. Build ==="
"${COMPOSE[@]}" build

echo ""
echo "=== 6. Infra services (postgres, redis, mailpit) ==="
"${COMPOSE[@]}" up -d postgres redis mailpit
echo -n "waiting for postgres/redis"
for svc in postgres redis; do
  until [ "$("${COMPOSE[@]}" ps -q "$svc" | xargs -r docker inspect -f '{{.State.Health.Status}}' 2>/dev/null)" = "healthy" ]; do
    echo -n .
    sleep 3
  done
done
echo " ok"

echo ""
echo "=== 7. Migrate ==="
"${COMPOSE[@]}" run --rm migrate

echo ""
echo "=== 8. Application ==="
if [ "$WITH_WORKER" = true ]; then
  echo "Starting api, web and worker (--with-worker)."
  "${COMPOSE[@]}" --profile worker up -d api web worker
else
  echo "Starting api and web. Worker skipped — no email/push/transcode will"
  echo "actually send/run; jobs queue in Redis instead. Re-run with"
  echo "--with-worker to also start it (budget ~180MB more RAM for it)."
  "${COMPOSE[@]}" up -d api web
fi
echo -n "waiting for api/web"
for svc in api web; do
  until [ "$("${COMPOSE[@]}" ps -q "$svc" | xargs -r docker inspect -f '{{.State.Health.Status}}' 2>/dev/null)" = "healthy" ]; do
    echo -n .
    sleep 3
  done
done
echo " ok"

if [ "$SKIP_SEED" = false ]; then
  echo ""
  echo "=== 9. Seed demo data ==="
  "${COMPOSE[@]}" exec -T api python scripts/seed_e2e_accounts.py
  # seed_demo_content.py / seed_demo_enrolment.py deliberately NOT run
  # here — verified broken against the current schema independent of
  # this Pi profile (seed_demo_content.py passes Lesson(activity_type=…),
  # a field that model no longer has since the block-based lesson
  # content builder migration; seed_demo_enrolment.py then fails too,
  # since it depends on a course seed_demo_content.py never finishes
  # creating). A pre-existing repo issue, not something this script
  # papers over — fix seed_demo_content.py upstream, then add both
  # calls back here. Until then the catalogue only has whatever
  # coursework you create by hand through the UI/API.
else
  echo ""
  echo "=== 9. Seed demo data (skipped: --skip-seed) ==="
fi

PI_IP="$(hostname -I 2>/dev/null | awk '{print $1}')" || PI_IP=""
PI_IP="${PI_IP:-<this device LAN IP>}"
cat <<SUMMARY

=== Up ===
Web:      http://${PI_IP}:3010   (or http://localhost:3010 from the Pi itself)
API docs: http://${PI_IP}:8010/docs
Mailpit:  http://${PI_IP}:8025   (every outbound email lands here, nothing leaves the box)

Break-glass admin: ${BREAK_GLASS_ADMIN_EMAIL:-see} / ${BREAK_GLASS_ADMIN_PASSWORD:-$ENV_FILE} ($ENV_FILE has the source of truth)
$([ "$SKIP_SEED" = false ] && echo "Seeded UAT logins: ops-admin@example.com / SmokeTest123!admin (super_admin), smoke-agent@example.com / SmokeTest123!agent (learner) — see apps/api/scripts/seed_e2e_accounts.py for the full list.")

Known gaps in this profile (see infra/docker-compose.pi.yml's header):
  - No ClamAV: any upload (course video/audio/captions, PO/payment-proof
    documents, assignment submissions) returns 503.
  - Worker $([ "$WITH_WORKER" = true ] && echo "is running" || echo "is not running") — email/push/transcode $([ "$WITH_WORKER" = true ] && echo "work" || echo "queue but never send/run").
  - No TLS — LAN-only HTTP, plain-text traffic. Don't expose this port to the internet.
  - No demo course content: scripts/seed_demo_content.py currently errors
    against the current schema (Lesson has no activity_type field any
    more) independent of this profile — a pre-existing repo issue, not
    something this script works around. The demo tenant has logins but
    an empty catalogue until you author a course by hand or that script
    is fixed upstream.

Tear down: docker compose -f $COMPOSE_FILE --env-file $ENV_FILE down
Wipe everything (including seeded data): add -v to that command.
SUMMARY
