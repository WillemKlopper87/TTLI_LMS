# TTLI_LMS — 05_COMMERCIAL §3 Feature Matrix: coverage audit

**Scope:** Every row of the feature matrix in `docs/05_COMMERCIAL.md` §3, checked against the actual code (routers, services, models, migrations, web pages) on 2026-08-16 by a read-only sub-agent. STATUS.md was used as a guide only; every classification was confirmed in code.

**Legend:** BUILT = works end to end (backend + UI where a UI is implied) · PARTIAL = backend only / UI only / a subset · MISSING = nothing exists · DEFERRED = the matrix marks it "—" or 01_PRD §9 puts it out of scope. Size = S/M/L rough effort to close.

**Summary (54 rows): BUILT 21 · PARTIAL 17 · MISSING 10 · DEFERRED 6.** Individual Starter/Professional is essentially deliverable today; Team/Corporate mostly (missing departments, accounting export, real Teams/calendar, admin analytics); Enterprise is not yet (no SSO, no branding self-service, no custom certificates, no audit-log viewer, no AI).

Paths: `api/` = `apps/api/src/`, `web/` = `apps/web/app/`, `mig/` = `apps/api/alembic/versions/`.

## 1. Full table

| # | Feature | Ph | Status | Evidence | Gap / what it would take | Size |
|---|---|---|---|---|---|---|
| **Content and funnel** |
| 1 | Public podcasts and resources | 2 | BUILT | `api/routers/podcasts.py`, `services/podcasts.py`, `spotify.py`, `mig/0026`; `web/podcasts/*`, `web/admin/podcasts` | No separate "resources" library; content itself empty (inventory gap) | — |
| 2 | Free sample lesson | 2 | BUILT | `Lesson.access_level="public"`; `/public/courses/{id}/curriculum`, `/public/lessons/{id}/preview`; `web/courses/[courseId]`, `web/preview/[lessonId]` | — | — |
| 3 | Guest demo account | 2 | BUILT | `api/routers/guest_access.py`, `mig/0025` sweep; `web/guest-access`, `web/auth/magic-link` | REQ-LEAD-05 sample-only watermark / guest→paid carry-over not built | S |
| 4 | Mobile-responsive web | 1 | PARTIAL | Tailwind `md:` on public/learner pages; `web/admin/layout.tsx` fixed `w-56` sidebar | Admin shell has no mobile layout | S |
| 5 | PWA install | 4.5 | BUILT | `web/manifest.ts`, `register-sw.tsx`, `public/sw.js`, push (`api/routers/push.py`, `mig/0027`) | Offline shell only (by design) | — |
| **Learning** |
| 6 | Self-paced courses | 4 | BUILT | `api/models/course.py`, routers `courses/learning/media`, services `courses/enrolment/completion`; `web/learn/*`, `web/admin/courses` | — | — |
| 7 | Learning paths | 4 | MISSING | zero hits for `learning_path` | `learning_paths` + `learning_path_courses`, path entitlement/`Product.kind="path"`, progress rollup, admin builder + learner page | L |
| 8 | Quizzes and assessments | 4 | Basic BUILT / Advanced PARTIAL | `api/models/assessment.py` (randomise, pass_score, max_attempts, time_limit), `services/quiz.py` (single/multiple/true_false auto-graded; text manual); `web/.../quiz-player.tsx`, `web/admin/grading` | No Likert/NPS/ranking/matching/file-upload types, no sample-N-from-bank, no per-question feedback | M |
| 9 | Surveys | 4 | PARTIAL | `/surveys*`, `services/survey.py`; `survey-form.tsx`; authoring in `lesson-activity-panel.tsx` | No results/aggregate endpoint or UI; `minimum_group_size` never enforced (REQ-ASSESS-06) | S–M |
| 10 | Anonymous survey option | 4 | BUILT | `response_mode`, blind-indexed `respondent_reference`, `user_id IS NULL` | — | — |
| 11 | Progress tracking | 4 | BUILT | `/enrolments`, `/enrolments/{id}/progress`, `/transcript`, `next_lesson_id`; heartbeats; `web/learn/*` | — | — |
| 12 | Anti-bypass completion controls | 4 | BUILT | `services/completion.py`, `video_progress.py`, `media/playback.py`, quiz limits, ClamAV, audit | `live_attendance_required` still "not available"; rules only editable via API (the wizard closes this) | S |
| 13 | Pre/post skills evaluation | 4 | MISSING | no pairing concept | `evaluation_role` + `pair_id` on quiz (or `assessment_pairs`), delta report, UI | M |
| **Credentials** |
| 14 | Certificate of completion | 4 | BUILT | `mig/0014`, `services/credentials.py` (reportlab PDF + QR), `/certificates/{id}/pdf`, revoke; `credentials-panel.tsx`, `web/admin/templates` | — | — |
| 15 | Public verification page | 4 | BUILT | `GET /verify/{token}` (blind-indexed, visibility-gated, every lookup logged); `web/verify/[token]` | — | — |
| 16 | Digital badges | 4 | BUILT | `badge_templates`/`badges`, visibility PATCH, templates CRUD | Open Badges/Credly out of scope (PRD §9) | — |
| 17 | LinkedIn sharing | 4 | BUILT | `GET /badges/{id}/share/linkedin` (share + add-to-profile URLs) | Keyed off badge id — certificate-only courses have no share endpoint | S |
| 18 | CPD / accreditation fields | 4 | PARTIAL | `CertificateTemplate.cpd_points`, printed on PDF, editable | Only one integer; no body/reference/validity; `Certificate.expires_at` never set | S |
| 19 | Custom certificate design | 5 | MISSING | `render_certificate_pdf` fixed layout (Helvetica, one border, no logo) | Design fields on templates (logo/background key, colours, layout preset), upload, renderer, admin preview | M |
| **Workshops** |
| 20 | Live group workshops | 5 | PARTIAL | `mig/0018`, `services/workshops.py` (availability, conflicts, capacity, waitlist, attendance override); `web/admin/workshops` | Credits deferred (`entitlements.kind` anticipates `workshop_credit`, no decrement); no learner-facing workshops/booking page; attendance not wired to `live_attendance_required` | M |
| 21 | One-on-one coaching | 5 | PARTIAL | only `SESSION_TYPE_VALUES` has `one_on_one` | No coaching-credit product, no private booking flow, no add-on purchase | M |
| 22 | Microsoft Teams integration | 5 | PARTIAL (stub) | `services/meeting/teams.py` raises `MeetingProviderUnavailable`; `book_session` hard-codes `manual`; Graph settings exist | Graph `onlineMeetings` create/cancel, provider selection, join_url to learners, invite (REQ-WS-05); needs Azure app registration | M |
| 23 | Zoom / Google Meet | 5 | MISSING | enum values only | Two providers on the `MeetingProvider` protocol + OAuth + UI | M |
| 24 | Multiple facilitators | 5 | MISSING | `WorkshopSession.facilitator_id` single FK | `session_facilitators` join, per-facilitator conflict check, roster authz, multi-select | M |
| 25 | Scheduling and calendar | 5 | PARTIAL | availability windows, TZ-aware, 24h push reminder | No ICS/invite, no learner "my sessions"/calendar, no facilitator calendar UI, no reschedule (REQ-WS-03) | S–M |
| **Corporate** |
| 26 | Seat management | 5 | BUILT | `mig/0016`, `services/organisations.py`; `web/organisations/*` incl. buy-seats | — | — |
| 27 | Bulk user import | 5 | BUILT | `/organisations/{id}/seats/invite` + `/seats/import` (CSV) | Org-scoped only | — |
| 28 | Manager dashboard | 5 | BUILT | `/organisations/{id}/reports/progress` aggregate; Report panel on org page | Modest: no charts/trend | — |
| 29 | Individual manager reporting | 5 | BUILT | three-way gate in `services/reports.py`; course + tenant toggles; `web/admin/settings` | — | — |
| 30 | Departments / business units | 5 | MISSING | zero hits | `departments` (org_id, parent_id), member FK, CSV column, dept filter on report + dept-scoped visibility, UI | M |
| **Commerce** |
| 31 | Card payment (Payfast / Netcash) | 3 | PARTIAL | Payfast provider + card checkout + webhook (`mig/0024`); `web/checkout/*` | Never run against a live/sandbox account; Netcash not built | S + M |
| 32 | EFT with proof upload | 3 | BUILT | `/checkout/eft`, `/payment-proof` (scanned), finance approve/reject; `web/admin/payments` | — | — |
| 33 | Purchase order / invoice terms | 3 | BUILT | `/checkout/po`, `Organisation.payment_terms`; buy-seats page | — | — |
| 34 | Sequential auditable invoicing | 3 | PARTIAL | gapless counters (`services/invoicing.py`), invoices/items, ledger, credit notes + refunds (`mig/0023`), Idempotency-Key | No invoice PDF, no `GET /invoices`, no buyer download | S–M |
| 35 | Subscriptions | 3* | BUILT | `mig/0021`, `services/subscriptions.py`; admin + account pages | Renewals manual EFT/PO (no card auto-renew — depends on #31) | — |
| **CRM and marketing** |
| 36 | Built-in CRM | 2/5 | Basic BUILT / "✅" PARTIAL | leads/contacts/consent (`mig/0007`), deals/tasks/notes/activities (`mig/0019`); `web/admin/leads`, `deals` | No owner/assignee, org link, search/filter, lead→deal conversion, contact page, import/export | M |
| 37 | Bulk email and newsletters | 5 | Basic BUILT / "✅" PARTIAL | segments, templates, consent+suppression gates, unsubscribe, bounce (`services/campaigns.py`); `web/admin/campaigns` | `scheduled_at` unused; plain-text only; no preference centre; bounce endpoint not ESP-authenticated; no behavioural segments | M |
| 38 | External CRM integration | — | DEFERRED | matrix "—", 01 §9 | Outbound webhooks/event feed would be the cheap entry | M |
| 39 | Accounting export (CSV) | 3 | MISSING | only CSV import exists; PRD §9 keeps CSV export in scope | `GET /invoices/export`, `GET /ledger/export` streaming CSV (finance gate), button on payments page | S |
| **Analytics and AI** |
| 40 | Learner progress analytics | 4 | PARTIAL | learner-side progress/transcript; org aggregate | No admin per-course completion/quiz/at-risk endpoints; "Learners"/"Reports" nav inert | M |
| 41 | Admin dashboards | 3 | PARTIAL | function-specific screens (payments, leads, campaigns, grading, deals) | `web/admin/page.tsx` is a 21-line stub; no REQ-ADMIN-01 KPI dashboard (payment analytics dashboard being built 2026-08-16) | S–M |
| 42 | Anonymised AI insights | 6 | MISSING | only `Tenant.ai_enabled`/`ai_monthly_token_budget` columns | REQ-CRM-06..09: provider abstraction, PII redaction gateway + log, insight jobs, budgets, kill switch, review UI | L |
| 43 | AI executive summaries | 6 | MISSING | as above | builds on #42 | M |
| **Tenancy and identity** |
| 44 | Custom branding | 5 | PARTIAL | `tenant_themes` (`mig/0006`), `GET /tenant/theme`, applied in layout/login/admin/manifest | No admin endpoint/UI to change a theme; `email_footer_text` unused; no per-tenant registration fields | S–M |
| 45 | Custom subdomain | 5 | PARTIAL | `tenant_domains` + hostname→tenant resolution (`core/tenancy.py`), BFF `X-Tenant-Host` | No admin CRUD, no verification/TLS automation, no flag | M |
| 46 | SSO (SAML / OIDC / Entra ID) | 5 | MISSING | zero hits; password/magic-link/TOTP only | Per-tenant IdP config, OIDC (Entra first) via `msal`/`authlib`, JIT provisioning + role mapping, SAML later | L |
| 47 | Custom content catalogue | 5 | BUILT | `course_tenant_assignments` (`mig/0011`), tenant-scoped products/prices with sell-only-assigned guard | — | — |
| 48 | API access | — | DEFERRED | matrix "—"; no API keys | `api_keys` table (hashed, scoped), auth dep, rate limits, admin UI | M |
| **Content protection** |
| 49 | Signed streaming + watermark | 4 | BUILT | `services/media/playback.py`, `video-player.tsx` | — | — |
| 50 | Widevine / FairPlay DRM | Flag | DEFERRED | PRD §5.8 names `VIDEO_DRM_ENABLED`, but no such flag exists yet | packager + licence server; flag first | L |
| 51 | Offline downloads | — | DEFERRED | PRD 5.8 "downloads disabled" | — | L |
| **Support and assurance** |
| 52 | Audit logs | 1 | PARTIAL (basic, write-only) | `audit_events` append-only (`mig/0001`), `services/audit.py`; written from auth, enrolment, quiz, survey, assignment, webhooks | No read endpoint, UI or export; gaps: payment approve/reject/refund, cert revoke, role changes, publish, exports; `AUTHZ_DENIED`, `ROLE_ASSIGNED` constants unused | M |
| 53 | Support | — | DEFERRED (operational) | — | — | — |
| 54 | SLA | — | DEFERRED (operational) | Phase 7 not started | — | — |

## 2. Top gaps for an enterprise-LMS demo (prioritised)

1. **Admin KPI dashboard + learner/course analytics** (#41, #40) — the first screen a buyer sees is a stub with two greyed-out nav items. The payment/revenue analytics dashboard (being built) plus one aggregate operations endpoint (active learners, pending EFTs, completions, certificates, upcoming sessions, at-risk) changes perceived maturity most per unit of effort. Data already exists.
2. **Audit log viewer + coverage** (#52) — Enterprise column promises "Advanced"; nothing is viewable and finance/credential/RBAC actions aren't logged. `GET /audit-events` (filterable, paginated) + CSV + `/admin/audit`.
3. **SSO / Entra ID** (#46) — the standard enterprise procurement gate; OIDC-only with JIT provisioning covers the demo.
4. **Self-service branding + subdomain management** (#44, #45) — runtime theming works; admins can't change it without a migration. `PATCH /tenant/theme` + logo upload + settings tab; domains CRUD.
5. **Learning paths** (#7) — Professional+ ✅ and core LMS vocabulary; entirely absent.
6. **Departments / business units + dept-scoped reporting** (#30).
7. **Real meeting integration + calendar invites + learner workshops page** (#22, #25, #20).
8. **Custom certificate design** (#19).
9. **Finance completeness: invoice PDF + accounting CSV export + live Payfast verification** (#34, #39, #31) — cheap to close, undermines an otherwise rigorous commerce story.
10. **AI insights vertical slice** (#42, #43) — one provider, survey-response summary with the redaction log beside it (the Phase 6 demo target).

Also small and demo-visible: survey results/aggregate with min-group enforcement (#9); pre/post pairing (#13); wire `live_attendance_required` to `attendance_records` + workshop credits (#20); a user/role admin UI (not in the matrix, but there is no way to create staff or assign roles from the product today).
