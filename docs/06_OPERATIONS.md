# 06 — Operations

**Scope reference:** [01_PRD.md](01_PRD.md) (decisions) · [02_DATA_MODEL.md](02_DATA_MODEL.md) (schema) · [04_SECURITY_AND_COMPLIANCE.md](04_SECURITY_AND_COMPLIANCE.md) (controls)

Audience: developers and site administrators.

---

## 1. Local environment

### 1.1 Services

| Service | Image | Host port | Why non-default |
|---|---|---:|---|
| Postgres | `postgres:16-alpine` | **5452** | 5432 is taken; worksorder holds 5442, collab 5433, Internal_Booking 55532 |
| Redis | `redis:7-alpine` | **6399** | 6379 taken; worksorder 6389, collab 6380 |
| MinIO API | `minio/minio` | **9140** | 9000 taken; worksorder 9110, collab 9002 |
| MinIO console | | **9141** | |
| Mailpit SMTP | `axllent/mailpit` | **1145** | worksorder 1125 |
| Mailpit web | | **8145** | worksorder 8125 |
| ClamAV (clamd) | `clamav/clamav-debian:stable` | **3410** | 3310 is the clamd default |
| API | local | **8010** | |
| Web | local | **3010** | 3000 is taken by several projects |

Every port here is deliberately non-default and checked against every sibling project on this machine. Reusing 5432 means two projects cannot run at once, which is the failure mode this table exists to prevent.

Health checks on every service; named volumes so a `docker compose down` does not destroy the database.

### 1.2 Postgres bootstrap

`infra/postgres-init/01-extensions.sql` enables `citext` (case-insensitive email domains and slugs), `pg_trgm` (catalogue search before a dedicated search service is justified), and `pgcrypto`. Row-level security is enabled per table by the migrations that create them, not here.

### 1.3 Configuration contract

`.env.example` is the contract, sectioned with `# --- Section ---` headers and inline secret-generation commands. **`DATABASE_URL` has no default** — the application refuses to start rather than guessing and silently connecting somewhere unintended.

`core/config.py` exposes `check_production_safety()`, which returns a **list of problems** rather than a boolean, so the failure log names every issue at once: debug enabled, break-glass admin active, SSO disabled where a tenant requires it, development storage credentials, TLS off, missing Sentry DSN, default encryption key, or AI configured without a redaction gateway.

---

## 2. Storage

### 2.1 Adapter

One interface, three implementations. The customer's requirement was explicitly "either S3 buckets, or a Microsoft hosting bucket, depending on the customer's hosting preference", so the choice is configuration, not architecture.

```
StorageService
  upload_object()      get_object()        delete_object()
  generate_signed_url()  get_public_url()
  set_metadata()       list_objects()      apply_lifecycle_policy()
```

`S3StorageAdapter` · `AzureBlobStorageAdapter` · `LocalStorageAdapter` (development, backed by MinIO).

### 2.2 Containers

Separated by classification, because a single bucket with mixed ACLs is how private content becomes public.

| Container | Access | Contents |
|---|---|---|
| `public-marketing` | Public read via CDN | Marketing images, public PDFs, public podcast audio, static assets |
| `private-content` | Signed URL only | Premium video renditions, course documents |
| `user-uploads` | Private | Payment proofs, assignment submissions, profile images — virus-scanned before readable |
| `generated-documents` | Private | Certificates, invoices, exports |
| `backups` | Highly restricted, separate key | Database and media backups |

Controls: public write blocked everywhere · short signed-URL expiry · encryption at rest · versioning on `generated-documents` and `backups` · lifecycle rules · access logging · CORS restricted to known hosts · least-privilege identities · key rotation. **No secrets or keys are ever stored in a bucket.**

Never public: premium course content, personal data, invoices, certificates, user uploads, AI outputs.

---

## 3. Media pipeline

### 3.1 Provenance

The VOD pipeline is ported from the in-house `Streaming_Server` project (`c:/Users/Wille/Downloads/applications/Streaming_Server`), a 3GPP 5G MBS broadcast head-end whose own architecture document states: *"With every flag off the system is an ordinary HLS origin; the standards layers switch on above it."* Underneath the broadcast machinery sits exactly the VOD pipeline this platform needs.

