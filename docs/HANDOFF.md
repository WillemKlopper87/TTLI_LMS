# HANDOFF — for the next agent

**Written:** 2026-08-08, end of the session that built Sprints 2–4 of Phase 1.
**Updated:** 2026-08-09 — a follow-up session closed most of §3 and §4:
work is committed (still no remote), the drift gate is wired, weaknesses
1/2/3/4/6/8 are fixed with tests, and Sprint 5's worker + password reset are
built (migration `0005`). Items below are struck through or marked ✅ where
done; [STATUS.md](STATUS.md) carries the current numbers (81 tests, 12
endpoints, 5 migrations; tenant themes followed as `0006`, and `apps/web`
now exists — themed login with MFA, empty admin shell, BFF proxy — verified
end-to-end against both tenants over HTTP). **Still genuinely open: push to
a remote and get CI green (note: the CI workflow does not yet build
`apps/web` — add a job when wiring the remote); weakness 7 (email via arq);
the Next 15 `npm audit` findings, which only Next 16 fixes — a stack-decision
change, not an `npm audit fix`.**

**Read this before touching code.** It records verified state, unfinished work in
priority order, known weaknesses worth reviewing, and the conventions that are
easy to break by accident.

---

## 1. Verified state at handoff

Every claim below was executed this session, not inferred.

| Gate | Result |
|---|---|
| `ruff check` / `ruff format --check` | PASS — 52 files |
| `mypy src` (strict) | PASS — 38 source files |
| `pytest` | **75 passed, 0 skipped** (7 auth-flow, 12 config, 9 crypto, 3 events, 8 RLS, 12 security, 20 storage + 4 new rate-limit/cache) |
| `alembic upgrade head` / `current` | at `0004 (head)` |
| Migration round-trip (`downgrade -1` → `upgrade head`) | PASS for 0002, 0003, 0004 |
| `alembic check` (drift) | clean |
| S3 adapter vs **real MinIO** | manual round-trip verified (upload/get/signed-url/delete) |
| `packages/api-client` | generated, `tsc --noEmit` clean |

Containers `ttli-postgres` (5452), `ttli-redis` (6399), `ttli-minio` (9140/9141)
were left running. Database is seeded (demo + acme tenants, break-glass admin).

**⚠ Nothing from this session is committed.** `git status` shows ~38 modified or
new files on `main`. There is no remote; CI has therefore *never actually run* —
treat `.github/workflows/api.yml` as unproven until it has. First job: review the
diff and commit in sensible chunks (suggested: ① Sprint-1 defect fixes,
② Sprint 2 identity, ③ Sprint 3 storage+events, ④ Sprint 4 redis+client).

## 2. What was fixed this session (context for reviewing the diff)

1. **RLS superuser bypass (critical).** The app connected as the `ttli`
   superuser, which bypasses RLS unconditionally — FORCE or not. Tenant
   isolation did not actually work. Fix: migration 0001 now creates a
   least-privileged `app_user` login; `DATABASE_URL` uses it, migrations keep
   using `ttli` via `DATABASE_URL_SYNC`. `app_user` has no UPDATE/DELETE grant
   on `audit_events` (grant layer + trigger = two layers).
2. **Migration round-trip was impossible.** 0002's downgrade hit the
   `audit_events` FK (RESTRICT) — fixed by disabling the append-only trigger
   for one DELETE inside the downgrade.
3. **Silent rollback of security bookkeeping.** `get_session` in
   [src/core/deps.py](../apps/api/src/core/deps.py) rolled back on *every*
   exception, so failed-login counters, lockouts and `LOGIN_FAILED` audit rows
   were never persisted. Now: `AppError` → commit; anything else → rollback.
   **This semantic is load-bearing.** Every future endpoint inherits it —
   never "simplify" it back to `async with session.begin():`.

## 3. Unfinished work, in order

### 3.1 Housekeeping — ✅ done 2026-08-09, except the push

