# TTLI_LMS — next-agent brief

**Last updated:** 2026-09-15. This file is current-state orientation only. Task status belongs in
[`BACKLOG.md`](BACKLOG.md); detailed sequencing lives in
[`BACKLOG_2026-09-11.md`](BACKLOG_2026-09-11.md); Sprint-1 merge/evidence ordering is GitHub
issue #31. Historical narrative belongs in `docs/archive/`, `STATUS.md` and `HANDOFF.md`.

## Current state

| Item | Current truth |
|---|---|
| `main` | `3d28fd53a723c1bce4f6037a8961cf802dd03c23` after #29. Always verify with `git log -1` before acting; do not treat this document as a permanent SHA source. |
| Branch protection | PR flow with required `quality`, `web`, `authenticated-e2e`, `secrets`, `images`; keep `main` green and up to date. |
| Migrations | `0001`–`0045` on current `main`. #26 proposes `0046`; do not assume it exists until that PR merges. |
| Authenticated E2E | Required API-backed job runs **all nine** authenticated spec files serially. `REQUIRE_API_E2E=1` makes readiness/seed failures hard failures; the API-less `web` job may still skip authenticated journeys by design while owning public/browser/axe coverage. |
| Current hardening gate | F1/F2 are closed. F9/T10, T11, T12 and T9/operator evidence remain before Sprint 1 closes. |

## Just closed

- **#27 — image/security gate:** merged as `7996ab400a4efbdf6dfac88ba37ba2168b4df689` after CI #168 passed all five required checks. Weekly scan issue #17 was reconciled and closed.
- **#29 — F1/F2 correctness:** merged as `3d28fd53a723c1bce4f6037a8961cf802dd03c23` after CI #178 passed all five required checks. The authenticated job log proves all nine named spec files actually executed under fail-closed mode. Tenant-domain cache writes now use `cache-delete → commit → cache-delete` with regression coverage.

## Active order — do not reorder merges

1. **#23 (this documentation refresh):** put the 2026-09-11 remediation findings and current Sprint-1 ownership/status onto today’s `main`; make `BACKLOG.md` the concise status authority and retain historical backlog detail under `docs/archive/`.
2. **#25 — F9/T10:** refresh onto the new `main`, resolve any overlap, run all five required checks, merge active worker canary/health and release-manifest code. A forced broken-worker rollback rehearsal remains operator evidence after code merge.
3. **#26 — T12 API tranche:** refresh after #25 in the safe order, resolve migration/overlap issues, run all required checks, merge only the code tranche. Retention policy/enforcement, admin workflow, Information Officer and remaining legal/owner decisions stay open unless explicitly delivered and evidenced.
4. **#30 — T11 observability:** finish API/worker/DB/queue/storage metrics, structured log retention/search, internal-only collection, alerting and one operator dashboard. Avoid personal/high-cardinality metric labels.
5. **Operator evidence:** T9 real off-VM encrypted backup/restore drill; T10 forced rollback evidence; T12 owner/legal/retention evidence.
6. **Integration acceptance:** Payfast sandbox matrix, real Entra/OIDC if the pilot needs SSO, production-shaped load test.
7. **Close Sprint 1** only when #31’s final criteria are satisfied.

## Open PR ownership

| PR / issue | Owns | Important boundary |
|---|---|---|
| #25 | F9/T10 worker canary/health + release evidence manifest | Code does **not** substitute for the forced rollback rehearsal. |
| #26 | Current T12 POPIA API/data-subject-rights tranche | Do not call T12 complete while retention/admin/legal/Information-Officer evidence remains open. |
| #30 | T11 minimum viable observability | Metrics/logs must not leak tenant/user IDs or raw object keys into labels. |
| #31 | Ordered Sprint-1 closure | Later work may be prepared separately but must not merge ahead of the active step. |

## Hard boundaries

- Do **not** begin Assessment Platform, Programmes, Analyst Workspace, Partner Portal,
  Licensing+xAPI, or Phase 6 AI implementation before Sprint 1 closes.
- Do not weaken CI/security/RLS/coverage/drift gates to obtain green.
- Do not merge stale branches just because their old CI was green; refresh onto current `main`
  and require fresh evidence.
- Do not mark operator/legal work done from code alone.
- Do not create a new status tracker. Update `BACKLOG.md` and, where sequencing matters,
  `BACKLOG_2026-09-11.md` / issue #31.
- Keep published history intact; no direct `main` push or history rewrite.

## External inputs still needed

- Real encrypted off-VM `rclone` destination and accountable owner for T9.
- Payfast/Netcash credentials for live payment acceptance.
- Production-shaped host/environment for restore and load evidence.
- Information Officer/legal responsibility and retention decisions for T12.
- Entra app registration if a pilot tenant uses OIDC SSO.
- Signed platform-owner/data-residency decision before T13 / any LLM call path.

## Verification conventions

- API/router/schema changes regenerate `packages/api-client` in the same PR; CI enforces drift.
- New tenant-scoped tables need RLS policy **and** grants covering every verb the service uses.
- Browser claims require the real BFF/API path where applicable; a screenshot or mocked component
  test does not replace an authenticated journey at a correctness boundary.
- Keep the production login-rate policy intact in tests; isolate/reset test limiter state instead
  of weakening the application setting.
- Preserve the reason comments around security/deployment gates. They document why a narrow
  exception or unusual CI shape exists and prevent future broadening by accident.
