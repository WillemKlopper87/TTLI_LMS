# STATUS

**Updated:** 2026-08-10 (Phase 5 complete; dependency-upgrade sprint — A/B/D/F/G shipped, C blocked/deferred, E pending — see §10)
**Scope reference:** [01_PRD.md](01_PRD.md) (requirements) · [02_DATA_MODEL.md](02_DATA_MODEL.md) (schema) · [03_API_SPEC.md](03_API_SPEC.md) (endpoints) · [04_SECURITY_AND_COMPLIANCE.md](04_SECURITY_AND_COMPLIANCE.md) (controls) · [05_COMMERCIAL.md](05_COMMERCIAL.md) (packaging) · [06_OPERATIONS.md](06_OPERATIONS.md) (infra)

---

## 1. Summary

Sprints 1–5 of Phase 1 are built; every gate passes against a live Postgres, Redis and MinIO. Phase 0 remains blocked on the customer — the foundation work was brought forward deliberately, because none of it depends on the ten open decisions.

Running the previously-blocked gates exposed that **Sprint 1's tenant isolation did not actually work**: the app connected as the Postgres superuser, which bypasses row-level security unconditionally. Fixed — the app now connects as a least-privileged `app_user` role created by the baseline migration, and the RLS suite passes as that role. The migration round-trip and a transaction-handling bug that silently discarded failed-login lockout counters were fixed in the same pass. Details in [HANDOFF.md §2](HANDOFF.md).

| Phase | Name | State | Done |
|---|---|---|---:|
| 0 | Discovery and sign-off | **BLOCKED** — 10 open decisions | 0% |
| 1 | Foundation | Built end-to-end, published, CI green | ~98% |
| 2 | Public site and content funnel | Leads, consent, events, guest access, the admin lead view, a real marketing landing page, a working contact form and a dedicated book page all built. Only Podcasts/"Cultivate with Intent" remain, blocked on missing content | ~70% |
| 3 | Commerce | Sprint 1: catalogue, orders, tax engine, the full EFT purchase path (now with a real UI, not just the API), sequential invoicing, the append-only ledger, the finance approval queue. Card (Payfast/Netcash) and PO checkout not started | ~40% |
| 4 | Core LMS, anti-bypass, credentials | Sprints 1–4 plus REQ-LMS-06/07 (transcript, captions), picked up in the 4.5 pass. Content model, the completion rule engine, enrolments, a real ported VOD transcode pipeline with signed HLS playback, heartbeat validation and WebVTT captions, quizzes/surveys/assignments with real auto-grading and anonymous-survey pseudonymisation, certificates/badges with a real PDF+QR/public verification/LinkedIn sharing, and a printable transcript. Only course/lesson/template *authoring UI* remains | ~95% |
| 4.5 | PWA and accessibility | Installable PWA (manifest, icons, service worker, offline shell), a real WCAG 2.1 AA contrast/labels/status-messages pass across `apps/web`. Push notifications deliberately deferred — no VAPID/content decision exists, same class of gap as Phase 3's payment-gateway sandbox creds | ~90% |
| 5 | Corporate, workshops, marketing | **Complete.** Sprint 1: organisations, seat-pool entitlements, PO checkout. Sprint 2: manager visibility (REQ-TEN-03) — the demo target itself, met. Sprint 3: facilitators, availability, workshops, sessions, capacity/waitlist booking, facilitator-overridable attendance, a pluggable meeting provider. Sprint 4: deal-centric CRM (deals/tasks/notes/activities) and a real marketing engine (segments, templates, campaigns, consent- and suppression-gated sending, a working unsubscribe link) | 100% |
| 6 | AI insights | Not started | 0% |
| 7 | Hardening and cloud | Not started | 0% |

