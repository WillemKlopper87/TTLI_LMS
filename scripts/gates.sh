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

# `git diff --exit-code` compares the working tree against the INDEX, so a
# legitimately-regenerated client trips this until it is staged. That is
# the intended workflow — `git add` the regenerated file, then gate — and
# it matches CI, where the checkout is clean and a correct commit produces
# no diff at all.
echo "== api-client drift"
ENVIRONMENT=local $V/python -c "import json; from src.main import app; print(json.dumps(app.openapi(), indent=2))" > openapi.json
(cd ../../packages/api-client && npm run generate >/dev/null && git diff --exit-code -- src/schema.gen.ts && npm run typecheck)

echo "== web lint + typecheck + build"
(cd ../web && npm run lint && npm run typecheck && npm run build)

# Playwright drives a PRODUCTION build on :3011 (see playwright.config.ts
# for why not the dev server). The authenticated spec skips itself when
# the API isn't up on :8010 — the public + axe specs still run, so this
# step is meaningful either way.
#
# Kill anything already on :3011 first. Playwright's reuseExistingServer
# would otherwise hand the whole suite to a server left running from an
# earlier gate run, which serves the PREVIOUS build — tests then fail
# against code that no longer exists, or worse, pass against code that
# was never rebuilt. Cost this exact confusion once (2026-08-21).
echo "== web e2e (playwright + axe)"
if command -v netstat >/dev/null 2>&1; then
  # `|| true`: with `set -e`, a grep that matches nothing would make
  # this assignment fail and kill the whole gate run.
  stale_pid=$(netstat -ano 2>/dev/null | grep LISTENING | grep ':3011' | awk '{print $5}' | head -1 || true)
  if [ -n "${stale_pid:-}" ]; then
    echo "   (killing stale :3011 server, pid $stale_pid)"
    taskkill //F //PID "$stale_pid" >/dev/null 2>&1 || kill -9 "$stale_pid" 2>/dev/null || true
    sleep 2
  fi
fi
(cd ../web && npm run test:e2e)

echo "== docs"
(cd ../.. && python docs/check_links.py && python docs/source/extract.py --check)

echo
echo "ALL GATES GREEN"
