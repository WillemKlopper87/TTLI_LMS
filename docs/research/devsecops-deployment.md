# TTLI_LMS — DevSecOps Deployment Research Briefing

**Scope:** Azure/AWS/GCP hosting shape and cost (including a genuine minimal-traffic starting tier), reverse-proxy/WAF strategy (including a cheaper-alternatives cut list), A/B testing infrastructure, and defense against automated/AI-driven scanning and scraping.

**Audience:** Engineering/DevOps. Compliance-relevant items are flagged inline for routing to whoever owns `docs/04_SECURITY_AND_COMPLIANCE.md`, not decided here.

**Method note:** Claims are marked as either a **verified fact** (sourced against official documentation/pricing pages) or **synthesis** (this document's own reasoning from verified building blocks). Cloud pricing changes; treat every dollar figure here as a current-as-of-research estimate (researched August 2026), not a quote — re-verify via each vendor's pricing calculator before committing budget.

**What's already decided and not re-opened by this document:** Hosting target is Azure, region South Africa North, for POPIA data-residency (`06_OPERATIONS.md` §4.2). The AWS/GCP comparison below is due-diligence context requested alongside this research, not a proposal to switch — see §1.5 for why the recommendation stays Azure.

---

## 1. Hosting and cost: Azure, AWS, and GCP compared

### 1.1 Azure region availability — the open question in `06_OPERATIONS.md` §4.3 is resolved, positively

`06_OPERATIONS.md` flags Container Apps availability in South Africa North as unverified, with App Service as the documented fallback. Checking every service in the §4.2 table directly against Microsoft's own regional-availability documentation:

| Service | South Africa North status | Source |
|---|---|---|
| **Azure Container Apps** | Available | Official Container Apps pricing page's supported-region set |
| **Azure Kubernetes Service (AKS)** | Available | Azure Backup for AKS's supported-region list explicitly includes South Africa North; Container Insights' region-mapping table maps `SouthAfricaNorth` directly; the 2019 GitHub tracking issue for AKS-in-SA-North is closed/archived as shipped |
| **App Service** (Linux containers, Basic/Standard/Premium, Premium v4, ASE v3) | Available, including availability-zone support | App Service Environment v3 region table and Premium v4 region list both show South Africa North with AZ support |
| **Postgres Flexible Server** | Available, including Zone-Redundant HA and Geo-Redundant backup | Official Postgres flexible-server "Azure regions" table: South Africa North row shows ✅ for Zone-Redundant HA, Same-Zone HA, and Geo-Redundant backup |
| **Azure Cache for Redis** | Available, including zone-redundant Standard/Premium | Official regional-availability table in the Cache-for-Redis high-availability docs |
| **Application Gateway v2 / WAF_v2** | Available | Official "unsupported regions" list names only China East, China North, US DOD East, US DOD Central |
| **Azure Front Door** | Available (global anycast edge, not regionally scoped) | n/a |

**Concrete finding, not a gap:** South Africa North is a mature, fully-featured Azure region for this entire stack — verified positively, contrary to the docs' cautionary framing. The one real gap found is narrower than anticipated: **Application Gateway *for Containers*** (the newer AKS-Gateway-API product, distinct from classic Application Gateway v2) is not in South Africa North's supported-region list — not part of this architecture either way.

**Forward-looking flag, not urgent:** Azure Cache for Redis (the classic product family, including Basic C0) is slated for retirement **April 30, 2028**, with Azure Managed Redis as the migration target (multiple 2026 Azure pricing sources). ~2 years of runway, comfortably past Phase 7 — but the Phase 7 Terraform work should provision **Azure Managed Redis** directly rather than the classic product where there's no reason to prefer the older SKU.

### 1.2 AWS: region and scale-to-zero reality

**Verified:** AWS's South Africa-adjacent region is **af-south-1 (Cape Town)**, launched 2020. All 153 AWS services are listed as available there, explicitly including Fargate, EKS, and ElastiCache (confirmed via AWS's core-services-in-every-region documentation). **RDS Postgres** is available region-wide as a foundational service.

**AWS App Runner — the nearest thing to Azure Container Apps / Cloud Run — is disqualified twice over:**
1. **Not available in af-south-1.** App Runner ships in only 11 of AWS's ~37 regions, and af-south-1 is not among them.
2. **Doesn't scale to zero even where it *is* available.** App Runner's default and minimum is 1 *provisioned* instance; provisioned instances bill **$0.007/GB-hour** continuously whether or not they're serving traffic, specifically to keep the app warm and avoid cold starts. An open GitHub roadmap issue (`aws/apprunner-roadmap#9`, "Scale to zero") remains unresolved as of this research — this is a known, requested, unshipped capability, not an oversight in this research.

**AWS Fargate: available, but no clean scale-to-zero for a standing service.** You *can* set an ECS service's `desiredCount` to 0 — that stops billing. But nothing wakes it automatically: the documented pattern is a Lambda function that watches for incoming requests (via a load balancer returning 503s to real visitors in the meantime) and flips `desiredCount` back to 1, after which the task takes **tens of seconds to over a minute** to become healthy. This is a real, working pattern used in production by some teams, but it is not "clean" in the way Cloud Run or Container Apps are — it's custom plumbing that trades a live user-facing error for the cost saving. **Stated plainly, as asked: AWS has no native, clean scale-to-zero option for a standing container service.**

