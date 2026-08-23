# P5 learning paths — post-ship code review and fix proposal

Reviewed 2026-08-23, after all four P5 phases shipped (`8b33259`,
`0fcdc79`, `64005af`, `d40fe0e`). Method: read every P5-touched module
end to end and traced each cross-feature seam (orders → entitlements →
seats, refunds, completion hook, certificate ownership) rather than
re-running the happy path the phases already smoke-tested. The happy
path is genuinely solid — refunds revoke correctly by construction
(shared `source_order_id`), RLS/grants on both new tenant-scoped tables
are complete, the dual-FK certificate work is consistent across all
four call sites, and the completion hook is idempotent twice over
(existing-certificate check + partial unique index). The findings below
are all edge-of-scope seams, ranked by severity.

---

## F1 — HIGH: an organisation can pay for a path and receive nothing

**The bug.** `orders.py::_fulfil_order`'s organisation branch grants a
pool entitlement with `kind="path"` and a comment claiming member-course
fan-out is "assign_seat's own concern, unchanged by P5". That claim is
wrong: `organisations.py::assign_seat`, `_pool_entitlements`,
`list_assigned_seats` and the seat-count query are all hardcoded to
`kind == "course"` and keyed by `course_id`. A path pool entitlement is
invisible to every one of them. No code anywhere can draw a seat from
it.

**Reachable in the shipped UI.** The public `GET /products`
(`routers/orders.py:126`) returns all active products regardless of
kind, and `/organisations/[id]/buy-seats` renders every price with no
kind filter. An org admin can select a path product, raise a PO, upload
the document, have finance approve it — money taken, invoice issued,
ledger written — and the seats can never be assigned.

