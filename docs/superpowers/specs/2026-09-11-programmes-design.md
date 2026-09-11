# Programmes (entry paths) — design

**Date:** 2026-09-11 · **Status:** draft for review · **Source:** TTLI services brochure pp.7–27 ([extract](../../source/05_ttli_services_brochure_2026.md)); customer instruction 2026-09-11 that these are launch services.
**Depends on:** [assessment platform](2026-09-11-assessment-platform-design.md) (assessment steps), existing workshops and learning paths. **Used by:** [partner portal](2026-09-11-partner-portal-design.md) (licensed practitioners run programmes for their clients).

## 1. Goal

Sell and run TTLI's five entry paths as first-class programmes on the
platform, so a client organisation buys "Lead with Intent" and the platform
carries every phase: the 360, the one-on-ones, the four workshops, the second
360 and the closing one-on-ones, with progress visible to TTLI, the
facilitator and the client.

| Path | Shape (brochure) | Programme steps |
|---|---|---|
| 1 Engagement Analysis | finalise questionnaire → administer → solutioning | `assessment` (ENGQ) → `one_on_one` (results debrief) → optional `workshop` |
| 2 Lead with Intent | 8 phases | `assessment` (360LWIA pre) → `one_on_one` → 4 × `workshop` → `assessment` (360LWIA post) → `one_on_one`; plus the LWI `course` for self-paced content |
| 3 Cultivate with Intent | 8 phases | as Path 2 with 360CWIA and the CWI course |
| 4 Strategy | 3 phases: Cultivate, Clarify, Cascade | 3 × `workshop` (leadership-team sessions) with `document` deliverables |
| 5 Essential Skills (ESWS) | 15 modular workshops in 4 quadrants | client picks any subset of 15 `workshop` steps; optional `assessment` (LSA/ICA) before and after |

Not in scope: authoring the workshop content itself (that is catalogue
intake), automatic scheduling of facilitators (manual booking as today).

## 2. Design: learning paths get typed steps and runs

`learning_paths` today is an ordered list of courses. A programme is the
same thing with more step types and a scheduled run per client. Two
changes, no new subsystem.

### 2.1 Typed steps

```
learning_path_steps              (replaces learning_path_courses; migrated 1:1 as kind='course')
  id, learning_path_id, position, kind ('course'|'workshop'|'assessment'|'one_on_one'|'document'),
  title, phase_label (e.g. "Phase 1: Discovery"), optional bool (ESWS pick-list),
  course_id | workshop_id | assessment_template_id (exactly one, by kind; NULL for document),
  evaluation_role ('pre'|'post'|NULL)  -- assessment steps: pairs the post to the pre
  completion_rule jsonb                 -- course: existing rules; workshop: attendance;
                                        -- assessment: instance closed (and subject complete for 360s);
                                        -- one_on_one: booking attended; document: uploaded + accepted
```

The existing `learning_path_courses` rows become `kind = 'course'` steps; the
current learner path UI keeps working because course steps are unchanged.

### 2.2 Programme runs

A run is the cohort concept the data model already resolved (02 §13 #5: a
scheduled run of a course or a path, with dates, capacity and a facilitator).
This spec makes that table real with a programme's needs:

```
cohorts                          (02 §13 #5, P17a)
  id, tenant_id, learning_path_id XOR course_id, organisation_id (nullable: public cohorts),
  title, starts_at, ends_at, capacity, lead_facilitator_id,
  status ('planned'|'active'|'completed'|'cancelled'), timestamps

cohort_steps                     (the run's instantiation of each path step)
  id, cohort_id, step_id, scheduled_for (nullable), status ('pending'|'scheduled'|'in_progress'|'done'|'skipped'),
  workshop_session_id | assessment_instance_id (nullable, filled when scheduled/created)

cohort_members
  id, cohort_id, user_id, path_enrolment_id, role ('participant'|'observer'), joined_at
```

