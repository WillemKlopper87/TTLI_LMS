#!/usr/bin/env bash
# The full pre-commit gate sweep, in CI's order, using the project venv
# (the machine's global ruff is years older and disagrees — always this
# venv). Run from anywhere; exits non-zero on the first failing gate.
# GitHub Actions mirrors these steps but is billing-blocked at the time
# of writing, so this script IS the gate (docs/NEXT_AGENT_BRIEF.md §1).
set -euo pipefail
cd "$(dirname "$0")/../apps/api"

V=.venv/Scripts

echo "== ruff check";           $V/ruff check .
echo "== ruff format --check";  $V/ruff format --check .
echo "== mypy";                 $V/mypy src
echo "== pytest";               PYTHONIOENCODING=utf-8 $V/pytest -q -p no:cacheprovider
echo "== alembic upgrade head"; ENVIRONMENT=local $V/alembic upgrade head
echo "== migration round-trip"; ENVIRONMENT=local $V/alembic downgrade -1 && ENVIRONMENT=local $V/alembic upgrade head
echo "== alembic check";        ENVIRONMENT=local $V/alembic check

echo "== api-client drift"
ENVIRONMENT=local $V/python -c "import json; from src.main import app; print(json.dumps(app.openapi(), indent=2))" > openapi.json
(cd ../../packages/api-client && npm run generate >/dev/null && git diff --exit-code -- src/schema.gen.ts && npm run typecheck)

echo "== web lint + typecheck + build"
(cd ../web && npm run lint && npm run typecheck && npm run build)

echo "== docs"
(cd ../.. && python docs/check_links.py && python docs/source/extract.py --check)

echo
echo "ALL GATES GREEN"
