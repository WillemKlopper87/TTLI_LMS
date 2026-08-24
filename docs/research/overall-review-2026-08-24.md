# Overall code review — 2026-08-24

**Scope:** the full session's shipped work (P7 phases 1–5:
`e160426..a1f76e6`; loose ends R14/O13/R8/R2/R3: `79cc5c1..9910a4c`)
plus a systemic pass over the security- and stability-sensitive
surfaces they touch (unauthenticated endpoints, money paths,
external-call paths, concurrency, the events table).

**Method:** same discipline as `p5-review-findings.md` — every claim
below was verified by reading the current code (file:line cited), not
inferred from memory or docs. Working tree was clean and the full
backend suite green at the time of review.

**Headline:** no exploitable authentication/authorization gap was
found. The real findings are two money-adjacent correctness bugs
(F1, F2), one latent availability bug that arms itself the day Teams
credentials are configured (F3), one silent data-loss bug that has
been dropping a conversion signal since podcasts shipped (F4), and an
unauthenticated abuse surface (F5). Everything else is smaller.

---

## Findings, most severe first

### F1 — Workshop-credit double-spend: no row lock on the entitlement (HIGH, money)

**Where:** `apps/api/src/services/workshops.py:509-535`
(`_consume_workshop_credit`).

**What:** the credit draw is a plain SELECT (oldest valid entitlement
with `quantity > 0`) followed by an in-Python decrement and flush.
There is no `.with_for_update()` — and no row locking anywhere in the
credit path. The only `FOR UPDATE` in the entire codebase is the
invoice-number counter (`services/invoicing.py:45`), which proves the
project already knows this idiom for money-adjacent counters and
simply didn't apply it here.

**Failure scenario:** a learner holds 1 credit for a workshop with two
upcoming sessions and issues two `book_session` calls concurrently
(double-click across two session cards, two tabs, or a script). Both
transactions read `quantity == 1`, both decrement, both commit:
`quantity == -1`, two seats claimed for one paid credit. The
`uq_bookings_session_user` unique index (`models/workshop.py:206`)
only blocks double-booking the *same* session — different sessions of
the same workshop sail through.

**Why the tests missed it:** the Phase 4 test exercises the loop
sequentially; nothing runs two bookings in the same instant.

**Fix (small):** add `.with_for_update()` to the entitlement SELECT so
the first transaction holds the row until commit and the second
re-reads `quantity == 0` and refuses. Make the refund symmetric — an
atomic `UPDATE entitlements SET quantity = quantity + 1` (or the same
`with_for_update` read) rather than read-modify-write.

---

### F2 — `update_product` never re-infers `kind`: a stale-kind product breaks fulfilment *after* payment (HIGH, money-adjacent)

**Where:** `apps/api/src/services/catalogue.py:339/350/361` (the three
bridge assignments) vs `:275-279` — `product.kind` is written in
`create_product` **only**; no code path in `update_product` touches it.

**What:** `create_product` deliberately allows a product with *no*
bridge (`kind="course"`, `course_id=None` — the "sellable wrapper"
`schemas/catalogue.py` §6.1 documents). The mutual-exclusion guards in
`update_product` check only that the *other two* bridges are unset —
so PATCHing `workshop_id` (or `learning_path_id`) onto that bridgeless
product passes every guard, sets the FK… and leaves `kind="course"`.

**Failure scenario:** admin creates a draft product, later attaches a
workshop via PATCH, prices it, activates it. A buyer pays by EFT.
Finance clicks approve → `orders.py::_fulfil_order` dispatches on
`kind == "course"`, finds `course_id is None`, raises `OrderError` —
the approval transaction rolls back. Money has moved at the bank;
fulfilment is now wedged until an engineer hand-edits the product row.
This is the exact failure class the P5 review's F3 fixed one level up
(the cross-attachment guard) — the kind-inference half was left
behind, and the workshop bridge inherited it.

**Related pre-existing wart:** the §6.1 "wrapper with no course" can
*never* fulfil at all (`kind="course"` + `course_id=None` →
`OrderError`), so activating one is already a landmine. Worth a guard
at activation time.

**Fix (small):** in `update_product`, re-infer `kind` whenever a
bridge is attached (same three-way inference `create_product` uses);
additionally, refuse `is_active=True` while `kind` and its bridge
disagree.

---

### F3 — A meeting-provider outage blocks cancellation, session-cancel, and waitlist promotion (MED today, HIGH the day Teams is configured)

