# TTLI LMS — whole-codebase audit report

**Audit date:** 2 September 2026  
**Repository:** `C:\ttli`  
**Branch reviewed:** `main`  
**HEAD reviewed:** `40a9d0d` (`feat: site audit remediation, feature-flags platform, video workflow redesign`)  
**Assessment type:** source-code, architecture, security, privacy, test, delivery and operational-readiness review

## 1. Executive summary

TTLI is a substantial multi-tenant learning and commerce platform rather than a prototype. It has unusually strong engineering foundations in PostgreSQL row-level security, tenant-context enforcement, explicit permissions, transaction-aware domain workflows, upload scanning, production configuration validation, generated API contracts and CI security gates.

The platform is suitable for continued controlled development and a tightly managed pilot. It should not yet be approved for an accountable production launch. The remaining risk has shifted away from missing baseline application controls and toward:

1. two correctness defects introduced in the latest video and deployment work;
2. insufficient regression coverage for the newest platform functionality;
3. incomplete production, recovery, observability and privacy evidence;
4. architectural concentration that makes increasingly complex workflows difficult to review safely; and
5. enterprise product capabilities that remain intentionally unbuilt.

No new critical authentication, privilege-escalation or cross-tenant RLS defect was identified during this review. That is a scoped source-review conclusion, not a penetration-test result.

### Overall assessment

| Area | Assessment | Summary |
|---|---|---|
| Tenant isolation and authorization | Strong | Forced RLS, request tenant context and explicit permissions are mature foundations. |
| Backend correctness | Strong with new high-risk gap | Mature transactional workflows; video policy binding requires immediate correction. |
| Frontend | Functional but concentrated | Broad product coverage; local types, large screens and minimal component testing increase regression risk. |
| API contract | Strong generation, limited consumption | Drift is gated, but most screens do not consume generated types directly. |
| Security engineering | Strong | Fail-fast configuration, upload scanning, CSP, secret scanning and blocking vulnerability gates are present. |
| Privacy/compliance | Incomplete | Data minimisation exists in important paths, but operational POPIA lifecycle workflows are not complete. |
| Testing | Broad but infrastructure-heavy | Strong real-service and browser design; newest features lack targeted tests and the pure-unit layer is thin. |
| Deployment and operations | Pilot-grade | A single-VM path exists, but immutable promotion, reliable component rollback, observability and recovery proof remain open. |
| Production readiness | Not demonstrated | No staging deployment, live-provider validation, restore rehearsal, load evidence or operated SLO evidence was established. |

## 2. Scope and method

The audit covered the repository in totality at an architectural and risk-oriented level, including:

- repository history, working-tree state and project documentation;
- FastAPI routers, services, models, schemas, migrations and worker design;
- tenant resolution, authentication, authorization, RLS and security configuration;
- payment, entitlement, learning, assessment, credential, workshop, CRM and media workflows;
- Next.js application structure, BFF/session handling, generated API types and browser suites;
- Dockerfiles, Compose topologies, deployment, update and backup scripts;
- GitHub Actions, dependency controls, secret scanning and image scanning;
- privacy and POPIA readiness;
- test distribution and locally executable quality gates; and
- stated roadmap and enterprise product gaps.

This review was not a penetration test, legal opinion, accessibility session with assistive technology, load test, live payment/provider certification, cloud architecture certification or disaster-recovery exercise.

## 3. Validation evidence

### Passed locally

| Check | Result |
|---|---|
| Git state before audit | Clean `main` checkout at `40a9d0d`. |
| Ruff lint | Passed. |
| Ruff formatting | Passed; 278 files already formatted. |
| Strict mypy | Passed; 182 source files checked. |
| TypeScript typecheck | Passed. |
| ESLint | Passed with 0 errors and 4 warnings. |
| Documentation link integrity | Passed; 349 relative links across 82 files. |
| Source extraction fidelity | Passed; 5 extracted files matched their source export. |
| Shell syntax | Passed for deploy, rolling-update, backup, development and gate scripts. |
| Working-tree hygiene after audit | Clean; temporary audit reports were removed. |