- ✅ Committed. **Still to do: push to a remote so CI runs for the first
  time.** Expect teething: the workflow has never executed.
- ✅ `.env.example` now covers every `Settings` field.
- ✅ `docs/STATUS.md` rewritten to current state.
- ✅ `docs/03_API_SPEC.md` gained §2.7 (MFA enrolment) and §2.8 (password
  reset).

### 3.2 Finish Sprint 4: the api-client drift gate — ✅ done 2026-08-09

Wired into `api.yml` (setup-node + `npm ci && npm run generate &&
git diff --exit-code -- src/schema.gen.ts && npm run typecheck`), verified
locally. `src/schema.gen.ts` is committed; `apps/api/openapi.json` stays
gitignored. The gate has already earned its keep once: the password-reset
endpoints changed the schema and forced a regeneration.

### 3.3 Remaining Phase 1 (sprint 5 of ~5) — half done 2026-08-09

- ✅ **arq worker** (`src/workers/main.py`): monthly partition extension and
  daily expired-auth purge, both via `SECURITY DEFINER` functions from
  migration `0005` so the worker keeps the least-privileged `app_user`
  connection. Run it with `arq src.workers.main.WorkerSettings`.
- ✅ **Password reset** (`0005`, §2.8 of the API spec): single-use, revokes
  every refresh-token family, clears the login lockout.
- ✅ **Tenant themes** — `0006` creates and seeds `tenant_themes`;
  `GET /api/v1/tenant/theme` returns the resolved tenant's palette, and the
  demo-target test proves two hostnames answer with two brands.
