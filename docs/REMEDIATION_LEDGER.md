# Remediation ledger

**This is the single, current audit-findings tracker for TTLI.** It replaces
three documents that used to overlap and disagree about what was still
open: `TTLI_Audit_Report_2026-09-02.md` and `fable5.1_review.md` (both
now archived, unchanged, at `docs/archive/` — read them only for the
original file:line evidence behind a finding, never for current status).
This file, not either of those, is authoritative on what is DONE, OPEN, or
DISPROVED. It does **not** replace [`docs/BACKLOG.md`](BACKLOG.md), which
stays the separate, sole authority for product/feature roadmap items —
this document is scoped to audit/review *findings* (correctness, security,
reliability defects), not feature work. Where a finding's remaining work
is roadmap-shaped rather than a defect, the row below says so and points
at the `BACKLOG.md` item that owns it (e.g. `O14`).

Two audit passes feed this ledger, in the order they happened (a third
remediation pass, 2026-09-05, closed Part B's §8 step 7 — see the Findings
table and "Commits made by the 2026-09-05 pass"):

- **Part A** — `TTLI_Audit_Report_2026-09-02.md` (audited `main` at
  `40a9d0d`): H1–H2, M1–M9, plus a POPIA-lifecycle section with no
  numbered findings.
- **Part B** — `fable5.1_review.md` (audited `main` at `10e759f` plus that
  session's ~42-file uncommitted working tree, dated 2026-09-03): C-1–C-3,
  H-1–H-20, plus ~45 Medium and ~60 Low findings not individually tracked
  here (see "Not attempted" below).

---

## Part A — `TTLI_Audit_Report_2026-09-02.md` findings

| ID | Title | Status | Notes |
|---|---|---|---|
| **H1** | Video delivery policy not bound to the destination course | DONE | Fixed and regression-tested in `10e759f` (`routers/media.py`, `tests/test_media.py`). The same change set that fixed this produced Part B's C-1 (lesson-block contract left inconsistent) — also DONE below. |
| **H2** | Worker deployment failure can leave an unreported mixed release | PARTIAL | `scripts/rolling-update.sh` now rolls API and worker back as one unit. Still open: the rollback check is still a 5-second process check, not an active heartbeat/canary; the final status doesn't record the actual running image digest + Git SHA per component. No BACKLOG item owns this yet — needs one before it's picked up. |
| **M1** | Weekly image-scan issues omit their evidence (filename mismatch; duplicate issues per finding) | DONE | — |
| **M2** | New video/platform functionality (feature flags, health endpoint, video settings, progressive delivery, 0040 upload/finalise) lacked targeted tests | MOSTLY DONE | Feature-flag, video-settings and H1 tests existed before this ledger; `tests/test_video_settings.py` (pure-function coverage) and Part B's H-2/H-3/H-4 concurrency tests close most of the remaining gap. Still open: a real browser journey for upload→select→finalise→attach→playback, and HLS-vs-progressive response/range/expiry tests. |
| **M3** | Production releases built from mutable source and tags (local `docker build` on the host, `latest`/`stable` runtime tags) | MOSTLY DONE | Build-once-in-CI, publish-by-digest, sign and verify: DONE (Part B's C-3). `infra/docker-compose.single-vm.yml`'s `migrate`/`api`/`worker`/`web` no longer carry a `build:` stanza — they only ever run the CI-built, cosign-verified image. `postgres`/`redis`/`garage`/`clamav`/`caddy`/`postfix-relay` are now digest-pinned. Residual, narrower than the original finding: `ci.yml`'s own Trivy scan step still targets some infra images by tag rather than digest. |
| **M4** | Backup doesn't meet the documented 15-minute RPO; no object-storage backup; no restore rehearsal | OPEN | Unchanged. Tracked below as Part B's **H-20**. |
| **M5** | Application test coverage overly infrastructure-dependent (fast/pure tier too thin) | DONE | Pure-function extraction landed: `services/subscriptions.py::compute_renewal_period`, plus new direct coverage for the already-pure `services/completion.py::evaluate/merge_rules` and `services/media/video_settings.py`. `pytest -m unit` marker and coverage config added to `apps/api/pyproject.toml`. The one regression this class of work had produced — `tests/test_orders_pricing.py` enshrining the wrong inclusive-VAT number — is fixed (Part B's H-1). |
| **M6** | Backend domains crossed maintainability thresholds (largest files mix authorization, state, provider calls and reporting) | PARTIAL | `services/workshops.py` (1358 lines) split into `authoring`/`booking`/`attendance`/`reporting` submodules — the concrete, line-verified split this finding proposed, done with zero router or test touch required. `services/enrolment.py`, `routers/assessment.py`, `services/learning_paths.py`, `services/orders.py`, `routers/auth.py` and several frontend files (`admin/workshops/page.tsx`, `lesson-activity-panel.tsx`, `checkout/page.tsx`) remain oversized — tracked as `docs/BACKLOG.md` **O14**. |
| **M7** | Frontend contracts/tests don't match the breadth of the UI (most screens hand-typed, not generated; component testing effectively absent) | OPEN | Unchanged. Overlaps Part B's **H-17** (session failure handling) and the effect-warning items below. |
| **M8** | BFF response forwarding narrower than the API contract (safe headers like correlation IDs silently dropped) | MOSTLY DONE | Response header allowlist existed already; `x-request-id` added this pass so support/log correlation survives the BFF. Still open: request-side header forwarding, and BFF-level tests for binary/streamed/rate-limited/range responses — tracked below as Part B's **M-19/M-22** (not individually broken out, see "Not attempted"). |
| **M9** | Current-state documentation fragmented across `README.md`/`STATUS.md`/`BACKLOG.md`/`NEXT_AGENT_BRIEF.md`/one-off reviews | DONE | `docs/archive/` now holds every superseded one-off review (`latest_critique.md`, `TTLI_Code_report.md`, `what_next.md`, and — as of this consolidation — `TTLI_Audit_Report_2026-09-02.md` and `fable5.1_review.md` themselves); `docs/BACKLOG.md` is the declared sole task-status authority for roadmap items; `docs/check_links.py` mechanically checks that migration-range claims in `README.md`/`NEXT_AGENT_BRIEF.md`/`BACKLOG.md` stay in sync with the actual latest migration; this file is now the sole audit-findings tracker. |

**§5 (POPIA lifecycle) and §6 (product/enterprise gaps) of the 2026-09-02
audit** are not findings with IDs. POPIA — data-subject access/export,
correction, erasure with legal/financial exceptions, retention enforcement,
consent withdrawal, legal holds, key rotation — remains entirely
unimplemented and is not tracked anywhere current; it needs its own
BACKLOG item before it can be picked up (none exists today). The product
gaps (departments/hierarchy, cohorts, gradebook, competency framework,
notifications, custom certificates, HRIS/xAPI/LTI, i18n, AI governance) are
already tracked as roadmap items in `docs/BACKLOG.md` (P15–P19, O10–O12,
R11–R15 and neighbours) — not duplicated here.

The 2026-09-02 audit's own "acceptance criteria for the immediate tranche"
(§9) are now mostly met — progressive/ready-state binding, feature-flag
tests, and "all gates + real-service API + browser suites pass without
skips" (see Part B's gate run below: 601 passed/13 skipped-by-environment/0
failed, 46 e2e passed/14 skipped-by-environment/0 failed) — with H2's
canary/digest-recording gap the one item still open against that list.

---

## Part B — `fable5.1_review.md` pass (2026-09-03)

This is the closing record for the remediation pass driven by
`fable5.1_review.md` (dated 2026-09-03, reviewed `main` at `10e759f` plus
that session's uncommitted working tree). Eight workstreams ran ahead of
this one — C-1, C-3, H-11, H-12, H-13, the money findings (H-1–H-4), and
learning-integrity (C-2, H-6, H-7, H-9, and H-8 as a side effect) — each
committing its own fix directly to `main`. This workstream is the final
verification and ledger: it did not redesign or redo any of those fixes,
only (1) ran the full gate sweep (`scripts/gates.sh`), (2) fixed the
integration gaps the sweep surfaced between those eight
independently-committed workstreams' work (including work two of them had
left uncommitted in the working tree), and (3) records the aggregate state
below.

## Gate status: GREEN

`scripts/gates.sh` — ruff check, ruff format --check, mypy, the full pytest
suite (real Postgres/Redis/ClamAV/Garage, not mocked), `alembic upgrade
head` + downgrade/upgrade round-trip + `alembic check`, `api-client drift`,
`web lint`/`typecheck`/`build`, `web e2e` (Playwright), and the docs
link/migration-range/source-extract checks — passes end to end as of this
pass's commits (`a8c0a14`, `db9ea97`, `dcd2c93`, `8612d67`, on top of
`c24dbeb`). Full pytest: **601 passed, 13 skipped, 0 failed** (614
collected), reproduced on two independent full runs after this pass's
fixes. The 13 skips are `ffmpeg`/`ffprobe` transcode tests (this Windows
dev machine has no `ffmpeg` on `PATH`) — a documented, pre-existing
local-environment gap (`HANDOFF.md`'s thirteenth pass had to add an
explicit `apt-get install ffmpeg` step to CI for the same reason), not a
code regression and not something this pass can fix locally.

**Playwright e2e**: **46 passed, 14 skipped, 0 failed** (4.8m). The skips
are the `authenticated-e2e` journeys, which `gates.sh`'s own comment
documents skip themselves when the API isn't up on `:8010` — this run
didn't start a separate API server alongside the Playwright-managed web
build, so that's expected, not a gap this pass introduced. The public
pages, axe (WCAG A/AA), broken-links and skin specs all ran for real
against the production build and passed, including axe scans of
`/`, `/catalogue`, `/login` under the tenant's actual brand colours.

### Integration gaps found and fixed by this pass

Four genuine gaps were found between the eight workstreams' independently
committed (or, in two cases, never-committed) changes:

1. **`main` was in an `ImportError` state.** H-12's media commit
   (`9920c6f`) added `routers/media.py` calls to `playback.mint(...,
   asset_id=...)`/`playback.validate(..., asset_id=...)` and imports of
   `AudioAssetResponse`/`AudioPlaybackResponse` from `schemas/media` and
   `AudioAsset` from `models` — none of which existed at `HEAD`.
   Separately, the API's own schemas (`schemas/learning.py`,
   `schemas/courses.py`, `schemas/course_wizard.py`) and
   `routers/learning.py::get_progress`/`record_heartbeat` still carried the
   pre-0041 flat `activity_type`/`video_asset_id`/`quiz_id`/… contract, out
   of step with the block-based contract the already-committed web player
   (`59c10d2`, `414096b`) expects to receive. `mypy` and a from-scratch
   `pytest` run both fail immediately in this state — this was not a
   subtle gap, `main` genuinely could not boot. **Fixed in `a8c0a14`**: add
   the missing `Audio*` schemas and model export, rename
   `playback.mint`/`validate`'s parameter to the generic `asset_id`
   `routers/media.py` already calls it with, and complete the
   `schemas`/`routers/learning.py`/`services/dashboard.py`/
   `services/operations.py` side of the 0041 cutover to match. (The fix
   itself existed, unfinished and uncommitted, in the working tree at the
   start of this pass — see "Provenance" below.)
