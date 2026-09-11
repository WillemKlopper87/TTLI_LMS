# TTLI_LMS — Next-agent brief

**Last updated:** 2026-09-11. This document describes current truth only. History,
rationale and superseded orders live in [`archive/NEXT_AGENT_BRIEF_2026-09-08.md`](archive/NEXT_AGENT_BRIEF_2026-09-08.md),
[`STATUS.md`](STATUS.md) and [`HANDOFF.md`](HANDOFF.md) — open those for *why*, never for *what is true now*.

## Current state

| Item | State |
|---|---|
| HEAD | `main` tracks `origin/main`. Run `git log -1` — do not copy a commit id from any document |
| CI on `main` | **Red** at the last push: the blocking container-image scan in `quality` caught CVE-2026-74860 (libxml2 Python bindings) in the pinned ClamAV image. Every application gate passed. Fix is on `fix/trivy-clamav-libxml2` as a scoped, expiring exception — see `.trivyignore` |
| Branch protection | Being enabled in the same pass: PR required, `quality` / `web` / `authenticated-e2e` / `secrets` / `images` required, branch must be up to date. Direct pushes to `main` stop working — that is intended |
| Migrations | `0001`–`0045` (`docs/check_links.py` enforces this range stays current) |
| Test tiers | API: ~597 tests, `pytest -m unit` runs without Docker, everything else needs `scripts/dev-up.sh`. Web: vitest (4 files) + 13 Playwright specs; 5 run against a real API in CI, the other 4 skip without one |
| Dev services | `docker compose -f infra/docker-compose.yml up -d` — postgres 5452, redis 6399, garage 9140/9141, mailpit 1145/8145, clamav 3410. API :8010, web :3010 |
| Dev logins | `apps/api/.venv/Scripts/python.exe scripts/seed_e2e_accounts.py` (ten least-privilege accounts, idempotent). `scripts/seed_demo_content.py` for the real catalogue, `scripts/seed_demo_enrolment.py` for a learner with an enrolment |

## Current priority — in order

1. **Green `main`, then protect it.** Merge the Trivy fix through a PR so the new gate is exercised once before it is required.
2. **T9–T12 production hardening** ([`BACKLOG.md`](BACKLOG.md) "Immediate TODO"): restore-drill evidence, deployment canary + rollback rehearsal, minimum viable observability, POPIA operational lifecycle.
3. **Structural debt** (after 2): frontend onto the generated API contract, a shared component layer, backend god-module splits — tracked as `BACKLOG.md` O8 / O14 and `REMEDIATION_LEDGER.md` M6 / M7.
4. **Phase 6 AI stays gated** until T13 and the owner's data-residency decision.

Do not add product features ahead of items 1–2. Add tests only at the named risk seams (media lifecycle, HLS/progressive delivery, BFF edge cases), not for raw count.

## Production blockers (engineering)

| # | Gap | Where tracked |
|---|---|---|
| T9 | Backup + restore rehearsal implemented, **not yet proven on a production-shaped host** | `BACKLOG.md` T9, `REMEDIATION_LEDGER.md` M4/H-20 |
| T10 | Worker deploy check is "process alive", not "consumes work"; no persisted release evidence; rollback never rehearsed | `BACKLOG.md` T10, `REMEDIATION_LEDGER.md` H2 |
| T11 | Sentry only — no metrics, log shipping, dashboards or alerts | `BACKLOG.md` T11 / O1 |
| T12 | No data-subject export / correction / erasure / retention / legal hold | `BACKLOG.md` T12 / O3 |
| — | Payfast never run against a real sandbox; Teams/Zoom/Meet/OIDC unit-tested against mocks only | `BACKLOG.md` B4, P7 |

## Owner blockers (do not build around these)

The full questionnaire is [`PLATFORM_OWNER_DECISION_PACK.md`](PLATFORM_OWNER_DECISION_PACK.md) with proposed answers in
[`PLATFORM_OWNER_RECOMMENDED_DEFAULTS.md`](PLATFORM_OWNER_RECOMMENDED_DEFAULTS.md). Headline items: the ten
`01_PRD.md §1.4` decisions (SCORM/xAPI, DRM level, VAT on international sales, AI provider + DPA + residency, CPD
body, brand, budget/date), Payfast credentials, real course content and video, Information Officer, cloud account.

## Where things are

| Need | Document |
|---|---|
| **Start here: the ordered sprint queue** | [`BACKLOG_2026-09-11.md`](BACKLOG_2026-09-11.md) |
| Actionable work queue (the only task-status authority) | [`BACKLOG.md`](BACKLOG.md) |
| Audit / review findings and their status | [`REMEDIATION_LEDGER.md`](REMEDIATION_LEDGER.md) |
| Requirements, data model, API, security, commercial, operations | `01_PRD.md` … `06_OPERATIONS.md` |
| Hosting shape and cost | `research/single-vm-deployment.md`, `research/devsecops-deployment.md` |
| Customer-facing intake | [`client-intake-checklist.md`](client-intake-checklist.md) |
| Historical logs (frozen, append-only) | [`STATUS.md`](STATUS.md), [`HANDOFF.md`](HANDOFF.md), `archive/` |

## Conventions that still bite

- Per-pass gate: `scripts/gates.sh` locally, then **live smoke through the BFF at :3010** — every real shipped bug was found there, not in pytest.
- Any router/schema change regenerates `packages/api-client` in the same commit; CI fails on drift.
- New RLS-forced tables: the `GRANT` must cover every verb the service issues (`0009` is the precedent; `0020`/`0022` are the scars).
- Never run `next build` while `next dev` is serving. Restart uvicorn/next before smoke tests.
- Windows: `write_bytes` not `write_text` (repo is `eol=lf`); `PYTHONIOENCODING=utf-8` for `arq`; drive Edge via Playwright + `--remote-debugging-port`, not the browser-use MCP.
- Keep the *why* comments in both apps. They are the real documentation.
