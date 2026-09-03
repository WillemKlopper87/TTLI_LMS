# TTLI_LMS — Next-agent brief (updated 2026-08-27)

Read this first for operating context, then use `docs/BACKLOG.md` as the
authoritative work queue. `STATUS.md` and `HANDOFF.md` are long-form historical
logs and should only be opened for detail on a specific subsystem. This brief
was refreshed after the 2026-08-27 review, authenticated-fetch consolidation,
new browser journeys and P9 survey-results phase; older sections below retain
useful design rationale but may contain historical counts.

---

## 1. State at a glance

| Item | State (verified 2026-08-27) |
|---|---|
| Branch / HEAD | `main` tracks `origin/main`; inspect `git status`/`git log -1` rather than copying a commit id from this document |
| CI (`.github/workflows/ci.yml`) | GitHub Actions billing is resolved and jobs execute normally. `013ebc2` repaired the P9 formatting gate; `2cfe90e` adds a required authenticated-browser job. Confirm the latest run before marking T1/T3 done |
| API gates | Ruff format/check and mypy pass. The full API suite and all 23 assessment tests pass locally against real Postgres/Redis/Garage/ClamAV; CI also enforces migrations, zero skipped integration tests, migration round-trip, model drift and generated-client drift |
| Web gates | Typecheck/build pass; ESLint has 0 errors and 53 tracked warnings. Public/axe tests remain fast and API-free; learner assessment, checkout, finance and organisation journeys now have a separate seeded integration job |
| Immediate work | Follow `docs/BACKLOG.md` T1–T6. Do not resurrect the obsolete 2026-08-20 order later in this file |
| Dev services | `docker compose -f infra/docker-compose.yml` (or `scripts/dev-up.sh`) — postgres 5452, redis 6399, garage 9140/9141, mailpit 1145/8145, clamav 3410. API :8010, web :3010. |
| Dev login | Run `apps/api/.venv/Scripts/python.exe scripts/seed_e2e_accounts.py`; it idempotently repairs the ten least-privilege accounts used by the Playwright specs. The script is the credential/role authority — do not copy its values into another seed path |

## 2. What is built

Numbers are STATUS.md's own table (`STATUS.md:64-74`); the per-section headings further down that
file are stale (they still say Phase 3 ~40%, Phase 1 ~95%) — trust the table.

| Phase | Done | What exists |
|---|---|---|
| 0 Discovery / sign-off | 0% — **customer-blocked** | 10 open decisions in `01_PRD.md §1.4`; engineering proceeded regardless |
| 1 Foundation | ~98% | Multi-tenant FastAPI + Next 16 BFF, RLS tenancy (double-asserted: host + JWT `tid`), JWT/Argon2id/magic-link/TOTP auth, storage adapters (local/S3/Azure), arq worker, error envelope, idempotency middleware, CI gate |
| 2 Public site / funnel | ~85% | Marketing site, leads/consent/events, guest access + expiry sweep, contact form, book pages (2 books), podcast platform, resources hub (articles + recommendations, 3 stages, all built incl. admin authoring), About/facilitator bios |
| 3 Commerce | ~85% | Catalogue, orders, SA VAT tax engine, EFT + PO purchase paths, sequential invoicing, append-only ledger, approval queue, `Idempotency-Key`, full refunds/credit notes, Payfast card checkout + webhook (**never run against a real Payfast sandbox — no credentials exist**), multi-tier subscriptions, free-preview lessons. Netcash not attempted. |
| 4 Core LMS | 100% | Content model, completion-rule engine, enrolments, real ffmpeg→HLS transcode with signed playback, heartbeat anti-bypass, WebVTT captions, quizzes/surveys/assignments with auto-grading, certificates (PDF+QR, public verify, LinkedIn), transcript, full course/module/lesson/template authoring UI |
| 4.5 PWA + a11y | **100%** | Manifest/SW/offline shell, WCAG 2.1 AA contrast pass, Web Push (VAPID, 3 triggers, verified live on Edge/WNS), and since 2026-08-20 the axe-core gate — the last item. |
| 5 Corporate / workshops / marketing | 100% | Organisations, seat pools, PO checkout, manager visibility, facilitators/workshops/sessions/waitlists, pluggable meeting provider (Teams), CRM (deals/tasks/notes), marketing engine (segments/templates/campaigns/unsubscribe) |
| 6 AI insights | 0% | Not started (demo target: 500 survey responses summarised with zero identifiers transmitted) |
| 7 Hardening + cloud | ~15% | Containerisation done 2026-08-20 (both Dockerfiles built and run, prod-shaped compose, CI image build + Trivy scan). Still absent: IaC, registry push, cloud provisioning, reverse proxy, staging, load test, restore drill. `docs/research/devsecops-deployment.md` remains the plan for the rest. |
| Enterprise UI pass (2026-08-17) | built | 11-screen prototype alignment, course-authoring wizard (`/admin/courses/new`), revenue analytics (`/admin/analytics`, migration 0028) |

