# Assessment platform — design

**Date:** 2026-09-11 · **Status:** draft for review · **Source:** [CUSTOMER_SESSION_2026-09-11.md](../../CUSTOMER_SESSION_2026-09-11.md) §3.2
**Depends on:** nothing new. **Depended on by:** [analyst workspace](2026-09-11-analyst-workspace-design.md).

## 1. Goal

Replace the customer's MS Forms company assessments with on-platform
assessments: a sellable template whose questions vary by product, run for one
client organisation at a time, answered by that organisation's staff via
invite link, with built-in high-level analysis and a clean export for the
customer's existing Power BI work. Launch: January 2027, alongside LWI.

Not in scope: Power BI Embedded, AI summarisation (Phase 6, gated on PRD
§1.4 #4), branching/skip logic, hosting third-party instrument items (DISC,
REACH) on the platform.

## 1a. The assessment catalogue and its four shapes

The catalogue is taken from the customer's services brochure
([source extract](../../source/05_ttli_services_brochure_2026.md), p.28),
which lists nine instruments; the verbal list from the session omitted Team
Capacity. Each maps to one of four `kind` values on the template, and the
kind decides who answers, about whom, and how results are cut.

| # | Product | Kind | Who answers | About whom | Result unit |
|---|---|---|---|---|---|
| 1 | TTLI Engagement Analysis (TTLI ENGQ) | `org_survey` | client staff, anonymous | the organisation | organisation / level / department |
| 2 | 360 Lead With Intent Assessment (360LWIA) | `multi_rater` | self + manager + peers + direct reports | one leader | subject, pre/post |
| 3 | 360 Cultivating with Intent Assessment (360CWIA) | `multi_rater` | as above | one leader | subject, pre/post |
| 4 | TTLI Leadership Skills Assessment (TTLI LSA) | `individual` | the person | themselves | subject |
| 5 | TTLI Psychological Safety Assessment (TTLI PSA) | `org_survey` | team members, anonymous | a team | team |
| 6 | TTLI Individual Capacity Analysis (TTLI ICA) | `individual` | the person | themselves | subject |
| 7 | TTLI Team Capacity Analysis (TTLI TCA) | `org_survey` | team members | a team | team |
| 8 | DISC Analysis | `external_instrument` | the person, on the vendor's platform | themselves | subject (uploaded report) |
| 9 | REACH Profiles | `external_instrument` | the person, on the vendor's platform | themselves | subject (uploaded report) |

**What the brochure fixes about the ENGQ** (p.8): a structured 50-question
diagnostic across nine engagement elements; customised per organisation
(culture, industry, size); insights cut by **Executive, Management and
Frontline** level; anonymous digital collection; a comprehensive report.
TTLI's delivery is three steps: *finalisation of questionnaire → survey
administration and analysis → solutioning*. Two consequences for the model:

- `level` (`executive`|`management`|`frontline`) is a first-class respondent
  attribute alongside `department`, and results are cut by it. Each level
  bucket is gated by `minimum_group_size` like any other.
- "Finalisation of questionnaire" means per-client tailoring. An instance in
  `draft` may edit its `question_snapshot` (reword, drop, add from the bank)
  before opening; the template is the starting point, not a lock. Edits are
  audited and the snapshot is frozen on open.

The brochure's engagement model names three value drivers, Connection,
Clarity and Capacity (pp.3–4); the nine elements are likely three per driver,
but the item bank itself is not published and stays an open item (§11).

**What it fixes about the 360s** (pp.9–10): both LWI and CWI are eight-phase
programmes in which Phase 1 is a 360 and Phase 7 is a *second* 360 to measure
progress, with one-on-one sessions and four workshops in between. So a
`multi_rater` instance carries `evaluation_role` and `pair_id` exactly as
surveys do today (`standalone`|`pre`|`post`), and the subject report for a
`post` instance shows the delta per competency against the paired `pre`. The
programme itself (assessment → one-on-ones → workshops → assessment →
one-on-ones) is specified in [programmes](2026-09-11-programmes-design.md); see §10.