**Where:** `apps/api/src/services/workshops.py:441`
(`cancel_session` → `provider.cancel_meeting`), `:780` and `:811`
(`_cancel_booking_row` → `remove_attendee` / `add_attendee`), `:653`
(`book_session` → `add_attendee`). `MeetingProviderUnavailable` is
caught **nowhere** in this file (verified by grep — zero matches).

**What:** every Graph call raises `MeetingProviderUnavailable` on any
failure (down, 5xx, bad credentials), and `core/deps.py::get_session`
rolls back the whole request on any exception. Fail-closed is the
*documented and correct* posture for **creating** a meeting (never
fabricate a join link). But the same posture on the cancel side means:

- a learner **cannot cancel their booking** while Graph is down
  (`remove_attendee` raises → rollback, including the credit refund);
- an admin **cannot cancel a session** (`cancel_meeting` raises);
- a **stranger's cancellation fails** because the waitlist-promotion
  `add_attendee` for the *promoted* learner raises.

Today every live workshop uses the `manual` provider (all no-ops), so
this is latent. It arms itself the moment a tenant sets
`meeting_provider="teams"` with real credentials — precisely the
configuration Phase 5 exists to enable.

**Fix (small):** wrap the three cancel-side/attendee-sync call sites
in `try/except MeetingProviderUnavailable` — log (and optionally
`push.notify_user` the organiser that the calendar is now stale) and
proceed. Keep `create_meeting` fail-closed. The Graph event a failed
`remove_attendee` leaves behind is a stale invite; a booking a failed
cancel leaves behind is a locked-in learner.

---

### F4 — `podcast.cta.guest_access_clicked` is fired by the frontend and silently rejected by the backend (MED, silent data loss, pre-existing)

**Where:** `apps/web/app/podcasts/[slug]/page.tsx:336` fires
`logEvent(slug, "podcast.cta.guest_access_clicked")`;
`apps/api/src/services/podcasts.py::ALLOWED_PODCAST_EVENT_NAMES`
contains exactly the six research-doc names — this is not one of them,
so `log_podcast_event` 404s it, and the frontend's fire-and-forget
`.catch(() => undefined)` swallows the 404.

**What:** every "Try a free lesson" click from a podcast page has been
dropped on the floor since the podcast subsystem shipped. This is a
conversion signal (a podcast listener entering the guest-access
funnel) — arguably more commercially interesting than the embed
click-through that *is* recorded. Today's R2 panel can never show it
because the data was never written.

**Fix (trivial):** add `CTA_GUEST_ACCESS_CLICKED =
"podcast.cta.guest_access_clicked"` to `PodcastEventName` and the
allowed set. Optionally surface it on the engagement panel.

---

### F5 — Unauthenticated event endpoints: no rate limit, one unbounded field (MED, abuse surface)

**Where:** `POST /public/podcasts/{slug}/events`
(`routers/podcasts.py`) and the new `POST /public/articles/{slug}/events`
(`routers/articles.py`). Rate limiting exists in exactly four routers
(auth, leads, guest_access, credentials — verified by grep) via the
reusable `services/rate_limit.hit()` + `client_ip()` pattern; neither
event endpoint uses it. `PodcastEventRequest.source`
(`schemas/podcasts.py:85`) is `str | None` with **no max length**,
stored verbatim into `event_properties` JSONB.

**Failure scenario:** an anonymous script POSTs in a loop — every
request inserts a row into the monthly-partitioned `events` table
(disk-fill; the partition-extension cron keeps the runway open
indefinitely) and directly inflates the R2 dashboard's counts (plays,
completions, CTA clicks — the numbers a marketing decision would be
made from). A large `source` string additionally bloats each row.
POPIA note: these rows are written with `consent_analytics=True` by
default — `services/events.py`'s own docstring already flags that as
"a stretch, revisit with the cookie banner"; unchanged here, just
restated.

**Fix (small):** apply the leads pattern (`rate_limit.hit`, per-IP,
something like 60/hour — generous for a human listener, hostile to a
loop) to both event endpoints; `Field(max_length=64)` on `source` and
`max_length=128` on `event_name` (already bounded semantically by the
allowed-set check, but cheap belt).

---

### F6 — Session capacity oversell race (MED, pre-existing since 0018)

**Where:** `apps/api/src/services/workshops.py:577` — `seat_counts()`
(a COUNT) then a status decision then an INSERT, no lock.

**Failure scenario:** two different learners book the last seat
concurrently; both count `registered < capacity`, both insert as
`"registered"` — capacity exceeded, nobody waitlisted. The unique
index doesn't help (different users). Consequence is a soft one (an
over-full session the facilitator discovers on the roster), which is
why this is MED not HIGH — but with `requires_credit` both learners
also *paid* for their seat.