**Proposed fix (block now, build later).**
1. `services/orders.py::create_order`: when `organisation_id` is not
   `None`, refuse any line whose product kind is `"path"` with a clear
   `OrderError` ("Path seat purchases aren't supported yet — buy seats
   per course."). Fail at order creation, not at fulfilment, so no
   money moves first.
2. `buy-seats/page.tsx`: filter the select to `kind === "course"`.
3. Correct the wrong comment in `_fulfil_order`.
4. Backlog a real "path seats" follow-up: extend `assign_seat` with a
   path variant that reuses `_fulfil_path_purchase`'s fan-out
   (per-employee path entitlement + member-course entitlements +
   enrolments + `PathEnrolment`). It is mostly plumbing that already
   exists.

**Adjacent observation (pre-existing, not P5's), corrected on
re-verification:** the same unfiltered select also offers subscription
products as org seat purchases. Checked against the actual code rather
than assumed: `order.subscription_id` is a top-level `Order` column set
only by `routers/subscriptions.py`'s dedicated flow — the generic
`POST /orders` buy-seats calls never sets it. So an org PO for a
subscription product does **not** silently grant anything; `_fulfil_
order`'s `kind == "subscription"` branch calls `fulfil_subscription_
order`, which immediately raises `SubscriptionError` because `order.
subscription_id is None` (a path marked `# pragma: no cover - only
called for such orders`, i.e. assumed unreachable — the unfiltered
`buy-seats` select is what makes it reachable). The failure rolls the
whole approval transaction back, so no money/entitlement leak — but
finance hits an opaque error trying to approve a PO that can never
fulfil, for a product the UI should never have offered. The kind filter
in step 2 should still be `=== "course"`, which prevents this case too,
just for a different reason (avoiding a broken PO, not a leak).

## F2 — HIGH: editing a purchased path's membership breaks its owners

`learning_path_courses` is fully mutable at any time (`add_course_to_
path` / `remove_course_from_path` have no state or purchaser guard),
but three consumers assume membership is frozen at purchase:

- **Add a course after purchase** → existing purchasers have no
  `Enrolment` for it, and `get_path_progress` calls
  `get_own_enrolment`, which **raises `Forbidden`** on the first
  missing enrolment. Their `/learn/paths/[id]` page errors permanently,
  and `all_member_courses_completed` can never reach `True` for them —
  no completion, no certificate, ever.
- **Remove the only incomplete course** → every *remaining* member is
  complete, but the completion check only runs inside
  `complete_lesson`, and the learner has no lesson left to complete.
  `completed_at` stays `NULL` forever; the certificate never issues.

**Proposed fix.**
1. `services/learning_paths.py::add_course_to_path` /
   `remove_course_from_path`: refuse when the path is `published`
   (mirrors how publish already gates tenant assignment — "unpublish
   first" is an honest admin workflow). This protects the common case
   cheaply.
2. Defence for paths already sold before an edit slips through:
   `get_path_progress` should treat a member course with no enrolment
   as 0% instead of raising — catch the `Forbidden` from
   `get_own_enrolment` per member (or pre-query enrolments) and emit
   the row with `enrolment_id=None`, which means
   `PathCourseProgressRow.enrolment_id` becomes `str | None` and the
   learner page renders the row without a "Continue" link.
3. Not proposed: back-filling enrolments for existing purchasers on
   add, or auto-completing on remove — both invent product decisions
   (does an old buyer get new content free?) that deserve their own
   backlog row, not a guess inside a bugfix.

## F3 — MEDIUM: `update_product` can produce a product that lies about its kind

`create_product` enforces "course or path, never both" and infers
`kind`; `update_product` enforces neither. PATCHing `learning_path_id`
onto a course product (or `course_id` onto a path product) leaves both
FKs set and `kind` stale — fulfilment then silently grants the wrong
thing. Admin-only (`product:manage`), so integrity not access, but the
failure is silent and money-adjacent.

**Proposed fix.** In `update_product`: raise `CatalogueError` if the
incoming `course_id` meets an existing `learning_path_id` or vice
versa. Optionally add the missing DB backstop in the next migration:
`CHECK (course_id IS NULL OR learning_path_id IS NULL)` on `products`.

## F4 — MEDIUM: the plan's own e2e/axe verification step was skipped

The approved P5 plan (Phase 4, "Verify") says: *"Playwright spec for
the public path page + axe pass (mirrors public.spec.ts's per-page
pattern)."* No spec was added — `apps/web/e2e/` has no mention of
paths, and no axe run ever touched `/paths`, `/paths/[id]`,
`/admin/paths` or `/learn/paths/[id]`. The live smoke was ad-hoc
scripts only.

**Proposed fix.** Add `{ path: "/paths", name: "learning paths" }` to
`public.spec.ts`'s `PUBLIC_PAGES` table (two tests for free: renders +
axe). The detail and learner pages need seeded data, so give them the
same treatment `learner.spec.ts` gives enrolments, or at minimum axe
the empty-state shells.

## F5 — MEDIUM: a path bought after its courses are already complete never completes

Completion is only ever detected inside `complete_lesson`. A learner
who already completed every member course (e.g. bought them
individually), then buys the path for its credential, gets a
`PathEnrolment` with `completed_at=NULL` and no remaining lesson to
trigger the check — stuck at "In progress, 100%" with no certificate.

**Proposed fix.** At the end of `_fulfil_path_purchase`, call
`all_member_courses_completed`; if `True`, set `completed_at`.
Certificate issuance at fulfilment time would drag `storage`/`settings`
into `orders.py` — defer that: a completed-but-uncertificated path is
at least visible and supportable, and the certificate half can ride the
F2.3 backlog row.

## F6 — LOW (several, one small PR)

- **`add_course_to_path` position collision**: position is assigned
  from `count(*)`; after a mid-list removal, count collides with an
  existing position and the order becomes ambiguous until a manual
  reorder. Use `max(position) + 1`.
- **Dashboard mislabels uncertificated paths**: `/learn`'s new section
  shows "Certified" / "View certificate" purely from `completed_at`,
  but a path with no template issues nothing. Add `has_certificate`
  (`certificate_template_id IS NOT NULL`) to `OwnPathEnrolmentRow` /
  `OwnPathEnrolmentResponse` and label "Completed" / "View path" when
  false.
- **Dead service function / missing read endpoint**:
  `list_tenant_path_assignments` has no route; the admin editor's
  "Assign to this tenant" gives only a transient notice and can never
  *show* assignment state. Courses have `GET /tenant-assignments` for
  exactly this. Add the GET twin and wire the editor.
- **No way to detach a certificate template from a path**: update
  semantics are "None = unchanged" and there is no `/clear-templates`
  sibling (courses have one). Small parity endpoint.
- **`all_member_courses_completed` omits an explicit
  `Enrolment.tenant_id` filter** — RLS covers it at runtime and
  user_ids are tenant-scoped, but every sibling query in the codebase
  filters explicitly; match the convention.
- **`list_public_paths` counts members per path in a loop** (N+1 on an
  anonymous endpoint). One grouped count query — the exact pattern
  `list_own_path_enrolments` already uses ten lines away.
- **`PathEnrolment.entitlement_id` goes stale** on re-purchase after a
  refund (points at the revoked entitlement; nothing reads it for
  access). Note-only: acceptable provenance drift, document in the
  model docstring.

---

## Suggested sequencing

| PR | Contents | Size |
|----|----------|------|
| 1 | F1 (org-path block, UI filter, comment fix) + F3 (update_product guard) + tests for both refusals | S |
| 2 | F2 (published-path membership guard + tolerant rollup) + F5 (completion check at fulfilment) + tests | M |
| 3 | F6 batch + F4 (e2e/axe specs) | S |
| backlog | Path seat assignment for organisations (the real F1 feature); product decision on membership edits vs. existing purchasers | — |

Everything above is additive or a guard; nothing requires a migration
except the optional `products` CHECK in F3.
