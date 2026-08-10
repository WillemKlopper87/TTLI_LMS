# HANDOFF — for the next agent

**Written:** 2026-08-08, end of the session that built Sprints 2–4 of Phase 1.
**Updated:** 2026-08-09, three times. Second pass closed §4's last item
(work committed, drift gate wired, all eight ranked weaknesses fixed with
tests, Sprint 5's worker + password reset + tenant themes + `apps/web` all
built — [STATUS.md](STATUS.md) carries current numbers: 85 tests, 13
endpoints, 6 migrations). Weakness 7 closed last: `send_email` now enqueues
a `send_email_job` (arq, `max_tries=5`, real delivery verified against
Mailhog in both local dev and CI) instead of sending inline — see
`src/core/queue.py`, `src/services/email.py`, `src/workers/main.py`.

**Third pass: the repo is published and CI is verified green.**
`https://github.com/WillemKlopper87/TTLI_LMS` (private). The *first-ever*
run failed immediately — `psql "$DATABASE_URL_SYNC" -f ...` in the "Create
extensions" step doesn't understand SQLAlchemy's `postgresql+psycopg2://`
scheme, so it silently fell back to a nonexistent local socket. That step
had been sitting unchanged since the original Sprint 1 commit and had
genuinely never executed until that run — exactly the class of bug the
whole point of running CI was to surface, and the local dev loop (Windows,
Python 3.11, `docker exec ttli-postgres psql` directly) could never have
caught it. Fixed with explicit `-h`/`-p`/`-U`/`-d` flags instead of the URI.
The second run — Python 3.12, Ubuntu, first time either had touched this
code — passed every step end to end, including the zero-skip integration
assertion, the migration round-trip, drift check, and the api-client drift
gate: [run 31318484520](https://github.com/WillemKlopper87/TTLI_LMS/actions/runs/31318484520).

**Fourth pass: upgraded to Next.js 16** (`15.5.23` → `16.3.0`). The impact
analysis referenced above turned out right — the app was built
async-API-clean from the start (already awaited `params`/`headers()`
everywhere), already on React 19.2.8 and TypeScript 5.9.3, so almost none of
16's breaking-change list applied. The one real hit: Turbopack, 16's new
default builder for `dev`/`build`, cannot resolve `@ttli/api-client` through
the `file:../../packages/api-client` npm-workspace symlink — confirmed as a
known, still-open upstream limitation (`vercel/next.js#85316`, `#88335`,
`#77562`), reproduced even after adding an explicit `"exports"` field to
that package. Fix: both scripts now pass `--webpack`
(`apps/web/package.json`), which resolves it exactly as Webpack (15's
default) always did — `apps/web/next.config.ts` documents why, so nobody
"cleans up" the flag later. Revisit once those upstream issues close.
Verified clean: `npm ci` from lockfiles in both `packages/api-client` and
`apps/web`, `typecheck`, `build`, and the full two-tenant HTTP smoke test
(including a POST through the BFF to `/auth/login`) — all pass identically
to the pre-upgrade run. A `web` job was added to `.github/workflows/api.yml`
in the same pass (installs `packages/api-client` first, since its own
dependencies — `openapi-fetch` — resolve from *its* `node_modules`, not
`apps/web`'s, once symlinked in); the workflow's internal `name:` is now
`ci` to reflect that it covers both apps (filename kept as `api.yml`).
Pushed, and — unlike the first CI run ever, which needed a real fix — this
one was green end to end on the first try, `quality` and the new `web` job
both: [run 31319510689](https://github.com/WillemKlopper87/TTLI_LMS/actions/runs/31319510689).

**Fifth pass: first Phase 2 backend work** — the three pieces that don't
depend on any of Phase 0's ten open decisions (§6 said as much; this is that
guidance acted on). Migration `0007` adds `contacts` (encrypted PII, same
pattern as `users`), `leads` (deliberately *not* the full CRM — 02 §10 names
eleven more tables, `deals`/`tasks`/`campaigns`/etc., that stay Phase 5;
this is only what `POST /leads` needs), and `consent_records` (append-only,
copied exactly from `audit_events`' two-layer enforcement). `POST /leads`
merges progressive-profiling fields into one lead row per contact across
repeat submissions rather than duplicating rows — worth knowing before
"fixing" it into an insert-only table. Separately, `src/models/event.py`'s
`events` table had existed since Sprint 3 with nothing writing to it;
`src/services/events.py` is that write path, now called from login
(success/failure), magic-link request, password-reset request, refresh
reuse detection, and lead capture. Read `src/services/events.py`'s
docstring before adding more call sites — the `consent_analytics=True`
default is a documented, deliberately narrow stretch of 04 §5.1's
anonymous-analytics allowance, not something to copy uncritically onto a
marketing surface. 6 new tests (`tests/test_leads.py`), migration
round-trips, 91 tests total, 0 skipped. Pushed as `90d334c`; CI green on
both jobs — https://github.com/WillemKlopper87/TTLI_LMS/actions/runs/31320338691
(1m47s, quality + web).

**Sixth pass: real TTLI brand replaces the placeholder navy/gold.** The
`demo` tenant's name and theme were always invented — "TTLI Executive
Institute" and a navy/gold palette nobody chose. Fetched
`https://ttli.co.za/`, the actual customer's live site, and extracted its
real name (Themba Thandeka Leadership Institute), logo, and color palette
(`#8E151C` primary, `#BC222A` secondary — pulled from the site's own CSS and
cross-checked against the logo SVG's fill colors, not guessed).
[docs/brand/ttli-brand-identity.md](brand/ttli-brand-identity.md) is the
provenance record — what was extracted, from where, and what was
deliberately left out (no brand typeface was identifiable; contact
details weren't listed on the page). Migration `0008` applies it to the
`demo` tenant only — `acme` stays on its own placeholder palette on
purpose, since it exists to prove per-tenant theming actually differs
per tenant. `apps/web/app/page.tsx` and `admin/page.tsx` now render
`theme.logo_url` when a tenant has one (falling back to the old
text-badge treatment for tenants without a logo, e.g. `acme`); the logo
is served as a PNG, not the SVG, because `next/image` disables SVG
optimization by default as an XSS precaution and the PNG needed no
config change. The SVG is still saved in `apps/web/public/brand/` as the
archival vector source. Verified: migration round-trip, `alembic check`
clean, `apps/web` `typecheck` and `build` clean, and a live HTTP smoke
test against both demo tenants — confirmed the TTLI (`demo`) login page
renders the real title/colors/logo while `acme`'s theme response is
byte-for-byte unchanged. Pushed as `9f4b631`; CI's `quality` job failed
first try on `ruff format --check` — the migration file had been through
`ruff check` locally but not `ruff format`, a gate-sweep gap worth
remembering. Fixed and pushed as `b161f18`; green on both jobs —
https://github.com/WillemKlopper87/TTLI_LMS/actions/runs/31321303793
(1m31s, quality + web).

**Seventh pass: admin lead view + guest-access provisioning — the two
Phase 2 pieces no open decision blocks.** Asked rather than guessed
scope (§6 already said Phase 0 gates most of Phase 2); the user picked
both. `GET /leads` (`src/services/leads.py::list_leads`) is paginated,
tenant-scoped, and gated on `analytics:view` — the seeded admin role
already carries that permission (0002), so this needed no new
permission or migration, just the first real use of
`Principal.require()`, which had existed unused in `core/deps.py` since
Sprint 2. `apps/web/app/admin/` gained a shared `layout.tsx` (auth
check + sidebar, previously duplicated into `page.tsx` — factored out
now that a second page needs it) and `admin/leads/page.tsx`.

`POST /guest-access` (03 §4.2, REQ-LEAD-04/05/06) reuses
`leads.capture()` first — every guest account is unique per lead — then
creates or reuses a `users` row via `identity.create_user(is_guest=True,
...)`, which already existed unused since Sprint 1. Decision #6 (7 vs 14
days) is still unsigned, so the window is `settings.guest_access_days`
(default 7), not a hardcoded guess. Two real bugs surfaced while making
"time-limited" actually true, since neither enforcement point existed
before this pass needed them:

1. `identity.consume_magic_link()` didn't check `guest_expires_at` at
   all — an expired guest's link would still work. Fixed with one
   comparison.
2. `tokens.rotate()` had the same gap for refresh tokens, but the fix is
   *not* as simple as adding a WHERE clause to the existing consuming
   UPDATE: that statement's failure path is reuse/theft diagnosis
   (`RefreshTokenReused`), and an expired guest is not a theft signal.
   Folding the two together would revoke the token family and fire a
   `TOKEN_REUSE_DETECTED` audit event for what is just expiry — a false
   security signal. Added a separate `GuestAccessExpired` exception,
   checked before the consuming UPDATE runs, so the two failure modes
   stay distinguishable both in code and in whatever alerts on that audit
   action later.

The hourly guest-expiry downgrade sweep (02 §12.4) still doesn't exist —
deliberately deferred, documented in `services/guest_access.py`'s
docstring and STATUS.md §5. It's `status`-column bookkeeping, not access
control; the two enforcement points above are what actually gate access,
and they don't depend on a cron job existing.

Verified: 101 tests (0 skipped, up from 91 — `tests/test_leads.py` +2,
new `tests/test_guest_access.py` +8), `ruff check`/`format`/`mypy` clean,
`alembic check` clean (no schema change — `is_guest`/`guest_expires_at`
already existed), `apps/web` `typecheck`/`build` clean, api-client
regenerated from the new `openapi.json`. Live HTTP smoke test against
real running servers: `POST /guest-access` through the real BFF → 204 →
confirmed a magic-link email actually arrived in Mailhog via the arq
worker (not just enqueued) → logged into an admin account and confirmed
the lead appears on `GET /leads` with correct decrypted fields. One
smoke-test surprise worth recording: paging through *all* historical
leads in the shared local dev Postgres hit `cryptography.exceptions.
InvalidTag` on older rows — contacts encrypted under a different
`FIELD_ENCRYPTION_KEY` than the currently configured one, accumulated
across this session's earlier test runs. Confirmed via targeted queries
that this is dev-database cross-session pollution, not a bug in
`list_leads()` — the newly created rows all decrypt fine, and the
automated test suite (which doesn't share that stale data) passed
cleanly. Not fixed here — it's local dev-environment hygiene, not
shippable code; a fresh `docker compose down -v && up` would clear it.
Pushed as `f6b3b70`; green on both jobs on the first try —
https://github.com/WillemKlopper87/TTLI_LMS/actions/runs/31322764499
(1m52s, quality + web).

**Eighth pass: Phase 3 sprint 1 — commerce foundation and the full EFT
purchase path.** With Phase 2's decision-independent slice done, §6 named
Phase 3/4 as next — but unlike Phase 2, both are blocked at the *root* by
unsigned decisions (VAT #2 and subscriptions #5 for commerce; SCORM/xAPI #1
and the DRM/watermark question #3 for the LMS content model). Asked the
user how to proceed rather than guessing scope; told to attempt it anyway,
using the same placeholder-not-guess pattern already established
(`guest_access_days`, `tenant_themes`'s seed colors). It worked here too:
02 §6.5 already says tax is data ("it lives in a row, not a constant"), so
migration `0009` seeds only South African domestic VAT — the one rate not
in question — and `services/tax.py` refuses the international case with a
specific, honest reason instead of inventing a rate. Subscriptions aren't
touched at all.

Scoped to one complete vertical slice — EFT — rather than three partial
ones: EFT needs no third-party account (card checkout needs live
Payfast/Netcash sandbox credentials, still on Phase 0's outstanding list;
PO capture was cut for scope, not blocked). `0009` adds 11 tables:
`products`, `prices`, `tax_rules`, `orders`, `order_items`, `payments`,
`invoice_number_counters`, `invoices`, `invoice_items`, `ledger_entries`
(append-only, same two-layer pattern as `audit_events`), `entitlements`.
`services/invoicing.py` implements REQ-PAY-09's sequential, gapless
numbering exactly as 02 §6.4 specifies — a per-`(tenant_id, series)`
counter locked with `SELECT ... FOR UPDATE` inside the issuing transaction,
not a Postgres sequence (non-transactional, leaves gaps on rollback).
`services/orders.py` drives the state machine end to end: create → EFT
checkout → proof upload → finance approves or rejects; approval issues the
invoice, grants entitlements and writes two ledger entries, all in one
transaction, matching 02 §6.2's "never before `fulfilled`" rule.

Live HTTP smoke testing (not just automated tests) caught two real bugs
before they shipped:

1. `create_order()` flushed the `Order` row *before* resolving each line's
   tax — so a refusal partway through (an unresolvable tax case, a bad
   `price_id`) left an orphaned empty `draft` order behind. `get_session()`
   commits whatever an `AppError` leaves flushed, by design, for auth
   bookkeeping (§2.3 above) — that same mechanism silently created data
   debris here. Fixed by resolving and validating every line *before*
   writing the order at all — a two-phase create, not one interleaved loop.
2. `_generate_payment_reference()` derived the reference from
   `order_id.hex[:10]` — but a UUID7's first 12 hex characters are its
   millisecond timestamp (`core/ids.py`), so two orders created in the same
   millisecond got an *identical* reference, colliding on the unique
   index. Only surfaced because a test created two orders back-to-back and
   failed intermittently — passed in isolation, failed under the full
   suite, which was the tell. Fixed by slicing from `hex[12:22]` instead,
   into the random portion; verified with a 5000-iteration collision test
   (0 collisions) and a live 5x rapid-fire smoke test.

Deferred, and tracked in STATUS.md §6 rather than silently dropped:
`Idempotency-Key` handling (03 §1.6) — the state-machine checks already
refuse a genuine double-submission with 400 rather than silently
re-processing it, so the financial harm (double invoice, double
entitlement) is prevented even without full replay semantics; virus
scanning on the payment-proof upload (04 §2, REQ-BYPASS-08) — no scanning
engine exists in this project at all, flagged explicitly rather than
pretended-away; credit notes/refunds; card and PO checkout.

Also fixed in this pass, unrelated to commerce: `apps/api/var/` (the local
storage adapter's on-disk root) was never gitignored and had payment-proof
test artifacts sitting untracked — added to `.gitignore`.

Verified: 110 tests (0 skipped, up from 101 — new `tests/test_commerce.py`,
9 tests), full gate sweep, migration round-trip, `alembic check` clean,
api-client regenerated, `apps/web` build/typecheck clean (no web changes
this sprint). Live smoke test: full EFT happy path (order → checkout →
proof → approve → invoice `INV-000001`, correct VAT, entitlement granted,
two ledger entries) and reject → resubmit → approve, both over real HTTP
against a running server, plus the append-only ledger genuinely refusing a
raw `UPDATE`. Pushed as `a26b753`; green on both jobs on the first try —
https://github.com/WillemKlopper87/TTLI_LMS/actions/runs/31324955958
(1m45s, quality + web).

**Ninth pass: `apps/web` gets a real design system, real content, and UI
for the whole EFT purchase path.** The user asked for two things together
— restyle `apps/web` to match the interface prototype (the 11-screen
journey mockup, `docs/brand/` provenance), and start building the screens
that don't exist yet — then mid-turn, separately, asked for the real
ttli.co.za content (copy, images, team, client logos) to go into the new
design rather than the prototype's invented course names. Both landed in
this pass.

*Design system.* The prototype's tokens (Charter serif, stone/surface
neutrals, `.btn`/`.tag`/`.card` components) are now in
`apps/web/app/globals.css`, bridged onto the existing tenant-driven
`--brand-primary`/`--brand-secondary` rather than replacing them —
`--brand-wash` is computed with `color-mix()`, not hardcoded, so it stays
correct for any tenant's color, not just TTLI's red. Login, the admin
shell, and the leads table were restyled onto it.

*Real content, not fiction.* A second extraction pass on ttli.co.za (the
first only got colors/logo) pulled the actual About narrative, the "90+
organisations, 19 countries" line, five real facilitator names/photos/
roles, nine real client logos (Standard Bank, HENSOLDT, De'Longhi,
Floorworx, ITEC Evolve, Shangoni, Earthlab, TWK, Barberton Mines), and the
founder's book *Lead with Intent* — all with provenance in
[docs/brand/ttli-brand-identity.md](brand/ttli-brand-identity.md), which
also flags that the team's personal emails/cellphone numbers are real and
sensitive even though TTLI publishes them themselves — carried into this
build for its narrow stated purpose (rebuilding this company's own site
with its own content), not redistributed further. Deliberately **not**
fabricated: testimonials (the real site has none), and stats beyond the
one track-record line.

*Routing changed*: `/` was the login page; it's now the real marketing
landing page (`apps/web/app/page.tsx`), and login moved to `/login`. Every
`router.replace("/")` in `admin/layout.tsx` had to move to `"/login"` with
it — check for that pattern before adding new auth redirects.

*New screens, all backed by real endpoints* (no fabricated data): `/login`
(moved), `/guest-access` (posts to the `POST /guest-access` this project
already had), `/catalogue` (new `GET /products`, listing the real seeded
product — not the prototype's "Leading Through Ambiguity"), `/checkout`
(customer-type → `POST /orders` → `POST .../checkout/eft` → proof upload,
the full REQ-PAY-03 path with a UI now, not just an API), `/admin/payments`
(new `GET /payments`, the finance approve/reject queue). Screens that
still cannot be built with real data — the course player, quiz, certificate
verification, corporate manager view — need Phase 4/5 backend that doesn't
exist (lessons, quizzes, certificates, organisations); building UI for
those now would mean fabricating the very data this pass was about not
fabricating, so they're still just the prototype's wireframe, not ported.

*A real bug, caught by testing the file upload for real*: the BFF proxy
(`apps/web/app/api/bff/[...path]/route.ts`) forwarded every non-GET
request body through `request.text()`. That's fine for JSON but silently
corrupts binary content on the UTF-8 decode/re-encode round-trip — exactly
what the new payment-proof upload does. Fixed by switching to
`arrayBuffer()` on both the request and response side. Verified properly,
not just "it returned 204": uploaded the real *Lead with Intent* JPEG
through the actual running BFF and diffed the stored file against the
original — identical size, identical MD5. Test this exact way (upload a
real binary, hash-compare what lands in `apps/api/var/storage/`) if you
touch this proxy again; a 204 alone would not have caught the corruption.

Verified: 113 tests (0 skipped, up from 110 — `tests/test_commerce.py`
gained 3 for `GET /products`/`GET /payments`), full backend gate sweep,
`apps/web` `typecheck`/`build` clean (11 routes), api-client regenerated.
Live smoke test over the real BFF, not mocked: catalogue → order → EFT
checkout → real-file proof upload (hash-verified) → finance queue →
approve → invoice issued, plus a separate guest-access submission. Not yet
pushed/CI-verified as of this note.

Queued next, per the user's own sequencing: the security-hardening pass
discussed earlier in this session — virus scanning on the payment-proof
upload (still not implemented — see the Eighth pass note and STATUS.md
§6), CSP/security headers on `apps/web`, and verifying dependency/
container scanning is actually wired into CI.

**Tenth pass: the security-hardening work queued above.** Three pieces.

*Virus scanning* (04 §3, REQ-BYPASS-08). `src/services/antivirus.py` is a
from-scratch client for clamd's raw INSTREAM wire protocol (4-byte
big-endian chunk-length-prefixed streaming, terminated by a zero-length
chunk) over `asyncio.open_connection` — no `clamd` package added, since the
protocol is small and a dependency would be one more thing to audit.
`upload_payment_proof` in `src/routers/orders.py` scans before the file
ever reaches storage; an infected file is refused with a `400` naming the
signature, and the order stays in `eft_pending_proof` rather than
advancing. **Fails closed**: an unreachable scanner raises
`ServiceUnavailable` (503) rather than accepting the file unscanned — the
one place in this codebase where "the dependency is down" means "refuse
the request", not "degrade gracefully", because degrading gracefully here
means shipping a virus. `infra/docker-compose.yml` gained a `clamav`
service (`clamav/clamav-debian:stable`, port 3410 → clamd's default 3310);
`.github/workflows/api.yml`'s `quality` job gained it too as a real GH
Actions service container — like Mailhog, it needs no launch args (`docker
inspect` confirms `CMD` is just `[clamd]`-equivalent), so it qualifies,
unlike MinIO. `tests/test_antivirus.py` runs three tests against a real
local clamd (clean file, the EICAR standard test string, and an
unreachable-host case) using the same skip-if-unreachable fixture pattern
`test_storage.py`'s S3 path already used — **not mocked**, because a mocked
AV client would never have caught a wire-protocol bug. A fourth test,
`test_infected_payment_proof_is_refused_and_order_does_not_advance` in
`tests/test_commerce.py`, uploads the EICAR string through the real
`/orders/{id}/payment-proof` endpoint and asserts the order state didn't
move. **First run of the full suite after wiring this in showed 62 tests
skipped** — Docker Desktop wasn't even running, so Postgres/Redis/MinIO/
ClamAV were all unreachable and every integration test silently skipped
rather than failing loud. Zero-skip CI (§5 below) is exactly the policy
that exists to catch this class of false-green result; started Docker,
brought the compose stack up, waited for ClamAV's and MinIO's health
checks (ClamAV can take a few minutes on a cold virus-DB download; this
container was already warm from earlier in the session), then re-ran —
**117 passed, 0 skipped.** Don't trust a green local run without checking
`docker ps` first if it's been a while since the stack was touched.

*CSP and security headers.* `apps/web/proxy.ts` (renamed from
`middleware.ts` — Next 16 deprecated the `middleware` file convention in
favour of `proxy`, same function shape, just `export function proxy`
instead of `export function middleware`; the old file's build output
literally printed a migration notice, which is how this was caught).
Generates a random nonce per request and sets a strict CSP —
`script-src 'self' 'nonce-<nonce>' 'strict-dynamic'`, no `unsafe-inline`,
no `unsafe-eval`. Next.js auto-detects the `nonce-` source and applies it
to its own inline hydration/RSC-streaming scripts, so this works without
any extra plumbing beyond the one file — see
[the Next.js CSP guide](https://nextjs.org/docs/app/guides/content-security-policy).
`style-src` keeps `unsafe-inline` deliberately: this app uses React's
inline `style` prop pervasively (`app/checkout`, `app/page.tsx`, etc.) and
Next's nonce mechanism doesn't cover style attributes the way it covers
its own script tags. That's a real but lower-severity gap than script
injection, and every inline style in this app is a literal, never
user-supplied data — revisit if that changes. Also sets
`X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`,
`Permissions-Policy`, and (production-only) HSTS.

*Dependency and container scanning.* `pip-audit` was already wired into
`.github/workflows/api.yml`'s `quality` job as of an earlier pass but had
never actually been run against current pins — running it for real found
**35 CVEs** across `fastapi`/`starlette`, `PyJWT`, `cryptography`, and
`python-multipart`. Fixed with staged upgrades (low-risk packages first,
the FastAPI/Starlette major-version jump last), each stage re-verified
with the full test suite + mypy, the FastAPI/Starlette jump additionally
smoke-tested live including a real multipart file upload through the
now-upgraded `python-multipart` *and* the new virus scanner together.
`pytest`/`pytest-asyncio` also needed bumping in the same pass —
`pytest-asyncio==0.25.0` caps at `pytest<9`, so upgrading `pytest` alone
would have broken the test runner; both moved together
(`pytest==9.1.1`, `pytest-asyncio==1.4.0`). Added `npm audit
--audit-level=high` as its own CI step in both the `quality` job (for
`packages/api-client`) and the `web` job (for `apps/web`) — previously
`npm audit` was never actually run in CI, only ad hoc locally.
`packages/api-client` needed a `js-yaml` override (CVE-2026-59870, a
quadratic-CPU DoS) in `package.json`'s `overrides` field, since the
`openapi-typescript` version that pulls it in transitively was already the
latest release and hadn't caught up upstream yet. **Regenerating the API
client after the FastAPI/Pydantic bump changed `schema.gen.ts` by five
lines** — a docstring-format change on the file-upload field and two new
optional fields (`input`, `ctx`) on the Pydantic validation-error schema —
both are Pydantic's newer version emitting slightly different OpenAPI
metadata, not a sign of anything wrong; committed as part of this pass
since the drift gate requires it to match.

Verified: full gate sweep against the real compose stack (ruff, ruff
format, mypy, 117 tests / 0 skipped, migration round-trip, `alembic
check`, api-client drift + `tsc --noEmit`), `apps/web` `typecheck` and
`build` both clean, `pip-audit` and both `npm audit` runs at 0 findings.
Pushed as `ab58ce7`; green on both jobs on the first try, including the
ClamAV service container's GH Actions `--health-cmd "clamdcheck.sh"`
syntax working correctly on its first-ever run (previously only exercised
via local `docker compose`) —
https://github.com/WillemKlopper87/TTLI_LMS/actions/runs/31332146723
(quality 2m37s, web 49s).

**Eleventh pass, start of a longer arc: Phase 2 close-out, then Phase 4
onward, skipping the rest of Phase 3.** User direction: build forward
through Phases 2/4/4.5/5/6/7 up to whatever is genuinely still blocked by
[01 §1.4](01_PRD.md#14-open-decisions-blocking-phase-0-sign-off), rather
than waiting on the customer. Card/PO checkout (Phase 3's remainder) stay
un-built — blocked on external sandbox credentials, not a choice. Two
things are being built but deliberately kept inert rather than skipped:
Phase 6's AI insights ship fully wired but `tenants.ai_enabled` (already
a spec'd column, 02 §11.2) stays off and demos run on synthetic data only
— decision #4 (may redacted prompts leave South Africa) is the customer's
DPA question, not engineering's, and real learner data going through it
unsigned would breach the residency requirement. Phase 7's Terraform gets
written and load/pen-test/DR-drill/POPIA-matrix work runs against the
local Compose stack; actual Azure provisioning stays parked on decision
#10 (region availability), independent of §5.10's already-settled
"Compose now, Azure later." Everything else has no real Phase-0
dependency left: SCORM (#1) is explicitly out of scope already; the video
launch default (signed HLS + watermark, DRM behind a flag, §5.8) is
already decided regardless of #3; CPD fields (#7) are nullable; brand
(#8) was already worked around with the real extracted TTLI identity.

Closed out Phase 2 first, since it was small: `apps/web/app/contact/` — a
real, working contact form (the live site's own contact page has none,
just contact details) posting to the existing `POST /leads` with
`source="contact_form"`. Rather than a parallel messages table, `0010`
adds a `message` column to `leads` itself, following the exact overwrite
semantics `services/leads.py`'s other progressive-profiling fields already
use (a documented, accepted tradeoff — a second submission from the same
person replaces the message rather than keeping both, fine at this
volume). Surfaces in the admin Leads screen as a new truncated/`title`-
tooltip column. Also `apps/web/app/lead-with-intent/page.tsx`, a dedicated
page for the founder's book using the real extracted copy (previously
only a landing-page teaser existed). **Deliberately not built:** Podcasts
and "Cultivate with Intent" — the real site names both in its nav but no
episode/page content was ever extracted for either; building them now
would mean fabricating copy, the same content-inventory gap Phase 0 is
already blocked on, not a missed task.

Verified: `tests/test_leads.py` gained
`test_contact_form_message_is_captured_and_visible_to_admin`; full backend
gate sweep (ruff, mypy, 118 tests / 0 skipped against the real compose
stack, migration round-trip, `alembic check`); `apps/web` `typecheck` and
`build` both clean (13 routes, up from 11); api-client regenerated for the
new `message` field. Pushed as `0ecbe81`; green on both jobs —
https://github.com/WillemKlopper87/TTLI_LMS/actions/runs/31333417953
(2m34s). Going straight into Phase 4 sprint 1 next (course/module/lesson
content model + completion rule engine + enrolments).

**Twelfth pass: Phase 4 sprint 1 — content model, the completion rule
engine, and enrolments.** `0011` adds `courses`/`modules`/`lessons`
(deliberately **not** tenant-scoped, 02 §1.3) and the tenant-scoped/RLS
`course_tenant_assignments`/`enrolments`/`lesson_completions`.
`Product.course_id` is the real bridge now — `services/orders.py::
approve_eft` resolves the actual `courses.id` instead of the product's own
id used as a stand-in before this sprint (see `services/entitlements.py`'s
old docstring in git history), and creates the enrolment in the same
transaction as the entitlement grant, get-or-create so a repeat purchase
of the same course doesn't violate the one-enrolment-per-course unique
constraint. Both demo tenants' existing seeded products (`0009`) now point
at the one seeded course — genuinely demonstrates the "one course, two
tenant-branded bundles at different prices" shape 02 §6.1 describes, not
just states it.

`src/services/completion.py` is the rule engine (REQ-BYPASS-01/02):
merges course-default and lesson-override `completion_rules` jsonb
per-field (02 §5.2), evaluates `minimum_time_seconds` for real against
server-assigned timestamps, and — this is the part worth reading before
adding a fifth rule field — treats any rule referencing a subsystem that
doesn't exist yet (video, quiz, survey, assignment, live attendance) as
**failed, with a specific reason**, never silently skipped. A lesson
authored with `quiz_pass_score` set must not complete just because no quiz
engine exists to check it against; that would be REQ-BYPASS-01 violated by
omission. `src/services/enrolment.py` is prerequisite enforcement
(REQ-BYPASS-10) — a strict linear chain by `(module.position,
lesson.position)` this sprint, no drip-release or cohorts yet — and the
three learner-facing endpoints (`GET /enrolments`, `GET /enrolments/{id}/
progress`, `POST /lessons/{id}/start`, `POST /lessons/{id}/complete`),
all ownership-gated the same way `routers/orders.py` gates orders. Every
progression decision is audit-logged via `audit_events`, including
refusals (REQ-BYPASS-11) — `AuditAction.LESSON_COMPLETED` /
`LESSON_COMPLETION_REFUSED`.

**A real, pre-existing gap surfaced and fixed along the way**: every login
redirected to `/admin` regardless of role, a harmless no-op back when only
staff accounts existed, but now a real learner buying a real course would
land on the empty admin shell with nothing to do. Fixed in
`apps/web/app/login/login-form.tsx` — after login, fetch `/auth/me` and
route by whether the account holds any staff-gating permission
(`analytics:view`, `payment:approve`); everyone else goes to the new
`/learn`. Same class of bug as the BFF binary-body issue from the ninth
pass: obvious only once there's a real user on the other side of it.

`apps/web/app/learn/page.tsx` ("my courses") and `/learn/[enrolmentId]`
(the lesson checklist — every state and unmet-requirements reason comes
straight from the server, the page does not compute a checklist itself)
are real, working UI, not API-only. Seeded content ("Executive Leadership
Certificate", one module, two document lessons) is explicitly structural
— the same "demo product seeded so the EFT purchase path is exercisable"
precedent `0009` set, not real TTLI curriculum, which was never provided.

Verified two ways. First, the usual gate sweep: ruff, ruff format, mypy,
125 tests / 0 skipped (7 new in `tests/test_learning.py`) against the real
compose stack, migration round-trip, `alembic check`, api-client
regenerated, `apps/web` `typecheck`/`build` clean (15 routes, up from 13).
Second — and this is the one worth repeating for any future anti-bypass
work — a live smoke test against the actual running API and web dev
servers, not the pytest ASGI transport: logged in as a real buyer over
real HTTP, bought the seeded course through the full EFT path, had a real
finance user approve it, listed the resulting real enrolment, fetched
real progress (lesson 1 available, lesson 2 locked with "Complete the
previous lesson first"), started lesson 1, attempted to complete it
immediately and got refused — `423`, `"0s spent of 30s required"` — then
waited the real 30 seconds and completed it for real, watching
`next_lesson_id` and the progress endpoint both correctly show lesson 2
unlocked. Pushed as `0431928`; green on both jobs —
https://github.com/WillemKlopper87/TTLI_LMS/actions/runs/31334900775
(quality 3m4s, web 44s).

**Thirteenth pass: Phase 4 sprint 2 — the ported VOD transcode pipeline,
signed HLS playback, heartbeat validation.** The biggest, most technically
novel piece of Phase 4. `0012` adds `video_assets`/`transcode_jobs`
(global, like `courses`) and `video_progress`/`video_heartbeats`
(tenant-scoped/RLS, like `enrolments`) — see the migration's own docstring
for why `video_heartbeats` gets the plain grant rather than
`ledger_entries`-style two-layer append-only enforcement, and why
partitioning was deliberately deferred alongside the retention sweep that
would consume it.

**The port itself** (`src/services/media/{ffmpeg,transcoder,pipeline}.py`)
is a from-scratch Python reimplementation of `Streaming_Server`'s
`transcoding-engine.js` — not a translation tool, a human read of the JS
and rebuilt the same ffmpeg argument construction in Python's
`asyncio.create_subprocess_exec`. Confirmed empirically, not assumed: ran
the real `ffmpeg` binary with the Python-built args against a synthetic
test clip and inspected the actual output tree before trusting the
upload-iteration logic in `pipeline.py` — ffmpeg auto-generates
`init_0.mp4`/`init_1.mp4` per variant (not the single `init.mp4` the
`-hls_fmp4_init_filename` flag name suggests), which is exactly the kind
of detail worth verifying against a real binary rather than the source
JS's comments. Runs as an arq job (`transcode_video_job`,
`src/workers/main.py`) off the request path, matching how
`send_email_job` already keeps SMTP off it. VOD-only: `Streaming_Server`'s
live sliding-HLS-window mode was deliberately not ported, since 01 §5.8
already decided this platform never streams live broadcast content —
porting a mode nothing here would ever exercise would be unexercised code
carrying its own bug surface for no reason.

**Signed HLS playback** (`src/services/media/playback.py`, 03 §6.7) solves
the "media players cannot set headers on segment requests" problem 06
§3.2 flagged as inherited from `Streaming_Server` but never actually
built there. The access token travels as a query parameter; `GET
/media/{id}/hls/{filename}` rewrites every relative reference inside a
served manifest to carry that same token — both plain lines and the
`#EXT-X-MAP:URI="..."` init-segment reference, which needed its own regex
since it's a comment-prefixed line with a URI hiding inside quotes.
Entitlement is checked once, before a URL is minted, never cached, via
`services/enrolment.py::has_access_to_video` (walks lesson → module →
course → the caller's own enrolment). Concurrent-session cap
(REQ-BYPASS-09) evicts the *oldest* Redis-tracked session when a new mint
exceeds the configured limit — the person in front of the screen right
now keeps playing, not whoever logged in first.

**Heartbeat validation** (`src/services/video_progress.py`,
REQ-BYPASS-02/03/04) is new logic, not ported from anywhere — nothing in
`Streaming_Server` needed it. `watched_seconds` grows by at most the
real, server-measured interval since the previous heartbeat (capped per
heartbeat at 30s so a paused tab or dropped connection can't be replayed
as watched time on reconnect — 03 §13 leaves the real heartbeat interval
an open question, so this is a documented reasonable default, not a
guess dressed up as a decision). `furthest_position_seconds` is a seek
ceiling with a small buffering-jitter tolerance; a heartbeat claiming a
position beyond it is refused with `SEEK_NOT_PERMITTED`, verified all the
way down to the database row (a rejected heartbeat writes nothing —
checked directly via SQL, not just the HTTP response code). This feeds
`video_watch_percentage`, which graduates out of the completion rule
engine's "not available yet" refusal list in this pass —
`services/enrolment.py::_video_watch_percentage` looks up real watched
data before `services/completion.py::evaluate` runs.

**Two real bugs, both caught only because this was verified live against
running servers, not just the test suite** — the same lesson the ninth
and eleventh passes already taught, worth repeating because it keeps
paying off: (1) `POST /lessons/{id}/video` 500'd with
`InsufficientPrivilegeError: permission denied for table lessons` —
`0011` left `lessons` SELECT-only for `app_user` since nothing wrote to it
that sprint; this sprint's narrow video-attach endpoint is lessons' first
real writer, so `0012` grants `UPDATE` (not `INSERT`/`DELETE` — still not
general authoring). Fixed in `0012` itself before it was ever committed,
not a follow-up migration. (2) `playback.validate()` crashed with
`AttributeError: 'str' object has no attribute 'decode'` — the Redis
client (`core/redis.py`) is constructed with `decode_responses=True`,
so every value already comes back as `str`; the `.decode()` calls I'd
written assumed `bytes`, copied from a mental model of redis-py's
default rather than checked against this project's actual client
construction. Neither bug was hit by `tests/test_media.py` because those
tests were written *after* the live smoke test that found them — a
reminder that a green test suite only proves what it was written to
check, not what a real request path actually does.

**A narrow, deliberate authoring endpoint**: `POST /lessons/{id}/video`
attaches a `video_asset_id` and flips `activity_type` to `"video"` — one
field, not general lesson CRUD, which still doesn't exist (STATUS.md
tracks that gap explicitly). It exists because the upload endpoint above
it is otherwise unreachable in any real end-to-end flow; don't grow it
into general authoring without deciding that's actually in scope.

**A third real bug, this time in CI itself, caught by the same
verify-don't-assume discipline**: `tests/test_media.py` needs a real
`ffmpeg`/`ffprobe` on PATH, and this workflow's zero-skip policy (the
"Assert integration tests ran" step) turns any skip into a hard CI
failure — so rather than assume `ubuntu-latest` ships ffmpeg, the first
push added an explicit `ffmpeg -version && ffprobe -version` step to
`.github/workflows/api.yml`'s `quality` job specifically so a wrong
assumption would fail loudly, at its own step, with an unambiguous
message. It was wrong: `ubuntu-latest` does **not** ship ffmpeg —
`quality` failed in 1m10s with `ffmpeg: command not found` (exit 127),
exactly as designed to. Fixed with a real `sudo apt-get install -y
ffmpeg` step ahead of the verify step, pushed as a second commit on this
same pass. Worth internalising: two of this pass's three real bugs (the
`lessons` grant, this one) were caught only because something was
actually run rather than reasoned about from documentation or memory —
the Redis `str`/`bytes` one makes three.

Real end-to-end verification, both automated and live: 18 new tests in
`tests/test_media.py`/`test_media_ffmpeg.py` (real ffmpeg transcodes, not
mocked — same reasoning as `test_antivirus.py`'s real ClamAV), full suite
143 tests / 0 skipped. Separately, a live smoke test against actually
running API, web and arq-worker processes: uploaded a real synthetic
video over real HTTP, watched the real worker transcode it in ~2s,
attached it to a lesson, minted a real playback token as a real enrolled
buyer, fetched the real manifest through the actual Next.js BFF (not the
API directly) and confirmed every reference line carried the token,
downloaded a real segment through both the API directly and through the
BFF and confirmed the two are MD5-identical (the same binary-integrity
verification the ninth pass's BFF fix established as the bar), sent real
heartbeats and watched a seek beyond the furthest position get refused
with the row-level state to prove it. `apps/web` gained `hls.js`
(`npm audit`: 0 vulnerabilities) and a real video player component with a
watermark overlay and 5-second heartbeat pings. `apps/web` `typecheck`/
`build` clean (still 15 routes — `/learn` and `/learn/[enrolmentId]`
already existed from the twelfth pass, this pass only added the video
player inside the existing lesson page). Pushed as `41c9598`; `quality`
failed as designed on the missing-ffmpeg check (see above); fixed with an
`apt-get install` step, pushed as `77beb76` — green on both jobs,
including the real ffmpeg transcode tests running for the first time on
an actual GitHub Actions runner —
https://github.com/WillemKlopper87/TTLI_LMS/actions/runs/31337009510
(quality 2m53s, web 47s).

**Fourteenth pass: Phase 4 sprint 3 — quizzes, surveys with per-survey
anonymity, assignments.** `0013` adds nine tables: `quizzes`/
`quiz_questions`/`surveys`/`survey_questions`/`assignments` global like
`courses` (a question bank belongs to a lesson, which belongs to a
globally-shared course); `quiz_attempts`/`quiz_answers`/
`survey_responses`/`assignment_submissions` tenant-scoped/RLS like
`enrolments`. `lessons` gains `quiz_id`/`survey_id`/`assignment_id`,
the same one-nullable-FK-per-subsystem pattern sprint 2's
`video_asset_id` established.

**Quizzes** (`src/services/quiz.py`, REQ-ASSESS-01/02/03,
REQ-BYPASS-05/06): question order is shuffled and persisted server-side
at attempt creation, not re-derived per fetch — REQ-BYPASS-05 means the
randomisation decision has to be the server's, once, not re-rolled in a
way a client could exploit. Attempt limits (REQ-BYPASS-06) are enforced
by counting non-invalidated attempts against `quiz.max_attempts` before a
new one is allowed to start, not trusted from the client. `single_choice`/
`multiple_choice`/`true_false` auto-grade at submission by comparing
selected option IDs against the question's own `correct` flags — never
sent to the client before submission (03 §6.5), verified by an assertion
that walks every returned question's options and confirms `"correct"` is
absent as a key, not just false. `short_text`/`long_text` stay ungraded
(`points_awarded=None`) until `POST /quiz-answers/{id}/grade`
(`quiz:grade`-gated) — REQ-ASSESS-03's "auto-grading with manual grading
for open-ended responses" built as two real stages, not one that fakes
grading open text. `passed` stays `None`, not `False`, while anything is
ungraded — a quiz genuinely awaiting a grader is not the same state as a
quiz someone failed, and the rule engine (below) treats them with
different messages even though both currently block completion.

**Anonymous surveys** (`src/services/survey.py`, REQ-ASSESS-05,
REQ-BYPASS-07) are the piece worth understanding before touching this
code: the spec requires *both* "no `user_id` stored" and "duplicate
submissions rejected" and "the completion rule engine can tell whether
this learner responded" — three requirements that look like they need
identity to satisfy the second and third while the first forbids exactly
that. The resolution reuses `core/crypto.py`'s existing
`CryptoBox.blind_index` — the same mechanism `contacts.email_blind_index`
already uses to look up encrypted emails — applied to
`f"{survey_id}:{enrolment_id}"` instead of an email. That produces a
stable pseudonym: deterministic for the same enrolment answering the same
survey twice (so duplicates and completion-gating both work), but not
reversible back to the enrolment without the blind-index key (so
anonymity holds). No `survey_answers` table — `SurveyResponse.answers` is
a jsonb list, matching 02 §7.6's own table list, which names
`survey_responses` and nothing else. Verified past the API response, at
the database row itself: `user_id IS NULL` (genuinely absent, not
null-by-coincidence), `respondent_reference` is a real blind-index hash,
and a matching `audit_events` row (`actor_user_id=NULL`) proves
anonymisation happened at submission time — 02 §7.6's own stated bar for
what makes this guarantee defensible later, not just claimed.

**Assignments** (`src/services/assignment.py`, REQ-BYPASS-08) reuse
`services/antivirus.py` exactly as payment-proof and video-source uploads
already do — scanned before storage, fail-closed on an unreachable
scanner. `POST /assignment-submissions/{id}/review` approves or rejects;
gated on `quiz:grade` since no dedicated `assignment:review` permission
exists and the facilitator role that would naturally hold one is Phase 5
— documented as a deliberate reuse, not an oversight, so nobody "fixes"
it into a new permission without checking whether Phase 5 already plans
to replace it.

**Rule engine wiring** (`src/services/completion.py`,
`src/services/enrolment.py::_completion_context`): `quiz_pass_score`,
`survey_required`, `assignment_approval_required` graduate out of "not
available yet", joining `video_watch_percentage` from sprint 2 — only
`live_attendance_required` (Phase 5) is still unbacked. Each new check
resolves through the same lesson → activity-subsystem lookup pattern
(`_quiz_passed`/`_survey_responded`/`_assignment_approved`), gathered
once per evaluation via `_completion_context` rather than four separate
awaits duplicated at both call sites (`complete_lesson`, `get_progress`).

**Three real bugs this pass, one of them in a test, not the product** —
worth recording because it's a different failure mode than the previous
two passes' bugs: (1) `submit_quiz_attempt`
(`routers/assessment.py`) originally read `enrolment_id` back off the
attempt row itself before passing it into `quiz_service.submit_attempt`,
which made that function's ownership check
(`existing.enrolment_id == enrolment_id`) tautological — any caller who
knew another learner's `attempt_id` could submit answers on their behalf.
Caught on a second read of my own code, not by a test; fixed by deriving
`enrolment_id` independently from the caller's own identity via
`resolve_enrolment_for_quiz`, so the ownership check inside
`get_own_attempt` is a real comparison. (2) The `lessons`/`options`/
`question_order` JSONB columns needed `list[dict[str, Any]]`/`list[str]`
typing, not `list[object]`, before mypy strict would allow indexing into
them — a lesson worth remembering for the next JSONB column this project
adds: type it for how it's actually read, not the loosest thing that
satisfies the column definition. (3) **The test bug**: an early version
of `test_completion_rule_engine_gates_on_quiz_survey_and_assignment`
directly `UPDATE`d the shared seeded lesson's `completion_rules` to test
gating, and didn't restore it — `lessons` is global, shared by every test
file in the suite, and the very next full-suite run broke
`test_learning.py`'s assertions about that same lesson's
`minimum_time_seconds` rule. Fixed with a `try`/`finally` that reads the
original value first and restores it unconditionally; the polluted dev
database itself also needed a manual `UPDATE` to recover, since the
first failing run predated the fix. Full suite re-run twice after, clean
both times, to confirm the fix actually holds and isn't itself flaky.

Verified: 9 new tests in `tests/test_assessment.py`, full suite 152 tests
/ 0 skipped (run twice for determinism after the test-pollution fix
above). Live smoke test against actually running servers: created a real
quiz with a `single_choice`, a `true_false` and a `long_text` question,
took it as a real enrolled buyer, watched `passed=null` while the text
answer was ungraded, graded it, watched score/passed finalise to
100%/true; created an anonymous survey, submitted a response, confirmed
`user_id IS NULL` and the audit row directly via SQL, confirmed a second
submission is refused; submitted a real assignment file, had an EICAR one
refused with the real signature name, approved the clean one. `apps/web`
gained `quiz-player.tsx`/`survey-form.tsx`/`assignment-upload.tsx`, wired
into `/learn/[enrolmentId]` by `activity_type`; `typecheck`/`build` both
clean (still 15 routes — no new pages, only new components inside the
existing lesson page). `npm audit` clean on both packages. Pushed as
`fac6dd3`; green on both jobs on the first try —
https://github.com/WillemKlopper87/TTLI_LMS/actions/runs/31359802592
(quality 3m5s, web 57s).

**Fifteenth pass: Phase 4 sprint 4 — certificates, badges, public
verification. The final Phase 4 sprint.** `0014` adds five tables:
`certificate_templates`/`badge_templates` global like `courses`;
`certificates`/`badges`/`credential_verifications` tenant-scoped/RLS like
`enrolments`. `courses` gains `certificate_template_id`/`badge_template_id`
— 02 §5.1 described these as already present, but `0011` deliberately
deferred them until the tables they point at existed.

**Issuance has no direct endpoint** (REQ-CRED-01): there is deliberately
no `POST /certificates`, for the same reason `POST /invoices` doesn't
exist — `services/credentials.py::issue_for_completed_enrolment` is
called only from `services/enrolment.py::complete_lesson`, in the same
request that just set `enrolment.completed_at`, so issuance is provably
tied to the rule engine's own confirmation rather than a second,
unaudited path to the same effect. A course with neither template
attached issues nothing; calling it twice for the same enrolment is a
no-op (checked by an existing-certificate lookup before insert).

**A real, caught-before-commit design bug, worth recording in full
because of how it was caught.** The first draft of `0014` gave
`certificates.verification_token` the exact same treatment as a
magic-link or refresh token: `core/security.py::new_token()`/
`hash_token()`, a one-way SHA-256 hash. That's correct for a token used
once and never needed again — wrong here, because the same token has to
be *reconstructed* later for `GET /badges/{id}/share/linkedin`'s
`certUrl` field, and a one-way hash can never support that. The gap
surfaced while writing that router endpoint: the first draft tried to
substitute `certificate.certificate_number` into the share URL instead
of the real token, which is not the same value — `certificate_number`
is a public, unguessable-but-not-secret serial (02 §8.1), not the secret
verification token. Caught on review before anything was committed, not
after a bug report. Fixed by redesigning the column as
`verification_token_encrypted` (`CryptoBox.encrypt`, reversible) plus
`verification_token_blind_index` (`CryptoBox.blind_index`, deterministic)
— the exact pattern `contacts.email_encrypted`/`email_blind_index`
already established two phases ago, reused rather than reinvented. The
migration had already been applied once to the local dev database with
the old column names before the fix; reconciling meant a real
`alembic downgrade -1` / `upgrade head` round-trip, not just editing the
file, run twice to confirm both the schema and `alembic check` held
clean afterward.

**A second real gap, found the same way — by trying to use the code, not
by reading it.** `certificate_templates` only had `signatory_name` (the
person who signs, e.g. "Dr. Thandeka Themba") — no separate field for
the issuing *organisation*. The snapshot code was putting the signatory's
name into LinkedIn's `organizationName` field, which reads as a person
being credited as the issuing institution. `badge_templates` already
modelled this correctly (its own `issuer_name` column, separate from
nothing since badges have no signatory concept); `certificate_templates`
now has `issuer_name` too, distinct from `signatory_name`/
`signatory_title`. The PDF's "Signed:" line uses the signatory; a new
"Issued by:" line and LinkedIn's `organizationName` use the issuer.
Caught while writing the live smoke test below, by actually reading the
LinkedIn payload it produced rather than asserting on shape alone.

**A third gap, found while building the frontend, not the API:** there
was no way for a learner's own client to discover the certificate/badge
IDs every other endpoint in this file needs — `GET /certificates/{id}/pdf`
etc. all take an ID the frontend had no way to obtain. Added
`GET /enrolments/{id}/credentials`, owner-only, returning both
(nullable) for a given enrolment — the one lookup keyed by something the
client already has.

**A fourth gap, REQ-CRED-07 specifically:** "learner controls credential
visibility" was only wired for badges (`PATCH /badges/{id}`) even though
`GET /verify/{token}` already gates on a *certificate's own* `visibility`
field — there was no way to ever change it off the `private` default.
Added `PATCH /certificates/{id}`, sharing a `VisibilityRequest` schema
with the badge endpoint since the three-way choice (`private`/`public`/
`link_only`) and the ownership check are identical.

**PDF + QR** (`services/credentials.py::render_certificate_pdf`, REQ-CRED-02):
`reportlab` draws a landscape A4 certificate directly — no template
engine, the layout is fixed and small — with a `qrcode`-generated QR
embedded via `ImageReader`, pointing at an *absolute* URL
(`settings.public_web_url`, new setting, default `http://localhost:3010`)
since a phone camera resolving a QR code has no notion of the BFF's
relative-path convention every other frontend call uses. New pinned
deps `reportlab==5.0.0`, `qrcode[pil]==8.2`, `Pillow==12.3.0` — verified
clean via `pip-audit`, and added to `pyproject.toml`'s
`ignore_missing_imports` override (same precedent as `argon2`/`boto3`)
since neither ships type stubs.

**Public verification** (`GET /verify/{token}`, REQ-CRED-03): rate-limited
20/hour/IP the same way `POST /leads` is, and every lookup is logged —
hit or miss — so the log doubles as abuse detection. A `private`
certificate behaves identically to an unknown token, which matters more
than it looks: visibility has to gate the page itself, not just whatever
listing might reference it, or a "private" certificate would still leak
through direct URL guessing.

Verified: 5 tests in `tests/test_credentials.py` covering issuance
(with and without templates attached), the private-by-default → public
visibility toggle reflected live in `GET /verify/{token}`, revocation
(permission-gated, reason required, reflected in verification status),
badge-visibility ownership enforcement, and LinkedIn share field
correctness including the corrected `organizationName`. Full suite: 157
tests / 0 skipped, run twice for determinism. Migration round-tripped
twice (once after the token redesign, once after the `issuer_name` fix)
— `alembic check` clean both times. `mypy src` clean (87 files, up from
83). Live smoke test against the actual running dev servers (API and
`apps/web`, not the test suite) — driven through the real BFF exactly as
the frontend calls it, including a mid-test discovery that the BFF only
forwarded `GET`/`POST` and needed `PATCH` added before the visibility
toggles could work at all: completed a real course, had a real
certificate+badge issued, fetched both via
`GET /enrolments/{id}/credentials`, downloaded the actual PDF (confirmed
`%PDF` header, since local dev storage returns a `file://` URL rather
than an HTTP one — read directly rather than fetched), toggled both
certificate and badge visibility from private to public through the
exact `PATCH` calls the UI makes, fetched the LinkedIn share fields and
confirmed `organizationName` read the institution rather than the
signatory, and loaded the actual public `/verify/[token]` page (200,
real HTML). One honest limitation: no browser automation tool was
available this pass, so the hydrated DOM was not visually inspected —
the underlying JSON contract and the page's initial HTML shell were
confirmed instead. `apps/web` gained `credentials-panel.tsx` (wired into
`/learn/[enrolmentId]`) and the public `app/verify/[token]/page.tsx` — 16
routes now, up from 15. `typecheck`/`build` both clean. `npm audit` clean
on both packages. `packages/api-client`'s `schema.gen.ts` regenerated
from a freshly-exported `openapi.json` and typechecked clean. Pushed as
`0fdad37`; green on both jobs on the first try —
https://github.com/WillemKlopper87/TTLI_LMS/actions/runs/31375456707
(quality 3m19s, web 57s).

**Sixteenth pass: Phase 4.5 — PWA and accessibility, plus two REQ-LMS
items left over from Phase 4.** Closes Phase 4 to ~95% and opens Phase
4.5 to ~90% — the only deliberate gap left open in either is push
notifications, discussed below.

**REQ-LMS-06/07 first, since they're really Phase 4's own unfinished
business.** Printable transcript: `GET /enrolments/{id}/transcript`
returns completed lessons only, each with the real `completed_at` the
rule engine assigned — not the full progress checklist
`GET /enrolments/{id}/progress` already serves, a different question
with a different answer. Learner-name resolution (full name, else
email — the same fallback `services/credentials.py` already used for
certificates) was duplicated inline there; pulled out into
`identity.py::display_name()` and both call sites now share it, since
two independent implementations of "how do we address this learner"
would drift the moment one changed. `apps/web` renders the transcript
as a real `@media print` page (`window.print()`), not a generated PDF —
the certificate already owns that treatment, and duplicating it for a
transcript would be building the same thing twice for no reason.

WebVTT captions: `video_assets.caption_object_key` (`0015`) plus
`POST /video-assets/{id}/captions`, human-authored upload rather than
automatic transcription — this project has no ASR pipeline, and
fabricating caption text for content nobody actually wrote would be
worse than shipping no captions at all. The interesting design decision
is where captions are *served*: rather than inventing a new
entitlement-checked endpoint, `captions.vtt` is stored under the video
asset's own `video-assets/{id}/` prefix and served through
`GET /media/{id}/hls/{filename}` — the exact signed-token mechanism
segments already use, since a `<track>` element can't set an
`Authorization` header any more than a segment request can (06 §3.2's
constraint, solved once, reused here rather than solved twice).

**PWA.** `app/manifest.ts`, not a static `public/manifest.json` — this
project's tenants each get their own theme (`app/layout.tsx` already
fetches it server-side to set brand CSS variables), so a hardcoded
manifest would install every tenant's PWA under TTLI's name and colour.
The manifest resolves `theme_color`/`name` from the same `getTheme()`
call, live-verified against the running dev server: the served
`/manifest.webmanifest` genuinely contains "Themba Thandeka Leadership
Institute" and `#8E151C`, not a placeholder. `short_name` has no backing
API field, so it's computed — initials when the tenant name won't fit a
home-screen label (~12 characters), the name itself when it will; for
TTLI's actual name this produces "TTLI" without that string being
hardcoded anywhere. Icons (192/512/maskable) were generated from the
real brand mark (`public/brand/ttli-mark.png`, the red starfish), not a
placeholder square — the maskable variant keeps the mark inside the
~80% safe zone every OS mask crops to, verified by rendering it.

The service worker (`public/sw.js`) is an offline *shell*, deliberately
not offline *data* — this platform's content is per-tenant, server-
rendered, and live; caching course/lesson state for real offline use
would need background sync and conflict resolution, infrastructure this
project doesn't have. What it honestly does: network-first for
navigations, falling back to a real branded `offline.html` only when the
network request itself fails, so a learner sees "you're offline, your
progress is safe on the server" instead of the browser's generic
connection-error page. Registered from a small `"use client"` component
(`register-sw.tsx`) mounted in the root layout, since `layout.tsx`
itself is an async server component and can't touch `navigator`.

**WCAG 2.1 AA — computed, not eyeballed.** Every color pair in
`globals.css` was run through the actual WCAG relative-luminance
contrast formula
(`(L1+0.05)/(L2+0.05)`, sRGB channels linearised per the spec), not
judged by looking at them. This found two real failures that had been
shipping since earlier sprints: `--faint` (`#9a9096`) read at 3.1:1
against white — used pervasively for timestamps, helper text and every
"Loading…" state across eleven files, all normal-weight text nowhere
near the "large text" size threshold that would lower the bar to 3:1.
`.tag--live`'s color (`#a66a0a`) read at 3.8:1 against its own wash —
tags render at 9px, so they need the full 4.5:1 too. Both darkened
(lightened in dark mode) along the *same hue* to 4.5:1+ against every
surface each token actually appears on — not just one background,
since `--faint` sits on `--surface`, `--stone` and `--surface-2` at
different points in the app, and the worst of the three is what
matters. Fixed at the token level in `globals.css` rather than patched
per call site, so all eleven files inherit the fix automatically and no
future usage can reintroduce the failure by picking a different
call-site override.

Missing accessible names were the next-most-consequential find: the
**login form** — the single most important form in the entire
application — had `placeholder` text standing in for a `<label>` on all
three of its inputs (email, password, MFA code), which fails WCAG
1.3.1/3.3.2/4.1.2 and, practically, means a screen-reader user gets no
announced field name at all. Fixed with `aria-label` plus `autoComplete`
values (`email`/`current-password`/`one-time-code` — WCAG 1.3.5, and a
genuine UX improvement for password managers, not just an accessibility
checkbox). Same pattern fixed on the admin payment-rejection input, the
quiz/survey free-text `<textarea>`s (labelled from the question prompt
text itself, so the accessible name matches what's visually asked), and
the assignment file picker.

`role="alert"` went on 16 dynamic error/status messages across every
form and async action in the app (WCAG 2.1's SC 4.1.3, new in 2.1 — a
genuine addition over 2.0, not a re-check of an old rule) — a failed
submit or a rejected upload is now announced without the user needing
focus already on that element. One found-and-deliberately-left case:
`credentials-panel.tsx`'s revoked-reason display is static content that
renders once on load, not a status change in response to an action, so
`role="alert"` there would be noise, not signal — the distinction
mattered enough to note in the diff rather than blanket-applying the
attribute everywhere red text appears.

Smaller fixes in the same pass: table headers gained `scope="col"`
(`admin/leads/page.tsx`'s pre-existing table, and the new transcript
table); `/catalogue` skipped straight from `<h1>` to `<h3>` on its
product cards with no `<h2>` between, fixed; the admin sidebar's
"coming soon" nav items were dimmed via `opacity: 0.6`, which against
the brand gradient's lighter end worked out to 3.55:1 — raised to a
verified 4.5:1+ and given `aria-disabled` plus italics so the "this
isn't real yet" meaning survives on a non-color channel too, not just a
fainter version of the same color.

**What this pass could not verify.** No browser automation tool was
available this session, so nothing here was confirmed with an actual
screen reader or a real keyboard-only pass — the fixes are correct by
construction (computed contrast ratios, HTML/ARIA output inspected via
curl, each change cites the WCAG success criterion it addresses) but
"structurally correct" and "confirmed accessible by a human using
assistive technology" are different claims, and only the first one is
being made here. Also not built: an automated accessibility gate
(axe-core or equivalent) in CI, so this audit is a one-time pass, not a
regression check — a future `globals.css` change could reintroduce a
contrast failure silently. Both are recorded as open items, not glossed
over.

**Push notifications ("where supported", 01 §5.9) were deliberately not
built**, the one piece of this phase's stated scope left undone on
purpose. Two real blockers, not an oversight: no VAPID key
infrastructure exists, and — more fundamentally — nobody has decided
what a push notification would actually say. A lesson reminder? A
certificate-issued confirmation? A payment-approved notice? Wiring the
mechanism without that product decision would repeat the exact mistake
this project has avoided everywhere else: inventing content nobody
asked for. Same category of gap as Phase 3's Payfast/Netcash sandbox
credentials — a real external decision blocking the work, not an
engineering shortcut.

Verified: 2 new backend tests (`tests/test_media.py`'s caption test,
`tests/test_learning.py`'s transcript test), full suite 159 tests / 0
skipped, run twice for determinism. Migration `0015` round-tripped
clean, `alembic check` clean. `mypy src` clean (87 files, unchanged —
captions/transcript logic went into existing files, no new backend
modules this pass). Live smoke test against the actual running dev
servers, through the real BFF: uploaded a real video, ran a real ffmpeg
transcode, uploaded a real WebVTT file, confirmed `has_captions`/
`captions_url` end to end; completed the seeded course for a fresh
learner and confirmed the transcript was empty before and fully
populated (real timestamps) after, including the actual
`/learn/[id]/transcript` page returning 200; confirmed
`/manifest.webmanifest`, `/sw.js` and `/offline.html` all serve
correctly and that `<link rel="manifest">`/`theme-color` appear in the
real rendered HTML. `apps/web` gained `manifest.ts`, `register-sw.tsx`,
`public/sw.js`, `public/offline.html`, three generated icon files, and
`/learn/[enrolmentId]/transcript/page.tsx` — 17 routes now, up from 16.
`typecheck`/`build` both clean. `npm audit` clean on both packages.
`packages/api-client` regenerated from a fresh `openapi.json` and
typechecked clean. Pushed as `595a673`; green on both jobs on the first
try — https://github.com/WillemKlopper87/TTLI_LMS/actions/runs/31386541830
(quality 4m6s, web 52s).

**Seventeenth pass: an independent security scan (OWASP ZAP + Trivy),
requested mid-Phase-5.** Not a sprint — a detour, at the user's explicit
request, to run tools neither `pip-audit` nor `npm audit` overlap with:
dynamic scanning against the actually-running app, and container-image
scanning against what `infra/docker-compose.yml` pulls from Docker Hub.

**ZAP baseline against `apps/web`, dev server first: 10 WARN, 0 FAIL.**
Three of the ten — "Dangerous JS Functions" (`eval(`), "Suspicious
Comments", "Timestamp Disclosure" — turned out to be dev-server-only
artifacts of webpack's `eval()`-based HMR source maps, not present in a
real build. Confirmed rather than assumed: `grep -rl "eval(" .next/
static/chunks/*.js` against a real `next build` returned zero matches,
and a full re-scan against `next build && next start` made all three
findings disappear on their own. The other three real, fixable findings
— `X-Content-Type-Options`/`Permissions-Policy` missing on static
assets, and `X-Powered-By: Next.js` leaking the framework — were fixed:
the two headers moved into `next.config.ts`'s `headers()` config for
`_next/static`/`_next/image`/`icon.png` specifically (rather than
widening `proxy.ts`'s matcher to run the CSP-nonce middleware on every
static asset, which would cost real overhead for headers that don't
need per-request randomness), and `poweredByHeader: false` was added.
Re-scanning the production build after the fix: 4 WARN remain, all
reviewed and accepted rather than fixed — `style-src 'unsafe-inline'`
(`proxy.ts`'s own docstring already justifies this), a COEP header
deliberately not added (no current feature needs the cross-origin
isolation it provides, and adding it without CORP-tagging every
resource risks silently breaking a future cross-origin embed, e.g. a
card-checkout iframe), and two purely informational findings. ZAP
against `apps/api` came back essentially clean (1 trivial WARN about
cacheable 404s).

**Trivy `fs` (vuln + secret + misconfig) against the repository: clean.**
Zero vulnerabilities in the three dependency manifests it found
(`requirements.txt`, both `package-lock.json` files) — an independent
confirmation of what `pip-audit`/`npm audit` already report, from a
different scanner and a different vulnerability database. Zero secrets
in tracked source. Getting a *clean run* took three attempts, and the
retries are worth recording: the first two attempts hit Trivy's
internal analysis timeout scanning `apps/api/var/storage` — 105 MB and
868 directories of leftover local video-transcode test artifacts from
every media/caption smoke test this session ever ran, gitignored but
never cleaned up, silently accumulating. Excluding it (`--skip-dirs`)
alongside `node_modules`/`.venv`/`.next`/`.mypy_cache` (already covered
by `pip-audit`/`npm audit`, no reason to re-scan them here) and a
longer `--timeout` got a scan to actually finish.

**Trivy `image` against every service in `infra/docker-compose.yml`:**
`postgres:16-alpine` 1 CRITICAL/14 HIGH (almost entirely a bundled Go
entrypoint helper, never exposed to network input), `redis:7-alpine`
clean, `minio/minio:latest` 6 CRITICAL/76 HIGH, `mailhog/mailhog:latest`
**109 CRITICAL/1250 HIGH** — MailHog has been unmaintained upstream for
years, still shipping on an EOL Alpine 3.12 base, and it shows.
`clamav/clamav-debian:stable` 5 CRITICAL/23 HIGH. Fixed the one with
both the worst numbers and the lowest switching cost: mailhog/mailhog
→ `axllent/mailpit:v1.24`, an actively-maintained, protocol-compatible
successor. Verified rather than assumed compatible — sent a real
message through it and inspected the actual response: Mailpit's API is
`/api/v1/messages`, not MailHog's `/api/v2/messages` its docs claim
"compatibility" for, and the message shape differs too (`To` is a list
of `{Name, Address}` objects, `Subject` is a plain string, not
MailHog's nested `Content.Headers` shape). `tests/test_workers.py` was
updated to the real shape, not the assumed one, and re-run against the
actual container to confirm. `minio`/`clamav`/`postgres` CVEs were
**not** version-bumped blindly — all three are functionally load-bearing
(storage, virus scanning, the primary database) unlike Mailhog, and an
untested version jump risks breaking something worse than the CVEs
themselves; tracked as an open item in STATUS.md §10 instead, for a
controlled upgrade-and-test pass.

**Then, a follow-up request: remove Mailhog/Mailpit entirely** — local
SMTP delivery verification judged non-essential right now. This looked
trivial and almost wasn't: `.github/workflows/api.yml`'s "Assert
integration tests ran" step hard-fails the build on *any* skipped
test (`if skipped: sys.exit(...)` — the same zero-skip discipline that
has caught real problems all session). `tests/test_workers.py::
test_send_email_job_delivers_via_smtp` already had a graceful
`pytest.skip(...)` fallback for "Mailhog/Mailpit not reachable" — safe
for a laptop that hasn't run `docker compose up` yet, fatal for a CI
job that will never have it reachable again once the service container
is deleted. Removed the test outright, not left skipping — the other
worker test (`test_send_sync_raises_on_unreachable_smtp_host`) already
covers the "SMTP unreachable" failure mode `send_sync`'s retry contract
depends on, and needs nothing running to do it. `services/email.py`'s
actual send path (`send_email()` only ever enqueues, never blocks a
request on SMTP) is completely unaffected — what's genuinely lost is
the one automated check that a real send reaches a real inbox, which is
now a documented gap (STATUS.md §10), not a silent one.

**A process note, not a code finding.** Partway through, another
Claude Code session — a different, unrelated project on this same
machine — turned out to be running its own Trivy scans concurrently,
into the same generic `/c/tmp/security-scan` directory this session had
carelessly reused instead of its own isolated scratchpad (the harness
provides one specifically to avoid exactly this). The collision
surfaced as an unfamiliar shell script scanning Docker images that
share nothing with this project — `pgvector`, `nats`, `neo4j`,
`ollama` — which is worth pausing on for anyone reading this later:
that pattern (unexplained files, referencing infrastructure that isn't
this project's) is exactly what a real prompt-injection or supply-chain
compromise would also look like. It was investigated before being
touched — traced to running containers named `itsm-*` for what was
evidently a different in-progress session — confirmed as directory
collision, not tampering, and only then was this session's own output
moved to its correct isolated path and re-run cleanly. The instinct to
stop and verify before trusting or deleting unfamiliar files in a
shared path was the right one regardless of how it turned out this
time.

**Housekeeping in the same pass** (the user's own follow-up ask, once
the scan surfaced how much had accumulated): removed `apps/api/var/
storage` (105 MB), `.mypy_cache` (72 MB), `.ruff_cache`, `.coverage`,
stray `__pycache__` directories, and `apps/web/tsconfig.tsbuildinfo` —
all gitignored, all regenerate on the next command that needs them.
`apps/api/.env` was of course never touched.

Verified: full suite 158 tests / 0 skipped (159 minus the removed
Mailhog test), run after every change in this pass, not just at the
end. `ruff`/`mypy`/`alembic check` clean. `apps/web` `typecheck`/`build`
clean, including the header fixes. Pushed as `9ddd5fa`, separately from
the in-progress Phase 5 organisations schema work (which touches
different files and wasn't feature-complete enough to commit yet) —
green on both jobs on the first try, confirming the CI service
container's own removal of Mailhog works, not just the local compose
file — https://github.com/WillemKlopper87/TTLI_LMS/actions/runs/31394330419
(quality 3m37s, web 55s).

**Addendum, same session, next message:** local SMTP delivery was worth
keeping after all — reinstated, but as Mailpit (the already-verified
fix above), never as the vulnerable `mailhog/mailhog` image. Restored:
the compose service, the CI service container, and
`test_send_email_job_delivers_via_smtp` (identical to what was
verified working before removal — same `/api/v1` shape, same
assertions). Re-ran the test against a live Mailpit container to
confirm the restoration actually works rather than trusting the diff:
4/4 tests in `tests/test_workers.py` pass. Net position after both
changes: 159 tests (back up from 158), the CVEs from the original
image are still gone, nothing about `services/email.py` changed at any
point in either direction. Pushed as `5850134`; green on both jobs on
the first try — https://github.com/WillemKlopper87/TTLI_LMS/actions/runs/31395568160
(quality 3m39s, web 52s).

**Eighteenth pass: Phase 5 sprint 1 — organisations, seat-pool
entitlements, PO checkout.** `0016` adds `organisations`/
`organisation_members` and finally puts real FK constraints on
`entitlements.organisation_id`/`role_assignments.organisation_id` —
both columns already existed, bare and unconstrained, since
`0001`/`0009`; 02 §4.5 documented this design years before
`organisations` itself existed to point at. The seat model: a
null-`user_id` entitlement is the purchased pool, a set-`user_id`
entitlement drawn from it is one assigned seat, and "available" is
always `sum(pool.quantity) − count(active assigned)` computed on read
— never a separately tracked counter that could drift out of sync
with reality. PO checkout (`POST /orders/{id}/checkout/po`) captures
the PO number and its document together in one multipart call, unlike
EFT — a purchase order document exists from the moment it's raised,
so there's no "reference now, proof later" split. `_fulfil_order()`
was extracted out of `approve_eft`'s body in `services/orders.py` as a
shared helper, now used by both `approve_eft` and the new
`approve_po`; it branches on whether the order has an
`organisation_id` to decide between a direct user
entitlement+enrolment and a pool entitlement.

Two real bugs surfaced and were fixed before this was called done, not
after:

1. **Migration round-trip failure.** `0016`'s `downgrade()` dropped
   `organisations` without first nulling
   `entitlements.organisation_id`/`role_assignments.organisation_id`.
   Once `tests/test_organisations.py` had run against a DB at head and
   created real entitlement rows with `organisation_id` set, a
   `downgrade -1` left those values orphaned (the FK constraint was
   already gone, so nothing caught it), and the next `upgrade head`
   failed re-creating the constraint against a freshly-empty
   `organisations` table. Fixed by nulling both columns before
   `drop_constraint` in `downgrade()`; round-trip (`downgrade -1` →
   `upgrade head` → `alembic check`) now verified clean against real
   orphaned data, not just a fresh database.
2. **No way to revoke a specific seat from the UI.** The aggregate
   `GET /organisations/{id}/seats` endpoint returns per-course totals
   only — no entitlement IDs, so the revoke button the frontend needed
   had nothing to call. Added `GET
   /organisations/{id}/seats/{course_id}/assignments`
   (`services/organisations.py::list_assigned_seats`), admin-gated
   like invite/import/revoke since it returns real email addresses,
   unlike the membership roster which any member can read. Covered by
   a new test (`test_assigned_seats_endpoint_lists_holder_and_drops_
   after_revoke`) verifying both that a fresh assignment appears
   immediately and that a revoke drops it immediately — same
   live-computed discipline as the aggregate summary.

Frontend: `/organisations` (list/create — creation is self-service,
REQ-TEN-02, any authenticated user can start one and becomes its first
admin), `/organisations/[id]` (members, seat summary, invite-by-email,
CSV import, a per-course expandable seat-holder list with a working
revoke button), `/organisations/[id]/buy-seats` (programme + quantity
→ PO number/document in one step, structurally identical to
`/checkout`'s EFT flow but PO-only and organisation-scoped).
`/admin/payments` extended to show `PO`/`EFT` and the PO number
instead of a payment reference when the provider is `po`. No new
component library was introduced — every page reuses the existing
plain-CSS-class system (`.card`/`.btn`/`.field`/`.input`/`.tag`/
`.table-wrap`) and the BFF-proxy-plus-raw-`fetch` pattern already
established by `/checkout` and `/admin/payments` — organisations were
deliberately not put under `/admin`, since that layout is gated on
staff permissions (`analytics:view`/`payment:approve`) and org
adminship is a per-organisation `organisation_members.relationship`,
not a platform role.

Full gate sweep re-run clean after both fixes: `ruff check` (128
files), `mypy src` (91 files, strict), `pytest -q -rs` run twice for
determinism (167 passed, 0 skipped — up from 159), `apps/web`
`typecheck`/`build` clean (20 routes now, +3), `packages/api-client`
regenerated and typechecked against the new endpoints. Live smoke test
ran the entire flow through the real BFF exactly as the browser would:
seed two real users (org admin, finance) via the actual service layer
(not fixtures) → login → create organisation → create a 2-seat order
with `organisation_id` set → PO checkout with a real small PDF → PO
number and amount confirmed in the response → finance approves →
`INV-*` issued → seat summary confirms `purchased=2, assigned=0` →
invite one employee → summary flips to `assigned=1` → holder list
shows the real email and its entitlement ID → revoke → summary drops
back to `assigned=0` → members list shows the new employee as a
`member`. All four new page routes confirmed rendering (HTTP 200) with
no console/server errors in the dev-server logs.

Committed as `74f4183`, pushed to `main`; CI green on both jobs on
the first try — https://github.com/WillemKlopper87/TTLI_LMS/actions/runs/31405256087
(quality 3m43s, web 1m1s), including the migration round-trip check
passing in a clean environment (confirms the `0016` downgrade fix
holds outside the local dev database it was diagnosed against).

**Nineteenth pass: Phase 5 sprint 2 — manager visibility, REQ-TEN-03's
demo target.** `0017` adds `team:reports:view_individual`, granted only
to `admin`/`super_admin` — a platform-staff override, not the actual
mechanism an organisation's own manager uses. That distinction is the
sprint's real design decision: RBAC roles in this codebase are
tenant-wide, not per-organisation, so granting the "explicit
permission" REQ-TEN-03 requires through `role_assignments` would let a
manager in one organisation see another organisation's individual
results — precisely the leak the ABAC condition
`manager.organisation_id = learner.organisation_id` exists to close.
An organisation's own manager instead satisfies that condition through
`organisation_members.relationship` (`manager`/`admin`, from 0016) —
already the right per-organisation grant mechanism, just reused rather
than duplicated. `services/reports.py::get_progress_report` checks all
three at once: `courses.manager_visibility = individual_enabled`,
`tenants.settings.allow_manager_individual_results = true` (the
existing `settings` jsonb column, no migration needed for that half),
and (RBAC permission OR org relationship in
manager/admin). Aggregate stats always return; individual rows are
**absent**, never present-and-redacted, on any single failing
condition (03 §9's exact wording) — a redacted row would still leak
that a person exists and didn't complete something, the precise
bullying-enabling gap REQ-TEN-03 exists to close.

Two narrow, single-purpose endpoints were added alongside the report
endpoint, deliberately not a general course-authoring or
tenant-settings surface: `PATCH /courses/{id}/manager-visibility`
(`course:edit`-gated) and `GET/PATCH /tenant/settings/manager-
visibility` (`tenant:manage`-gated, merges into the existing settings
jsonb via `flag_modified` rather than overwriting it). `GET /courses`
was added too, once the frontend build made clear the admin toggle UI
had no way to list courses to toggle — same "narrow, not general"
discipline as the endpoint it supports, `course:view`-gated, no
create/update/delete.

Migration round-trip was verified *immediately* after writing `0017`
(`downgrade -1` → `upgrade head` → `alembic check`) rather than
discovered broken later — applying sprint 1's own lesson before it
could repeat.

Frontend: `/admin/settings` (the tenant-wide checkbox, a per-course
visibility dropdown — reuses the existing plain-CSS-class system, no
new components), and a "Report" panel added to the existing
`/organisations/[id]` seats table (a "Report" button per course
showing aggregate stats always, individual rows only when the API
says `individual_visible: true`, and an explicit "an admin has not
enabled manager visibility for this course" message otherwise — never
a client-side guess about what should be visible).

Full gate sweep clean: `ruff check`/`format --check` (134 files),
`mypy src` (95 files, strict), `pytest -q -rs` run twice for
determinism (173 passed, 0 skipped — up from 167), `apps/web`
`typecheck`/`build` clean (22 routes, +1). Live smoke test seeded a
third real user (a platform `super_admin`, distinct from the org's own
admin and from finance) via the actual service layer, then drove the
exact demo scenario through the real BFF: report showed
`individual_visible: false` and an empty `learners` array before
either toggle → platform admin flipped the course toggle via `PATCH
/courses/{id}/manager-visibility` → flipped the tenant toggle via
`PATCH /tenant/settings/manager-visibility` → the same report, same
organisation, now returned the real invited employee's email and
`status: "not_started"`. Both new page routes (`/admin/settings`,
the extended `/organisations/[id]`) confirmed rendering with no
console/server errors. Toggles were reset back to their safe defaults
after the smoke test so the dev database doesn't carry stray state
into the next session.

Committed as `7c88fe3`, pushed to `main`; CI green on both jobs on
the first try — https://github.com/WillemKlopper87/TTLI_LMS/actions/runs/31407990708
(quality 3m53s, web 57s).

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

**⚠ Historical note, no longer current:** at the point this section was
written, nothing was committed and there was no remote — see the "Third
pass" update at the top of this file for what actually happened: the repo
is now published and `.github/workflows/api.yml` is verified green (one
real bug found and fixed on the way — a `psql` URI-parsing failure in the
"Create extensions" step, unrelated to anything built this session).

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

### 3.1 Housekeeping — ✅ done 2026-08-09, including the push

- ✅ Committed, pushed to `https://github.com/WillemKlopper87/TTLI_LMS`
  (private), CI verified green (see the "Third pass" note at the top of
  this file).
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
- ✅ **Empty admin shell** — `apps/web` (Next.js **16.3.0** — upgraded from
  15.5 in the "Fourth pass" noted at the top of this file — React 19,
  Tailwind 4, port 3010): server-rendered login page themed from
  `GET /tenant/theme`, the MFA challenge step, an admin shell showing the
  signed-in principal, and the BFF proxy (the browser's only path to the
  API — no CORS surface). Access token lives in SPA memory per 04 §1.2; the
  HttpOnly-cookie refresh flow via the BFF is the natural next web-tier
  step. Hand-written minimal scaffold, not create-next-app; `npm run build`
  and `npm run typecheck` now also run in CI (`web` job, `api.yml`).

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
7. ✅ **Email failures are swallowed** — fixed by moving the actual send onto
   the arq worker: `send_email` now only enqueues (`core/queue.py`,
   `ArqRedis`), which still can't fail the request (an enqueue failure logs
   and returns, same as before), but the send itself
   (`workers/main.py:send_email_job`) runs with `max_tries=5` and *raises* on
   an SMTP failure so arq actually retries instead of silently dropping it.
   `test_send_email_job_delivers_via_smtp` verifies real delivery to Mailhog;
   `test_magic_link_request_enqueues_email_for_a_known_address` verifies the
   request path hands off rather than blocking. Mailhog is now a CI service
   container too (it needs no launch args, unlike MinIO, so the GH Actions
   `services:` block works for it directly).
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
- **Phase 2 (public site/funnel):** the decision-independent slice is done —
  leads/consent/events, `GET /leads` + the admin `Leads` screen, and
  `POST /guest-access` (see the "Seventh pass" note above). What's left is
  genuinely blocked: marketing pages need Phase 0's brand/design sign-off
  (#8) and a content inventory neither of which engineering can produce.
  REQ-LEAD-05/07 (sample entitlements, guest→paid conversion) need Phase 4's
  course tables. Don't build ahead of those — there's nothing left in Phase 2
  that isn't blocked on either Phase 0 or Phase 4.
- **Phase 3 (commerce):** sprint 1 (see "Eighth pass") built the foundation
  and the full EFT path — read it before adding to this phase, it already
  has the append-only ledger, sequential invoicing and the tax engine
  wired up correctly; don't rebuild them differently. What's left: card
  checkout (blocked on live Payfast/Netcash sandbox credentials, not a
  decision or a design gap), PO capture, credit notes/refunds, and
  `Idempotency-Key` handling (03 §1.6) — put real idempotency keys on
  webhook tables via a unique constraint when card checkout arrives, not
  application logic.
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
