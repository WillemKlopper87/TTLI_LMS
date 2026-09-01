# TTLI LMS codebase critique — 28 August 2026

## 1. Executive summary

This review assessed the complete current TTLI repository at commit `023dd9f`, including the FastAPI backend, Next.js frontend, generated API package, PostgreSQL row-level-security model, migrations, background workers, CI, container topology, tests, documentation and current backlog.

TTLI is a capable, security-conscious LMS with unusually broad functionality for its maturity. Recent work has materially improved the baseline: assessment reporting and reusable question banks are complete, authenticated browser journeys now gate CI, Sentry is genuinely wired, and the React effect-warning backlog has been reduced from 53 warnings to zero warnings in that rule family. The present frontend lint result is only three unrelated non-blocking warnings.

No new critical authentication or tenant-isolation defect was identified in this round. The main risks have shifted from missing baseline controls to production proof and maintainability:

1. the production environment, registry, IaC, release promotion, backup/restore and aggregate observability are not implemented or demonstrated;
2. POPIA data-subject, retention, legal-hold and breach-response workflows remain incomplete;
3. the generated API contract is enforced in CI but barely consumed by the frontend;
4. several frontend and backend modules have become very large and carry too many workflows;
5. local backend tests can silently skip nearly the entire integration suite when services are absent;
6. corporate learning structures—departments, cohorts, delegated reporting and a unified gradebook—remain incomplete.

The system is suitable for continued controlled development and a tightly managed pilot. It is not ready for an accountable production launch until operational and privacy evidence is completed.

### Overall assessment

| Area | Assessment | Main conclusion |
|---|---|---|
| Tenant security | Strong | Forced PostgreSQL RLS, application tenant checks and careful BFF boundaries are substantial strengths. |
| Backend | Strong but concentrated | Strict typing and service-layer invariants are good; several service/router modules are now oversized. |
| Frontend | Functionally strong, uneven architecture | Build and lint are healthy, but page-local state/data code and handwritten response types dominate. |
| Tests and CI | Good | Broad CI gates exist; local integration-test behaviour remains misleading and component coverage is thin. |
| Operations | Incomplete | Containers exist, but no provisioned cloud environment, promotion flow, restore proof or aggregate monitoring exists. |
| Privacy/compliance | Good controls, incomplete lifecycle | Survey privacy and minimal APIs are strong; data-subject and retention workflows remain open. |
| Enterprise LMS completeness | Moderate-to-strong | Rich course, commerce, assessment and workshop coverage; organisational learning structures remain shallow. |

No existing uncommitted work was altered. In particular, the modified `docs/06_OPERATIONS.md`, untracked `docs/research/deployment-rollback-strategy.md`, and untracked `latest_critique.md` were preserved.

## 2. Current baseline and review method

### Repository state

- Branch: `main`, aligned with `origin/main` at review time.
- Reviewed HEAD: `023dd9f` (`T6 slice 3: fix the remaining 19 real set-state-in-effect cases`).
- Recent completed work includes authenticated CI browser journeys, assessment reporting/pairing, question banks, quiz timeout correctness, frontend effect cleanup and real Sentry initialisation.
- Principal stack: FastAPI, SQLAlchemy async, PostgreSQL with forced RLS, Redis/arq, Next.js 16.3, React 19, generated OpenAPI TypeScript types and Playwright.

### Review activities

The review included:

- architecture and dependency inspection;
- recent commit and uncommitted-change reconciliation;
- authorization, tenant context, BFF and production-safety inspection;
- upload, download, antivirus and object-storage review;
- CI, Docker and production-shaped Compose review;
- searches for unimplemented paths, oversized modules, raw fetch usage, local transport types and inline styles;
- reconciliation with `docs/BACKLOG.md`, `what_next.md`, `docs/NEXT_AGENT_BRIEF.md` and the existing critique;
- representative static and build validation.

This is a code and engineering-readiness critique. It is not a penetration test, legal opinion, live-provider certification, load test or production disaster-recovery exercise.

## 3. Validation evidence from this review

| Check | Result |
|---|---|
| Ruff lint | Passed. |
| Ruff formatting check | Passed; 270 files already formatted. |
| Strict mypy | Passed; 176 source files checked. |
| Frontend ESLint | Passed with 0 errors and 3 warnings. |
| Frontend TypeScript check | Passed. |
| Next.js production build | Passed; 61 static pages generated and route build completed. |
| API test attempt with inherited shell environment | Collection failed because `DEBUG=release` is not a valid Pydantic boolean. |
| API test attempt with `DEBUG=false` | Integration modules skipped slowly because local PostgreSQL/Redis dependencies were unavailable; the run was stopped and is not counted as a passing test suite. |