**`Streaming_Server` is not modified by this project.** The logic is ported into `apps/api/src/services/media/`.

### 3.2 What was ported

From `src/services/transcoding-engine.js` and `src/services/ffmpeg-controller.js`:

| Behaviour | Why it matters |
|---|---|
| One decode → N encodes via `split` in the filter graph | Three separate FFmpeg processes let each encoder place IDR frames independently; segment boundaries then do not align and **the player cannot switch rung without an artefact**. The ladder looks correct and is unusable |
| IDR pinned to segment boundaries: `force_key_frames` + `sc_threshold 0` | Frame-rate independent, unlike GOP-count approaches |
| Declared `maxrate` / `bufsize` VBV per rung | Predictable bandwidth; unconstrained VBR overshoot wastes egress |
| CMAF/fMP4 output with a master playlist | Standard adaptive streaming |
| Job persistence with hydrate-on-restart | Processes die; the job record survives |
| Progress persisted at most every 5 s | FFmpeg emits `-progress` roughly twice a second; every one of those does not need a database round-trip |
| Retention sweep on transcode output | Disk is not free |

Also adopted, from `src/middleware/auth.js`: accepting the access token as a query parameter on segment requests, because **media players cannot set headers on segment requests**. That constraint lands on day one of building a player and is easy to discover the hard way.

Starting ladder, inherited and reasonable for executive talking-head content:

| Rung | Resolution | Video | Maxrate | Bufsize | Audio |
|---|---|---|---|---|---|
| 480p | 854×480 | 1200k | 1320k | 2400k | 96k |
| 720p | 1280×720 | 2800k | 3080k | 5600k | 128k |
| 1080p | 1920×1080 | 5000k | 5500k | 10000k | 128k |

### 3.3 What was deliberately not ported

The entire broadcast stack — RaptorQ AL-FEC, ROUTE/FLUTE, LCT, TMGI allocation, BM-SC signalling, MBSFN SYNC, MooD, R&S RF control — is irrelevant to unicast VOD.

**`mbms-security.js` contributes nothing.** It implements the 3GPP MSK/MTK key hierarchy (TS 33.246); its own header notes that broadcast content protection *"has a shape unicast DRM does not."* No part of it transfers to Widevine or FairPlay.

### 3.4 What had to be built

None of this exists in `Streaming_Server`:

