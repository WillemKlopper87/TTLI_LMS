# TTLI_LMS — consolidated backlog

Every outstanding item in one numbered list, so work can be picked by number.
Compiled 2026-08-20 by checking each research document against the actual
code, not by trusting the documents' own status claims. Sizes are S/M/L as
the source research estimated them; where this compilation disagreed with a
document, the code won.

Sources: `docs/research/enterprise-gaps-plan.md` (Passes A–K),
`docs/research/feature-matrix-coverage.md` (the 54-row audit),
`docs/NEXT_AGENT_BRIEF.md` §7, and the per-doc leftovers found on 2026-08-20.

**Status key:** `OPEN` · `BLOCKED` (waiting on someone outside engineering) ·
`DECIDED-NO` (deliberately not building).

---

## P — Product gaps (the enterprise-gaps-plan Passes A–K)

None of these have started. Ordered as the plan orders them: demo value per
unit of effort, with the two procurement gates (P4) placed where they must be.

| # | Item | Size | Why it matters | Status |
|---|---|---|---|---|
| **P1** | **Admin operations home + per-course analytics** (Pass A; audit #41, #40). `GET /admin/overview` KPI block + "needs attention" lists; `GET /admin/courses/{id}/analytics` (funnel, completion rate, per-lesson drop-off, quiz distribution, at-risk); rebuild `/admin`; retire the two inert nav items | S–M | `/admin` is a 21-line "Welcome" stub with two dead nav links — the first screen any buyer or admin opens. Every input already exists in `orders`, `enrolments`, `lesson_completions`, `quiz_attempts` | OPEN |
| **P2** | **Audit log read path + coverage** (Pass B; audit #52). `GET /audit-events` filterable + keyset-paginated + CSV export, `audit:read` permission, `/admin/audit` page; add `audit.record` to payment approve/reject/refund, certificate revoke, role changes, course publish, tenant settings | M | "Advanced audit logs" is an Enterprise-column promise. Events are written but there is **no read path at all**, and finance/credential/RBAC actions aren't logged. Also the first thing a POPIA reviewer asks for. Note: `events` is monthly-partitioned (`0004`) — the read path must respect partition range | OPEN |
| **P3** | **Tenant self-service: branding, domains, users, roles** (Pass C; audit #44, #45 + unlisted). `PATCH /tenant/theme` + logo upload with live preview; `GET/POST/DELETE /tenant/domains` with verification token + TLS status readout; **a user/role admin UI** | M | There is currently **no way to create a staff user or assign a role from inside the product** — `routers/tenant.py` has exactly one PATCH (manager-visibility). Theme and domains change only by migration | OPEN |
| **P4** | **SSO — Entra ID / OIDC** (Pass D; audit #46). Per-tenant IdP config, OIDC via `msal`/`authlib`, JIT provisioning + role mapping; SAML later | L | The standard corporate procurement gate for Team/Corporate tiers. `msal` is named in README's stack table but **nothing exists** — password/magic-link/TOTP only | OPEN |
| **P5** | **Learning paths** (Pass E; audit #7). `learning_paths` + `learning_path_courses`, path entitlement / `Product.kind="path"`, progress rollup, admin builder, learner page, path certificate | L | Core LMS vocabulary and a Professional-tier ✅ in the feature matrix. `learning_path` returns **zero hits** in the codebase | OPEN |
| **P6** | **Finance completeness** (Pass H; audit #34, #39, #31). Invoice PDF; `GET /invoices` for the buyer; accounting CSV export (`/invoices/export`, `/ledger/export`, finance-gated) | S–M | Cheap to close, and the rigorous gapless-invoicing/ledger work is invisible to a customer without it | OPEN |
| **P7** | **Workshops end to end** (Pass G; audit #20, #22, #24, #25). Real Teams `onlineMeetings` create/cancel + join_url delivery; ICS/calendar invites; learner "my sessions" page; multiple facilitators per session (`session_facilitators`); reschedule (REQ-WS-03); decrement workshop credits | M–L | Live workshops are half the commercial pitch. The Teams provider is a **stub that raises**, `book_session` hard-codes `manual`, and there is no learner-facing workshops page | OPEN |
| **P8** | **Departments / business units + dept-scoped reporting** (Pass F; audit #30). `departments` (org_id, parent_id), member FK, CSV import column, dept filter on reports, dept-scoped visibility, UI | M | Corporate reporting is flat per organisation. `department` returns **zero hits** | OPEN |
| **P9** | **Assessment depth** (Pass J; audit #8, #9, #13). Survey results/aggregate endpoint + UI with `minimum_group_size` enforced (REQ-ASSESS-06); pre/post skills pairing (`evaluation_role` + `pair_id`, delta report); question banks | S–M | The anonymous-survey story is built on the write side only — responses go in, nothing reads them back. `minimum_group_size` is specified and never enforced | OPEN |
| **P10** | **Custom certificate design** (Pass I; audit #19). Design fields on templates (logo/background key, colours, layout preset), upload, renderer, admin preview | M | `render_certificate_pdf` is a fixed layout: Helvetica, one border, no logo. Certificates are the visible product of the LMS | OPEN |
| **P11** | **AI insights vertical slice** (Pass K = Phase 6; audit #42, #43). Provider abstraction, PII-redaction gateway + redaction log, insight jobs, token budgets, kill switch, review UI | L | Phase 6's demo target: 500 survey responses summarised with zero identifiers transmitted, shown beside the redaction log. Only `Tenant.ai_enabled` / `ai_monthly_token_budget` columns exist. Must ship inert behind the flag | OPEN |
| **P12** | **CRM depth** (audit #36, #37). Deal owner/assignee, organisation link, search/filter, lead→deal conversion, contact detail page, import/export; campaigns: use `scheduled_at`, HTML email, preference centre | M | Fine for a demo, thin for daily use | OPEN |
| **P13** | **Small, demo-visible items** (audit #17, #18, #21, #23, REQ-LEAD-05/07): LinkedIn share for certificate-only courses; CPD fields beyond one integer (body/reference/validity, `Certificate.expires_at` never set); one-on-one coaching product + private booking; Zoom/Meet providers; guest→paid carry-over; sample-only watermarking | S each | Each is a column or an enum value away from working | OPEN |
| **P14** | **Mobile layout for the admin shell** (audit #4) | S | `app/admin/layout.tsx` has a fixed `w-56` sidebar. Facilitators mark attendance on phones | OPEN |
| **P15** | **Learner-facing search; notifications centre; email preference centre** (UI design screens 19 + baseline UX) | S–M | Push exists but there is no in-app inbox; no search across catalogue/resources; no email preference page. `notification centre` returns zero hits | OPEN |
| **P16** | **Workshops calendar screen** (UI design screen 13). Month grid + agenda `.rowlist`, booking reuses `.buybox`, facilitator availability editor | M | Design-only. `calendar` returns zero hits in `apps/web` | OPEN |

---

## R — Research-document leftovers (found 2026-08-20 by re-checking each doc against code)

| # | Item | Size | Detail | Status |
|---|---|---|---|---|
| **R1** | **Charts on the payment analytics dashboard** | S–M | `payment-analytics-dashboard.md` §7 specified recharts. It is **not installed** and `/admin/analytics` has no chart markup — the dashboard is numbers and tables only. Endpoints, CSV exports, migration `0028` and the `finance` permission grant are all done | OPEN |
| **R2** | **"Podcast engagement" panel on the analytics dashboard** | S | `podcast-platform-integration.md` §123 explicitly asked the analytics dashboard to surface plays / completion rate / CTR / top CTA-converting episodes from the six listen-stat event types. Never picked up | OPEN |
| **R3** | **Article view events** | S | `resources-hub-design.md` open decision #3: articles should emit at least a "viewed" event for symmetry with podcasts' six. Still undecided and unbuilt | OPEN |
| **R4** | **EFT ageing alert (>48h pending)** | S | `02_DATA_MODEL.md` §12.4 designed it, and `bank-eft-automation.md` names it as **the trigger** to revisit EFT automation. Zero hits in code — so the signal that would tell us to act can never fire | OPEN |
| **R5** | **Completion-time estimates** (wizard differentiator #8) | S–M | Video `duration_seconds` is already stored; documents by word count, quizzes by question count; surface the sum on `GET /public/courses` and in the catalogue | OPEN |
| **R6** | **Free-preview nudge** (wizard differentiator #9) | S | Readiness warning "no lesson is marked public; free previews convert" + one-click flip. The preview→guest→lead funnel is already built end to end | OPEN |
| **R7** | **Bulk / zip content upload** (wizard differentiator #10) | M–H | Folder → modules/lessons. Feasible, but uploads are fully memory-buffered today; large zips want presigned upload first | OPEN |
| **R8** | **`robots.txt` + Content Signals policy** | S | `devsecops-deployment.md` §6.3 recommends the Cloudflare Content-Signals `robots.txt` extension to separate search indexing from AI training. There is **no `robots.txt` at all** in `apps/web` | OPEN |
| **R9** | **Feature flags / staged rollout** | M | `devsecops-deployment.md` §5.3: do **not** adopt a platform; extend the existing `subscriptions_enabled` settings pattern to per-tenant and percentage rollout with kill switches. Needed before Phase 6 ships inert (P11) | OPEN |
| **R10** | **Logo-wall expand toggle** | S | `homepage-redesign.md`: deliberately deferred until the logo count is meaningfully past 9. Revisit at 20+ | DECIDED-NO (for now) |
| **R11** | **ASR / auto-captions** (wizard differentiator #11) | H | Codebase explicitly declines ASR; collides with the data-residency posture behind `01_PRD` §1.4 decision #4 | BLOCKED (policy) |
| **R12** | **SCORM import** (wizard differentiator #12) | — | `01_PRD` §1.4 decision #1 puts it out of scope | DECIDED-NO |
| **R13** | **PayShap Request-to-Pay; direct bank APIs** | M / L | `bank-eft-automation.md` items 3–4: defer RTP until R4's ageing alert fires regularly; direct bank integration is "not worth pursuing at this scale, possibly never" | DECIDED-NO (until R4 fires) |

---

## O — Operational / platform gaps still open

Seven hardening passes shipped on 2026-08-20 (see `docs/NEXT_AGENT_BRIEF.md` §1).
These remain.

| # | Item | Size | Detail | Status |
|---|---|---|---|---|
| **O1** | **Observability** | M | Sentry DSN is a config flag only. No metrics, tracing, log shipping, dashboards or alerts, though `06_OPERATIONS.md` describes them. Incidents would be diagnosed from uvicorn stdout | OPEN |
| **O2** | **Backups + a tested restore drill** | M | Prose only (the PG16→18 dump/restore). No scheduled backup, no restore ever tested. Phase 7's demo target is literally "restore drill completed" | OPEN |
| **O3** | **POPIA data-subject rights** | M | No export-my-data, no delete-my-account, no retention jobs beyond guest expiry and auth purge. `04_SECURITY` §11 still lists legal hold and breach notification as open | OPEN |
| **O4** | **Secret scanning in CI** | S | No gitleaks/trufflehog, despite dev credentials committed in `infra/docker-compose.yml` and `ci.yml`. Those are defensibly dev-scoped — but nothing would catch the day a real key lands | OPEN |
| **O5** | **Release management** | S | No tags, no changelog, no PRs; 29 `autosave:` commits on `main`. No way to say "what shipped in v0.x" | OPEN |
| **O6** | **Deeper browser coverage** | M | Playwright + axe landed 2026-08-20 but coverage is deliberately shallow: public pages + one authenticated journey. Admin screens, the learner player and the checkout flow have no browser coverage | OPEN |
| **O7** | **`react-hooks/set-state-in-effect` cleanup** | M | 34 pre-existing sites, warn-only in ESLint so the gate could start honest. Each is a real behavioural refactor | OPEN |
| **O8** | **Docs consolidation + codebase shrink** | M | The user asked for this on 2026-08-16. `HANDOFF.md` is 209 KB and `STATUS.md` 185 KB, both append-only; `authedFetch` is copy-pasted into 18 files; the 11k-line generated API client is imported once; `components/` has 2 files for 50 pages | OPEN |
| **O9** | **1,320 test courses in the dev catalogue** | S | `scripts/hide_test_courses.py --apply` — dry-run verified, reversible, never applied. Needs a human to run it | OPEN |
| **O10** | **Multi-currency / i18n plumbing** | M | Tax engine seeds SA VAT only and refuses international buyers; UI is English-only, ZAR-only. README's pitch is "South Africa and internationally" | BLOCKED on B2 |
| **O11** | **Cloud provisioning: Azure Container Apps, Front Door, IaC, registry push, staging** | L | Containerisation is done and verified (2026-08-20). Everything above the image is not: no IaC, no registry, no environment, no TLS/edge, no staging | BLOCKED on B3 |
| **O12** | **Load test at 100 concurrent** | M | Phase 7 demo target. Needs O11 first to be meaningful | BLOCKED on O11 |

---

## B — Blocked on someone outside engineering

Do not build around these; they change the build, not just the schedule.

| # | Item | Blocks |
|---|---|---|
| **B1** | **The decision register — all 10 items in `01_PRD.md` §1.4, signed** | Phase 0, and several items below |
| **B2** | Accountants' written position on VAT for international digital services | O10, all pricing |
| **B3** | Azure region/account availability confirmed and provisioned | O11, O12 |
| **B4** | **Payfast (and Netcash) sandbox/production credentials** | Card checkout has never run against a real account; also blocks the one actionable EFT item in R13 |
| **B5** | Content inventory — video count, duration, source formats; real podcast audio; book copy | The unit-cost model, transcode sizing, and every "the platform is built but empty" page |
| **B6** | Brand/design system sign-off; wireframes for the six persona views | — |
| **B7** | Real footer social URLs | The last `homepage-redesign.md` item |
| **B8** | Information Officer registered with the Information Regulator | POPIA compliance posture (customer obligation) |
| **B9** | GitHub Actions billing | CI has been dead account-wide since 2026-08-20; `scripts/gates.sh` is the gate meanwhile |

---

## Suggested order, if you want one

1. **P1** — the admin home is the worst first-impression in the product and the data already exists.
2. **P2** — audit read path; small, and it unblocks the compliance conversation.
3. **R1** — charts finish a dashboard that is already 90% built.
4. **P6** — invoice PDF + CSV export; cheap, and it makes the finance work visible.
5. **P3** → **P4** — tenant self-service, then SSO, together the enterprise procurement gate.
6. Then the larger builds: **P5**, **P7**, **P11**.

Quick wins that could ride along with any of the above: **R4**, **R6**, **O4**, **O5**, **O9**, **P14**.