The repository and CI history document successful full-suite and focused question-bank runs from the preceding tranche. Those are useful prior evidence, but this report does not relabel them as a newly reproduced full-suite run.

## 4. Improvements since the previous review

### T6 is effectively complete, but the backlog is stale

`docs/BACKLOG.md` still lists T6 as open with 53 ESLint warnings. Current evidence shows only three warnings:

- two `@next/next/no-img-element` warnings in `components/site-header.tsx`;
- one anonymous default export warning in `postcss.config.mjs`.

There are no remaining `react-hooks/set-state-in-effect` warnings in the current lint result. The recent commits also fixed the quiz timeout path rather than merely suppressing the warning. T6 should be marked complete and the three residual warnings tracked separately as small cleanup.

### Sentry is now a real control

The production configuration has long required a Sentry DSN, but recent work now initialises the SDK and distinguishes unexpected exceptions from deliberate application errors. This closes the previous “configured but not operating” gap. Metrics, tracing, dashboards and alerting remain separate outstanding work.

### Question-bank and assessment depth are complete

The question bank is tenant-scoped, protected by `course:edit`, covered by forced RLS, copy-on-apply, and represented in both API and browser flows. Privacy-gated pre/post survey reporting is also present. These should no longer appear as missing product capabilities.

## 5. High-priority findings

### H1 — Production deployment and recovery remain unproven

**Severity: High — production release blocker**

The repository has production-shaped API/web images, a separate migration service and a Compose topology. CI builds images and runs report-only Trivy scans. This is a good substrate, but it is not a deployment system.

Still absent or unproven:

- Azure Container Apps or another real target environment;
- infrastructure as code;
- registry push and immutable digest-based promotion;
- staging;
- protected production approvals;
- signed artifacts/SBOM verification;
- scheduled backups for PostgreSQL and object storage;
- a demonstrated restore drill;
- rollback execution and evidence;
- production traffic switching and post-deployment checks.

`docs/research/deployment-rollback-strategy.md` and the operations edits may improve the design, but documentation is not operational evidence.

Recommendation:

1. Provision a minimal staging environment using IaC.
2. Publish API/web images with commit-SHA tags and retain digests as release evidence.
3. Turn high/critical container findings into a blocking policy with a documented exception path.
4. Run migrations as a protected one-shot deployment job.
5. Automate PostgreSQL and object-storage backups.
6. Restore both into an isolated environment and prove application-level integrity.
7. Run a forward deploy and rollback rehearsal, including a migration that cannot be naively downgraded.

### H2 — POPIA lifecycle workflows are incomplete

**Severity: High — compliance and customer assurance blocker**

TTLI contains excellent privacy-focused implementation details: minimal learner-facing coaching data, privacy-thresholded survey results, encrypted sensitive fields, blind indexes, consent records, protected uploads and audit events. The lifecycle around that data is not complete.

Outstanding capabilities include:

- learner data export/access request;
- correction workflow beyond ordinary profile editing;
- erasure or defensible anonymisation;
- retention schedules across database rows, Redis, event partitions, object storage, logs and backups;
- legal holds;
- breach-response workflow and evidence;
- email/preferences management across communications;
- proof that deletions propagate through storage and backups according to policy.

Recommendation:

- Build a data inventory linking each model/object category to purpose, lawful basis, owner, retention and deletion behaviour.
- Implement an authenticated export request with asynchronous generation, protected download and audit trail.
- Implement policy-driven anonymisation/deletion with legal-hold checks and idempotent retries.
- Add retention jobs with dry-run reports, completion evidence and alerts for failed deletion.
- Treat privacy threshold configuration as governed configuration, not an arbitrary tenant preference.

### H3 — Operational visibility stops at individual error capture

**Severity: High for production operations**

Sentry closes unexpected exception capture, and structured logging is a strong start. The platform still lacks service-level metrics, distributed tracing, central log retention, dashboards and alerting. The readiness endpoint checks only PostgreSQL; it does not prove Redis, object storage, antivirus, queue health or worker freshness.

The production-shaped Compose file contains no health checks for API, worker or web. `depends_on` orders startup but does not establish ongoing health. A healthy web process can therefore front an unavailable API, and a healthy API cannot show that scheduled/background work is progressing.

Recommendation:

- Add RED/USE metrics for web/API, database pool, Redis, queue latency, job failures, webhook outcomes, email, storage and antivirus.
- Add worker heartbeat and oldest-job-age alerts.
- Expand readiness only to hard serving dependencies; report softer dependencies separately to avoid unnecessary traffic removal.
- Add container/platform health probes and service-level objectives.
- Alert on privacy-sensitive failures such as retention backlog, failed webhook reconciliation and repeated survey-threshold access attempts.

## 6. Medium-priority findings

### M1 — Generated API types are enforced but barely consumed

**Severity: Medium — runtime correctness and maintainability**

The OpenAPI schema and `packages/api-client/src/schema.gen.ts` are regenerated and drift-checked in CI, which is excellent. Only about two frontend files currently import the generated package, while approximately 57 app files define local `interface` or `type` declarations and most data access is raw `authedFetch` plus manual `response.json()`.

This means the contract gate proves that generated artifacts match the backend, but it does not prove that most screens match either artifact. A backend field rename can leave CI green while a page fails at runtime.

Recommendation:

- Introduce a thin domain-oriented facade around `openapi-fetch` rather than importing enormous generated types directly into presentation code.
- Standardise error-envelope parsing, cancellation, pagination and mutation behaviour.
- Migrate one bounded domain at a time, starting with question bank/assessment, authentication and commerce.
- Add a lint/import rule that prevents migrated domains from returning to handwritten transport types.
- Keep frontend view models when they represent UI composition rather than wire payloads.

### M2 — The question-bank page still duplicates its initial read path

**Severity: Medium-low — correctness under future edits**

`apps/web/app/admin/question-bank/page.tsx` defines a reusable `load` callback, but its effect repeats the fetch/error/state logic instead of calling the callback. This was already noted during the implementation and remains present. The page also defines its own `BankItem` transport interface instead of consuming the generated contract.

Recommendation:

- Make the effect call one cancellable/stale-safe loader.
- Use the question-bank domain as the first generated-client facade pilot.
- Add focused tests for unauthorised, loading, server-error, create, delete and stale-response behaviour.

### M3 — Local integration tests can produce a false green

**Severity: Medium — developer feedback integrity**

Most backend tests are integration-marked and skip when PostgreSQL/Redis are unavailable. CI detects skips after pytest by parsing JUnit output and then fails, so the central gate is protected. Local pytest still spends time skipping module after module and can finish green after exercising very little.

The suite is also vulnerable to unrelated inherited environment values: `DEBUG=release` prevented all collection until explicitly changed to `false`.

Recommendation:

- Fail fast at session start when required services are absent, unless an explicit `ALLOW_SKIP_INTEGRATION=1` escape hatch is set.
- Set or validate test-owned environment variables in one bootstrap layer before application import.
- Print the isolated database and Redis target once at startup.
- Centralise repeated client/login/reachability fixtures in `conftest.py`.
- Provide a separate, explicitly named unit-only command for service-free work.

### M4 — Backend modules have crossed maintainability thresholds

**Severity: Medium — change and review risk**

Largest current implementation modules include:

- `services/workshops.py`: about 1,358 lines;
- `services/enrolment.py`: about 1,026 lines;
- `routers/assessment.py`: about 987 lines;
- `services/learning_paths.py`: about 803 lines;
- `services/orders.py`: about 781 lines;
- `routers/workshops.py`: about 731 lines;
- `routers/auth.py`: about 682 lines.

These files hold coherent domains, but several now combine creation, transitions, reporting, external-provider coordination and read models. The danger is not line count alone; it is that transaction and permission invariants become difficult to review as new features are added.

Recommendation:

- Characterise transaction and concurrency behaviour before extraction.
- Split by use case: authoring, booking, attendance, provider sync, reporting; login, refresh, recovery, MFA and magic link.
- Keep routers thin and retain state invariants in owning transaction-aware services.
- Avoid a generic “service framework”; use explicit domain modules with narrow public functions.

### M5 — Frontend screens and styling remain highly concentrated

**Severity: Medium — accessibility, consistency and change cost**

Current hotspots include:

- admin workshops page: about 1,089 lines;
- lesson activity panel: about 1,058 lines;
- checkout page: about 581 lines;
- admin analytics page: about 523 lines;
- curriculum outline: about 505 lines.

There are roughly 1,009 inline `style` occurrences. This keeps `style-src 'unsafe-inline'` in the CSP and makes consistent responsive/accessibility behaviour harder to maintain. The strict nonce-based script CSP is good; the style exception remains a measurable weakness.