The four ESLint warnings were one request-triggering `setState` effect, two raw `<img>` warnings and one anonymous default export warning.

### Not established in this environment

| Check | Limitation |
|---|---|
| Full API suite | Correctly refused to run because Postgres and Redis were unreachable. It is not reported as passing. |
| RLS/integration verification | Requires the isolated migrated test database and Redis. |
| Migration round-trip and model drift | Not run against a live database. |
| Authenticated Playwright journeys | Required API and infrastructure services were not started. |
| OpenAPI/client regeneration | `apps/api/openapi.json` was absent locally; CI exports it before client generation. |
| Single-VM Compose rendering | Real production-only secrets were unavailable; required-variable checks failed closed. |
| Live providers | Payfast, Teams/Graph, SMTP, object storage and other provider integrations were not exercised against real accounts. |
| Production operations | No deployed health, alert, release, backup or restore evidence was available. |

## 4. Priority findings

### H1 — Video delivery policy is not bound to the destination course

**Severity: High**  
**Files:** `apps/api/src/routers/media.py`, `apps/api/src/models/course.py`, migration `0040`

The new two-phase upload accepts a client-supplied `course_id`, describes it as advisory, stores it on the video asset and uses it to decide whether progressive/as-is delivery is allowed. Finalisation re-reads the same stored advisory value.

The later lesson attachment endpoint loads only the lesson and asset. It does not:

- resolve the lesson's module and owning course;
- require that course to match `asset.course_id`;
- re-evaluate `allow_bypass` against the actual destination course; or
- require the asset to be finalised and `ready`.

Consequences:

- an asset can be finalised as progressive under a permissive course or tenant default, then attached to a course that requires transcoding;
- an invalid or absent advisory course can fall back to tenant policy;
- a draft, uploaded, processing or failed asset can be attached to a lesson, producing a broken learner experience; and
- the server does not enforce the policy boundary described by the administration UI.

**Required remediation**

1. Resolve `Lesson -> Module -> Course` inside the attachment transaction.
2. Require the asset to be in the `ready` state.
3. Bind the asset to the destination course or require an exact course match.
4. Re-evaluate progressive-delivery policy against the actual destination course.
5. Add regression tests covering permissive-to-restricted attachment, invalid course IDs, cross-course reuse, every non-ready state and a policy change between upload and attachment.

### H2 — Worker deployment failure can leave an unreported mixed release

**Severity: High**  
**File:** `scripts/rolling-update.sh`

The updater rolls the worker back if it fails its five-second running check, but deliberately continues with the new API and web release. It can therefore finish with:

- the new database migration applied;
- API on the new image;
- worker on the old image; and
- web on the new image.

The final success message nevertheless states that API, worker and web are all on the new version. The script also exits successfully after the worker rollback.

This is unsafe when API and worker job payloads, database assumptions or scheduled-job behavior evolve together.

**Required remediation**

1. Treat worker failure as a release failure.
2. Roll API and worker back as one compatibility unit, or establish and test an explicit version-skew contract.
3. Replace the five-second process check with an active worker heartbeat or canary job.
4. Record and display the actual image digest and Git SHA for every running component.
5. Make the final status and exit code reflect partial or failed rollout states.

### M1 — Weekly image-scan issues omit their evidence

**Severity: Medium**  
**File:** `.github/workflows/image-scan-weekly.yml`

The scan writes filenames containing the image tag and `-report`, such as `trivy-ttli-api:rescan-report.txt`. The issue-creation step tries to read `trivy-ttli-api-rescan.txt` and its web equivalent. A new high/critical finding will still open an issue, but both evidence sections will report that no file exists.

The workflow also opens a new issue on every failing schedule without finding or updating an existing issue for the same unresolved finding.

**Recommended remediation**

- Use deterministic filesystem-safe filenames independent of image tags.
- Upload the reports as workflow artifacts even if issue creation fails.
- Add a stable issue marker and update/reopen the existing issue instead of creating weekly duplicates.
- Add a small workflow test or shell assertion that every expected report exists before issue creation.

