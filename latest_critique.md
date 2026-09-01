# TTLI LMS codebase evaluation and critique

**Reviewed and regenerated:** 2026-08-28  
**Scope:** `C:\ttli`, frontend through backend, assessed as a production enterprise LMS.

## Executive assessment

TTLI is functionally strong but architecturally uneven. It has unusually broad coverage: multi-tenancy, PostgreSQL
RLS, course authoring, assessments, learning paths, workshops, commerce, OIDC SSO, credentials, PWA support and
accessibility gates. The next phase should consolidate the frontend/backend architecture, deepen enterprise learning
structures and prove production operations rather than adding disconnected features.

| Area | Assessment | Main concern |
|---|---|---|
| LMS coverage | Strong | Enterprise learning structures and interoperability remain thin |
| Backend correctness/security | Strong | Large service/router modules increase change risk |
| Frontend functionality | Strong | Page-local logic and weak generated-client adoption |
| Learner experience | Good | Search, inbox and richer learning engagement are missing |
| Corporate LMS readiness | Moderate | Departments, cohorts and delegated reporting are incomplete |
| Testing | Good | Browser coverage is selective; no coverage threshold |
| Production readiness | Moderate-low | Observability, backups, IaC, staging and load proof are absent |

## Strengths to preserve

- Forced PostgreSQL row-level security exercised through a non-owner account.
- Host and JWT tenant assertions.
- MFA-purpose-token rejection, logout revocation and idempotency-race tests.
- Safe uploads, object storage adapters, antivirus scanning and protected access.
- Privacy-thresholded survey reporting and minimal learner-facing data responses.
- Generated OpenAPI contract with a CI drift gate.
- Courses, modules, lessons, completion rules and prerequisites.
- HLS video, captions and progress heartbeats.
- Quizzes, surveys, assignments and reusable question banks.
- Learning paths and path-level credentials.
- Workshops, bookings, waitlists, rescheduling and calendar invitations.
- Corporate seat purchases and manager visibility.
- Certificates, CPD metadata and public verification.
- OIDC/Entra-style SSO, PWA support, push notifications and accessibility tests.

## Frontend critique

### Generated API contract is barely consumed

The generated client is effectively used in one frontend source file. Most pages use raw authenticated requests and
handwritten interfaces. This allows API field changes to compile while individual pages fail at runtime.

Improve by creating a typed API facade around the generated client, standardising error-envelope handling and adding
reusable query/mutation hooks. Migrate by bounded domain rather than attempting a wholesale rewrite.

### React effect warning baseline

ESLint reports approximately 52 warnings, mainly request-triggering `set-state-in-effect` patterns. These can cause
duplicate requests, cascading renders and stale state. Prefer server-side initial reads where appropriate and use
client query hooks with cancellation and stale-response protection. Do not blanket-disable the rule.

### Oversized screens

Notable hotspots include:

- admin workshops: roughly 1,085 lines;
- lesson activity panel: roughly 1,054 lines;
- checkout: roughly 581 lines;
- admin analytics: roughly 521 lines;
- curriculum outline: roughly 503 lines.

Split data access, state machines, validation and presentation into domain hooks and focused components.

### Shared design system is undersized

There are about 1,000 inline-style occurrences across roughly 97 files and very few shared components. This also keeps
`style-src 'unsafe-inline'` in the CSP. Build accessible primitives for fields, buttons, tables, modals, loading,
empty states, status indicators and notifications, then remove inline styling incrementally.

### Learner workspace gaps

- No cross-catalogue/resource search.
- No in-app notification centre.
- No email preference centre.
- No bookmarks, highlights or private notes.
- No lesson discussion/Q&A.
- No unified deadlines and assessment calendar.

The learner dashboard is capable but remains more transactional than developmental.

## Backend critique

### Large domain modules

Examples include workshops, enrolment, assessment, learning paths, orders and authentication. Split by use case while
preserving transaction, permission and tenant boundaries. A smaller file is not useful if an invariant becomes harder
to find.

### Cohort lifecycle is incomplete

A nullable cohort identifier exists without a complete cohort domain. Mature support needs enrolment windows,
start/end dates, capacity, facilitators, milestones, deadlines, transfers, announcements and archived reporting.

### Organisational hierarchy is missing

Corporate reporting is flat. Add hierarchical departments/business units, effective-dated membership, delegated
administration, department assignments and historically defensible reporting.

### No unified gradebook