Items 7 and 8 are third-party instruments administered by an accredited
external practitioner (a health professional today). Both vendors require
accreditation and run their own platforms: REACH practitioners issue survey
codes on the REACH Ecosystem and debrief the profile
([REACH certification](https://us.reachecosystem.com/reach-certification?isRedirect=true),
[PD Training](https://pdtraining.com.au/courses/reach-ecosystem-accredited-practitioner-training-course));
DISC accreditation in South Africa is HPCSA-registered and practitioners
administer and debrief on the provider's psychometrics platform
([InterACT-Global](https://interact-global.co/psychometric-training-accreditation-courses/disc-south-africa/)).
The platform therefore never hosts their items: it records who was assessed,
by which accredited practitioner, and stores the resulting report against the
subject, feeding the same report workflow as everything else. Reproducing
DISC or REACH item content on the platform would be a licensing breach.

## 2. Decisions carried in

| Decision | Answer | Consequence |
|---|---|---|
| Assessed party | An **Organisation** (existing model) | Instances, respondents and reports hang off `organisations.id`; org admins see results under the existing manager-visibility rules |
| Power BI at launch | **Export + link** | CSV and JSON export endpoints; finished Power BI reports come back as attachments via the analyst workflow |
| Response identity | Per-template, fixed at creation, same as surveys | Reuse `survey_response_mode` semantics and the anonymisation audit guarantee |

## 3. Domain model

Extend the survey subsystem rather than clone it. Surveys stay course-bound;
assessments are the standalone, sellable form of the same thing.

```
assessment_templates            (tenant-owned product definition)
  id, tenant_id, slug, title, description, version (int),
  kind ('org_survey'|'multi_rater'|'individual'|'external_instrument'),
  rater_groups jsonb (multi_rater only: [{key:'self'|'manager'|'peer'|'direct_report'|'other',
                     min_group_size:int, anonymous:bool}]),
  vendor (external_instrument only: 'disc'|'reach'|...),
  response_mode ('identified'|'anonymous'), minimum_group_size (default 5),
  status ('draft'|'published'|'retired'), price_id -> products (nullable),
  sections jsonb [{key, title, position}], created_by, timestamps
  UNIQUE (tenant_id, slug, version)

assessment_template_questions   (frozen per template version)
  id, template_id, section_key, question_type, prompt, options jsonb,
  position, scoring jsonb (nullable: {scale: [1..5], reverse: bool})
  -- created by copying question_bank_items (assessment_kind='survey'),
  -- same as the existing "apply bank item" flow

assessment_instances            (one run for one organisation)
  id, tenant_id, template_id (+version), organisation_id,
  title, status ('draft'|'open'|'closed'|'archived'),
  evaluation_role ('standalone'|'pre'|'post'), pair_id (nullable),
  levels_enabled bool (ENGQ: cut by executive/management/frontline),
  opens_at, closes_at, question_snapshot jsonb, created_by, timestamps
  -- snapshot is what respondents see; editable in draft (tailoring), frozen
  -- on open; template edits never leak into a live run
  -- pre/post pairing: same CHECK and partial unique indexes as `surveys`

assessment_subjects             (multi_rater, individual, external_instrument)
  id, instance_id, user_id (nullable), name_encrypted, email_encrypted,
  department, role_label, status ('pending'|'in_progress'|'complete'),
  timestamps
  -- the person being assessed; org_survey instances have no subjects

assessment_invitations
  id, instance_id, subject_id (nullable; required unless org_survey),
  rater_group (nullable; multi_rater only), token_hash bytea UNIQUE,
  email_encrypted (nullable when anonymous), department, level, role_label,
  sent_at, opened_at, submitted_at, expires_at
  -- for anonymous instances the token is the only identity; email is never
  -- stored, and the invitation row is what prevents double submission

assessment_responses
  id, tenant_id, instance_id, invitation_id (nullable), subject_id (nullable),
  rater_group (nullable), user_id (nullable), respondent_reference bytea (nullable),
  department, level, role_label, answers jsonb, created_at
  CHECK ((user_id IS NULL) <> (respondent_reference IS NULL))   -- same as 0013
  UNIQUE (instance_id, invitation_id)

assessment_subject_results      (external_instrument only)
  id, subject_id, administered_by_user_id (accredited practitioner),
  administered_at, vendor_reference, scores jsonb (nullable, e.g. DISC D/I/S/C),
  report_object_key (private container, virus-scanned), timestamps
```

`assessment_responses` mirrors `survey_responses` on purpose (same
one-subject check, same opaque reference) so the anonymisation guarantee and
its audit event are the ones already tested. `department` and `role_label`
are the only attributes an anonymous respondent carries, and only aggregated
above `minimum_group_size`.

No new tables for analysis. Aggregation is computed, not stored.

**Per-kind rules**

- `org_survey`: no subjects; anonymity and `minimum_group_size` as for
  surveys; results by organisation, level and department. Team-level
  instruments (PSA, TCA) are the same kind run for a team-sized group; the
  "team" is the instance, no extra entity.
- `multi_rater`: one subject per assessed leader; a `post` instance reuses
  the `pre` instance's subjects and shows per-competency deltas; invitations
  carry a rater group; `self` and `manager` responses are identified to the subject's
  report (there is one of each), `peer`/`direct_report`/`other` are anonymous
  and only shown when the group meets its `min_group_size` (default 3).
  Results per subject: per-competency self score, others' mean, gap, and
  hidden-strength / blind-spot lists; an instance-level roll-up across
  subjects for the organisation.
- `individual`: one subject who is also the sole respondent; identified;
  results per subject with a personal report and an organisation roll-up.
- `external_instrument`: no questions, no invitations; the practitioner
  records administration and uploads the vendor report per subject. Results
  page lists subjects, status and report links only.

## 4. Flows

**Author (Content author / Admin):** create template → add questions from the
question bank or inline → publish (locks version) → optional product link so
it can be sold through the existing order/invoice path.

**Sell and start (Admin / Finance):** an order for the template product, or a
manual grant, creates an instance for the organisation in `draft`. Admin sets
title, window, and either uploads a respondent CSV (email, department, role)
or generates N anonymous links. Opening the instance sends invitations
through the existing ESP path.

**Set up subjects (multi_rater, individual, external):** admin or partner
adds subjects (CSV: name, email, department, role) and, for 360s, each
subject's raters with their group. The subject nominates peers and direct
reports themselves when the instance is configured `self_nominated = true`,
via their own invite link, with the manager confirming the list.

**Respond (no account):** `GET /a/{token}` renders the snapshot, one submit,
then the token is spent. A 360 rater sees the subject's name and their own
group on the form. Rate-limited per IP through the existing limiter.
Identified instances record `user_id` when the email matches an existing user,
otherwise the invitation is the identity.

**Analyse (Admin, Org admin per privacy rules, Analyst per engagement):**
per-question distributions, per-section mean and spread using `scoring`,
comparison against a prior instance of the same template for the same
organisation (reuse of the pre/post delta logic), completion rate. Aggregates
respect `minimum_group_size`; free-text answers are listed only for
identified instances or where the group is above threshold, and only to
roles with `assessment:analyse`.

**Export:** `GET /assessments/instances/{id}/export.csv` (one row per
response, one column per question, attributes included only if the mode
permits) and `/export.json` (the same, plus metadata) for Power BI. Both are
audited reads.

## 5. API surface (v1)

```
POST   /assessments/templates                      assessment:author
GET    /assessments/templates                      assessment:author | assessment:analyse
POST   /assessments/templates/{id}/questions       assessment:author
POST   /assessments/templates/{id}/publish         assessment:author
POST   /assessments/instances                      assessment:run
POST   /assessments/instances/{id}/invitations     assessment:run   (csv or count)
POST   /assessments/instances/{id}/open|close      assessment:run
GET    /assessments/instances?organisation_id=     assessment:run | org membership (admin)
GET    /assessments/instances/{id}/results         assessment:analyse | org admin (aggregate only)
GET    /assessments/instances/{id}/export.(csv|json) assessment:analyse
GET    /a/{token}                                  public
POST   /a/{token}                                  public
```

New permissions: `assessment:author`, `assessment:run`, `assessment:analyse`.
Content author gains `author`; Admin gains all three; Organisation admins get
aggregate results through membership, not a permission, exactly as the
progress report does today.

## 6. Privacy and security

- Anonymous instances: no email stored on invitations, token is the only
  handle, `respondent_reference` is derived the same way as surveys, audit
  event on every submission proving no identity was written.
- `minimum_group_size` gates every aggregate and every free-text listing;
  `department`/`role_label` breakdowns additionally require each bucket to
  meet the threshold.
- Export endpoints are audited with row counts; exported files are never
  stored, they are streamed.
- Public respond endpoint: token is 32 random bytes, compared by hash,
  single-use, expiring with the instance window; rate-limited.
- Tenant isolation: every table carries `tenant_id`; instance queries are
  always tenant + organisation scoped.

## 7. Web

Admin: templates list/editor (reuse the survey question editor components),
instance list per organisation, instance detail with invitations, results and
export buttons. Organisation dashboard: "Assessments" tab showing instances
and aggregate results. Public: `/a/[token]` single-page form, works at phone
width, no auth, no layout chrome.

## 8. Testing

- Service tests: template versioning locks; snapshot immutability; one-subject
  constraint; threshold gating incl. per-bucket; delta against prior instance.
- Router tests: permission matrix per endpoint; org admin sees aggregate only;
  token single-use and expiry; export column set per response mode.
- Playwright: author → sell → invite → respond anonymously → results gated
  until 5 responses → export.

## 9. Size and order

L. About four weeks for one engineer including web. Builds first; the analyst
workspace spec assumes these tables exist.

## 10. Programmes

Lead with Intent and Cultivate with Intent are sold as eight-phase journeys:
360 → one-on-one → four workshops → second 360 → one-on-one. The chain is
launch scope (customer instruction 2026-09-11) and is specified in
[programmes](2026-09-11-programmes-design.md): learning paths gain typed
steps and a run per organisation, and an `assessment` step creates the
instance (paired pre/post for 360s) for that run's participants.

## 11. Open items for the customer

- The item content for every TTLI-owned instrument (the ENGQ's 50 items and
  nine elements, the 360LWIA and 360CWIA competencies, LSA, PSA, ICA, TCA):
  sections, items, scales, reverse-scored items, scoring and any benchmarks.
  A sample MS Forms export of each.
- Confirm that ICA is `individual` and TCA is `org_survey` at team scope, and
  whether PSA/TCA respondents are anonymous (assumed yes, as for the ENGQ).
- How much per-client tailoring of the ENGQ is typical (reword only, or add
  and drop items), so the draft-edit rules are not wider than needed.
- For DISC and REACH: which practitioner is accredited, on which vendor
  platform, and whether the vendor's terms allow storing the PDF report on
  a third-party platform (most do for the client's own records).
- Whether any assessment must remain identified for the psychologist's
  one-on-one work (drives which templates are `identified`).
