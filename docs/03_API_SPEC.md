# 03 — API Specification

**Scope reference:** [01_PRD.md](01_PRD.md) (requirements) · [02_DATA_MODEL.md](02_DATA_MODEL.md) (schema) · [04_SECURITY_AND_COMPLIANCE.md](04_SECURITY_AND_COMPLIANCE.md) (authz)

All endpoints live under `/api/v1`. The Next.js tier consumes them through the generated client in `packages/api-client`; it never hand-writes a request shape.

---

## 1. Conventions

### 1.1 General

- JSON request and response bodies, UTF-8.
- `snake_case` field names, matching the Pydantic schemas.
- Timestamps are RFC 3339 with an explicit offset, always UTC: `2026-08-08T14:32:00Z`.
- Money is a string decimal with an explicit currency: `{"amount": "1250.00", "currency": "ZAR"}`. Never a float.
- Collections are always wrapped, never a bare array — a bare top-level array cannot be extended with pagination later without breaking clients.

### 1.2 Standard request headers

| Header | Required | Purpose |
|---|---|---|
| `Authorization: Bearer <jwt>` | Yes, except public endpoints | Access token |
| `X-Tenant-Host` | Set by the BFF | Resolved hostname; the API derives tenant from it and from the token claim, and rejects a mismatch |
| `Idempotency-Key` | On all unsafe payment endpoints | Client-generated UUID |
| `If-Match` | On updates to versioned resources | Optimistic concurrency |
| `Accept-Language` | Optional | Reserved; content is English-only at launch |

The tenant is asserted twice — from the host and from the token — and disagreement is a `403`. A single source would make host spoofing a tenancy bypass.

### 1.3 Error envelope

Every non-2xx response uses one shape:

```json
{
  "error": {
    "code": "LESSON_LOCKED",
    "message": "Complete the current lesson requirements first.",
    "details": {
      "missing_requirements": ["video_watch_percentage", "quiz_pass_score"],
      "video_watch_percentage": {"required": 80, "actual": 41},
      "quiz_pass_score": {"required": 70, "actual": null}
    },
    "request_id": "01J9Z2K7VQ4N8XG3TB6RMFH2AC"
  }
}
```

`code` is a stable machine-readable constant; `message` is safe to display; `details` is structured and endpoint-specific. `request_id` correlates to the structured log.

Error messages never disclose whether an email address exists, which tenant a resource belongs to, or why authorisation failed beyond the fact that it did.

### 1.4 Status codes

| Code | Use |
|---|---|
| 200 | Success with a body |
| 201 | Created; `Location` header set |
| 202 | Accepted for async processing; body carries a job ID |
| 204 | Success, no body |
| 400 | Malformed request |
| 401 | Missing or invalid credentials |
| 403 | Authenticated but not permitted — including tenant mismatch |
| 404 | Not found, **or** found but not visible to this caller |
| 409 | State conflict, e.g. duplicate idempotency key with a different payload |
| 412 | `If-Match` precondition failed |
| 422 | Semantically invalid — validation failures |
| 423 | Locked — the lesson gating code |
| 429 | Rate limited; `Retry-After` set |

`404` deliberately covers "exists but not yours". Distinguishing them leaks the existence of other tenants' data.

### 1.5 Pagination

Cursor-based. Offsets drift under concurrent writes, and the events table is large enough for that to matter.

```
GET /api/v1/courses?limit=25&cursor=eyJpZCI6...
```

```json
{
  "items": [...],
  "page": {"next_cursor": "eyJpZCI6...", "has_more": true}
}
```

### 1.6 Idempotency

Required on `POST /orders`, `POST /payments/*`, `POST /refunds`, and every provider webhook. The key plus a hash of the request body is stored; a replay with the same key and body returns the original response, and a replay with the same key and a *different* body returns `409`.

### 1.7 Optimistic concurrency

Mutable resources carry `version` (integer) and return it as a weak `ETag`. Updates send `If-Match`. A stale write gets `412`, never a silent overwrite. This matters most on course completion rules and tenant settings, where two admins editing concurrently is realistic.