Quiz attempts, assignments, completion and credentials exist, but there is no unified grade/achievement model. It
should consolidate weighting, rubrics, manual grading, moderation, attempt history, overrides, final results and
transcript export while keeping surveys outside identifiable grading.

### Competency and skill framework is absent

Learning paths organise content but do not map learning to workforce capability. Add competency definitions,
proficiency levels, role requirements, course mappings, evidence, reassessment and skill-gap reporting.

### Interoperability strategy is unresolved

SCORM is a declared non-goal and xAPI/LTI are absent. Document whether the platform will support SCORM, xAPI, LTI,
HRIS synchronisation, bulk learning-history imports and completion webhooks—or which customer segments are excluded.

## Testing gaps

- Video playback is not covered by the authenticated browser gate.
- Frontend component/hook tests are effectively absent.
- CI collects coverage without enforcing a threshold.
- Complex frontend behaviour depends mainly on slower end-to-end tests.
- Teams and Payfast lack real provider-environment proof.
- Accessibility should include modal, loading, validation and error states.
- Large services need more rollback and concurrency invariant tests.

Use a test pyramid of domain tests, real PostgreSQL/RLS integration tests, API boundary tests, component tests, focused
browser journeys and controlled live-provider staging checks.

## Privacy and operational gaps

POPIA operational capability remains incomplete: learner data export, erasure/anonymisation, comprehensive retention,
legal hold, breach response and preference management require complete workflows.

Production blockers include:

- no metrics, tracing, central log aggregation, dashboards or alerts;
- no scheduled backups or demonstrated restore drill;
- no provisioned staging environment or cloud IaC;
- no release promotion and registry process;
- no meaningful concurrency/load evidence;
- no live Payfast or Microsoft Graph verification;
- mutable GitHub Action tags rather than reviewed commit SHA pins.

## Recommendation order

1. Typed frontend data layer and React warning reduction.
2. Decompose the largest frontend and backend modules.
3. Departments, organisational hierarchy and delegated administration.
4. Real cohort lifecycle.
5. Unified gradebook, rubrics and moderation.
6. Learner search, inbox and preference centre.
7. POPIA data-subject and retention workflows.
8. Competency and skills framework.
9. Observability, backups, staging, IaC and load testing.
10. Decide SCORM/xAPI/LTI and HRIS integration strategy.
11. Custom certificate design and presentation enhancements.
12. AI insights only after feature flags, privacy operations and observability are mature.

## Next-agent plan

### Tranche 1: frontend reliability pilot

Use the bounded question-bank domain to prove a generated-type API facade, standard error handling, cancellation and
effect-safe loading. Remove its handwritten transport interfaces and duplicated load behaviour. Add component/hook
coverage and retain its authenticated browser journey.

Exit criteria:

- generated transport types are used;
- no duplicate fetch implementation is introduced;
- relevant React warnings are removed without suppression;
- loading, API-error, unauthorised and stale-response cases are tested;
- lint, typecheck, build and focused Playwright pass.

### Tranche 2: module decomposition

Characterise tests and transactions first. Extract one cohesive backend domain and one large frontend screen. Keep
permissions near entry points and invariants in the owning service. Avoid speculative generic abstractions.

### Tranche 3: corporate learning structure

Resolve department hierarchy, multiple membership, effective dating, delegated subtree administration, import matching
and historical attribution before building the schema and reports.

### Tranche 4: cohorts

Decide whether a cohort is a course run or may span courses. Then model enrolment transitions, scheduling, deadlines,
facilitators, transfers and reporting together.

### Tranche 5: gradebook governance

Define assessed activities, weighting, rubric versioning, manual grading, moderation, audit history and privacy-safe
learner/facilitator/admin views.

## Verification gates

- Preserve RLS and explicit tenant filtering.
- Add permission, tenant-isolation and concurrency tests.
- Run Ruff format/check and strict mypy.
- Run affected and complete API tests against the isolated database.
- Run Alembic drift and round-trip checks for model changes.
- Regenerate OpenAPI and API-client artefacts for contract changes.
- Run frontend lint, typecheck, build and focused component/browser tests.
- Run accessibility checks for new interactions.
- Distinguish mocked integration tests from live evidence.
- Update `docs/BACKLOG.md` and `docs/NEXT_AGENT_BRIEF.md` rather than creating another status log.

## Recommended immediate action

Start with the frontend reliability pilot, then decomposition. These reduce defect risk across every later LMS feature
without requiring unresolved customer or regulatory decisions.
