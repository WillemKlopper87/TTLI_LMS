# Analyst workspace and report workflow — design

**Date:** 2026-09-11 · **Status:** draft for review · **Source:** [CUSTOMER_SESSION_2026-09-11.md](../../CUSTOMER_SESSION_2026-09-11.md) §3.3
**Depends on:** [assessment platform](2026-09-11-assessment-platform-design.md).

## 1. Goal

Let in-house staff and contracted analysts (today: an external psychologist)
work on assessment results inside the platform, isolated from everything
else, and hand finished reports to the owners through a reviewed workflow.
The report is the deliverable the client organisation eventually sees.

Not in scope: in-platform report authoring (reports are uploaded PDFs plus a
summary), Power BI Embedded, AI drafting.

## 2. Decisions carried in

| Decision | Answer | Consequence |
|---|---|---|
| Analyst visibility | **Full identified responses** where the instance is identified | The operator agreement carries the POPIA weight; the platform limits *which* instances, audits *every* read, and never widens beyond the engagement |
| Report delivery | Upload (PDF/PPTX) + summary text, state machine to owners | Power BI output arrives as an attachment; embed is post-launch |

## 3. Roles and isolation

**New role `analyst`** with permissions `assessment:analyse` and
`report:submit` only. No `course:*`, no `order:*`, no `user:*`, no
`analytics:view`. Analysts are ordinary users in the TTLI tenant; MFA is
required as for other elevated roles.

`assessment:analyse` alone is not enough to read anything. Access is gated by
an **engagement**:

```
assessment_engagements
  id, tenant_id, instance_id, analyst_user_id, assigned_by,
  starts_at, ends_at, revoked_at (nullable), purpose text,
  timestamps
  UNIQUE (instance_id, analyst_user_id) WHERE revoked_at IS NULL
```

Policy: an analyst may read an instance's results, free text and export only
if an unrevoked engagement exists for them, `now()` is inside the window, and
the instance is `closed`. Admins keep unconditional access through
`assessment:analyse` plus `tenant:manage`. Every results/export read by an
analyst writes an audit event with instance, analyst and row count.

Analysts never see the organisation's members, seats, CRM records or other
instances. The organisation dashboard is not reachable with the analyst role.

**Owner** in the workflow is any user with `report:review`. Admin gains
`report:review`; the customer's two owners are Admins.

## 4. Report state machine

```
reports
  id, tenant_id, instance_id, engagement_id, author_user_id,
  status ('draft'|'submitted'|'returned'|'accepted'|'withdrawn'),
  title, summary text, version int, submitted_at, decided_at,
  decided_by, decision_note, timestamps

report_attachments
  id, report_id, object_key (private container, virus-scanned),
  filename, content_type, size_bytes, uploaded_at, scan_result
```

Transitions (each writes an audit event):

| From | To | Who | Rule |
|---|---|---|---|
| — | draft | analyst (engaged) or admin | one open draft per engagement |
| draft | submitted | author | at least one clean-scanned attachment or non-empty summary |
| submitted | returned | reviewer | `decision_note` required |
| returned | draft | author | version += 1, previous attachments kept, immutable |
| submitted | accepted | reviewer | report becomes read-only; attachments become the release |
| draft / returned | withdrawn | author | terminal |

Accepted reports are immutable: no edits, no attachment deletes. A new
report is a new row.

**Release to the organisation** is a separate, explicit step:
`POST /reports/{id}/release` by a reviewer marks `released_at` and makes the
accepted attachments visible to the organisation's admins in the
"Assessments" tab. This is the "reports available on the platform" outcome
the customer asked for, without the analyst ever addressing the client.

## 5. Notifications

Existing ESP path. Templates: engagement assigned (to analyst), report
submitted (to all `report:review` holders), report returned/accepted (to
author), report released (to organisation admins). All are plain
transactional emails with a deep link, no content in the body.

## 6. API surface (v1)

```
POST   /assessments/engagements                    assessment:run   (admin assigns)
POST   /assessments/engagements/{id}/revoke        assessment:run
GET    /analyst/engagements                        assessment:analyse (own, active)
GET    /analyst/engagements/{id}/results           engagement policy
GET    /analyst/engagements/{id}/export.(csv|json) engagement policy
POST   /reports                                    report:submit (engaged)
POST   /reports/{id}/attachments                   author, draft only
POST   /reports/{id}/submit | withdraw             author
GET    /reports?status=submitted                   report:review (owner inbox)
POST   /reports/{id}/return | accept               report:review
POST   /reports/{id}/release                       report:review
GET    /organisations/{id}/reports                 org admin (released only)
```

## 7. Security notes (security-officer items)

- Engagement window is the control: contractors lose access automatically at
  `ends_at`; revocation is immediate (no cache on the policy check).
- Exports by analysts are streamed, audited, and watermarked in the CSV
  header with engagement id and analyst email so a leaked file is traceable.
- Attachments go through the existing antivirus scan before they are
  readable, same as assignment uploads.
- A POPIA operator agreement per external analyst is a contractual
  prerequisite recorded on the engagement (`purpose` plus an `agreement_ref`
  field); the admin UI refuses to assign an external analyst without it.
- Analysts are excluded from CSV bulk-invite, CRM and analytics routes at the
  permission level, not by hiding UI.

## 8. Web

Analyst home: list of active engagements, each opening results, export and
the report draft. Owner inbox: submitted reports with accept/return. Org
"Assessments" tab gains a "Reports" section listing released reports with
download links (signed, short-lived URLs from private storage).

## 9. Testing

- Policy tests: analyst without engagement → 403; expired or revoked
  engagement → 403; instance not closed → 409; admin bypass.
- State machine tests: every allowed and disallowed transition; immutability
  after accept; version bump on resubmission.
- Audit tests: every analyst read produces an event with row count.
- Playwright: admin assigns engagement → analyst downloads export, uploads
  PDF, submits → owner returns → analyst resubmits → owner accepts and
  releases → org admin downloads.

## 10. Size

M. About two weeks after the assessment platform lands; the state machine and
policy are small, the tests are most of the work.

## 11. Open items for the customer

- What the psychologist currently receives (format) and returns (format), to
  confirm PDF/PPTX upload is enough for launch.
- Whether releases to the organisation should also notify the organisation's
  primary contact in CRM.