- ✅ **Empty admin shell** — `apps/web` (Next.js 15.5, React 19, Tailwind 4,
  port 3010): server-rendered login page themed from `GET /tenant/theme`,
  the MFA challenge step, an admin shell showing the signed-in principal,
  and the BFF proxy (the browser's only path to the API — no CORS surface).
  Access token lives in SPA memory per 04 §1.2; the HttpOnly-cookie refresh
  flow via the BFF is the natural next web-tier step. Hand-written minimal
  scaffold, not create-next-app; `npm run build` and `npm run typecheck` are
  the gates until a web CI job exists.

## 4. Known weaknesses to review (none are gate failures; all are real)

Ordered by risk. **1/2/3/4/6/8 fixed with tests on 2026-08-09; 5 and 7 remain.**

1. ✅ **MFA challenge tokens are replayable** — fixed: a successful verify
   claims the token via Redis `SET NX`; the second success is refused
   (`test_mfa_challenge_is_single_use`). Failed code attempts still retry
   against the same challenge, bounded by the 6-attempt lockout.
2. ✅ **Device fingerprint enforced** — the consuming UPDATE in
   `tokens.rotate()` refuses a mismatch (when both sides carry one) without
   consuming or revoking, so a wrong-fingerprint presenter can neither rotate
   nor DoS the real session (`test_refresh_rejects_device_fingerprint_mismatch`).
3. ✅/⬜ **Rate limiter** — the immortal-key crash window is healed
   (`EXPIRE ... NX` on every hit); the 2× window-edge burst stays, accepted
   and documented in the module docstring. Still open: 03 §1.8's limits for
   guest signup / verification / heartbeat — wire `rate_limit.hit` in as
   those endpoints land.
4. ✅ **Negative caching** — unknown hostnames are cached as a 10s miss
   sentinel (`test_unknown_hostname_is_negative_cached`).
5. ✅ **`X-Tenant-Host` is client-controllable** — the BFF now exists
   (`apps/web/app/api/bff/[...path]/route.ts`) and sets `X-Tenant-Host` from
   the request's own Host header, discarding anything inbound; verified by
   smoke test (a smuggled header still resolved the true tenant). Standing
   rule: **any future ingress in front of the API must preserve this** — the
   API keeps its own `tid`-claim cross-check as the second layer.
6. ✅ **`sync_database_url` derivation footgun** — `alembic/env.py` now
   refuses to run migrations over an `app_user` connection, with the real
   reason in the error.
7. ⬜ **Email failures are swallowed** (`services/email.py` logs and continues
   — correct for enumeration safety on magic links, but there's no
   retry/queue). The worker exists now; move sends onto arq.
8. ✅ **Migration 0002** now reads pydantic Settings (which loads `.env`), so
   a plain-shell `alembic` run seeds identically to the app and CI.

## 5. Conventions that will bite you if unknown

- **Zero-skip CI.** `api.yml` fails the build if *any* test skips. Never add a
  test that can skip in CI; the moto pattern in
  [tests/test_storage.py](../apps/api/tests/test_storage.py) is the template
  for "needs a cloud service" tests.
- **Two DB roles.** App = `app_user` (RLS-bound). Migrations = `ttli`
  (superuser). Every new tenant-scoped table needs, in its migration: ENABLE +
  FORCE RLS, the `tenant_isolation` policy, and a GRANT to `app_user`
  (0003/0004 are the pattern). Append-only tables get INSERT/SELECT only.
- **`alembic check` runs in CI** — models and migrations must agree. New
  models must be imported in `src/models/__init__.py` or drift detection is
  blind to them. Monthly `events_YYYY_MM` partitions are excluded via
  `include_object` in [alembic/env.py](../apps/api/alembic/env.py).
- **Auth responses are deliberately uniform** (timing-equalised, same message
  for every failure mode). Don't "improve" error specificity on auth paths.
- **Ports are reserved** (README table): 5452/6399/9140/9141/1145/8145/8010/3010.
  Other projects on this machine own the defaults.
- **LF endings** enforced by `.gitattributes`; line length 100; mypy strict.
- **Run everything through `./.venv/Scripts/python.exe -m ...`** from
  `apps/api/` (Windows; system python is not the project env).

## 6. Phase guidance beyond Phase 1

- **Phase 0 is still the critical path** and is the customer's, not yours: ten
  unsigned decisions ([01 §1.4](01_PRD.md)). Nothing you build changes that;
  keep bringing forward only work that no open decision can invalidate.
- **Phase 2 (public site/funnel):** starts with `apps/web` — which sprint 5's
  admin shell scaffolds anyway. Leads/consent tables follow the 0003 migration
  pattern; `consent_records` is append-only (copy the audit_events treatment).
  Event tracking already has its table — Phase 2 only adds the write path.
- **Phase 3 (commerce):** the append-only `ledger_entries` and sequential
  invoice numbers are SARS-compliance-critical — read 02 §6.4/§6.6 *before*
  designing, and reuse the two-layer append-only enforcement (revoked grant +
  raising trigger) exactly as `audit_events` does. Idempotency keys on all
  webhook tables (unique constraint, not application logic).
- **Phase 4 (LMS/media):** port from `Streaming_Server`
  (`c:/Users/Wille/Downloads/applications/Streaming_Server`) into
  `src/services/media/` — **do not modify that project** (06 §3.1). The
  storage adapter's `generate_signed_url` is already the hook for signed HLS.
- **Don't quote prices or dates.** 05_COMMERCIAL is explicitly not quotable
  until a unit-cost model exists; STATUS §11 explains why no schedule is
  published. Preserve both stances in any doc you touch.

## 7. How to verify your own work (the bar this session used)

```bash
cd apps/api
./.venv/Scripts/python.exe -m ruff check . && ./.venv/Scripts/python.exe -m ruff format --check .
./.venv/Scripts/python.exe -m mypy src
./.venv/Scripts/python.exe -m pytest -q -rs          # expect 0 skips with containers up
./.venv/Scripts/python.exe -m alembic check          # no drift
./.venv/Scripts/python.exe -m alembic downgrade -1 && ./.venv/Scripts/python.exe -m alembic upgrade head
python docs/check_links.py                            # from repo root, after doc edits
```

A migration that has not survived its own round-trip is not done. A security
claim that has not been asserted by a test running as `app_user` is not done.
STATUS.md is updated in the same change as the work it describes, never later.
