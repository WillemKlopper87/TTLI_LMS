# STATUS

**Updated:** 2026-08-09 (sprints 2–5 built; Sprint 1 tenancy defects found and fixed; security-hardening pass added)
**Scope reference:** [01_PRD.md](01_PRD.md) (requirements) · [02_DATA_MODEL.md](02_DATA_MODEL.md) (schema) · [03_API_SPEC.md](03_API_SPEC.md) (endpoints) · [04_SECURITY_AND_COMPLIANCE.md](04_SECURITY_AND_COMPLIANCE.md) (controls) · [05_COMMERCIAL.md](05_COMMERCIAL.md) (packaging) · [06_OPERATIONS.md](06_OPERATIONS.md) (infra)

---

## 1. Summary

Sprints 1–5 of Phase 1 are built; every gate passes against a live Postgres, Redis and MinIO. Phase 0 remains blocked on the customer — the foundation work was brought forward deliberately, because none of it depends on the ten open decisions.

Running the previously-blocked gates exposed that **Sprint 1's tenant isolation did not actually work**: the app connected as the Postgres superuser, which bypasses row-level security unconditionally. Fixed — the app now connects as a least-privileged `app_user` role created by the baseline migration, and the RLS suite passes as that role. The migration round-trip and a transaction-handling bug that silently discarded failed-login lockout counters were fixed in the same pass. Details in [HANDOFF.md §2](HANDOFF.md).

| Phase | Name | State | Done |
|---|---|---|---:|
| 0 | Discovery and sign-off | **BLOCKED** — 10 open decisions | 0% |
| 1 | Foundation | Built end-to-end, published, CI green | ~98% |
| 2 | Public site and content funnel | Leads, consent, events, guest access, the admin lead view, and a real marketing landing page (real TTLI copy/imagery, not placeholder) all built | ~55% |
| 3 | Commerce | Sprint 1: catalogue, orders, tax engine, the full EFT purchase path (now with a real UI, not just the API), sequential invoicing, the append-only ledger, the finance approval queue. Card (Payfast/Netcash) and PO checkout not started | ~40% |
| 4 | Core LMS, anti-bypass, credentials | Not started | 0% |
| 4.5 | PWA and accessibility | Not started | 0% |
| 5 | Corporate, workshops, marketing | Not started | 0% |
| 6 | AI insights | Not started | 0% |
| 7 | Hardening and cloud | Not started | 0% |

| Gate | Status |
|---|---|
| `ruff check` / `ruff format --check` | **PASS** — 86 files |
| `mypy src` (strict) | **PASS** — 62 source files |
| `pytest` | **PASS** — 117 passed, **0 skipped** (against real Postgres, Redis, MinIO, Mailhog *and* ClamAV) |
| `pip-audit -r requirements-dev.txt` | **PASS** — 0 known vulnerabilities (35 found and fixed this pass — see §4 below) |
| `npm audit` (`packages/api-client`, `apps/web`) | **PASS** — 0 vulnerabilities in both |
| `alembic upgrade head` | **PASS** — at `0009` |
| Migration round-trip | **PASS** — every revision downgrades and re-upgrades |
| `alembic check` | **PASS** — no model drift |
| `api-client` drift check | **PASS** — generated client committed, gate wired in CI |
| S3 adapter vs real MinIO | **PASS** — manual round-trip on port 9140 |
| Real ClamAV virus scan (clean + EICAR + unreachable-host) | **PASS** — `tests/test_antivirus.py`, real `clamd` on port 3410 |
| Source extraction fidelity | **PASS** — `python docs/source/extract.py --check` |
| Documentation link integrity | **PASS** — `python docs/check_links.py` |
| CI (`.github/workflows/api.yml`), `quality` + `web` jobs | pending this push — first run with the new ClamAV service container |

**Headline:** 117 tests (0 skipped), 22 endpoints, 28 tables (events partitioned monthly ×14), 9 migrations, typed TS client with a CI drift gate, email delivery through the arq worker with retries, 11 `apps/web` routes, CSP + security headers on every `apps/web` response, virus-scanned payment-proof uploads, dependency scanning (`pip-audit`, `npm audit`) wired into CI.