### 1.8 Rate limits

| Surface | Limit |
|---|---|
| Anonymous | 60 req/min per IP |
| Authenticated | 600 req/min per user |
| Login and password reset | 10/min per IP, 5/min per account, with progressive delay |
| Guest signup | 5/hour per IP |
| Public certificate verification | 30/min per IP |
| Video heartbeat | 12/min per session — just above the 10 s interval |
| AI insight generation | Per-tenant token budget, not request count |

---

## 2. Authentication

### 2.1 `POST /auth/login`

Email and password. Returns a 15-minute access token and a 30-day rotating refresh token bound to a device fingerprint. When MFA is enforced for any of the caller's roles, returns `202` with `{"mfa_required": true, "mfa_token": "..."}` instead of tokens.

### 2.2 `POST /auth/magic-link`

Always returns `204`, whether or not the address exists. Enumeration is the entire attack here.

### 2.3 `POST /auth/magic-link/consume`

Single-use token, 15-minute expiry. Consumption is atomic — a replay fails.

### 2.4 `POST /auth/mfa/verify`

TOTP with a ±1 window. Six consecutive failures lock MFA verification for 15 minutes and write an audit event.

### 2.5 `POST /auth/refresh`

Rotates the refresh token. **Reuse of a consumed refresh token revokes the entire token family and audits it** — that is the theft signal.

### 2.6 `GET /auth/sso/{tenant_slug}/authorize`, `POST /auth/sso/{tenant_slug}/callback`

Per-tenant SAML/OIDC. Just-in-time provisioning with role mapping. Phase 5.

---

## 3. Catalogue and content

