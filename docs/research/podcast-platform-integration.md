# TTLI_LMS — Podcast Platform Integration: Data Model, Backend, Frontend and Stats Blueprint

**Scope:** Expanding REQ-STORE-04 (podcast episodes: player, transcript, show notes, related-course CTA) into a full architecture covering (a) whether TTLI's existing podcast content can reuse the video media pipeline or needs a lighter path, (b) Spotify (and other platform) embedding plus admin curation of third-party episodes, (c) a "no frontend bloat" build shape, and (d) podcast engagement statistics capture, consistent with this project's existing event-logging conventions.

**Audience:** Engineering (backend + frontend). Compliance-relevant items (third-party iframe cookies/tracking, POPIA cross-border data) are flagged inline for whoever owns `docs/04_SECURITY_AND_COMPLIANCE.md`, not decided here. Analytics-dashboard-UI items are flagged inline for whoever owns the (separately, concurrently authored) `docs/research/payment-analytics-dashboard.md`, not designed here.

**Method note:** Every claim about the current repo state below was verified by reading the actual files (models, routers, services, admin pages, proxy/CSP config, migrations) as of 2026-08-16 — this is not written from the docs alone. Where the docs (`01_PRD.md`, `02_DATA_MODEL.md`) describe a "not built yet" table, that was independently confirmed against the latest migration (`0024_card_checkout.py`) and the absence of any `podcast`/`resource` model file.

---

## 1. What already exists, verified against the repo

**Confirmed not built:** No `podcast_episodes` or `resources` table/model exists (`apps/api/src/models/` has no such file; latest migration is `0024_card_checkout.py`; no `002x_podcasts.py`). No podcast router, no admin podcasts page. `apps/web/app/page.tsx`'s own docstring confirms the Podcasts page is deliberately unbuilt, blocked on the same content-inventory gap as Phase 0 (`01_PRD.md §1.4`) — this plan does not resolve that content-inventory gap; it is infrastructure for whenever real episode content lands.

**What is reusable, and what is not:**