Scale: 24 routers / ~45 services / 27 models / 44 migrations (`0001`–`0044`) / ~26k LOC API;
50 `page.tsx` + 6 BFF routes / ~20k LOC web; ~318 tests, all HTTP-level through the real
middleware stack against real Postgres/Redis/Garage/ClamAV/ffmpeg.

## 3. Open work

### 3a. Engineering — actionable now
1. ~~**Make CI green**~~ **DONE 2026-08-20.** Also fixed en route: `Article`/`Recommendation` were never registered in `src/models/__init__.py`, so `alembic check` compared against blind metadata (masked by the red Format step). Original item: `ruff format` the two files; export `openapi.json` and `npm run generate` in `packages/api-client`; commit both. Convention (see §6) is that any router/schema change regenerates the client in the same commit — the last three passes skipped it.
2. ~~**Security: MFA-pending JWT is accepted as an access token.**~~ **FIXED 2026-08-20** — `decode_access_token` rejects `purpose` tokens; regression test in `tests/test_auth_flows.py`. Original finding: `src/core/security.py:98` `decode_access_token` checks signature + `exp` only; `issue_purpose_token` (`:104`) mints the MFA challenge token with the same secret and `sub`/`tid` claims (`routers/auth.py:110-118`). Result: with a password but no TOTP, an attacker gets a 5-minute bearer that passes `get_principal` (`core/deps.py:136`) with empty `perms`; every endpoint that takes `PrincipalDep` without `principal.require(...)` is reachable — `routers/learning.py` has 8 such endpoints and 0 `require` calls. The docstring on `issue_purpose_token` claims the opposite. Fix: reject any token carrying `purpose` in `decode_access_token` (or require a positive `typ: "access"` claim). Add a test.
3. ~~**Idempotency middleware is replay-caching, not replay-protection.**~~ **FIXED 2026-08-20** — reservation flow + migration `0032` + nightly `prune_idempotency_keys` sweep; race + stale-takeover tests in `tests/test_idempotency.py`. Original finding: `core/idempotency.py:128-190` — SELECT key → `call_next` (handler commits) → INSERT key, in three transactions. Two concurrent replays both miss, both create the order, loser gets a 500 from the unique index after the side effect is durable. Fix: INSERT an in-flight row `ON CONFLICT DO NOTHING` *before* `call_next`, 0 rows = 409, update with the response after. Also nothing prunes `idempotency_keys`.
4. ~~**`get_session` commits on every `AppError`, globally**~~ **FIXED 2026-08-20** — rollback default; `AuditedSessionDep` for the auth router and `POST /lessons/{id}/complete` (REQ-BYPASS-11). Beware: FastAPI yield-dependencies must stay flat generators (see HANDOFF 2026-08-20 entry). Original finding: (`core/deps.py:79-88`). Justified for login-failure counters, but it means any service that mutates and then raises a business-rule error commits the partial state. Give the auth path its own dependency; default everything else to rollback.
5. `scripts/hide_test_courses.py --apply` — 1,320 test-course artefacts still pollute the catalogue; dry-run verified, reversible, never applied (a human must run it).
6. `ProductSummary` lacks `course_id`/`course_slug` (product → course deep-link); PO checkout has no `ap_email` field. Both specified in the enterprise-UI contract, not delivered.
7. ~~axe-core CI gate (last Phase 4.5 item)~~ **DONE 2026-08-20** — Phase 4.5 is complete.
8. Stale test data: ~~the workshops test above~~ (self-cleaning since 2026-08-20); the underlying issue — tests share the dev DB with the running app and leak rows — remains, tracked in §7b "Test environment isolation".