### M2 — New video and platform functionality lacks targeted regression tests

**Severity: Medium**

No test references were found for the new:

- feature-flag list/update endpoints;
- system-health endpoint;
- course/tenant video settings;
- selected transcode rungs;
- progressive delivery path; or
- upload/finalise workflow introduced by migration `0040`.

The existing media suite exercises the prior upload/transcode design. Static checks cannot detect the destination-course policy gap in H1.

Feature-flag changes also do not appear to emit audit events, despite changing tenant production behavior.

**Recommended remediation**

- Add API tests for permission denial, tenant isolation, persistence, unknown flags, defaults and audit emission.
- Add media state-machine and policy tests described under H1.
- Add a real browser journey for video upload, selection, finalisation, attachment and learner playback.
- Test both HLS and progressive responses, content type, range behavior and expiry/revocation.

### M3 — Production releases are built from mutable source and tags

**Severity: Medium**  
**Files:** `infra/docker-compose.single-vm.yml`, `scripts/rolling-update.sh`

The single-VM deployment uses mutable upstream tags, including `latest` and `stable`, and builds application images directly on the production host after `git pull --ff-only`.

This limits reproducibility and makes it difficult to prove that the source reviewed, the image scanned and the image deployed are identical. Image IDs offer a local rollback convenience, but not durable artifact promotion or recovery after host loss.

**Recommended remediation**

- Build once in CI and publish immutable digest-addressed images.
- Generate SBOM and provenance alongside the images.
- Sign images and verify signatures at deployment.
- Promote the same digest through staging and production.
- Pin third-party runtime images by digest and update them through a reviewed process.
- Deploy by release identifier rather than pulling and compiling on the production host.

### M4 — Backup capability does not meet the documented recovery objective

**Severity: Medium**  
**File:** `scripts/backup-db.sh`

The current backup script creates one nightly logical PostgreSQL dump and copies it off the VM. It correctly acknowledges that this provides a worst-case 24-hour RPO, not the documented 15-minute target.

The script does not by itself protect:

- Garage/object-storage content;
- Redis-backed queued work;
- coordinated consistency between database rows and stored objects; or
- recovery correctness through automated restore verification.

**Recommended remediation**

- Back up database and object storage under one documented recovery procedure.
- Add WAL-based or managed continuous database recovery if the 15-minute RPO remains required.
- Perform scheduled restores into an isolated environment.
- validate migrations, object availability and representative learner/admin journeys after restore;
- measure and record achieved RPO/RTO rather than treating backup creation as recovery proof.

### M5 — Application test coverage is broad but overly infrastructure-dependent

**Severity: Medium**

The repository contains roughly 482 Python test functions and strong real-service coverage, but most significant application suites are module-level integration suites. In this audit environment, loss of Postgres and Redis meant the full suite correctly stopped and the non-integration selection exercised no meaningful application tests.

This slows feedback and makes domain policy defects harder to isolate.

**Recommended remediation**

- Extract pure policy and state-transition functions where doing so does not weaken transaction ownership.
- Add fast tests for validation, transition matrices, pricing/tax calculations, policy resolution, feature flags and serialization.
- Retain real PostgreSQL tests for RLS, constraints, locking and concurrency.
- Add coverage reporting by domain with a conservative ratcheting floor.
- Avoid replacing valuable integration tests with mocks; add a lower layer beneath them.

### M6 — Backend domains have crossed maintainability thresholds

**Severity: Medium**

Largest backend implementation files include:

| Module | Approximate lines |
|---|---:|
| `services/workshops.py` | 1,358 |
| `services/enrolment.py` | 1,026 |
| `routers/assessment.py` | 987 |
| `services/learning_paths.py` | 803 |
| `services/orders.py` | 781 |
| `routers/workshops.py` | 743 |
| `services/analytics.py` | 705 |
| `routers/auth.py` | 683 |