- `apps/api/src/services/media/` (`pipeline.py`, `ffmpeg.py`, `transcoder.py`, `playback.py`) is the ported VOD ladder from `Streaming_Server`: multi-rendition HLS, signed short-lived playback tokens (`playback.py`'s `mint`/`validate`), concurrent-session caps (REQ-BYPASS-09), heartbeat-driven progress. It exists to solve *premium, gated, anti-bypass-sensitive video* problems — adaptive bitrate switching for long paid content, seek-ceiling enforcement, watermarking. None of that is a real requirement for podcast audio, which is explicitly marketing content meant to be given away (REQ-STORE-03/04, and REQ-STORE-05's "ungated" tier).
- `apps/api/src/services/storage/base.py` already defines `Container.PUBLIC_MARKETING` — a container with a **stable public URL** (`get_public_url`), explicitly the right shape for "never public: premium content... public: marketing" (§2.2). This is the correct target container for self-hosted podcast audio, and it requires none of the signed-URL/token machinery `playback.py` provides.
- `apps/web/app/admin/catalogue/page.tsx` is the concrete admin-CRUD template to follow: `"use client"`, a `useAdmin()` permission gate (`me.permissions.includes(...)`), `authedFetch` through `/api/bff/...`, an expandable-row table, a create form, `PATCH`-based partial updates, server-side error messages surfaced verbatim. `apps/api/src/routers/courses.py`'s `/public/courses/{id}/curriculum` and `/public/lessons/{id}/preview` are the concrete public-unauthenticated-endpoint template (no auth, tenant-resolved via `TenantDep`).
- `apps/api/src/models/event.py` (`Event`, table `events`, monthly-partitioned, first-party in Postgres, REQ-CRM-05/§5.11) is the existing event-logging convention to extend for stats — **not** `audit_events` (`apps/api/src/models/audit.py`'s `AuditAction`), which is reserved for authz/financial/completion-integrity/content-publication actions per its own constant catalogue, not playback telemetry.
- `apps/api/src/core/config.py`'s pattern for optional third-party integrations (`payfast_merchant_id: str = ""`, checked at call time, not at startup) is the template for Spotify credentials: empty by default, feature gracefully degrades to manual entry rather than erroring.
- `apps/web/proxy.ts`'s CSP currently has **no `frame-src` directive** (falls back to `default-src 'self'`) and `connect-src 'self'` — an embedded Spotify iframe or a client-side oEmbed fetch would both be blocked today. This is a required, explicit, narrowly-scoped change (§9).
- The BFF (`apps/web/app/api/bff/[...path]/route.ts`) is a catch-all proxy; its forwarded-header allowlist is header-based, not path-based, so new `/admin/podcasts/*` and `/public/podcasts/*` routes need no BFF changes.

---

## 2. Does TTLI's existing podcast content need the video pipeline, or a lighter path?

**Recommendation: a lighter, standalone path. Do not route podcast audio through `video_assets`/`transcode_jobs`/`playback.py`.**

Reasoning:
1. The transcode ladder exists to solve a problem podcasts don't have: switchable-bitrate video for a large synchronous audience over variable connections, on long-form *paid* content where completion fraud has commercial stakes. A 30–60 minute MP3 is small; there is no adaptive-rendition value in transcoding audio the way there is for video, and REQ-BYPASS's anti-bypass controls (seek-ceiling, concurrent-session caps, heartbeat validation) exist specifically because completion must be provably real for a certificate — podcasts issue no certificate and gate no completion rule.
2. `Container.PUBLIC_MARKETING` already gives a stable public URL with no signed-URL ceremony — exactly matched to "ungated" content per REQ-STORE-05's first tier.
3. Reusing the gated pipeline would import complexity (transcode jobs, HLS manifests, token minting) that actively fights the requirement that most podcast content be freely, permanently linkable and crawlable (SEO — REQ-STORE-06 — and AI-crawler indexability, per the concurrently-researched `devsecops-deployment.md §6.3`'s point that transcripts are exactly the content type that benefits from being crawlable).

**Concrete shape:** a new, small upload path — raw audio file upload (mp3/m4a) → virus-scanned (reuse the existing scan-before-readable pattern already used for assignment uploads, REQ-BYPASS-08) → `ffprobe` (already a system dependency via `ffmpeg.py`) run once for `duration_seconds` only, no rendition ladder, no `transcode_jobs` row → stored directly under `Container.PUBLIC_MARKETING` (or `Container.PRIVATE_CONTENT` + `generate_signed_url` for the rare `access_level=gated` episode) → served by a native HTML5 `<audio>` element. No new arq worker job is needed at launch scale (a handful of episodes); if upload-time `ffprobe` ever becomes slow enough to want async processing, promote it to an arq task later — not a day-one requirement.

Video-format podcast recordings are out of scope for this plan — REQ-STORE-04 frames podcasts as audio with transcript/show notes; a video podcast would use the existing video pipeline unchanged.

---

## 3. Spotify integration and third-party curation

### 3a. Embedding TTLI's own cross-posted episodes

**Recommendation: Spotify's oEmbed endpoint for metadata, a hand-built `<iframe src="https://open.spotify.com/embed/episode/{id}">` for rendering — never inject Spotify's returned HTML blob directly** (that would defeat the CSP nonce discipline `proxy.ts` already enforces, and makes the allow-listed host implicit rather than explicit).

**Recommend also building the full Spotify Web API client-credentials flow** (register a free Spotify Developer app; `POST https://accounts.spotify.com/api/token` with `grant_type=client_credentials`; app-only, no user OAuth, no scopes) because:
- It unlocks "paste a Spotify episode URL, auto-fill title/description/duration/artwork" — a real UX improvement over hand-entry.
- The same credential and the same lookup-by-URL capability is needed anyway for curated third-party episodes (§3b), so it's shared infrastructure, not two integrations.
- It follows the exact graceful-degradation pattern `payfast_merchant_id` already establishes: `spotify_client_id`/`spotify_client_secret` default to `""`, the lookup endpoint returns a clear "not configured, enter manually" response rather than erroring, and nothing else in the codebase needs to branch on whether it's configured.

Apple Podcasts and other platforms: no metadata-autofill API as clean as Spotify's oEmbed/Web API combination exists without scraping. Recommend deferring dedicated Apple Podcasts metadata lookup, but modeling `external_platform` generically (`spotify` / `apple_podcasts` / `other`) so manual URL+iframe embed (`embed.podcasts.apple.com`, no key required) works day one without autofill, and a dedicated connector is an additive follow-up, not a redesign.

### 3b. Curating other hosts' episodes ("recommended by [host]")

This is explicitly a CMS/curation feature, not an embed widget — it needs its own admin add/edit/remove flow and a data-model distinction from TTLI's own content. See §5's `kind` field and curator-attribution columns.

---

## 4. "Without bloating the frontend" — embed vs SDK vs self-host, and the real requirement conflict

**Recommendation: zero new frontend dependencies.** Plain `<iframe>` for every Spotify-sourced player (TTLI's own cross-posted episodes and curated third-party episodes alike) — no SDK, near-zero bundle cost, Spotify's own chrome handles playback. The **Spotify Web Playback SDK is the wrong tool entirely** — it requires a Premium listener's own OAuth and is for building a Spotify client, not embedding a show; do not use it. For self-hosted audio, a native `<audio>` element plus a small amount of React state (play/pause/seek/rate) — do not add a podcast-player npm package; the native element already covers everything needed for a handful of TTLI episodes.

**The real requirement conflict, stated explicitly:** REQ-STORE-04 requires player **+ transcript + show notes + related-course CTA**. Spotify's iframe embed gives you a player and Spotify's own branding/chrome — it does **not** give you transcript text, structured show notes, or a CTA you can render inside it. Embed-only cannot satisfy REQ-STORE-04 as written.

**Recommendation: a hybrid, grounded in that specific conflict, not a generic hedge.**
- For **TTLI's own episodes** (`kind='authored'`): self-host the audio (cheap — no transcoding, per §2) so the LMS fully owns and renders transcript, show notes, and an in-page related-course CTA button — the actual requirement — and additionally show a "also on Spotify" embed/badge linking out, for cross-platform discovery and to inherit Spotify's existing follower/social-proof equity. Neither embed-alone (fails the transcript/show-notes/CTA requirement) nor self-host-alone (throws away already-built Spotify distribution) satisfies the actual ask; the hybrid does both.
- For **curated third-party episodes** (`kind='curated'`): embed-only is correct and sufficient. TTLI doesn't own that show's transcript or notes and has no right to fabricate them — the `curator_note` field ("why recommended") is the substitute for show notes here, by design, not an oversight.

---

## 5. Data model — revising `02_DATA_MODEL.md §5.6`'s `resources`/`podcast_episodes` starting point

Scope note: this plan builds `podcast_episodes` only. The sibling `resources` table (REQ-STORE-03's resource hub) is a related but distinct, still-unbuilt feature — not conflated here.

**`podcast_episodes`** — tenant-scoped (`TenantMixin`), unlike the global `courses` table: podcast curation is tenant-specific marketing content (closer to `leads`/`campaigns` than to the shared course catalogue), and different tenants will plausibly curate differently once multi-tenant marketing content matures (`02 §1.3`'s carve-out is for *shared catalogue* rows specifically; this isn't one).

| Column | Type | Notes |
|---|---|---|
| `id` | uuid7 PK | |
| `tenant_id` | uuid FK | `TenantMixin`, RLS |
| `kind` | text (`authored` \| `curated`) | Distinguishes TTLI's own episodes from externally curated ones — the core new distinction the product owner asked for |
| `slug` | text, unique per tenant | |
| `title`, `description` | text | |
| `state` | reuse `ContentState` enum (`draft`/`in_review`/`approved`/`published`/`archived`) | Same publishing workflow as `courses` (REQ-ADMIN-02) — no new enum |
| `access_level` | reuse `AccessLevel` enum (`public`/`gated`/`guest`/`paid`/`corporate`) | REQ-STORE-05's three tiers map onto the existing enum already used by `lessons.access_level` — no new enum |
| `show_notes` | text, nullable | Populated for `authored`; not required for `curated` |
| `transcript` | text, nullable | Populated for `authored` only — REQ-STORE-04's literal requirement |
| `related_course_id` | uuid FK → `courses.id`, nullable | The conversion CTA target |
| `audio_object_key` | text, nullable | `Container.PUBLIC_MARKETING` or `PRIVATE_CONTENT` key; null for `curated` (embed-only) |
| `duration_seconds` | integer, nullable | From `ffprobe` on upload, or from Spotify metadata lookup |
| `cover_image_object_key` | text, nullable | `Container.PUBLIC_MARKETING` |
| `external_platform` | text, nullable (`spotify`/`apple_podcasts`/`other`) | Which platform `external_url`/`external_embed_id` point to |
| `external_url` | text, nullable | Canonical episode page (e.g. `open.spotify.com/episode/...`); the "listen on Spotify" link for `authored`, the primary listen path for `curated` |
| `external_embed_id` | text, nullable | Parsed Spotify episode ID, cached so the iframe `src` isn't re-parsed from `external_url` on every render |
| `curator_name` | text, nullable | Populated for `curated` only — the "recommended by [host]" attribution |
| `curator_note` | text, nullable | "Why recommended" — the `curated` substitute for `show_notes` |
| `position` | integer, nullable | Manual ordering, same convention as `modules.position`/`lessons.position` |
| `created_at`/`updated_at` | `TimestampMixin` | |

Validation (app-level, Pydantic, matching the project's existing `completion_rules`-style soft-validation convention rather than a DB `CHECK`): `kind='curated'` requires `external_url` + `curator_name`; `kind='authored'` requires either `audio_object_key` or an eventual Spotify cross-post link, and permits `transcript`/`show_notes`.

No changes needed to `AccessLevel`/`ContentState` — both enums are reused as-is, matching this project's stated preference for closed-set Postgres enums where the set is stable (`02 §3`).

---

## 6. Statistics: event shape, storage, and the explicit hand-off to the analytics dashboard

**Follow the existing `events` table (`apps/api/src/models/event.py`), not a new bespoke table and not `audit_events`.** `audit_events`' `AuditAction` catalogue is reserved for authz/financial/completion-integrity/content-publication actions; podcast playback is exactly the kind of first-party marketing telemetry `events` already exists for (REQ-CRM-05, `01 §5.11`). New rows are just new `event_name` values through whatever ingestion path `events` already uses, carrying `tenant_id`, `anonymous_id`/`user_id` (nullable), `session_id`, `consent_marketing`/`consent_analytics` captured on the row per the existing convention.

Proposed `event_name` values and `event_properties` shape:

| `event_name` | `event_properties` | Purpose |
|---|---|---|
| `podcast.episode.viewed` | `{episode_id, kind}` | Funnel top — detail page loaded |
| `podcast.play.started` | `{episode_id, kind, source: "self_hosted"\|"spotify_embed"}` | Play begun |
| `podcast.play.progress` | `{episode_id, percent_complete, position_seconds}` | Coarse checkpoints (25/50/75/100%) — deliberately **not** a `video_heartbeats`-style 10-second-interval table: there is no completion rule engine consuming this and no anti-bypass concern, so a full heartbeat table would be unjustified complexity for ungated marketing content |
| `podcast.play.completed` | `{episode_id, percent_complete ≥ ~90}` | |
| `podcast.embed.click_through` | `{episode_id, external_platform}` | Distinguishes an external-embed click-through from a self-hosted full play, per the product owner's explicit ask |
| `podcast.cta.course_clicked` | `{episode_id, related_course_id}` | The actual conversion signal REQ-STORE-04 exists for |

**Explicit note for whoever reconciles this with `docs/research/payment-analytics-dashboard.md` once it lands:** these `event_name` values should surface as a "Podcast engagement" panel on the future admin analytics dashboard (plays, completion rate, click-through rate, top CTA-converting episodes toward course purchases) — reading from the same `events` table the payment dashboard will likely also query. This plan does not design that dashboard UI; it only guarantees the data is captured in the shape the dashboard will expect.

Admin curation actions (episode published/unpublished/added/removed) **do** warrant a new `AuditAction` constant (e.g. `PODCAST_PUBLISHED`), matching `courses`' publish/unpublish audit trail under REQ-ADMIN-03's "content publication" category — this is a content-workflow action, not playback telemetry, so it belongs in `audit_events`, not `events`.

---

## 7. Backend endpoints

**Public** (tenant-resolved via `TenantDep`, no auth for ungated — mirrors `courses.py`'s `/public/courses/{id}/curriculum` pattern):
- `GET /public/podcasts` — published episodes, cursor-paginated, filterable by `kind`/`access_level`
- `GET /public/podcasts/{slug}` — episode detail; for `access_level=gated`, returns a reduced payload (title/summary/cover) until unlocked
- `GET /public/podcasts/{slug}/audio` — resolves to a stable public URL redirect (ungated, `PUBLIC_MARKETING`) or a signed-URL redirect (gated, `PRIVATE_CONTENT`, reusing `generate_signed_url` — not `playback.py`'s token minting, which is HLS-specific)
- `POST /public/podcasts/{slug}/events` — logs the §6 event set; rate-limited at the existing anonymous tier (60/min, `03_API_SPEC.md §1.8`)

**Admin** (new `podcast:manage` permission string, matching the `product:manage`/`course:edit` convention):
- `GET /admin/podcasts`, `POST /admin/podcasts`, `PATCH /admin/podcasts/{id}` (with `If-Match`, per §1.7's optimistic-concurrency convention), `POST /admin/podcasts/{id}/publish` / `/unpublish` — mirrors `courses.py` exactly; no hard `DELETE`, only `state=archived` per REQ-ADMIN-02's workflow
- `POST /admin/podcasts/upload-audio` — multipart upload, virus-scanned, `ffprobe`-probed, no transcode job
- `GET /admin/podcasts/spotify-lookup?url=...` — server-side Spotify Web API call (client-credentials token, Redis-cached until near-expiry, same `httpx.AsyncClient` pattern already used in `services/payments/payfast.py`); returns `{title, description, duration_seconds, image_url, release_date}` to prefill the admin form, or a clear "not configured" response if `spotify_client_id` is empty

---

## 8. Frontend structure — no new dependencies

**Public:**
- `apps/web/app/podcasts/page.tsx` — server component, SSR list (own + curated sections), satisfies REQ-STORE-06's SEO requirement with zero client JS for the list itself
- `apps/web/app/podcasts/[slug]/page.tsx` — server component for transcript/show-notes/CTA (SSR — deliberately crawlable, unlike gated course content), with one small `"use client"` leaf (`PodcastPlayer.tsx`) for interactive audio — matching the existing convention of isolating client islands (e.g. `contact/page.tsx`'s form) rather than making the whole page client-rendered
- `SpotifyEmbed.tsx` — a plain `<iframe src="https://open.spotify.com/embed/episode/{id}">` in a fixed-aspect-ratio wrapper, click-to-load (see §9's compliance flag) with a click-through event listener
- Gated-episode unlock reuses the existing lead-capture pattern (`POST /leads`, `source="podcast_gate"`, same shape as `contact/page.tsx`'s `source="contact_form"`)

**Admin:**
- `apps/web/app/admin/podcasts/page.tsx` — new file, structurally identical to `apps/web/app/admin/catalogue/page.tsx`: `useAdmin()` permission gate, `authedFetch` via `/api/bff/podcasts`, expandable-row table, create form with a "Look up from Spotify URL" prefill button next to `external_url`

---

## 9. CSP, BFF and a compliance flag not decided here

- `apps/web/proxy.ts`: add `frame-src https://open.spotify.com` (and `https://embed.podcasts.apple.com` when/if Apple embeds are added) — currently absent, so `default-src 'self'` blocks any iframe today. This is a required, narrowly-scoped change.
- Spotify Web API calls happen server-side only (`apps/api`, `httpx.AsyncClient`), never from the browser — so `connect-src 'self'` needs **no** change. This is also the leaner choice: zero new `script-src`/`connect-src` surface, only the one `frame-src` addition.
- BFF (`apps/web/app/api/bff/[...path]/route.ts`): no changes — the allowlist is header-based, not path-based; new routes ride the existing catch-all.
- **Compliance flag, not decided here (route to whoever owns `04_SECURITY_AND_COMPLIANCE.md`):** loading `open.spotify.com` in an iframe causes the visitor's browser to fetch a resource directly from Spotify, which plausibly sets cookies/does device fingerprinting independent of any TTLI account — in tension with `01_PRD.md §5.11`'s explicit "no third-party tracker" stance and REQ-STORE-07's "cookie/marketing consent before any non-essential tracking." No cookie-consent banner component exists yet in the repo to gate this against. **Recommended safe default pending that sign-off:** render `SpotifyEmbed.tsx` as a static thumbnail + "load Spotify player" button, injecting the iframe only on explicit click (a self-contained mitigation that works regardless of whether/when a consent-banner system is built) — flagged as a recommendation, not a final compliance decision.

---

## 10. Build sequence

- [ ] Migration: `podcast_episodes` table + RLS policy (mirrors `leads`/`events` tenant-scoped pattern) + `podcast:manage` permission row
- [ ] Backend: `models/podcast.py`, Pydantic schemas, `services/podcasts.py` (audio upload + virus scan + `ffprobe`, publish/unpublish, CRUD)
- [ ] Backend: public router (`/public/podcasts*`) + admin router (`/admin/podcasts*`), both registered in the router `__init__`
- [ ] Backend: Spotify client-credentials service (`services/spotify.py`, `httpx.AsyncClient`, Redis-cached token) + `GET /admin/podcasts/spotify-lookup`; `spotify_client_id`/`spotify_client_secret` added to `config.py`, empty-default
- [ ] Backend: `events` ingestion path extended with the §6 `event_name` values (or confirm/reuse whatever existing ingestion endpoint REQ-CRM-05 already ships)
- [ ] `packages/api-client` regeneration (CI gate, per `01_PRD.md §7`)
- [ ] `proxy.ts`: add `frame-src https://open.spotify.com`
- [ ] Frontend: `apps/web/app/podcasts/page.tsx`, `[slug]/page.tsx`, `PodcastPlayer.tsx`, `SpotifyEmbed.tsx` (click-to-load)
- [ ] Frontend: `apps/web/app/admin/podcasts/page.tsx`
- [ ] Demo: publish one `authored` episode with self-hosted audio + transcript + CTA, publish one `curated` episode via Spotify-URL-paste autofill, verify both play, verify events land in `events`, verify a gated episode requires lead capture before unlocking

---

## 11. Explicit open questions / assumptions

1. **Gated-episode unlock mechanism** (REQ-STORE-05's "gated" tier) is not yet implemented anywhere in the repo for *any* content type — this plan proposes reusing `POST /leads` + a short-lived unlock grant, but that mechanism should be shared with the still-unbuilt resource hub (REQ-STORE-03) rather than invented twice; flag for whoever builds that hub first.
2. Whether `apps/api` already has a generic first-party event-ingestion endpoint (vs. events written only from specific server-side actions today) was not exhaustively confirmed — `POST /public/podcasts/{slug}/events` above assumes a thin wrapper exists or is added; verify against the actual `events`-writing call sites during implementation.
3. Content-inventory gap: this plan is infrastructure only — real TTLI episode data (audio files, transcripts, Spotify links) is still blocked on the same Phase 0 content-inventory item `page.tsx`'s docstring already flags.
4. Spotify Developer app registration (client ID/secret) is an operational task for whoever owns hosting credentials, not an engineering blocker — the empty-default pattern means the feature ships functional (manual entry) without it.

---

*Researched August 2026 against the TTLI_LMS repository as it exists on this date — re-verify against current model/router state before implementation if time has passed.*
