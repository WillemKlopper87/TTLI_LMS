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
new `message` field. Not yet pushed as of this note — going straight into
Phase 4 sprint 1 next (course/module/lesson content model + completion
rule engine + enrolments), so this and that will likely land as one push.

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
