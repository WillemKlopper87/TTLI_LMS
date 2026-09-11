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
§1.4 #4), branching/skip logic, per-respondent scoring feedback.

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
  opens_at, closes_at, question_snapshot jsonb, created_by, timestamps
  -- snapshot is what respondents see; template edits never leak into a live run

assessment_invitations
  id, instance_id, token_hash bytea UNIQUE, email_encrypted (nullable when
  anonymous), department, role_label, sent_at, opened_at, submitted_at,
  expires_at
  -- for anonymous instances the token is the only identity; email is never
  -- stored, and the invitation row is what prevents double submission

assessment_responses
  id, tenant_id, instance_id, invitation_id (nullable),
  user_id (nullable), respondent_reference bytea (nullable),
  department, role_label, answers jsonb, created_at
  CHECK ((user_id IS NULL) <> (respondent_reference IS NULL))   -- same as 0013
  UNIQUE (instance_id, invitation_id)
```

`assessment_responses` mirrors `survey_responses` on purpose (same
one-subject check, same opaque reference) so the anonymisation guarantee and
its audit event are the ones already tested. `department` and `role_label`
are the only attributes an anonymous respondent carries, and only aggregated
above `minimum_group_size`.

No new tables for analysis. Aggregation is computed, not stored.

## 4. Flows

**Author (Content author / Admin):** create template → add questions from the
question bank or inline → publish (locks version) → optional product link so
it can be sold through the existing order/invoice path.

**Sell and start (Admin / Finance):** an order for the template product, or a
manual grant, creates an instance for the organisation in `draft`. Admin sets
title, window, and either uploads a respondent CSV (email, department, role)
or generates N anonymous links. Opening the instance sends invitations
through the existing ESP path.

**Respond (no account):** `GET /a/{token}` renders the snapshot, one submit,
then the token is spent. Rate-limited per IP through the existing limiter.
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

## 10. Open items for the customer

- First two assessments to migrate (names, sections, question counts, scales)
  and a sample MS Forms export of each.
- Whether any assessment must remain identified for the psychologist's
  one-on-one work (drives which templates are `identified`).