Recommendation:

- Extract stable feature panels, not arbitrary fragments.
- Build shared form, table, dialog, callout, loading, empty-state, pagination and notification primitives.
- Move literal inline styles to classes/tokens incrementally.
- Remove `unsafe-inline` from `style-src` only after measuring and eliminating all required exceptions.
- Fix the remaining image warnings using `next/image` or an explicitly justified loader.

### M6 — The test pyramid is weighted toward integration and browser tests

**Severity: Medium**

The repository has ten Playwright spec files and strong real-service API integration coverage. Frontend component/hook tests are effectively absent, coverage is collected but no threshold is enforced, and video playback remains outside the authenticated CI journey.

Recommendation:

- Add component tests for shared data hooks, forms, dialogs and error states.
- Measure backend coverage by domain and set a conservative ratcheting threshold rather than an arbitrary high number.
- Add a real authenticated HLS playback/heartbeat browser journey.
- Expand axe testing to validation, modal, loading and server-error states.
- Add concurrency/rollback tests around bookings, credits, enrolment completion, payments and assessment submission.

### M7 — Security and dependency scans are not consistently blocking

**Severity: Medium**

Positive controls include `pip-audit`, npm audit, gitleaks full-history scanning and Trivy. However, container Trivy steps are explicitly report-only, GitHub Actions use mutable major tags such as `@v4`/`@v5`, and base images are tag-pinned rather than digest-pinned.

Recommendation:

- Block on exploitable high/critical findings, with time-bound reviewed exceptions.
- Pin third-party actions to commit SHAs and automate controlled updates.
- Pin production base images by digest while retaining human-readable version comments.
- Generate and retain SBOM/provenance alongside published images.

### M8 — Public-read and webhook abuse controls are uneven

**Severity: Medium-low**

Login, leads, guest access, public verification and content-engagement events have deliberate rate limiting. The backlog correctly notes that broad `/public/*` reads and some webhook surfaces lack a consistent per-tenant/IP quota strategy. Payment webhooks have strong signature/confirmation/reconciliation logic; the future ESP bounce webhook is not public yet and is correctly protected by `campaign:manage` until real provider authentication exists.

Recommendation:

- Define route classes and quotas instead of adding one-off limits.
- Separate browser IP, authenticated principal, tenant and provider-webhook budgets.
- Add replay protection/idempotency and signed-provider identity before exposing future webhooks.
- Monitor reject rates and avoid allowing the BFF address to collapse all users into one bucket.

### M9 — BFF response forwarding is narrower than the upstream contract

**Severity: Medium-low — transport correctness**

The generic BFF forwards only the upstream status, body and `Content-Type`. It drops `Content-Disposition`, caching validators, retry guidance and other safe response metadata. Current download helpers supply their own filenames, so the main user journeys work, but endpoint semantics can be lost silently as the API evolves.

Recommendation:

- Define a response-header allowlist including safe headers such as `Content-Disposition`, `Cache-Control`, `ETag`, `Last-Modified`, `Retry-After` and request/correlation identifiers where applicable.
- Test binary, empty, streamed and error responses through the BFF, not only through direct ASGI tests.
- Continue stripping hop-by-hop, cookie and unsafe cross-boundary headers.

### M10 — Backlog and status documentation drift remains expensive

**Severity: Medium-low**

The repository has a well-researched backlog, but `docs/BACKLOG.md` still shows T6 as open after its implementation. `HANDOFF.md` and `STATUS.md` remain large append-only histories, and current truth is spread across backlog, brief, critique, research and commit messages.

Recommendation:

- Mark T6 complete and record the three residual lint warnings separately.
- Keep `BACKLOG.md` as the status authority.
- Reduce `STATUS.md` to current gates/releases and archive historical handoff content by date.
- Add a small CI check for mutually contradictory headline versions/test counts where practical.

## 7. Product and enterprise capability gaps

These are scope gaps rather than newly discovered defects:

### Organisational structure

Departments/business units and hierarchical delegated reporting remain open. For enterprise clients, this should support effective dating, multiple assignments where required, manager scope, import reconciliation and historical attribution.

### Cohorts

A cohort identifier is not a complete cohort lifecycle. Required decisions include whether cohorts represent course runs or cross-course groups, enrolment windows, capacity, facilitators, milestones, transfers, archived reports and communication.

### Unified gradebook and moderation

