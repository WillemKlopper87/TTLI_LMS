# What next — synthesis of the external critique against actual state

**Written:** 2026-08-28. Source: `latest_critique.md` (an independently produced
review), cross-checked against the live codebase, `docs/BACKLOG.md`, and this
session's own verified findings, then reconciled into one driving list. This
file is a decision aid, not a new status log — the durable record stays
`docs/BACKLOG.md`; the "new backlog items" section below is what should be
folded into it.

## Evaluation of the critique

Spot-checked eight of its specific, falsifiable claims (file line counts for
six files, the inline-style count, the `cohort_id` model comment, the CSP
citation, the GitHub Actions pinning claim) — every one was exact, including
line numbers. It is reliable. Two corrections against it and against this
session's own earlier critique:

- **CI does collect coverage.** `pytest --cov=src --cov-report=term-missing`
  runs in `ci.yml:157`. The critique's "no enforced threshold" framing is the
  accurate one — coverage is measured, nothing fails the build on it. An
  earlier claim in this session that coverage wasn't measured at all was
  wrong.
- **The critique doesn't name the Sentry gap precisely.** `SENTRY_DSN` is
  *required* to boot in production (`check_production_safety`), but
  `sentry_sdk` isn't a dependency and is never initialized anywhere in
  `apps/api/src`. `docs/BACKLOG.md`'s O1 already captures this exactly
  ("Sentry DSN is a config flag only") — so this is tracked, just worth
  keeping sharp: the guard makes the gap look closed when it isn't.

Most of the critique maps directly onto existing `docs/BACKLOG.md` rows. Six
things in it are genuinely **not** currently tracked anywhere and should
become new backlog items (see below).

## Already done or in flight — do not re-plan these

- **P9 (survey analytics)** — all three phases shipped and CI-green as of
  `2903a60`: privacy-gated results/CSV, pre/post pairing with a delta report,
  reusable question banks.
- **T1–T4** (CI restore, P9 verification against real services, authenticated
  browser journeys made a required CI gate, docs refresh) — done, `3ebfcf7`.
- **T6 slice 1** — the quiz-timeout `react-hooks/set-state-in-effect` fix,
  which surfaced and fixed a real bug (the server's time-limit check had zero
  tolerance for network latency, so the client's own auto-submit-at-zero
  request was rejected 100% of the time). CI-green, `7f0a43f`. ESLint warnings
  now 52, not 53. This is exactly the critique's own Tranche 1 pilot pattern,
  already proven on a real file — continue the same slice-by-slice approach
  rather than restarting it as a fresh "Tranche 1."

## New backlog items the critique surfaced (not currently in `docs/BACKLOG.md`)

These should be added as new rows, not folded silently into existing ones —
each is independently scoped work:

1. **Large-module decomposition.** `services/workshops.py` (1,358 lines),
   `services/enrolment.py` (1,026), `routers/assessment.py` (987),
   `services/learning_paths.py` (803), `services/orders.py` (781),
   `routers/auth.py` (682) on the backend; `admin/workshops/page.tsx` (1,085),
   `lesson-activity-panel.tsx` (1,054), `checkout/page.tsx` (581) on the
   frontend. Real change-risk, not cosmetic — but per the critique's own
   caution, a smaller file is only a win if the transaction/permission
   invariant stays easy to find, so this wants tests characterized *before*
   any extraction, not after.
2. **Cohort lifecycle.** `Enrolment.cohort_id` (`models/learning.py:59`) is an
   intentional nullable placeholder with no table behind it. Needs a real
   decision first — is a cohort a course run, or can one span courses? — before
   any schema work, per the critique's own caution against cementing the
   current shape by accident.
3. **Unified gradebook / achievement model.** Quiz attempts, assignments,
   surveys, completion, and credentials each carry their own grading and
   reporting logic today with no shared model for weighting, rubrics, manual
   grading + moderation, or transcript export.
4. **Competency / skills framework.** Learning paths exist; nothing connects
   a completed course to a role requirement or a skill-gap report. The
   critique argues this is higher enterprise value than P11 (AI insights) —
   worth weighing against P11's position in the existing order.
5. **Interoperability strategy decision.** SCORM is `DECIDED-NO` (R12), ASR is
   `BLOCKED (policy)` (R11) — but xAPI, LTI 1.3, HRIS sync, bulk history
   import, and completion webhooks have no decision recorded at all. This is
   a documentation/decision task, not a build task, and it's cheap to close.
6. **GitHub Actions commit-SHA pinning.** `ci.yml` uses mutable tags
   (`actions/checkout@v4`, etc.) throughout. Small, mechanical, worth doing
   opportunistically rather than as its own tranche.

## Reconciled priority order

The critique's 12-item order and `docs/BACKLOG.md`'s existing P/O/R/B
structure agree far more than they conflict. Collapsing them, and accounting
for what's already shipped:

**Now (in flight, cheap, no external dependency):**
1. Finish T6 (O7) — continue the same slice-by-slice `set-state-in-effect`
   cleanup; each slice so far has been small and has caught a real bug.
2. Wire Sentry for real (closes O1's most misleading half in hours, not days).
3. Document the interoperability decision (new item 5 above) — pure writing,
   no code risk, closes an open enterprise-sales question.

**Next (bounded, no external blocker, meaningfully de-risks everything after):**
4. Typed API facade pilot on one bounded domain (critique's Tranche 1 proper,
   as opposed to T6's warning-by-warning sweep) — question-bank is the
   critique's own suggested pilot and is recently-built with existing
   coverage to protect.
5. Module decomposition (new item 1), starting with whichever hotspot is
   about to be touched by other work anyway (workshops, if P16 or credit
   logic changes are next; assessment, if P9 phase work continues).
6. POPIA data-subject workflows (O3) — this is the one item in this whole
   list with real legal exposure attached, not just tech debt. Do not let it
   drift to the bottom of a feature-depth list.

**Then (genuine product depth, no blocker but real design work):**
7. Departments / organisational hierarchy (P8).
8. Cohort lifecycle (new item 2) — needs the course-run-vs-spans-courses
   decision first.
9. Unified gradebook (new item 3).
10. Learner search / notification centre / preference centre (P15).
11. Competency and skills framework (new item 4).

**Blocked on infrastructure the code can't provide:**
12. Observability completion, backups + restore drill, staging + IaC, load
    testing (O1 remainder, O2, O11, O12) — all genuinely blocked on B3 (Azure
    environment) for the parts that need real infra; the backup/restore drill
    specifically does not need to wait for B3 and could move up if a target
    Postgres exists to drill against.

**Blocked on people outside engineering, not sequenced further:**
13. B1 (decision register sign-off), B2 (VAT position), B4 (Payfast prod
    creds), B5 (content inventory), B6 (brand sign-off), B8 (Information
    Officer registration).

**Deliberately last:**
14. P10 (certificate design), P11 (AI insights — correctly gated behind
    R9/feature flags and O1/observability being real first).

## Immediate next action

Continue T6 (item 1 above) — it's already proven itself as low-risk and
high-signal (one slice in, one real bug found and fixed, CI green each time).
Once the warning count is meaningfully down or exhausted, move to the typed
API facade pilot (item 4) using the same question-bank domain the critique
independently suggested.
