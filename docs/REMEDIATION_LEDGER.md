# Remediation ledger — `fable5.1_review.md` pass (2026-09-03)

This is the closing record for the remediation pass driven by
[`fable5.1_review.md`](../fable5.1_review.md) (dated 2026-09-03, reviewed
`main` at `10e759f` plus that session's uncommitted working tree). Eight
workstreams ran ahead of this one — C-1, C-3, H-11, H-12, H-13, the money
findings (H-1–H-4), and learning-integrity (C-2, H-6, H-7, H-9, and H-8 as a
side effect) — each committing its own fix directly to `main`. This
workstream is the final verification and ledger: it did not redesign or
redo any of those fixes, only (1) ran the full gate sweep
(`scripts/gates.sh`), (2) fixed the integration gaps the sweep surfaced
between those eight independently-committed workstreams' work (including
work two of them had left uncommitted in the working tree), and (3) records
the aggregate state below.

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

### Commits made by this pass

| Commit | What |
|---|---|
| `a8c0a14` | Finished the 0041/H-12 lesson-block API surface — audio-asset schemas, `LessonBlock`/`AudioAsset` model exports, `playback.mint`/`validate`'s `asset_id` rename, and the schemas/`routers/learning.py`/`dashboard.py`/`operations.py` side of the blocks cutover. Without this, `main` did not import. |
| `db9ea97` | Closed H-11's same-second suspend/reinstate race (`is_access_token_revoked` extracted and tightened to `<=`; reinstatement clears the marker instead of relying on it losing a timing race). |
| `dcd2c93` | Committed the previously-untracked `0041_lesson_blocks.py` migration — every migration `0042` onward depended on a file that was never in git. |
| `8612d67` | Regenerated `packages/api-client/src/schema.gen.ts` for H-12/H-13's docstring changes. |

## Not attempted in this pass

Everything below is unchanged from `fable5.1_review.md` and was explicitly
out of scope for this pass. Ordered using the review's own
**§8 "Suggested order of work"** (steps 7–11), which is what should be
picked up next, in this order:

**Next (§8 step 7 — web session/SSO reliability):**
- **H-15** — SSO cannot complete in the browser (`/auth/sso/callback` doesn't exist; the BFF routes are dead).
- **H-16** — a tenant logo upload with a bare storage key crashes `/login` and the admin shell for that tenant (no `remotePatterns`, no `error.tsx`).
- **H-17** — session bootstrap/rotation has no failure path (`postRefresh` has no try/catch, the rotation timer doesn't reschedule on rejection, most `busy` flags have no `finally`).

**§8 step 8 — event-loop blocking:**
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

## Uncommitted, out-of-scope work left in the working tree

A separate, earlier remediation pass against `TTLI_Audit_Report_2026-09-02.md`
(a different, prior audit — its own M2/M3/M5/M6/M8/M9 items, not this
ledger's C-/H- findings) left real, correct-looking but **uncommitted**
work sitting in the working tree throughout this run:
`apps/api/pyproject.toml` (coverage config + a `unit` marker),
`apps/api/tests/test_completion.py`/`test_video_settings.py`/
`test_subscriptions_period_math.py` (new pure-function unit tests),
`apps/api/src/services/subscriptions.py` (a pure-function extraction those
tests exercise), `apps/api/src/services/workshops/` (the `services/
workshops.py` → package split, `workshops.py` itself deleted on disk),
`.trivyignore` and `infra/docker-compose.single-vm.yml` (digest pins + a
`caddy`/`postfix-relay` CVE review), `apps/web/app/api/bff/[...path]/
route.ts` (forwarding the `x-request-id` response header), and
`docs/BACKLOG.md`/`HANDOFF.md`/`STATUS.md`/`check_links.py` plus
`docs/archive/` (docs consolidation, including the migration-range check
this pass's `c24dbeb` predecessor already relies on). None of it belongs to
any of this ledger's named findings, so per this workstream's scope
boundary ("if you discover you need to change a shared file another
workstream owns, note it — don't edit it") it was left exactly as found:
not committed, not reverted, not evaluated for correctness beyond what was
needed to confirm it doesn't conflict with this pass's own changes (it
doesn't — no file overlap except `apps/api/src/services/subscriptions.py`,
which this pass's changes never touch). Whoever owns that pass should
review and commit or discard it. Also left in place, for the same reason:
five stray debug-log files at the repo root (`collect.log`, `gates_output
{,2,3}.log`, `pytest_full1.log`) from that same interrupted session, which
should have gone to a scratchpad rather than the repo — harmless (untracked,
`git status` noise only) but worth a manual cleanup.
