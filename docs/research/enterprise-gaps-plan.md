# TTLI_LMS — Enterprise gap closure plan

**Source:** `feature-matrix-coverage.md` (audit of 05_COMMERCIAL §3: 21 BUILT · 17 PARTIAL · 10 MISSING · 6 DEFERRED of 54 rows) and `enterprise-lms-ui-design.md` (the interface target). This document turns the audit's top-10 list into sequenced, buildable passes with scope, tables/endpoints, and dependencies.

**Sequencing principle:** each pass is one self-contained slice that ends green — gate sweep, live smoke, docs updated, commit, CI. Passes are ordered by *demo value per unit of effort*, with the two procurement gates (SSO, audit) pulled early because they have the longest lead time on the customer's side (Azure app registration, compliance review).

**Not in this plan (deliberate):** rows 38 (external CRM), 48 (API access), 50 (DRM), 51 (offline downloads), 53–54 (support/SLA) — deferred by design in 01_PRD §9 or operational, not code.

---

## Pass A — Operations dashboard and course analytics *(gaps #41, #40 · S–M + M)*

**Why first:** the first screen an enterprise buyer opens is `/admin`, currently a 21-line "Welcome" stub with two greyed-out nav items ("Learners", "Reports"). Every input already exists in `orders`, `enrolments`, `lesson_completions`, `certificates`, `workshop_sessions`. Highest perceived-maturity gain per hour.

**Build:**
- `GET /admin/overview` → KPI block (revenue MTD, active learners, pending EFT/PO approvals, completions this month, certificates issued, upcoming sessions, at-risk learners) + "needs attention" lists (EFT proofs awaiting approval, ungraded submissions, failed transcodes, at-risk learners).
- `GET /admin/courses/{id}/analytics` → per-course enrolment funnel, completion rate, median time-to-complete, per-lesson drop-off (from `lesson_completions` states), quiz score distribution, at-risk list.
- Frontend `/admin` rebuilt to the `.dash-top` + `.stats` + `.rowlist` idiom (design doc §5 item 14); new `/admin/reports/courses` page; retire the two inert nav items.
- Reuses the payment/revenue analytics endpoints already shipped (`/analytics/revenue-summary`, `/analytics/registrations`) rather than duplicating them.

**Depends on:** payment analytics backend (done). **Ends with:** the admin home a buyer can be shown cold.

## Pass B — Audit log viewer and coverage *(gap #52 · M)*

**Why:** "Advanced audit logs" is an Enterprise-column promise; `audit_events` is append-only and correctly grant-restricted, but there is no read path at all, and the finance/credential/RBAC actions a compliance reviewer asks about are not recorded.

**Build:**
- `GET /audit-events` — filterable (actor, action, entity_type, entity_id, date range), keyset-paginated, `audit:read` permission seeded to admin/super_admin/compliance; CSV export at `/audit-events/export.csv`.
- Coverage: add `audit.record` calls to payment approve/reject/refund (`services/orders.py`, `refunds.py`), certificate revoke, role assignment/removal, course publish/unpublish, tenant setting changes, data exports. Wire the already-defined-but-unused `AUTHZ_DENIED` and `ROLE_ASSIGNED` constants.
- `/admin/audit` page: `.tablewrap` with filters, actor/action/entity/when, expandable before/after JSON.

**Depends on:** nothing. **Note:** the events table is monthly-partitioned (`0004`) — the read path must respect the partition range.

## Pass C — Tenant self-service: branding, domains, users and roles *(gaps #44, #45 + the unlisted admin gap · S–M, M, M)*

**Why:** white-label theming *works* at runtime (two demo tenants prove it) but only a migration can change a logo or colour, and there is no way to create staff or assign a role from inside the product — an enterprise pilot cannot be handed over without it.

**Build:**
- `PATCH /tenant/theme` + logo/background upload (reuse the ClamAV-scanned upload path and `Container.PUBLIC_MARKETING`), with a live preview of `.site-head` and a `.ccard` in `/admin/settings`.
- `GET/POST/DELETE /tenant/domains` with a verification token + `tls_status` readout (no TLS automation yet — record and display state).
- **User & role admin** (not in the matrix but blocking): `GET/POST /users` (invite by email, magic-link onboarding), `GET/PUT /users/{id}/roles`, role list from `role_permissions`; `/admin/people` page. Every mutation audited (Pass B).
- Wire `email_footer_text` into `services/email.py` (currently dead).

**Depends on:** Pass B for the audit trail on role changes (or ship together).

## Pass D — SSO (Entra ID / OIDC) *(gap #46 · L)*

**Why:** the standard enterprise procurement gate; the customer's own Azure tenant is on the critical path, so start the registration early even if code lands later.

**Build:** `tenant_idp_configs` (tenant_id, protocol, issuer, client_id, client_secret_encrypted, allowed_domains, role_mapping jsonb); OIDC authorization-code + PKCE via `msal` or `authlib`; JIT user provisioning with role mapping; "Sign in with your organisation" on `/login` resolved per tenant domain; session issuance reuses the existing JWT/refresh-cookie tier unchanged. SAML deferred behind the same config table.

