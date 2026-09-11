# Facilitator licensing and xAPI emission — design

**Date:** 2026-09-11 · **Status:** draft for review · **Source:** [CUSTOMER_SESSION_2026-09-11.md](../../CUSTOMER_SESSION_2026-09-11.md) §3.1 and §1 #1
**Depends on:** nothing new. Independent of the assessment specs.

## 1. Goal

Let external facilitators, including health professionals, buy a licence to
run LWI (Lead With Intent) with their own clients on the TTLI platform, with
their clients isolated from TTLI's and from each other, and with TTLI seeing
usage and royalty figures. Separately, emit xAPI statements for LWI learning
activity to a licensee's or a corporate customer's Learning Record Store.

Not in scope: a subdomain or full theme per licensee, licensee-authored
content, xAPI content import (no xAPI/SCORM player), a public LRS of our own.

## 2. Decision: a licensee is an Organisation, not a Tenant

The earlier session note suggested a facilitator tenant. On reading the code,
an Organisation already provides what a licensee needs: an admin who invites
their own people (CSV or one by one), a seat pool drawn from entitlements,
aggregate progress reporting, and the manager-visibility privacy chain. A
separate Tenant would require cross-tenant content licensing, since courses
are tenant-scoped, and a hostname per solo practitioner. That is weeks of
work for branding the customer did not ask for.

So: `organisations.kind` gains the value `licensee`, and LWI stays in the
TTLI tenant.

## 3. Domain model

```
organisations
  + kind ('corporate'|'licensee')   default 'corporate'
  + logo_object_key (nullable)      shown on licensee learners' certificates and header

licences
  id, tenant_id, organisation_id, course_id XOR learning_path_id (a programme licence, see
  the programmes spec §3), status ('active'|'suspended'|'expired'),
  seats_purchased int, seats_used int (derived, cached), starts_at, ends_at,
  price_per_seat_cents, currency, royalty_pct (nullable, for reporting only),
  order_id (nullable), notes, timestamps
  UNIQUE (organisation_id, course_id) WHERE status = 'active'

licence_seat_grants
  id, licence_id, entitlement_id, learner_user_id, granted_at, revoked_at
  -- one row per learner enrolled under the licence; ties usage to billing
```

Seat assignment reuses `services.organisations.assign_seat` with a licence as
the pool source: a licensee's seat pool is the sum of active licences' seats
rather than an order's entitlements. Everything downstream (enrolment,
completion, certificates) is unchanged.

## 4. Commercial flow

1. Finance/Admin creates the licensee Organisation (`kind = licensee`) and
   the facilitator as its `admin` member. The facilitator has no platform
   role beyond learner; org membership is the authority.
2. A licence is created against an order (EFT/PO through the existing
   checkout; card later when Payfast lands) or manually with `notes`.
3. The facilitator invites clients; each invite consumes a seat via a
   `licence_seat_grants` row. Refusal when `seats_used == seats_purchased` or
   the licence is outside its window.
4. Clients learn in the normal player; certificates carry the licensee logo
   next to TTLI's and the wording "delivered by {organisation.name}".
5. Renewal: a new licence row; expired licences keep existing learners'
   access until their own entitlement expiry, no new seats.

TTLI-side **usage and royalty report** (`analytics:view`): per licensee,
seats purchased/used, completions, certificates issued, revenue, royalty
at `royalty_pct`. CSV export. This is the customer's visibility into
"who is using LWI".

## 5. Isolation and content protection

- Licensee admins see only their organisation's members and aggregate
  progress; the manager-visibility default (aggregate only) applies and an
  Admin can enable individual results per course for licensees exactly as
  for corporates.
- Licensee admins get no `course:*` permissions: they cannot view authoring,
  download source video, or export course structure. Video remains signed
  HLS with the existing watermark, which now includes the organisation slug.
- Licensee learners are ordinary users in the TTLI tenant, scoped by
  organisation membership; they cannot see other organisations.
