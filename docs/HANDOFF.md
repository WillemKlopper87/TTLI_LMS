# HANDOFF — for the next agent

**Written:** 2026-08-08, end of the session that built Sprints 2–4 of Phase 1.
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

### 3.1 Housekeeping (do first, ~an hour)

- **Commit** (see §1). Then push to a remote so CI runs for the first time.
  Expect teething: the workflow was extended blind (APP_DB_PASSWORD env,
  app_user URL) and has never executed.
- **`.env.example` is stale.** Missing every setting added since Sprint 1:
  `MAGIC_LINK_MINUTES`, `MFA_PENDING_MINUTES`, `MFA_ENROLL_MINUTES`,
  `MFA_ISSUER_NAME`, `STORAGE_LOCAL_ROOT`, `AZURE_STORAGE_CONNECTION_STRING`.
  Compare against `Settings` in [src/core/config.py](../apps/api/src/core/config.py).
- **`docs/STATUS.md` is two sprints stale.** It still describes Sprint 1 (39
  tests, 3 endpoints, 8 tables, "blocked on Docker"). Reality: 75 tests, 10
  endpoints, 13 tables (incl. partitioned `events` with 14 partitions),
  4 migrations, Docker running. Rewrite §1–§4; keep the honest tone.
- **`docs/03_API_SPEC.md` §2** does not document `POST /auth/mfa/enroll` /
  `enroll/confirm` (spec'd verification but not the enrolment it presupposes).
  Add them; note the enrolment-token flow.

### 3.2 Finish Sprint 4: the api-client drift gate

`packages/api-client` exists and typechecks, but the **CI drift gate — the
entire point per README ("with a CI drift gate") — is not wired.** Add to
`api.yml` after the "Export OpenAPI" step:

```yaml
- name: api-client drift
  working-directory: packages/api-client
  run: |
    npm ci
    npm run generate
    git diff --exit-code -- src/schema.gen.ts
    npm run typecheck
```

`src/schema.gen.ts` must be committed for `git diff --exit-code` to mean
anything. `apps/api/openapi.json` is deliberately gitignored (regenerated);
the generated *client* is the committed artifact.

### 3.3 Remaining Phase 1 (sprint 5 of ~5)

From [STATUS.md §4](STATUS.md) and the Phase 1 demo target ("two tenants
resolving to different themes; login with MFA; an empty admin shell"):

- **arq worker skeleton** (`src/workers/` is an empty package; Redis is up).
  First two jobs: extend `events` partitions monthly (0004 bootstraps only
  ~13 months), and purge expired `refresh_tokens` / `magic_links` rows.
- **Tenant themes** (`tenant_themes` table per 02 §4.3) + surfacing
  `tenant.settings` so two hostnames render differently.
- **Empty admin shell** — first `apps/web` scaffold (Next.js 15, port 3010),
  consuming `@ttli/api-client`.
- **Password reset flow** — same single-use hashed-token machinery as magic
  links (04 §1.2 says 30 min); mostly copy the existing pattern.

## 4. Known weaknesses to review (none are gate failures; all are real)

Ordered by risk:

1. **MFA challenge tokens are replayable.** The `mfa_token` from a 202 login is
   a stateless JWT valid 5 minutes and *not* invalidated after successful
   verify — verify twice, get two token families. Fix: single-use marker in
   Redis keyed on the token's hash (same pattern as rate limiting), or a `jti`
   denylist. [src/routers/auth.py](../apps/api/src/routers/auth.py) `mfa_verify`.
2. **Device fingerprint is stored, never checked.** 04 §1.2 says refresh
   tokens are "device-bound"; `tokens.rotate()` carries the fingerprint
   forward but does not compare it. Decide: enforce (reject mismatched
   rotation) or downgrade the doc claim.
3. **Rate limiter details** ([src/services/rate_limit.py](../apps/api/src/services/rate_limit.py)):
   fixed-window (2× burst at window edges — acceptable per spec, but note it);
   `INCR` then `EXPIRE` non-atomic — a crash between them leaves an immortal
   key. A 5-line Lua script or `SET ... NX EX` + `INCR` fixes both. Also: only
   login + magic-link-request are limited; 03 §1.8 also lists guest signup,
   verification, heartbeat (future endpoints — wire the helper in as they land).
4. **No negative caching for unknown hostnames.** `get_or_resolve_tenant`
   caches hits only; a flood of requests with bogus `X-Tenant-Host` values hits
   Postgres every time. Cache the miss for ~10s.
5. **`X-Tenant-Host` is client-controllable.** Harmless while the token's
   `tid` claim is cross-checked (`get_principal` does), but the production BFF
   **must strip inbound `X-Tenant-Host`** — record that in 06_OPERATIONS when
   the web tier lands.
6. **`sync_database_url` derivation footgun.** If `DATABASE_URL_SYNC` is unset
   it derives from `DATABASE_URL` — which is now `app_user`, who cannot CREATE
   ROLE. Migrations would fail confusingly. Consider making
   `DATABASE_URL_SYNC` required, or asserting the derived URL isn't app_user's.
7. **Email failures are swallowed** (`services/email.py` logs and continues —
   correct for enumeration safety on magic links, but there's no retry/queue.
   Move sends onto arq when workers exist.)
8. **Migration 0002 reads `os.getenv` directly**, not pydantic Settings — so
   running `alembic downgrade`/`upgrade` from a shell without the break-glass
   env vars exported silently skips seeding the admin (bit me this session;
   the RLS "no seeded user" skip was the symptom). Align it with Settings or
   document loudly in the migration docstring.

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