**The genuine AWS zero-cost-when-idle answer is Lambda (container-image support), not a container platform.** Lambda bills per invocation with true zero cost at zero traffic. FastAPI can run on Lambda via an ASGI adapter (Mangum or similar); Next.js has first-party Lambda deployment tooling (OpenNext). This is a real, workable path — but it is **a different compute model**, not a lift-and-shift of the same container that runs everywhere else: request/response semantics instead of an always-addressable process, and — the sharper problem for this specific stack — **the arq worker's continuous Redis-queue-polling loop does not fit the Lambda invocation model at all** without swapping the job queue mechanism itself to something SQS-triggered. That's a real architecture change to the worker, not a deployment config change.

**AWS pricing (verified baseline, us-east-1; af-south-1-specific rates were not independently confirmed — treat as directional, and note that "regions outside the US typically carry a premium," a pattern confirmed in principle though not with an exact af-south-1 percentage):**
- Fargate: **$0.04048/vCPU-hour + $0.00444/GB-hour**
- RDS Postgres `db.t4g.micro` (2 vCPU/1 GiB): **~$11.68/month** compute-only
- ElastiCache `cache.t4g.micro`: **~$9–12/month** baseline (Valkey ~$9.34, Redis OSS ~$12)

**A real, dated finding worth flagging:** AWS ElastiCache started **Extended Support surcharges on February 1, 2026** for Redis OSS versions 4 and 5 that haven't been upgraded — an **80% premium for years 1–2, 160% for year 3**, and reserved-instance pricing does *not* discount it. This only bites deployments still pinned to an old engine version; a fresh 2026 deployment on a current Redis OSS version avoids it entirely, but it's a real trap for anyone cloning an older reference architecture.

### 1.3 GCP: region and scale-to-zero reality