2. **The `0041_lesson_blocks.py` migration file was never committed.**
   `0042` (H-12), `0043` (H-2/H-3) and `0044` (H-6/H-7) all carry
   `down_revision` chains through `"0041"`, but `apps/api/alembic/
   versions/0041_lesson_blocks.py` — the file `0042` depends on — was
   never `git add`ed. `alembic upgrade head` only worked on this machine
   because the file was still present on disk; a fresh clone or clean
   checkout of `main` would hit `Can't locate revision identified by
   '0041'` and the entire migration chain from 0041 onward would be
   unrunnable. **Fixed in `dcd2c93`** — committed the existing file
   unchanged, and additionally round-tripped it for the first time ever
   (`downgrade` all the way to `0040`, `upgrade head`, `alembic check`
   clean) since no prior commit's own round-trip check had gone back far
   enough to exercise `0041`'s own `downgrade()`.
3. **H-11's suspension cutoff had a same-second race.** `core/deps.py`
   compared `iat < revoked_at` (strictly less-than) so a token minted in
   the same *reinstatement* second as a later fresh login wouldn't be
   caught by a stale marker — but `iat` and `revoked_at` are both
   whole-second values, so the same comparison let a token through when
   *suspend* happened in the same second as the login it was meant to
   kill (`iat == revoked_at` is indistinguishable from "minted after" at
   that resolution). This is exactly the failure `scripts/gates.sh`'s own
   pytest run hit
   (`test_suspending_a_user_kills_their_sessions_immediately` failing with
   200 instead of 401) — reproducible on a warmed-up test process, not on
   the first (slow, cold-start) test in one. **Fixed in `db9ea97`**:
   `set_status` now deletes the revocation marker outright on
   reinstatement (`tokens.clear_access_token_revocation`) instead of
   leaving it to be out-raced by a fresh login's `iat`, which makes it
   safe to tighten the comparison to `iat <= revoked_at`
   (`tokens.is_access_token_revoked`, extracted so it's independently
   testable). New test pins the exact same-second collision directly
   against real Redis rather than depending on timing luck.
