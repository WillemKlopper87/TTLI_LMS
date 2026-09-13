# Feature delivery brief — the five launch modules (written 2026-09-13)

**For:** the agent(s) who plan, build and deliver the assessment platform,
programmes, analyst workspace, partner portal, and licensing + xAPI for the
January 2027 launch.
**Read first:** [`NEXT_AGENT_BRIEF.md`](NEXT_AGENT_BRIEF.md) §1 and §6 for
operating context and gates, then [`BACKLOG.md`](BACKLOG.md) for the live
queue. This brief does not replace either; it tells you how to turn the five
specs into shipped, evidenced software without repeating the mistakes the
codebase already paid for.

**The specs (approved approach, 2026-09-11, PR #24):**

| Module | Spec | Screens |
|---|---|---|
| Assessment platform | [spec](superpowers/specs/2026-09-11-assessment-platform-design.md) | [mockups](https://claude.ai/code/artifact/19bc9788-01ad-49a9-a157-79866b6ee492) |
| Programmes | [spec](superpowers/specs/2026-09-11-programmes-design.md) | [mockups](https://claude.ai/code/artifact/3e632814-117d-4193-828f-fa8c4cbc59e0) |
| Analyst workspace | [spec](superpowers/specs/2026-09-11-analyst-workspace-design.md) | [mockups](https://claude.ai/code/artifact/a16899b8-ceb6-43d7-bffd-f12c587d88e6) |
| Partner portal | [spec](superpowers/specs/2026-09-11-partner-portal-design.md) | [mockups](https://claude.ai/code/artifact/e55e82d9-08c6-4655-823e-f93aa8624cc6) |
| Licensing + xAPI | [spec](superpowers/specs/2026-09-11-facilitator-licensing-xapi-design.md) | [mockups](https://claude.ai/code/artifact/cd6bc277-b521-4804-a559-3f365c1c9c25) |

Customer context: [`CUSTOMER_SESSION_2026-09-11.md`](CUSTOMER_SESSION_2026-09-11.md)
and the brochure extract [`source/05_ttli_services_brochure_2026.md`](source/05_ttli_services_brochure_2026.md).

---

## 1. Entry conditions — do not start before these hold

1. **Sprint 1 hardening is done** (`BACKLOG_2026-09-11.md` P1: F1/F2/F9, T10, T11, T12). The
   governing rule there is "no new product features until Sprint 1 is complete". It is
   not negotiable and it is not yours to relax. Verify with the BACKLOG rows, not by
   reading this document.
2. **Item content exists for at least one instrument.** Without the ENGQ's 50 items and
   nine elements, the assessment platform has nothing to demo. Ask for the ENGQ first;
   build the template shell in parallel, but the UAT demo needs the real instrument.
3. **The customer has answered the questions that change the data model.** These are
   listed per module in §5. Anything else can be assumed with a default and revisited.

If (1) is not true, work the hardening queue. If (2) or (3) is not true, build the
first slice anyway (it is model + service + tests, no content needed) and put the
question in the PR description so the owner sees it.

**Staffing reality, stated once here because it changes what "on track" means from
day one:** the plan in §3 needs two engineers from week 5 or the January date slips
or scope drops. If you are reading this alone, decide now which cut you are taking
(see §3's staffing note) and say so in BACKLOG before you start slice A.1, not when
you notice you're behind in December.

## 2. How to think about this work

These are the principles behind every decision in the specs. When a spec is silent,
apply them; when a spec contradicts them, the principle wins and you note the
deviation in the PR.

- **Extend, never clone.** Assessments are surveys with a template/instance split, not
  a forms subsystem. Programmes are learning paths with typed steps, not a workflow
  engine. Licensees are organisations with a licence row, not tenants. Analysts are a
  role plus an engagement row. Every time you find yourself creating a parallel
  concept (a second response table, a second progress tracker, a second permission
  system), stop and find the existing seam.
- **The server decides.** Completion, thresholds, windows, seat limits, engagement
  validity: all evaluated in the service layer, never trusted from the client. This
  is the codebase's founding rule (REQ-BYPASS) and the new modules inherit it.
- **Privacy floors are invariants, not features.** `minimum_group_size` on every
  aggregate and every bucket, the one-subject CHECK on responses, no `user_id` on
  anonymous rows, engagement windows checked on every read. Write the test for the
  invariant before the feature that could break it. A privacy regression here has a
  human cost; treat it like a payment bug.
- **Every read of sensitive data is audited.** Analyst results, free text, exports,
  practitioner views of their clients' individual rows. Use `services.audit.record`
  with row counts. If an endpoint returns identified or free-text data and does not
  audit, it is not done.
- **`tenant_id` on every new table, RLS forced, `app_user` grants asserted.** The
  migration test for RLS-forced tables must include yours. This is where migrations
  `0008`, `0020` and `0022` came from; do not add a `0046`-style regret.
- **Vertical slices, thin and demoable.** Each PR is one behaviour end to end: model,
  migration, service, router, generated client, one screen, tests at the seam, a
  BFF smoke. Never a "models PR" then a "routers PR" then a "UI PR"; those merge
  green and demo nothing.
- **Commercial questions block, technical ones do not.** Pricing units, who bills
  whom, review gates: ask and wait. Column names, page layouts, batch sizes: decide,
  document in the PR, move on.
- **Match what is there.** Same admin shell, same tokens, same `.btn`/`.tag`/
  `.table-wrap` classes, Newsreader/Archivo/Plex Mono. The mockups were built from
  the real `globals.css`; if a screen needs a new component, add it to `components/`
  (there are two files there today, which is a known gap) rather than a fourth copy
  of an inline card.
- **Feature-flag each module.** Add a `KNOWN_FLAGS` entry per module
  (`assessments`, `programmes`, `partner_portal`, `licensing`, `xapi`). Off by default
  in production until UAT signs the module off. Existing data is unaffected by a
  flag; only new actions are refused while off. This is how the platform already
  handles subscriptions and workshops.

## 3. Order and dependency

```
Sprint 1 hardening ─┐
                    ├─► A. Assessment platform (wk 1–4)
                    │        ├─► B. Programmes (wk 5–7)        ─┐
                    │        └─► C. Analyst workspace (wk 5–7) ─┤
                    │                                            ├─► D. Partner portal (wk 8–10)
                    └─► E. Licensing + xAPI (wk 5–10, parallel) ─┘
                                                                  └─► UAT, content load, buffer (wk 11–13)
```

- **A first, alone.** It is the largest and the others read its tables. One engineer,
  four weeks, no parallel feature work on it.
- **B and C together from week 5** if there are two engineers; B then C if there is
  one. They touch different tables and different screens.
- **E can start any time after Sprint 1 hardening plus §6's permission migration**
  (the only thing it depends on). If a second engineer exists earlier than week 5,
  they start E once that migration is merged — it is a slice 0 in front of A, not a
  reason to wait for A itself.
- **D last.** It is mostly a shell over A, C and E, and its model deltas
  (`parent_organisation_id`, `assessment_licences`, `partner_profiles`) are small.
  Building it first would mean building it twice.
- **Week 11 onward is not slack.** It is UAT with the customer's real instruments,
  loading fifteen workshops and the LWI course, and the security-officer review of
  the analyst and partner isolation. Plan for it.

Staffing honesty: 13 engineer-weeks after a 3-week hardening sprint, against a
January 2027 date, needs two engineers from week 5. With one, drop D's practitioner
run wizard to a TTLI-only flow and ship licensing without the xAPI worker; say so in
BACKLOG when you make the call, do not discover it in December.

## 4. The delivery loop, per slice

For every slice, in this order. It is the existing per-pass gate from
`NEXT_AGENT_BRIEF.md` §6 with the feature-specific steps added.

1. **Plan the slice** with `superpowers:writing-plans` from the spec section it
   implements. Plans live in `docs/superpowers/plans/`. One plan per module, sliced;
   not one plan per PR.
2. **Write the invariant tests first**, at the service seam, in the module's test
   file (`tests/test_assessments.py`, `tests/test_programmes.py`,
   `tests/test_engagements.py`, `tests/test_partners.py`, `tests/test_licences.py`,
   `tests/test_xapi.py`). Use the shared `conftest.py` fixtures; do not add a 26th
   private `client` fixture.
3. **Migration**: next number in sequence, one per slice, with the RLS/grant block,
   the downgrade, and the `alembic check` round trip. Update the migration-count
   claims in README/NEXT_AGENT_BRIEF/BACKLOG in the same commit; CI's docs gate will
   fail you otherwise.
4. **Service, then router, then `npm run generate`** in `packages/api-client`. The
   drift gate is real. Web code calls the BFF through `lib/authed-fetch.ts`.
5. **One screen**, built from the mockup, using existing classes. Public respondent
   pages (`/a/[token]`) get no layout chrome and must pass axe at phone width.
6. **Playwright spec for the journey** in `apps/web/e2e/`, wired into the
   `authenticated-e2e` job with the `REQUIRE_API_E2E` hard-fail block. Seed any new
   least-privilege accounts through `scripts/seed_e2e_accounts.py`, nowhere else.
7. **Live smoke through the BFF at :3010** after restarting both servers. Every real
   bug this project shipped was found there, not in pytest.
8. **PR**: conventional prefix (`feat(assessments):`), spec section in the body,
   the open question if there is one, the five required checks green, squash merge.
   Evidence (run URL, screenshot, timing) goes in the BACKLOG row for the slice.
9. **Tag a UAT build** at the end of each module (`v0.10.0-uat-assessments` and so
   on) with a CHANGELOG heading, so the customer can name what they tested.

Definition of done for a slice: tests at the seam, migration round-trips, client
regenerated, screen smoke-tested live, e2e in CI, audit events where data is
sensitive, flag respected, BACKLOG row updated. Not "code merged".

## 5. Per module: slices, first PR, exit demo, blocking questions

### A. Assessment platform

Slices, in order:

1. `assessment_templates` + `assessment_template_questions` with kinds, versions,
   publish/retire; question-bank copy. First PR of the whole programme. No UI beyond
   the admin list.
2. `assessment_instances` with `question_snapshot`, draft tailoring (audited edits,
   freeze on open), pre/post pairing reusing the survey CHECK/partial indexes.
3. Invitations and the public respond page for `org_survey` (token, single use,
   rate limit, `level` + `department`). Anonymous first; identified after.
4. Results service: per-element aggregates, level and department cuts, floor gating
   per bucket, free text above the floor. Reuse `services.survey.aggregate_results`
   and `aggregate_delta`; extend, do not fork.
5. Monitor page and results page in `/admin` from the mockups. CSV/JSON export,
   streamed and audited.
6. `assessment_subjects` + rater groups for `multi_rater`; subject reports with
   self-versus-others and the post/pre delta.
7. `individual` kind (subject is respondent) and `external_instrument` kind
   (`assessment_subject_results`, upload through the antivirus path).
8. Product link so an instrument can be sold through the existing order path.

Exit demo: author the ENGQ from the customer's items, run it for a demo
organisation with generated links, submit 20 responses across three levels, watch
the Legal bucket stay withheld, export the CSV, open the level heatmap.

Blocking before slice 4: which instruments are anonymous versus identified
(assumed: ENGQ, PSA, TCA anonymous; LSA, ICA identified; 360 self/manager identified,
peers/reports anonymous). Blocking before slice 2: how much tailoring is allowed
(assumed: reword, drop, add from bank; no new sections). Not blocking: respondent
form option A or B (build A, one section per screen; B is a layout change later).

### B. Programmes

1. Migrate `learning_path_courses` to `learning_path_steps` with `kind='course'`;
   path readiness and publish tests unchanged. This migration is the risk; do it
   alone and first.
2. Add step kinds `workshop`, `assessment`, `one_on_one`, `document` with the
   exactly-one FK constraint and `evaluation_role` on assessment steps.
3. `cohorts` (finally, P17a) with the XOR parent, `cohort_steps`, `cohort_members`.
   Run creation pre-creates paired assessment instances and consumes seats.
4. Completion engine: `workshop_attended`, `assessment_complete`,
   `one_on_one_attended` rules; path enrolment completes; programme certificate.
5. Run board in `/admin`, client dashboard Programmes tab, learner home card.

Exit demo: create an LWI run for a demo organisation with 6 participants, see both
360s created and paired, book a workshop, mark attendance, close the post 360, one
participant earns the certificate, one is blocked with the specific unmet step named.

Blocking before slice 4: attendance rule for the certificate (assumed: every
workshop, with facilitator-marked exemption). Not blocking: whether self-paced
modules gate the next workshop (assumed: no).

### C. Analyst workspace

1. `analyst` role and the three permissions (`assessment:analyse`, `report:submit`,
   `report:review`); `assessment_engagements` with the window and the policy check.
   Test matrix: no engagement, expired, revoked, instance not closed, admin bypass.
2. Analyst read endpoints with audit-on-read and watermarked exports.
3. `reports` state machine and `report_attachments` through antivirus; immutability
   after accept; version bump on resubmit; release as a separate step.
4. Owner inbox at `/admin › Partners` (built here, in C, hosted in D's admin
   namespace — D's own slices do not recreate it, they only add the practitioner
   reports that land in the same inbox); ESP templates for assigned, submitted,
   returned, accepted, released.
5. Analyst pages on the partner shell (§D slice 1 provides the shell; build C's
   pages against a minimal shell if D has not started).

Exit demo: assign an engagement with a 3-day window, analyst reads rows and exports
(audit log shows both with counts), submits a report, owner returns it, analyst
resubmits, owner accepts and releases, client admin downloads; then the window
expires and the analyst's list is empty.

Blocking before slice 2: does the analyst see prior runs of the same instrument for
the same client (assumed: only if engaged on them). Blocking before slice 3:
attachment types (assumed: PDF, PPTX, PBIX; scanner coverage to be verified for the
last two, fall back to PDF only if not).

### D. Partner portal

1. `/partner` shell: top bar, membership-driven nav, redirect rules (`/admin` for a
   non-staff partner → `/partner`; `/partner` for a staff user → `/admin`). Empty
   home with explanation. Playwright: a partner can never load an admin route.
2. `partner_profiles` and onboarding: MFA, agreement acceptance with reference and
   timestamp, registration number encrypted; `status` gate on every licence and
   engagement.
3. `organisations.parent_organisation_id` and `kind` values; client creation by
   partner (assumed allowed) with TTLI visibility of the tree.
4. `assessment_licences` with runs and `requires_ttli_review`; practitioner run
   wizard reusing A's wizard components; report release honouring the review gate.
   Practitioner reports submitted here land in C's owner inbox (`/admin ›
   Partners`) — no new inbox to build, just the `requires_ttli_review` routing.
5. Admin Partners section: list, invite, grant licence, suspend (freeze, not
   delete). The report inbox from C.4 lives on this same page; this slice adds the
   partner roster and licence controls around it.

Exit demo: invite a practitioner, they cannot open `/admin`, they complete
onboarding, run an ENGQ for a client they created, submit the report, TTLI reviews
and it is released; suspend them and confirm immediate lockout with data intact.

Blocking before slice 3: whether partners create clients themselves (assumed: yes).
Blocking before slice 5: what suspension does to clients (assumed: freeze for TTLI
review; reassignment later).

### E. Licensing + xAPI

1. `licences` (course XOR learning path) and `licence_seat_grants`; seat pool from
   licences in `services.organisations.assign_seat`; refusal at limit and outside
   term; expiry keeps existing access.
2. Licensee permission matrix test: no `course:*`, no other organisations,
   watermark carries the organisation slug.
3. Certificate rendering with the licensee logo and "delivered by" line.
4. Usage and royalty report with CSV.
5. `organisation_lrs_configs` + `xapi_outbox`; statement builder with golden tests
   per event; outbox written in the same transaction as the event.
6. arq worker: batch, backoff, per-org delivery status; admin/partner settings page
   with test connection and the delivery log; stub LRS in tests.

Exit demo: grant a 3-seat licence, enrol three learners, refuse the fourth, one
completes and gets the co-branded certificate, statements land in the stub LRS
including the `earned` one, the usage report shows the seats and royalty.

Blocking before slice 4: royalty semantics (assumed: informational percentage, not
an invoice source). Not blocking: workshop attendance as an xAPI verb (assumed: off
at launch).

## 6. Cross-cutting items to do once, early

- **Permissions — slice 0, before any module's slice 1.** Add all new permission
  strings in one migration (`assessment:author`, `assessment:run`,
  `assessment:analyse`, `report:submit`, `report:review`, `cohort:run`), seed them
  onto Admin, and the subset onto Content author and Facilitator. This is the one
  migration every module reads, including E if it starts in parallel with A — do it
  first and merge it before any module's slice 1 branches, so nobody is blocked
  mid-slice waiting on it. Partners get capability through membership, licences and
  engagements, never through admin permissions.
- **Feature flags**: the five `KNOWN_FLAGS` entries, in A's first PR.
- **ESP templates**: assessment invitation and reminder, engagement assigned, report
  submitted/returned/accepted/released, licence expiring. One PR, plain text, deep
  links, no data in the body.
- **Storage**: reports and vendor instrument PDFs go to the private container via
  the existing antivirus scan; signed short-lived URLs for download. No new bucket.
- **Audit**: one helper for "sensitive read with row count" so every module calls the
  same function and the audit log reads the same way.
- **Docs gate**: every migration bumps the counts in the three documents CI checks.
  Do this in the same commit as the migration, every time.

## 7. Traps I expect

- **Forking the survey code** because assessments "feel different". The tables mirror
  `surveys` on purpose. If the survey service needs a parameter, add the parameter.
- **Computing aggregates in SQL for speed** and losing the per-bucket floor. Answers
  are JSONB arrays by design (0013); keep Python-side aggregation and add an index
  later if it is ever slow at 500 responses. It will not be.
- **Letting the partner shell reuse admin permission checks** "just for the list
  endpoints". The isolation is the product. Membership and engagement are the only
  keys.
- **Treating the cohort migration as a schema-only change.** `Enrolment.cohort_id` is
  already nullable and referenced in docs; check what the data model doc §13 #5
  promised before you name things.
- **Building the xAPI worker before the outbox.** The outbox row in the same
  transaction as the learning event is the correctness guarantee; the worker is just
  delivery.
- **Putting item content in code or seeds.** Instruments are the customer's IP and
  arrive through the admin authoring screens, versioned. Demo seeds may hold a
  clearly synthetic 9-item survey, never the ENGQ.
- **Skipping the tag.** The customer cannot test "main". Tag each module's UAT build.

## 8. Reporting back

- BACKLOG rows per slice with evidence; CHANGELOG heading per tag; `NEXT_AGENT_BRIEF.md`
  §1 state table refreshed when a module ships. No new status documents.
- When a customer answer changes an assumption in §5, edit the spec, note it in the
  PR, and move on. Do not maintain a parallel decisions file; the spec is the record.
- If you find yourself more than a week behind the plan in §3, say so in the BACKLOG
  header and propose the cut (see the staffing note). Silence is the only failure
  mode that cannot be recovered in January.