**Verified, and genuinely news relative to what this project's own docs likely assumed:** Google Cloud now has a real Africa region — **`africa-south1` (Johannesburg)**. It's live and open for customer use (multiple 2024–2025 sources), and direct checks against Google's own regional documentation confirm **Cloud Run, Cloud SQL, Memorystore for Redis (including Memorystore for Redis Cluster), and GKE Autopilot are all available there.** This region did not exist as recently as ~2023, which is plausibly why an Azure/AWS-only framing was reasonable when this architecture was first scoped — it's worth knowing this has changed, purely as due-diligence context (see §1.5 for why it doesn't change the recommendation).

**Cloud Run is the best-in-class scale-to-zero answer of the three clouds.** With `min-instances=0` and the default CPU-during-requests-only billing mode, Cloud Run has **genuinely zero compute charge at zero traffic** — no provisioned-instance floor the way App Runner has. Free tier: 2 million requests, 180,000 vCPU-seconds, 360,000 GiB-seconds per month, renewing monthly, never expiring.

**Cloud Run worker pools reached General Availability on April 14–15, 2026** — a purpose-built feature for exactly this stack's arq worker: an always-on pull-based consumer for a queue, with Google's own documentation explicitly naming **"Redis task queues"** as a supported use case. This is a materially better fit than AWS's Lambda-requires-SQS story — GCP's worker-pool primitive can run the same continuous-polling arq worker pattern natively, without a queue-technology swap.

**GCP pricing (verified baseline, us-central1 — africa-south1-specific rates not independently confirmed, same caveat as AWS above):**
- Cloud SQL `db-f1-micro` (shared-core): **~$7–10/month** compute-only — the cheapest smallest-tier managed Postgres of the three clouds, but shared-core instances carry **no SLA and are ineligible for committed-use discounts**, a real trade-off for that price.
- Memorystore for Redis, Basic tier: **minimum instance size is 1 GiB** (unlike Azure's 250MB Basic C0), at ~$0.049/GiB-hour ≈ **~$36/month** — notably the *priciest* smallest-managed-Redis floor of the three clouds, because GCP simply doesn't offer a smaller managed tier to start from.

### 1.4 Scale-to-zero comparison, side by side

| | Azure Container Apps | GCP Cloud Run | AWS App Runner | AWS Fargate | AWS Lambda |
|---|---|---|---|---|---|
| Native scale-to-zero | Yes (`minReplicas: 0`) | Yes (`min-instances=0`), the reference implementation | **No** — 1 provisioned instance minimum, billed continuously | No — needs custom Lambda+ALB wake-up plumbing, real cold-start/503 risk | Yes, true per-invocation |
| In South Africa/af-south-1/africa-south1 region | Yes | Yes | **No** | Yes | Yes |
| Fits a continuous-queue-polling worker (arq) natively | Yes, via KEDA Redis-list-length scale rule | Yes, via Cloud Run worker pools (GA April 2026) | n/a | Yes (it's just a container) | **No** — needs a queue-technology swap to SQS |
| Verdict for TTLI | Clean fit | Clean fit, best-in-class idle cost | Disqualified (region + no scale-to-zero) | Workable but not "clean" scale-to-zero | Workable for web/API only, not the worker, without re-architecture |

### 1.5 Recommendation: stay on Azure — here's the honest reasoning, not just the incumbent answer

The AWS/GCP research surfaces two genuinely new facts worth registering even though the decision doesn't change: **GCP now has a real, technically-capable South Africa region it didn't have when this architecture was likely first scoped**, and **Azure Container Apps and GCP Cloud Run are both clean scale-to-zero fits while AWS is not**. Given that, the reasoning for staying on Azure is:

1. **Region maturity.** South Africa North (Azure, 2019) has the longest track record and, per §1.1's exhaustive check, the broadest confirmed service parity of the three regions. Cape Town (AWS, 2020) is a full, mature region too (153 services). Johannesburg (GCP, live since ~2023–2025) is the newest and — while every service this stack needs is confirmed present — is the least battle-tested of the three at this specific location.
2. **No re-platforming justification.** The cost and scale-to-zero differences between Azure and GCP specifically are marginal (both clean scale-to-zero platforms, comparable near-zero-tier cost — see §2), not the kind of gap that justifies discarding whatever Azure-specific work (Key Vault integration, `AzureBlobStorageAdapter`, the existing `06_OPERATIONS.md` design) already exists.
3. **AWS is the clearest "no" of the three** for this specific workload shape, on its own technical merits (no clean scale-to-zero, and the worker doesn't fit its zero-cost compute option without a real architecture change) — independent of the region question.

**Compliance note, same category as the WAF-vendor flag in §3:** if GCP or AWS were ever adopted for any component (not recommended here), that's a new cloud-provider subprocessor relationship requiring its own POPIA-residency confirmation and subprocessor-register entry (`04_SECURITY_AND_COMPLIANCE.md` §5.4) — af-south-1 and africa-south1 both plausibly satisfy the same data-residency intent Azure's South Africa North does, but that determination belongs with whoever owns §5, not DevOps, and wasn't independently re-verified here.

---

## 2. The minimal-start scaling path

The team doesn't yet know real traffic. `06_OPERATIONS.md` §5.5 already states the target Stage-1 shape (50–500 learners, ~100 concurrent) — but nothing says that has to be day one. Below is a genuine tier *underneath* that pilot number, followed by the concrete, non-redesigning path upward.

### 2.1 Tier 0 — soft launch, 5–20 real users, mostly idle

**Azure (recommended platform, per §1.5), using Container Apps' actual scale-to-zero mechanics:**

| Component | Configuration | Rough monthly cost |
|---|---|---|
| Web | Container Apps, `minReplicas: 0`, HTTP scale rule wakes it on request | ~$0–5 (comfortably inside the free monthly grant at this volume) |
| API | Container Apps, `minReplicas: 0` | ~$0–10 |
| Worker (arq) | Container Apps, `minReplicas: 0`, **KEDA Redis-list-length scale rule** — scales up when jobs are queued, then a **300-second cool-down** before scaling back to zero once the queue is empty | ~$0–10 |
| ClamAV | Container Apps, **`minReplicas: 1` recommended, not 0** — cold-starting ClamAV means reloading virus definitions (can run 10–30+ seconds); tolerable in principle since scanning is already an async, gated step (`04_SECURITY_AND_COMPLIANCE.md` §3: "virus scanning before the file is readable by anyone"), but keeping it warm is cheap enough that the predictability is worth paying for | ~$8–10 |
| Postgres | Flexible Server, smallest **Burstable B1ms** (1 vCore/2GB) — **Postgres does not scale to zero on any of the three clouds** (stated plainly); the closest sourced reference point is B2ms (2 vCore/8GB) at ~$99/month (UK South), so B1ms is a reasoned extrapolation, not a sourced figure | ~$25–35 *(synthesis, not sourced)* |
| Redis | Two real options, see below | $0–5 or $16 |
| Blob Storage | Standard LRS, negligible content volume | ~$1–5 |
| Edge/TLS | **Defer Front Door entirely at this tier** — Container Apps' own `*.azurecontainerapps.io` ingress includes free automatic TLS termination and a public HTTPS endpoint out of the box. Front Door only starts earning its keep once a custom domain, CDN caching, or WAF is actually wanted | $0 |
| **Total** | | **~$35–75/month**, depending on the Redis and ClamAV choices below |

**The Redis decision at Tier 0 is a real, honest trade-off, not a default:**
- **Cheapest:** self-host Redis as its own scale-tolerant Container App (~$0–5/month). Defensible specifically *because* nothing durable lives only in Redis here — MFA-replay claims and rate-limit counters are short-TTL by design, and the only real risk is an in-flight arq job lost on a restart, which at 5–20 users mostly-idle is a low-probability, low-consequence event.
- **Recommended anyway:** Azure Cache for Redis Basic C0, ~$16/month. At this price, the operational simplicity (no cold-start/data-loss reasoning to carry) is worth paying for even at Tier 0 — this is the one place this document recommends spending the extra few dollars rather than chasing the theoretical floor.

**GCP equivalent (Cloud Run), for comparison:** web/API/ClamAV as Cloud Run services at `min-instances=0` (true $0 idle), worker as a Cloud Run worker pool consuming the same Redis queue pattern natively (no re-architecture, per §1.3) — compute lands near **$0–10/month total**, genuinely cheaper at idle than Azure's floor because Cloud Run has no per-service minimum the way ClamAV's recommended `minReplicas: 1` imposes on Azure. Add Cloud SQL `db-f1-micro` (~$7–10) and either self-hosted Redis (~$0–5) or Memorystore Basic (~$36, notably pricier here — see §1.3). **Total: ~$10–20/month (self-hosted Redis) to ~$50–55/month (managed Redis).** Comparable-to-cheaper than Azure at this exact tier — the gap that matters is §1.5's region-maturity and no-re-platforming reasoning, not this specific number.

**AWS equivalent, stated plainly per §1.2:** there is no clean $0-at-idle container answer. The realistic floor is the smallest possible Fargate tasks (0.25 vCPU/0.5GB, AWS's minimum) running continuously for web/API/worker/ClamAV: at ~$9/month per minimal task × 3–4 services ≈ **$35–45/month in compute alone**, before RDS (~$12–15) and ElastiCache (~$9–12, mind the Extended Support trap in §1.2). **Total: ~$55–80/month** — meaningfully higher than Azure or GCP's floor, specifically because AWS has no genuine scale-to-zero primitive for a standing container service. This is the concrete, plainly-stated answer the research was asked to give rather than forcing a false equivalence.

### 2.2 The upgrade path — turning knobs, not redesigning

This is one continuous architecture with levers, matching `06_OPERATIONS.md` §5.5's own stated philosophy ("nothing done pre-emptively... each is a response to a measurement") rather than three separate designs:

**Tier 0 → Pilot (50–500 learners, ~100 concurrent, the shape `06_OPERATIONS.md` already scopes):**
1. Raise Container Apps `minReplicas` from 0 to 1 on web and API — eliminates cold-start latency for real users now that real users exist. (Worker can often stay at `minReplicas: 0` with the KEDA queue trigger even at pilot scale — cold-starting a background job is invisible to the end user in a way a cold-started page load is not.)
2. If Redis was self-hosted at Tier 0, migrate to managed Basic C0 now — session/queue continuity starts mattering once there's a real user base to disappoint.
3. Add Front Door Standard (~$35/month) once a custom domain, CDN caching, or basic WAF custom rules are actually wanted — not before.
4. Postgres stays on the smallest Burstable tier; it was never scale-to-zero, so nothing changes here except watching the existing §5.5 triggers (CPU >70% sustained, storage >80%).

**Pilot → 10x (500–5,000 learners):**
5. Raise Container Apps max replicas per the existing §5.5 trigger table.
6. Upsize Postgres to General Purpose + read replica (already the documented Stage 2 plan).
7. Redis to Standard/Premium tier for HA.
8. Reassess Front Door Standard → Premium **only** once bot/scan traffic volume in Front Door's own logs justifies the $295/month jump (see §3–§4) — the same evidence-gated trigger already used for AKS reconsideration in §1.

No step here is a rewrite: every lever is a configuration change on infrastructure already provisioned at Tier 0, which is the point of choosing Container Apps (or Cloud Run) over a platform that would force a genuine redesign to add elasticity later.

---

## 3. Reverse proxy + WAF

### 3.1 Framing for the user's background

The BFF (`apps/web/app/api/bff/[...path]/route.ts`) is the only path from browser to API — no CORS surface exists because the API is never on the browser's origin. That's the mental model to map onto: this project doesn't need a WAF "in front of the API" the way a traditional reverse-proxy setup would, because there **is no public API origin** — the API's `X-Tenant-Host`-trusting listener is never internet-reachable in the target architecture; only the BFF's edge is. So the WAF question collapses to: **what sits in front of the Next.js app**, full stop. There's no separate "inspect the BFF's outbound calls to the API" question worth solving — that's an internal, same-network call between two of your own containers, not a public attack surface; a WAF there would be inspecting traffic you already validate with Pydantic at the boundary (`04_SECURITY_AND_COMPLIANCE.md` §3).

### 3.2 What already exists and what a WAF adds on top

Already true, and a WAF doesn't duplicate it: per-request CSP nonce + full security header set (`proxy.ts`), server-side rate limiting with progressive login delay (`03_API_SPEC.md` §1.8), Pydantic input validation at every API boundary, parameterized queries, CSRF on cookie-authenticated state changes. A WAF's actual incremental value on top of that: (a) blocking known-bad request signatures before they reach the Next.js process at all; (b) IP-reputation and geo-based blocking the app layer has no visibility into; (c) a second, independently-operated rate-limiting layer that survives even if the app-layer limiter has a bug; (d) bot classification (§6) that behavioral app-layer logic can't do as well because it doesn't see raw TLS/HTTP fingerprints.

### 3.3 Option comparison

| | Azure Front Door Standard | Azure Front Door Premium | Application Gateway WAF_v2 | Cloudflare (in front of Azure origin) |
|---|---|---|---|---|
| Base cost (verified) | $35/mo + ~$0.009/10K requests | $330/mo + ~$0.015/10K requests, **WAF + Bot Manager + Threat Intel included** | ~$0.443/gateway-hour fixed (~$323/mo) + $0.0144/capacity-unit-hour (realistically another ~$100+/mo minimum) — **no CDN/edge caching, no bot manager** | Free (Bot Fight Mode) / Pro $20–25/mo (Super Bot Fight Mode + full managed WAF ruleset) / Business $200–250/mo |
| WAF managed rule sets | Custom rules only, no managed OWASP ruleset | Included | Available as an add-on to the base gateway cost | Free tier: reduced "Free Managed Ruleset" subset, no OWASP CRS, **0 custom rules**. Pro+: full managed ruleset + custom rules |
| Bot classification | Not available | **Bot Manager ruleset — Premium-tier-only**, classifies Good/Bad/Unknown with JSChallenge action | Not a native feature | Free: Bot Fight Mode (basic). Pro+: Super Bot Fight Mode |
| Global edge / CDN | Yes, anycast | Yes, anycast | No — regional, single-region deployment | Yes, anycast, includes Johannesburg + Cape Town PoPs |
| Fits the BFF chokepoint | Naturally — single origin, no CORS complexity to preserve | Same | Same, but comparable-or-more cost than Front Door Premium for less capability | Same |

### 3.4 Recommendation

**Azure Front Door Standard now (~$35/month, treated as basic edge/CDN/TLS infrastructure, not "the WAF spend"), with a defined, evidence-gated trigger to move to Premium.**

- Application Gateway WAF_v2 will feel most like "the reverse-proxy-with-WAF setup you're used to" — a dedicated, network-resident appliance, closer to an nginx+ModSecurity mental model. But it costs about as much as Front Door Premium ($330/mo) or more, while giving up global anycast edge presence, CDN caching, and any bot classification. It only wins if you specifically need VNet-only/private ingress — not the case for a public LMS.
- Front Door Standard already gets the anycast edge, custom WAF rules, and CDN caching for `_next/static` — directly useful given `06_OPERATIONS.md` §4.4's own flag that CDN egress is the line item most likely to surprise.
- Cloudflare is a legitimate option on pure bot-tooling economics (see §4), but see the compliance flag below before treating it as a pure cost decision.

**Trigger to move Standard → Premium:** log evidence in Front Door's own (included) access logs of real bot/scanner volume the app layer isn't already absorbing, or a Phase 7 pen-test finding the managed ruleset would have caught. Don't pre-pay $295/month extra before there's evidence — mirrors §5.5's "nothing done pre-emptively" discipline.

**Compliance flag, not decided here:** Cloudflare operates edge PoPs in Johannesburg and Cape Town, so in-country traffic inspection is possible — but Cloudflare's own GDPR documentation states metadata/logs are processed in US/EU data centers by default; in-region processing is guaranteed only via the paid Data Localization Suite (enterprise pricing, not evaluated here). Azure Front Door/App Gateway sit inside the existing Microsoft/Azure DPA already presumably covering the rest of this deployment. If Cloudflare is ever adopted, it needs its own subprocessor-register entry and a POPIA §72 cross-border-transfer justification — the same category of work already done for the ESP and AI provider (`04_SECURITY_AND_COMPLIANCE.md` §5.4).

---

## 4. Cheaper WAF alternatives — a genuine cut list

The $330/month Front Door Premium tier is real money for a project with no confirmed traffic yet. This section is deliberately a set of *cuts*, not "everything eventually" — each item states what you give up.

### 4.1 Is Cloudflare's fully-free tier a realistic stand-in?

**What the free tier actually includes, verified:** unmetered DDoS mitigation; the "Free Managed Ruleset" (a reduced subset covering only the highest-impact, most widely exploited patterns — explicitly **not** the OWASP Core Rule Set, so no real SQLi/XSS/RCE-pattern coverage); **up to 5 custom WAF rules**, with no regex support and no Log action; basic Bot Fight Mode (detects simple bots from cloud ASNs and headless browsers, issues a compute-expensive challenge, not configurable). Turnstile (the CAPTCHA-replacement widget) is free and unlimited at every tier, including Free.

**What you give up versus a paid tier:** the actual OWASP-pattern managed ruleset (Pro+), any custom-rule volume beyond 5 (Pro+ raises this materially), Super Bot Fight Mode's per-category actions and verified-bot allowlisting, and any SLA. For a pilot-stage app whose real OWASP-Top-10-shaped protection already lives at the application layer (Pydantic validation, parameterized queries — §3.2), the free tier's gap versus Pro is arguably smaller than it looks on paper; the free tier's DDoS and basic-bot coverage alone is real, useful, and costs nothing.

**Verdict: technically realistic, but skip it for now anyway — for a reason unrelated to its feature set.** Adopting Cloudflare at all, even the free tier, opens the same subprocessor/data-processing-location question flagged in §3.4. That review has a real cost (routing to whoever owns `04_SECURITY_AND_COMPLIANCE.md` §5, a POPIA §72 assessment, a subprocessor-register entry) that isn't worth paying before there's a proven need for anything Cloudflare offers that isn't already covered.

### 4.2 Is a self-hosted open-source WAF (Coraza/ModSecurity) a realistic stand-in?

**Verified, current as of 2026:** OWASP Coraza is a mature, actively-developed, pure-Go WAF engine, fully compatible with ModSecurity's SecLang rule syntax and the OWASP Core Rule Set — meaning it runs the *same* managed ruleset Front Door Premium and Cloudflare Pro charge for, at zero licensing cost. It's designed to embed into modern reverse proxies (Caddy, Traefik, HAProxy) or run as a standalone sidecar. A concretely documented 2026 pattern: Caddy (automatic HTTPS) + Coraza (OWASP CRS v4) as a small, self-contained reverse-proxy container.

**How it would actually sit in front of Container Apps:** either (a) Coraza/Caddy becomes the public-facing Container App, reverse-proxying internally to the Next.js app (which becomes internal-only) — the closer analogue to "a reverse proxy with WAF" the user is already used to — or (b) it runs as a sidecar container within the same Container Apps multi-container revision, sharing localhost networking, with Container Apps' own ingress still fronting the sidecar's port. Both are real, working patterns, not theoretical.

**What you give up:** this is genuinely free in licensing terms but not free in operational terms — rule tuning to avoid false positives on real traffic, keeping the CRS ruleset current, monitoring the WAF container itself for resource exhaustion or crashes, and one more container in the image-scanning pipeline `STATUS.md` §10 already tracks via Trivy/Grype in CI. None of this is hard, but it's real, ongoing work for a team that's already carrying the app-layer security work documented in §3.2.

**Verdict: realistic, but skip it for now too.** Front Door Standard's built-in custom-rules capability — already being paid for as basic edge/CDN infrastructure regardless of WAF strategy (§3.4) — covers the "I want to write my own block rules" need for free, without adding an operational surface. Self-hosted Coraza is worth revisiting specifically if the team ever wants the full OWASP CRS at zero recurring licensing cost and is willing to carry the tuning/patching tax — a real option for later, not a clear win today.

### 4.3 The prioritized cut list

| Item | Decision | Reasoning |
|---|---|---|
| Front Door Standard (~$35/mo) | **Pay for it now** | Not really "WAF spend" — it's the basic edge/CDN/TLS layer any public site needs; custom WAF rules and CDN caching are bonuses already included, and CDN caching plausibly pays for itself in reduced origin traffic |
| Front Door Premium's extra ~$295/mo (managed OWASP ruleset + Bot Manager) | **Skip until log-evidenced** | No traffic yet to justify it; duplicates protection the app layer already provides for OWASP-Top-10-shaped threats; trigger is real scan/bot volume in Front Door Standard's own logs, or a Phase 7 pen-test finding |
| Cloudflare (any tier, including fully free) | **Skip entirely for now** | Not a capability gap — it's genuinely useful even free — but a new subprocessor/compliance-review cost that isn't worth paying before there's a proven need for something Cloudflare offers that Azure doesn't |
| Self-hosted Coraza/ModSecurity sidecar | **Skip entirely for now** | Real, free, and technically sound, but adds an operational/patching surface (rule tuning, CRS updates, one more container in the CI scan pipeline) that isn't worth carrying yet when Front Door Standard's custom rules already cover the same itch |
| Bot Manager / Super Bot Fight Mode-class behavioral bot classification | **Skip until incident-triggered** | See §6 — no evidence yet of AI-agent or sophisticated-bot traffic against this specific app |
| Web Bot Auth adoption, Content Signals Policy beyond basic `robots.txt` | **Skip until Cloudflare (or Azure equivalent) is independently justified** | Standards-track but immature; currently Cloudflare-ecosystem-first; not worth architecting around before there's a reason to be on that ecosystem at all |

---

## 5. A/B testing / feature-flag infrastructure

### 5.1 What the codebase already does

`apps/api/src/core/config.py` already has the pattern in production use: typed boolean settings on the `Settings` object (`subscriptions_enabled: bool = True`), read once via `@lru_cache get_settings()`, with the comment on that exact field explaining the philosophy — a flag exists so "a deployment can still turn it off without a redeploy," configured per-environment via `.env`. This is a real, working feature-flag mechanism today. It's deployment-scoped, not user-scoped: it can't currently split individual users within one deployment, only on/off per environment.

### 5.2 Option comparison

| Approach | What it's good for | Cost at this scale | Self-hostable? |
|---|---|---|---|
| **Extend the existing `Settings` pattern** with a tenant- or user-scoped variant (a `feature_flags` table keyed by tenant/user, simple percentage-rollout logic in the policy module) | On/off rollouts, staged tenant rollouts, kill switches — most of what "future feature rollouts" actually needs now | $0 — no new infrastructure | n/a, it's your own code |
| **Edge-based traffic splitting** (Front Door/App Gateway weighted routing) | Splitting traffic between two *entirely different deployments* (e.g., canary a new container image) | Included in existing Front Door/App Gateway spend | n/a |
| **GrowthBook** | Real experimentation: stats engine, CUPED, sequential testing, visual editor | Self-hosted: **free**, unlimited users, runs against your own infrastructure. Cloud: free ≤3 users, then $40/user/month | Yes — fully open source, free self-host |
| **Unleash** | Feature-flag management, gradual rollout/kill-switch focus, less of an experimentation platform | Self-hosted OSS (Apache 2.0): free forever, capped at 1 project/2 environments on the free tier. Cloud: $75/seat/month, 5-seat minimum | Yes, with the cap above |
| **PostHog** | Feature flags bundled with product analytics | 1M feature-flag requests/month free (cloud), then ~$0.0001–0.00001/request declining. MIT-licensed, free Docker Compose self-host | Yes |
| **LaunchDarkly** | Enterprise-grade experimentation and flag governance | Usage-based in 2026: ~$10/service connection/month + ~$8.33/1,000 client-side MAU. SaaS-only | No |

### 5.3 Recommendation

**Don't adopt a dedicated platform yet. Extend the existing `Settings`/policy-module pattern to support per-tenant and percentage-based rollout; revisit GrowthBook (self-hosted) only once actual A/B experimentation — not just staged rollout — is a real near-term need.**

- LaunchDarkly is the wrong shape at this scale — no self-host option, usage-based pricing built around a much larger MAU count.
- Unleash's free-tier project/environment cap is a real constraint (local/staging/production is already 3 environments before shipping one feature), and it's flag-governance-focused, not built for statistically-sound experimentation.
- GrowthBook is the standout for when TTLI needs *actual* experimentation — free to self-host with no user cap, reads assignment data from wherever you already store it.
- PostHog is a fine second choice, but pulls in a full product-analytics platform when TTLI already has first-party, in-Postgres analytics by deliberate design (`01_PRD.md` §5.11).
- At "will likely be used for future feature rollouts" maturity, what's actually needed is staged/percentage rollout and kill switches — exactly what `subscriptions_enabled`'s pattern already proves out.

### 5.4 The architectural constraint worth flagging

TTLI is multi-tenant with per-tenant Postgres RLS and encrypted PII (`04_SECURITY_AND_COMPLIANCE.md` §2.4, §4.2). Any experiment-assignment mechanism needs to either (a) key on data that's already cleartext and non-identifying — `tenant_id`, `course_id`, cohort/lifecycle attributes, the same category §4.4 already establishes as safe for marketing segmentation — or (b) if per-user, key on the existing internal user ID (already access-controlled and RLS-scoped) rather than a new identifier or PII sent to a third party. This is exactly why self-hosted (GrowthBook, or the `Settings`-pattern extension) is the safer default: assignment logic and its data never leave the tenant-isolated, RLS-protected database, inheriting the existing isolation and encryption posture for free. A SaaS flag/experimentation platform becomes a new subprocessor seeing at least pseudonymous user-behavior data — worth a compliance sign-off before adoption, same category as the WAF-vendor flags above, not a blocker to raise now since nothing is being adopted yet.

---

## 6. Defending against automated/AI-driven threats and scanners

### 6.1 What bot mitigation actually costs and does at this scale

**Verified:** Azure Front Door's Bot Manager ruleset (Good/Bad/Unknown classification, JSChallenge action) is **Premium-tier-only** — no path to it on Standard. Cloudflare's Bot Fight Mode is free on every plan; Super Bot Fight Mode (verified-bot allowlisting, per-category actions, JS-based detection) requires Pro ($20–25/mo)+. Turnstile itself is unlimited and free at every tier.

**Synthesis:** for a team this size, Cloudflare's free/Pro-tier bot tooling is meaningfully more accessible than Azure's Premium-gated equivalent — a real point in Cloudflare's favor specifically for bot mitigation, which sharpens rather than resolves the tension with §3.4/§4.1's compliance flag. If staying single-vendor-Azure matters more than saving on bot tooling, the honest trade is: no serious managed bot classification until traffic/attack patterns justify Front Door Premium.

### 6.2 AI-agent-driven traffic vs. traditional bots — what's actually different

**Verified, sourced:** AI browser-automation agents (OpenAI Operator, Claude for Chrome/Computer Use, open frameworks like Browser Use — ~108,000 GitHub stars as of August 2026) run inside **real Chromium** with genuine user-agent strings, passing network-level checks that trip up simpler scripted bots. Commercial anti-bot vendors (Cloudflare, PerimeterX, DataDome) have moved detection into the browser layer — mouse-movement smoothness, typing-interval consistency, navigation timing — specifically because AI agents' interaction patterns (perfectly straight mouse paths, uniform typing speed, predictable timing) still read as non-human behaviorally even when indistinguishable at the network/TLS-fingerprint layer. Offensive tooling actively targets these signals: `puppeteer-extra-plugin-stealth`, `puppeteer-real-browser`, TLS-impersonation tools (`curl-impersonate`, `curl-cffi`).

**The emerging, standards-track mitigation as of 2026:** **Web Bot Auth** — an IETF-draft standard (RFC 9421 HTTP Message Signatures, Ed25519 keys, a `Signature-Agent` header, a published JWKS directory) letting a bot cryptographically prove identity per request rather than relying on a spoofable user-agent or IP allowlist. Backed by Cloudflare, Amazon, Akamai, and OpenAI, with an IETF WebBotAuth working group chartered in 2026; AWS WAF added support November 2025; Cloudflare, Vercel, Shopify, and Akamai have implemented it. Currently-signing agents include Anthropic Claude, OpenAI ChatGPT, Perplexity, and Common Crawl. No evidence found of Azure Front Door or Application Gateway supporting it yet — it currently reads as Cloudflare-ecosystem-first (and AWS WAF).

**Honest limitation:** this is a genuinely fast-moving space (an IETF working group chartered *this year*) — re-verify before committing budget or architecture to any specific bot-mitigation product here.

### 6.3 AI crawler opt-out conventions — distinct from the security-scanner threat

**Verified, sourced:** `robots.txt` remains the operative, voluntary mechanism. Major AI crawlers expose **separate user-agents for separate purposes** — e.g., OpenAI's `GPTBot` (training) vs. `ChatGPT-User` (real-time fetch on explicit user request) — so a site can block training scraping while staying readable when a learner pastes a course link into ChatGPT. Common 2026 pattern (88% of major news publishers): block training/dataset bots (`GPTBot`, `CCBot`, `Google-Extended`, `ClaudeBot` training behavior), allow search-indexing and user-fetch bots.

**`llms.txt` is not yet load-bearing** — adoption sits around 10% of domains, and major AI citation engines don't reliably fetch it; treat as aspirational.

**The more substantive newer development: Cloudflare's Content Signals Policy**, a `robots.txt` extension (`Content-Signal: search=yes, ai-train=no`) separating search indexing, AI-answer use, and AI training into independently controllable categories, built on the IETF AIPREF working group's draft standard. As of **September 15, 2026**, Cloudflare's default for all new domains (and existing free-tier customers) blocks "mixed-use" AI crawlers on any ad-carrying page. Directly relevant to TTLI: paid course content is exactly the asset class this protects. If Cloudflare is ever adopted (§4.1), this comes effectively bundled in; staying on Azure, the equivalent protection is a well-maintained `robots.txt` disallowing AI-training user-agents under `private-content`-serving paths, enforced regardless by the existing signed-URL/entitlement mechanism (`06_OPERATIONS.md` §3.5) that gates access independent of crawler compliance.

### 6.4 Third-party automated vulnerability scanners — what a WAF actually adds

**Verified/synthesized from 2026 WAF research:** modern WAFs stop the bulk of generic, signature-matched scanning (SQLi/XSS/known-CVE-pattern probing) at the edge. Documented gaps, consistently across sources: (a) API-specific abuse — schema validation and endpoint-level rate limiting are inconsistently handled by generic WAF rule sets; (b) payload-padding evasion — attackers pad malicious requests to exceed inspection windows or dodge regex matching; (c) a cited late-2025 incident ("React2Shell" in the sourced material) demonstrated signature-based WAFs being bypassed outright.

**Concretely for TTLI, reasoned from the architecture already in place:** the two gaps that matter most for a generic WAF (API-schema validation, endpoint-level auth) are **already covered at the application layer** — Pydantic validates every boundary, the ABAC policy module is the single authorization chokepoint (`04_SECURITY_AND_COMPLIANCE.md` §2.1), per-endpoint rate limits already exist (`03_API_SPEC.md` §1.8). A WAF adds real, incremental value against the *other* class of threat — noisy, high-volume, generic internet-wide scanning that never reaches human attention otherwise — not against a sophisticated targeted attack on this app's business logic, which no edge WAF substitutes for the Phase 7 penetration test already scoped.

### 6.5 Prioritized recommendation

**Do now, at pilot scale (cheap, low-effort, real value):**
1. Ship a real `robots.txt` disallowing AI-training user-agents (`GPTBot`, `CCBot`, `ClaudeBot` training behavior, `Google-Extended`) from `/courses/*`, `/lessons/*`, and any `private-content`-backed path — cheap, standards-based, protects the paid-content asset class directly, independent of whatever edge/WAF vendor is chosen.
2. Front Door Standard (§3.4/§4.3) — its basic request-level protections plus existing app-layer defenses reasonably cover the generic-scanner threat class at pilot scale.
3. Nothing further on AI-agent-specific detection yet — Web Bot Auth is too new/unevenly supported to architect around today, and the realistic current threat to a pilot-stage LMS is generic scanning and content scraping, not sophisticated agentic attack tooling.

**Defer until traffic/attack-surface actually grows:**
1. Front Door Premium / Cloudflare Super Bot Fight Mode — wait for log evidence.
2. Web Bot Auth adoption/verification — revisit once Azure-side support exists or a Cloudflare move is independently justified.
3. Content Signals Policy / granular AI-training-vs-search controls beyond basic `robots.txt` — only worth the operational overhead once there's a Cloudflare deployment to hang it on.

---

## Summary tables

### Hosting

| Tier | Azure (recommended) | GCP (comparable) | AWS (weakest fit) |
|---|---|---|---|
| Tier 0 — soft launch, 5–20 users | ~$35–75/mo | ~$10–55/mo | ~$55–80/mo (no clean scale-to-zero) |
| Pilot — 50–500 learners | ~$290–380/mo | Comparable, not independently re-priced at this tier | Comparable-or-higher, same scale-to-zero gap doesn't matter once `minReplicas`/min-instances ≥1 anyway |
| 10x — 500–5,000 learners | ~$800–1,500/mo + CDN egress (dominant variable) | Not independently re-priced | Not independently re-priced |

### WAF/edge spend

| Item | Decision |
|---|---|
| Front Door Standard | Pay now (~$35/mo) — basic edge infra, not "WAF spend" |
| Front Door Premium | Defer — evidence-gated (~$330/mo when triggered) |
| Cloudflare (any tier) | Skip now — real capability, but a compliance-review cost not yet justified |
| Self-hosted Coraza/ModSecurity | Skip now — free but adds ops/patching surface not yet justified |

### A/B testing

| Now | Later, if needed |
|---|---|
| Extend the existing `Settings`/policy-module pattern for tenant/percentage rollout ($0) | GrowthBook self-hosted, once real statistical experimentation (not just staged rollout) is needed |

### Anti-bot/scanner/AI-crawler

| Now | Defer until evidence |
|---|---|
| AI-training `robots.txt`; Front Door Standard; existing app-layer controls | Bot Manager/Super Bot Fight Mode; Web Bot Auth; Content Signals Policy |

**Compliance items to route to whoever owns `04_SECURITY_AND_COMPLIANCE.md` §5, not decided here:** (1) any Cloudflare adoption needs a subprocessor-register entry and POPIA §72 cross-border justification; (2) any AWS/GCP component adoption needs the same for that cloud provider; (3) any SaaS feature-flag/experimentation platform needs the same for pseudonymous user-behavior data.

---

*Researched August 2026. Re-verify pricing and region/feature availability against each vendor's current documentation before committing budget — this is a snapshot, not a standing source of truth.*