| Gate | Status |
|---|---|
| `ruff check` / `ruff format --check` | **PASS** — 154 files |
| `mypy src` (strict) | **PASS** — 110 source files |
| `pytest` | **PASS** — 187 passed, **0 skipped**, run twice for determinism (against real Postgres, Redis, MinIO, Mailpit, ClamAV *and* real ffmpeg) |
| `pip-audit -r requirements.txt` | **PASS** — 0 known vulnerabilities |
| `npm audit` (`packages/api-client`, `apps/web`) | **PASS** — 0 vulnerabilities in both |
| `alembic upgrade head` | **PASS** — at `0019` |
| Migration round-trip | **PASS** — every revision downgrades and re-upgrades |
| `alembic check` | **PASS** — no model drift |
| `api-client` drift check | **PASS** — generated client committed, gate wired in CI |
| S3 adapter vs real MinIO | **PASS** — manual round-trip on port 9140 |
| Real ClamAV virus scan (clean + EICAR + unreachable-host) | **PASS** — `tests/test_antivirus.py`, real `clamd` on port 3410 |
| Real ffmpeg transcode → real HLS ladder → real playback through the BFF, incl. WebVTT captions | **PASS** — `tests/test_media.py`; live smoke test end to end (see HANDOFF.md's Thirteenth and latest passes) |
| Real quiz auto-grading, anonymous-survey pseudonymisation, virus-scanned assignment submissions | **PASS** — `tests/test_assessment.py`; live smoke test end to end (see HANDOFF.md's Fourteenth pass) |
| Real certificate PDF+QR generation, public verification, revocation, badge/certificate visibility, LinkedIn sharing | **PASS** — `tests/test_credentials.py`; live smoke test through the actual running dev servers and the real BFF, including the `/verify/[token]` page itself (see HANDOFF.md's Fifteenth pass) |
| Real printable transcript, owner-only, completed-lessons-only | **PASS** — `tests/test_learning.py`; live smoke test through the real BFF and the actual `/learn/[id]/transcript` page (see HANDOFF.md's latest pass) |
| WCAG 2.1 AA contrast audit | **PASS** — every text/background pair in `globals.css` computed against the real WCAG relative-luminance formula (not eyeballed); two failures found and fixed (`--faint` at 3.1:1, `--live` tag at 3.8:1 — both now 4.5:1+ in both themes) |
| PWA installability | **PASS** — manifest (dynamic, per-tenant `theme_color`/name via `app/manifest.ts`), 192/512/maskable icons, service worker with a real offline-shell fallback — verified live: `/manifest.webmanifest`, `/sw.js`, `/offline.html` all serve correctly, `<link rel="manifest">` and `theme-color` confirmed in rendered HTML |
| Source extraction fidelity | **PASS** — `python docs/source/extract.py --check` |
| Documentation link integrity | **PASS** — `python docs/check_links.py` |
| CI (`.github/workflows/api.yml`), `quality` + `web` jobs | **PASS** — green on both jobs on the first try, [run 31414239299](https://github.com/WillemKlopper87/TTLI_LMS/actions/runs/31414239299) (quality 3m57s, web 1m2s) |

**Headline:** 187 tests (0 skipped), 102 endpoints, 71 tables (events partitioned monthly ×14), 19 migrations, typed TS client with a CI drift gate, email delivery through the arq worker with retries, 26 `apps/web` routes, CSP + security headers on every `apps/web` response, virus-scanned uploads, dependency scanning (`pip-audit`, `npm audit`) wired into CI, a server-side completion rule engine gating real course progress across video/quiz/survey/assignment, a real ported VOD transcode pipeline with signed HLS playback and WebVTT captions, quizzes/surveys/assignments with real auto-grading and anonymous-survey pseudonymisation, certificates/badges with a real reportlab-rendered PDF and encrypted+blind-indexed public verification, a printable transcript, an installable PWA with a real offline shell, a WCAG 2.1 AA-verified colour system, a real organisation seat-pool purchasing flow (PO checkout → finance approval → seat pool → bulk invite/CSV import → revoke-and-reassign), manager visibility gated on all three of REQ-TEN-03's conditions at once, real workshop booking (facilitator availability, capacity/waitlist, facilitator-overridable attendance, a pluggable meeting provider), and a real CRM/marketing engine (deal-centric pipeline with an append-only activity trail, segments computed from lead attributes, campaign sends gated on both marketing consent and the suppression list, and a working one-click unsubscribe link) — closing out Phase 5.

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
| Guest account provisioning: unique-per-lead, time-limited, magic-link-only; expiry enforced at both magic-link consumption and refresh rotation | `src/services/guest_access.py`, `/guest-access` | 8 tests in `tests/test_guest_access.py`; HTTP smoke test confirmed real SMTP delivery via the arq worker (Mailpit, since §10) |
| Commerce foundation + EFT purchase path: server-resolved price/tax, data-driven tax engine, sequential gapless invoicing, append-only ledger, entitlements, the finance approval queue | `0009`, `src/services/{tax,orders,invoicing,ledger,entitlements,catalogue}.py`, `/products`, `/orders`, `/payments` | 12 tests in `tests/test_commerce.py`; HTTP smoke test — full EFT flow, reject/resubmit, 5x rapid order creation with no reference collisions |
| Real `apps/web` build: the prototype's design system (Charter serif, stone/surface palette, button/card/tag components) applied to every page; real TTLI copy, team photos and client logos from ttli.co.za (not placeholder content); routing restructured (`/` is now the marketing landing page, login moved to `/login`) | `apps/web/app/{globals.css,page.tsx,login/,guest-access/,catalogue/,checkout/,admin/payments/}`, `docs/brand/ttli-brand-identity.md` | `typecheck`/`build` clean, 11 routes; HTTP smoke test of the full journey — landing → guest-access → catalogue → checkout → EFT proof upload → finance approval → invoice, over the real BFF |
| BFF binary-body fix: the proxy forwarded every non-GET body through `request.text()`, which silently corrupts binary content (multipart file uploads) on the UTF-8 round-trip | `apps/web/app/api/bff/[...path]/route.ts` | Verified with an actual JPEG proof-of-payment upload through the real BFF: stored file is byte-identical to the original (same size, same MD5) |
| Security hardening: real ClamAV virus scan (REQ-BYPASS-08) before a payment-proof upload is stored, fail-closed if the scanner is unreachable; CSP with a per-request nonce + security headers on every `apps/web` response; `pip-audit`/`npm audit` wired into CI as real gates (35 CVEs found and fixed — see `requirements.txt`'s comment) | `src/services/antivirus.py`, `apps/web/proxy.ts`, `.github/workflows/api.yml` | `tests/test_antivirus.py` (real clamd: clean file, EICAR, unreachable-host); `tests/test_commerce.py::test_infected_payment_proof_is_refused_and_order_does_not_advance`; full gate sweep re-run clean after each dependency bump |
| Course content model (global, not tenant-scoped) + the server-side completion rule engine + enrolments sourced from an entitlement | `0011`, `src/services/{completion,enrolment}.py`, `/enrolments`, `/lessons/{id}/start`, `/lessons/{id}/complete` | 7 tests in `tests/test_learning.py`; live HTTP smoke test against a running server — real refusal (`"0s spent of 30s required"`) then a real completion after waiting past the threshold, next lesson correctly unlocked |
| Ported VOD transcode pipeline (real ffmpeg) + signed HLS playback with token-rewritten manifests + heartbeat-validated watch progress | `0012`, `src/services/media/{ffmpeg,transcoder,pipeline,playback}.py`, `src/services/video_progress.py`, `/video-assets`, `/media/{id}/playback`, `/media/{id}/hls/{filename}`, `/lessons/{id}/heartbeat` | 18 tests in `tests/test_media.py`/`test_media_ffmpeg.py` (real ffmpeg, not mocked); live smoke test — real transcode, playback through the actual BFF, MD5-identical segment delivery, seek-beyond-furthest-position refused |
| Quizzes (auto-graded + manually-graded), anonymous/identified surveys, virus-scanned assignments, all wired into the completion rule engine | `0013`, `src/services/{quiz,survey,assignment}.py`, `/quizzes`, `/surveys`, `/assignments` and their sub-routes | 9 tests in `tests/test_assessment.py`; live smoke test — real quiz with mixed auto/manual grading, anonymous survey response verified `user_id IS NULL` at the database level, infected assignment submission refused, clean one approved |
| Certificates and badges: real PDF (reportlab) with an embedded scannable QR code, encrypted+blind-indexed verification token (reconstructable, unlike a hashed magic-link token), public verification page gated on learner-chosen visibility, revocation with audit trail, LinkedIn "Add to Certification" sharing | `0014`, `src/services/credentials.py`, `/enrolments/{id}/credentials`, `/certificates/{id}/pdf`, `/verify/{token}`, `/certificates/{id}/revoke`, `/certificates/{id}` (PATCH), `/badges/{id}` (PATCH), `/badges/{id}/share/linkedin` | 5 tests in `tests/test_credentials.py`; live smoke test through the actual running dev servers over the real BFF — course completion issuing a real certificate+badge, a real downloaded PDF confirmed to start with `%PDF`, visibility toggled from private to public through the exact `PATCH` calls the frontend makes, the public `/verify/[token]` page itself returning 200 |
| Real `apps/web` UI: `credentials-panel.tsx` (certificate/badge cards, visibility selectors, PDF download, LinkedIn share) wired into `/learn/[enrolmentId]`; the public, unauthenticated `/verify/[token]` page (REQ-CRED-03) | `apps/web/app/learn/[enrolmentId]/credentials-panel.tsx`, `apps/web/app/verify/[token]/page.tsx` | `typecheck`/`build` clean; live smoke test confirmed the BFF proxy (extended to forward `PATCH`) round-trips both visibility toggles and the `/verify/[token]` route renders |
| WebVTT captions (REQ-LMS-07): human-authored upload, served through the same signed playback token as HLS segments — no new entitlement path | `0015`, `/video-assets/{id}/captions`, `services/media/playback.py` (`.vtt` content-type) | 1 test in `tests/test_media.py`; live smoke test — real ffmpeg transcode, real caption upload, `has_captions`/`captions_url` confirmed through the real BFF |
| Printable transcript (REQ-LMS-06): completed lessons only, real `completed_at` timestamps, owner-only | `src/services/enrolment.py::get_transcript`, `/enrolments/{id}/transcript`, `apps/web/app/learn/[enrolmentId]/transcript/page.tsx` (browser print, not a generated PDF) | 1 test in `tests/test_learning.py`; live smoke test — real course completion, transcript empty before and fully populated after, the actual print page returning 200 |
| WCAG 2.1 AA: computed contrast audit (not eyeballed) found and fixed two real palette failures; form labels added where only a placeholder existed (login, quiz/survey free-text, assignment upload, admin reject-reason); `role="alert"` on 16 dynamic status messages; table header `scope`; heading-hierarchy fix | `apps/web/app/globals.css`, `login-form.tsx`, `quiz-player.tsx`, `survey-form.tsx`, `assignment-upload.tsx`, `admin/payments/page.tsx`, `admin/leads/page.tsx`, `catalogue/page.tsx` | Contrast ratios verified with the actual WCAG relative-luminance formula; `typecheck`/`build` clean |
| Installable PWA: dynamic per-tenant manifest, 192/512/maskable icons generated from the real TTLI brand mark, a service worker with a genuine offline-shell fallback (not fabricated offline data sync) | `apps/web/app/manifest.ts`, `register-sw.tsx`, `public/sw.js`, `public/offline.html` | Live-verified against the running dev server: `/manifest.webmanifest` resolves the real tenant theme, `/sw.js` and `/offline.html` serve correctly, `<link rel="manifest">`/`theme-color` confirmed in rendered HTML |
| Organisations and seat-pool entitlements (02 §4.5, REQ-TEN-02) + PO checkout (closes Phase 3's deferred PO gap): self-service org creation, a null-`user_id` pool entitlement vs a set-`user_id` assigned seat, "available" always computed rather than tracked as a drifting counter | `0016`, `src/services/organisations.py`, `src/routers/organisations.py`, `_fulfil_order()` shared helper in `src/services/orders.py` | 8 tests in `tests/test_organisations.py`; live smoke test through the real BFF — org created, PO submitted with its document in one step, finance approved, seat pool activated, one seat invited then revoked and its capacity confirmed free for reassignment |
| Real `apps/web` UI: `/organisations` (list/create), `/organisations/[id]` (members, seat summary per course, invite-by-email, CSV import, per-course seat-holder list with revoke), `/organisations/[id]/buy-seats` (programme + quantity → PO number/document in one step, mirroring `/checkout`'s EFT flow) | `apps/web/app/organisations/**` | `typecheck`/`build` clean, 3 new routes; live smoke test drove every screen's underlying call through the real BFF end to end |
| Manager visibility (02 §4.5, REQ-TEN-03, 04 §2.3's P2 policy — the Phase 5 demo target): aggregate-only by default, individual rows require the course toggle *and* the tenant toggle *and* the viewer holding a real per-organisation grant, all at once — response shape is determined by policy, not query parameters, so a failing condition means the row is absent, never present-and-redacted | `0017`, `src/services/reports.py`, `GET /organisations/{id}/reports/progress`, `PATCH /courses/{id}/manager-visibility`, `GET/PATCH /tenant/settings/manager-visibility` | 6 tests in `tests/test_reports.py`; live smoke test — report correctly aggregate-only before either toggle, individual row appears the instant both toggles and the org-admin viewer condition hold, matching the exact demo scenario |
| Real `apps/web` UI: `/admin/settings` (tenant toggle, per-course visibility dropdown), a "Report" panel added to `/organisations/[id]` (aggregate stats always, individual rows only when the API says they're visible) | `apps/web/app/admin/settings/page.tsx`, `apps/web/app/organisations/[id]/page.tsx` | `typecheck`/`build` clean, 1 new route; live smoke test confirmed both pages render and the toggle round-trip works through the real BFF |
| Workshops, facilitators, booking (02 §9, REQ-WS-01 through 03/05 through 08): weekly facilitator availability windows with real conflict/outside-availability rejection, capacity enforcement with a real waitlist that promotes the earliest waitlisted booking the instant a seat frees up, facilitator-overridable attendance (a facilitator's manual call always wins over any provider report), a pluggable meeting-provider contract with a fully-working `manual` fallback | `0018`, `src/models/workshop.py`, `src/services/workshops.py`, `src/services/meeting/{base,manual,teams}.py`, `src/routers/{workshops,courses}.py` | 5 tests in `tests/test_workshops.py`; live smoke test through the real BFF — facilitator registered, availability added, workshop and session created, learner booked (real manual meeting link with `join_url: null` provisioned), facilitator viewed the roster (a stranger correctly refused with 403), attendance marked `attended` |
| Real `apps/web` UI: `/admin/workshops` (facilitator registration + availability, workshop/session creation for `workshop:manage` holders, booking for any authenticated user, a roster/attendance panel gated the same way the API gates it) | `apps/web/app/admin/workshops/page.tsx` | `typecheck`/`build` clean, 1 new route; live smoke test drove every screen's underlying call through the real BFF end to end |
| Deal-centric CRM (02 §10, REQ-CRM-01/02): `deals`/`tasks`/`notes` all hang off a deal, every mutation writes a real `activities` row (append-only, same two-layer enforcement as `consent_records`) — a deal always carries its own complete history, never a derived view | `0019`, `src/models/crm.py`, `src/services/deals.py`, `src/routers/deals.py` | 4 tests in `tests/test_deals.py`; live smoke test through the real BFF — a real public lead capture → deal created → stage changed → task created and completed → note added, deal detail returning the full activity trail in order |
| Marketing engine (02 §10, REQ-CRM-04): segments computed from lead stage/UTM attributes (never a stored address list), campaign sends gated on **both** current marketing consent and the suppression list independently, a real one-click unsubscribe link embedded in every send that actually revokes consent and suppresses future sends (not just logs an event), a bounce-webhook code path structured the way a real ESP would call it. No separate ESP provider abstraction (unlike workshops' meeting providers) — `services/email.py`'s real SMTP path already sends both transactional and bulk mail; REQ-CRM-03's SPF/DKIM/DMARC is a DNS/domain decision, not a code gap | `0019`, `src/services/campaigns.py`, `src/routers/campaigns.py` | 5 tests in `tests/test_campaigns.py`; live smoke test — real send to a real Mailpit-delivered inbox (subject *and* body both `{{first_name}}`-substituted — a real bug found live and fixed, the subject substitution was originally missed), the real unsubscribe link followed end to end, confirmed to exclude the contact from a second campaign send via the consent gate |
| Real `apps/web` UI: `/admin/deals` (pipeline list, deal creation, an expandable detail panel with stage/tasks/notes/activity trail), `/admin/campaigns` (segment/template/campaign creation, send, live stats), `/unsubscribe/[id]` (the public one-click landing page the email link resolves to) | `apps/web/app/admin/deals/page.tsx`, `apps/web/app/admin/campaigns/page.tsx`, `apps/web/app/unsubscribe/[id]/page.tsx` | `typecheck`/`build` clean, 3 new routes; live smoke test confirmed every page renders with no console/server errors |

### Endpoints live

`GET /health` · `GET /health/ready` · `GET /auth/me` · `GET /tenant/theme` · `GET /tenant/settings/manager-visibility` · `GET /leads` · `GET /orders/{id}` · `GET /products` · `GET /payments` · `GET /courses` · `GET /enrolments` · `GET /enrolments/{id}/progress` · `GET /enrolments/{id}/credentials` · `GET /enrolments/{id}/transcript` · `GET /video-assets/{id}` · `GET /media/{id}/playback` · `GET /media/{id}/hls/{filename}` · `GET /surveys/{id}` · `GET /certificates/{id}/pdf` · `GET /verify/{token}` · `GET /badges/{id}/share/linkedin` · `GET /organisations` · `GET /organisations/{id}` · `GET /organisations/{id}/members` · `GET /organisations/{id}/seats` · `GET /organisations/{id}/seats/{course_id}/assignments` · `GET /organisations/{id}/reports/progress` · `GET /facilitators` · `GET /facilitators/{id}/availability` · `GET /workshops` · `GET /workshops/{id}/sessions` · `GET /sessions/{id}/roster` · `GET /deals` · `GET /deals/{id}` · `GET /segments` · `GET /email-templates` · `GET /campaigns` · `GET /campaigns/{id}` · `GET /unsubscribe/{email_send_id}` · `POST /auth/login` · `POST /auth/magic-link` · `POST /auth/magic-link/consume` · `POST /auth/mfa/verify` · `POST /auth/mfa/enroll` · `POST /auth/mfa/enroll/confirm` · `POST /auth/refresh` · `POST /auth/password-reset` · `POST /auth/password-reset/confirm` · `POST /leads` · `POST /guest-access` · `POST /orders` · `POST /orders/{id}/checkout/eft` · `POST /orders/{id}/checkout/po` · `POST /orders/{id}/payment-proof` · `POST /payments/{id}/approve` · `POST /payments/{id}/reject` · `POST /lessons/{id}/start` · `POST /lessons/{id}/complete` · `POST /lessons/{id}/heartbeat` · `POST /video-assets` · `POST /lessons/{id}/video` · `POST /video-assets/{id}/captions` · `POST /quizzes` · `POST /quizzes/{id}/questions` · `POST /lessons/{id}/quiz` · `POST /quizzes/{id}/attempts` · `POST /quiz-attempts/{id}/submit` · `POST /quiz-answers/{id}/grade` · `POST /surveys` · `POST /surveys/{id}/questions` · `POST /lessons/{id}/survey` · `POST /surveys/{id}/responses` · `POST /assignments` · `POST /lessons/{id}/assignment` · `POST /assignments/{id}/submissions` · `POST /assignment-submissions/{id}/review` · `POST /certificates/{id}/revoke` · `POST /organisations` · `POST /organisations/{id}/seats/invite` · `POST /organisations/{id}/seats/import` · `POST /organisations/{id}/seats/{entitlement_id}/revoke` · `POST /facilitators` · `POST /facilitators/{id}/availability` · `POST /workshops` · `POST /workshops/{id}/sessions` · `POST /sessions/{id}/book` · `POST /bookings/{id}/cancel` · `POST /sessions/{id}/attendance` · `POST /deals` · `POST /deals/{id}/tasks` · `POST /tasks/{id}/complete` · `POST /deals/{id}/notes` · `POST /segments` · `POST /email-templates` · `POST /campaigns` · `POST /campaigns/{id}/send` · `POST /email-events/bounce` · `PATCH /deals/{id}/stage` · `PATCH /certificates/{id}` · `PATCH /badges/{id}` · `PATCH /courses/{id}/manager-visibility` · `PATCH /tenant/settings/manager-visibility` (non-health routes under `/api/v1`)

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
- [x] `apps/web/app/contact/page.tsx` — a real, working contact form (the live site's own contact page has none, just contact details) posting to `POST /leads` with `source="contact_form"`; `leads.message` (`0010`) carries the free-text body and surfaces in the admin Leads screen
- [x] `apps/web/app/lead-with-intent/page.tsx` — a dedicated page for the founder's book, using the real extracted copy, not the landing page's teaser only

### Outstanding — blocked on Phase 0 or genuinely not started

- [ ] Podcasts and "Cultivate with Intent" as dedicated routes — the real site names both in its nav, but no episode/page content was ever extracted for either, so building them now would mean fabricating copy. Same content-inventory gap as Phase 0, not a missed task
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

## 7. Phase 4 — Core LMS, anti-bypass, credentials (~95%)

Course authoring, the ported media ladder, signed HLS, watermarking, heartbeat validation, the server-side completion rule engine, quizzes, surveys with per-survey anonymity, certificates with public verification, badges with LinkedIn sharing.

### Done — sprint 1: content model, the completion rule engine, enrolments

- [x] `courses`, `modules`, `lessons` (`0011`) — deliberately **not** tenant-scoped (02 §1.3: "the global course catalogue rows that all tenants share"); `course_tenant_assignments` controls per-tenant visibility instead of duplicating rows
- [x] `Product.course_id` bridges commerce to learning for real — `services/orders.py::approve_eft` resolves the actual course now, not the product's own id used as a stand-in before this sprint. Both demo tenants' existing seeded products point at the one seeded course, proving the "one course, two tenant-branded bundles at different prices" shape (02 §6.1)
- [x] `enrolments`, `lesson_completions` (`0011`, tenant-scoped, RLS) — an enrolment is created only from `approve_eft`, in the same transaction as the entitlement grant, never independently
- [x] The completion rule engine (`src/services/completion.py`, REQ-BYPASS-01/02): evaluates `minimum_time_seconds` for real against server-assigned timestamps; a rule field whose subsystem doesn't exist yet (video, quiz, survey, assignment, live attendance) evaluates as **not met** with a specific reason, never silently skipped
- [x] `POST /lessons/{id}/start` (idempotent), `POST /lessons/{id}/complete` (423 `LESSON_LOCKED` with the unmet-requirements checklist on refusal), `GET /enrolments/{id}/progress`, `GET /enrolments` (REQ-LMS-03's discovery list) — all ownership-gated
- [x] Prerequisite enforcement (REQ-BYPASS-10): a strict linear chain by `(module.position, lesson.position)` this sprint — no drip-release dates or cohorts yet (02 §13 open question)
- [x] Every progression decision is audit-logged, including refusals (REQ-BYPASS-11) — `audit_events.action` = `lesson.completed` / `lesson.completion_refused`
- [x] Real `apps/web` UI: `/learn` (my courses) and `/learn/[enrolmentId]` (the lesson checklist, start/complete buttons) — post-login routing now sends learners here instead of the admin shell, and staff (any `analytics:view`/`payment:approve` holder) to `/admin`
- [x] Seeded one demo course ("Executive Leadership Certificate", one module, two document lessons) — explicitly structural content to exercise the mechanics end to end, the same precedent `0009`'s demo product set; not real TTLI curriculum, which was never provided

### Done — sprint 2: the ported VOD transcode pipeline, signed HLS, heartbeat validation

- [x] `video_assets`, `transcode_jobs`, `video_progress`, `video_heartbeats` (`0012`) — the first two global (like `courses`), the last two tenant-scoped/RLS like `enrolments`
- [x] `src/services/media/{ffmpeg,transcoder,pipeline}.py` — the VOD ladder ported from `Streaming_Server`'s `transcoding-engine.js` (06 §3.2): one decode, N encodes via a single `filter_complex split`, IDR pinned to segment boundaries, CMAF/fMP4 output, VOD-only (this platform never streams live, so the source's live sliding-window mode wasn't ported). Runs as an arq job (`transcode_video_job`) off the request path
- [x] `POST /video-assets` (upload, `course:edit`-gated, virus-scanned through the same `services/antivirus.py` the payment-proof path uses) · `GET /video-assets/{id}` · `POST /lessons/{id}/video` (a narrow single-field attach, not general lesson authoring)
- [x] Signed HLS playback (`src/services/media/playback.py`, 03 §6.7): entitlement checked before a URL is ever minted, Redis-backed short-lived tokens, `GET /media/{id}/hls/{filename}` rewrites every manifest's internal references to carry the token — the "media players cannot set headers on segment requests" constraint 06 §3.2 inherited from the source project, solved for real here since nothing in `Streaming_Server` had to
- [x] Concurrent-session cap (REQ-BYPASS-09) — the oldest playback session is evicted when a new one exceeds the configured limit, not the newest
- [x] Heartbeat validation (`src/services/video_progress.py`, REQ-BYPASS-02/03/04): server-assigned timestamps only, `watched_seconds` bounded by real elapsed wall-clock time per heartbeat, `furthest_position_seconds` seek ceiling refuses forward jumps
- [x] `video_watch_percentage` graduated out of the rule engine's "not available yet" list — real watch data now backs it
- [x] Real `apps/web` video player (`app/learn/[enrolmentId]/video-player.tsx`, hls.js) with a real watermark overlay and heartbeat pings every 5s

### Done — sprint 3: quizzes, surveys with per-survey anonymity, assignments

- [x] `quizzes`, `quiz_questions`, `quiz_attempts`, `quiz_answers`, `surveys`, `survey_questions`, `survey_responses`, `assignments`, `assignment_submissions` (`0013`) — question banks global like `courses`; attempts/responses/submissions tenant-scoped/RLS like `enrolments`
- [x] Quiz-taking (REQ-ASSESS-01/02/03, REQ-BYPASS-05/06): server-side randomised question/option order persisted per attempt, attempt limits and time limits enforced server-side, correct answers never sent to the client before submission. `single_choice`/`multiple_choice`/`true_false` auto-grade at submission; `short_text`/`long_text` stay ungraded (`passed=null`, genuinely unknown, not failed) until a `quiz:grade` holder grades them, which re-finalises the attempt's score
- [x] Anonymous surveys (REQ-ASSESS-05): `respondent_reference` is `CryptoBox.blind_index(f"{survey_id}:{enrolment_id}")` — the same mechanism `contacts.email_blind_index` already uses — so duplicate submissions are rejected and the completion rule engine can confirm *this enrolment* responded, without `user_id` ever being written for an anonymous response. Verified directly at the database level, not just via the API: `user_id` is genuinely `NULL`, and a matching `audit_events` row (`actor_user_id=NULL`) proves anonymisation happened at submission time
- [x] Assignments (REQ-BYPASS-08): submissions virus-scanned through the same `services/antivirus.py` payment-proof/video-source uploads use, fail-closed; `POST /assignment-submissions/{id}/review` approves or rejects, gated on `quiz:grade` (no dedicated `assignment:review` permission exists yet — the facilitator role that would naturally hold one is Phase 5)
- [x] `quiz_pass_score`, `survey_required`, `assignment_approval_required` graduated out of the rule engine's "not available yet" list — real data now backs all three, joining `video_watch_percentage` from sprint 2. Only `live_attendance_required` (Phase 5) remains unbacked
- [x] Real `apps/web` UI: `quiz-player.tsx` (question rendering by type, submit, score/passed display), `survey-form.tsx` (anonymous surveys say so on screen), `assignment-upload.tsx` (file picker, virus-rejection message), all wired into `/learn/[enrolmentId]` by `activity_type`

### Done — sprint 4: certificates, badges, public verification

- [x] `certificate_templates`, `certificates`, `badge_templates`, `badges`, `credential_verifications` (`0014`) — templates global like `courses`; the rest tenant-scoped/RLS like `enrolments`. `courses.certificate_template_id`/`badge_template_id` (nullable FKs) — 02 §5.1 described these as already present on `courses`, but `0011` deliberately deferred them until the target tables existed
- [x] `verification_token` is encrypted + blind-indexed (`CryptoBox.encrypt`/`blind_index`, the same pattern `contacts.email_encrypted`/`email_blind_index` already established), not one-way hashed like a magic-link/refresh token — it has to be *reconstructable* for `GET /badges/{id}/share/linkedin`'s `certUrl`, which a hash can never support. **Caught and fixed before commit**, not after: the migration was first written with a hash, the design gap surfaced while wiring the LinkedIn endpoint, and the schema/model/service were corrected together — see `0014`'s migration docstring
- [x] `certificate_templates.issuer_name` — a second real gap caught in this pass: the template only had `signatory_name` (the *person* who signs), and the code was putting that person's name into LinkedIn's `organizationName` field. `badge_templates` already modelled issuer separately from signatory; `certificate_templates` now does too
- [x] Issuance has no direct endpoint (REQ-CRED-01) — `services/credentials.py::issue_for_completed_enrolment` is called only from `services/enrolment.py::complete_lesson`, at the exact moment the rule engine confirms the course is complete; a course with neither template configured issues nothing, idempotent if called twice
- [x] Real PDF generation (`reportlab`, landscape A4) with an embedded scannable QR code (`qrcode[pil]`) pointing at an absolute verification URL (`PUBLIC_WEB_URL`, new setting — unlike the BFF's relative-path convention, a QR code a phone camera resolves needs an absolute URL); stored via the existing storage service under `GENERATED_DOCUMENTS`, served through a 300s signed URL
- [x] `GET /verify/{token}` (public, unauthenticated, rate-limited 20/hour/IP like `POST /leads`): a `private`-visibility certificate (REQ-CRED-07's default) behaves identically to an unknown token — visibility gates the page itself, not just a listing. Every lookup is logged, hit or miss, doubling as abuse detection
- [x] `POST /certificates/{id}/revoke` (`certificate:revoke`-gated, reason required, audited); `PATCH /certificates/{id}` and `PATCH /badges/{id}` (learner-controlled `private`/`public`/`link_only`, REQ-CRED-07) — the certificate half of this didn't exist until this pass either, found by checking `GET /verify/{token}`'s own gating logic against what the API actually let a learner change
- [x] `GET /enrolments/{id}/credentials` — a fourth gap found while building the frontend: there was no way for a learner's own client to discover the certificate/badge IDs every other endpoint above needs. Owner-only, returns both (nullable) for a given enrolment
- [x] `GET /badges/{id}/share/linkedin` — LinkedIn's documented `profile/add` deep-link query parameters, reconstructing the exact verification URL embedded in the original PDF's QR code from the encrypted token, never a re-derived one
- [x] Real `apps/web` UI: `credentials-panel.tsx` on `/learn/[enrolmentId]` (certificate/badge cards, visibility selectors, PDF download, LinkedIn share), and the public `/verify/[token]` page (REQ-CRED-03) — required extending the BFF proxy to forward `PATCH`, which it didn't before this sprint

### Done — REQ-LMS-06/07: printable transcript, WebVTT captions (picked up during the 4.5 pass)

- [x] `GET /enrolments/{id}/transcript` (REQ-LMS-06) — completed lessons only, each with the real `completed_at` the rule engine assigned, not the full progress checklist `GET /enrolments/{id}/progress` already serves. `identity.py` gained a `display_name()` helper (full name, else email fallback) refactored out of `credentials.py`'s issuance code and reused here — the same learner-name resolution, not a second implementation that could drift
- [x] `video_assets.caption_object_key` (`0015`) + `POST /video-assets/{id}/captions` (REQ-LMS-07) — human-authored WebVTT upload, not automatic transcription (no ASR pipeline exists in this project, and fabricating caption text for content nobody wrote would be worse than no captions). Served through the exact same signed playback token as HLS segments, not a new entitlement path — `<track kind="captions">` in `video-player.tsx`
- [x] Real `apps/web` UI: `/learn/[enrolmentId]/transcript` (browser print via `window.print()` and a real `@media print` rule, not a generated PDF — the certificate already owns that treatment)

### Outstanding — the rest of Phase 4

- [ ] Course/lesson/template authoring UI — content, question banks and now certificate/badge templates are migration-seeded or wired via direct SQL in tests, same precedent as Phase 3 sprint 1's seeded product; no authoring *screen* exists yet for any of them, though the API endpoints a real one would call now do (learning content) or don't yet (templates — no `POST /certificate-templates` exists, matching REQ-CRED-01's "no direct issuance endpoint" reasoning doesn't apply to templates themselves, this is a genuine gap, not a deliberate omission)

**Demo target:** attempt to skip a lesson and be refused with the specific unmet requirements listed; complete properly; verify the certificate from a phone. **Met** — verified live over real HTTP against running servers (not just the test suite): started a lesson, got refused early with `"0s spent of 30s required"`, waited the real threshold, completed it, watched the next lesson unlock; uploaded a real video, watched a real ffmpeg transcode complete, played it back through signed HLS end to end through the actual BFF with byte-identical (MD5-verified) segment delivery, and confirmed a seek beyond the furthest watched position is refused; took a real quiz with a mix of auto-graded and manually-graded questions, watched the score/passed state update correctly at each stage; submitted an anonymous survey response and confirmed anonymity at the database level; submitted a real assignment, had an infected one refused by the virus scanner, and approved a clean one; completed the full seeded course and had a real certificate+badge issued, downloaded a real PDF with a scannable QR, verified it on the actual public `/verify/[token]` page, toggled visibility from private to public through the real UI path, and shared it via LinkedIn's own deep link.

---

## 8. Phase 4.5 — PWA and accessibility (~90%)

Installable PWA, offline shell, WCAG 2.1 AA audit and remediation (01 §5.9/§6.6). Push notifications are the one piece deliberately not built.

### Done

- [x] Dynamic web app manifest (`apps/web/app/manifest.ts`, not a static `public/manifest.json`) — `theme_color`/`name`/`short_name` resolve the *signed-in tenant's* own theme via the same `getTheme()` server call `layout.tsx` already uses, so a white-label tenant installs under its own identity, not TTLI's hardcoded one. `short_name` is computed (initials when the tenant name is too long for a home-screen label) since the API has no dedicated short-name field
- [x] Icons generated from the real TTLI brand mark (`public/brand/ttli-mark.png`), not a placeholder — 192×192 and 512×512 `any`-purpose, plus a 512×512 `maskable` variant with the mark kept inside the ~80% safe zone every OS mask (circle, squircle, rounded-square) crops to
- [x] Service worker (`public/sw.js`) with a genuine offline-shell fallback, not fabricated offline data sync — this platform's content is per-tenant and server-rendered from a live API, so caching course/lesson data would need background sync and conflict resolution this project has no infrastructure for. What it honestly provides: network-first navigation, falling back to a real branded `offline.html` (not the browser's default connection-error page) only when the network request itself fails
- [x] iOS-specific PWA meta tags (`apple-mobile-web-app-capable`, `apple-touch-icon`) — iOS Safari doesn't read the web manifest for "Add to Home Screen"
- [x] WCAG 2.1 AA contrast audit — every color pair in `globals.css` computed against the actual WCAG relative-luminance formula (`(L1+0.05)/(L2+0.05)`), not eyeballed. Two real failures found: `--faint` at 3.1:1 on white (used pervasively for timestamps/helper text/loading states, all normal-weight text well under the "large text" threshold) and `.tag--live`'s color at 3.8:1 against its own wash (tags render at 9px, nowhere near large-text size). Both corrected to 4.5:1+ in both light and dark mode, verified against every surface each token actually appears on (not just one background)
- [x] Missing accessible names fixed where a `placeholder` was standing in for a `<label>` (WCAG 1.3.1/3.3.2/4.1.2) — most notably the login form's email/password/MFA-code inputs, the single most important form in the app, which had none. Also fixed: the admin payment-rejection reason input, quiz/survey free-text answers, the assignment file picker. Login inputs also gained `autoComplete` values (`email`/`current-password`/`one-time-code` — WCAG 1.3.5)
- [x] `role="alert"` added to 16 dynamic status/error messages across every form and async action in `apps/web` (WCAG 2.1's SC 4.1.3, Status Messages) — screen readers now announce a failed submit or a rejected upload without the user needing to already be focused on that element
- [x] Table header `scope="col"` added (`admin/leads/page.tsx`'s existing table, and the new transcript table) — WCAG 1.3.1
- [x] Heading-hierarchy fix on `/catalogue` — product cards were `<h3>` directly under the page's `<h1>`, skipping `<h2>` entirely
- [x] Admin sidebar's "coming soon" nav items read at 3.55:1 against the brand gradient's lighter end (opacity-based dimming) — raised to a verified 4.5:1+, with italics added as a non-opacity-only way to keep them visually distinct from real links
- [x] REQ-LMS-06/07 (transcript, captions) — real accessibility features in their own right, credited under Phase 4 above since that's where their requirement IDs live, but built in this pass

### Outstanding

- [ ] Push notifications ("where supported", 01 §5.9) — deliberately not built. No VAPID key infrastructure exists, and more importantly no one has decided what a push notification would even say (lesson reminder? certificate issued? payment approved?) — building the wiring without that decision would be the same mistake as inventing UI copy nobody wrote. Same class of gap as Phase 3's Payfast/Netcash sandbox credentials: a real external/product decision, not an engineering shortcut
- [ ] No automated accessibility test (axe-core or similar) wired into CI yet — this pass's audit was a real, computed, one-time pass, not a regression gate. A future change to `globals.css` could reintroduce a contrast failure silently
- [ ] No browser automation available this session to visually verify screen-reader behaviour or keyboard navigation end to end — the fixes are structurally correct (verified via computed contrast ratios, HTML output inspection, and WCAG success-criterion citations) but were not confirmed with an actual screen reader

**Demo target:** installable app; WCAG 2.1 AA audit passed. **Met**, with the push-notification caveat above — verified live against the running dev server: the manifest resolves the real tenant's theme (confirmed the exact JSON payload), the service worker and offline page both serve correctly, and `<link rel="manifest">`/`theme-color` are present in the actual rendered HTML, not just the source. The accessibility side was verified by computation (contrast ratios) and inspection (HTML/ARIA output), not by a live assistive-technology session — see Outstanding.

---

## 9. Phase 5 — Corporate, workshops, marketing (100%, complete)

Organisations and seat-pool purchasing, manager visibility, workshops/facilitators/booking, CRM and marketing engine.

### Done — sprint 1: organisations, seat-pool entitlements, PO checkout

- [x] `organisations`, `organisation_members` (`0016`, 02 §4.5) — FK constraints added via `op.create_foreign_key()` to the `entitlements.organisation_id`/`role_assignments.organisation_id` columns that already existed, bare and unconstrained, since `0001`/`0009`: the data model documented this design years before `organisations` itself existed to point at. `organisation_members.relationship` (`member`/`manager`/`admin`) is a distinct concept from RBAC `role_assignments` — org standing, not platform permissions
- [x] Seat pool model: a null-`user_id` entitlement is the purchased pool, a set-`user_id` entitlement drawn from it is one assigned seat, "available seats" is `sum(pool.quantity) − count(active assigned)` computed on read, never a separately tracked counter that could drift
- [x] Self-service organisation creation (REQ-TEN-02) — any authenticated user can start one and becomes its first admin; no separate signup flow exists yet, so the realistic actor already has an account from an earlier individual purchase
- [x] PO checkout (`POST /orders/{id}/checkout/po`, 0016's own worked example from 01 §4.3 workflow 5): PO number and document captured together in one multipart call, unlike EFT — a purchase order document exists from the moment it's raised, so there's no "reference now, proof later" split. `_fulfil_order()` extracted as a shared helper in `services/orders.py`, used by both `approve_eft` and the new `approve_po`; branches on `order.organisation_id` to grant a pool entitlement instead of a direct user entitlement+enrolment
- [x] Bulk seat assignment: `POST /organisations/{id}/seats/invite` (typed emails) and `POST /organisations/{id}/seats/import` (CSV upload) both find-or-create the employee's account and grant a real entitlement+enrolment, refusing cleanly once the pool is exhausted rather than over-allocating
- [x] Seat revocation (`POST /organisations/{id}/seats/{entitlement_id}/revoke`) frees capacity for reassignment without retroactively removing the enrolment already granted — REQ-TEN-02 asks for reassignment, not a course-access-revocation flow
- [x] `GET /organisations/{id}/seats/{course_id}/assignments` — the per-seat holder list the revoke UI needs, added alongside the aggregate `/seats` summary once the frontend build surfaced that gap; admin-gated like invite/import/revoke since it carries real emails, unlike the membership roster which any member can read
- [x] Real `apps/web` UI: `/organisations` (list/create), `/organisations/[id]` (members, seat summary, invite, CSV import, per-course seat-holder list with revoke), `/organisations/[id]/buy-seats` (PO checkout flow); `/admin/payments` extended to show PO vs EFT and the PO number
- [x] Migration round-trip bug found and fixed: `downgrade()` dropped `organisations` without first nulling `entitlements.organisation_id`/`role_assignments.organisation_id`, so a downgrade after real seat-purchase test data existed left orphaned FK values that broke the next `upgrade head`. Fixed by nulling both columns before dropping the constraints; round-trip (`downgrade -1` → `upgrade head` → `alembic check`) now verified clean

### Done — sprint 2: manager visibility (REQ-TEN-03, 04 §2.3's P2 policy)

- [x] `team:reports:view_individual` permission (`0017`), granted to `admin`/`super_admin` — the platform-staff override half of REQ-TEN-03's "explicit permission" condition. An organisation's own manager satisfies that same condition through `organisation_members.relationship` (`manager`/`admin`) instead: RBAC roles here are tenant-wide, not per-organisation, so granting the permission through `role_assignments` would let a manager in one organisation see another's individual results — exactly what the ABAC scoping condition exists to prevent
- [x] `services/reports.py::get_progress_report` — aggregate stats (enrolled, completed, completion rate) always returned; individual rows (email, status, completion date, best quiz score) only when **all three** conditions hold: `courses.manager_visibility = individual_enabled`, `tenants.settings.allow_manager_individual_results = true`, and the viewer is a real per-organisation manager/admin or platform permission holder. Response shape is determined by policy, not query parameters (03 §9) — a failing condition means the row is absent, never present-and-redacted
- [x] `GET /organisations/{id}/reports/progress`, `PATCH /courses/{id}/manager-visibility` (course:edit-gated, a narrow single-field endpoint — no general course-authoring surface added), `GET/PATCH /tenant/settings/manager-visibility` (tenant:manage-gated, merges into the existing `settings` jsonb rather than overwriting it), `GET /courses` (course:view-gated, the read-side counterpart the admin toggle UI needs)
- [x] Real `apps/web` UI: `/admin/settings` (tenant-wide toggle, per-course visibility dropdown), a "Report" panel on `/organisations/[id]` showing aggregate stats always and individual rows only when the API says they're visible, with an explicit "an admin has not enabled manager visibility for this course" message when they aren't
- [x] Migration round-trip verified immediately this time (`downgrade -1` → `upgrade head` → `alembic check`), applying the lesson from sprint 1's bug before it could repeat

**Demo target (sprint 2):** a manager who cannot see individual scores until an admin enables it for one course. **Met** — verified live over real HTTP against running servers: the report showed `individual_visible: false` and an empty `learners` array before either toggle was flipped; after a platform admin flipped both the course-level and tenant-level toggles through the real `apps/web` UI's backing endpoints, the same report for the same organisation returned the real invited employee's email and status. A plain org member (not manager/admin) was confirmed to still see aggregate-only even with both toggles on, and a non-member was refused the report entirely (403).

### Done — sprint 3: workshops, facilitators, booking (02 §9, REQ-WS-01 through REQ-WS-09)

- [x] `facilitators`, `facilitator_availability`, `workshops`, `workshop_sessions`, `bookings`, `meeting_links`, `attendance_records` (`0018`) — the exact table set 02 §9 already named; a new `facilitator` RBAC role plus `workshop:manage`/`workshop:facilitate` permissions, since "corporate roles arrive with the corporate phase" was the seed migration's own stated plan back in `0002`
- [x] Weekly facilitator availability (`day_of_week`/`start_time`/`end_time`) with real enforcement — `services/workshops.py::create_session` refuses a session outside every one of the facilitator's stated windows, and separately refuses a session that overlaps one the same facilitator already has (double-booking), each with a specific, distinguishable error message
- [x] Capacity enforcement with a real waitlist (REQ-WS-03): booking past capacity is `waitlisted`, not refused outright; cancelling a `registered` booking promotes the earliest `waitlisted` one automatically — verified by booking two learners against a capacity-1 session, cancelling the first, and confirming the second is now `registered` holding the exact booking row that was waitlisted, not a new one
- [x] Facilitator-overridable attendance (REQ-WS-08): `attendance_records.source` distinguishes `provider_report` from `facilitator_manual` — a facilitator's manual call always wins, recorded with who made it and when
- [x] Pluggable meeting-provider contract (REQ-WS-06, `src/services/meeting/`): `manual` (the always-available fallback — a real, working provider this sprint, `join_url` starts `null` for the facilitator to fill in by hand) and `teams` (structured correctly against a real `MeetingProvider` interface, but genuinely blocked on `GRAPH_CLIENT_ID`/`GRAPH_CLIENT_SECRET`/`GRAPH_TENANT_ID` — no Azure AD app registration exists yet, the same class of external-credential gap as Phase 3's Payfast/Netcash, refused cleanly rather than faked)
- [x] `GET/POST /facilitators`, `GET/POST /facilitators/{id}/availability`, `GET/POST /workshops`, `GET/POST /workshops/{id}/sessions`, `POST /sessions/{id}/book`, `POST /bookings/{id}/cancel`, `POST /sessions/{id}/attendance`, `GET /sessions/{id}/roster` — creation/management is `workshop:manage`-gated, booking is self-service like course enrolment (any authenticated user, gated on capacity not permission), attendance/roster are gated on being that session's own facilitator or holding `workshop:manage`, the same ownership-or-override pattern `routers/orders.py` already established for finance
- [x] Real `apps/web` UI: `/admin/workshops` — facilitator registration and availability management, workshop/session creation for `workshop:manage` holders, a "Book" button any authenticated user can use, and a roster/attendance panel that 403s the same way the API does for a non-facilitator viewer
- [x] Migration round-trip verified immediately after writing `0018`, before building anything on top of it — the sprint-1 lesson now applied twice running
- [x] Deliberately deferred, both documented in `0018`'s own migration docstring rather than left as silent gaps: REQ-WS-04 (credit-based booking — `entitlements.kind` already anticipates `workshop_credit`/`coaching_credit`, but consuming a credit needs quantity-decrement semantics `entitlements` doesn't have yet; sessions are open-enrolment this sprint) and REQ-WS-09 (post-workshop survey — reuses the existing `surveys` engine rather than a new `workshop_feedback` table; wiring a session to a survey is a smaller follow-up, not a new subsystem)

### Done — sprint 4: CRM and marketing engine (02 §10, REQ-CRM-01 through REQ-CRM-05)

- [x] Exactly the ten tables 02 §10 already named (`0019`): `deals`, `tasks`, `notes`, `activities`, `segments`, `email_templates`, `campaigns`, `email_sends`, `email_events`, `suppressions` — `leads`/`contacts`/`consent_records` already existed from Phase 2, reused rather than duplicated. `tasks`/`notes` always reference a `deal_id` (required) — a pipeline-tracking CRM, not a freeform contact-notes app
- [x] `activities` is append-only (same two-layer enforcement as `consent_records`: revoked grant + a raising trigger reusing `refuse_mutation()`) — every deal creation, stage change, task creation/completion and note addition writes a real row, giving each deal a complete, tamper-evident history rather than a derived view computed after the fact
- [x] Segments match only non-PII `leads` attributes (pipeline stage, the UTM quintet) — 02 §10/04 §4.4's own resolution of the encrypted-email-vs-bulk-marketing conflict: a segment is computed at send time, never a stored address list
- [x] Campaign sends check two independent gates before ever reaching a contact: current marketing consent (`consent_records`, Phase 2) and the suppression list (`suppressions`, keyed on `email_blind_index` — 02 §10's own wording, never plaintext). A contact without consent is silently excluded (counted, never listed) from the send result; a suppressed contact still produces an `email_sends` row so the campaign's own report can show it was correctly withheld
- [x] No separate ESP provider abstraction, unlike `0018`'s meeting providers — `services/email.py`'s real SMTP path (Mailpit locally, any real relay in production) already sends both transactional and bulk mail end to end, so there is no second, blocked-on-credentials implementation to build an interface around. REQ-CRM-03's "SPF/DKIM/DMARC on a dedicated sending domain" is a DNS/domain-ownership decision, not a code capability gap
- [x] A real one-click unsubscribe link (`{PUBLIC_WEB_URL}/unsubscribe/{email_send_id}`) is embedded in every sent email — following it writes a real suppression row *and* a real `granted=false` marketing-consent row (reusing `services/consent.py::record`, not a parallel implementation) *and* an append-only `email_events` row, and a second campaign to that contact genuinely excludes them (via the consent gate, which fires before the suppression check) rather than just logging that someone clicked
- [x] `POST /email-events/bounce` — structured the way a real ESP's signed webhook would call it, `campaign:manage`-gated for now since no live ESP integration exists to authenticate a genuinely public caller (same documented scope boundary as `services/meeting/teams.py` not making real Graph calls)
- [x] A real bug found and fixed during the live smoke test, not left for later: `{{first_name}}` substitution was only applied to the email body, never the subject line — a real Mailpit-delivered message showed the literal placeholder in its subject. Fixed in `services/campaigns.py::send_campaign`, re-verified against a fresh real send
- [x] A real test-determinism bug found and fixed before it could cause flaky CI: the demo tenant's `leads` table is a persistent dev database shared across every test run, not reset between them, so a segment scoped only by pipeline stage would also match leads a *previous* run of the same test file left behind, breaking exact-count assertions on the second of the two required determinism passes. Fixed by tagging every test-created lead with a unique `utm_campaign` marker and always including it in that test's own segment criteria — verified by intentionally running the full suite twice in a row with real leftover data present the second time
- [x] Real `apps/web` UI: `/admin/deals` (pipeline list, deal creation, an expandable panel with stage/tasks/notes/activity trail), `/admin/campaigns` (segment/template/campaign creation, send, live sent/suppressed/bounced stats), `/unsubscribe/[id]` (the public landing page the email link resolves to — one-click, no confirmation step, per RFC 8058's own convention)
- [x] Migration round-trip verified immediately after writing `0019`, same discipline as every migration since sprint 1's bug

**Demo target (Phase 5, overall):** a manager who cannot see individual scores until an admin enables it for one course — met in sprint 2 (§9 above). Phase 5 itself is now complete: organisations/seats, manager visibility, workshops/booking, and CRM/marketing all built and verified.

---

## 9a. Phases 6–7 (0%)

| Phase | Demo target |
|---|---|
| 6 AI insights | 500 survey responses summarised with zero identifiers transmitted, shown beside the redaction log |
| 7 Hardening and cloud | Load test at 100 concurrent; restore drill completed; POPIA matrix delivered |

---

## 10. Independent security scan (OWASP ZAP + Trivy)

Run mid-Phase-5 at the user's request — a second, independent pass alongside the existing `pip-audit`/`npm audit` CI gates, using tools neither of those overlaps with (dynamic scanning, container-image scanning, filesystem secret scanning).

| Scan | Target | Result |
|---|---|---|
| ZAP baseline | `apps/web` (dev server) | 0 FAIL, 10 WARN |
| ZAP baseline | `apps/web` (production build, post-fix) | 0 FAIL, 4 WARN |
| ZAP baseline | `apps/api` | 0 FAIL, 1 trivial WARN (cacheable 404s) |
| Trivy `fs` (vuln + secret + misconfig) | Repository source, excluding dependency trees `pip-audit`/`npm audit` already cover | Clean — 0 vulnerabilities, 0 secrets, 0 misconfigs |
| Trivy `image` | Every image in `infra/docker-compose.yml` | See below |

**Fixed:**
- `mailhog/mailhog:latest` carried 109 CRITICAL / 1250 HIGH CVEs — the upstream project has been unmaintained for years, still on an EOL Alpine 3.12 base. Swapped for `axllent/mailpit:v1.24`, its actively-maintained successor, verified end-to-end against a real captured message (its `/api/v1` shape differs from MailHog's `/api/v2` — `tests/test_workers.py` was updated to match, not assumed compatible). Briefly removed outright on a follow-up request, then reinstated on a second follow-up once local SMTP delivery was judged worth keeping after all — Mailpit stayed as the fix, not a reversion to the vulnerable image. Net effect: the CVEs are gone, the real-delivery test (`test_send_email_job_delivers_via_smtp`) is back and passing, nothing about `services/email.py`'s enqueue-only send path changed at any point.
- ZAP found `X-Content-Type-Options`/`Permissions-Policy` missing on `_next/static`/`_next/image`/`icon.png` — `proxy.ts`'s matcher deliberately skips static assets (a per-request CSP nonce is pointless on a JS chunk), so these two static, non-nonce headers moved to `next.config.ts`'s `headers()` instead of broadening the middleware matcher.
- `X-Powered-By: Next.js` — `poweredByHeader: false` added.
- ZAP's "Dangerous JS Functions" (`eval(`), "Suspicious Comments" and "Timestamp Disclosure" findings were confirmed to be **dev-server-only artifacts** (webpack's `eval()`-based HMR source maps) — verified by grepping the actual production bundle (`grep -rl "eval(" .next/static/chunks/*.js` → 0 matches) and re-scanning a real `next build && next start`, where all three disappeared.

**Reviewed and accepted, not fixed:**
- `style-src 'unsafe-inline'` in the CSP — `proxy.ts`'s own docstring already documents why (pervasive literal-only inline `style` props, never user-controlled data).
- `Cross-Origin-Embedder-Policy` missing — adding COEP without CORP-tagging every resource risks silently breaking future cross-origin embeds (a card-checkout iframe, once that ships); this app has no current feature that needs the cross-origin isolation COEP provides, so it's deferred rather than added speculatively.
- Docker image CVEs in `minio/minio:latest` (6 CRITICAL / 76 HIGH), `clamav/clamav-debian:stable` (5 CRITICAL / 23 HIGH), `postgres:16-alpine` (1 CRITICAL / 14 HIGH, almost entirely in a bundled Go entrypoint helper never exposed to network input) — not blindly version-bumped without a controlled upgrade-and-test cycle, since these are functionally load-bearing (storage, virus scanning, primary database), unlike Mailhog. Tracked as a real, open item below, not silently accepted.
- `redis:7-alpine` — clean, 0 findings.

**A process note, not a code finding:** a concurrent Claude Code session for a different, unrelated project on this same machine was also running Trivy scans at the same time, into the same generic `/c/tmp/security-scan` path this session initially (mistakenly) reused instead of its own isolated scratchpad. The collision surfaced as an unfamiliar script scanning images that don't exist in this project (`pgvector`, `nats`, `neo4j`, `ollama`) — investigated and confirmed harmless (a different session's own working files, not anything injected), then all of this session's scan output was moved to its proper isolated path and re-run cleanly.

**Housekeeping, same pass:** `apps/api/var/storage` (105 MB of leftover local video-transcode test artifacts, already gitignored), `.mypy_cache` (72 MB), `.ruff_cache`, `.coverage`, stray `__pycache__` directories, and `apps/web/tsconfig.tsbuildinfo` were removed — all regenerate on the next relevant command and were never tracked by git.

**Open:**
- [ ] `minio/minio`, `clamav/clamav-debian`, `postgres:16-alpine` — schedule a controlled version bump + full regression pass; not urgent (all three are on non-`:latest` or soon-to-be-pinned tags, reachable only from the local dev network, not the public internet). **In progress** — see "Dependency-upgrade sprint" below, which is that controlled pass
- [ ] No automated ZAP/Trivy gate wired into CI yet — this was a one-time, manually-triggered pass, not a regression gate

### Dependency-upgrade sprint (in progress)

A full audit of every major package/language/image against its actual latest, requested outside the Phase 1–5 roadmap. Scoped as a sequence of small, independently-verified passes — same discipline as every phase sprint (gate sweep, real tests, docs updated in the same pass, commit → push → CI green before the next one) — rather than one large bump.

- [x] **Sprint A — Mailpit `v1.24` → `v1.29.2`.** Fixes a real vulnerability, CVE-2026-27808 (the Link Check API could be used to probe internal network IPs). `infra/docker-compose.yml` and `.github/workflows/api.yml`'s service container both bumped. Verified: `/api/v1/messages` shape unchanged (checked directly, not assumed), `tests/test_workers.py`'s real-delivery test passes, full suite (187 tests) green. Committed `426fe7b`, CI green — [run 31421466431](https://github.com/WillemKlopper87/TTLI_LMS/actions/runs/31421466431) (quality 3m54s, web 59s)
- [x] **Sprint B — low-risk Python patch/minor batch.** SQLAlchemy 2.0.36→2.0.51, alembic 1.14→1.19, uvicorn 0.34→0.52, pydantic 2.10→2.13, pydantic-settings 2.7→2.15, argon2-cffi 23→25, structlog 24→26, asyncpg 0.30→0.31, psycopg2-binary 2.9.10→2.9.12, ruff 0.8→0.16, pytest-cov 6→7. Checked uvicorn's own breaking changes specifically (`setup_event_loop`→`get_loop_factory` rename, `reload_delay` default change) since it moved the most versions — neither applies, this project only invokes uvicorn via the CLI, never subclasses `Config`/`Server`. `redis` stays pinned here on purpose; its bump is paired with the Redis server major-version bump instead (Sprint C+F), not folded into the "low-risk" batch. The new `ruff` version itself surfaced 6 real findings the old version's rule set didn't catch — 4 unused tuple-unpacked test variables (`RUF059`) and 2 blocking `pathlib`/file-read calls inside async functions (`ASYNC240`, one in real application code — `services/media/transcoder.py`'s `output_dir.mkdir()`, now wrapped in `asyncio.to_thread` matching `services/storage/s3.py`'s existing pattern for exactly this). Fixed all 6, not suppressed. Full suite (187 tests) green twice, `mypy` (still pinned 1.14.1 pending its own Sprint D) clean, `pip-audit` clean. **A real pre-existing drift alembic 1.19 caught that 1.14 couldn't**: `alembic check` failed in CI (not locally, since I hadn't re-run it after bumping alembic itself — a real gap in this sprint's own verification, caught by CI rather than before pushing) with "Detected removed check constraint `ck_survey_responses_one_subject`". Root cause: `0013`'s migration created that constraint via raw `op.execute()`, but `SurveyResponse` never declared it in `__table_args__` — a gap that existed since `0013` shipped, invisible to the older alembic's autogenerate, which the newer version's `checkconstraint_byname` plugin now correctly detects. Fixed by declaring the `CheckConstraint` in the model (matching `ConsentRecord`'s already-correct handling of the identical "exactly one of X/Y" pattern), re-verified: `alembic check` clean, full round-trip clean, full suite green twice more. **A second real drift, same root cause (verification gap, not a code bug)**: CI then failed `api-client drift` — pydantic 2.13.4 changed how `dict[str, object]` JSONB fields (`Activity.detail`, `Segment.criteria`) render in the generated OpenAPI schema (`Record<string, never>` → an open `{[key: string]: unknown}` index signature), which this sprint's own regenerated `openapi.json` was never re-diffed against the committed `schema.gen.ts` before pushing. Fixed by regenerating both and re-verifying `apps/web`'s `typecheck`/`build` end to end (26 routes, clean). Two real findings from one dependency bump, both caught by CI rather than local verification — the lesson: a pydantic/alembic-adjacent bump needs `alembic check` *and* `api-client` regeneration run explicitly, not assumed covered by the general gate sweep. Committed `8d08ce2`/`7635b24`/`5638b8e`, CI green — [run 31423931672](https://github.com/WillemKlopper87/TTLI_LMS/actions/runs/31423931672) (quality 3m48s, web 47s)
- [ ] **Sprint C — redis-py client bump — genuinely blocked, not just risky.** `arq==0.28.0` (this project's job queue — email sending, video transcoding, monthly partition extension, auth purge) declares `redis[hiredis]<6,>=4.2.0` as a hard dependency, confirmed by actually trying to install `redis==8.1.0` locally: pip's resolver reported the conflict outright. `arq` is itself in maintenance-only mode with no newer release to lift that cap — its own maintainers point to SAQ or Streaq as successors. Bumping redis-py past 5.x means replacing arq first, which is a real migration (four job types, tested behaviour, its own risk profile), not a version-number change to fold into a dependency-bump sprint. Deferred as its own future decision, same class as the TypeScript 7.0 hold below
- [x] **Sprint F — Redis server 7→8 alone, decoupled from the client.** Safe on its own: RESP3 is opt-in via `HELLO 3`, so a RESP2 client (redis-py 5.x, staying pinned per Sprint C above) is never forced onto the new protocol — Redis 8 serves both simultaneously, the same guarantee since RESP3's introduction in Redis 6.0. Every real call site was audited first (`core/tenancy.py`'s tenant cache, `routers/auth.py`'s MFA-replay claim, `services/media/playback.py`'s session tracking, `services/rate_limit.py`) — plain GET/SET/DEL/INCR/EXPIRE/ZADD/ZRANGE/ZCARD/ZREM, `decode_responses=True` already normalizes bytes→str either way, nothing here touches a command whose shape differs between protocol versions. Also: Redis relicensed back to AGPLv3 with 8.0 GA, so the earlier SSPL/RSAL licensing concern that first justified staying on 7 no longer applies. `infra/docker-compose.yml` and `.github/workflows/api.yml`'s service container both bumped to `redis:8-alpine`. Verified live, not just reasoned about: recreated the container (`docker compose up -d`), confirmed `redis_version:8.10.0` via `redis-cli info server`, ran the full suite twice against it (187 tests, 0 skipped, both clean) — every one of the four audited call sites is exercised by the existing test suite over the real `REDIS_URL=redis://localhost:6399/0` connection, not mocked. `ruff check`/`mypy src` both clean. Committed `b066cb9`, CI green — [run 31425259891](https://github.com/WillemKlopper87/TTLI_LMS/actions/runs/31425259891) (quality 3m46s, web 52s)
- [x] **Sprint D — mypy 1.14.1 → 2.3.0.** Checked both defaults this jump was expected to flip, not assumed clean from the pin bump alone: `--local-partial-types` has no toggle left at all in 2.3.0 (mandatory now, nothing to fix around — the flag itself is gone from `--help`), and `--strict-bytes` is on by default with `--no-strict-bytes` as the new opt-out. `mypy src` reports zero new issues against this codebase either way — no PEP 688 `bytes`/`bytearray`/`memoryview` mixing anywhere it would bite, so no fixup pass was actually needed, contrary to this sprint's original estimate. Verified, not inferred: full gate sweep (`ruff check`, `ruff format --check`, `mypy src`, `pip-audit`) clean, full suite (187 tests) green twice. Committed `c806b6c`, CI green — [run 31426384033](https://github.com/WillemKlopper87/TTLI_LMS/actions/runs/31426384033) (quality 4m03s, web 50s)
- [x] **Sprint G — migrate local dev storage from `minio/minio` (community binaries discontinued Oct 2025, repo archived twice since — no further security patches will ever land) to Garage `v2.3.0`.** Two things the original scoping got wrong, both corrected by verifying hands-on rather than trusting docs/search summaries: (1) a web search claimed Garage doesn't support the S3 `CreateBucket` operation — this project's `ensure_container()` depends on exactly that call — but the *official* S3-compatibility reference, fetched directly, says `CreateBucket` is "✅ Implemented"; a live container confirmed it, including the `BucketAlreadyOwnedByYou` idempotency path `ensure_container` already handles. (2) The original plan assumed the distroless image's missing healthcheck could become "a TCP/HTTP check instead" — false: the image ships *only* the `garage` binary, confirmed by `docker exec ... sh` failing with "executable file not found in $PATH", so there is no tool inside the container to run any check with, TCP or otherwise. `infra/docker-compose.yml`'s `garage` service therefore has no `healthcheck:` block at all, same as `mailhog`, for the same documented reason. Bootstrap turned out simpler than scoped: Garage 2.3.0's `--single-node --default-bucket` server flags read `GARAGE_DEFAULT_ACCESS_KEY`/`SECRET_KEY`/`BUCKET` and auto-configure the single-node layout, an access key, and a bucket — no custom init container needed. Confirmed hands-on (not assumed from the flag's name) that the auto-created key also gets full create-bucket rights, not just owner rights on the one default bucket, by creating a second bucket the key was never explicitly granted and watching it succeed. One real constraint the migration surfaced: Garage requires access keys in a `GK<24 hex>`/`<64 hex>` format, unlike MinIO's arbitrary strings, so `apps/api/.env` and the repo's `.env.example` both needed their `S3_ACCESS_KEY`/`S3_SECRET_KEY` values regenerated to match. `infra/garage/garage.toml` added (single-node config, `s3_region = "af-south-1"` matching `.env`'s existing `S3_REGION`). Verified against the live container, exercising every operation `services/storage/s3.py` actually performs, not a subset: `ensure_container` (including its idempotent second-call path) across all four real containers (`private-content`, `user-uploads`, `generated-documents`, `public-marketing`), `upload_object`/`get_object` roundtrip, `list_objects` with a prefix, `generate_signed_url` — fetched over real HTTP, not just generated — `set_metadata`'s `CopyObject` self-copy trick, `get_public_url`, and `apply_lifecycle_policy`'s `Expiration` rule. CI is unaffected either way: `tests/test_storage.py`'s automated suite runs against moto's in-process S3 mock, not a live MinIO/Garage container, so this was always a local-dev-only swap. Full suite (187 tests) green twice, `ruff`/`mypy` clean. README.md, `docs/06_OPERATIONS.md` and `.env.example` updated in the same pass. Committed `c703319`, CI green — [run 31428593756](https://github.com/WillemKlopper87/TTLI_LMS/actions/runs/31428593756) (quality 3m28s, web 58s)
- [ ] Sprint E — PostgreSQL 16→18 (dump/restore, not in-place — the data format isn't binary-compatible across majors; the official image also moved to a versioned data-directory path in 18, so the compose volume mount needs updating too; verify `citext`/`pg_trgm`/`pgcrypto` against PG18 before committing)
- [ ] TypeScript 5.9→7.0 — deliberately **not** scoped as a sprint. 7.0's Go-rewritten compiler has no stable programmatic API until 7.1 (the thing that breaks `typescript-eslint`/`ts-morph` elsewhere); this repo has no such tooling today, but Next 16's build-time type-checking against it hasn't been spiked yet. Revisit later, don't fold into this pass

---

## 11. Known gaps in what is already written

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

## 12. Recommended next three steps

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

## 13. Schedule reality

The source material claims 9–14 months for the full ecosystem while its own gate durations sum to 52–83 weeks. Neither figure survived review.

What can honestly be said: **Phase 0 is the only thing on the critical path right now, and it is entirely in the customer's hands.** Engineering ranges for Phases 1–7 exist in [01 §8](01_PRD.md#8-delivery-plan) but they are ranges for a small team against a signed scope, and there is no signed scope yet. Publishing a date before the decision register is closed would be inventing one.

The first genuinely sellable configuration arrives at the end of Phase 4, not Phase 3.
