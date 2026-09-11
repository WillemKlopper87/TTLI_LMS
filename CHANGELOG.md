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

## [0.9.0-uat1] - 2026-09-11

The first UAT baseline: every application gate green on a protected `main`.
Tagged at the merge of #22 so the UAT team can name the exact build it tested.

### Added

- Branch protection on `main`: pull request required; `quality`, `web`,
  `authenticated-e2e`, `secrets` and `images` must pass; branch must be up to
  date; linear history; no force-push or deletion. CI is now a pre-merge gate,
  not a post-push alarm.
- `docs/BACKLOG_2026-09-11.md`, the ordered remediation queue from the
  2026-09-11 code review, and its 22 verified findings (F1–F22) in `BACKLOG.md`.

### Changed

- `docs/NEXT_AGENT_BRIEF.md` is now a short current-state document; the
  2026-09-08 narrative version is archived with its rationale intact.

### Fixed

- Scope CVE-2026-74860 (libxml2 Python-binding use-after-free) to the ClamAV
  image only, expiring 2026-12-11: the pinned digest ships no python3, so the
  vulnerable binding layer is absent. Every other image keeps it blocking.
- Close request transactions before sending responses, eliminating the
  create-then-read race that made authenticated CI intermittently lose newly
  created products and lesson blocks.
- Anchor rolling analytics windows to PostgreSQL's clock, preventing small
  host/container clock skew from excluding a just-committed event.
- Pin the CI PostgreSQL services and blocking Trivy scan to the exact
  single-VM production digest. Document four expiring, payload-scoped
  util-linux false-positive exceptions: the image contains `libuuid`, but the
  affected util-linux mount/nsenter implementations are absent.

### Changed

- Put production hardening ahead of Phase 6 AI work in the authoritative
  backlog and current-state handoff.

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