### 3b. Engineering — planned, larger
- Phase 6 AI insights (ship inert behind `ai_enabled=false`), then Phase 7 hardening/containerisation per `docs/research/devsecops-deployment.md`.
- Payment analytics dashboard beyond what shipped in `/admin/analytics` (`docs/research/payment-analytics-dashboard.md`).
- redis-py bump is blocked by `arq` (pins redis <6, maintenance-only); replacing arq (SAQ/Streaq) is a real migration across 4 job types.
- Post-build cleanup the user has already asked for (see §5): docs consolidation + codebase shrink.

### 3c. Customer-blocked (do not build around these)
Decision register (10 items, `01_PRD.md §1.4`); VAT position for international sales; Payfast/Netcash sandbox accounts; Azure SA-North availability; content inventory (videos, podcast audio, book copy); brand/design system sign-off; footer social URLs; Information Officer registration.

## 4. What I would have done differently

Ranked by how much it will cost the next agent.

### Correctness / security
- The three items in §3a.2–4 above. They are small fixes; the pattern behind them is that middleware/dependency-level code was written with a docstring asserting a property (`never accepted as an access token`, replay protection, "only login needs commit-on-error") that no test checks. **Add a test per invariant at the `core/` layer.**
- ~~Access-token `jti` never used~~ — fixed 2026-08-20 (logout denylists it; `get_principal` refuses denylisted tokens).

### Frontend architecture
- **The generated API client is 11,398 lines and is imported once** (`lib/server-api.ts:8`, for `getTheme()`). Everything else is raw `fetch` + hand-written interfaces (~12 in `lib/server-api.ts`, ~60 more inline in pages; 14 in `lesson-activity-panel.tsx` alone). The type contract, its CI drift gate and the regenerate step all exist and are bypassed — an API field rename typechecks clean and fails at runtime. I would have made every BFF/server call go through the generated types from day one; the fix now is a `lib/api.ts` wrapper typed from `schema.gen.ts` and a page-by-page migration.
- ~~**`authedFetch` copied across 18 files**~~ — fixed 2026-08-27. Authenticated network calls use `lib/authed-fetch.ts`, which preserves caller headers and refreshes/retries once on a stale-token 401; authenticated files use `lib/authed-download.ts`. Remaining `getAccessToken()` calls are readiness guards or the shared transport itself.
- **`components/` has two files** for a 50-page app; `lesson-activity-panel.tsx` is 964 lines and eight more pages exceed 430. Inline `style={{}}` is pervasive enough that the CSP keeps `style-src 'unsafe-inline'` *because of it* (`proxy.ts` says so). I would have extracted a small component set (card, table, form field, button, status pill, modal) when the enterprise design system landed, and moved styles to Tailwind classes so the CSP could drop `unsafe-inline`.
- ~~**No web tests**~~ — Playwright + axe landed 2026-08-20. Coverage now includes public/axe, learner assessment/completion, EFT checkout/return, finance approval and organisation seat purchasing. The authenticated journeys gained their own required API-backed CI job on 2026-08-27; video playback remains the explicit browser gap.
- Static content in code (`lib/facilitators.ts`) is fine as a stopgap but is a third content source next to the DB and the CMS-ish admin pages; it should move behind the API once bios exist.