4. **`packages/api-client/src/schema.gen.ts` was stale.** H-12's and
   H-13's docstring changes (`media.py`, `reports.py`) flow into the
   OpenAPI spec's embedded operation descriptions; neither workstream
   regenerated the client. **Fixed in `8612d67`** — regenerated via the
   same commands the gate itself runs; `tsc --noEmit` clean; no route or
   type shape changed, only embedded doc comments.

Three smaller gaps from an earlier, interrupted run of this same
verification workstream were already fixed and committed on `main` before
this run started (visible in `git log`, not re-done here):
`ac3e67d` (ruff-format on 4 files H-11/H-12 committed unformatted),
`9e7ba35` (`get_public_curriculum` missing the `tenant_id` `e2daea1`'s
signature change required), and `c24dbeb` (`NEXT_AGENT_BRIEF.md`'s
migration-range claim, stale again after `0042`–`0044`).

### Provenance note

Items 1 and 4 above were not newly discovered from a clean slate. At the
start of this run, `git status` already showed a large, correct-looking,
*uncommitted* diff across exactly the files item 1 lists — the natural
reading is that the earlier interrupted run of this same workstream had
already diagnosed the `ImportError` and drafted the fix, but was cut off
before finishing verification and committing it. This run read every file
in that diff against what each named commit actually needed (not just
trusted that it was correct), ran the full test suite against it twice,
and committed it once confirmed. Items 2 and 3 were found independently by
this run.