Creating a run for an organisation: pick the path, the organisation, the
participants (from org members or CSV, consuming seats as today), and the
lead facilitator. The platform pre-creates `cohort_steps` for every path
step; for `assessment` steps it creates the assessment instance for that
organisation with the participants as subjects (360s) or as invitees (ENGQ,
LSA, ICA), so the Phase 1 360 exists the moment the run does and the Phase 7
360 is created paired to it. `workshop` steps are scheduled by booking a
workshop session and linking it. `one_on_one` steps are one workshop session
of the existing `one_on_one_coaching` type per participant, booked from the
facilitator's availability. `optional` steps (ESWS) are included or skipped
per run at creation.

### 2.3 Progress and completion

A participant's `path_enrolment` completes when every non-skipped step's
completion rule is met for them, evaluated server-side by the existing
completion engine extended with three rule types: `workshop_attended`,
`assessment_complete`, `one_on_one_attended`. Programme certificates use the
path's certificate template; a 360 post/pre delta appears on the
participant's programme report, and the organisation dashboard shows run
progress per phase with the manager-visibility rules unchanged.

## 3. Who runs programmes

- **TTLI** runs its own client programmes from `/admin` (Programmes section:
  paths, runs, step scheduling, progress).
- **Licensed practitioners** run programmes for their own clients from
  `/partner` when their licence covers the path (the licence model in the
  licensing spec gains `learning_path_id` as an alternative to `course_id`;
  seats are per participant). The practitioner is the lead facilitator and
  books their own one-on-ones and workshops.
- **Client organisations** see the run, the schedule and progress on their
  dashboard; participants see their next step in the learner home.

## 4. API surface (v1)

```
POST   /learning-paths/{id}/steps                   course:edit    (typed step; replaces add-course)
PATCH  /learning-paths/{id}/steps/{stepId}           course:edit
POST   /cohorts                                      cohort:run     (path or course + organisation + participants)
GET    /cohorts?organisation_id=                     cohort:run | org admin
POST   /cohorts/{id}/steps/{stepId}/schedule         cohort:run     (links a workshop session or books one-on-ones)
POST   /cohorts/{id}/steps/{stepId}/skip             cohort:run
GET    /cohorts/{id}/progress                        cohort:run | org admin (aggregate) | lead facilitator
GET    /me/programmes                                 learner (next step, schedule)
```

New permission `cohort:run` for Admin and Facilitator; partners get it
through their licence, not the role.

## 5. Web

Admin: Programmes section with path editor (typed steps, phase labels,
optional flag), run creation wizard, run board (phases as columns, steps as
cards with schedule/skip), progress per participant. Partner: same run board
scoped to their clients. Organisation dashboard: "Programmes" tab with phase
progress. Learner home: "Your programme" card with next step and dates.

## 6. Testing

- Migration: every `learning_path_courses` row becomes a course step; path
  readiness and publish rules still pass.
- Run creation: assessment instances pre-created and paired; seats consumed;
  optional steps skippable.
- Completion engine: the three new rule types; a participant who missed a
  workshop cannot complete; 360 post delta rendered.
- Playwright: create an LWI run for an organisation → Phase 1 360 open →
  book a one-on-one → schedule workshops → close post 360 → participant sees
  certificate and delta.

## 7. Size and sequencing

M–L, about three weeks: one for typed steps and the cohorts table (P17a),
one for run creation and scheduling, one for the completion rules, run
board and learner view. Sits after the assessment platform and can overlap
with the analyst workspace. Revised January 2027 programme, after the
three-week hardening sprint:

| Weeks | Work |
|---|---|
| 1–4 | Assessment platform |
| 5–7 | Programmes (this spec) · Analyst workspace in parallel |
| 8–10 | Partner portal · Licensing (course + path licences) · xAPI |
| 11–13 | Buffer, UAT with LWI content, ESWS and instrument content loading |

This is roughly 13 engineer-weeks after hardening, which needs two engineers
from week 5 or the buffer disappears. Content (courses, workshops, items for
seven instruments) is the customer's critical path, not engineering's.

## 8. Open items for the customer

- Which ESWS workshops are delivered live only, and which have or will have
  self-paced content (affects whether they are `workshop` or `course` steps).
- Whether Strategy (Path 4) should be on the platform at launch or remain a
  consulting engagement with documents only.
- Standard durations and facilitator counts per workshop, for capacity.