- Health-professional use: no patient data enters the platform. If a licensee
  wants to run assessments for their clients, that is an assessment instance
  for their organisation under the assessment platform spec, with the same
  privacy controls. Nothing extra for launch.

## 6. xAPI statement emission

**Scope:** outbound only. For each organisation (licensee or corporate) an
optional LRS configuration; the platform posts statements for that
organisation's learners. No inbound statements, no launch protocol.

```
organisation_lrs_configs
  id, organisation_id UNIQUE, endpoint_url, auth_type ('basic'), 
  credentials_encrypted, actor_mode ('mbox'|'account'), enabled bool,
  last_success_at, last_error, timestamps

xapi_outbox
  id, tenant_id, organisation_id, statement_id UUID UNIQUE, statement jsonb,
  attempts int, next_attempt_at, delivered_at, last_error, created_at
```

**Statement mapping** from existing completion-engine events, produced in
the same transaction that records the event, into `xapi_outbox`:

| Platform event | Verb | Object |
|---|---|---|
| lesson started | `initialized` | lesson |
| lesson completed | `completed` | lesson (result.completion) |
| quiz attempt graded | `answered`/`passed`/`failed` | quiz (result.score scaled/raw/min/max) |
| course completed | `completed` | course |
| certificate issued | `earned` (ADL) | certificate, with verification URL |

Actor: `mbox` (`mailto:` of the learner email) or `account` (homePage =
platform URL, name = user id) per config; licensees pick `account` if they
must not receive emails. Context includes `contextActivities.grouping` for
the course and an `extensions` entry for the organisation.

**Delivery:** an arq worker job drains the outbox per organisation with
exponential backoff (1 min → 24 h, max 10 attempts), batches up to 50
statements per `POST /statements`, records `last_success_at`/`last_error`
on the config. Admin UI shows queue depth and last error per organisation
and offers "test connection". Failures never affect learner flow.

## 7. API surface (v1)

```
POST   /organisations                         existing; body gains kind, logo
POST   /licences                              invoice:create | tenant:manage
GET    /licences?organisation_id=             tenant:manage | org admin (own)
POST   /licences/{id}/suspend|reactivate      tenant:manage
POST   /organisations/{id}/invite             existing; consumes a licence seat when kind=licensee
GET    /reports/licensees                     analytics:view (usage/royalty, csv)
PUT    /organisations/{id}/lrs                org admin | tenant:manage
POST   /organisations/{id}/lrs/test           org admin | tenant:manage
GET    /organisations/{id}/lrs/status         org admin | tenant:manage
```

## 8. Web

Admin: organisation form gains kind and logo; licence list/create per
organisation; licensee usage report page. Organisation admin (facilitator):
the existing organisation dashboard with a "Licence" card (seats used/left,
expiry) and an "Integrations → xAPI" settings panel. Learner: certificate
shows the licensee logo; no other change.

## 9. Testing

- Seat pool from licences; refusal at limit and outside window; expiry keeps
  existing access.
- Licensee admin permission matrix: no course authoring, no other orgs.
- Certificate rendering with and without licensee logo.
- xAPI: statement builder golden tests per event; outbox written in the
  same transaction as the event; worker retry/backoff; batch delivery
  against a stub LRS; credentials never logged.
- Playwright: create licensee → licence → invite client → client completes a
  lesson → statement appears in stub LRS → usage report shows the seat.

## 10. Size

M. About three weeks: one for licences and seats, one for reporting and
certificate/watermark changes, one for xAPI outbox and worker. Can run in
parallel with the analyst workspace once the assessment platform is in.

## 11. Open items for the customer

- Price per seat, minimum pack size, licence term, and whether a royalty
  figure is needed in reporting or only seat revenue.
- Whether licensees may run assessments for their clients at launch.
- Which LRS the first licensee or corporate uses, for a real conformance
  test before January.