- Per-user, per-asset signed URLs with short expiry, bound to user and session
- Watch-progress heartbeat validation ([03 §6.3](03_API_SPEC.md#63-post-lessonsidheartbeat))
- Concurrent-stream limits
- Geo and domain restriction
- CDN integration
- Entitlement checks before a URL is minted

### 3.5 Video protection at launch

Short-lived signed HLS URLs · server-side heartbeat validation · per-user **player-overlay** watermark carrying email and IP · downloads disabled unless an administrator enables them.

The watermark is a player overlay rendered client-side, **not** per-user re-encoding. Forensic burned-in watermarking would require a transcode per viewer and is not proportionate at this scale.

### 3.6 DRM upgrade path

Behind `VIDEO_DRM_ENABLED`. When switched on, either a licence-only provider (EZDRM, PallyCon, Axinom) bolted onto the in-house packager with CENC, or migration of premium assets to a full provider (Mux, JW Player, Cloudflare Stream).

**Azure Media Services is not an option** — retired mid-2024. The source material recommends it in one answer while warning against it in another; the warning was correct.

---

## 4. Infrastructure

### 4.1 Now: Docker Compose

Every phase demos on a laptop. This is a deliberate cost decision, not a shortcut — the customer's most specific constraint was that infrastructure must not consume early revenue, and provisioning cloud before there is anything to host contradicts it.

### 4.2 Later: Azure South Africa North

| Component | Service | Start size | Cost control |
|---|---|---|---|
| Web | Container Apps *(verify — see §4.3)* | 0.5 vCPU / 1 GB, min 1 max 2 | Consumption plan, autoscale cap |
| API + worker | Container Apps *(verify)* | 1 vCPU / 2 GB, min 1 max 4 | Consumption plan, autoscale cap |
| Database | Postgres Flexible Server | B2ms, 2 vCore, 8 GB, 128 GB storage | Burstable, HA off initially |
| Cache / queue | Azure Cache for Redis | Basic C0 | Smallest tier |
| Object storage | Blob Storage | Standard LRS | Lifecycle policies |
| CDN | Front Door Standard | Pay-as-you-go | Cache static aggressively |
| Secrets | Key Vault | Standard | |
| Email | External ESP | Consumption | Volume cap |
| Monitoring | Azure Monitor + Sentry | 30-day retention | Retention limit |

Non-production: dev on small containers with an out-of-hours sleep schedule; staging as a scaled-down production clone with sanitised data.

### 4.3 Verify before committing

**Azure Container Apps availability in South Africa North must be confirmed, not assumed** ([01 §1.4](01_PRD.md#14-open-decisions-blocking-phase-0-sign-off) #10). Regional service availability changes, and the source material asserts an Azure-everything architecture without checking. If Container Apps is unavailable, **App Service for Containers** in the same region is the documented fallback and changes nothing above the hosting layer.

Confirm the same way for Postgres Flexible Server and Azure Cache for Redis.

### 4.4 Cost guardrails

Adopted wholesale from the source material, which is right about this:

Budget alerts per environment · autoscale caps · log retention limits · backup retention limits · staging sleep schedules · AI token caps per tenant · email volume caps · **CDN egress budget alerts** — the one most likely to surprise, because it scales with success rather than with usage patterns anyone modelled.

### 4.5 Deployment

Four environments: local, dev, staging, production. Terraform, written in Phase 7. GitHub Actions.

Pipeline gates in order: `ruff check` → `ruff format --check` → `mypy src` (strict) → `alembic upgrade head` → `pytest --cov` → **fail if integration tests were skipped** → `alembic downgrade -1 && alembic upgrade head` → `alembic check` → regenerate `packages/api-client` and **fail on diff** → export `openapi.json` → container build and scan → deploy staging → smoke tests → manual approval → deploy production → migrations → health checks.

Rolling deployments with health checks and automatic rollback. Migrations are backward-compatible: add nullable, backfill, constrain — never all three in one release.

---

## 5. Running it

### 5.1 Monitoring

Track: HTTP error rate · API p95 latency · queue depth · payment webhook failures · EFT approval ageing · email delivery failures · **video playback failures and CDN egress** · AI spend · database CPU and storage · container CPU and memory · login failures · certificate generation failures · transcode job failures.

### 5.2 Alerts

| Condition | Threshold |
|---|---|
| Error rate | > 2% for 10 minutes |
| API p95 latency | > 800 ms for 10 minutes |
| Queue backlog | > 500 jobs |
| Payment webhook failure | Any |
| EFT approvals pending | > 48 hours |
| **Invoice sequence gap** | **Any — page immediately** |
| Database storage | > 80% |
| AI spend | Over daily budget |
| CDN egress | Over daily budget |
| Email bounce rate | Over threshold |
| Transcode failures | > 3 consecutive |

The invoice sequence gap alert is the one that must never be routed to a digest. A gap means the allocation transaction is broken, and discovering it from an auditor is not an option.

### 5.3 Log retention

Application logs 30 days hot · access logs 30–90 days · audit events 7 years · financial records per SARS requirement.

### 5.4 Backup and recovery

Managed Postgres automated backups with point-in-time restore · object storage versioning · infrastructure as code · documented secrets recovery · DNS export · tenant configuration export.

| Metric | Target |
|---|---|
| RPO | 15 minutes |
| RTO | 4–8 hours |
| Backup retention | 7–30 days |
| Restore test | **Quarterly** |

An untested backup is not a backup. The restore drill is on the calendar (§7.4), not in someone's intentions.

### 5.5 Scaling triggers

Nothing below is done pre-emptively. Each is a response to a measurement.

| Trigger | Action |
|---|---|
| App CPU > 70% sustained | Raise container max replicas |
| API p95 > 800 ms | Add replicas, then optimise queries |
| DB CPU > 70% sustained | Upgrade tier, then add a read replica |
| Queue lag > 1,000 jobs | Split the worker into its own service |
| Events table growth | Partition weekly instead of monthly |
| Heartbeat volume | Shorten the aggregation window |
| Catalogue search slow | Dedicated search service |
| CDN egress cost | Renegotiate, or tighten the ladder's top rung |
| Enterprise isolation demanded | Dedicated schema per tenant |

Stage 1 is the launch shape: single region, modular monolith, managed Postgres, arq/Redis, external email and AI, self-hosted video, 50–500 learners, ~100 concurrent. Stage 2 adds a read replica, a separate worker service and dedicated search. Stage 3 adds tenant isolation options, multi-region DR and a warehouse.

---

## 6. Cost model

**This does not exist yet, and [05_COMMERCIAL.md](05_COMMERCIAL.md) cannot be quoted until it does.**

Build it in Phase 0, once the content inventory is complete. Required inputs:

| Input | Source | Drives |
|---|---|---|
| Total video hours, current and projected | Phase 0 content inventory | Transcode compute, storage |
| Average learner watch hours per course | Estimate, then measure from Phase 4 | **CDN egress — the dominant variable cost** |
| Concurrent peak by hour | Load test in Phase 7 | Container sizing |
| Emails per learner per month | Campaign plan | ESP tier |
| AI tokens per tenant per month | Phase 6 measurement | AI add-on pricing |
| Facilitator hourly cost | Customer | Workshop credit pricing |
| Gateway fee percentages | Payfast, Netcash | Net revenue per tier |
| Support hours per tier | Customer | "Dedicated account manager" is a salary |

Model gross margin per tier at 50, 200 and 500 learners. A tier that loses money at 500 learners is a growth trap, and Individual Starter at R950 against 40 hours of streamed video is the specific case to check first.

---

## 7. Administrator runbook

### 7.1 Daily

Failed payments and webhooks · **pending EFT approvals** · failed emails · job queue failures · error tracker · new corporate enquiries · AI spend · transcode failures.

### 7.2 Weekly

Backup success · storage usage · database growth · campaign performance · content publishing queue · certificate revocation requests · user access requests · CDN egress against budget.

### 7.3 Monthly

Audit log review · role assignment review · tenant configuration review · tax and invoice export · AI usage and cost · video usage and cost · email deliverability · **invoice sequence integrity confirmation**.

### 7.4 Quarterly

Restore drill · access review · penetration test findings review · subprocessor register review.

### 7.5 Tenant onboarding

1. Create the tenant record.
2. Configure the subdomain; wait for DNS validation and TLS issuance.
3. Upload logo and theme.
4. Configure the content catalogue assignment.
5. Configure privacy settings, including **`allow_manager_individual_results`** — default false.
6. Configure manager visibility defaults per course.
7. Configure SSO if required; test with a real account from the tenant's directory.
8. Create administrator users; enforce MFA.
9. Test login, content access, and a payment path end to end.
10. Enable monitoring and alerting for the tenant.
11. Record support contacts.

### 7.6 Course publishing

1. Course metadata complete.
2. Modules and lessons complete and ordered.
3. Video transcoded, ladder verified, playback tested on a phone.
4. Documents uploaded and readable.
5. Quiz and survey configured; **survey anonymity mode chosen — it cannot be changed after responses exist**.
6. Completion rules set and reviewed.
7. Certificate template assigned.
8. Badge assigned if applicable.
9. Price and package assigned.
10. Tenant visibility set.
11. Analytics events verified firing.
12. Publish.

The publish endpoint runs this list and refuses on any incomplete item ([03 §3](03_API_SPEC.md#3-catalogue-and-content)), so it is a gate rather than a reminder.

---

## 8. Open questions

1. **Container Apps in South Africa North** — verify (§4.3).
2. **CDN provider** — Front Door versus a third party, decided on egress pricing once the content inventory exists.
3. **Transcode compute** — inline in the API worker, or a separate container with more CPU? Depends on the initial catalogue size.
4. **Backup residency** — geo-redundant storage may replicate outside South Africa. Confirm against the residency requirement before enabling it.
5. **Staging data sanitisation** — the procedure for producing a usable but de-identified staging dataset is not yet written.
