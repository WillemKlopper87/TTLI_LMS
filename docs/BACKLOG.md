# TTLI_LMS — active backlog

This is the **status authority** for outstanding work. It intentionally contains current state,
ownership and exit criteria rather than a chronological build narrative.

- Detailed ordered remediation queue: [`BACKLOG_2026-09-11.md`](BACKLOG_2026-09-11.md),
  refreshed on 2026-09-15.
- Exact pre-refresh backlog snapshot: [#23 pre-refresh `docs/BACKLOG.md`](https://github.com/WillemKlopper87/TTLI_LMS/blob/49555bc963609c49f202c312add7c248afa4134d/docs/BACKLOG.md).
- Sprint-1 merge/evidence coordination: GitHub issue #31.
- Master delivery roadmap through the January 2027 integrated release: GitHub issue #32.

**Status key:** `DONE` · `IN PROGRESS` · `OPEN` · `BLOCKED` · `GATED` · `DECIDED-NO`.

---

## 1. Immediate gate — Sprint 1 production hardening

No Assessment Platform, Programmes, Analyst Workspace, Partner Portal, Licensing+xAPI,
or Phase 6 AI implementation starts until this gate is closed or the platform owner explicitly
accepts a named residual risk.

| Ref | Item | Current state | Exit criterion |
|---|---|---|---|
| #27 | Image/security gate | **DONE 2026-09-15.** CI #168 green; payload-scoped Trivy dispositions, targeted web libpcre2 fix, API cJSON reachability guard; weekly issue #17 closed. Merged as `7996ab4`. | Five required checks green on the accepted payloads. |
| **F1** | Truthful authenticated browser coverage | **DONE 2026-09-15 via #29.** CI #178 proves all nine named authenticated specs ran under `REQUIRE_API_E2E=1` with no silent skips. Merged as `3d28fd5`. | All nine authenticated journeys execute and pass in the required API-backed job. |
| **F2** | Tenant-domain cache invalidation | **DONE 2026-09-15 via #29.** Domain writes now use `cache-delete → commit → cache-delete`, with regression coverage for hit/miss eviction and hostname normalization. | A domain add/remove is authoritative immediately; TTLs are fallback bounds only. |
| **T9 / O2** | Backups + restore rehearsal | **OPEN — operator evidence.** Backup/restore tooling exists; no code change can substitute for a real off-VM crypt destination, accountable owner and production-shaped restore drill. | Archive lands off-host; isolated restore succeeds; measured RPO/RTO recorded and within targets. |
| **F9 / T10** | Worker health, deployment integrity and rollback proof | **CODE DONE 2026-09-15 via #25; operator evidence remains.** CI #189 passed all five protected gates and #25 merged as `7a4e2bf`. Worker health now uses `arq --check` with a 30 s sentinel refresh; a failed worker rollout rolls API+worker back together; normal and rollback-state release manifests are written and the encrypted backup path persists them off-host. Remaining T10 gate: forced broken-worker rollback rehearsal on a production-shaped host with before/after evidence and known-good recovery. | Stalled worker fails deployment; every release emits evidence; failed worker release rolls API+worker back together and known-good canary passes. |
| **T11 / O1** | Minimum viable observability | **IN PROGRESS — #30.** Sentry error capture is already shipped. #30 owns aggregate API/worker/DB/queue/storage metrics, internal collection, alerting, searchable structured logs and an operator dashboard. | Required signals are collected without tenant/user-cardinality leakage; alerts are actionable; logs survive container restart and are searchable by request/job correlation id. |
| **T12 / O3** | POPIA operational lifecycle | **IN PROGRESS — #26 refreshed after #25.** Current code tranche provides access/export, anonymising erasure, legal hold and consent withdrawal. Export JSON is now an ephemeral five-minute Redis capability deleted on first download, so it does not leave an indefinite decrypted object in storage. The export is still explicitly non-exhaustive: workshops, survey responses and CRM contact history remain support-handled residual categories. Retention policy/enforcement, admin workflow, Information Officer responsibility and remaining legal/owner decisions stay open. | Data-subject lifecycle is tested end to end; retained financial/accreditation records are de-identified rather than incorrectly deleted; export coverage/residual process is explicit; owner/legal decisions are recorded. |
| **T13 / P11** | Phase 6 readiness decision | **GATED.** Do not start the AI vertical slice before T9–T12 are closed or explicitly accepted and data-residency/budget/kill-switch decisions are signed. | Readiness decision recorded; tenant kill switches and budget enforcement exist before any LLM call path. |

### Integration acceptance still required

| Item | Status / blocker | Exit evidence |
|---|---|---|
| Payfast sandbox matrix | **BLOCKED on B4 credentials.** | Success/cancel/duplicate+replayed ITN/bad signature/wrong amount or currency/delay/refund/outage matrix recorded. |
| Real Entra/OIDC acceptance | **Conditional.** Required if a pilot tenant uses SSO; needs tenant app registration. | Real IdP login/callback/session acceptance recorded. |
| Production-shaped load test | **BLOCKED on a production-shaped host.** | Pilot profile exercised with latency, DB-pool saturation and duplicate-fulfilment assertions. |

---

## 2. 2026-09-11 independent review findings

These findings were verified against code at the review baseline. Status below is current; the
original detailed sequencing and exit criteria are in [`BACKLOG_2026-09-11.md`](BACKLOG_2026-09-11.md).
F14–F16 were not registered findings in that review; the numbering intentionally jumps from
F13 to F17.

| Ref | Finding | Status |
|---|---|---|
| **F1** | Four authenticated Playwright specs were green by never entering the API-backed required loop. | **DONE — #29 / CI #178.** |
| **F2** | Tenant-domain resolution cache was not invalidated on domain mutation. | **DONE — #29 / CI #178.** |
| **F3** | Gradebook N+1 around quiz lookup and attempts. | **OPEN.** |
| **F4** | Learner dashboard N+1 around quiz lookup and attempts remaining. | **OPEN.** |
| **F5** | Campaign send loops contacts and enqueues inside the request transaction. | **OPEN.** |
| **F6** | Admin lists/exports lack consistent pagination/ceilings. | **OPEN.** |
| **F7** | `infra/docker-compose.prod.yml` is stale relative to the single-VM production topology. | **OPEN.** |
| **F8** | Compose resource/log-rotation limits are incomplete. | **OPEN.** |
| **F9** | Worker had no active healthcheck; updater could accept a running-but-broken worker. | **DONE IN CODE — #25 / CI #189 / `7a4e2bf`; T10 rollback rehearsal evidence still open.** |
| **F10** | Dependabot lacks Docker ecosystem coverage for base images. | **OPEN.** |
| **F11** | CI duplicates expensive browser/build/test/tool-install work. | **OPEN.** |
| **F12** | Digest-pinned images remain partly non-reproducible because package/transitive resolution is not fully locked. | **OPEN.** |
| **F13** | Date/money formatting is inconsistent across several pages. | **OPEN.** |
| **F17** | Screenshot-pass UX defects: push prompt placement, mobile header/catalogue/player and learner IA. | **IN PROGRESS 2026-09-19.** **F17a done** — push opt-in no longer fetches/prompts on `/checkout/*` or the lesson player (`/learn/<enrolment id>`); vitest route-gating tests. **F17b done** — public header collapses behind an `aria-expanded` toggle under 760px (was an overflowing scroll strip); vitest ARIA tests plus Playwright mobile-viewport (375px) no-overflow and axe checks on every public page. **F17d done** — `.foot-nav` stacks full-width under 560px so "Next lesson 🔒" stays in the content column (CSS-only; no player e2e fixture exists, so no automated coverage). Remaining: F17c (mobile catalogue filters), F17e (learner nav IA — the dashboard's continue CTA already exists). |
| **F18** | Anonymous storefront pages are force-dynamic/no-store and lack route loading states. | **OPEN.** |
| **F19** | Local `ttli_test` state can accumulate across runs. | **OPEN.** |
| **F20** | Thin test areas plus broad exception handling in tenant-user role/suspension paths. | **OPEN.** |
| **F21** | Migration round-trip exercises only the newest migration. | **OPEN.** |
| **F22** | Trivy is installed from a mutable apt channel rather than a checksum-pinned release. | **OPEN.** |

The same review ruled out authenticated-response caching through the BFF, an SSO `next=` open
redirect, repeated `getTheme()` work in the root layout, and the admin access-token boot race.
Do not re-raise those without new evidence.

---

## 3. Structural debt after Sprint 1

Do this after the production gate, and profile before optimising.

| Area | Items | Status |
|---|---|---|
| Data access/performance | F3, F4, F5, F6; slow-query capture + `EXPLAIN (ANALYZE, BUFFERS)` before indexes. | **OPEN.** |
| Storefront delivery | F18 caching/revalidation and `loading.tsx` coverage. | **OPEN.** |
| Frontend contract safety | Incremental typed facade over `packages/api-client`, highest-risk pages first. | **OPEN.** |
| Shared components / decomposition | O8/O14; split large mixed-responsibility pages/services after characterisation tests. | **OPEN.** |
| UX | F17a–e. | **OPEN.** |
| Test/CI hygiene | F7, F8, F10, F11, F12, F19, F20, F21, F22; media lifecycle and BFF edge coverage. | **OPEN.** |

---

## 4. Product / platform backlog after hardening

Only owner-approved work should move ahead of the structural-debt queue.

| Ref | Item | Status |
|---|---|---|
| **P6 residual** | Live Payfast verification. | **BLOCKED on B4.** |
| **P8** | Departments / business units + department-scoped reporting. | **OPEN.** |
| **P10** | Custom certificate design. | **OPEN.** |
| **P11** | AI insights vertical slice. | **GATED on T13.** |
| **P12** | CRM depth. | **OPEN.** |
| **P15** | Learner search, notifications centre, email preferences. | **OPEN.** |
| **P16** | Workshops calendar screen. | **OPEN.** |
| **P17a** | Cohort schema and lifecycle. | **OPEN.** |
| **P18** | Unified gradebook UI/moderation/group reporting/export. | **IN PROGRESS — backend partial only.** |
| **P19** | Competency / skills framework. | **OPEN.** |
| **R7** | Bulk / zip content upload. | **OPEN.** |
| **R9** | Feature flags / staged rollout. | **OPEN; prerequisite for P11 rollout.** |
| **R11** | ASR / auto-captions. | **BLOCKED on policy/data-residency position.** |
| **R15** | Interoperability strategy decision: xAPI/LTI/HRIS/history import/completion webhooks. | **OPEN decision task.** |
| **O6** | Deeper browser coverage — video playback remains uncovered. | **OPEN.** |
| **O8** | Documentation consolidation + generated-client/shared-component cleanup. | **OPEN.** |
| **O10** | Multi-currency / i18n plumbing. | **BLOCKED on B2.** |
| **O11** | Azure production/staging provisioning and IaC. | **BLOCKED on B3.** |
| **O12** | Production-shaped load test. | **BLOCKED on O11 / production host.** |
| **O14** | Large-module decomposition. | **OPEN.** |

Explicitly deferred/declined items such as SCORM and direct-bank integration remain documented
in the commit-pinned historical backlog; they are not silently converted back into build work here.

---

## 5. External decisions / evidence

Do not code around these.

| Ref | Required input | Blocks |
|---|---|---|
| **B1** | Signed platform-owner decision pack. | Phase 0 decisions, production configuration, T13/P11. |
| **B2** | Accountants' written international VAT position. | O10 / international pricing. |
| **B3** | Azure region/account/environment provisioned. | O11, O12. |
| **B4** | Payfast/Netcash sandbox and production credentials. | Live card acceptance. |
| **B5** | Real content inventory and media inputs. | Cost model and production content readiness. |
| **B6** | Brand/design-system sign-off. | Final persona/UI sign-off. |
| **B7** | Real footer social URLs. | Final public-site cleanup. |
| **B8** | Information Officer responsibility/registration confirmed. | T12 compliance posture. |

---

## Working rule

Every implementation PR must update the relevant row here with evidence in the same change.
Do not create parallel status documents. Historical snapshots are retained by immutable Git
history; current truth belongs here. Sprint-1 closure remains issue #31; the macro roadmap
through the integrated January 2027 release is issue #32.