> Published: `https://github.com/WillemKlopper87/TTLI_LMS` (private). CI's first-ever run failed on a `psql` URI-parsing bug in a step unchanged since Sprint 1 — never executed before, so never caught; fixed, and the second run passed every step end to end. Still open: CI does not yet build/typecheck `apps/web` ([HANDOFF.md](HANDOFF.md)).

---

## 2. What exists now

### Working and verified

| Component | File | Verified by |
|---|---|---|
| Own git repository | `.git/` | `git rev-parse --show-toplevel` returns the project path, not `C:/Users/Wille` |
| Ignore rules | [.gitignore](../.gitignore) | Covers Python, Node, `.env`, transcode output, local data |
| Source extractor | [docs/source/extract.py](source/extract.py) | `--check` passes; asserts exact character counts |
| Extracted source | [docs/source/](source/) | 5 files, byte-identical to the export modulo LF normalisation |
| Documentation set | `docs/01`–`06`, `STATUS.md` | Cross-links resolve |
| Config + production safety | `src/core/config.py` | 13 tests in `tests/test_config.py` |
| Field encryption + blind index | `src/core/crypto.py` | 9 tests in `tests/test_crypto.py` |
| Argon2id, JWT, TOTP, UUID v7 | `src/core/security.py`, `ids.py` | 12 tests in `tests/test_security.py` |
| Tenant resolution + Redis cache (incl. negative cache) + RLS binding | `src/core/tenancy.py`, `db.py`, `redis.py` | `tests/test_rls.py`, `tests/test_auth_flows.py` |
| Schema + RLS + least-privileged `app_user` role | `alembic/versions/0001` | 8 RLS tests, run as `app_user` |
| Seed: 17 permissions, 6 roles, 2 tenants, break-glass admin | `alembic/versions/0002` | reads pydantic Settings, not raw env |
| Magic links, TOTP + recovery codes, refresh rotation with family revocation, device binding | `0003`, `src/services/{identity,tokens}.py` | 14 end-to-end HTTP tests in `tests/test_auth_flows.py` |
| Storage adapter: Local / S3 / Azure, container classification enforced | `src/services/storage/` | 20 tests (moto for S3; verified against real MinIO) |
| First-party `events`, partitioned monthly, consent on the row | `0004`, `src/models/event.py` | 3 raw-SQL tests in `tests/test_events.py` |
| Password reset (single-use, revokes all sessions) | `0005`, `/auth/password-reset*` | end-to-end test |
| Rate limiting: 10/min IP, 5/min account on auth endpoints | `src/services/rate_limit.py` | 2 tests |
| arq worker: partition extension + auth-row purge via SECURITY DEFINER functions | `src/workers/main.py`, `0005` | 2 tests in `tests/test_workers.py` |
| Typed TS client + CI drift gate | `packages/api-client/` | `tsc --noEmit`; `git diff --exit-code` in CI |
| CI pipeline | `.github/workflows/api.yml` (`quality` + `web` jobs) | verified green — see the run link below |
| Lead capture: contacts + leads (progressive profiling merges, not duplicates) + consent | `0007`, `src/services/{leads,consent}.py`, `/leads` | 8 tests in `tests/test_leads.py` |
| Event write path: `events` table now actually receives rows (login, magic-link, password-reset, token reuse, lead capture) | `src/services/events.py` | covered in `tests/test_leads.py` |
| Real TTLI brand (name, logo, `#8E151C`/`#BC222A`) replacing the placeholder navy/gold, extracted from ttli.co.za with documented provenance | `0008`, [docs/brand/ttli-brand-identity.md](brand/ttli-brand-identity.md), `apps/web/public/brand/` | migration round-trip; `apps/web` build/typecheck; HTTP smoke test against both demo tenants confirming `acme` is untouched |
| Admin lead view: paginated, tenant-scoped, gated on `analytics:view` | `src/services/leads.py::list_leads`, `/leads` (GET), `apps/web/app/admin/leads/` | 2 tests in `tests/test_leads.py`; HTTP smoke test through the real BFF against a logged-in admin |
| Guest account provisioning: unique-per-lead, time-limited, magic-link-only; expiry enforced at both magic-link consumption and refresh rotation | `src/services/guest_access.py`, `/guest-access` | 8 tests in `tests/test_guest_access.py`; HTTP smoke test confirmed real Mailhog delivery via the arq worker |
| Commerce foundation + EFT purchase path: server-resolved price/tax, data-driven tax engine, sequential gapless invoicing, append-only ledger, entitlements, the finance approval queue | `0009`, `src/services/{tax,orders,invoicing,ledger,entitlements,catalogue}.py`, `/products`, `/orders`, `/payments` | 12 tests in `tests/test_commerce.py`; HTTP smoke test — full EFT flow, reject/resubmit, 5x rapid order creation with no reference collisions |
| Real `apps/web` build: the prototype's design system (Charter serif, stone/surface palette, button/card/tag components) applied to every page; real TTLI copy, team photos and client logos from ttli.co.za (not placeholder content); routing restructured (`/` is now the marketing landing page, login moved to `/login`) | `apps/web/app/{globals.css,page.tsx,login/,guest-access/,catalogue/,checkout/,admin/payments/}`, `docs/brand/ttli-brand-identity.md` | `typecheck`/`build` clean, 11 routes; HTTP smoke test of the full journey — landing → guest-access → catalogue → checkout → EFT proof upload → finance approval → invoice, over the real BFF |
| BFF binary-body fix: the proxy forwarded every non-GET body through `request.text()`, which silently corrupts binary content (multipart file uploads) on the UTF-8 round-trip | `apps/web/app/api/bff/[...path]/route.ts` | Verified with an actual JPEG proof-of-payment upload through the real BFF: stored file is byte-identical to the original (same size, same MD5) |
| Security hardening: real ClamAV virus scan (REQ-BYPASS-08) before a payment-proof upload is stored, fail-closed if the scanner is unreachable; CSP with a per-request nonce + security headers on every `apps/web` response; `pip-audit`/`npm audit` wired into CI as real gates (35 CVEs found and fixed — see `requirements.txt`'s comment) | `src/services/antivirus.py`, `apps/web/proxy.ts`, `.github/workflows/api.yml` | `tests/test_antivirus.py` (real clamd: clean file, EICAR, unreachable-host); `tests/test_commerce.py::test_infected_payment_proof_is_refused_and_order_does_not_advance`; full gate sweep re-run clean after each dependency bump |

### Endpoints live

`GET /health` · `GET /health/ready` · `GET /auth/me` · `GET /tenant/theme` · `GET /leads` · `GET /orders/{id}` · `GET /products` · `GET /payments` · `POST /auth/login` · `POST /auth/magic-link` · `POST /auth/magic-link/consume` · `POST /auth/mfa/verify` · `POST /auth/mfa/enroll` · `POST /auth/mfa/enroll/confirm` · `POST /auth/refresh` · `POST /auth/password-reset` · `POST /auth/password-reset/confirm` · `POST /leads` · `POST /guest-access` · `POST /orders` · `POST /orders/{id}/checkout/eft` · `POST /orders/{id}/payment-proof` · `POST /payments/{id}/approve` · `POST /payments/{id}/reject` (non-health routes under `/api/v1`)

---

## 3. Phase 0 — Discovery and sign-off (BLOCKED)

Blocked on the customer, not on engineering. No code may start until this closes.

### Done

- [x] Requirement extraction from the source material, with traceability ([01 §3.12](01_PRD.md#312-requirement-traceability))
- [x] Nine internal contradictions in the source identified and adjudicated ([source/README.md](source/README.md))
- [x] Stack decided and justified ([01 §5](01_PRD.md#5-technical-decisions))
- [x] Delivery plan replacing the source's two irreconcilable schedules ([01 §8](01_PRD.md#8-delivery-plan))
- [x] Data model, API surface, security model, packaging and operations documented
- [x] `Streaming_Server` reuse assessed — what ports, what does not ([06 §3](06_OPERATIONS.md#3-media-pipeline))

### Outstanding

- [ ] **Decision register signed by the customer** — all 10 items in [01 §1.4](01_PRD.md#14-open-decisions-blocking-phase-0-sign-off)
- [ ] Accountants' written position on VAT for international digital services
- [ ] Azure Container Apps availability in South Africa North confirmed
- [ ] Content inventory — video count, total duration, source formats
- [ ] Unit-cost model built from that inventory ([06 §6](06_OPERATIONS.md#6-cost-model))
- [ ] Brand and design system
- [ ] Wireframes for the six persona views
- [ ] Payfast and Netcash sandbox accounts registered
- [ ] Information Officer registered with the Information Regulator (customer obligation)

---

## 4. Phase 1 — Foundation (~95%)

### Done — sprints 1–5

- [x] Monorepo skeleton: `apps/api`, `infra/`, `.github/`, `packages/api-client`
- [x] `infra/docker-compose.yml` on the reserved ports ([06 §1.1](06_OPERATIONS.md#11-services))
- [x] `.env.example` and `check_production_safety()` returning a list of problems
- [x] FastAPI skeleton, structlog, request IDs, the error envelope
- [x] Alembic baseline with `citext`, `pg_trgm`, `pgcrypto`
- [x] Tenancy: `tenant_id`, hostname resolution (Redis-cached, misses too), `SET LOCAL app.tenant_id`, RLS with `FORCE`, **least-privileged `app_user` connection**
- [x] Identity: Argon2id, JWT, lockout, timing-equalised login; magic links; TOTP with recovery codes and its own lockout; single-use MFA challenges
- [x] Refresh-token rotation: family revocation on reuse, device-fingerprint binding
- [x] Password reset: single-use, revokes every session, clears lockout
- [x] Field encryption (AES-GCM) and HMAC blind index
- [x] Append-only audit log — raising trigger *and* no UPDATE/DELETE grant for `app_user`
- [x] Seed migration: 17 permissions, 6 roles, 2 tenants, break-glass admin refused in production
- [x] Storage adapter across S3, Azure Blob and local; five classified containers
- [x] Events table, partitioned monthly, with a `SECURITY DEFINER` extension function
- [x] `packages/api-client` generation with a CI drift gate
- [x] Redis-backed rate limiting and the tenant-config cache
- [x] arq worker: monthly partition extension, daily expired-auth purge
- [x] `.github/workflows/api.yml` with the full gate set ([06 §4.5](06_OPERATIONS.md#45-deployment))

### Outstanding — to close Phase 1

- [x] Push to a remote and get CI green — [run 31318484520](https://github.com/WillemKlopper87/TTLI_LMS/actions/runs/31318484520)
- [x] CI builds/typechecks `apps/web` — new `web` job in `.github/workflows/api.yml` (renamed `ci` internally; file kept as `api.yml`), green on its first-ever run
- [x] `tenant_themes` ([02 §4.3](02_DATA_MODEL.md#43-tenant_themes)): table, seed, `GET /tenant/theme` — two hostnames return two palettes (`0006`)
- [x] `apps/web` (Next.js **16.3.0**, port 3010): tenant-themed login with the MFA step, empty admin shell, and a BFF proxy that sets `X-Tenant-Host` from the real Host header — dropping any smuggled value — so the browser never talks to the API directly (no CORS surface)
- [x] Email retry via arq ([HANDOFF.md §4](HANDOFF.md) weakness 7): `send_email` enqueues a `send_email_job` (`max_tries=5`) instead of sending inline; the request path never blocks on or fails because of SMTP

**Demo target — met, verified over HTTP, twice (Next 15 and again on Next 16):** `localhost:3010` renders TTLI Executive Institute in navy `#1B2A4A`; `meridian.localhost:3010` renders Meridian Holdings in green `#14532D` from the same build; login flows through the BFF (including a full POST proxy round-trip), MFA challenge included; the admin shell shows the signed-in principal and permissions.

> **Upgraded to Next 16** (was: deferred, see prior note below). Resolves the postcss/sharp CVEs `npm audit` flagged under 15 — `apps/web` audits clean now. The app was built async-API-clean from the start, so the only real casualty was Turbopack (16's new default builder): it cannot resolve `@ttli/api-client` through the `file:../../packages/api-client` npm-workspace symlink — a known, still-open upstream limitation (`vercel/next.js#85316`, `#88335`, `#77562`), not something in our config. Worked around with `--webpack` in both `dev` and `build` scripts (`apps/web/next.config.ts` documents why); Webpack resolves it exactly as it did under Next 15. Verified: clean `npm ci` from lockfiles in both `packages/api-client` and `apps/web`, `typecheck`, `build`, and the full two-tenant HTTP smoke test all pass identically to before the upgrade.

---

## 5. Phase 2 — Public site and content funnel (~55%)

Marketing pages, resource hub, podcasts, gated content, consent management, lead capture with UTM attribution, guest accounts with expiry and watermarking, event tracking.

### Done — no open decision blocks it

- [x] Lead capture: `POST /api/v1/leads` (03 §4.1) — always 204 (enumeration resistance, same rule as magic-link/password-reset), rate-limited 5/hour/IP (03 §1.8's guest-signup number, the closest documented analogue)
- [x] `contacts` (encrypted PII, same pattern as `users`) + `leads` (UTM quintet, source, score, stage, REQ-LEAD-02 progressive profiling — a second submission from the same person fills in more fields on the *same* row rather than duplicating it)
- [x] `consent_records` — append-only, two-layer enforcement identical to `audit_events` (revoked grant + raising trigger); privacy consent gates acceptance, marketing consent is recorded as its own purpose row
- [x] `events` write path is no longer theoretical — login, magic-link request, password-reset request, refresh-token reuse, and lead capture all write rows now
- [x] `GET /api/v1/leads` — paginated, tenant-scoped, gated on `analytics:view` (the seeded admin role already carries it — no new permission needed); backs the admin `Leads` screen (`apps/web/app/admin/leads`)
- [x] `POST /api/v1/guest-access` (03 §4.2, REQ-LEAD-04/05/06) — provisions a unique-per-lead, time-limited guest `users` row and emails a magic link (never a password); repeat requests refresh the same guest rather than duplicating it, and requests against an existing full account never downgrade it. The expiry window (decision #6, 7 vs 14 days) ships as `settings.guest_access_days` (default 7) rather than a hardcoded guess. Guest expiry is enforced at both points that actually gate access — magic-link consumption and refresh-token rotation, the latter raising its own `GuestAccessExpired` rather than being misclassified as token-theft
- [x] Real TTLI brand (name, logo, `#8E151C`/`#BC222A`) extracted from ttli.co.za and applied throughout `apps/web` — provenance in [docs/brand/ttli-brand-identity.md](brand/ttli-brand-identity.md), §2's table
- [x] A real marketing landing page at `apps/web/app/page.tsx` — the site's actual About narrative, "90+ organisations, 19 countries" track record, the *Lead with Intent* book, five real facilitator photos and nine real client logos (Standard Bank, HENSOLDT, De'Longhi and others), all extracted from ttli.co.za at the customer's own request, not invented copy. `/login` moved off the root path to make room for it — see the routing note in HANDOFF.md
- [x] `apps/web/app/guest-access/page.tsx` — a real form posting to `POST /guest-access`, not just the backend from the prior pass

### Outstanding — blocked on Phase 0 or genuinely not started

- [ ] The rest of the real site's pages as their own routes — Podcasts, "Lead With Intent"/"Cultivate with Intent" as dedicated pages, a working contact form. The landing page folds their content into one page for now; the real site's contact page has no form either, just contact details
- [ ] REQ-LEAD-05's sample-only entitlement/watermarking and REQ-LEAD-07's guest→paid conversion — both need course/enrolment tables that don't exist yet (Phase 4)
- [ ] The hourly guest-expiry downgrade sweep (02 §12.4) — expiry is enforced at the auth layer instead (see above); the sweep is about `status` bookkeeping, not access control, so it's a smaller follow-up
- [ ] The full CRM (`deals`, `tasks`, `notes`, `activities`, `campaigns`, `segments`, email tables) — deliberately out of scope here; that's Phase 5 (02 §10)

**Demo target:** the whole funnel, from a podcast to a working guest login, with the lead visible in admin. Met almost end to end — the real landing page's "Try a free lesson" CTA reaches a working `/guest-access` page, submissions are visible on `/admin/leads`, and the magic link signs in — the one piece still missing is an actual podcast episode page (Podcasts isn't ported as its own route yet).

---

## 6. Phase 3 — Commerce (~40%)

Catalogue, cart, checkout, Payfast and Netcash sandboxes, EFT with proof upload and finance approval, PO capture, sequential invoicing, append-only ledger, VAT engine, entitlements.

### Done — sprint 1: the EFT purchase path, end to end

- [x] `products`, `prices`, `tax_rules`, `orders`, `order_items`, `payments`, `invoice_number_counters`, `invoices`, `invoice_items`, `ledger_entries`, `entitlements` (`0009`) — 11 new tables, RLS on all, append-only enforcement on `ledger_entries` (same two-layer pattern as `audit_events`/`consent_records`)
- [x] Tax engine (`src/services/tax.py`, REQ-PAY-08): data-driven, not hardcoded — `0009` seeds only South African domestic VAT (15%), the one rate 01 §1.4 #2 doesn't block. International customers are refused with a clear, specific reason, never charged a guessed rate
- [x] `POST /orders` — prices and tax resolved server-side from `price_id` references, never a client-supplied amount (03 §5.1)
- [x] `POST /orders/{id}/checkout/eft`, `POST /orders/{id}/payment-proof`, `POST /payments/{id}/approve`, `POST /payments/{id}/reject` (REQ-PAY-03) — the full EFT lifecycle: bank details issued, proof uploaded, finance approves or rejects, rejection returns to `eft_pending_proof` for resubmission
- [x] Sequential, gapless invoice numbering (`src/services/invoicing.py`, REQ-PAY-09) — a per-`(tenant_id, series)` counter locked with `SELECT ... FOR UPDATE` inside the issuing transaction, not a Postgres sequence (which leaves gaps on rollback)
- [x] Entitlements granted only on the `fulfilled` transition, in the same transaction as invoice issuance and the ledger entries recording both (02 §6.2)
- [x] `GET /orders/{id}` — ownership-gated (a learner sees their own order; `payment:approve` is a separate, finance-only gate on approve/reject)
- [x] `GET /products` (public catalogue) and `GET /payments` (the finance approval queue, `payment:approve`-gated)
- [x] Real `apps/web` UI for the whole path: `/catalogue` (lists the real seeded product), `/checkout` (customer-type selection → EFT bank details → proof upload), `/admin/payments` (finance's approve/reject queue) — the EFT flow is no longer API-only

### Outstanding — blocked on external accounts, or genuinely not started

- [ ] Card checkout (Payfast/Netcash) — blocked on live sandbox credentials (01 §1.4's Phase 0 outstanding list), not a decision or a design gap
- [ ] PO capture — deferred to keep sprint 1 to one complete vertical slice (EFT) rather than three partial ones; the schema (`orders.po_number`/`po_document_key`, `po_pending_approval` status) already anticipates it
- [ ] Credit notes and refunds — `ledger_entries` already has `refund_issued`/`credit_note_issued` entry types ready; the issuing flow itself isn't built
- [ ] `Idempotency-Key` handling on `POST /orders`/`POST /payments/*` (03 §1.6, REQ-PAY-07) — deferred; matters most for the webhook retries that come with card checkout, which isn't built either. Not a silent gap: every state transition in `services/orders.py` checks the expected state first, so a genuine double-submission is refused (400), not silently re-processed — real double-invoicing is prevented even without full replay semantics
- [x] Virus scanning on the payment-proof upload (04 §2, REQ-BYPASS-08) — real ClamAV (`clamd`), fail-closed if unreachable
- [ ] Subscriptions — untouched on purpose; 01 §1.4 #5 is unsigned

**Demo target:** three purchase paths each producing an auditable invoice; a rejected EFT; a credit note. **Two of three met** — EFT produces an auditable invoice (verified: `INV-000001` format, correct VAT, entitlement granted, ledger entries written) and a rejected EFT correctly returns to `eft_pending_proof`. Card and PO paths, and the credit note, are the outstanding third.

> Nothing is sellable at the end of this phase — there is no course player yet. A working checkout demo will look like a finished business and is not one. See [05 §3](05_COMMERCIAL.md#what-is-sellable-and-when).

---

## 7. Phase 4 — Core LMS, anti-bypass, credentials (0%)

Course authoring, the ported media ladder, signed HLS, watermarking, heartbeat validation, the server-side completion rule engine, quizzes, surveys with per-survey anonymity, certificates with public verification, badges with LinkedIn sharing.

**Demo target:** attempt to skip a lesson and be refused with the specific unmet requirements listed; complete properly; verify the certificate from a phone.

---

## 8. Phases 4.5–7 (0%)

| Phase | Demo target |
|---|---|
| 4.5 PWA and accessibility | Installable app; WCAG 2.1 AA audit passed |
| 5 Corporate and workshops | A manager who cannot see individual scores until an admin enables it for one course |
| 6 AI insights | 500 survey responses summarised with zero identifiers transmitted, shown beside the redaction log |
| 7 Hardening and cloud | Load test at 100 concurrent; restore drill completed; POPIA matrix delivered |

---

## 9. Known gaps in what is already written

### Closed since the source material

- Two irreconcilable delivery schedules → one dependency-ordered plan
- Multi-tenancy contradiction → schema-ready now, white-label features later
- DRM contradiction → signed HLS at launch, DRM flag-gated
- Certificates/badges split → one engine, one phase
- Mobile contradiction → responsive web, then PWA, native deferred
- Encrypted email versus bulk marketing → resolved in [04 §4.4](04_SECURITY_AND_COMPLIANCE.md#44-how-marketing-works-against-encrypted-email)
- Azure Media Services recommendation → recorded as retired and unusable
- Two AI providers silently dropped → all four restored
- "Salt and hash everything" → corrected to hash-what-you-verify, encrypt-what-you-read

### Still open

- **[02 §13](02_DATA_MODEL.md#13-open-questions-for-engineering-review)** — UUID v7 generation, events partitioning granularity, blind index rotation, bespoke enterprise lesson modelling, cohort definition, heartbeat interval
- **[03 §13](03_API_SPEC.md#13-open-questions-for-engineering-review)** — heartbeat tolerance, concurrent session scope, verification rate limit, bulk invite ceiling, webhook replay window
- **[04 §11](04_SECURITY_AND_COMPLIANCE.md#11-open-questions)** — pepper rotation, blind index rotation, impersonation scope, legal hold, breach notification, minimum group size
- **[06 §8](06_OPERATIONS.md#8-open-questions)** — Container Apps region, CDN provider, transcode compute placement, backup residency, staging sanitisation
- **[05 §7](05_COMMERCIAL.md#7-before-any-of-this-is-quotable)** — the entire unit-cost model. No pricing is quotable until it exists

### Corrections made to the source material

| Source claim | Correction |
|---|---|
| "Azure Media Services (with DRM)" as a primary video option | Retired mid-2024. Not usable |
| Gate durations summing to 52–83 weeks alongside a stated 9–14 month total | Both discarded; one plan published |
| AI stack table naming only Azure OpenAI plus two fallbacks | The customer asked for four providers; Gemini and Copilot restored |
| "Salt and hash" all captured information | Impossible for data that must be read back; see [04 §4.1](04_SECURITY_AND_COMPLIANCE.md#41-what-the-customer-asked-for-and-what-is-actually-correct) |
| 15 roles at launch | Phased: 6 in Phase 1, corporate roles in Phase 5 |
| Illustrative pricing presented in quotable form | Marked not-quotable pending a cost model |

---

## 10. Recommended next three steps

1. **Put the decision register to the customer.** All ten items in [01 §1.4](01_PRD.md#14-open-decisions-blocking-phase-0-sign-off), as one document, for signature. Nothing else can start.
2. **Get the content inventory.** Video count, total duration, source formats. It feeds the transcode sizing *and* the cost model, and the cost model gates every price in [05_COMMERCIAL.md](05_COMMERCIAL.md).
3. **Verify Azure region availability and register the payment sandboxes.** Both have external lead times; neither should be discovered on the Phase 3 critical path.

### Running the verification that exists today

```bash
python docs/source/extract.py --check     # source fidelity against the export
python docs/check_links.py                # every relative link and anchor resolves
git rev-parse --show-toplevel             # repository isolation
```

---

## 11. Schedule reality

The source material claims 9–14 months for the full ecosystem while its own gate durations sum to 52–83 weeks. Neither figure survived review.

What can honestly be said: **Phase 0 is the only thing on the critical path right now, and it is entirely in the customer's hands.** Engineering ranges for Phases 1–7 exist in [01 §8](01_PRD.md#8-delivery-plan) but they are ranges for a small team against a signed scope, and there is no signed scope yet. Publishing a date before the decision register is closed would be inventing one.

The first genuinely sellable configuration arrives at the end of Phase 4, not Phase 3.