**Depends on:** Pass C (user/role admin, so mapped roles have somewhere to land). **External:** an Azure AD app registration from the customer.

## Pass E — Learning paths *(gap #7 · L)*

**Why:** Professional-and-above ✅ in the matrix and the first thing an LMS buyer asks for after "courses".

**Build:** `learning_paths` (tenant-visible via the same assignment join as courses) + `learning_path_courses` (ordered); `Product.kind='path'` so a path is sellable through the existing order → entitlement → enrolment bridge; path progress = rollup of member-course progress; path-level certificate on completion (reuse `certificate_templates`); admin editor reusing the wizard's Curriculum drag idiom; learner path page + dashboard integration.

**Depends on:** the course wizard (shipping now) for the editor idiom.

## Pass F — Departments and dept-scoped reporting *(gap #30 · M)*

**Build:** `departments` (org_id, parent_id, name) + `organisation_members.department_id`; department column in invite/CSV import; department filter on the progress report; manager visibility scoped per department; org chart in `/organisations/[id]`.

**Depends on:** the manager-report participation rows (in the presentation API pass, shipping now).

## Pass G — Workshops end to end *(gaps #22, #25, #20, #24 · M + S–M + M + M)*

**Why:** Teams is Starter ✅ in the matrix but `services/meeting/teams.py` raises on every path and `book_session` hard-codes the `manual` provider, so no join link ever reaches a learner.

**Build:** Graph `onlineMeetings` create/cancel with client-credentials auth; per-workshop provider selection; join_url surfaced to learners; `.ics` attached to the booking email; a learner-facing `/workshops` calendar + booking page (`.buybox` idiom); `session_facilitators` join table for multiple facilitators; wire `live_attendance_required` to `attendance_records`; workshop credits decrementing `entitlements.kind='workshop_credit'`.

**External:** Azure app registration (same as Pass D — do them together).

## Pass H — Finance completeness *(gaps #34, #39, #31 · S–M, S, S)*

**Build:** invoice PDF (reportlab, same discipline as the certificate renderer) + `GET /invoices` + buyer download; `GET /invoices/export.csv` and `/ledger/export.csv` (streaming, finance-gated) with a button on `/admin/payments`; verify the Payfast integration against a real sandbox account once credentials exist (01 §1.4). Netcash only if the customer confirms they need it.

## Pass I — Custom certificate design *(gap #19 · M)*

**Build:** design fields on `certificate_templates` (logo/background object key, accent colour, layout preset, signature image); `render_certificate_pdf` reads them instead of the fixed Helvetica layout; upload endpoints; live preview in `/admin/templates` and in wizard step 5.

## Pass J — Assessment depth *(gaps #8, #13, #9 · M, M, S–M)*

**Build:** additional question types (Likert, NPS, ranking, matching, file upload) with their grading rules; sample-N-from-bank on attempt creation; per-question feedback; pre/post pairing (`evaluation_role` + `pair_id`) with a per-enrolment and per-cohort delta report; survey results/aggregate endpoint enforcing the existing-but-unused `minimum_group_size`.

## Pass K — AI insights vertical slice *(gaps #42, #43 · L)*

**Why last:** largest gap, and the Phase 6 demo target is narrow — 500 survey responses summarised with zero identifiers transmitted, shown beside the redaction log.

**Build:** provider abstraction (one provider first, the four-provider fan-out later), a PII redaction/tokenisation gateway with a persisted redaction log, arq insight jobs, per-tenant token budgets against the existing `ai_monthly_token_budget`, a kill switch, and a human-review queue. Ships inert (`ai_enabled` off) until the customer signs the data-processing decision in 01 §1.4.

---

## Suggested order

| Order | Pass | Rough size | Unblocks |
|---|---|---|---|
| 1 | A — Ops dashboard + course analytics | S–M + M | the cold demo |
| 2 | B — Audit viewer + coverage | M | compliance review, C |
| 3 | C — Branding, domains, users & roles | S–M + M + M | pilot handover, D |
| 4 | G — Workshops end to end | M (+ Azure) | Phase 5 completeness |
| 5 | H — Finance completeness | S–M | finance sign-off |
| 6 | D — SSO (Entra/OIDC) | L (+ Azure) | enterprise procurement |
| 7 | E — Learning paths | L | Professional tier |
| 8 | F — Departments | M | Corporate tier |
| 9 | I — Custom certificates | M | Enterprise tier |
| 10 | J — Assessment depth | M | "Advanced" claim |
| 11 | K — AI insights slice | L | Phase 6 demo |

Passes D and G share the Azure app registration — request it at the start of pass 1 so it is not on the critical path when they come up. Passes A–C together move the product from "strong learner experience with an unfinished console" to "an operator can run and hand over a tenant", which is the gap a buyer actually feels.