| Endpoint | Notes |
|---|---|
| `GET /courses` | Public. Facets per REQ-STORE-01. Returns only courses visible to the resolved tenant |
| `GET /courses/{slug}` | Public. Curriculum with lessons marked locked/available for the caller |
| `GET /resources`, `GET /podcasts` | Public; `access_level` decides whether the body or only the teaser is returned |
| `POST /courses` · `PATCH /courses/{id}` | `course:edit`. `If-Match` required |
| `POST /courses/{id}/publish` | `course:publish`. Runs the publishing checklist and refuses on any incomplete item, returning the list |
| `POST /lessons/{id}/completion-rules` | `course:edit`. Body validated against the schema in [02 §5.2](02_DATA_MODEL.md#52-completion_rules-shape). **Changing rules re-evaluates existing completions** and may revoke certificates — the response states how many |

---

## 4. Leads and guest access

### 4.1 `POST /leads`

Public, rate-limited. Creates lead, contact and consent records, attributes UTM, and optionally provisions a guest account. Returns `204` regardless of whether the email was already known.

### 4.2 `POST /guest-access`

Creates a unique, time-limited guest user with a sample-only entitlement (REQ-LEAD-04/05). Never returns credentials in the body — a magic link is emailed. `guest_expires_at` is set from the tenant's configured window, pending [01 §1.4](01_PRD.md#14-open-decisions-blocking-phase-0-sign-off) #6.

---

## 5. Commerce

### 5.1 `POST /orders`

`Idempotency-Key` required. Prices are resolved **server-side** from `prices`; a client-supplied amount is ignored, not trusted and validated. Returns the order with its computed tax breakdown and the matched `tax_rule_id` per line.

### 5.2 `POST /orders/{id}/checkout/card`

Returns a redirect URL for Payfast or Netcash hosted checkout. The platform never sees card data (REQ-PAY-06).

### 5.3 `POST /orders/{id}/checkout/eft`

Transitions to `eft_pending_proof` and returns bank details plus the unique `payment_reference`.

### 5.4 `POST /orders/{id}/payment-proof`

Multipart upload. Virus-scanned before it becomes readable. Transitions to `eft_pending_approval` and notifies finance.

### 5.5 `POST /orders/{id}/checkout/purchase-order`

Captures PO number and document, generates a pro-forma invoice, transitions to `po_pending_approval`.

### 5.6 `POST /payments/{id}/approve` · `POST /payments/{id}/reject`

`refund:process`-adjacent permission `payment:approve`. **There is no automated approval path** (REQ-PAY-03). Approval issues the tax invoice, grants entitlements and writes the ledger entry, all in one transaction. Rejection returns the order to `eft_pending_proof` with a reason.

### 5.7 `POST /webhooks/payfast` · `POST /webhooks/netcash`

Unauthenticated but **signature-validated**; an invalid signature is `401` and an audit event. Idempotent on `provider_event_id`. Always returns `200` once persisted — retry storms are worse than late processing, so the work happens on the queue.

### 5.8 `GET /invoices/{id}` · `GET /invoices/{id}/pdf`

`GET /invoices/export?from=&to=&format=csv` produces the SARS-ready export, and is itself an audited action.

---

## 6. Learning and progression

### 6.1 `GET /enrolments/{id}/progress`

Returns per-lesson state with, for each locked lesson, the specific unmet requirements. The UI renders the checklist from this — it does not compute it.

### 6.2 `POST /lessons/{id}/start`

Idempotent. Records `first_seen_at`, transitions `available` → `in_progress`.

### 6.3 `POST /lessons/{id}/heartbeat`

The anti-bypass workhorse.

```json
{"position_seconds": 214, "playback_rate": 1.0, "session_id": "01J9Z..."}
```

Server-side validation, and every one of these is a rule the client cannot talk its way around:

1. `created_at` is assigned by the server; any client timestamp is discarded (REQ-BYPASS-02).
2. The interval since the previous heartbeat is measured server-side. Accumulated watch time increases by at most that interval, so watched time can never outrun wall-clock time (REQ-BYPASS-03).
3. `position_seconds` above `furthest_position_seconds + tolerance` is rejected with `SEEK_NOT_PERMITTED` (REQ-BYPASS-04).
4. `playback_rate` above the configured maximum is rejected.
5. Concurrent sessions beyond the limit terminate the oldest and audit it (REQ-BYPASS-09).

### 6.4 `POST /lessons/{id}/complete`

Runs the merged rule set server-side. Success transitions to `completed` and returns the next available lesson. Failure is `423 LESSON_LOCKED` with the `details` payload from §1.3. **The client's opinion is never consulted** (REQ-BYPASS-01).

### 6.5 `POST /quizzes/{id}/attempts` · `POST /quiz-attempts/{id}/submit`

Attempt creation enforces the attempt limit and returns randomised questions and options. Correct answers are never sent to the client before submission. Time limits are enforced against the server-recorded `started_at`.

### 6.6 `POST /surveys/{id}/responses`

When the survey's `response_mode` is `anonymous`, the handler **must not write `user_id`** ([02 §7.6](02_DATA_MODEL.md#76-surveys-survey_questions-survey_responses)). Duplicate submission is prevented by `respondent_reference`. A contract test asserts the column is absent, not merely null — this is the kind of guarantee that decays silently under refactoring.

### 6.7 `GET /media/{video_asset_id}/playback`

Returns a short-lived signed playlist URL plus the watermark payload the player overlays.

```json
{
  "playlist_url": "https://cdn.../master.m3u8?token=...",
  "expires_at": "2026-08-08T15:02:00Z",
  "watermark": {"text": "jakoklopper@gmail.com · 41.x.x.x", "opacity": 0.18}
}
```

Entitlement is checked before the URL is minted; the URL is bound to the user and the session; segment requests accept `?access_token=` because media players cannot set headers on segment requests. Download is refused unless the admin has enabled it for the tenant, package or user.

---

## 7. Credentials

| Endpoint | Notes |
|---|---|
| `GET /certificates/{id}/pdf` | Owner or `certificate:issue` holder |
| `GET /verify/{token}` | **Public, unauthenticated.** Returns holder, course, dates, status, issuer. Rate-limited and logged |
| `POST /certificates/{id}/revoke` | `certificate:revoke`. Reason required. Audited |
| `PATCH /badges/{id}` | Learner sets `visibility` (REQ-CRED-07) |
| `GET /badges/{id}/share/linkedin` | Returns the share URL and the *Add to Certification* field set: name, issuing organisation, issue date, expiry, credential ID, credential URL |

---

## 8. Workshops

`GET /workshops`, `GET /facilitators/{id}/availability`, `POST /bookings`, `POST /bookings/{id}/cancel`, `POST /workshop-sessions/{id}/attendance`.

Booking validates payment or credit, capacity, facilitator availability and timezone in one transaction, then queues meeting provisioning. **Provisioning failure does not fail the booking** — it falls back to `manual` and alerts an administrator (REQ-WS-06). A learner whose booking succeeded should not lose it because Graph was briefly unavailable.

`POST /workshop-sessions/{id}/attendance` accepts `source: provider_report | facilitator_manual`; the facilitator's entry always wins (REQ-WS-08).

---

## 9. Corporate

`POST /organisations/{id}/seats`, `POST /organisations/{id}/invitations`, `POST /organisations/{id}/invitations/bulk` (CSV, async, returns a job ID), `GET /organisations/{id}/reports/progress`.

The progress report is where the manager-visibility rule bites. Its response shape is **determined by policy, not by query parameters**: unless all three conditions in [04 §2.3](04_SECURITY_AND_COMPLIANCE.md#23-abac-policies) hold, individual rows are absent from the payload — not present-and-redacted. A client cannot request individual data into existence.

---

## 10. Analytics and AI

`POST /events` accepts a batch of first-party events; consent flags are recorded on each row at write time ([02 §11.1](02_DATA_MODEL.md#111-events)).

`POST /ai/insights` is `202` plus a job ID. The job runs the redaction gateway before any provider call and records `identifiers_removed`. `GET /ai/jobs/{id}` returns provider, model, token usage, cost estimate and redaction metadata — visible to administrators so the anonymisation claim can be inspected rather than trusted.

Requests are refused when the tenant's `ai_enabled` is false or the monthly token budget is exhausted (`AI_BUDGET_EXCEEDED`).

---

## 11. Compatibility

`/api/v1` is stable once Phase 3 ships. Additive changes only: new optional fields, new endpoints, new enum members that clients must tolerate. Breaking changes go to `/api/v2` with both served for at least 90 days. Deprecations carry a `Deprecation` and `Sunset` header for at least one full phase before removal.

---

## 12. Testing requirements

| Layer | Requirement |
|---|---|
| Contract | `packages/api-client` regenerates from `openapi.json` with no diff. CI fails otherwise |
| Integration | Every endpoint against a live Postgres. Skipped integration tests **fail the build** |
| Authorization | Every endpoint tested from every role, asserting both allow and deny. A new endpoint without deny tests does not merge |
| Tenancy | Cross-tenant access attempts return 404 for every resource type |
| Anti-bypass | Explicit adversarial tests: forged timestamps, seek-ahead, replayed heartbeats, concurrent sessions, attempt-limit exhaustion, direct `POST /lessons/{id}/complete` without prerequisites |
| Idempotency | Duplicate webhook delivery, duplicate order submission, refresh-token reuse |
| Financial | Invoice sequence has no gaps across a concurrent issue test; ledger `UPDATE` and `DELETE` are refused by the database |
| Load | 100 concurrent users against the player and checkout paths |

---

## 13. Open questions for engineering review

1. **Heartbeat tolerance.** How much position drift is legitimate on a flaky connection before a seek is judged illegitimate? Too tight produces false refusals for real learners on poor South African mobile links.
2. **Concurrent session limit.** Per user, or per user per course? An executive with a laptop and a tablet is a normal case, not an attack.
3. **Public verification rate limit.** 30/min may be too low for an employer batch-verifying a cohort's certificates.
4. **Bulk invite ceiling.** At what CSV size does the synchronous validation pass need to become asynchronous too?
5. **Webhook replay window.** How long are `provider_event_id` records retained before a replay stops being recognised as a duplicate?
