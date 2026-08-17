# TTLI_LMS — Resources Hub: Target Design

**Scope:** The full target shape of `/resources` — every content type it should eventually carry, how each maps onto the data model (existing or net-new), and a staged build order. Produced after the nav-redundancy pass that turned "Resources" from a bare podcast list into a real section (`docs/HANDOFF.md`'s 2026-08-17 entry, `apps/web/app/resources/page.tsx`).

**Audience:** Engineering, and whoever owns content strategy for the resource hub next. This is a planning document — the build-now slice is already merged; everything marked **[stage 2+]** is designed but not built.

**Method note:** Every "already built" claim below is checked against the actual code as of 2026-08-17, cited by file path. Every "net-new" claim states exactly what table/endpoint/page it needs so a future pass can scope it without rediscovery.

**Headline:** Of the five content types a resources hub typically carries, **three already had a real data model and just needed a page** (podcasts, curated recommendations, the newsletter via the existing lead/campaign engine) and **two are genuinely new** (long-form articles, a structured "further reading" recommendation list independent of podcast episodes). The stage-1 build shipped the three that existed; stages 2–3 below are the new ones.

---

## 1. Stage 1 — shipped 2026-08-17

What `/resources` (`apps/web/app/resources/page.tsx`) carries today, and why each piece was free or cheap:

- **The podcast** (`.hero-card` "Latest episode" + a rowlist of the rest) — `PodcastEpisode` (`apps/api/src/models/podcast.py`) already distinguishes `kind: "authored" | "curated"`, `show_notes`, `transcript`, `related_course_id`, `curator_name`/`curator_note`. `GET /public/podcasts` and `GET /public/podcasts/{slug}` (`routers/podcasts.py`) already existed; the hub composes them, it adds nothing to the API.
- **What our facilitators recommend** — the same `PodcastEpisode` rows where `kind == "curated"`, filtered client-side. This is the closest thing the codebase has today to a "further reading" list, and it is scoped to podcast-shaped content only (a curated episode is still an episode — it has a slug, a listen/embed path, no article body).
- **The book** (`Lead with Intent`) — static content, already had its own page (`apps/web/app/lead-with-intent/page.tsx`); the hub just links to it.
- **Newsletter signup** — no new subsystem. `POST /leads` (`routers/leads.py`, `LeadRequest` in `schemas/leads.py`) already accepts `marketing_consent`; a newsletter subscriber *is* a lead with that consent set, matching the platform's existing model where `services/campaigns.py` computes segments from lead attributes and checks consent + suppression at send time (`0019`'s migration docstring). Building a parallel "subscriber" table would fork consent handling the campaign engine already gets right.
- **"Where to go next"** — three static cards (guest access, workshops, organisations) with no data dependency; pure navigation.

Nothing above required a migration. The only backend addition in this pass was unrelated (`GET /public/workshops`, for the Live Workshops page built the same day).

---

## 2. Stage 2 — Articles / blog **[net-new]**

The one content type genuinely absent from the data model. No table, no router, no admin authoring surface exists for long-form written content — `grep -ri "article\|blog"` across `apps/api/src/models` returns nothing.

### 2.1 Data model

New table `articles` (tenant-scoped, mirroring `podcast_episodes`' shape rather than `courses`' — articles have no curriculum, no completion rules, no pricing):

```
articles
  id              uuid pk
  tenant_id       uuid fk -> tenants (RESTRICT, like podcast_episodes)
  slug            text, unique per (tenant_id, slug)
  title           text
  dek             text nullable        -- one-line summary, shown in the rowlist/card
  body            text                 -- markdown; rendered client-side, same trust
                                        -- boundary as podcast show_notes/transcript
                                        -- (author-authenticated content, not user input)
  cover_image_object_key  text nullable
  author_name     text nullable        -- free text, not a user FK: TTLI publishes under
                                        -- facilitator names that may not have accounts
  related_course_id  uuid fk -> courses (SET NULL), nullable
  state           content_state        -- reuse the enum courses/podcasts already share
  published_at    timestamptz nullable -- set on transition to published, not on create;
                                        -- this is what "Latest article" sorts on, distinct
                                        -- from created_at (an article can be drafted for
                                        -- weeks before it goes live)
  reading_minutes int nullable         -- computed at publish time from word count,
                                        -- same heuristic course_wizard.py already uses
                                        -- for lesson duration estimates (~200 wpm)
  position        int, server_default 0
```