Quiz, assignment, completion and credential data exist independently. A mature gradebook requires weighted activities, rubric/version governance, attempt history, manual overrides, moderation, finalisation and transcript export. Anonymous surveys must remain outside identifiable grading.

### Competencies and skills

Learning paths organise content but do not yet map learning to role capability, proficiency, evidence, expiry/reassessment and skill gaps.

### Learner experience

Cross-catalogue/resource search, in-app notification centre, email preference centre, bookmarks/notes, discussion/Q&A and unified deadlines remain open.

### Interoperability

SCORM is currently a deliberate non-goal; xAPI, LTI, HRIS synchronisation, learning-history import and outbound completion webhooks remain unresolved. This needs an explicit customer-segment decision before procurement commitments are made.

### Other open backlog items

- custom certificate design;
- CRM depth;
- workshops calendar view;
- feature flags/staged rollout before AI;
- multi-currency/i18n, blocked on commercial/tax decisions;
- live Payfast, Teams/Graph and other provider verification, blocked on credentials/accounts;
- AI insights only after privacy, feature-control and observability foundations are ready.

## 8. Strengths to preserve

- Forced RLS with non-owner application/test users and explicit tenant filtering.
- Host and JWT tenant assertions at the request boundary.
- Production fail-fast checks for debug, secrets, encryption keys, local storage, Sentry and insecure service endpoints.
- In-memory access tokens with path-scoped HttpOnly refresh cookies and refresh serialisation.
- BFF overwriting tenant host rather than trusting a browser-supplied tenant header.
- Strict nonce-based production script CSP and useful security headers.
- Consistent application error envelope.
- Idempotency and transaction discipline around commerce operations.
- Content-sniffed, virus-scanned uploads and private object-storage patterns.
- Privacy-thresholded survey reporting and minimal learner-facing coaching responses.
- Real PostgreSQL CI coverage and migration round-trip/drift gates.
- Generated OpenAPI/client drift gate.
- Authenticated browser journeys that start real dependencies and fail on skips.
- Graceful, explicit refusal for unconfigured external providers rather than fake success.
- Strong explanatory comments documenting why security and transaction choices exist.

## 9. Recommended execution order

### Immediate engineering tranche

1. Finish the question-bank frontend reliability pilot: generated types, one loader, cancellation/stale-response handling and focused tests.
2. Make local integration tests fail fast unless skipping is explicitly requested.
3. Preserve safe upstream response headers through the BFF and add proxy-boundary tests.
4. Mark T6 complete and clear the three residual lint warnings.
5. Extract one bounded workflow from `services/workshops.py` and one panel from the admin workshops screen, with characterization tests first.

### Production-readiness tranche

1. Provision staging with IaC and immutable registry artifacts.
2. Add metrics, worker health, dashboards and actionable alerts.
3. Implement scheduled database/object backups and complete a restore rehearsal.
4. Run load, security and expanded accessibility checks against staging.
5. Verify Payfast and Graph/Teams in controlled provider environments.
6. Formalise release promotion, rollback, evidence retention and named acceptance.

### Privacy and enterprise tranche

1. Build POPIA export, retention/anonymisation and legal-hold foundations.
2. Add departments/business units and delegated reporting.
3. Define and implement the cohort lifecycle.
4. Define gradebook/moderation governance.
5. Add learner search, notifications and preference management.
6. Decide interoperability and competency strategy before building AI insights.

## 10. Suggested acceptance criteria for the next immediate slice

The question-bank reliability pilot is complete when:

- the page consumes generated transport types through a small facade;
- initial and post-mutation reads share one implementation;
- stale or aborted responses cannot overwrite newer state;
- the standard API error envelope is rendered consistently;
- unauthorised, loading, empty, failure, create and delete cases have focused tests;
- its authenticated Playwright journey remains green;
- Ruff, strict mypy, full API tests with zero skips, migration checks, OpenAPI/client drift, frontend lint/typecheck/build and documentation gates pass.

## 11. Conclusion

TTLI has moved beyond a simple LMS prototype. Its strongest qualities are tenant security, explicit failure behaviour, broad transactional workflows, real-service CI and unusually careful engineering commentary. The next phase should resist adding disconnected features. The highest return now comes from proving production operations and privacy lifecycle controls while gradually reducing architectural concentration and making the generated contract real in frontend code.

There is no evidence from this review that the recent question-bank, Sentry or T6 work should be rolled back. The immediate code task should be the bounded question-bank reliability pilot; the immediate organisational task should be a production-like deployment and restore rehearsal.
