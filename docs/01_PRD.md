# 01 — Product Requirements

**Status:** Phase 0, awaiting customer sign-off. No code exists.
**Scope reference:** [02_DATA_MODEL.md](02_DATA_MODEL.md) (schema) · [03_API_SPEC.md](03_API_SPEC.md) (endpoints) · [04_SECURITY_AND_COMPLIANCE.md](04_SECURITY_AND_COMPLIANCE.md) (authz, privacy, VAT) · [05_COMMERCIAL.md](05_COMMERCIAL.md) (packaging) · [06_OPERATIONS.md](06_OPERATIONS.md) (infra, runbook)

---

## 0. How this document relates to the blueprint

`docs/source/` holds ~185,000 characters of AI-generated planning material produced before this plan existed. **It is a reference blueprint, not the plan.** It was written without knowledge of the existing internal systems, it contradicts itself on several expensive decisions, and one of its recommendations (Azure Media Services) names a product retired in mid-2024.

This document is the authority. Section 5 records every departure from the blueprint with a rationale and an explicit *Not chosen*. Section 1.4 lists what the blueprint left undecided. [docs/source/README.md](source/README.md) maps all nine internal contradictions to the section that settles each one.

Where the blueprint is right, it is adopted without ceremony — its anti-bypass control table, its lean-infrastructure discipline, its warning against scattering permission checks, and its advice not to build an email sending engine are all carried forward intact.

---

## 1. Product definition

### 1.1 Problem statement

A South African executive-education company sells leadership and management training — the customer's own framing is *"think Gartner, and other business schools"*. Today it has content (existing video, marketing collateral, podcasts) and no platform. There is no LMS, no storefront, no CRM, and no accounting integration. Corporate buyers expect to pay by invoice, EFT or purchase order; individual buyers expect to pay by card. Completion has to mean something, because certificates are the product's proof of value — a learner who clicks *Next* eleven times has bought nothing worth certifying.

### 1.2 Product goal

A multi-tenant platform that sells executive training, delivers it under enforced completion rules, certifies it verifiably, and gives the company the CRM and billing spine it currently lacks — launched on infrastructure lean enough that hosting cost does not consume early revenue.

### 1.3 Success metrics (pilot)

| Metric | Target |
|---|---|
| Learners supported at launch | 50–500 registered, ~100 concurrent |
| Purchase paths working end to end | 3 (card, EFT with proof, PO/invoice) |
| Invoice audit trail | Sequential, gapless, exportable for SARS |
| Completion integrity | Zero client-side completion decisions |
| API p95 latency | < 500 ms on common endpoints |
| Certificate verification | Public URL resolves for every issued certificate |

### 1.4 Open decisions (blocking Phase 0 sign-off)

Engineering does not start until these are closed. Each is unanswered in the source material.