The issue is not line count alone. Several modules combine authorization assumptions, state changes, provider calls, reporting, read models and transaction boundaries. That makes concurrency and rollback behavior increasingly difficult to review.

**Recommended remediation**

- Characterise behavior with tests before extraction.
- Split by use case rather than creating a generic service framework.
- Keep transaction ownership explicit.
- Separate workshop authoring, booking, attendance, provider synchronization and reporting.
- Separate authentication login, refresh, recovery, MFA and magic-link flows.

### M7 — Frontend contracts and tests do not match the breadth of the UI

**Severity: Medium**

The generated API schema is drift-gated, but most frontend screens still use raw authenticated fetches, manual `response.json()` calls and locally declared response types. Consequently, a backend/client contract can remain internally consistent while a manually typed page fails at runtime.

Frontend component and hook testing remains effectively absent. Playwright journeys are valuable, but they are expensive and cannot economically cover every validation, loading, retry and failure state.

**Recommended remediation**

- Adopt generated operation/result types incrementally when touching a screen.
- Add shared typed query/mutation helpers without obscuring HTTP behavior.
- Add component tests for forms, dialogs, pagination, empty states, error mapping and refresh/retry behavior.
- Preserve Playwright for critical cross-layer journeys and accessibility checks.
- Reduce the remaining request-triggering effect warning rather than suppressing it.

### M8 — BFF response forwarding remains narrower than the API contract

**Severity: Medium-low**

The generic BFF primarily forwards status, body and content type. Safe upstream semantics such as `Content-Disposition`, cache validators, `Retry-After` and correlation identifiers can be lost.

**Recommended remediation**

- Define an explicit safe response-header allowlist.
- Continue stripping hop-by-hop, cookie and unsafe cross-boundary headers.
- Test binary, empty, streamed, rate-limited and error responses through the BFF itself.

### M9 — Current-state documentation remains fragmented

**Severity: Medium-low**

`README.md`, `docs/STATUS.md`, `docs/BACKLOG.md`, `docs/NEXT_AGENT_BRIEF.md`, `what_next.md`, `latest_critique.md`, the previous `TTLI_Code_report.md` and this report overlap. Some historical status entries remain useful evidence but are easy to mistake for current truth.

**Recommended remediation**

- Keep `docs/BACKLOG.md` as the sole task-status authority.
- Keep one short current-state handoff.
- Archive dated reviews rather than copying their conclusions into every status file.
- Add lightweight checks for contradictory headline phase, migration and test-count claims.

## 5. Privacy and compliance assessment

### Positive controls

- Sensitive learner-facing responses have been deliberately minimized in important flows.
- Encryption and blind indexes exist for protected fields.
- Anonymous survey reporting uses threshold controls.
- Audit infrastructure and administrative audit views exist.
- Tenant isolation and explicit permissions reduce accidental cross-customer disclosure.
- First-party analytics avoid unnecessary third-party tracking.

### Outstanding POPIA lifecycle capabilities

Production readiness still requires operated workflows for:

- data-subject access and portable export;
- correction requests;
- erasure/anonymisation with documented legal and financial exceptions;
- retention enforcement across database, object storage, logs and backups;
- consent withdrawal propagation;
- legal holds;
- processor/subprocessor governance;
- breach-response evidence;
- encryption/blind-index key rotation; and
- auditable approval and completion records for privacy requests.

These are not satisfied by policy documentation alone. They require code paths, operator procedures, permissions, audit records and rehearsed evidence.

## 6. Product and enterprise gaps

The following are roadmap gaps rather than defects in implemented functionality:

1. departments/business units, hierarchy and delegated reporting;
2. full cohort or course-run lifecycle;
3. unified gradebook, moderation, manual overrides and finalisation;
4. competency/skill frameworks, proficiency, evidence and reassessment;
5. learner notification centre and communication preferences;
6. bookmarks, notes, discussion/Q&A and unified deadlines;
7. custom certificate design;
8. deeper CRM automation and provider-backed email events;
9. workshops calendar-oriented administration;
10. HRIS synchronization, xAPI, LTI and outbound completion webhooks;
11. multi-currency, localization and international tax decisions; and
12. production AI insight governance, redaction, review and cost control.