### Backend architecture
- `services/enrolment.py` (954 lines) and `routers/assessment.py` (746) are god-modules; `routers/auth.py` (653) mixes login, MFA, magic-link, reset and recovery. Split by use case before adding Phase 6.
- **Test suite: right shape, implemented 25 times.** `conftest.py` provides 5 fixtures; 24 test files define their own `client`, 26 their own `_redis_reachable`, ~22 their own login helper — 13k test LOC for 318 tests. Any change to app construction or auth touches ~25 files. Centralise into `conftest.py`.
- **False green when Docker is down**: 29/35 test files are `integration`-marked and skip if Postgres/Redis are unreachable; only CI's post-hoc "0 skipped" check catches it. Locally, `pytest` with no services = green run that tested nothing. Make the skip a hard failure unless `ALLOW_SKIP_INTEGRATION=1`.
- ~~Tests write into the same DB the dev server uses~~ — fixed 2026-08-20 (conftest-provisioned `ttli_test` + redis db 1).
- Note: the older claim that "tests run as table owner and bypass RLS" is **wrong** — `conftest.py:20-25` connects as `app_user` and migrations use `FORCE ROW LEVEL SECURITY`; RLS *is* exercised. Don't repeat that claim.
- Migrations `0008`, `0020`, `0022` exist only to fix data/GRANTs earlier migrations missed. Add a test that, for every RLS-forced table, asserts `app_user` has each verb the service layer issues.

