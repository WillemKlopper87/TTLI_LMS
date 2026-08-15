# 05 — Commercial Packaging

**Scope reference:** [01_PRD.md](01_PRD.md) (requirements) · [02_DATA_MODEL.md](02_DATA_MODEL.md) (entitlements) · [06_OPERATIONS.md](06_OPERATIONS.md) (unit costs)

> **All figures in this document are illustrative and are not quotable.**
>
> They are carried over from the source material, which states the same caveat. No unit-cost model exists yet, so gross margin is unknown at every tier. See §7 before any of these numbers reaches a customer.

---

## 1. Packaging principles

### 1.1 Segments

| Segment | Description | Buying motion |
|---|---|---|
| Guests / leads | Free content, podcasts, resources, demo access | Self-serve, no payment |
| Individual learners | Self-paced courses and certificates | Card, immediate |
| Professional learners | Individuals wanting workshops, coaching, assessments | Card, considered |
| Teams / SMEs | Small groups with manager reporting | Invoice or EFT |
| Corporate / Enterprise | White-label, SSO, custom content, PO billing | PO, procurement cycle |

### 1.2 Billing models

One-time course purchase · multi-tier subscription (built — [01 §1.4](01_PRD.md#14-open-decisions-blocking-phase-0-sign-off) #5 resolved, see §5's subscription note below) · corporate seat-based annual billing · invoice, EFT and purchase order · live workshop credits · one-on-one session credits · enterprise setup fee plus recurring licence.

### 1.3 Currency and tax

| Market | Currency | Tax |
|---|---|---|
| South Africa | ZAR | VAT at the prevailing rate |
| International | USD | Configurable; export treatment where applicable |

International VAT treatment is **blocked** pending the accountants' written position. Prices must state clearly whether they are VAT-inclusive or exclusive; getting this wrong on a public page is a compliance problem, not a copy problem.

### 1.4 How packaging maps to the system

Packages are not hard-coded. A purchase writes **entitlement** rows ([02 §4.7](02_DATA_MODEL.md#47-entitlements)), and every gate in the product — course access, workshop credits, AI insights, manager dashboards — resolves against entitlements plus feature flags. Adding a tier is configuration; it does not require a release.

---

## 2. Package structure

### 2.1 Free / Guest

Lead generation. **Not** a product tier — a funnel stage.

**Included:** public podcasts, articles and brochures · course previews · a guest demo account · one sample lesson · one sample quiz · newsletter subscription.

**Limits:** time-limited (7 or 14 days, pending decision) · no real certificate · no premium downloads · no live workshops · watermarked content · unique account per lead, never shared credentials.

**Price:** free.

### 2.2 Individual Starter

**Included:** one self-paced course or bundle · video lessons · documents · quiz · progress tracking · certificate of completion · digital badge · LinkedIn sharing · email support · web and mobile-web access.

**Excluded:** live workshops · coaching · manager dashboard · custom branding.

| Currency | One-time | Optional monthly |
|---|---|---|
| ZAR | R950 – R2,500 | R250 – R650 |
| USD | $65 – $175 | $19 – $49 |

### 2.3 Individual Professional

Everything in Starter, plus multiple courses or a learning path · advanced assessments · pre/post skills evaluation · live group workshop credits · downloadable resources · priority support · CPD-style certificate where applicable · badge levels · personal progress insights.

**Add-ons:** one-on-one coaching, extra workshops, executive assessment debrief.

| Currency | One-time | Optional monthly |
|---|---|---|
| ZAR | R4,500 – R9,500 | R750 – R1,500 |
| USD | $320 – $650 | $55 – $110 |

### 2.4 Team / SME

**Included:** 5–10 seats · group learning paths · live workshop credits · manager dashboard · aggregate analytics · certificates and badges · invoice/EFT payment · bulk learner invitation · completion reports.

**Privacy default:** managers see aggregate progress. Individual results are hidden unless a system administrator enables them per course — see [04 §2.3](04_SECURITY_AND_COMPLIANCE.md#23-abac-policies). This is a selling point, not a limitation: it is what makes staff willing to answer surveys honestly.

| Seats | ZAR annual | USD annual |
|---|---|---|
| 5 | R18,500 – R35,000 | $1,300 – $2,400 |
| 10 | R32,500 – R65,000 | $2,300 – $4,500 |

### 2.5 Corporate

Everything in Team, plus 20+ seats · purchase order support · invoice terms · dedicated onboarding · cohort and facilitator scheduling · custom reporting · anonymised aggregate AI insights · manager privacy controls · multiple departments · bulk user management · optional API export · SLA-based support.

| Item | ZAR | USD |
|---|---|---|
| Annual licence, 20 seats | R75,000 – R150,000 | $5,200 – $10,500 |
| Additional seat | R2,500 – R5,000 | $175 – $350 |
| Implementation fee | R15,000 – R45,000 | $1,050 – $3,200 |

### 2.6 Enterprise White-Label

Everything in Corporate, plus custom subdomain (`company.executivetrainingportal.co.za`) · custom branding, theme and login page · custom content catalogue · tenant-specific policies · SSO via SAML/OIDC and Microsoft Entra ID · custom registration fields · custom certificates, badges and email branding · enhanced audit logs · data retention controls · dedicated account manager · security review support.

| Item | ZAR | USD |
|---|---|---|
| Setup fee | R65,000 – R180,000 | $4,500 – $12,500 |
| Monthly platform fee | R18,500 – R55,000 | $1,300 – $3,900 |
| Annual licence | R195,000 – R550,000+ | $13,500 – $38,500+ |
| SSO implementation | R18,500 – R45,000 | $1,300 – $3,200 |
| Custom content development | POA | POA |

Enterprise is quote-based against user count, business units, content customisation, SSO complexity, support SLA, retention requirements, integrations, AI usage and streaming volume.

---

## 3. Feature matrix

Legend: ✅ included · ➕ optional add-on · ❌ not included · **Ph** = the phase that delivers it

| Feature | Ph | Free | Starter | Professional | Team | Corporate | Enterprise |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| **Content and funnel** |
| Public podcasts and resources | 2 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Free sample lesson | 2 | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Guest demo account | 2 | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Mobile-responsive web | 1 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| PWA install | 4.5 | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Learning** |
| Self-paced courses | 4 | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Learning paths | 4 | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |
| Quizzes and assessments | 4 | ❌ | Basic | Advanced | Advanced | Advanced | Advanced |
| Surveys | 4 | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Anonymous survey option | 4 | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Progress tracking | 4 | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Anti-bypass completion controls | 4 | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Pre/post skills evaluation | 4 | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |
| **Credentials** |
| Certificate of completion | 4 | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Public verification page | 4 | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Digital badges | 4 | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| LinkedIn sharing | 4 | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| CPD / accreditation fields | 4 | ❌ | ➕ | ➕ | ➕ | ➕ | ✅ |
| Custom certificate design | 5 | ❌ | ❌ | ❌ | ❌ | ➕ | ✅ |
| **Workshops** |
| Live group workshops | 5 | ❌ | ❌ | ✅ credits | ✅ credits | ✅ credits | ✅ credits |
| One-on-one coaching | 5 | ❌ | ➕ | ➕ | ➕ | ➕ | ➕ |
| Microsoft Teams integration | 5 | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Zoom / Google Meet | 5 | ❌ | ➕ | ➕ | ➕ | ➕ | ➕ |
| Multiple facilitators | 5 | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ |
| Scheduling and calendar | 5 | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Corporate** |
| Seat management | 5 | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ |
| Bulk user import | 5 | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ |
| Manager dashboard | 5 | ❌ | ❌ | ❌ | Aggregate | Aggregate | Aggregate |
| Individual manager reporting | 5 | ❌ | ❌ | ❌ | Admin-enabled | Admin-enabled | Admin-enabled |
| Departments / business units | 5 | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **Commerce** |
| Card payment (Payfast / Netcash) | 3 | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| EFT with proof upload | 3 | ❌ | ➕ | ➕ | ✅ | ✅ | ✅ |
| Purchase order / invoice terms | 3 | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ |
| Sequential auditable invoicing | 3 | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Subscriptions | 3* | ❌ | ➕ | ➕ | ➕ | ➕ | ➕ |
| **CRM and marketing** |
| Built-in CRM | 2/5 | ❌ | Basic | Basic | ✅ | ✅ | ✅ |
| Bulk email and newsletters | 5 | ❌ | Basic | Basic | ✅ | ✅ | ✅ |
| External CRM integration | — | ❌ | ❌ | ❌ | ➕ | ➕ | ➕ |
| Accounting export (CSV) | 3 | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ |
| **Analytics and AI** |
| Learner progress analytics | 4 | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Admin dashboards | 3 | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Anonymised AI insights | 6 | ❌ | ❌ | ➕ | ➕ | ✅ | ✅ |
| AI executive summaries | 6 | ❌ | ❌ | ❌ | ➕ | ✅ | ✅ |
| **Tenancy and identity** |
| Custom branding | 5 | ❌ | ❌ | ❌ | ❌ | ➕ | ✅ |
| Custom subdomain | 5 | ❌ | ❌ | ❌ | ❌ | ➕ | ✅ |
| SSO (SAML / OIDC / Entra ID) | 5 | ❌ | ❌ | ❌ | ❌ | ➕ | ✅ |
| Custom content catalogue | 5 | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| API access | — | ❌ | ❌ | ❌ | ❌ | ➕ | ➕ |
| **Content protection** |
| Signed streaming + watermark | 4 | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Widevine / FairPlay DRM | Flag | ❌ | ➕ | ➕ | ➕ | ➕ | ➕ |
| Offline downloads | — | ❌ | ❌ | ➕ | ➕ | ➕ | ➕ |
| **Support and assurance** |
| Audit logs | 1 | ❌ | Basic | Basic | ✅ | ✅ | Advanced |
| Support | — | Self-service | Email | Priority email | Priority + onboarding | Dedicated | Account manager |
| SLA | — | ❌ | ❌ | ❌ | Basic | Enhanced | Enterprise |

`3*` — subscriptions are built (multi-tier, course-bundle plans, EFT/PO-funded renewals — see §5's subscription note); [01 §1.4](01_PRD.md#14-open-decisions-blocking-phase-0-sign-off) #5 is resolved.
`—` — deferred by design; see [01 §9](01_PRD.md#9-explicitly-out-of-scope).

### What is sellable, and when

Reading the phase column against the delivery plan gives the honest revenue timeline:

| After phase | Sellable |
|---|---|
| 3 | **Individual Starter** — but with no LMS to deliver, so not yet |
| 4 | **Individual Starter and Professional** — the first genuinely sellable configuration |
| 5 | **Team, Corporate**, and Enterprise minus AI |
| 6 | **Enterprise** in full |

Nothing is sellable before Phase 4. Commerce without a course player takes money for a product that cannot be delivered — a distinction worth being explicit about with the customer, because a working checkout demo at the end of Phase 3 will look like a finished business.

---

## 4. Add-on catalogue

| Add-on | Description | ZAR | USD |
|---|---|---|---|
| Live group workshop seat | One seat in a scheduled workshop | R1,200 – R3,500 | $85 – $250 |
| One-on-one coaching session | 60–90 minutes | R2,500 – R6,500 | $175 – $450 |
| Executive assessment debrief | Personalised review | R3,500 – R8,500 | $250 – $600 |
| Additional corporate seat | Per year | R2,500 – R5,000 | $175 – $350 |
| Custom course development | Per module | POA | POA |
| SSO setup | SAML/OIDC implementation | R18,500 – R45,000 | $1,300 – $3,200 |
| White-label setup | Tenant setup and branding | R15,000 – R45,000 | $1,050 – $3,200 |
| AI analytics module | Anonymised insights, monthly | R3,500 – R9,500 | $250 – $650 |
| DRM upgrade | Widevine + FairPlay | POA — see §7 | POA |
| SCORM/xAPI support | If required | POA | POA |
| API access | Integration access | POA | POA |
| Premium support | Faster SLA | POA | POA |

---

## 5. Commercial terms

**VAT and tax.** South African prices must clearly state inclusive or exclusive. USD pricing must state whether tax is excluded. Invoices carry VAT registration details. All treatment is subject to accountant sign-off.

**Payment terms.** Individuals pay immediately by card. Corporates: invoice, EFT or PO on 15 or 30-day terms. Enterprise: contract terms. **Access is granted on payment confirmation, never on payment promise** — the EFT and PO flows gate entitlement on finance approval ([03 §5.6](03_API_SPEC.md#56-post-paymentsidapprove--post-paymentsidreject)).

**Refunds.** Suggested: 7-day refund on individual digital purchases where less than 20% is complete. Corporate subject to contract. Workshops subject to cancellation policy. One-on-one sessions require 48 hours' notice. The 20% threshold is enforceable because completion is server-side and auditable.

**Subscriptions**: multi-tier, each plan a course bundle with its own price and billing interval. Renewals are funded through the existing EFT/PO manual-approval checkout, not automatic card charging (no Payfast/Netcash integration exists yet — see [03 §5](03_API_SPEC.md)). Upgrading is immediate and always a new full-price order for a full new period (the remainder of the old period is forfeited, disclosed at confirmation) — never prorated, since this codebase has no credit-note mechanism. Downgrading (including cancellation) is deferred to the next renewal: access continues at the current tier through `current_period_end` plus a 3-day grace period, then lapses automatically (a daily sweep formally closes out the record). A per-subscription cooldown, equal to the current plan's billing interval, blocks another plan change immediately after one — the anti-abuse control for rapid tier-hopping.

**Corporate seats.** Assigned, not shared. Reassignment allowed. Unused seats non-refundable unless contracted. Minimum seat counts may apply.

**Enterprise agreements** should cover tenant isolation, SSO configuration, data retention, support SLA, uptime target, security review rights, the subprocessor list, AI data handling, content ownership, custom development and termination export.

---

## 6. Launch packaging

Three offers at launch. More tiers is more support surface, more billing edge cases and more ways to be wrong about margin.

1. **Individual course purchase** — one-time, self-paced, certificate, badge, email support.
2. **Team bundle** — 5 or 10 seats, aggregate manager dashboard, invoice/EFT, optional workshop credits.
3. **Enterprise enquiry** — "Contact sales". Custom subdomain, optional SSO, PO billing, custom content, optional AI.

Individual Professional and Corporate are introduced once real demand distinguishes them from the tiers either side.

---

## 7. Before any of this is quotable

The pricing above is inherited from the source material, which describes it as illustrative. It has never been checked against cost. These are the inputs needed:

| Input | Why it matters |
|---|---|
| **Video encoding and egress** | Self-hosting removes per-minute encoding cost, but CDN egress scales directly with learner count and video length. A 40-hour executive programme streamed to 500 learners is the number that decides whether Starter at R950 has any margin |
| **AI token cost per tenant per month** | Priced as an add-on at R3,500–R9,500/month with no measured consumption behind it |
| **Facilitator cost per session** | Workshop credits are sold at R1,200–R3,500 per seat; if a facilitator costs more than the seats sold, credits lose money at scale |
| **ESP volume cost** | Per-thousand-email pricing against campaign frequency |
| **Payment gateway fees** | Payfast and Netcash percentages differ, and materially so on a R950 sale |
| **Support cost per tier** | "Dedicated account manager" is a salary, priced here as a feature |
| **Content production cost** | Amortised across expected sales volume |
| **DRM** | Currently POA, and correctly so — the licence cost decides whether the flag is ever switched on |

Recommended next step: build the unit-cost model in [06_OPERATIONS.md §6](06_OPERATIONS.md#6-cost-model) against the actual content inventory once Phase 0 completes it, then revisit every figure in this document. Until then these are anchors for discussion, not prices.