## Findings

| ID | Title | Status | Tests added | Commit hash(es) | Residual risk / notes |
|---|---|---|---|---|---|
| **C-1** | 0041 lesson-block cutover breaks the learner player, admin wizard, four CI gates and the browser job | DONE | `tests/test_preview.py`, `tests/test_course_wizard.py`, `tests/test_courses.py` updated; `apps/web/e2e/fixtures/author-content.ts` updated | `946c8d3`, `59c10d2`, `414096b`, `3813110`, `8760bfa`, `66c78a8` + this pass's `a8c0a14`, `dcd2c93`, `8612d67` | `main` did not actually boot (import error) and the `0041` migration file itself was never committed until this pass — see integration gaps 1–2, 4 above. Verified this pass: ruff/mypy/pytest/migration round-trip (through `0041`'s own downgrade, not just `-1`)/api-client drift/web typecheck+build+lint all green against the fully-migrated tree. |
| **C-3** | Image publish/sign not gated on any test job; deploy scripts skip signature verification | DONE | none (CI workflow + deploy script changes; no new pytest coverage applies) | `fa4842f`, `0297fb3` | Verified by reading `ci.yml` (`images:` now `needs: [quality, secrets, web, authenticated-e2e]`) and `rolling-update.sh`/`deploy-single-vm.sh` (absence of `cosign` on the host is now a hard `die`, not a warn-and-continue). **Not exercised by an actual GitHub Actions run** — CI remains billing-blocked per `docs/HANDOFF.md`; `scripts/gates.sh` is the substitute gate and does not touch `ci.yml`'s job graph. |
| **H-11** | Suspending a user does not end their sessions | DONE | `tests/test_tenant_users.py`, `tests/test_auth_flows.py` | `cad134e` + this pass's `db9ea97` (ruff-format fix `ac3e67d`) | `cad134e`'s own fix had a same-second edge case that let a suspend lose a race against the login it was meant to kill — see integration gap 3 above. Closed this pass with a deterministic (non-timing-dependent) regression test. |
| **H-12** | Content-authoring surface is global; tenant `admin` can read/edit/publish another tenant's bespoke courses and quiz answer keys | DONE | `tests/test_h12_tenant_boundary.py` (new, 17 tests, two real tenants); `tests/test_preview.py` regression test | `9f745eb`, `3615cf5`, `88f7156`, `9920c6f`, `d2941f9`, `0da325f`, `9f9ddb3`, `e2daea1` + this pass's `9e7ba35`, `ac3e67d`, `a8c0a14` (the video/audio-asset half of `9920c6f`), `8612d67` | `9920c6f`'s audio/video-asset scoping half was committed in a state that didn't import — see integration gap 1. `assign_course_to_tenant`'s own docstring documents a known, deliberately-accepted residual: self-assignment isn't gated on "already exclusively claimed by another tenant" (RLS makes that check unreliable from inside a different tenant's request) — a caller who already knows another tenant's `course_id` out of band can still self-assign to it. That is H-12's own documented scope boundary. |
| **H-13** | Org progress report leaks every learner's decrypted full name to any org member, not just admin/manager | DONE | `tests/test_reports.py` (plain-member test now expects 403; manager-relationship and display-name-masking tests added) | `b02c7cc` + this pass's `8612d67` (stale client doc comment) | — |
| **H-1** | Inclusive-VAT prices charged 15% too much; the unit test enshrined the wrong number | DONE | `tests/test_orders_pricing.py` (new, asserts `grand_total == 115.00` for the inclusive case) | `a15c0e5` | — |
| **H-2** | Concurrent order approvals double-fulfil an order (two invoices, two ledger pairs, double revenue) | DONE | `tests/test_commerce.py::test_concurrent_eft_approvals_fulfil_exactly_once` | `488a76e` | Migration `0043` adds DB-layer unique backstops (`invoices.order_id`, `credit_notes.invoice_id`, `refunds.order_id`) behind the `SELECT ... FOR UPDATE` lock, matching this repo's `workshops/booking.py` pattern. |
| **H-3** | Concurrent refunds double-refund the same order | DONE | `tests/test_refunds.py::test_concurrent_refunds_of_the_same_order_produce_exactly_one_refund` | `488a76e` (same commit as H-2 — one lock, one migration, both races) | Same migration/lock as H-2. |
| **H-4** | A buyer who pays twice has the second Payfast ITN silently lost (no audit row, no 200, endless Payfast retry) | DONE | `tests/test_webhooks.py::test_second_itn_for_an_already_fulfilled_order_is_persisted_and_flagged` | `286dfda` | — |
| **C-2** | Prerequisite locking computed for display only — start/complete the last lesson directly and get a certificate | DONE | `tests/test_learning.py::test_last_lesson_cannot_be_started_before_prerequisites` / `test_course_never_completes_with_incomplete_required_lessons`; `tests/test_learning_paths.py::test_learning_path_certificate_cannot_be_triggered_by_skipping_a_course_prerequisite` | `fdd5fc8` | — |
| **H-6** | Video watch time multiplied by concurrent heartbeats; accrues while paused | DONE | `tests/test_media.py::test_parallel_heartbeats_do_not_multiply_watch_time` + the paused-position test | `e58e8f1` | Migration `0044` adds `video_progress.last_position_seconds` (bounds accrual by actual position delta) plus the row lock. |
| **H-7** | Quiz attempt limits and answer/version counters are check-then-insert with no uniqueness backstop | DONE | `tests/test_assessment.py::test_parallel_quiz_starts_*`, `test_parallel_submits_of_the_same_attempt_do_not_double_count_answers`, `test_parallel_assignment_submissions_never_share_a_version` | `e58e8f1` (same commit as H-6 and H-8) | Migration `0044` unique indexes: `(enrolment_id, quiz_id, attempt_number)`, `(attempt_id, question_id)`, `(enrolment_id, assignment_id, version)`. |
| **H-8** | A quiz attempt is consumed on every quiz-player mount (no resume-open-attempt path) | DONE — fell out of the H-7 fix | `tests/test_assessment.py::test_starting_a_quiz_with_an_open_attempt_resumes_it` / `test_starting_a_quiz_after_the_open_attempt_expired_issues_a_fresh_one` | `e58e8f1` | Backend-contract fix only: `start_attempt` now returns an already-open, unsubmitted attempt instead of minting a new one. This pass did not independently re-verify `quiz-player.tsx`'s mount behaviour against a live browser; correct at the API-contract level regardless of client call count, which is what actually closes the finding. |
| **H-9** | Public preview access (media/quiz/survey/assignment) ignores course published state and tenant assignment | DONE | `tests/test_h9_public_preview_boundary.py` (new, 14 tests) | `df9a2fd` | — |
| **H-15** | SSO cannot complete in the browser — `/auth/sso/callback` does not exist and the BFF routes are dead | DONE | `tests/test_sso.py` (deep-link round trip, default, off-site refusal, plus a parametrised `safe_next_path` unit test); `apps/web/e2e/sso.spec.ts` (new, 5 cases incl. axe) | `fe28409` | The server half needed no correctness fix; what was missing was the callback page and the entry button. The parked `next` is now returned as `next_path` and sanitised on both sides (`services/oidc.py::safe_next_path`) — it arrives from an anonymous query parameter and ends up as somewhere the browser is told to go. A full round trip against a **real** IdP is still untested; `tests/test_sso.py`'s fake provider at the HTTP boundary is what covers the protocol. |
| **H-16** | A tenant logo upload crashes `/login` and the admin shell for that tenant | DONE | `tests/test_tenant_users.py` (served-as-URL, no-logo 404; the existing upload test now asserts the stored key against the database rather than the response) | `cec15f8` | `GET /tenant/branding/logo` streams the object and both theme reads resolve a stored key to it; `lib/theme-assets.ts` maps that to its BFF path and drops anything it cannot vouch for. `app/error.tsx` + `app/global-error.tsx` are the boundaries whose absence turned the render throw into a whole-tenant 500 — the app had none anywhere. Verified live through the BFF (upload → theme → `/login` renders → bytes served). |
| **H-17** | Session bootstrap and rotation have no failure path | DONE | `apps/web/e2e/session-refresh.spec.ts::a transport failure never signs an admin out` (both halves: `/auth/me` aborted at the transport layer, and a products 401 whose refresh is answered 503) | `6f91538`, `417894d` | The refresh now reports three outcomes — only 401/403 ends a session; a transport failure, 5xx or unparseable 200 retries at 1s/3s/8s and leaves the session alone. The admin shell no longer treats every failure of its identity call as a sign-out. The "most busy flags have no try/finally" half was fixed in the transport rather than at forty call sites: `lib/bff-fetch.ts::unreachable` resolves a transport failure to a 503 carrying the API's own error envelope, and both `authedFetch` and the new `bffFetch` use it, so each caller's existing `!resp.ok` branch does the work. |

### Commits made by the 2026-09-03 pass

| Commit | What |
|---|---|
| `a8c0a14` | Finished the 0041/H-12 lesson-block API surface — audio-asset schemas, `LessonBlock`/`AudioAsset` model exports, `playback.mint`/`validate`'s `asset_id` rename, and the schemas/`routers/learning.py`/`dashboard.py`/`operations.py` side of the blocks cutover. Without this, `main` did not import. |
| `db9ea97` | Closed H-11's same-second suspend/reinstate race (`is_access_token_revoked` extracted and tightened to `<=`; reinstatement clears the marker instead of relying on it losing a timing race). |
| `dcd2c93` | Committed the previously-untracked `0041_lesson_blocks.py` migration — every migration `0042` onward depended on a file that was never in git. |
| `8612d67` | Regenerated `packages/api-client/src/schema.gen.ts` for H-12/H-13's docstring changes. |

### Commits made by the 2026-09-05 pass (§8 step 7)

| Commit | What |
|---|---|
| `cec15f8` | H-16 — `GET /tenant/branding/logo` streams the uploaded logo; both theme reads resolve the stored key to it; `lib/theme-assets.ts` maps it to the BFF path and refuses anything else; `app/error.tsx` and `app/global-error.tsx` added. |
| `6f91538` | H-17, first half — three named refresh outcomes with bounded transient retries, and an admin shell that only sends you to /login when the API says the session is over. |
| `417894d` | H-17, second half — `lib/bff-fetch.ts`; a transport failure resolves to a 503 envelope for both transports instead of rejecting past every `setBusy(false)`. |
| `7d1debb` | Unblocked the finance e2e: it located its row by buyer email on a shared dev database, so one dead run's leftover pending payment broke every run after it. |
| `fe28409` | H-15 — the callback page, the sign-in button, and `next_path` returned and sanitised on both sides. |

**Gate at the end of this pass.** Full API suite: green on a **fresh**
`ttli_test` (the database is created once and never dropped, so it
accumulates). Playwright: green per spec and green for the whole suite
when it is not fighting itself — see below. ruff, ruff format, mypy,
`alembic check`, api-client drift, web lint (0 errors, 4 pre-existing
warnings), typecheck and build all clean.

**Two pre-existing flakes this pass had to diagnose to trust its own gate
run**, both instances of M-31 and neither introduced here:

1. `tests/test_learning.py::test_progress_carries_structured_checks_and_a_course_roll_up`
   and `::test_dashboard_greets_the_learner_and_points_at_the_next_lesson`
   fail with `lessons_total == 4` against an expected 2. Some sibling test
   adds lessons to the seeded "Executive Leadership Certificate" course and
   does not clean up, and because `ttli_test` is never dropped the damage
   is permanent from the first run onwards. Both pass on a freshly dropped
   database. The culprit was not hunted down — it needs its own pass, and
   the durable fix is a per-run database or a truthful teardown, not
   another patched assertion.
2. The Playwright suite run in parallel exhausts the API's 5-per-minute
   per-account login limit, because several specs log in from
   `beforeEach` as well as through the form. Four specs failed on 429 in a
   full-suite run and every one of them passed alone.

## Not attempted in this pass

Everything below is unchanged from `fable5.1_review.md` and was explicitly
out of scope for this pass. Ordered using the review's own
**§8 "Suggested order of work"** (steps 7–11), which is what should be
picked up next, in this order:

~~**§8 step 7 — web session/SSO reliability**~~ — **DONE 2026-09-05**
(H-15, H-16, H-17; rows in the Findings table above).

**Next (§8 step 8 — event-loop blocking):**
- **H-5** — arq's default 300s `job_timeout` is unset; a cancelled transcode leaves `asset.state="transcoding"` forever and orphans the ffmpeg child.
- **H-14** — Argon2 password verification (~250ms) runs synchronously on the event loop with no `to_thread`.
- **M-4** — `POST /auth/sso/start` runs uncached, synchronous DNS resolution on the event loop, anonymous and unlimited.

**§8 step 9 — production-safety guard and backups:**
- **H-19** — `check_production_safety` checks a MinIO-era key, not the Garage key this repo actually commits; unchecked for staging; no live-Payfast-credentials-with-sandbox-flag check.
- **H-20** — backup is a nightly logical dump with no restore path, no restore rehearsal, and no Garage (object storage) backup at all, contradicting the ops doc's stated PITR/15-min-RPO promise.

**§8 step 10 — proxy trust and upload limits:**
- **M-2** — per-IP rate limiting trusts the first (attacker-controlled) `X-Forwarded-For` hop; every IP-keyed limit is bypassable behind an appending proxy.
- **M-3** — no request-body size limit anywhere in the upload path; clamd's 25 MiB default `StreamMaxLength` silently defeats the 500 MB bypass-size setting.

**§8 step 11 and beyond — deploy/scan/test hygiene, remaining web/docs items:**
- **M-28–M-31** — migration-before-swap ordering with no additivity check; `.trivyignore`'s ~75 exceptions all expiring on one day; the zero-skip gate not covering AV/Mailpit/ffmpeg/seed-data local skips; test-hygiene items (unordered `LIMIT 1` queries on a shared DB, tautological assertions, no `pytest-timeout`). This pass's own gate run observed one likely instance of exactly this class of debt: a single run of the full suite produced 5 additional, non-reproducing failures (an off-by-one on a shared-DB analytics count, and four rate-limit boundary assertions) that did not recur across three subsequent full/partial reruns, including a deliberate rerun of the same file combination — consistent with M-31's own description of shared-DB, unordered-query flake rather than a defect in any of this pass's fixes, but not root-caused further as it falls outside this pass's named scope.
- **H-18** — checkout shows a client-computed price (hardcoded `VAT_RATE = 0.15`) that can diverge from what is actually charged; no price shown at all for learning paths.
- **M-18–M-27** — the full web list: broken CSV export link, possible BFF path-traversal via `%2e%2e`, missing `error.tsx`/`loading.tsx` everywhere, authenticated JSON becoming browser-cacheable, orphaned pending orders on checkout retry, keyboard/AT gaps on file upload, consumer-facing copy contradicting the legal pages, unsubscribe firing on GET, dead service-worker offline fallback, and more (full list in `fable5.1_review.md` §3).
- **M-33** — the ~20-item docs-contradicts-code table (`README.md`, `06_OPERATIONS.md`, `super_smart_admin.md`, `NEXT_AGENT_BRIEF.md`, `BACKLOG.md`, `.trivyignore`, `CHANGELOG.md`).

**Flagged by name but not placed in §8's own ordering — HIGH severity, unaddressed:**
- **H-10** — re-booking a cancelled workshop session 500s (`uq_attendance_records_booking_id` fires because `_cancel_booking_row` never deletes the old `AttendanceRecord`). Not mentioned in §8's numbered steps; by severity it belongs alongside the step-7/8 items above.

**Everything in §3 MEDIUM and §4 LOW** not already named above (M-1, M-5–M-17
in full, and the complete LOW list across API/web/ops) — none of it was
attempted in this pass. The full, file:line-cited list is
`fable5.1_review.md` §3–§4; nothing here should be treated as re-verified
just because it isn't repeated in this ledger.

## Addendum — the other pass's work, and the document consolidation itself

The section below used to describe a separate, earlier remediation pass's
work as **uncommitted and out of scope**. It has since been reviewed and
committed, and the review-document consolidation this ledger itself now
represents was carried out at the same time. Recorded here rather than
rewritten into Part A above so the "what actually happened, in what order"
trail stays intact.

**The 2026-09-02-audit pass's leftover work** (`apps/api/pyproject.toml`
coverage/`unit`-marker config; `tests/test_completion.py`,
`tests/test_video_settings.py`, `tests/test_subscriptions_period_math.py`;
`services/subscriptions.py::compute_renewal_period`;
`services/workshops.py` → `services/workshops/{authoring,booking,
attendance,reporting,errors}.py`; `.trivyignore` +
`infra/docker-compose.single-vm.yml` digest pins and the `build:` stanza
removal; the BFF's `x-request-id` header forward; and the
`docs/BACKLOG.md`/`HANDOFF.md`/`STATUS.md`/`check_links.py`/`docs/archive/`
docs consolidation) was read in full against current code, exercised
(`pytest tests/test_workshops.py tests/test_completion.py
tests/test_video_settings.py tests/test_subscriptions_period_math.py
tests/test_subscriptions.py` — 71 passed; `ruff check` and `mypy` clean on
every touched Python file; `docs/check_links.py` clean), and committed in
eight scoped commits: `1f298b7`, `5bfc1c6`, `d251dda`, `41249d8`,
`ee5a499`, `2d58cf8`, `5b6f692`, `12333c5`. See Part A's M3/M5/M6/M8/M9 rows
above for what each closed. The five stray debug-log files at the repo
root (`collect.log`, `gates_output{,2,3}.log`, `pytest_full1.log`) were
deleted, not committed — they were never meant to be tracked.

**This document itself.** `TTLI_Audit_Report_2026-09-02.md` and
`fable5.1_review.md` — the two source reviews behind Parts A and B — are
now archived verbatim at `docs/archive/`, per Part A's M9 row. Every
finding either document tracked either has a row above (Part A / Part B's
Findings table) or is named in "Not attempted" below; nothing was dropped
silently. Going forward, this file is the one to update when a finding's
status changes — not the archived source reviews.
