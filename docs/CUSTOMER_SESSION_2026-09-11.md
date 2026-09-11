# Customer session — 2026-09-11 — decisions and new scope

**Purpose:** record what the customer decided in the 2026-09-11 session, which
open decisions in [`01_PRD.md` §1.4](01_PRD.md#14-open-decisions-blocking-phase-0-sign-off)
they close, and three requests that are **not in the current scope** and need
their own scoping before they enter [`BACKLOG.md`](BACKLOG.md). Nothing here
changes the Sprint 0/1 hardening queue (`BACKLOG_2026-09-11.md`, on the
`docs/backlog-2026-09-11` branch), which remains "no new product
features until Sprint 1 is complete".

---

## 1. Decisions taken

| §1.4 # | Decision | Answer | Effect on the repo |
|---|---|---|---|
| 1 | SCORM/xAPI | **xAPI required.** | Was listed as out of scope pending this answer. Nothing in `apps/` implements xAPI today. Needs a scoping item — see §3.1. |
| 6 | Guest access duration | **7 days.** | Code already defaults to 7 (`apps/api/src/core/config.py`, `guest_access_days`). The intake checklist said "shipped as 14" — that was stale; corrected. Confirm `.env.prod` does not override. |
| 7 | CPD / accreditation body | **None.** Not registered with any CPD body. | CPD fields on `courses` stay nullable and unused; no CPD points on certificates; "CPD-style certificate" wording in [`05_COMMERCIAL.md`](05_COMMERCIAL.md) §2.3 should be dropped or softened. |
| 8 | Brand / design system | **Still open.** Customer is sorting out branding, marketing and CI. | Reverse-engineered palette stays. Blocks final UI polish only, not engineering. |
| 9 | Launch date | **January 2027.** Budget not discussed. | About 16 weeks after Sprint 1 (~3 weeks) for §3 scoping and build. Phase sequencing can now be planned against a date. |
| 10 | Hosting | **Azure, South Africa (SA North).** | Matches [`06_OPERATIONS.md`](06_OPERATIONS.md) §4.2. Container Apps availability in SA North still to be verified (engineering). |
| — | Security officer | **Wille (engineering) acts as security officer.** | Owner for [`04_SECURITY_AND_COMPLIANCE.md`](04_SECURITY_AND_COMPLIANCE.md), Trivy exception approvals, incident response. Does **not** replace the POPIA Information Officer, which must still be a named person on the customer's side. |
| — | Multi-region | **Discussed, not decided.** If customers outside SA buy, launch in US and UK/EU. | Not in scope for January 2027. Stage 1 is single-region by design (06 §9). Record as a Stage 3 trigger: first paying non-SA organisation. Also re-raises §1.4 #2 (VAT on international digital services) and GDPR for UK/EU learners. |

## 2. First product: LWI (Lead With Intent)

- Content is described as "basically ready". This is the first real entry for
  the **course catalogue** row in the intake checklist. Request it as
  structured content (modules, lessons, video, quiz, survey, pass thresholds)
  now, so publishing (06 §7.6) is not the January bottleneck.
- A certificate template is still required before LWI can be published at all.

## 3. New scope — not planned for, needs scoping

None of the three below exists in the PRD, data model or backlog. Each needs
its own brainstorm and a phase slot; sizes are first impressions only.

### 3.1 Licensing LWI to external facilitators (incl. health professionals)

**What they want:** other facilitators buy a licence to run LWI with their own
clients.

**What exists:** tenancy in the schema, organisation seats, white-label
tenants (05 §2.6), a Facilitator role scoped to *TTLI's* workshops.

**Gap:** a licensee model. A licensee owns their own learners, cohorts and
reporting on TTLI's content, with TTLI retaining content ownership and
royalty/usage visibility. Design decision (see the spec): a licensee is an
**Organisation with `kind = licensee`** inside the TTLI tenant, not a
separate Tenant. To settle:

- Is a licensee a white-label tenant (existing model, priced at 05 §2.6) or a
  new lighter "practice" tenant tier?
- Per-seat, per-cohort, or flat annual licence? Who bills the end learner?
- Content protection: licensees must not be able to export or re-author LWI.
- Health professionals: does their use create any patient-data or
  professional-body obligations on the platform? (Customer to confirm.)
- xAPI (§1 #1) is probably driven by this: licensees may want LWI statements
  in their own LRS. Scope xAPI as *statement emission to a configurable LRS*,
  not as an xAPI content player, unless told otherwise.

**Size:** M–L. Mostly commercial model, tenant tiering and reporting; little
new learner-facing UI.

### 3.2 Assessment / questionnaire platform (replacing MS Forms)

**What they want:** the one-on-one company assessments they currently run in
MS Forms, captured on the platform, with questions varying by the assessment
bought, high-level analysis on the answers, and eventually the Power BI
reports surfaced in the platform.

**What exists:** `surveys` / `survey_questions` / `survey_responses` with
per-survey anonymity, minimum group size, typed questions
(`question_type`), tied to lessons and the completion engine.

**Gap:** surveys are course-bound. This needs:

- **Assessment templates** as a product: sellable, versioned,
  organisation-scoped, not attached to a course. Reuse the survey tables with
  a template/instance split rather than a new subsystem.
- **Question bank + per-assessment selection** (questions change by
  assessment purchased). The quiz question-bank pattern already exists;
  extend it to surveys.
- **Respondent flows outside the LMS:** the people answering are often the
  client company's staff, not learners. Needs invite-by-link with the same
  anonymity guarantees.
- **Built-in analysis:** per-question distributions, section scores,
  benchmark vs prior runs. Keep it to what Power BI does at "high level";
  do not rebuild Power BI.
- **Power BI in-platform:** export first (CSV/API; 05 §2.5 already lists
  "optional API export") for the customer's existing Power BI, then later
  Power BI Embedded in the org dashboard. Embed is a licensing and cost
  decision (Embedded capacity is not cheap at low volume).
- **Phase 6 AI insights** overlaps here (survey summarisation), still gated
  on §1.4 #4.

**Size:** L. Largest of the three, but builds on the strongest existing area.

### 3.3 Analyst workspace with report workflow

**What they want:** in-house staff and contracted external analysts (an
external psychologist today) work on the platform, isolated from everything
else, and hand finished reports to the owners through a workflow.

**What exists:** single ABAC policy module (04 §2), manager-visibility
privacy chain, assignment review (`reviewed_by_user_id`, `approved_at`),
virus-scanned uploads, audit events.

**Gap:**

- **Analyst role** with least-privilege access: sees only the assessment
  instances assigned to them, pseudonymised where the survey is anonymous,
  no CRM/billing/course access. External contractors get MFA (already
  required for elevated roles) and time-boxed engagements.
- **Report entity + state machine:** draft → submitted → owner review →
  accepted/returned, with audit on every transition and immutable accepted
  versions. This is the assignment-review pattern generalised.
- **Owner inbox** for submitted reports; notification via the existing ESP.
- **Contractor data handling:** a POPIA operator agreement per external
  analyst; the platform should make the data exposed minimal (no raw PII
  unless the assessment is identified and the contract allows it).

**Size:** M. The workflow is small; the access-isolation review is where the
care goes, and it is a security-officer item.

## 4. Suggested sequencing (for the January 2027 date)

Specs (2026-09-11, approved approach, pending written review):
[assessment platform](superpowers/specs/2026-09-11-assessment-platform-design.md) ·
[analyst workspace](superpowers/specs/2026-09-11-analyst-workspace-design.md) ·
[facilitator licensing + xAPI](superpowers/specs/2026-09-11-facilitator-licensing-xapi-design.md).

1. Sprint 0/1 hardening (in flight, ~3 weeks). Unchanged.
2. LWI content intake + publish rehearsal on UAT. Can run in parallel with 1.
3. Brainstorm + spec §3.2 (assessments), then §3.3 (analyst workflow). They
   share the data model, so do them together.
4. Brainstorm + spec §3.1 (licensing) and xAPI. Commercial questions first.
5. Multi-region, Power BI Embedded, AI insights: post-launch.

## 5. Questions to take back to the customer

- Does the January 2027 date mean *LWI selling to the public* or *everything
  in §3 live*? The answer sets what is a launch blocker.
- Licensing: pricing model, who bills the end learner, and whether licensees
  get their own branding.
- Which assessments (names, question counts, who answers) should be first;
  a sample MS Forms export of each.
- What the external psychologist currently receives (raw responses? PII?)
  and returns (format).
- Still outstanding from the intake checklist: POPIA Information Officer,
  legal review of `/privacy` and `/terms`, Payfast credentials, VAT ruling,
  transactional email provider, budget.