Enterprise scope should be chosen from validated customer segments. It should not displace the correctness and operational work in this report.

## 7. Strengths to preserve

- Forced PostgreSQL RLS and request-scoped tenant configuration.
- Double tenant assertions and fail-closed access patterns.
- Explicit permission checks and no-privilege-escalation rules.
- Fail-fast production-safety validation.
- Transaction-aware booking, payment, entitlement, learning and credential workflows.
- Concurrency protections in high-risk booking and idempotency paths.
- Fail-closed antivirus handling for uploads.
- Payment signature, confirmation, replay and reconciliation controls.
- Path-scoped refresh cookies and BFF-based session boundary.
- Strict production script CSP and useful security headers.
- Ruff, strict mypy, TypeScript and ESLint gates.
- OpenAPI-to-TypeScript drift enforcement.
- Real-service authenticated browser CI with skip prevention.
- Full-history secret scanning.
- Blocking high/critical container scanning with reviewed, expiring exceptions.
- Rationale-rich comments that explain security and transaction decisions.

## 8. Recommended remediation roadmap

### Tranche 1 — immediate correctness and evidence fixes

1. Bind video assets and progressive-delivery policy to the actual destination course.
2. Require ready assets at lesson attachment.
3. Add the missing migration `0040` and feature-flag regression suites.
4. Make API/worker deployment atomic and add worker readiness evidence.
5. Correct weekly Trivy report filenames and issue deduplication.
6. Emit audit events for feature-flag changes.

### Tranche 2 — production-like deployment proof

1. Build immutable images in CI and deploy by digest.
2. Provision an isolated staging environment from repeatable infrastructure.
3. Run migration, rollback, queue, upload, email, payment and media smoke tests.
4. Add aggregate logs, metrics, traces, queue health and alert routing.
5. Rehearse database plus object-storage restoration and record achieved RPO/RTO.
6. Validate live Payfast and Teams/Graph flows when credentials become available.

### Tranche 3 — privacy and architectural sustainability

1. Implement subject-access/export and retention/erasure workflows.
2. Add key-rotation procedures and tests.
3. Decompose the largest backend modules in behavior-preserving slices.
4. Adopt generated frontend contracts incrementally.
5. Introduce component-level frontend tests and a faster backend policy-test layer.

### Tranche 4 — enterprise product expansion

Start with organisational hierarchy and delegated reporting, then define cohorts and gradebook governance. Continue only from customer-validated requirements and preserve anonymous-survey separation from identifiable learner grading.

## 9. Acceptance criteria for the immediate tranche

The immediate work should not be considered complete until:

- a progressive asset cannot be attached to a course whose effective settings forbid bypass;
- a non-ready asset cannot be attached to a lesson;
- tests cover course mismatch, invalid course, state transitions and tenant isolation;
- platform feature-flag endpoints have permission, tenant, persistence and audit tests;
- a failed worker rollout returns failure and cannot be reported as a successful uniform release;
- the deployed component-version report reflects the actual running images;
- a simulated weekly Trivy failure attaches or embeds both scan reports; and
- all existing static gates plus the real-service API and authenticated browser suites pass without skips.

## 10. Conclusion

TTLI has a strong application-security and domain-engineering core. The repository demonstrates careful thinking about tenant boundaries, money, entitlements, completion rules, upload safety and failure behavior. Those qualities should be preserved.

The current risk is that rapid feature growth is outpacing invariant-level tests and production proof. The latest video workflow shows how an apparently well-commented policy can remain client-advisory at the server boundary, while the updater shows how operational scripts can report a uniform success after creating component version skew.

The next release should therefore be a focused reliability tranche, not another broad feature tranche. Once the immediate correctness defects are fixed and a production-like deployment and restore rehearsal have produced evidence, TTLI will have a credible path from a strong pilot system to a production-operable platform.
