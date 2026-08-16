# TTLI_LMS — Payment & Revenue Analytics Dashboard: Architecture Plan

**Scope:** A new admin-only "Payment & Revenue Analytics" section under `apps/web/app/admin/`, backed by two new read-only, tenant-scoped, timeframe-filterable aggregation endpoints on `apps/api`. Covers backend routes/schemas/aggregation shape, a supporting index-only migration, frontend route/component structure, charting-library choice, report/export scope, and build sequence.

**Audience:** The implementer picking this up next. Every decision below is resolved, not left open, except where explicitly marked as an open question.

**Method note:** Every claim is grounded in a real file read during this investigation (cited inline as `path:line`), not inferred from the requirements prose alone. Where the schema genuinely doesn't decide something (e.g. "predicted revenue"), the reasoning for the concrete choice made is given in full, not deferred.

---

## 1. Grounding: tenancy, organisation, and what "package/tier" really is

**Multi-tenancy is real, not single-operator.** `tenants` seeds two independent demo tenants (`demo`, `acme`) with their own subdomains (`apps/api/alembic/versions/0002_seed_roles_and_tenants.py:81-84`), `tenant_domains` supports arbitrary custom hostnames per tenant (`apps/api/src/models/tenant.py:43-63`), and `docs/05_COMMERCIAL.md` §2.6 sells "Enterprise White-Label" with a `company.executivetrainingportal.co.za` custom subdomain as a product tier. This is a genuine multi-operator SaaS schema, not "TTLI is the only tenant." Every tenant-scoped table (`orders`, `payments`, `ledger_entries`, `subscriptions`, `entitlements`, etc.) carries RLS `FORCE ROW LEVEL SECURITY` keyed on `app.tenant_id` (`apps/api/alembic/versions/0009_commerce_foundation.py:480-493`), and every existing admin read endpoint scopes explicitly to `principal.tenant_id` on top of that (`apps/api/src/routers/orders.py:341-373`). No code path anywhere in `routers/` queries across tenants. **Decision: the new dashboard is tenant-scoped only** — identical pattern to `list_pending_payments`: `principal.tenant_id` passed into every service query, RLS as the second layer. No cross-tenant reporting.

**"Organisation" is the buyer-company, nested inside one tenant.** `organisations.tenant_id` is a required FK (`apps/api/src/models/organisation.py:21-30`); `organisation_members` joins users to organisations within that tenant. One tenant (e.g. the `acme` operator) can have many organisations (its corporate customers). This is exactly the "by company" axis requirement #4 asks for.

**"Package/tier" is not a stored column anywhere** — `docs/05_COMMERCIAL.md` §1.4 states this explicitly: "Packages are not hard-coded. A purchase writes entitlement rows... Adding a tier is configuration; it does not require a release." The only real, admin-configured "tier" object in the schema is `subscription_plans` (`name`, `slug` — `apps/api/src/models/subscription.py:39-70`); an admin can literally name a plan "Team" or "Corporate" and that becomes the tier. One-time course purchases (no subscription) have no tier concept at all beyond the product they bought. **Decision (§4.4 below): the dashboard's package axis is derived from real entitlement/subscription state, not from the commercial-doc tier names, which are sales copy over this substrate, not a schema.**

## 2. Permission gating

`analytics:view` ("View analytics dashboards") already exists, seeded in `apps/api/alembic/versions/0002_seed_roles_and_tenants.py:42`, granted to `admin` and `super_admin` only (lines 62-78) — **not** to `finance`. This is the correct, purpose-built gate for read-only reporting, distinct from `payment:approve` (an action permission, gates EFT/PO approval — `apps/api/src/routers/orders.py:349,383,423`) the same way `refund:process` is kept distinct from `payment:approve` by design (`apps/api/src/routers/orders.py:440-443`).

**Decision:** gate both new endpoints on `principal.require("analytics:view")`.

**Assumption flagged as an open question (§12):** `finance` — the role most likely to actually use a payment/revenue dashboard day-to-day — currently lacks `analytics:view`. Recommend a small data migration adding `analytics:view` to the `finance` role's `role_permissions`, alongside this feature. This is a product/security-owner call, not purely technical, so it's called out rather than silently done.

Frontend gating mirrors the existing convention exactly (`apps/web/app/admin/subscriptions/page.tsx:39-40,144-156`): `const canView = me.permissions.includes("analytics:view")`, with a "your role doesn't hold analytics:view" fallback render — server-side `principal.require` is the real gate, this is only to hide UI a caller can't use.

