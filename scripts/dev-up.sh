#!/usr/bin/env bash
# Bring the local stack up and say what to run next. Bash (Git Bash on
# Windows) because that is the shell this repo is developed in; there is
# deliberately no Makefile — `make` is not installed on the dev machine.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f apps/api/.env ]; then
  cp .env.example apps/api/.env
  echo "apps/api/.env created from .env.example — review it before going further."
fi

docker compose -f infra/docker-compose.yml up -d

echo -n "waiting for postgres/redis/clamav health"
for svc in ttli-postgres ttli-redis ttli-clamav; do
  until [ "$(docker inspect -f '{{.State.Health.Status}}' "$svc" 2>/dev/null)" = healthy ]; do
    echo -n .
    sleep 3
  done
done
echo " ok"

if [ ! -d apps/api/.venv ]; then
  echo "no apps/api/.venv yet — create it first:"
  echo "  cd apps/api && python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt"
  exit 1
fi

(cd apps/api && .venv/Scripts/alembic upgrade head)

cat <<'NEXT'

Stack is up and migrated. In separate terminals:
  cd apps/api && .venv/Scripts/uvicorn src.main:app --reload --port 8010
  cd apps/api && PYTHONIOENCODING=utf-8 .venv/Scripts/arq src.workers.main.WorkerSettings
  cd apps/web && npm run dev          # first time: npm ci in packages/api-client, npm install here
NEXT
