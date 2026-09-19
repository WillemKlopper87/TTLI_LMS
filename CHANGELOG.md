# Changelog

All notable changes to TTLI LMS, in [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
format, newest first. This is the "what shipped" view; `docs/STATUS.md`
stays the detailed, dated build log with the *why* behind each pass —
read that for the narrative, this file for the summary.

Everything before `[0.1.0]` shipped without a version marker (`docs/BACKLOG.md`
O5) — `docs/STATUS.md` has that history in full; it is not reconstructed
here, since guessing precise per-commit boundaries after the fact would
carry false confidence a real changelog shouldn't have.

## [Unreleased]

Everything since `0.1.0`, newest themes first. Dependency bumps and CI
image-scan bookkeeping are omitted — `git log` has them.

### Added

- **Facilitator licensing and xAPI**, **partner portal**, **analyst
  workspace**, **programmes** (typed learning-path steps, cohorts and runs)
  and the **assessment platform** (templates and instances), each with its
  own admin UI.
- **POPIA data-subject rights**: access/export, anonymising erasure, legal
  hold and consent withdrawal.
- **Observability**: Prometheus metrics, Grafana dashboard, Loki/Alloy
  structured logs and alert rules.
- **Shared gradebook** (weighted marks across quizzes and assignments).
- **Raspberry Pi 3B+ profile** for proof-of-concept/UAT (`infra/docker-compose.pi.yml`,
  `scripts/deploy-pi.sh`).
- Filterable people list with confirm-before-suspend; refund picker over the
  tenant's invoices; generated course art on catalogue cards.
- Component/unit test tier for the web app (Vitest + Testing Library);
  API-client, migration-drift and axe (desktop and mobile) gates in CI.
- Engineering how-to and external user guide (`docs/HOWTO.md`,
  `docs/USER_GUIDE.md`); T9/T10 operator runbook.

### Changed

- **Campaign send** runs in a background job; the request only flips the
  campaign to `sending` and returns.
- **Admin lists** — `GET /tenant/users` and `GET /video-assets` — take
  `limit`/`offset` and report `total`, instead of silently capping.
- **Storefront and theme reads** revalidate every 60 s, keyed per tenant,
  instead of `no-store`; storefront routes gain loading states.
- **Web formatting**: one shared date/money/number convention, enforced by a
  lint rule. Finance and invoice tables now always show two decimals.
- **Mobile and learner UX**: collapsible public header and catalogue filters,
  player navigation that stays on screen, learner nav split into learning vs
  account groups, push prompt kept out of checkout and the player.
- Gradebook and dashboard queries are batched (constant query count).
- Argon2 and SSO work moved off the event loop.
- `organisations.kind` is one enum: `standard | partner | client | licensee`.
- Production hardening now precedes Phase 6 AI work in the backlog.

### Fixed

- Payfast is restricted to ZAR, requires a passphrase, and validates the
  currency at fulfilment; the CSP now lets its form post.
- A cross-tenant bespoke-course assignment residual is closed.
- The subscription EFT confirmation no longer unmounts before it renders;
  refunds state plainly that they only record accounting.
- Request transactions close before responses are sent, removing a
  create-then-read race; analytics windows use PostgreSQL's clock.
- Lesson video plays under the CSP; a cancelled transcode fails loudly
  instead of hanging; a dead network no longer freezes forms.
- The test database is reset at the start of every pytest run.

### Security

- A penetration test's 18 findings were fixed, including: production
  start-up refuses weak keys, localhost services and dev credentials; the
  database role is verified unable to bypass row-level security; push
  endpoints are checked against private addresses (SSRF); role revocation
  and guest expiry take effect on live tokens; uploads are size-bounded,
  scanned and served with `nosniff`; OpenAPI docs are off in production.
- ClamAV and other image CVEs are cleared or narrowly excepted with expiry.

## [0.1.0] - 2026-08-23

First tagged snapshot. Phases 1, 4, 4.5 and 5 complete; Phases 2–3
substantially built; Phase 0 (customer decision sign-off) still open;
Phases 6–7 not started. Full current state: `docs/STATUS.md` §1's table,
`docs/BACKLOG.md`.

### Added

- Multi-tenant platform: FastAPI + SQLAlchemy 2.0 async API, Next.js 16
  App Router web app (BFF proxy), Postgres row-level security tenancy
  (double-asserted: host + JWT `tid`).
- Identity: self-issued JWT, Argon2id, magic links, TOTP MFA, per-tenant
  OIDC single sign-on (Entra ID class), logout token denylisting.
- Core LMS: course/module/lesson authoring, self-hosted HLS video with
  heartbeat anti-bypass, WebVTT captions, quizzes/surveys/assignments
  with auto-grading, PDF+QR certificates with public verification,
  transcripts.
- Commerce: SA VAT tax engine, EFT/purchase-order/Payfast card checkout,
  sequential tax invoicing, append-only ledger, refunds and credit
  notes, `Idempotency-Key` reservations, multi-tier subscriptions,
  free-preview lessons.
- Corporate: organisations, seat pools, PO checkout, manager visibility,
  workshops/facilitators/sessions/waitlists, pluggable meeting provider.
- CRM and marketing: leads/deals/tasks/notes, segments/templates/
  campaigns/unsubscribe.
- Public site: storefront, podcast platform, resources hub (articles +
  curated recommendations), guest access with expiry sweep, PWA
  (manifest/service worker/offline shell), Web Push.
- Tenant self-service: branding (logo, colours, WCAG-checked), custom
  domains, staff administration (invite/role/suspend, with
  no-privilege-escalation and no-self-change invariants).
- Admin operations: dashboard + per-course analytics, revenue trend
  series, audit log read path with export, two switchable visual skins
  (classic and "1a — The Institute").
- Quality gates: ESLint (core-web-vitals), Playwright + axe-core WCAG
  2.1 A/AA on every public page, `ruff`/`mypy`/`pytest`, `alembic check`
  + round-trip, generated-API-client drift gate, `pip-audit`/`npm audit`,
  Trivy image scan, gitleaks secret scan.
- Containerisation: both apps' Dockerfiles, a production-shaped Compose
  topology, CI image build.

### Security

- Fixed: an MFA-pending JWT was accepted as a full access token.
- Fixed: the idempotency middleware raced two concurrent replays into
  duplicate side effects instead of blocking the second.
- Fixed: `get_session` committed partial state on every `AppError`,
  globally, not just for the login path that needed it.
- Fixed: storage object keys were built unsafely at six call sites; SVG
  logo uploads (script-carrying) are now refused.

### Known gaps

Not built: learning paths, departments/business units, AI insights
(Phase 6), full workshops (Teams integration is a stub), custom
certificate design, deeper assessment/CRM features, cloud provisioning
beyond the container images. `docs/BACKLOG.md` has the complete,
numbered list.