### Dependency / repo / process
- ~~`apps/api/uv.lock` stub~~ — deleted 2026-08-20; `requirements.txt` is the declared single source of truth (transitive deps still unpinned).
- **29 of 135 commits on `main` are `autosave: in-flight agent work (HH:MM)`**, pushed to origin, so `git log`/`blame` carry no rationale and all rationale lives in the 209 KB HANDOFF.md instead. Zero merge commits, zero PRs, zero tags, everything direct-to-main; a red main is only discovered after the fact. I would have kept autosaves on a scratch branch and squash-merged named commits (a PR per pass gives you CI *before* main and a place for the security-review triage that currently happens in follow-up commits). Rewriting history now is technically cheap (single author) but is a decision, not a chore — flag it, don't do it silently.
- **Docs bloat**: HANDOFF.md 209 KB, STATUS.md 185 KB, both append-only, both internally inconsistent (STATUS's gate table says 277 tests / migrations at `0021`; its headline says 320 / 29 migrations; reality is ~318 / 31). README says "Phase 0 blocked, Phase 1 in progress", "Next.js 15", "Redis 7", "187 tests". I would have kept STATUS to a phase table + gates + open items (~150 lines) and made HANDOFF a dated log that gets archived per phase. The user has already asked for this consolidation once the build settles — do it before Phase 6 rather than after; it is the single largest tax on every new agent.
- ~~`chat-export-1786178220416.json` at repo root~~ — moved to `docs/source/` 2026-08-20 (`extract.py --check` still passes).
- ~~`.env.example` copied to the wrong directory; 8 undocumented bring-up steps~~ — fixed 2026-08-20: README's Local development block now documents the full sequence (venv, worker terminal, api-client `npm ci`, correct `.env` target), and `scripts/dev-up.sh` / `scripts/gates.sh` automate bring-up and the full gate sweep (bash — `make`/`just` are not installed on the dev machine).
- CI: ~~file is `api.yml`~~ ~~no `concurrency` group; no `permissions:` block~~ ~~`docs/check_links.py` / `extract.py --check` not in the workflow~~ ~~no Dependabot~~ (all fixed 2026-08-20: renamed `ci.yml`, concurrency + permissions blocks, both doc checks now gate, `.github/dependabot.yml` weekly/grouped). Still open: actions pinned by mutable `@v4`; no `--cov-fail-under` (measure first); no secret scanning despite dev creds committed in compose/CI; ZAP/Grype/Snyk manual-only. Trivy report-only by design. `clamav/clamav-debian:stable` is the one floating image tag.
- ~~Compose service `mailhog` runs Mailpit~~ — renamed `mailpit`/`ttli-mailpit` 2026-08-20.

### Things done well that the next agent should keep
RLS with `set_config(..., true)` + `FORCE ROW LEVEL SECURITY` + double tenant assertion; `check_production_safety()` fail-fast; the single error envelope; the BFF that overwrites `X-Tenant-Host` from its own `Host` and forwards bodies as `arrayBuffer`; refresh cookie path-scoped to `/api/bff/auth` with `navigator.locks` refresh serialisation; per-request CSP nonce; graceful degradation for every un-provisioned third party (Payfast, Spotify, VAPID, Graph); the ruff/mypy strictness; and — above all — the *why* comments throughout both apps. Do not strip those comments; they are the real documentation.

## 5. Historical recommended order — superseded

This 2026-08-20 sequence is retained as history. Do not execute it: most items
are complete. The live order is `docs/BACKLOG.md` T1–T6.

1. Green CI (§3a.1) — one commit, push, wait for green. Delete `wip/enterprise-ui`.
2. The three `core/` fixes (§3a.2–4) with a test each — one commit, live-smoke MFA login through the BFF.
3. Docs consolidation the user asked for: shrink STATUS.md to table + gates + open items; archive HANDOFF passes into `docs/handoff/YYYY-MM.md`; fix README's stack/status lines; move the chat export; add a `justfile`/`Makefile` and fix the `.env` path. Do this **now** — every later agent pays for it.
4. Test hygiene: shared fixtures in `conftest.py`, separate test DB, hard-fail on skip.
5. Frontend: `lib/authed-fetch.ts` + typed `lib/api.ts` from `schema.gen.ts`; ESLint + Playwright smoke + axe in the `web` job (closes Phase 4.5).
6. Then the product gaps in §7a in order (Passes A–K of `docs/research/enterprise-gaps-plan.md`), Phase 6 → Phase 7 per the existing research docs, and the payment-analytics extension.

## 6. Conventions and gotchas (carry forward)

- Per-pass gate: `ruff check` + `ruff format --check` + `mypy src` + full `pytest` + `alembic check` + downgrade/upgrade round-trip + web `typecheck`/`build` + `npm run generate` in `packages/api-client` if any router/schema/docstring changed → **live smoke through the BFF at :3010** (every real bug this project shipped was found there, not in pytest) → STATUS/HANDOFF → commit → push → CI green.
- Restart uvicorn/next before smoke tests; a stale server silently serves old code. Never run `next build` while `next dev` is serving (both write `.next/`) — it took the site down once.
- Windows: Python `write_text` produces CRLF (repo is `eol=lf`); use `write_bytes` or normalise. Run `arq` with `PYTHONIOENCODING=utf-8`. Drive Edge via `--remote-debugging-port` + a small CDP script rather than the browser-use MCP.
- New RLS-forced tables: check the `GRANT` covers every verb the service issues (0009 is the precedent; 0020/0022 are the scars).
- The machine is unstable — persist work to disk incrementally and tell subagents to do the same.

> **The numbered backlog lives in [BACKLOG.md](BACKLOG.md)** — every outstanding
> item as P1–P16 (product), R1–R13 (research leftovers), O1–O12 (operational)
> and B1–B9 (customer-blocked), compiled 2026-08-20 by re-checking each
> research document against the code. Work is picked by number from there;
> §7 below is the narrative version of the same ground.

## 7. Missing but beneficial — what the current solution does not have

Two lists. The first is product scope, grounded in the 54-row audit in
`docs/research/feature-matrix-coverage.md` (2026-08-16) and re-checked against the code on
2026-08-18 — nothing below has been built since that audit unless stated. The sequenced build plan
for the product items already exists as Passes A–K in `docs/research/enterprise-gaps-plan.md`;
none of those passes has started. The second list is platform/operational capability the docs
never planned as features but a production LMS needs.

### 7a. Product gaps (in the order I would build them)

| # | Gap | Today | Why it matters | Size |
|---|---|---|---|---|
| 1 | **Admin operations home + per-course analytics** (audit #41, #40; Pass A) | `apps/web/app/admin/page.tsx` is a 21-line "Welcome" stub with two inert nav items ("Learners", "Reports"); `/admin/analytics` covers revenue only | First screen any buyer or admin sees. Every input already exists in `orders`, `enrolments`, `lesson_completions`, `quiz_attempts` | S–M |
| 2 | **Audit log read path + coverage** (#52; Pass B) | `audit_events` is written (auth, enrolment, quiz, survey, assignment, webhooks) but there is no `GET`, no UI, no export; payment approve/reject/refund, certificate revoke and role changes are not logged | Enterprise column promises "advanced audit logs"; also the first thing a POPIA reviewer asks for | M |
| 3 | **Tenant self-service: branding, domains, users, roles** (#44, #45 + unlisted; Pass C) | Theme and domains change only by migration; there is **no UI or endpoint to create a staff user or assign a role** — `routers/tenant.py` has one PATCH (manager-visibility) | An admin cannot onboard a colleague without a developer | M |
| 4 | **SSO — Entra ID / OIDC** (#46; Pass D) | Password, magic link, TOTP only; `msal` is named in README's stack table but nothing exists | Standard corporate procurement gate for the Team/Corporate tiers | L |
| 5 | **Learning paths** (#7; Pass E) | Zero hits for `learning_path` | Core LMS vocabulary; the Professional tier lists it | L |
| 6 | **Finance completeness** (#34, #39, #31; Pass H) | No invoice PDF, no `GET /invoices` for the buyer, no accounting CSV export (`/invoices/export`, `/ledger/export`), Payfast never run against a sandbox | Cheap to close; the rigorous ledger/invoicing work is invisible to a customer without it | S–M |
| 7 | **Workshops end to end** (#20, #22, #24, #25; Pass G) | Teams provider is a stub that raises; no ICS/calendar invite; no learner "my sessions" page; single facilitator per session; no reschedule; workshop credits not decremented | Live workshops are half the commercial pitch | M–L |
| 8 | **Departments / business units** (#30; Pass F) | Zero hits | Corporate reporting is flat per organisation | M |
| 9 | ~~**Assessment depth** (#8, #9, #13; Pass J)~~ **DONE 2026-08-27** | Privacy-gated survey results/CSV, pre/post delta reporting, and tenant-scoped reusable quiz/survey question banks now have API, admin UI and authenticated browser coverage | — | DONE |
| 10 | **Custom certificate design** (#19; Pass I) | Fixed reportlab layout, Helvetica, no logo | Certificates are the visible product of the LMS | M |
| 11 | **AI insights vertical slice** (#42, #43; Pass K = Phase 6) | Only `Tenant.ai_enabled` / `ai_monthly_token_budget` columns | The Phase 6 demo target; ship inert behind the flag | L |
| 12 | CRM depth (#36, #37) | No deal owner/assignee, org link, search/filter, lead→deal conversion, contact page; campaigns are plain-text, `scheduled_at` unused, no preference centre | Fine for a demo, thin for daily use | M |
| 13 | Coaching / one-on-one (#21), Zoom/Meet (#23), CPD fields beyond one integer (#18), LinkedIn share for certificate-only courses (#17), guest→paid carry-over and sample watermark (REQ-LEAD-05/07) | Enum values or a single column each | Small, demo-visible | S each |
| 14 | Mobile layout for the admin shell (#4) | Fixed `w-56` sidebar | Facilitators mark attendance on phones | S |
| 15 | Learner-facing search across catalogue/resources; a learner notification centre (push exists, no in-app inbox); an email preference centre | None | Expected baseline UX in any LMS | S–M |
| 16 | Deferred by the PRD but commonly asked for: API keys / outbound webhooks (#38, #48), SCORM/xAPI import, discussion or Q&A per lesson, ASR-generated captions, DRM (#50), offline downloads (#51) | Not built, by decision | Raise with the customer before Phase 7 rather than discover in a tender | — |

### 7b. Platform and operational gaps

| Gap | Today | Why it matters |
|---|---|---|
| **Deployment substrate** | ~~No Dockerfile, no prod compose, no migration-on-deploy~~ — all added and verified running 2026-08-20 (`apps/*/Dockerfile`, `infra/docker-compose.prod.yml`, CI `images` job). Still open: no IaC, no registry push, no cloud provisioning, no reverse proxy/TLS (Container Apps ingress covers TLS at Tier 0 per the research doc), no staging | Images are real; the cloud target is not provisioned |
| **Observability** | Sentry DSN is a config flag only; no metrics, tracing, log shipping, dashboards or alerts; `06_OPERATIONS.md` describes them | Incidents will be diagnosed from uvicorn stdout |
| **Backups / restore drill** | Prose only (the PG16→18 dump/restore); no scheduled backup, no tested restore | Phase 7 demo target is "restore drill completed" |
| **Global rate limiting / abuse controls** | CORRECTION: leads, guest-access and `/verify/*` always had per-IP limits (the 08-18 review missed them). Real defect fixed 2026-08-20: behind the BFF all "per-IP" buckets shared the BFF's address — the BFF now forwards `X-Forwarded-For` and the API honours it behind `TRUST_X_FORWARDED_FOR` (default false; enable only when the API is BFF-only). Still open: no limits on `/public/*` reads or webhooks; no per-tenant quotas |
| **Token revocation** | ~~jti never read~~ — fixed 2026-08-20: logout denylists the presented token's jti (TTL = remaining life), `get_principal` checks it | Done |
| **Data-subject rights (POPIA)** | No export-my-data / delete-my-account flow, no retention jobs beyond guest expiry and auth purge; `04_SECURITY` §11 lists legal hold and breach notification as open | Compliance obligations the customer will be asked about |
| **Frontend quality gates** | ~~No ESLint, no e2e, no axe~~ — all three added 2026-08-20: ESLint (`core-web-vitals`, errors blocking), Playwright smoke (public pages + real login), axe-core WCAG 2.1 A/AA on every public page, in `scripts/gates.sh` and CI. Still open: component/unit tests, Lighthouse, admin/learner-deep coverage | Gate exists; coverage is shallow by design |
| **Automated dependency updates** | No Dependabot/Renovate; `arq` blocks redis-py; transitive deps unpinned | Every bump has been a manual sprint |
| **Test environment isolation** | ~~No `ttli_test` DB~~ — since 2026-08-20 conftest provisions and targets `ttli_test` + redis db 1 unconditionally. Still open: per-test engine churn; the 1,320 historical test courses still pollute the dev catalogue (`scripts/hide_test_courses.py --apply`, human decision) | Root cause fixed; leftovers remain |
| **Developer ergonomics** | No Makefile/justfile, ~8 hand-typed bring-up steps, `.env` path trap, `uv.lock` stub, `mailhog` service runs Mailpit | Every new agent loses the first hour |
| **Feature flags / kill switches** | Per-feature `*_ENABLED` settings exist for some (break-glass, DRM named but absent, AI) but no runtime toggle mechanism | Phase 6 AI must ship inert and be switchable without a deploy |
| **Multi-currency / i18n** | Tax engine seeds SA VAT only and refuses international buyers; UI is English-only, ZAR-only | README's pitch is "South Africa and internationally"; blocked on the VAT decision, but the currency/locale plumbing could be laid now |
| **Release management** | No tags, no changelog, no PRs; autosave commits on `main` | No way to say "what shipped in v0.x" |
