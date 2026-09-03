#!/usr/bin/env bash
# Prepare a fresh Ubuntu/Debian cloud VM and deploy the whole TTLI stack
# onto it: Docker, firewall, the app + its infra containers (Postgres,
# Redis, Garage, ClamAV, an SMTP relay) behind Caddy, plus a nightly
# off-VM backup cron job. See docs/research/single-vm-deployment.md for
# the architecture this implements and the tradeoffs against the
# documented Azure Container Apps target (docs/06_OPERATIONS.md §4.2).
#
# Usage (as a user with sudo, on the target VM):
#   sudo -E ./scripts/deploy-single-vm.sh
#
# Idempotent by design where it matters: re-running after the first
# successful deploy will NOT regenerate FIELD_ENCRYPTION_KEY/
# BLIND_INDEX_KEY/APP_DB_PASSWORD if .env.prod already exists — doing so
# would make every already-encrypted database row permanently
# unreadable. Re-running pulls the latest image build and restarts
# services; it does not touch secrets.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ttli}"
REPO_URL="${REPO_URL:-}"
COMPOSE_FILE="infra/docker-compose.single-vm.yml"
ENV_FILE="$APP_DIR/.env.prod"

log()  { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run as root (sudo -E $0) — installs system packages and writes to $APP_DIR"

# --------------------------------------------------------------------
# 1. System packages: Docker Engine + Compose plugin, ufw, rclone,
#    openssl (secret generation).
# --------------------------------------------------------------------
log "Installing system packages"
apt-get update -qq
apt-get install -y --no-install-recommends \
  ca-certificates curl gnupg ufw rclone openssl git >/dev/null

if ! command -v docker >/dev/null 2>&1; then
  log "Installing Docker Engine"
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  ARCH="$(dpkg --print-architecture)"
  CODENAME="$(. /etc/os-release && echo "$VERSION_CODENAME")"
  echo "deb [arch=$ARCH signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $CODENAME stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y --no-install-recommends \
    docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null
  systemctl enable --now docker
else
  log "Docker already installed, skipping"
fi

# --------------------------------------------------------------------
# 2. Firewall: only SSH, HTTP, HTTPS reach this VM from outside. Every
#    app/infra container talks over the internal Docker network — see
#    the compose file's own note on why that's also what keeps
#    check_production_safety() satisfied.
# --------------------------------------------------------------------
log "Configuring firewall (22, 80, 443 only)"
ufw allow 22/tcp   >/dev/null
ufw allow 80/tcp   >/dev/null
ufw allow 443/tcp  >/dev/null
ufw --force enable >/dev/null
ufw status verbose

# --------------------------------------------------------------------
# 3. The repo itself. If this script is already being run from inside a
#    checked-out repo (the common path — you SSH in, clone once, run
#    this), use that. Otherwise clone REPO_URL into APP_DIR.
# --------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$SCRIPT_DIR/infra/docker-compose.single-vm.yml" ]; then
  log "Using existing checkout at $SCRIPT_DIR"
  APP_DIR="$SCRIPT_DIR"
  ENV_FILE="$APP_DIR/.env.prod"
elif [ -d "$APP_DIR/.git" ]; then
  log "Updating existing checkout at $APP_DIR"
  git -C "$APP_DIR" pull --ff-only
else
  [ -n "$REPO_URL" ] || die "no repo at $SCRIPT_DIR and REPO_URL is not set — either run this from inside a checkout, or: REPO_URL=git@... $0"
  log "Cloning $REPO_URL into $APP_DIR"
  git clone "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

# --------------------------------------------------------------------
# 4. Secrets and configuration. Only generated once, ever — see the
#    header note on why re-running must not touch an existing .env.prod.
# --------------------------------------------------------------------
b64rand() { openssl rand -base64 "$1" | tr -d '\n'; }
hexrand() { openssl rand -hex "$1"; }

if [ -f "$ENV_FILE" ]; then
  log "$ENV_FILE already exists — leaving secrets untouched"
  # shellcheck disable=SC1090
  set -a; source "$ENV_FILE"; set +a
else
  log "First run: collecting configuration"
  echo "Leave a prompt blank to accept the [default] shown."
  read -rp "Domain this VM will serve, e.g. app.example.com: " DOMAIN
  [ -n "$DOMAIN" ] || die "a domain is required — Caddy's automatic HTTPS needs one, and Payfast/certificate QR codes embed it as an absolute URL"

  read -rp "Sentry DSN (required — the API refuses to start without one): " SENTRY_DSN
  [ -n "$SENTRY_DSN" ] || die "SENTRY_DSN is required by check_production_safety() — create a project at sentry.io (or self-hosted) first"

  echo
  echo "SMTP relay (services/email.py sends unauthenticated SMTP only — this"
  echo "VM's postfix-relay container authenticates outward on its behalf)."
  read -rp "  Relay host:port, e.g. [smtp.sendgrid.net]:587 : " SMTP_RELAY_HOST
  read -rp "  Relay username: " SMTP_RELAY_USERNAME
  read -rsp "  Relay password: " SMTP_RELAY_PASSWORD; echo
  read -rp "  From address, e.g. no-reply@$DOMAIN: " EMAIL_FROM
  EMAIL_FROM="${EMAIL_FROM:-no-reply@$DOMAIN}"

  echo
  echo "Container registry (CI builds, scans, signs and pushes images to GHCR --"
  echo "TTLI_Audit_Report_2026-09-02.md M3 -- this VM only ever pulls by digest,"
  echo "never builds, on releases shipped via scripts/rolling-update.sh)."
  read -rp "  GHCR namespace [ghcr.io/willemklopper87/ttli_lms]: " REGISTRY
  REGISTRY="${REGISTRY:-ghcr.io/willemklopper87/ttli_lms}"
  read -rp "  GitHub username the pull token belongs to: " GHCR_USERNAME
  [ -n "$GHCR_USERNAME" ] || die "GHCR_USERNAME is required -- rolling-update.sh authenticates to GHCR with it"
  read -rsp "  Fine-grained PAT, packages:read only, scoped to this repo: " GHCR_PAT; echo
  [ -n "$GHCR_PAT" ] || die "GHCR_PAT is required -- create one at https://github.com/settings/personal-access-tokens/new"

  echo
  echo "Off-VM backup destination (rclone remote, e.g. an rclone-configured"
  echo "Azure Blob/S3/B2 bucket — run 'rclone config' separately if you"
  echo "haven't already). Leave blank to skip backups for now (not recommended)."
  read -rp "  rclone remote, e.g. myazure:ttli-backups : " BACKUP_RCLONE_REMOTE

  echo
  echo "Payfast (optional — leave blank to keep card checkout disabled, EFT/PO still work):"
  read -rp "  Merchant ID: " PAYFAST_MERCHANT_ID
  read -rp "  Merchant key: " PAYFAST_MERCHANT_KEY
  read -rsp "  Passphrase: " PAYFAST_PASSPHRASE; echo

  log "Generating secrets"
  SECRET_KEY="$(b64rand 48)"
  FIELD_ENCRYPTION_KEY="$(b64rand 32)"
  BLIND_INDEX_KEY="$(b64rand 32)"
  # Regenerate on the rare collision rather than ship two identical keys —
  # check_production_safety() refuses to start if they match.
  while [ "$FIELD_ENCRYPTION_KEY" = "$BLIND_INDEX_KEY" ]; do
    BLIND_INDEX_KEY="$(b64rand 32)"
  done
  POSTGRES_SUPERUSER_PASSWORD="$(b64rand 24)"
  APP_DB_PASSWORD="$(b64rand 24)"
  REDIS_PASSWORD="$(b64rand 24)"
  # Garage's own key format, not arbitrary — GK + 24 hex, then 64 hex
  # (infra/docker-compose.yml's own comment on this exact constraint).
  S3_ACCESS_KEY="GK$(hexrand 12)"
  S3_SECRET_KEY="$(hexrand 32)"
  GARAGE_RPC_SECRET="$(hexrand 32)"
  GARAGE_ADMIN_TOKEN="$(hexrand 24)"

  cat > "$ENV_FILE" <<EOF
# Generated $(date -u +%FT%TZ) by scripts/deploy-single-vm.sh.
# DO NOT regenerate FIELD_ENCRYPTION_KEY/BLIND_INDEX_KEY/APP_DB_PASSWORD
# after real data exists — doing so makes existing encrypted rows and
# the database password permanently wrong. Back this file up somewhere
# other than this VM (a password manager, Key Vault) — it's the one
# file that turns a fresh checkout back into this exact deployment.

DOMAIN=$DOMAIN
PUBLIC_WEB_URL=https://$DOMAIN
API_PUBLIC_URL=https://$DOMAIN

SECRET_KEY=$SECRET_KEY
FIELD_ENCRYPTION_KEY=$FIELD_ENCRYPTION_KEY
BLIND_INDEX_KEY=$BLIND_INDEX_KEY

POSTGRES_SUPERUSER_PASSWORD=$POSTGRES_SUPERUSER_PASSWORD
APP_DB_PASSWORD=$APP_DB_PASSWORD
DATABASE_URL=postgresql+asyncpg://app_user:$APP_DB_PASSWORD@postgres:5432/ttli
DATABASE_URL_SYNC=postgresql+psycopg2://ttli:$POSTGRES_SUPERUSER_PASSWORD@postgres:5432/ttli

REDIS_PASSWORD=$REDIS_PASSWORD
REDIS_URL=redis://:$REDIS_PASSWORD@redis:6379/0

S3_ACCESS_KEY=$S3_ACCESS_KEY
S3_SECRET_KEY=$S3_SECRET_KEY
GARAGE_RPC_SECRET=$GARAGE_RPC_SECRET
GARAGE_ADMIN_TOKEN=$GARAGE_ADMIN_TOKEN

REGISTRY=$REGISTRY
GHCR_USERNAME=$GHCR_USERNAME
GHCR_PAT=$GHCR_PAT

SENTRY_DSN=$SENTRY_DSN

SMTP_RELAY_HOST=$SMTP_RELAY_HOST
SMTP_RELAY_USERNAME=$SMTP_RELAY_USERNAME
SMTP_RELAY_PASSWORD=$SMTP_RELAY_PASSWORD
EMAIL_FROM=$EMAIL_FROM

BACKUP_RCLONE_REMOTE=$BACKUP_RCLONE_REMOTE

PAYFAST_MERCHANT_ID=$PAYFAST_MERCHANT_ID
PAYFAST_MERCHANT_KEY=$PAYFAST_MERCHANT_KEY
PAYFAST_PASSPHRASE=$PAYFAST_PASSPHRASE
PAYFAST_SANDBOX=true
EOF
  chmod 600 "$ENV_FILE"
  # shellcheck disable=SC1090
  set -a; source "$ENV_FILE"; set +a

  if [ -z "$BACKUP_RCLONE_REMOTE" ]; then
    warn "No backup remote configured — this deployment has NO database backups."
    warn "Add BACKUP_RCLONE_REMOTE to $ENV_FILE and re-run this script once you have one."
  fi
fi

# --------------------------------------------------------------------
# 5. DNS sanity check. Caddy's automatic HTTPS will fail (silently, on
#    its own retry loop) if the domain doesn't already resolve here —
#    catch that now with a clear message instead of a confusing first
#    request timeout.
# --------------------------------------------------------------------
log "Checking DNS for $DOMAIN"
VM_IP="$(curl -fsS https://ifconfig.me || curl -fsS https://api.ipify.org || true)"
RESOLVED_IP="$(getent hosts "$DOMAIN" | awk '{print $1}' | head -n1 || true)"
if [ -n "$VM_IP" ] && [ -n "$RESOLVED_IP" ] && [ "$VM_IP" != "$RESOLVED_IP" ]; then
  warn "$DOMAIN resolves to $RESOLVED_IP, this VM is $VM_IP."
  warn "Caddy will not obtain a TLS certificate until the A record points here."
  warn "Continuing anyway — fix DNS and Caddy will pick up the cert on its own retry."
fi

# --------------------------------------------------------------------
# 6. Generate the Garage config from the secrets above (never the
#    checked-in infra/garage/garage.toml, which is a published dev-only
#    secret). Regenerated every run — it holds no data itself, only
#    points at the two volumes that do. Gitignored (infra/garage.toml),
#    distinct from the checked-in infra/garage/garage.toml the local
#    dev compose file uses.
# --------------------------------------------------------------------
log "Writing infra/garage.toml"
cat > infra/garage.toml <<EOF
metadata_dir = "/var/lib/garage/meta"
data_dir = "/var/lib/garage/data"
db_engine = "lmdb"
replication_factor = 1
rpc_bind_addr = "[::]:3901"
rpc_public_addr = "127.0.0.1:3901"
rpc_secret = "$GARAGE_RPC_SECRET"

[s3_api]
s3_region = "af-south-1"
api_bind_addr = "[::]:3900"
root_domain = ".s3.garage.internal"

[admin]
api_bind_addr = "[::]:3903"
admin_token = "$GARAGE_ADMIN_TOKEN"
EOF

# --------------------------------------------------------------------
# 7. Caddyfile with the real domain substituted. Safe to regenerate
#    every run — no secrets live in it. Generated into infra/Caddyfile
#    (gitignored) from the checked-in infra/Caddyfile.template, so a
#    later `git pull` never fights with or reverts this VM's real config.
# --------------------------------------------------------------------
log "Writing infra/Caddyfile for $DOMAIN"
sed "s/{DOMAIN}/$DOMAIN/g" infra/Caddyfile.template > infra/Caddyfile

# --------------------------------------------------------------------
# 8. Pull the release and start.
#
# No `build:` in $COMPOSE_FILE any more (TTLI_Audit_Report_2026-09-02.md
# M3 — the same "run what CI scanned and signed, not a fresh host build"
# reasoning as scripts/rolling-update.sh, which this block deliberately
# mirrors). A first-time bootstrap needs the exact same pull-then-tag
# step rolling-update.sh does on every later release, since without it
# `up -d` would try to resolve the bare `ttli-api:latest`/`ttli-web:latest`
# image names compose.yml references against Docker Hub instead of GHCR.
# --------------------------------------------------------------------
log "Pulling the release (this takes a few minutes on first run)"
export GIT_SHA="${RELEASE:-$(git rev-parse HEAD)}"
API_IMAGE="$REGISTRY/ttli-api:sha-$GIT_SHA"
WEB_IMAGE="$REGISTRY/ttli-web:sha-$GIT_SHA"
echo "$GHCR_PAT" | docker login ghcr.io -u "$GHCR_USERNAME" --password-stdin
docker pull "$API_IMAGE"
docker pull "$WEB_IMAGE"
# Mandatory, not best-effort (fable5.1_review.md C-3): a host with no
# cosign has no way to tell a real release from an unsigned or tampered
# image, so first-boot must refuse rather than warn and continue —
# skipping the check here would leave every subsequent
# scripts/rolling-update.sh redeploy on this host looking "verified" for
# a machine that was never actually capable of verifying anything. See
# that script's own comment on this same check for the full reasoning.
command -v cosign >/dev/null 2>&1 \
  || die "cosign is not installed on this host — refusing to deploy an unverified image. Install it first: https://docs.sigstore.dev/cosign/system_config/installation/"
cosign verify \
  --certificate-identity "https://github.com/WillemKlopper87/TTLI_LMS/.github/workflows/ci.yml@refs/heads/main" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
  "$API_IMAGE" "$WEB_IMAGE" >/dev/null \
  || die "signature verification failed — refusing to deploy an unsigned or tampered image"
docker tag "$API_IMAGE" ttli-api:latest
docker tag "$WEB_IMAGE" ttli-web:latest

log "Starting the stack"
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d

log "Waiting for core services to report healthy"
for svc in postgres redis clamav; do
  printf '  %s: ' "$svc"
  for _ in $(seq 1 60); do
    status="$(docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" ps -q "$svc" | xargs -r docker inspect -f '{{.State.Health.Status}}' 2>/dev/null || echo starting)"
    [ "$status" = "healthy" ] && { echo "healthy"; break; }
    printf '.'; sleep 5
  done
