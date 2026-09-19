# TTLI_LMS — next-agent brief

**Last updated:** 2026-09-15. This file is current-state orientation only. Task status belongs in
[`BACKLOG.md`](BACKLOG.md); detailed sequencing lives in
[`BACKLOG_2026-09-11.md`](BACKLOG_2026-09-11.md); Sprint-1 merge/evidence ordering is GitHub
issue #31 and the master delivery roadmap through January 2027 is issue #32. Historical narrative
belongs in `docs/archive/`, `STATUS.md` and `HANDOFF.md`.

## Current state

| Item | Current truth |
|---|---|
| `main` | `7a4e2bf762ae3db3094f344832ded6a33bc2d6c6` after #25. Always verify with `git log -1` before acting; do not treat this document as a permanent SHA source. |
| Branch protection | PR flow with required `quality`, `web`, `authenticated-e2e`, `secrets`, `images`; keep `main` green and up to date. |
| Migrations | Latest is `0047` (cross-tenant bespoke-course assignment check) as of this PR. Always verify with `ls apps/api/alembic/versions` before acting; do not treat this document as a permanent count. |
| Authenticated E2E | Required API-backed job runs **all nine** authenticated spec files serially. `REQUIRE_API_E2E=1` makes readiness/seed failures hard failures; the API-less `web` job may still skip authenticated journeys by design while owning public/browser/axe coverage. |
| Current hardening gate | F1/F2 are closed; F9/T10 code is merged. #26/T12 is the active code gate, followed by T11 and the T9/T10/T12 operator evidence. |

## Just closed

- **#27 — image/security gate:** merged as `7996ab400a4efbdf6dfac88ba37ba2168b4df689` after CI #168 passed all five required checks. Weekly scan issue #17 was reconciled and closed.
- **#29 — F1/F2 correctness:** merged as `3d28fd53a723c1bce4f6037a8961cf802dd03c23` after CI #178 passed all five required checks. The authenticated job log proves all nine named spec files actually executed under fail-closed mode. Tenant-domain cache writes now use `cache-delete → commit → cache-delete` with regression coverage.
- **#23 — backlog refresh:** merged as `12edc22494f4506816a1cd772f5947536d4db781`; `docs/BACKLOG.md` is again the current status authority.
- **#25 — F9/T10 code tranche:** merged as `7a4e2bf762ae3db3094f344832ded6a33bc2d6c6` after CI #189 passed all five required checks. Active `arq --check` worker health, coupled API+worker rollback, normal release manifests and rollback-state evidence manifests are on `main`. The real broken-worker rollback rehearsal remains operator evidence.

## Active order — do not reorder merges

1. **#26 — T12 API tranche:** refreshed after #25. Preserve access/export, anonymising erasure, legal hold and consent withdrawal; keep the export ephemeral rather than leaving decrypted PII in object storage; run all required checks and merge only when the exact refreshed head is green. Retention policy/enforcement, admin workflow, Information Officer and remaining legal/owner decisions stay open unless explicitly delivered and evidenced.
2. **#30 — T11 observability:** finish API/worker/DB/queue/storage metrics, structured log retention/search, internal-only collection, alerting and one operator dashboard. Avoid personal/high-cardinality metric labels.
3. **Operator evidence:** T9 real off-VM encrypted backup/restore drill; T10 forced rollback evidence; T12 owner/legal/retention evidence.
4. **Integration acceptance:** Payfast sandbox matrix, real Entra/OIDC if the pilot needs SSO, production-shaped load test.
5. **Close Sprint 1** only when #31’s final criteria are satisfied.
6. **Feature programme** then follows issue #32: shared slice 0 → Assessment → Programmes/Analyst → Licensing+xAPI → Partner Portal → integrated UAT/content → January release. Each dependent slice must be committed, pushed, green and merged to `main` before advancing.

## Open PR ownership

| PR / issue | Owns | Important boundary |
|---|---|---|
| #26 | Current T12 POPIA API/data-subject-rights tranche | Do not call T12 complete while export coverage, retention/admin/legal/Information-Officer evidence remains open. |
| #30 | T11 minimum viable observability | Metrics/logs must not leak tenant/user IDs or raw object keys into labels. |
| #31 | Ordered Sprint-1 closure | Later work may be prepared separately but must not merge ahead of the active step. |
| #32 | Master TTLI delivery roadmap | Every element ends committed/pushed/green/merged on `main` before dependent work advances. |

## Hard boundaries

- Do **not** begin Assessment Platform, Programmes, Analyst Workspace, Partner Portal,
  Licensing+xAPI, or Phase 6 AI implementation before Sprint 1 closes.
- Do not weaken CI/security/RLS/coverage/drift gates to obtain green.
- Do not merge stale branches just because their old CI was green; refresh onto current `main`
  and require fresh evidence.
- Do not mark operator/legal work done from code alone.
- Do not create a new status tracker. Update `BACKLOG.md` and, where sequencing matters,
  issue #31 / issue #32.
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