## 3. Revenue definitions — resolved concretely

### 3.1 Actual revenue

**Definition:** net cash collected in the period, from the append-only ledger, per currency:

```
actual_revenue[currency] =
    SUM(ledger_entries.amount WHERE entry_type = 'payment_received'
        AND created_at IN [period.start, period.end))
  - SUM(ledger_entries.amount WHERE entry_type = 'refund_issued'
        AND created_at IN [period.start, period.end))
```

**Why the ledger, not `orders.grand_total` or `payments.amount` directly:** `ledger_entries` is the append-only, audit-authoritative record of money actually moving (`docs/02_DATA_MODEL.md` §1.5, §6.6) — every fulfilment writes a `payment_received` entry and every refund a `refund_issued` entry inside the same transaction as the state change (`apps/api/src/services/orders.py:389-411`, confirmed against `apps/api/src/services/ledger.py`). Querying it means the dashboard's "actual" figure always reconciles with what finance/audit already trusts, and refunds net out automatically without a second join against `refunds`. `ledger_entries.amount` is VAT-inclusive gross (mirrors `payment.amount` = `order.grand_total`) — this is "cash collected," the everyday finance-dashboard meaning of "actual revenue." (`vat_amount` is also stored per row if a net-of-VAT toggle is wanted later — out of v1 scope.)

**Gotcha found in code, worth flagging to the implementer directly:** `order_status` includes a `'paid'` enum value (`apps/api/src/models/commerce.py:36-47`) that **no code path ever sets** — `_fulfil_order` transitions orders straight from a pending state to `'fulfilled'`, never through `'paid'` (`apps/api/src/services/orders.py:386`). Any query written against `orders.status = 'paid'` will silently return zero rows forever. Use `'fulfilled'`.

### 3.2 Predicted revenue

Two components, kept **separate and labelled**, not silently summed into one mystery number — plus a combined total:

**Pipeline value** (orders that could still convert, but haven't):
```
pipeline[currency] = SUM(orders.grand_total)
  WHERE orders.status IN ('pending_payment','eft_pending_proof',
                           'eft_pending_approval','po_pending_approval')
  AND orders.created_at IN [period.start, period.end)
```
Deliberately **not** risk-weighted by a historical conversion rate — there is no stored, defensible conversion-rate data anywhere in this schema to weight it by, and inventing a percentage would be presenting a fabricated number as fact. Labelled plainly as "orders awaiting payment/approval — not yet converted."

**Subscription renewal forecast** (recurring revenue scheduled to bill in this exact window):
```
renewals[currency] = SUM(subscription_plans.price.unit_amount)
  FOR EACH subscriptions
  WHERE status = 'active' AND cancel_at_period_end = false
  AND current_period_end IN [period.start, period.end)
```
**Why this, not a normalized MRR run-rate:** the user's timeframe picker is arbitrary (24h through 1 year, or a custom range) — an MRR figure (`unit_amount / billing_interval_days * 30`) would need re-deriving per preset and doesn't map cleanly onto a 24-hour or a 3-month custom window. "Which subscriptions are actually scheduled to renew inside this exact window" uses only real, already-stored dates (`current_period_end`) and answers the literal question a period-scoped dashboard is asking. Renewals are still funded through the manual EFT/PO approval flow (`apps/api/src/models/subscription.py:5-8`), not auto-charged — this number is a *forecast* of expected billing, not a guarantee, and the UI must label it that way.

```
predicted_total[currency] = pipeline[currency] + renewals[currency]
```

### 3.3 Multi-currency handling — critical detail

Money is `NUMERIC` + separate `currency` (`docs/02_DATA_MODEL.md` §1.7); this project sells in ZAR and USD (`docs/05_COMMERCIAL.md` §1.3). **Every total in this feature must be computed and rendered per-currency, never summed across currencies.** Both response schemas (§4.2) return money as `list[{currency, amount}]`, never a bare number. The revenue-comparison chart renders one grouped-bar series per currency present in the period (typically just ZAR today), not a single blended figure.

## 4. Backend

### 4.1 New service module: `apps/api/src/services/payment_analytics.py`

Mirrors the existing service-module convention (`services/orders.py`, `services/ledger.py`, `services/reports.py`). Functions, all `tenant_id`-scoped, all read-only:

- `resolve_period(preset: str | None, from_date: date | None, to_date: date | None) -> Period` — server-side resolution (never trust a client-computed boundary — same "resolve server-side" principle `services/orders.py:88-96` already applies to prices/tax). Presets anchor to `now()` at request time; custom range expands the two dates to a full-day UTC window `[from 00:00:00, to+1day 00:00:00)`.
- `paid_vs_waiting(session, tenant_id, period) -> PaidVsWaiting` — per distinct `orders.user_id` with an order `created_at` in period, buckets by that user's most-recent order status in the period: `fulfilled` → paid; `pending_payment`/`eft_pending_proof`/`eft_pending_approval`/`po_pending_approval` → awaiting; `eft_rejected`/`cancelled`/`refunded` → did_not_convert. (Window function `ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY created_at DESC)` per SQLAlchemy, then bucket.)
- `payment_method_breakdown(session, tenant_id, period) -> list[ProviderBreakdown]` — join `ledger_entries` (`entry_type='payment_received'`) to `payments` on `entity_id = payments.id` (`entity_type='payment'`), group by `payments.provider`, `payments.currency`; count + sum per group, filtered on `ledger_entries.created_at IN period`.
- `actual_revenue(session, tenant_id, period) -> list[MoneyByCurrency]` — §3.1's query.
- `predicted_revenue(session, tenant_id, period) -> PredictedRevenue` — §3.2's two queries.
- `registrations_by_package(session, tenant_id, period) -> list[PackageRow]` — for `users` with `created_at IN period` (and `status != 'suspended'`... actually include all statuses, note as v1 simplification): left join active `subscriptions` → `subscription_plans.name`; else check for any `entitlements` sourced from a `fulfilled` order with `product.kind != 'subscription'` → bucket `"One-time purchase"`; else → bucket `"No purchase"`. Current-state entitlement snapshot, not historical (there is no temporal "what tier were they on" tracking in this schema — see §12).
- `registrations_by_organisation(session, tenant_id, period) -> list[OrgRow]` — for `users` with `created_at IN period`, left join `organisation_members` → `organisations.name`; no membership → bucket `"Individual (no organisation)"`.

### 4.2 New schemas: `apps/api/src/schemas/payment_analytics.py`

Following the existing flat-`BaseModel` convention (`apps/api/src/schemas/commerce.py:83-148`):

```python
class MoneyByCurrency(BaseModel):
    currency: str
    amount: Decimal

class PeriodResponse(BaseModel):
    preset: str | None
    from_: datetime = Field(alias="from")
    to: datetime

class PaidVsWaitingResponse(BaseModel):
    paid: int
    awaiting_payment: int
    did_not_convert: int
    total_users: int

class ProviderBreakdownRow(BaseModel):
    provider: str            # "card" | "eft" | "po"
    payment_count: int
    amount: list[MoneyByCurrency]

class PredictedRevenueResponse(BaseModel):
    pipeline: list[MoneyByCurrency]
    subscription_renewals: list[MoneyByCurrency]
    total: list[MoneyByCurrency]

class RevenueSummaryResponse(BaseModel):
    period: PeriodResponse
    paid_vs_waiting: PaidVsWaitingResponse
    payment_methods: list[ProviderBreakdownRow]
    actual_revenue: list[MoneyByCurrency]
    predicted_revenue: PredictedRevenueResponse

class PackageRow(BaseModel):
    package_label: str
    user_count: int

class OrganisationRow(BaseModel):
    organisation_id: str | None
    organisation_name: str
    user_count: int

class RegistrationsResponse(BaseModel):
    period: PeriodResponse
    total_registered: int
    by_package: list[PackageRow]
    by_organisation: list[OrganisationRow]
```

### 4.3 New router: `apps/api/src/routers/payment_analytics.py`

```python
router = APIRouter(prefix="/payment-analytics", tags=["commerce"])
```
mounted in `apps/api/src/main.py` alongside the other `include_router(..., prefix="/api/v1")` calls (`apps/api/src/main.py:114-131`).

A single shared FastAPI dependency `TimeframeQuery` (query params `preset`, `from`, `to`) used by every route below — same pattern as `PrincipalDep`/`SessionDep`/`CryptoDep` (`apps/api/src/core/deps.py:159`).

Routes (all `principal.require("analytics:view")`, all GET, all read-only — **no `Idempotency-Key` needed**, that middleware only gates mutating commerce endpoints — `apps/api/src/core/idempotency.py:40`):

| Route | Returns |
|---|---|
| `GET /payment-analytics/revenue-summary` | `RevenueSummaryResponse` — requirements #1, #2, #3 |
| `GET /payment-analytics/revenue-summary/export.csv` | `text/csv` of the same rows |
| `GET /payment-analytics/registrations` | `RegistrationsResponse` — requirement #4 |
| `GET /payment-analytics/registrations/export.csv` | `text/csv` of the same rows |

CSV export is a real backend endpoint (not client-side re-derivation), built with Python's stdlib `csv.writer` + `io.StringIO()` — this exact stdlib module is already a dependency-free precedent in this codebase, just used for the opposite direction today (`apps/api/src/routers/organisations.py:12-13,255` uses `csv.reader` for bulk-CSV *import*; writing is the same module, zero new dependency). Response via `Response(content=buffer.getvalue(), media_type="text/csv")`. Building it server-side, from the same aggregation functions as the JSON routes, guarantees the export can never drift from what's on screen.

**No BFF proxy changes needed.** `apps/web/app/api/bff/[...path]/route.ts:14` already forwards `request.nextUrl.search` verbatim on every method, so `/api/bff/payment-analytics/revenue-summary?preset=last_7d` works with zero proxy changes — same as every existing admin page's GET calls.

## 5. Migration: indexes only, no new tables/columns

New Alembic revision `0025_payment_analytics_indexes.py` (next after `0024_card_checkout.py`). **No new stored aggregate tables** — at TTLI's realistic near-term order volumes (thousands, not millions, per tenant per year), correctly indexed aggregation over existing normalized tables is sufficient; a rollup table is a real but premature optimisation with no `EXPLAIN ANALYZE` evidence behind it yet. Revisit only if production data shows otherwise.

Reviewed the actual indexes on every column this feature groups/filters by:

| Table | Existing indexes | Gap | New index |
|---|---|---|---|
| `orders` | `tenant_id`, `user_id` (`commerce.py:154-165`) | no `(status, created_at)` composite for the pipeline/paid-waiting queries; `organisation_id` FK has **no index at all** | `ix_orders_tenant_status_created (tenant_id, status, created_at)`; `ix_orders_tenant_organisation (tenant_id, organisation_id)` |
| `payments` | `tenant_id`, `order_id` (`commerce.py:232-243`) | no `(provider, created_at)` | `ix_payments_tenant_provider_created (tenant_id, provider, created_at)` |
| `ledger_entries` | `tenant_id`, `(tenant_id, entity_type, entity_id)` (`commerce.py:472-473`) | no `(entry_type, created_at)` — the exact pair §3.1/§4.1's revenue and payment-method queries filter and group on | `ix_ledger_entries_tenant_type_created (tenant_id, entry_type, created_at)` |
| `subscriptions` | `tenant_id`, `user_id`, unique `(tenant_id, user_id)` (`subscription.py:104-118`) | no `(status, current_period_end)` — needed for the renewal-forecast query | `ix_subscriptions_tenant_status_period (tenant_id, status, current_period_end)` |
| `users` | `tenant_id` only (`user.py:32-37`) | no `created_at` index at all | `ix_users_tenant_created (tenant_id, created_at)` |

All added via `op.create_index(...)`, round-tripped `upgrade → downgrade -1 → upgrade` per `docs/02_DATA_MODEL.md` §12.3's migration discipline. No RLS/enum/permission changes needed in this migration (permission grant, if adopted, is its own tiny data migration — §2).

## 6. Timeframe picker UX → query parameters

Presets rendered as a toggle-button row (styled like the existing `.tag`/`.btn--ghost` set — `apps/web/app/admin/payments/page.tsx` conventions), plus two native `<input type="date">` fields for a custom range:

```
last_24h | last_7d | last_30d | last_3m | last_6m | last_1y | (custom via date inputs)
```

- Clicking a preset button sets `?preset=last_7d` and clears any custom dates.
- Editing either date input switches to `?from=2026-07-01&to=2026-08-16` (server infers "custom" when `from`/`to` are present, `preset` absent or ignored).
- Server validates: exactly one of `preset` XOR (`from` and `to`) must be present; `from <= to`; reject otherwise with the same `AppError`-style refusal-text convention every other endpoint uses.
- Both new endpoints share the identical `TimeframeQuery` params, so switching the timeframe control re-fires both fetches (`revenue-summary` and `registrations`) together — one shared state variable in `page.tsx`.

## 7. Charting approach: recharts

**No chart library exists today** (`apps/web/package.json:12-18` — confirmed: only `hls.js`, `next`, `react`, `react-dom`). This feature needs six distinct, correctly-legended, responsive visualisations (paid/waiting pie, payment-method pie + bar, actual-vs-predicted grouped bar, package pie, organisation bar).

**Weighed:**
- **Hand-rolled SVG** — consistent with this frontend's current minimal-dependency posture, but six charts × correct arc math, legends, tooltips, responsive sizing, and accessible labelling is real, avoidable engineering and bug surface for a feature that isn't this product's core differentiator. Rejected for this scope.
- **visx** — lower-level primitives, more control, but meaningfully more code and a steeper learning curve than this team's other pages show appetite for (every existing admin page is a plain table/card, not custom data-viz). Rejected.
- **recharts** — **recommended.** React-native composable components (`<PieChart>`, `<BarChart>`) map directly onto the six charts needed with minimal glue code, renders SVG (matching this project's existing SVG-based visual style, no canvas), and is the standard low-friction choice specifically because it avoids reinventing tooltip/legend/`ResponsiveContainer` primitives from scratch. This is a *charting* dependency for a genuinely chart-heavy feature — a different category from the general UI/form kits this frontend has deliberately avoided (no MUI, no shadcn) — so adding it doesn't violate the minimal-footprint principle, it's proportionate to the one feature that actually needs it.

**Action:** add `recharts` (latest version confirmed compatible with React 19.2 at implementation time — verify peer-dependency range before pinning) to `apps/web/package.json` `dependencies` only.

## 8. Report generation / export scope

- **On-screen report view — v1, required.** The dashboard page itself, laid out to read as a coherent report: resolved period stated at the top, then the panels in order (#1 → #4). A print stylesheet (`@media print` in `globals.css`, no new dependency) makes "print to PDF" work via the browser natively — zero extra code for a PDF-shaped output.
- **CSV export — v1.** Server-side, stdlib `csv` module, same aggregation functions as the JSON routes (§4.3) — cheap, dependency-free, and matches `docs/05_COMMERCIAL.md`'s already-promised "Accounting export (CSV)" feature (§3 feature matrix, Team tier and up).
- **Server-generated branded PDF — deferred to v2, explicitly out of v1.** `reportlab` already exists in this codebase and generates certificate PDFs (`apps/api/src/services/credentials.py:23-26,137-198`), and is the right tool to extend later — but its current usage is a single fixed-layout template with no chart rendering. A multi-chart PDF report needs either server-side chart rasterisation (a new capability) or accepting the browser-print path above as "good enough." Recommend shipping v1 with CSV + browser print, and only build a true server-rendered PDF once there's a concrete request that browser-print doesn't satisfy — at that point, extend `reportlab`, not introduce a second PDF library.

## 9. Frontend: route and component breakdown

New route `apps/web/app/admin/payment-analytics/`, added to `WORKING_SECTIONS` in `apps/web/app/admin/layout.tsx:21-33` (label "Payment Analytics", href `/admin/payment-analytics`) — replaces/supersedes the currently-inert "Reports" placeholder (`layout.tsx:34`), or sits alongside it; recommend renaming the inert "Reports" entry to point here since this *is* the reports section, rather than adding an eighth top-level nav item — implementer's call, flagged in §12.

Files (following the `courses/page.tsx` + `courses/lesson-activity-panel.tsx` precedent of splitting out a sibling component file once a page has real internal complexity — `apps/web/app/admin/courses/`):

- `page.tsx` — permission gate (`me.permissions.includes("analytics:view")`, same pattern as `subscriptions/page.tsx:39-40,144-156`), timeframe state, the two `authedFetch` calls (`revenue-summary`, `registrations`), passes resolved data down.
- `timeframe-picker.tsx` — preset buttons + custom date inputs, emits the resolved query-string fragment.
- `charts.tsx` — thin recharts wrapper components: `PaidVsWaitingPie`, `PaymentMethodPie`, `PaymentMethodBar`, `RevenueComparisonBar` (grouped, per-currency), `PackagePie`, `OrganisationBar`.
- `csv-export-links.tsx` — two `<a href="/api/bff/payment-analytics/.../export.csv?...">` download links (browser handles the download natively through the BFF's pass-through — no client-side blob construction needed).

Stat-card row above the charts (total actual revenue, total predicted, paid-user count, awaiting count) using the existing `.card p-4` convention (`apps/web/app/admin/payments/page.tsx:158` and throughout) in a `flex flex-wrap gap-3` or Tailwind `grid grid-cols-*` row — Tailwind is already a devDependency (`apps/web/package.json:20,24`), used for layout throughout existing admin pages.

## 10. Data flow (end to end)

1. Admin opens `/admin/payment-analytics`. `layout.tsx` resolves `me` (permissions) as it does for every admin page.
2. `page.tsx` checks `analytics:view`; if absent, renders the fallback message (mirrors `subscriptions/page.tsx`).
3. Default timeframe (`preset=last_30d`) fires two `fetch("/api/bff/payment-analytics/revenue-summary?preset=last_30d", ...)` and `.../registrations?...` calls with `Authorization: Bearer <token>`.
4. BFF (`route.ts`) forwards verbatim to `${API_URL}/api/v1/payment-analytics/...` with `X-Tenant-Host` set from the request's own `Host` header.
5. FastAPI resolves `Principal` (tenant + permissions from the JWT), sets `app.tenant_id` for the request's DB session, `principal.require("analytics:view")`.
6. `TimeframeQuery` dependency resolves `preset`/`from`/`to` into a concrete UTC `Period`.
7. `payment_analytics` service functions run their aggregation queries against `orders`/`payments`/`ledger_entries`/`subscriptions`/`users`/`organisations` — RLS plus the explicit `tenant_id` filter both apply.
8. Router assembles the Pydantic response, FastAPI serialises it (Decimal fields follow the existing `InvoiceResponse`/`RefundResponse` convention).
9. Frontend renders stat cards + the six recharts components from the two payloads.
10. Changing the timeframe re-fires steps 3-9. CSV links point at the `.../export.csv` variants with the same query params, downloaded directly by the browser through the same BFF path.

## 11. Build sequence

**Phase 0 — Migration**
- [ ] Write `0025_payment_analytics_indexes.py` (five indexes, §5). Round-trip `upgrade → downgrade -1 → upgrade`.
- [ ] (Product decision, §2) — data migration granting `analytics:view` to the `finance` role, if approved.

**Phase 1 — Backend**
- [ ] `src/schemas/payment_analytics.py` (§4.2).
- [ ] `src/services/payment_analytics.py` (§4.1) — period resolution + six aggregation functions.
- [ ] `src/routers/payment_analytics.py` (§4.3) — four GET routes, `analytics:view`-gated.
- [ ] Register in `src/main.py`'s `include_router(...)` list.
- [ ] Tests: period-resolution edge cases (UTC boundaries, inclusive custom range), RLS cross-tenant isolation (second tenant's rows never leak), the `'paid'` vs `'fulfilled'` status trap (§3.1), multi-currency non-summing assertion, CSV export byte-for-byte matches JSON aggregation.

**Phase 2 — Frontend**
- [ ] Add `recharts` to `apps/web/package.json` (§7).
- [ ] `app/admin/payment-analytics/page.tsx`, `timeframe-picker.tsx`, `charts.tsx`, `csv-export-links.tsx` (§9).
- [ ] Add nav entry in `app/admin/layout.tsx` (§9).
- [ ] Print stylesheet for the on-screen report view (§8).
- [ ] Manual/browser verification: permission-gated render, all six charts populate correctly across every preset and a custom range, CSV downloads match on-screen totals, second-tenant login shows zero cross-tenant leakage.

## 12. Open questions and assumptions

1. **Should `finance` get `analytics:view`?** (§2) Recommended yes; not applied without product/security sign-off since it's a role-permission change affecting more than this one feature.
2. **Nav placement:** rename the existing inert "Reports" placeholder (`layout.tsx:34`) to point at this route, or add a new nav entry alongside it? Implementer/product call — both are one-line changes.
3. **Package-axis current-state vs point-in-time:** `registrations_by_package` reflects a user's *current* entitlement/subscription state, not what tier they were on at the moment they registered — this schema has no temporal tier history to query instead (entitlements have `granted_at`/`expires_at`/`revoked_at`, not a full tier-change log). Stated as the only available, correct interpretation, not silently assumed.
4. **`recharts` exact version pin against React 19.2** — confirm the compatible major version at implementation time; not independently verified here.
5. **`did_not_convert` bucket in the "paid vs waiting" pie** — the user's literal ask was binary ("paid vs waiting"); a third bucket (`eft_rejected`/`cancelled`/`refunded`) was added because collapsing those into either "paid" or "waiting" would misrepresent them. Flagged in case the stakeholder specifically wants a strict two-slice pie instead.

---

*Researched August 2026 against the TTLI_LMS repository as it exists on this date — re-verify against current model/router state before implementation if time has passed.*
