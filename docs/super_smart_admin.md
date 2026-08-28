# Super Smart Admin Guide

A practical, task-oriented companion to the formal docs — deployment,
setup, day-to-day management and the account model, written for the
person who actually runs this platform. It doesn't replace
[docs/06_OPERATIONS.md](06_OPERATIONS.md) or
[docs/04_SECURITY_AND_COMPLIANCE.md](04_SECURITY_AND_COMPLIANCE.md);
it points into them and adds what those documents don't cover: exact
commands, the mistakes that actually happen, and how to tell a real
problem from expected behaviour.

**Where things stand**: Docker Compose locally, Azure South Africa
North documented as the production target but not provisioned yet
([06 §4.2](06_OPERATIONS.md#42-later-azure-south-africa-north)). Every
"Deployment" instruction below is for local/staging use today; the
Azure blueprint is the plan, not yet a running thing.

---

## 1. Deployment

### 1.1 Local development, start to finish

```bash
cp .env.example apps/api/.env
docker compose -f infra/docker-compose.yml up -d   # Postgres, Redis, Garage, Mailpit, ClamAV

cd apps/api
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt   # once
.venv/Scripts/alembic upgrade head
.venv/Scripts/uvicorn src.main:app --reload --port 8010
PYTHONIOENCODING=utf-8 .venv/Scripts/arq src.workers.main.WorkerSettings    # second terminal

cd packages/api-client && npm ci          # once
cd apps/web && npm install && npm run dev # :3010
```

`scripts/dev-up.sh` (Git Bash) does the Compose-up-and-print-commands
part of this for you. `scripts/gates.sh` runs the same checks CI does
locally before you push.

**The step everyone forgets**: `.env.example` ships with `SECRET_KEY`,
`FIELD_ENCRYPTION_KEY` and `BLIND_INDEX_KEY` all blank on purpose —
"nothing here is a working secret." Leave them blank and you don't get
a clean error, you get a 500 on the *login* endpoint with a buried
traceback (`jwt.exceptions.InvalidKeyError: HMAC key must not be
empty`), while the frontend just shows "Those credentials are not
valid" — which sends you chasing the wrong bug. Generate real values
before you start uvicorn, using the commands `.env.example` already
has next to each field:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"                          # SECRET_KEY
python -c "import base64,os; print(base64.b64encode(os.urandom(32)).decode())"        # FIELD_ENCRYPTION_KEY
python -c "import base64,os; print(base64.b64encode(os.urandom(32)).decode())"        # BLIND_INDEX_KEY (a *different* run — never derive one from the other)
```

For a disposable local database it doesn't matter that these are
freshly generated each time you rebuild the environment. It matters a
great deal for anything with real data — see §2.1.

### 1.2 CI/CD gate

Every push runs, and every one of these actually blocks a merge:

- `ruff` + `mypy` + `pytest` (full suite, real Postgres/Redis — see
  §1.4 for what "real" enforces)
- Alembic check + round-trip (migration reversibility)
- `api-client` drift check (generated OpenAPI types match the live
  schema)
- Web `typecheck` + `lint` + `build`
- `gitleaks` full-history secret scan
- Playwright e2e (`authenticated-e2e` job — real browser journeys
  against a real running stack)
- **Trivy container scan — blocking**, `.github/workflows/ci.yml`'s
  `quality` and `images` jobs. `--exit-code 1 --ignorefile
  .trivyignore`: a genuinely new CRITICAL/HIGH finding fails the
  build. `.trivyignore` at the repo root lists exactly what's already
  reviewed — each entry is a real CVE this project doesn't control
  (an upstream package with no patch yet, or a binary bundled inside a
  third-party image) with a comment explaining why and an `exp:` date
  90 days out. Past that date the exception stops applying and the
  build fails again until someone re-reviews it — it's designed to
  force a periodic look, not to become a permanent blind spot.

If Trivy fails CI on something *not* already in `.trivyignore`: that's
real and new. Check whether a newer base image tag fixes it first
(`docker buildx imagetools inspect <image>:<tag>` — no pull needed);
only add it to `.trivyignore` once you've confirmed there's genuinely
no fix available yet, with the same reasoning-plus-date format the
existing entries use.

### 1.3 Container images

`apps/api/Dockerfile` and `apps/web/Dockerfile` pin their base images
by digest (`FROM image:tag@sha256:...`), not just a tag. A mutable tag
lets whoever controls the upstream registry change what a production
build actually pulls, silently. Re-resolve deliberately, not on a
schedule:

```bash
docker buildx imagetools inspect python:3.12-slim   # or node:24-slim
```

Take the **index digest** (multi-arch manifest list), not a
platform-specific one — that's what keeps a pull resolving correctly
on both amd64 and arm64 dev machines. `infra/docker-compose.yml`'s
third-party images (Postgres, Redis, Garage, Mailpit, ClamAV) are
pinned the same way where they've been reviewed; check
`docs/STATUS.md` §10 for the last review pass on those.

### 1.4 What "real tests" means here

`apps/api/tests/conftest.py` hard-fails the suite (`pytest.exit`,
exit code 1) if integration-marked tests are selected but Postgres or
Redis aren't reachable — it does not silently skip them and report
green. If you need to run the pure-unit subset with services down,
set `ALLOW_SKIP_INTEGRATION=1`. This exists because a suite that
quietly skips its own integration coverage is worse than no suite —
it looks green for the wrong reason.

### 1.5 Production (not yet live)

Full blueprint: [06 §4.2–4.5](06_OPERATIONS.md#42-later-azure-south-africa-north).
The one mechanism worth knowing about ahead of time:
`check_production_safety()` runs at API boot and **refuses to start**
if `ENVIRONMENT=production` and any of: debug mode on, break-glass
admin enabled, SSO required but disabled, dev storage credentials
still set, TLS off, or no Sentry DSN configured. It returns the actual
list of what's wrong, not a bare failure — read the boot log, not just
the exit code.

---

## 2. Setup

### 2.1 Environment variables that must not be reused from dev

`.env.example` documents every variable inline. These four are the
ones where reusing a convenient placeholder is actively dangerous
rather than just sloppy:

| Variable | Why it matters |
|---|---|
| `SECRET_KEY` | Signs every access/refresh token. Rotate it and every issued session is invalidated at once — plan a rotation, don't do it by accident. |
| `FIELD_ENCRYPTION_KEY` | Encrypts PII at rest (emails, payment references, etc.). **Losing this key means that data is unrecoverable, not just re-encryptable** — back it up somewhere that isn't this repo or this server. |
| `BLIND_INDEX_KEY` | Powers lookup (e.g. "find the user with this email") without decrypting every row. Must be a genuinely separate key from `FIELD_ENCRYPTION_KEY` — deriving one from the other defeats the point of having two. |
| `BREAK_GLASS_ADMIN_PASSWORD` | Only reachable at all when `BREAK_GLASS_ADMIN_ENABLED=true`, which `check_production_safety()` refuses in production anyway (§1.5) — but don't rely on that as the only reason to change it locally. |

If you rotate `FIELD_ENCRYPTION_KEY` without a re-encryption migration,
existing encrypted fields become unreadable — the app degrades
gracefully (shows `(unreadable — key rotated)` rather than crashing or
guessing), which is correct behaviour, not a bug to chase. Seeing that
message means exactly one thing: the row in front of you was written
under a different key than the one currently configured.

### 2.2 Seed data (local/dev only)

Three scripts, run from `apps/api` with the venv active:

```bash
.venv/Scripts/python scripts/seed_e2e_accounts.py     # 10 named test accounts, various roles — idempotent
.venv/Scripts/python scripts/seed_demo_content.py      # 5 real programmes + podcast/article/recommendation, published and priced
.venv/Scripts/python scripts/seed_demo_enrolment.py [slug]   # one demo learner, enrolled in a real course
```

All three check `settings.environment` and refuse to run against
anything but `local`/`development`/`dev` — they can't be pointed at
production by accident. `seed_e2e_accounts.py` is also what Playwright
e2e specs authenticate as; the same tenant accumulates their fixture
data over repeated runs (`E2E Assessment Course a1b2c3`-style rows) —
harmless for testing, but filter it out (e.g. `?level=executive`) if
you're using the local catalogue to demo or screenshot anything.

### 2.3 Tenant onboarding

Full checklist: [06 §7.5](06_OPERATIONS.md#75-tenant-onboarding) — DNS,
TLS, theme, SSO, MFA enforcement, monitoring, the works. The two demo
tenants seeded by migration `0002` (`demo` → `localhost`, `acme` →
`meridian.localhost`) are the reference for how domain-to-tenant
mapping actually works (`tenant_domains.hostname`, resolved from
`X-Tenant-Host` or the `Host` header — `apps/api/src/core/tenancy.py`).

---

## 3. Management — the admin dashboard, section by section

Everything below lives under `/admin` for an account with the
`admin` or `super_admin` role. Nav order, roughly grouped by what
you'd actually be doing:

**Running the business**
- **Operations** — the landing dashboard: revenue MTD, active
  learners, payments awaiting approval, submissions awaiting review,
  learners at risk. Start here.
- **Leads** / **Deals** / **Campaigns** — the CRM spine: enquiry
  capture through to a closed deal, and the email campaigns that feed
  it.
- **Payments** — EFT and purchase-order approvals specifically
  (`payment:approve`). Card payments settle automatically; these are
  the ones that need a human to confirm the money actually arrived.
- **Analytics** / **Reports** — dashboards and per-course completion
  reports. **Reports → Courses → [course]** is where a manager's
  "individual results" visibility rule (§4) actually gets applied.
- **Audit log** — every permission-gated write, who did it, when.
  Read-only, `audit:read`.

**Running the content**
- **Courses** / **Learning paths** / **Catalogue** — course
  authoring, multi-course bundles, and pricing/visibility. Course
  publishing is a *gate*, not a checklist you can skip past — see
  [06 §7.6](06_OPERATIONS.md#76-course-publishing) for the full
  eleven-point list the publish endpoint actually enforces.
- **Workshops** — facilitators, sessions, bookings, attendance for
  live (Teams-based) sessions.
- **Podcasts** / **Articles** / **Recommendations** — the free/public
  content that feeds the marketing site, separate from paid courses.
- **Grading** — open-ended assessment answers that need a human score
  (`quiz:grade`) — auto-graded quiz questions never appear here.
- **Question bank** — the shared pool of reusable quiz/survey
  questions courses draw from.

**Running the org**
- **People** — every user on the tenant: role assignment, suspension,
  invites.
- **Subscriptions** — the renewing-access bundles (Full Library,
  Leadership Track, etc.) as distinct from one-off course purchases.
- **Templates** — certificate and email templates.
- **Settings** — tenant-level configuration: theme, manager-visibility
  defaults, SSO, the things §2.3's onboarding checklist walks through
  once and rarely touches again.

---

## 4. Accounts, roles and permissions

Permissions are strings (`course:edit`, `payment:approve`, …); roles
are named bundles of them. Full model:
[04 §2.2–2.4](04_SECURITY_AND_COMPLIANCE.md#22-roles-and-permissions).
The roles that exist today:

| Role | Roughly | 
|---|---|
| `guest` | Anonymous/free-lesson access — `course:view` only |
| `learner` | Can enrol and complete lessons |
| `content_author` | Authors and publishes courses, grades assessments |
| `finance` | Orders, invoices, EFT/PO approval, refunds — nothing else |
| `admin` | Everything above minus finance and tenant-level config |
| `super_admin` | Every permission that exists |

Four ABAC rules sit on top of role checks and matter more than the
role table for anything involving cross-tenant or cross-person data —
lesson access, a manager viewing an individual's results, finance
access, and AI processing all require every condition in their
predicate to hold, not just the base permission. **P2** (manager
viewing individual results) is the one to know cold: it defaults to
aggregate-only, and a false condition means the individual rows are
*absent* from the response, not present-and-redacted — that's a
deliberate anti-bullying control, not a preference. Full predicates:
[04 §2.3](04_SECURITY_AND_COMPLIANCE.md#23-abac-policies).

**Break-glass admin**: `BREAK_GLASS_ADMIN_ENABLED=true` seeds one
admin account from `BREAK_GLASS_ADMIN_EMAIL`/`_PASSWORD` at migration
time — the only account that exists before you've created anyone
else. `check_production_safety()` refuses to boot with it enabled in
production, so this is a local/staging-only escape hatch, not a
standing production account.

**Organisations** are self-service: any authenticated user can start
one (`POST /organisations`) and becomes its first admin — there's no
separate "org signup" flow. That's how "buying for a team" works from
the customer side: sign in, create (or join) an organisation, buy
seats, invite people.

**Impersonation** (`user:impersonate`) requires MFA re-authentication,
is time-boxed to 30 minutes, shows a persistent banner to whoever's
impersonating, and is audited on entry and exit. It never grants
Finance permissions regardless of who's being impersonated.

---

## 5. Troubleshooting — real problems hit while running this

- **Login returns "Those credentials are not valid" but the account
  and password are definitely right.** Check the API's own log before
  trusting the frontend message — that copy is a generic fallback for
  any non-2xx response, including a genuine 500. The actual cause seen
  here: `SECRET_KEY` blank → JWT signing throws → 500 → frontend shows
  the generic invalid-credentials copy. Fix per §1.1.
- **A field shows `(unreadable — key rotated)` instead of real
  content.** Not a bug — `FIELD_ENCRYPTION_KEY` in your current
  environment doesn't match the key that encrypted that row. Expected
  after restoring a database dump into an environment with a
  different key, or after seeding fresh data with a placeholder key
  in a database that already had rows from an earlier, different key.
- **A migration or seed script throws `ValueError: encryption key
  must be 32 bytes`.** `FIELD_ENCRYPTION_KEY` or `BLIND_INDEX_KEY` is
  blank or malformed — see §1.1 for the exact generation commands.
- **Disk fills up and Docker starts returning 500s / hanging on
  `docker ps`.** Watch free space proactively during any local
  session with the stack running — `df -h` (or `Get-PSDrive C` in
  PowerShell). Docker Desktop on Windows/WSL2 does not reliably shrink
  its `docker_data.vhdx` back down after cleanup; when Docker itself
  becomes unresponsive, that's usually the proximate cause, but it is
  not the only thing that can fill a disk fast — treat "what's
  actually consuming space" as its own investigation rather than
  assuming Docker every time.
- **A container shows `Exited` instead of `Up` after the host was
  under disk pressure.** `docker compose -f infra/docker-compose.yml
  up -d` restarts existing containers without recreating them or
  touching their volumes — data survives. Only Mailpit tends to show
  `Recreate` on a routine `up -d` (its image tag changes more often
  than the others get bumped).
- **`npm run dev` or `uvicorn` exits with no error in the log.**
  Confirm the process is actually still running (`tasklist` /
  `Get-Process`) and the port is listening (`netstat -ano | grep
  :3010`) before assuming a real crash — under resource pressure a dev
  process can be killed by the OS without writing anything to its own
  log. Restart it and re-check; if it dies again immediately, *then*
  read the log for a real stack trace.