| # | Decision | Why it blocks | Owner |
|---|---|---|---|
| 1 | **SCORM/xAPI required?** | Changes the content model at its root. Asked by the blueprint, skipped in the reply. | Customer |
| 2 | **VAT on international digital services** | The tax engine cannot be built on a guess. The blueprint itself defers to the accountants. | Customer's accountants |
| 3 | **Is signed HLS + watermarking accepted as "industry standard" for launch?** | If not, a DRM provider joins the critical path and the cost model changes. See §5.8. | Customer |
| 4 | **AI provider and DPA** — may prompt data leave South Africa after redaction? | Determines whether AI insights ship at all under the residency requirement. | Customer + legal |
| 5 | ~~Subscriptions in or out?~~ **Resolved: in.** Multi-tier, course-bundle plans built, funded through the existing EFT/PO checkout (no automatic card charging — no Payfast/Netcash integration exists). See [05 §5](05_COMMERCIAL.md#5-commercial-terms) and REQ-PAY-12. | — | Customer |
| 6 | **Guest access expiry: 7 or 14 days?** | Both offered in the source, neither chosen. | Customer |
| 7 | **CPD/accreditation body** | Determines mandatory certificate fields and whether points are tracked. | Customer |
| 8 | **Brand and design system** | Recorded as TBA. Blocks all UI work. | Customer |
| 9 | **Budget and launch date** | Recorded as TBA. Determines phase sequencing and team size. | Customer |
| 10 | **Azure Container Apps availability in South Africa North** | Verify, do not assume. App Service for Containers is the documented fallback. See [06_OPERATIONS.md §4](06_OPERATIONS.md#4-infrastructure). | Engineering |

---

## 2. Users and roles

### 2.1 Personas

| Persona | Needs |
|---|---|
| **Visitor** | Browse courses, listen to podcasts, download a brochure — without an account |
| **Guest** | A time-limited sample of the real product, to decide whether to buy |
| **Individual learner** | Buy a course, complete it, get a certificate worth putting on LinkedIn |
| **Corporate learner** | Complete assigned training without their individual scores being visible to their manager |
| **Team manager** | See whether the team is progressing — in aggregate |
| **Organisation admin** | Buy seats on a PO, invite staff, assign courses, get completion reports |
| **Facilitator** | Run live workshops, mark attendance, review assignments |
| **Content author** | Build courses, set completion rules, publish |
| **Finance** | Approve EFT proofs, issue invoices and credit notes, export for SARS |
| **Administrator** | Everything above, plus tenant configuration and privacy toggles |

### 2.2 Permission model

RBAC for coarse capability, ABAC for contextual access. Permissions are **strings from day one** (`course:publish`, `certificate:revoke`, `refund:process`), so adding a role is data, not code.

The blueprint proposes 15 roles. That is unbuildable as a first cut, and most of them are indistinguishable until corporate features exist. Roles are introduced with the phase that needs them:

| Phase | Roles added |
|---|---|
| 1 | Guest, Learner, Content Author, Finance, Admin, Super Admin |
| 5 | Corporate Learner, Team Manager, Organisation Admin, Facilitator |
| 6+ | Analyst, Auditor, Support, Marketing |

Full role catalogue, permission strings and the ABAC policies are in [04_SECURITY_AND_COMPLIANCE.md §2](04_SECURITY_AND_COMPLIANCE.md#2-authorization).

---

## 3. Functional requirements

Requirement IDs are referenced from the data model, API spec and STATUS. Traceability against the customer's four messages is at §3.12.

### 3.1 Storefront and content funnel

| ID | Requirement |
|---|---|
| REQ-STORE-01 | Public catalogue with facets: topic, format, level, duration, price, certificate included, live workshop included |
| REQ-STORE-02 | Course detail pages carrying learning outcomes, curriculum, certificate preview, and a corporate "request invoice" path |
| REQ-STORE-03 | Resource hub with topic / format / audience / funnel-stage filters |
| REQ-STORE-04 | Podcast episodes with player, transcript, show notes and a related-course call to action |
| REQ-STORE-05 | Three content access tiers: ungated, gated (contact details required), and guest-account-only |
| REQ-STORE-06 | Server-rendered marketing and course pages — SEO is a functional requirement, not a nicety |
| REQ-STORE-07 | Cookie and marketing consent captured before any non-essential tracking |

### 3.2 Lead capture and guest access

| ID | Requirement |
|---|---|
| REQ-LEAD-01 | Minimum signup fields: first name, last name, business email, privacy consent, marketing consent |
| REQ-LEAD-02 | Progressive profiling for company, job title, industry, team size, training goal, budget, timeline |
| REQ-LEAD-03 | UTM source, medium, campaign, content and term captured and attributed to the lead |
| REQ-LEAD-04 | **Guest accounts are unique per lead** — no shared `demo/demo123` credentials |
| REQ-LEAD-05 | Guest access is time-limited, role-limited, sample-only, watermarked, and issues no real certificate |
| REQ-LEAD-06 | Magic-link delivery; passwords are never emailed |
| REQ-LEAD-07 | Guest → paid conversion preserves the same email and carries guest progress into the paid enrolment |
| REQ-LEAD-08 | Signup rate limiting; optional disposable-domain blocking |

### 3.3 Commerce, payments and tax

| ID | Requirement |
|---|---|
| REQ-PAY-01 | Payfast hosted checkout with validated IPN and sandbox support |
| REQ-PAY-02 | Netcash hosted checkout with reference-based async reconciliation |
| REQ-PAY-03 | Direct EFT: display bank details, generate a unique payment reference, accept a proof-of-payment upload, notify finance, require explicit approval before enrolment activates |
| REQ-PAY-04 | Purchase order: capture PO number, accept a PO document upload, generate a pro-forma invoice, gate access on finance approval |
| REQ-PAY-05 | Payment states: pending, paid, failed, cancelled, refunded, EFT pending approval, EFT rejected, manually approved |
| REQ-PAY-06 | **Card details are never stored.** Gateway tokens only |
| REQ-PAY-07 | Webhook signature validation and idempotent processing on every gateway callback |
| REQ-PAY-08 | ZAR for South African buyers, USD for international; VAT rules configurable per jurisdiction |
| REQ-PAY-09 | **Sequential, gapless invoice numbering.** Invoices are never deleted — only voided by credit note |
| REQ-PAY-10 | Append-only financial ledger; physical deletion of ledger rows is impossible by construction |
| REQ-PAY-11 | Exportable tax report with tax code and reason code per line |
| REQ-PAY-12 | Subscriptions behind a feature flag (`settings.subscriptions_enabled`, default on) — §1.4 #5 resolved in; multi-tier, course-bundle plans, EFT/PO-funded renewals |

### 3.4 Learning delivery

| ID | Requirement |
|---|---|
| REQ-LMS-01 | Hierarchy: Course → Module → Lesson → activity (video, document, quiz, survey, assignment, workshop requirement) |
| REQ-LMS-02 | Learning paths, bundles, prerequisites, drip release, cohort and self-paced modes |
| REQ-LMS-03 | Resume-where-you-left-off, progress indicators, completion states |
| REQ-LMS-04 | Adaptive-bitrate video with a switchable ladder — see §5.8 |
| REQ-LMS-05 | Per-lesson and per-course **completion rule engine**, configurable: minimum time, video watch percentage, quiz pass score, survey required, assignment approval, live attendance |
| REQ-LMS-06 | Printable transcript |
| REQ-LMS-07 | WCAG 2.1 AA, keyboard navigation, captions |

### 3.5 Anti-bypass controls

The governing rule, stated well by the blueprint and adopted verbatim: **the frontend may display progress, but the backend is the source of truth.**

| ID | Requirement |
|---|---|
| REQ-BYPASS-01 | All completion decisions are made server-side; no client assertion of completion is trusted |
| REQ-BYPASS-02 | Server-side timestamps only; client-supplied timestamps are ignored |
| REQ-BYPASS-03 | Video heartbeat events validate real playback; progress rate is bounded so 0% → 100% jumps are rejected |
| REQ-BYPASS-04 | Seeking beyond the highest legitimately-reached position is refused |
| REQ-BYPASS-05 | Quiz question and answer randomisation from a question bank |
| REQ-BYPASS-06 | Attempt limits and time limits per assessment |
| REQ-BYPASS-07 | Required surveys block completion; duplicate submissions rejected |
| REQ-BYPASS-08 | Assignment uploads are type-validated and virus-scanned; facilitator approval where configured |
| REQ-BYPASS-09 | Concurrent session limits to deter account sharing |
| REQ-BYPASS-10 | Prerequisite enforcement in the backend, not the navigation UI |
| REQ-BYPASS-11 | Every progression decision is audit-logged, including refusals |

The blueprint's own caveat is retained and should be repeated to the customer: no system stops a determined attacker. The goal is *difficult, detectable and auditable* — and controls aggressive enough to frustrate a paying executive are a commercial risk in their own right.

### 3.6 Assessment and surveys

| ID | Requirement |
|---|---|
| REQ-ASSESS-01 | Question types: single/multiple choice, true-false, Likert, short and long text, file upload, ranking, matching, NPS |
| REQ-ASSESS-02 | Question banks with randomised selection and ordering |
| REQ-ASSESS-03 | Auto-grading with manual grading for open-ended responses |
| REQ-ASSESS-04 | Pre/post skills evaluation pairing |
| REQ-ASSESS-05 | **Per-survey anonymity, chosen at survey creation.** When anonymous: no `user_id` stored with the response, a random respondent reference instead, aggregate reporting only, and an audit record proving anonymisation happened at submission |
| REQ-ASSESS-06 | Minimum group size enforced before any aggregate survey result is displayed |

### 3.7 Credentials

| ID | Requirement |
|---|---|
| REQ-CRED-01 | Certificates issue only when the rule engine confirms every requirement is met |
| REQ-CRED-02 | PDF generation with course, learner, issuer, dates, certificate ID, QR code and signatory |
| REQ-CRED-03 | Public verification page showing holder, course, issue and expiry dates, and status (valid / expired / revoked) |
| REQ-CRED-04 | Revocation with audit trail; reissue supported |
| REQ-CRED-05 | Badges with criteria, evidence URL, issuer metadata and levels |
| REQ-CRED-06 | LinkedIn sharing via both the share URL and *Add to Certification* (credential ID + credential URL) |
| REQ-CRED-07 | Learner controls credential visibility — private, public, or link-verifiable. Consent matters for corporate training |
| REQ-CRED-08 | CPD points as optional certificate fields — pending decision §1.4 #7 |

### 3.8 Workshops

| ID | Requirement |
|---|---|
| REQ-WS-01 | Session types: one-on-one coaching, group workshop, cohort session, assessment debrief |
| REQ-WS-02 | Facilitator profiles and availability calendars with timezone handling |
| REQ-WS-03 | Capacity, booking windows, waitlists, cancellation and reschedule rules, no-show handling |
| REQ-WS-04 | Credit-based booking where a package includes sessions |
| REQ-WS-05 | Microsoft Teams via Graph API: create meeting, generate join link, send calendar invite, update and cancel |
| REQ-WS-06 | Pluggable meeting provider interface — Teams first, Zoom and Meet behind the same contract, manual link as the always-available fallback |
| REQ-WS-07 | Attendance states: registered, joined, attended, partially attended, no-show, cancelled, rescheduled |
| REQ-WS-08 | Facilitator can always confirm attendance manually, whatever the provider reports |
| REQ-WS-09 | Post-workshop survey feeding the completion rule engine |

### 3.9 CRM, marketing and AI insights

| ID | Requirement |
|---|---|
| REQ-CRM-01 | Leads, contacts, organisations, deals, tasks, notes, activities, consent records |
| REQ-CRM-02 | Pipeline stages with source and campaign attribution |
| REQ-CRM-03 | Transactional email through an external ESP with SPF, DKIM and DMARC on a dedicated sending domain |
| REQ-CRM-04 | Campaign and newsletter sending, segmentation, suppression list, unsubscribe and bounce handling, preference centre |
| REQ-CRM-05 | First-party event tracking stored in Postgres — no third-party tracker |
| REQ-CRM-06 | **AI provider abstraction covering all four the customer asked for: OpenAI, Anthropic Claude, Google Gemini, and Azure OpenAI / Copilot.** The blueprint silently dropped Gemini and Copilot; they are restored here |
| REQ-CRM-07 | **PII redaction gateway.** Direct identifiers are stripped and tokenised (`[PERSON_1]`, `[COMPANY_1]`) before any prompt leaves the platform |
| REQ-CRM-08 | AI insights link to a cohort, never to an individual, unless the course explicitly permits individual reporting |
| REQ-CRM-09 | Per-tenant token budgets, human review of significant insights, no automated punitive action, prompt-injection defence, per-tenant AI kill switch |

### 3.10 Corporate and multi-tenancy

| ID | Requirement |
|---|---|
| REQ-TEN-01 | `tenant_id` on every tenant-scoped table, enforced by middleware and Postgres row-level security, **from Phase 1** |
| REQ-TEN-02 | Organisations, seat allocation, bulk invite, CSV import, seat reassignment |
| REQ-TEN-03 | **Manager visibility defaults to aggregate only.** Individual results require the course-level toggle *and* the tenant-level setting *and* an explicit permission — the customer's stated reason is to avoid bullying |
| REQ-TEN-04 | Custom subdomain per enterprise tenant (`company1.executivetrainingportal.co.za`) — later phase, behind a flag |
| REQ-TEN-05 | Per-tenant theme, catalogue, registration fields, email branding, privacy settings — later phase, behind a flag |
| REQ-TEN-06 | Per-tenant SAML/OIDC federation — later phase, behind a flag |

### 3.11 Administration

| ID | Requirement |
|---|---|
| REQ-ADMIN-01 | Dashboard: revenue, active learners, new leads, **pending EFT approvals**, completions, certificates issued, workshops scheduled, at-risk learners |
| REQ-ADMIN-02 | Content publishing workflow: draft → in review → approved → published → archived |
| REQ-ADMIN-03 | Immutable audit log covering logins, role changes, payment approvals, refunds, certificate issuance and revocation, content publication, data exports and AI configuration changes |
| REQ-ADMIN-04 | Feature flags for every deferred capability |

### 3.12 Requirement traceability

Every requirement stated in the customer's four messages maps to at least one ID above. This table exists because the source material lost two AI providers between one answer and the next.

| Customer statement (source message) | Requirement IDs |
|---|---|
| Courses purchasable on a website (1) | REQ-STORE-01/02, REQ-PAY-01/02 |
| Payfast or Netcash, or direct EFT with local banks (1) | REQ-PAY-01/02/03 |
| Advanced LMS after purchase, credentials issued (1) | REQ-LMS-01…07, REQ-LEAD-06 |
| Paid one-on-one live workshops via Meet / Teams / Zoom (1) | REQ-WS-01/05/06 |
| Certificate generation after completion (1) | REQ-CRED-01/02 |
| Must not bypass training by clicking Next (1) | REQ-BYPASS-01…11 |
| Badges and progress shareable via LinkedIn, Coursera-like (1) | REQ-CRED-05/06 |
| RBAC and ABAC (1) | §2.2, [04 §2](04_SECURITY_AND_COMPLIANCE.md#2-authorization) |
| Tiered roles/views by package purchased (1) | REQ-TEN-02, entitlements in [02 §6](02_DATA_MODEL.md#6-commerce) |
| Individual **and** group training (1) | REQ-TEN-02/03 |
| Admin high-level status + deep AI analytics on testing and surveys (1) | REQ-ADMIN-01, REQ-CRM-06…09 |
| Billing, invoicing, CRM (1) | REQ-PAY-09/10/11, REQ-CRM-01/02 |
| Bulk email and monthly newsletters (1) | REQ-CRM-03/04 |
| Phased delivery, each gate demoable (2) | §8 |
| Marketing collateral and podcasts as a sales lure (2) | REQ-STORE-03/04/05 |
| Free content and guest/test credentials capturing convertible data (2) | REQ-LEAD-01…08 |
| Static bucket, S3 **or** Microsoft, per hosting preference (2) | [06 §2](06_OPERATIONS.md#2-storage) storage adapter |
| Captured data salted and hashed against compromise (2) | [04 §4](04_SECURITY_AND_COMPLIANCE.md#4-data-protection) — see §4.3 on why most of it must be encrypted, not hashed |
| Both SA and international market (3) | REQ-PAY-08 |
| ZAR local, USD international, SA tax rules (3) | REQ-PAY-08/11 |
| VAT registered, fully auditable for compliance (3) | REQ-PAY-09/10/11 |
| Corporate invoice / EFT / PO (3) | REQ-PAY-03/04 |
| Enterprise subdomains with uniquely catered content (3) | REQ-TEN-04/05 |
| CPD/accreditation as an option (3) | REQ-CRED-08 |
| Per-survey anonymity toggle (3) | REQ-ASSESS-05 |
| Managers see overview, not specifics, to avoid bullying (3) | REQ-TEN-03 |
| AI must process anonymised data (3) | REQ-CRM-07/08 |
| Top four AI providers: OpenAI, Claude, Gemini, Copilot (3) | REQ-CRM-06 |
| Industry-standard video protection, DRM to stop scraping (3) | REQ-LMS-04, §5.8 |
| Downloads only if admin allows, tied to the customer (3) | §5.8, REQ-BYPASS-09 |
| Teams first, extensible to others (3) | REQ-WS-05/06 |
| Multiple facilitators and scheduling (3) | REQ-WS-02/03 |
| ~50–500 learners, ~100 concurrent (3) | §6.2 |
| Analytics on clicks, visits, interests (3) | REQ-CRM-05, REQ-ADMIN-01 |
| Data residency in South Africa (3) | [06 §4](06_OPERATIONS.md#4-infrastructure), REQ-CRM-05 |
| Lean infrastructure that does not eat revenue (4) | §5.10, [06 §4](06_OPERATIONS.md#4-infrastructure) |
| Technical solution document for developers/admins (4) | This document + [06_OPERATIONS.md](06_OPERATIONS.md) |
| Feature matrix / pricing tier document (4) | [05_COMMERCIAL.md](05_COMMERCIAL.md) |

---

## 4. Workflow design

### 4.1 Order state machine

```
                 ┌──────────► cancelled
                 │
draft ──► pending_payment ──► paid ──► fulfilled ──► refunded
                 │                         │
                 ├──► eft_pending_proof ────┤
                 │         │                │
                 │         ▼                │
                 ├──► eft_pending_approval ─┤
                 │         │                │
                 │         ├──► eft_rejected
                 │         │
                 └──► po_pending_approval ──┘
```

Entitlements are granted on the `fulfilled` transition and never before. `eft_rejected` returns to `eft_pending_proof` on resubmission, and every transition writes a ledger entry.

### 4.2 Lesson completion state machine

```
locked ──► available ──► in_progress ──► requirements_met ──► completed
   ▲                          │
   └──────────────────────────┘
        (prerequisite revoked, or attempt limit exhausted)
```

`requirements_met` is computed server-side by the rule engine on every progression request. The client may render `completed` optimistically but the API is the arbiter, and a refusal returns the specific unmet requirements (see the `LESSON_LOCKED` error in [03_API_SPEC.md §1](03_API_SPEC.md#1-conventions)).

### 4.3 Core workflows

1. **Lead to sale** — discover → consume ungated content → CTA → lead form (creates contact, lead, consent record, UTM attribution, optionally a guest account) → magic link → sample content → nurture sequence → purchase → enrolment, with guest progress carried over.
2. **Guest credential** — form → validate email, consent, duplicate lead → create guest user with sample-only entitlement and hard expiry → magic link → track engagement → pre-expiry conversion prompt → downgrade at expiry, lead retained in CRM.
3. **Card purchase** — checkout → gateway → webhook (signature validated, idempotent) → order paid → entitlement granted → confirmation.
4. **EFT purchase** — order pending → bank details and unique reference issued → learner uploads proof → finance notified → approve or reject → on approval, invoice issued and entitlement granted.
5. **PO purchase** — organisation admin selects seats → PO number and document captured → pro-forma issued → finance approves → seats activated → admin invites learners.
6. **Learning completion** — entitlement checked → backend records lesson start, video heartbeats, elapsed time, quiz attempts, survey submission → rule engine validates on each advance → unlock or return unmet requirements → on course completion issue certificate and badge, notify, offer sharing.
7. **Live workshop** — browse → select slot → validate payment/credit, capacity and facilitator availability → booking created → meeting provisioned via Graph → invite and reminders → join → attendance recorded → post-session survey → completion rules updated.

### 4.4 Re-evaluation triggers

Completion is recomputed, and a certificate may be revoked, when: a course's completion rules change; an assignment approval is withdrawn; attendance is corrected after the fact; a quiz attempt is invalidated for suspected cheating; or an entitlement is revoked following a refund or chargeback.

---

## 5. Technical decisions

Each subsection is a verdict, not a topic.

### 5.1 Backend — FastAPI, not NestJS

**Decision.** Python 3.12, FastAPI, SQLAlchemy 2.0 async, Alembic, Pydantic v2, pydantic-settings. Version pins copied from `Agentic_development_worksorder`.

**Rationale.** Every existing internal application — `mast-app`, `site_visit_access_system`, `Facial Recognition`, `Agentic_development_worksorder`, `Agentic_development_collab_platform` — is FastAPI + SQLAlchemy + Alembic + Postgres. The reusable surface is concrete, not theoretical: the storage adapter the blueprint spends a section designing already exists; so does the config-safety pattern, the JWT and MSAL wiring, and the base model mixins. Worksorder's CI pipeline transfers as a unit, including the migration round-trip and `alembic check` drift gates — which matter more here than anywhere, given that this product's core compliance claim is gapless, auditable invoice numbering. Python also suits this product's awkward corners: `reportlab` and `qrcode` for certificates (both already running in `site_visit_access_system`), and mature NLP tooling for the PII redaction gateway.

**Consequence.** Type sharing with the web tier is generated rather than native — see §5.3. Two toolchains in one repository.

**Not chosen: NestJS + Prisma** (the blueprint's recommendation). No reusable in-house code, a second long-term stack to maintain, and Prisma is weakest exactly where this product is most demanding — row-level security, partial indexes, append-only ledger constraints, and reporting queries.

### 5.2 Web — Next.js, not React + Vite

**Decision.** Next.js 15 App Router, TypeScript, Tailwind. Public site, storefront, learner portal and admin portal in one application. Server-rendered where SEO matters. Route handlers act as a thin BFF only — hostname → tenant resolution, session cookie handling, brokering signed media URLs. **No domain logic in the web tier.**

**Rationale.** The public site *is* the sales funnel (REQ-STORE-06); an SPA undercuts the thing the customer is paying for. Precedent exists in-house: `Agentic_development_Internal_Booking` runs Next.js 15 against a non-Node backend, so a polyglot frontend/backend split is established practice.

**Consequence.** Deviates from the React + Vite house default. A Node runtime in production alongside Python.

**Not chosen: React + Vite** (house default) — measurably worse for a content-marketing funnel. **Not chosen: two frontends** (Vite app plus a separate static marketing site) — two deployments, two auth surfaces, one avoidable seam.

### 5.3 Type contract — generated, not written

**Decision.** FastAPI emits `openapi.json`; `openapi-typescript` generates `packages/api-client`; **CI regenerates and fails on drift.**

**Rationale.** This recovers most of what the blueprint's all-TypeScript argument was actually about. Worksorder's pipeline already exports `openapi.json` as a build artifact, so the mechanism is half-built. A future Expo app consumes the same package.

**Consequence.** A build step rather than a shared source of truth. Contract tests are mandatory, not optional.

### 5.4 Identity — self-issued, federation outsourced

**Decision.** Self-issued JWT, Argon2id via `argon2-cffi`, magic links, TOTP MFA required for Finance, Admin and Facilitator roles. Enterprise SAML/OIDC federation via `msal`, configured per tenant.

**Rationale.** Guest accounts with hard expiry, magic-link onboarding, entitlement-bearing sessions and per-tenant role mapping all fight a hosted IdP. Argon2id is the customer's implied requirement ("salted and hashed") done correctly, and `Agentic_development_collab_platform` already pairs PyJWT with `argon2-cffi`. Federation is genuinely someone else's problem, so it is delegated.

**Not chosen: Auth0 / Cognito / Keycloak** (the blueprint says "custom not recommended") — correct as general advice, wrong for a product whose access model is entitlement-driven.

### 5.5 Tenancy — schema-ready now, white-label later

**Decision.** `tenant_id` on every scoped table, tenant-resolution middleware and Postgres row-level security from Phase 1. Custom subdomains, per-tenant theming, per-tenant catalogues and SSO ship in Phase 5+ behind feature flags.

**Rationale.** The blueprint contradicts itself here — "nice to have later" in one answer, foundation work in the next. Both are half right. Tenancy in the schema is cheap now and brutal to retrofit; white-label *features* are expensive and delay first revenue. Split the difference along that line.

**Consequence.** Every query carries tenant context from day one. RLS policies are written alongside each migration, not after.

### 5.6 Authorization — one policy module

**Decision.** A dedicated, typed, exhaustively-tested policy module. Permission strings from day one. No permission check anywhere else in the codebase.

**Rationale.** The blueprint's warning is correct: *do not scatter permission checks randomly through the code.* With per-tenant, per-course and per-manager-relationship visibility rules, scattered checks guarantee a privacy incident — and the manager-visibility rule exists specifically to prevent workplace bullying, so getting it wrong has a human cost, not just a compliance one.

**Not chosen: an OPA sidecar** — Rego plus a sidecar is unjustified at 100 concurrent users. **Casbin** was considered; a hand-rolled evaluator is preferred for testability against the four named policies in [04 §2.3](04_SECURITY_AND_COMPLIANCE.md#23-abac-policies).

### 5.7 Async work — arq + Redis

**Decision.** `arq` with Redis 7.

**Rationale.** House standard. The blueprint recommends a Postgres-backed queue specifically to avoid paying for Redis — but Redis is needed anyway for rate limiting and tenant-config caching, so the saving is illusory. Take the blueprint's *cost discipline* (budget alerts, autoscale caps, retention limits), not its conclusion.

**Not chosen: Celery** — its threading model fights async SQLAlchemy, as documented in worksorder.

### 5.8 Video — self-hosted ladder, DRM behind a flag

**Decision.** Port the VOD transcode pipeline from the in-house `Streaming_Server` project into a Python media module. At launch: short-lived signed HLS URLs, server-side heartbeat validation, a per-user player-overlay watermark, downloads disabled. Widevine/FairPlay is a documented upgrade behind `VIDEO_DRM_ENABLED`.

**Rationale.** `Streaming_Server` is a 3GPP 5G MBS broadcast head-end, but its own architecture document states that *"with every flag off the system is an ordinary HLS origin; the standards layers switch on above it."* Underneath the broadcast machinery sits exactly the right VOD pipeline: one decode → N encodes, IDR pinned to segment boundaries so renditions are switchable without artefacts, declared VBV per rung, CMAF/fMP4 with a master playlist, `vod` already the default packaging mode. That is the part normally rented from a Mux-class provider. The build-vs-buy line falls at DRM, not at transcoding.

The watermark the source describes — *"overlay the logged-in user's email semi-transparently"* — is a **player overlay**, not per-user re-encoding. That distinction is what keeps launch-stage protection cheap.

**Consequence.** Signed-URL issuance, heartbeat validation, concurrent-stream caps, geo/domain restriction and CDN integration must be built; none exist in `Streaming_Server`. Nothing of its `mbms-security.js` transfers — 3GPP MSK/MTK broadcast keying is a different problem from unicast DRM, as its own header notes. `Streaming_Server` itself is not modified by this project. Full detail in [06_OPERATIONS.md §3](06_OPERATIONS.md#3-media-pipeline).

**Not chosen: renting an encoder at launch** — recurring per-minute and per-GB cost for something already owned. **Not chosen: Azure Media Services** — retired mid-2024; the blueprint recommends it in one answer while warning against it in another.

### 5.9 Mobile — responsive web, then PWA, native deferred

**Decision.** Responsive web in every phase. PWA at Phase 4.5. Native React Native deferred with no committed date.

**Rationale.** Apple and Google in-app-purchase rules are actively hostile to a product whose main revenue paths are corporate invoice, EFT and purchase order. A learning companion app adds cost without adding a sales channel.

**Not chosen: React Native at Gate 9** (the blueprint's position in one answer, contradicted in another).

### 5.10 Deployment — Compose now, Azure later

**Decision.** Docker Compose for local and demo. Azure South Africa North documented as the production target. Terraform written in the hardening phase, not before.

**Rationale.** The customer's final and most specific constraint is that infrastructure cost must not consume early revenue. Provisioning cloud before there is anything to host contradicts that directly — and so does the blueprint's own Answer 3, which was written before the constraint existed and adds multi-tenancy, DRM and Azure-everything on top.

**Consequence.** Every phase demos on a laptop. Azure region availability must be verified before commitment (§1.4 #10).

### 5.11 Analytics — first-party, in Postgres

**Decision.** An `events` table in Postgres, written by the API. No third-party analytics tracker.

**Rationale.** Data residency is a stated requirement; a first-party table satisfies it without argument, avoids a consent-banner category, and at this volume needs no warehouse. The blueprint's own lean-analytics advice says the same.

**Consequence.** Dashboards are built, not bought. Partitioning is a documented scaling trigger, not a launch concern.

### 5.12 Repository layout

```
apps/
  web/            Next.js 15 — public site, storefront, learner + admin portals
  api/            FastAPI — system of record
    src/
      core/       config, db, security, storage, errors, ratelimit, policy
      models/     SQLAlchemy
      schemas/    Pydantic
      routers/    HTTP surface
      services/   domain logic, incl. media/ (ported transcode ladder)
      workers/    arq tasks
    alembic/
    tests/
packages/
  api-client/     generated from openapi.json — never hand-edited
infra/
  docker-compose.yml
  postgres-init/
docs/
```

---

## 6. Non-functional requirements

### 6.1 Data integrity — the hard rules

1. **No completion decision is ever made by a client.**
2. **Ledger entries and audit events are append-only.** No `UPDATE`, no `DELETE`, enforced at the database level.
3. **Invoice numbers are sequential and gapless per tenant per financial year.** Allocation happens inside the issuing transaction.
4. **Anonymous survey responses never carry a `user_id`** — not nullable-and-empty, not present.
5. **Every payment webhook is idempotent**, keyed on the provider's event ID.

### 6.2 Performance

| Metric | Target |
|---|---|
| API p95, common endpoints | < 500 ms |
| Concurrent users at launch | ~100 |
| Registered learners at launch | 50–500 |
| Report generation | Asynchronous above 2 s |
| Video start time | < 3 s on a 10 Mbps connection |

### 6.3 Availability and recovery

Uptime target 99.5% at launch, revisited when an enterprise SLA is signed. RPO 15 minutes, RTO 4–8 hours. Restore tested quarterly — an untested backup is not a backup.

### 6.4 Security

Detailed in [04_SECURITY_AND_COMPLIANCE.md](04_SECURITY_AND_COMPLIANCE.md). Headline: TLS everywhere, no public database access, secrets in Key Vault, MFA on privileged roles, field-level encryption for PII, OWASP ASVS as the review baseline, and OWASP LLM Top 10 for the AI surface.

### 6.5 Auditability

Every financial action, permission change, credential issuance and AI configuration change is recorded immutably, searchable and exportable. This is a sales feature as much as a compliance one — see [05_COMMERCIAL.md](05_COMMERCIAL.md).

### 6.6 Accessibility

WCAG 2.1 AA. Keyboard navigation, screen-reader support, video captions, contrast and visible focus states. Verified in Phase 4.5, not retrofitted at the end.

---

## 7. Definition of done

A phase is done when all of the following hold:

- [ ] `ruff check` and `ruff format --check` pass
- [ ] `mypy src` passes in strict mode
- [ ] `pytest --cov` passes with no integration tests skipped
- [ ] `alembic upgrade head`, `alembic downgrade -1`, `alembic upgrade head` round-trips cleanly
- [ ] `alembic check` reports no un-migrated model drift
- [ ] `packages/api-client` regenerates with no diff
- [ ] The phase's demo script runs end to end against seeded data
- [ ] [STATUS.md](STATUS.md) is updated with the honest percentage

---

## 8. Delivery plan

The blueprint offers two irreconcilable schedules — five phases in one answer, eleven gates in another, with gate durations summing to 52–83 weeks against a stated total of 9–14 months. Both are discarded. What follows is one dependency-ordered plan. Every phase ends in something demoable, which was the customer's explicit requirement.

Durations are engineering ranges for a small team and assume Phase 0 is signed off. They are not a quote.

| Phase | Name | State | Ships |
|---|---|---|---|
| 0 | Discovery and sign-off | **BLOCKED** | Decision register, wireframes, content inventory |
| 1 | Foundation | Gated on 0 | Tenancy, identity, policy engine, storage, CI |
| 2 | Public site and funnel | | Marketing site, resource hub, leads, guest access |
| 3 | Commerce | | Card, EFT, PO, invoicing, ledger, VAT |
| 4 | Core LMS and credentials | | Player, rule engine, assessments, certificates, badges |
| 4.5 | PWA and accessibility | | Installable, WCAG 2.1 AA |
| 5 | Corporate and workshops | | Organisations, seats, manager views, Teams, campaigns |
| 6 | AI insights | | Redaction gateway, provider adapters, cohort insights |
| 7 | Hardening and cloud | | Terraform, pen test, load test, DR drill, go-live |

**Phase 0 — Discovery and sign-off.** Close every item in §1.4. Brand and design system. Wireframes for the six persona views. Content inventory of existing video and podcasts. *No engineering.* Deliverable: a signed decision register.

**Phase 1 — Foundation.** Monorepo. Docker Compose with Postgres 16, Redis 7, MinIO and Mailhog on reserved ports. FastAPI skeleton with `check_production_safety()`. Alembic baseline. Identity: Argon2id, JWT, magic links, TOTP. Tenant middleware and RLS. The policy module with its test suite. Immutable audit log. Storage adapter across S3, Azure Blob and local. Events table. `packages/api-client` generation. The full CI gate set. *Demo: two tenants resolving to different themes; login; empty admin shell.*

**Phase 2 — Public site and content funnel.** Marketing pages, resource hub, podcast integration, gated content, consent management. Lead, contact and organisation records with UTM attribution. Guest accounts with hard expiry and watermarking. Event tracking. *Demo: the whole funnel, from a podcast to a working guest login, with the lead visible in admin.*

**Phase 3 — Commerce.** Catalogue, cart, checkout. Payfast and Netcash sandboxes. EFT with proof upload and finance approval. PO capture with pro-forma. Sequential invoice numbering, append-only ledger, VAT engine, entitlements. *Demo: three purchase paths, each producing an auditable invoice; a rejected EFT; a credit note.*

**Phase 4 — Core LMS, anti-bypass and credentials.** Course, module and lesson authoring. The media module: ported VOD ladder, signed HLS, player-overlay watermark, heartbeat validation, concurrent-stream caps. The server-side completion rule engine. Quizzes with question banks. Surveys with per-survey anonymity. Certificates with public QR verification. Badges with LinkedIn sharing. *Demo: attempt to skip a lesson and be refused with the specific unmet requirements; complete properly; verify the certificate from a phone.*

**Phase 4.5 — PWA and accessibility.** Installable, offline shell, push where supported. WCAG 2.1 AA audit and remediation.

**Phase 5 — Corporate, workshops and marketing engine.** Organisations, seats, bulk invite and CSV import. Manager dashboards defaulting to aggregate only, with the privacy toggle chain working. Facilitators, availability, booking. Microsoft Teams via Graph. Campaigns and newsletters through the ESP with suppression and bounce handling. *Demo: a manager who cannot see individual scores until an admin enables it for one course.*

**Phase 6 — AI insights.** PII redaction gateway with a worked before/after. Provider adapters for all four providers. Token budgets. Insight storage against cohorts. Human review workflow. *Demo: 500 survey responses summarised with zero identifiers transmitted, shown alongside the redaction log.*

**Phase 7 — Hardening and cloud.** Terraform for Azure South Africa North. Penetration test. Load test to 100 concurrent. Backup restore drill. POPIA compliance matrix. Go-live checklist.

---

## 9. Explicitly out of scope

Deferred by design. Each needs its own justification to enter scope.

- Native iOS and Android applications
- SCORM/xAPI (pending §1.4 #1)
- Open Badges standard export, Credly/Accredible integration
- Accounting system integration (Xero, Sage, QuickBooks, Pastel) — CSV export only at launch
- Course marketplace, affiliate and referral programmes
- Gamification, leaderboards, community forums
- Proctoring and identity verification during assessment
- AI tutor / conversational learning assistant
- Multi-language content

---

## 10. Risks

| Risk | Mitigation |
|---|---|
| **Scope.** The customer's own first message says "scope can change", and the source material grew from a storefront to a multi-tenant enterprise SaaS across four turns | Phase gates with sign-off; §9 defended actively |
| **The in-house CRM, billing and marketing engine is the largest hidden cost in the source and is barely acknowledged there** | Phase 3 ships invoicing only; campaigns go to the ESP; full CRM is Phase 5 with its own justification |
| **EFT fraud** — proof-of-payment uploads are trivially forgeable | Unique references, finance approval required, reconciliation against bank statements, no auto-approval ever |
| **Payment reconciliation drift** between gateway and ledger | Idempotent webhooks keyed on provider event ID; a daily reconciliation report is a Phase 3 deliverable |
| **Privacy incident via manager visibility** — the feature exists to prevent bullying, so a bug here has a human cost | Aggregate-only default; three independent conditions required to reveal individuals; policy module tested against the named cases |
| **AI cost overrun** | Per-tenant token budgets, caching, async batching, hard caps, spend alerting |
| **AI sending PII offshore** | Redaction gateway with a logged before/after; §1.4 #4 blocks the phase until legal signs off |
| **Video cost** if streaming grows faster than revenue | Self-hosted ladder removes per-minute encoding cost; CDN egress monitored with budget alerts |
| **Azure region gaps** — not every service exists in South Africa North | §1.4 #10 verification before commitment; App Service fallback documented |
| **VAT misconfiguration on international sales** | Blocked on accountant sign-off; tax rules are data, not code; every calculation logged with a reason code |
| **Accessibility as legal exposure** for a corporate-training product | WCAG 2.1 AA in Phase 4.5, not at the end |

---

## 11. Immediate next actions

1. Put §1.4 to the customer as a single decision register and get it signed.
2. Get the accountants' written position on VAT for international digital services (§1.4 #2).
3. Confirm Azure Container Apps and Postgres Flexible Server availability in South Africa North (§1.4 #10).
4. Inventory the existing video and podcast library — count, duration, source formats — to size the transcode workload.
5. Register Payfast and Netcash sandbox accounts; both are on the Phase 3 critical path and provisioning is not instant.