done

# --------------------------------------------------------------------
# 9. Nightly backup cron — 02:00 server time, idempotent (won't add a
#    second identical line on re-run).
# --------------------------------------------------------------------
log "Installing nightly backup cron"
CRON_LINE="0 2 * * * APP_DIR=$APP_DIR $APP_DIR/scripts/backup-db.sh >> /var/log/ttli-backup.log 2>&1"
( crontab -l 2>/dev/null | grep -vF "backup-db.sh" ; echo "$CRON_LINE" ) | crontab -

# --------------------------------------------------------------------
# 10. Smoke test.
# --------------------------------------------------------------------
log "Smoke-testing https://$DOMAIN/"
sleep 5
if curl -fsS -o /dev/null -w '%{http_code}' "https://$DOMAIN/" 2>/dev/null | grep -q '^[23]'; then
  echo "OK — the site is responding."
else
  warn "Could not confirm https://$DOMAIN/ yet — this is normal in the first minute or two"
  warn "while Caddy obtains its certificate. Check with: docker compose -f $COMPOSE_FILE logs -f caddy"
fi

cat <<SUMMARY

============================================================
  Deployed: https://$DOMAIN
  App dir:  $APP_DIR
  Env file: $ENV_FILE  (chmod 600 — back this up off-VM)

  Useful commands:
    docker compose -f $COMPOSE_FILE ps
    docker compose -f $COMPOSE_FILE logs -f api
    docker compose -f $COMPOSE_FILE logs -f worker
    $APP_DIR/scripts/backup-db.sh          # run a backup manually
    crontab -l                             # confirm the nightly backup

  Read docs/research/single-vm-deployment.md for what's different from
  the documented Azure target, and when to move off this shape.
============================================================
SUMMARY