RLS policy and `app_user` grants follow the exact `0026` (`podcast_episodes`) precedent — `SELECT, INSERT, UPDATE, DELETE`, tenant-isolated.

### 2.2 API

- `POST/GET/PATCH /articles` (admin, `content:manage` or reuse `podcast:manage` — needs a decision, see §4) — same shape as `routers/podcasts.py`'s authoring endpoints.
- `GET /public/articles`, `GET /public/articles/{slug}` — unauthenticated, `state == "published"` only, mirroring `GET /public/podcasts`.

### 2.3 Frontend

- `/resources/articles` (or fold into `/resources` once there's enough volume to need its own listing — start folded in, same pattern the podcast section used before it got its own `/podcasts` page).
- `/resources/articles/[slug]` — `.article` layout (the class already exists in `globals.css`, used by the podcast detail page), reusing `.prose`/`.lead` for the body, a `.gate` lead-magnet block where relevant, and the same Related-programme `.aside-card` pattern `podcasts/[slug]/page.tsx` already has.
- Admin: an authoring screen under `/admin/articles`, structurally copied from `/admin/podcasts` (the existing admin page's own docstring says it was "structurally copied from `admin/catalogue/page.tsx`'s expandable-row convention" — same move again).

### 2.4 Size

Medium. One migration, one router+service+schema trio (all with a close precedent to copy), two public pages, one admin page. No new infrastructure — no upload pipeline is needed since `cover_image_object_key` reuses the storage adapters `services/media/` and `services/podcasts.py` already call.

---

## 3. Stage 3 — Structured "further reading" **[net-new, smaller]**

Distinct from curated podcast episodes: a short list of external links (books, papers, other people's articles) with a one-line editorial note, not full episodes. Today the only "recommendation" surface is a curated podcast episode, which forces every recommendation to be shaped like an episode (has a `duration_seconds`, an embed path) even when it is really "here is an article, go read it."

### 3.1 Data model

New table `recommendations`:

```
recommendations
  id              uuid pk
  tenant_id       uuid fk -> tenants (RESTRICT)
  title           text
  url             text                 -- external
  source_name     text nullable        -- "Harvard Business Review", "the author's own blog"
  curator_name    text nullable        -- same free-text pattern as podcast_episodes.curator_name
  curator_note    text nullable        -- why this is worth reading
  related_course_id  uuid fk -> courses (SET NULL), nullable
  position        int
  state           content_state
```

Smaller than articles — no body, no reading time, no slug (it links out rather than hosting a detail page). A `GET /public/recommendations` list is the whole public surface; no detail route.

### 3.2 Where it surfaces

The resources hub's "What our facilitators recommend" section (currently curated podcast episodes only) becomes recommendations-first once this exists, with curated episodes folding into the same visual list rather than owning a separate section — the distinction between "a recommended podcast episode" and "a recommended article" is a `kind`/`url` difference the reader doesn't need to see as two headings.

### 3.3 Size

Small. One migration, one thin router (list + admin CRUD), no detail page.

---

## 4. Open decisions before building stage 2/3

1. **Permission code.** Reuse `podcast:manage` (articles are the same "content author curates the marketing surface" job) or add `content:manage` as an umbrella that podcast/article/recommendation authoring all move to. The former is zero-migration; the latter is more honest long-term and matches `course:edit`'s precedent of one permission per authoring domain rather than one per table.
2. **Markdown renderer.** `body`/`show_notes`/`transcript` are already stored as plain text and rendered with `white-space: pre-wrap`-style handling (see `podcasts/[slug]/page.tsx`). An article's body is long-form enough that real markdown (headings, lists, links) is worth it — needs a client-side renderer added to `apps/web` (a small dependency, not a backend change).
3. **Whether articles get their own analytics** — the podcast subsystem has six listen-stat event types (`docs/STATUS.md`'s podcast entry). Articles would want at least a "viewed" event for symmetry; decide whether that's stage 2 or a later pass.

None of these block stage 1, which is already shipped and needs no article/recommendation infrastructure to be complete on its own terms.