**Fix (small):** `SELECT … FOR UPDATE` on the `workshop_sessions` row
at the top of `book_session` serialises bookings per session (cheap —
contention is per-session, not global) and makes the count-then-insert
atomic. This also incidentally serialises F1's credit draw for the
common same-session case, but F1 needs its own lock regardless.

---

### F7 — `top_cta_episodes` 500s on a malformed `episode_id` property (LOW, robustness)

**Where:** `apps/api/src/services/analytics.py` (`top_cta_episodes`) —
`uuid.UUID(eid)` on values read back out of `event_properties` JSONB.
Today only `log_podcast_event` writes them (always a valid UUID), but
one hand-inserted or future-writer row with a junk `episode_id` takes
the whole analytics dashboard down with an unhandled `ValueError`.
**Fix:** skip unparseable ids (`try/except ValueError → continue`).

### F8 — Teams `add_attendee`/`remove_attendee` read-modify-write race (LOW, latent)

**Where:** `services/meeting/teams.py` — GET the event's attendee
list, mutate in memory, PATCH the whole list. Two concurrent bookings
on the same session can interleave (both GET, both PATCH, last write
wins) and silently drop one learner's invite. Graph supports
`If-Match`/etag on events; a retry-on-conflict (or accepting that F6's
per-session lock already serialises the booking path that calls this)
closes it. Worth a code comment at minimum.

### F9 — Teams token cache never invalidated on auth failure (LOW, latent)

**Where:** `services/meeting/teams.py:84-123` — the module-level token
cache expires only by clock. If the client secret is rotated in Azure
mid-lifetime, every Graph call fails for up to ~55 minutes with no
recovery path except waiting. **Fix:** on a 401 from `_request`, clear
`_cached_token` and retry once with a fresh token.

---

## Improvement notes (not bugs)

- **I1** — `/analytics/podcast-engagement` has no CSV twin; the
  router's own module docstring promises "a CSV twin of each" report.
- **I2** — `events.record` mints a fresh `anonymous_id` per event when
  none is supplied (`services/events.py:53`), and the public event
  endpoints never supply one — so views→plays→completions can never be
  tied to a visitor, only counted. Fine for today's panel; a stable
  (consented) visitor id is the prerequisite for any funnel/retention
  view later.
- **I3** — `ArticleViewTracker` fires from `useEffect`, which React
  StrictMode double-invokes in dev — dev-only double counts, harmless
  in prod. A `useRef` once-guard would silence it.
- **I4** — refunding a consumed credit whose entitlement has since
  *expired* increments a row the validity filter will never draw from
  again — the learner "gets back" a credit they can't spend. No
  deadline policy is specified anywhere, so this is a product
  decision, not a bug; recording it so it's a decision and not an
  accident.
- **I5** — `log_podcast_event` stores `None`-valued keys
  (`percent_complete`, `position_seconds`, `source`) as JSONB nulls on
  every event; dropping unset keys before write is a one-liner and
  shrinks every row.

## Checked and found sound

For completeness — surfaces examined with no finding: BFF proxy header
allowlist (X-Tenant-Host overwrite, Idempotency-Key pass-through);
`build_object_key`/`assert_safe_key` plus all three storage adapters'
independent key refusal; the events partition runway (the
`extend_event_partitions` cron exists — `workers/main.py:39,312` — 12
months ahead, monthly); ICS escaping/folding and the owner-only
calendar endpoint; credit refund non-duplication (no path re-cancels a
cancelled booking; reactivation overwrites provenance correctly);
reschedule atomicity (one transaction, refund+consume nets to zero);
`uq_bookings_session_user` blocking same-session duplicates;
organisation orders refusing non-course kinds (keeps workshop credits
out of the seat pool); the public event endpoints 404-ing unpublished
content (no draft-probing); RLS plus explicit tenant filters on every
new query; `robots.ts` (prefix-match semantics handled, bare routes
covered); the Teams client's fail-closed unconfigured path and its
platform-config-only URL interpolation.

## Suggested packaging

- **PR1 — money correctness:** F1 (credit lock) + F6 (session lock) +
  F2 (kind re-inference + activation guard). One test each: a
  concurrent double-spend test (two tasks, one credit), a concurrent
  last-seat test, and a PATCH-bridge-then-fulfil test.
- **PR2 — resilience:** F3 (catch provider failures on cancel paths) +
  F9 (token retry-once) + F7 (uuid guard) + F8 (comment/retry).
- **PR3 — abuse + data:** F5 (rate limits + field bounds) + F4
  (guest-access event name) + I1/I3/I5 as ride-alongs.
