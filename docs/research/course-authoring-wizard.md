# TTLI_LMS — Course Create & Upload Wizard: Planning Report

**Scope:** A wizard-type, admin-facing "create a course and upload its content" workflow — easy to drive, easy to manage, resumable — plus the differentiator features worth adding on top, ranked by value against effort. Then an alignment pass: for each wizard element and differentiator, how much of it the codebase already has (built / partial / missing).

**Audience:** Engineering (backend + frontend). This is a planning report, not a build — nothing in the repo was modified in producing it.

**Method note:** Every claim about current repo state was verified by reading the actual files (models, routers, services, admin pages, migrations, `docs/STATUS.md`, `docs/HANDOFF.md`, `docs/01_PRD.md`) as of 2026-08-16, by a read-only sub-agent dispatched for the purpose. File paths are cited throughout so each claim can be re-checked.

**Headline finding:** of 22 wizard elements, **11 are already built, 7 are partial, 4 are missing.** Every step's persistence and permission model exists today. The genuinely new backend surface is small and additive (2 delete endpoints, 2 atomic-reorder endpoints, 1 readiness endpoint, 1 duplicate endpoint, detach/clear-FK semantics — no new tables). The dominant work is frontend composition around ~1,470 lines of proven authoring components, plus surfacing two backend capabilities that are currently UI-dark (completion rules, certificate/badge template attachment).

---

## 1. Current state map

### 1.1 Backend — content model and authoring

**Model** (`apps/api/src/models/course.py`): `Course` / `Module` / `Lesson` are **global, not tenant-scoped** (02 §1.3); `CourseTenantAssignment` is the per-tenant visibility join. Key fields:

- `Course`: `slug` (unique), `title`, `description`, `state` (enum `draft / in_review / approved / published / archived` — **only `draft` and `published` are reachable via endpoints today**; `in_review`/`approved`/`archived` exist in the DB enum but nothing sets them), `manager_visibility`, `completion_rules` (JSONB, validated on write against `CompletionRules` in `services/completion.py`), `certificate_template_id`, `badge_template_id`.
- `Module`: `course_id`, `title`, `position`.
- `Lesson`: `module_id`, `title`, `position`, `activity_type` (`document`/`video`/`quiz`/`survey`/`assignment`), `access_level` (`public`/`gated`/`guest`/`paid`/`corporate` — `public` = free preview), `body` (document text), one nullable FK per subsystem (`video_asset_id`, `quiz_id`, `survey_id`, `assignment_id`), per-lesson `completion_rules` override (merged per-field with the course default).

**Authoring API** (`apps/api/src/routers/courses.py`, `src/services/courses.py`):
- `POST/GET/PATCH /courses`, `GET /courses/{id}` — create auto-slugs with uniqueness suffixing; PATCH accepts title/description/completion_rules/certificate_template_id/badge_template_id.
- `POST /courses/{id}/publish` — **validates structure**: at least one module, every module at least one lesson (`CourseAuthoringError` with a human message). `unpublish` → back to draft.
- `POST /courses/{id}/modules`, `GET .../modules`, `PATCH /modules/{id}` (title, **position**).
- `POST /modules/{id}/lessons`, `GET .../lessons`, `PATCH /lessons/{id}` (title, access_level, body, completion_rules, **position**). New lessons always start as `document`; activity FKs are owned by each subsystem's attach endpoints (explicit design note in the service docstring).
- `POST /courses/{id}/tenant-assignments` (only published courses assignable), `GET /tenant-assignments`.
- Public, unauthenticated: `GET /public/courses/{id}/curriculum` (shape only) and `GET /public/lessons/{id}/preview` (only `access_level="public"` lessons of published+assigned courses).

**Notable API gaps** (verified): **no DELETE for course/module/lesson**, no archive endpoint, no atomic reorder (position PATCH is per-item, no sibling renumbering), no way to **clear** a template FK (`update_course` treats `None` as "unchanged"), no detach endpoints for quiz/survey/assignment/video (a lesson can never go back to `document`).

**Permissions** (`alembic/versions/0002_seed_roles_and_tenants.py`, `0022`, `0026`): `course:view` (held by learners — security-sensitive: STATUS §9b records that quiz answer keys must never sit behind it), `course:edit` (all authoring incl. quizzes/media), `course:publish` (publish/unpublish/tenant-assign), `quiz:grade` (grading + assignment review), `product:manage` (pricing — admin/super_admin only, deliberately **not** content_author; enforced by `test_content_author_cannot_price_products`), `podcast:manage`.

### 1.2 Content upload / media pipeline

(`apps/api/src/routers/media.py`, `src/services/media/{ffmpeg,transcoder,pipeline,playback}.py`, `src/services/storage/`)

- **Upload is direct multipart through the BFF into API memory** (`await file.read()`), ClamAV-scanned fail-closed (`services/antivirus.py`), stored to `Container.PRIVATE_CONTENT`, then an arq job (`transcode_video_job`) runs a real ffmpeg HLS ladder (ported from Streaming_Server). State machine: `uploaded → transcoding → ready | failed`, polled via `GET /video-assets/{id}`.
- `GET /video-assets` lists assets (id, state, duration_seconds, has_captions) for the "attach existing" path.
- Captions: `POST /video-assets/{id}/captions`, human-authored WebVTT only — **the code explicitly declines ASR** ("no ASR pipeline exists... fabricating caption text would be worse than no captions").
- Playback: signed short-lived token in query string, manifest rewriting, Redis concurrent-session cap, watermark payload, heartbeat/seek-ceiling anti-bypass.
- Storage adapters Local/S3(Garage)/Azure (`services/storage/`); `generate_signed_url` exists (S3 presign at `storage/s3.py:108`) but is used only for **downloads** (assignment submission download, certificate PDF). **No presigned-upload path exists** — a practical size ceiling since video uploads are fully buffered in the BFF and API.
- Podcast audio is a deliberately separate, lighter path (`services/podcasts.py` — one ffprobe call, public container, no ladder).

### 1.3 Assessments, credentials, pricing

- **Quiz/survey/assignment authoring** (`routers/assessment.py`): full create + question-add + lesson-attach + admin list/detail (`GET /quizzes`, `GET /quizzes/{id}` with correct-flags, `GET /surveys`, `GET /assignments`, `GET /assignments/{id}`), learner attempt/submit/grade flow, preview endpoints (`GET /quizzes/{id}/preview`, `GET /assignments/{id}/preview`), grading queues (`GET /quiz-answers/ungraded`, `GET /assignment-submissions/pending`, signed `/download`).
- **Credential templates** (`routers/credentials.py:285-380`): certificate templates (title, issuer_name, signatory name/title, cpd_points) and badge templates (title, criteria, issuer_name, level) — create/list/patch. Issuance is automatic on completion, no direct endpoint (by design).
- **Pricing** (`routers/catalogue.py`, `services/catalogue.py`): admin `/catalogue/*` — product create (inactive), attach course (validates tenant assignment), add/delete prices, activate (refused with zero prices), `GET /catalogue/sellable-courses` with `already_sold_as`. Fulfilment bridge `Product.course_id → entitlement → enrolment` already live in `services/orders.py`. Subscriptions (`0021`) bundle courses into plans.
- **Completion rule engine** (`services/completion.py`): `minimum_time_seconds`, `video_watch_percentage`, `quiz_pass_score`, `survey_required`, `assignment_approval_required` all backed; `live_attendance_required` still refuses with "not available". Rules referencing missing subsystems fail loudly, never skip.

### 1.4 Frontend — admin authoring today

- **`apps/web/app/admin/courses/page.tsx`** (507 lines): one single-page master-detail screen — create-course form → course chips → publish/unpublish + tenant-assign buttons → add-module form → module chips → add-lesson form (title, access level, body) → lesson table (access-level dropdown inline) → "Manage content" opens…
- **`apps/web/app/admin/courses/lesson-activity-panel.tsx`** (964 lines): 4-tab quiz/survey/assignment/video panel; each tab has "attach existing" (dropdown) and "create new"; quiz/survey question builder (type select, prompt, points, dynamic option rows with correctness marking); video tab has a 5-phase upload state machine (`idle → uploading → polling → ready | failed`) with 4s transcode polling and WebVTT caption upload.
- **`/admin/templates`** (308 lines): create/list certificate and badge templates. **No UI anywhere attaches a template to a course** — zero references to `certificate_template`/`badge_template` in `apps/web/app`; the `PATCH /courses/{id}` capability is dark.
- **`/admin/catalogue`**: draft product → attach course → price → activate, one screen. **`/admin/subscriptions`**: plan + bundle editor. **`/admin/grading`**: two FIFO queues. **`/admin/workshops`, `/admin/podcasts`**: separate subsystems.
- **`/preview/[lessonId]`** (`apps/web/app/preview/[lessonId]/page.tsx`): real, working free-preview page — document renders unauthenticated; video/quiz/survey/assignment previews render for any signed-in account. **Only works for `access_level="public"` lessons of published, tenant-assigned courses** — useless for an author previewing a draft.
- **No completion-rules UI at all** — zero references to `completion_rules` in `apps/web`; the entire rule engine (the platform's signature anti-bypass feature) is authorable only via raw API.
- **No reordering UI** — `position` is displayed read-only; the PATCH-position primitive is dark.
- Transport: everything goes through the BFF proxy (`app/api/bff/[...path]/route.ts`, binary-safe via `arrayBuffer()`), bearer access token + HttpOnly refresh cookie with cross-tab lock (STATUS §9b item 4).

### 1.5 Docs / spec sources

`docs/01_PRD.md` (REQ-* codes source: REQ-LMS-*, REQ-BYPASS-*, REQ-CRED-*, REQ-STORE-*, plus the 10 open Phase-0 decisions in 01 §1.4), `docs/02_DATA_MODEL.md` (02 §5 content model), `docs/03_API_SPEC.md`, `docs/STATUS.md` (§9b frontend backlog — items 1–5 all shipped), `docs/HANDOFF.md`, `docs/research/`. Relevant decisions: **SCORM/xAPI (#1) is explicitly out of scope**; content inventory (video counts/formats) is still an unclosed customer gap.

**Crucial architectural fact for the wizard:** a course is invisible and unsellable until it is `published` AND tenant-assigned AND wrapped in an active priced product. So a wizard can write real rows at every step with zero risk of leaking half-finished content — **no "wizard session" or staging store is needed; `state="draft"` already is the draft mechanism, and autosave is inherent because every step is a real API write.**

---

## 2. Wizard design

Proposed route: `apps/web/app/admin/courses/new/page.tsx` (stepper), with `/admin/courses/[courseId]/edit` re-entering the same stepper for an existing course. The existing `/admin/courses` page becomes the list/manage view linking into it.

### Step 1 — Basics (`course:edit`)
- **Reuses as-is:** `POST /courses` (auto-slug), `PATCH /courses/{id}`.
- **Small additions:** none strictly required. Optional (one migration): `thumbnail_url` / `estimated_minutes` / `tags` on `Course` — nothing like them exists; the catalogue card today shows only title/description.
- **Frontend:** simple form; on first save the course id anchors the whole wizard (URL becomes `/admin/courses/{id}/edit?step=2` — resumability for free).

### Step 2 — Curriculum structure (`course:edit`)
- **Reuses as-is:** `POST /courses/{id}/modules`, `POST /modules/{id}/lessons`, `PATCH /modules/{id}` / `PATCH /lessons/{id}` (rename, position).
- **Backend additions (small):**
  - `DELETE /modules/{id}` and `DELETE /lessons/{id}` (DB cascade already `ON DELETE CASCADE`; guard: refuse deleting a lesson with existing `lesson_completions`, or soft-block on published courses). Today a typo'd module is permanent.
  - `POST /courses/{id}/modules/reorder` + `POST /modules/{id}/lessons/reorder` taking an ordered id list and renumbering atomically in one transaction — the per-item position PATCH can't do this safely (sequential PATCHes race and can duplicate positions, and prerequisite order is `(module.position, lesson.position)` in `services/enrolment.py`, so order is learner-facing correctness, not cosmetics).
- **Frontend:** outline tree with drag-and-drop (differentiator #6).

### Step 3 — Content per lesson (`course:edit`)
- **Reuses as-is:** everything in `lesson-activity-panel.tsx` — document body via `PATCH /lessons/{id}`; video via `POST /video-assets` → poll `GET /video-assets/{id}` → `POST /lessons/{id}/video`; captions via `POST /video-assets/{id}/captions`. The panel should be extracted/reused, not rewritten (964 lines of proven logic incl. the FormData/content-type and `video_asset_id` param subtleties documented in STATUS §9b item 2).
- **Backend additions (small):** detach endpoints (or let attach endpoints accept null) so a lesson can revert to `document`; today attach is one-way.
- **Frontend additions:** upload progress bars (the current `fetch` upload has no progress events — XHR or streamed fetch through the existing BFF), and an aggregate "n videos still transcoding" strip so the admin keeps working while ffmpeg runs (states already served by `GET /video-assets`).

### Step 4 — Assessments & completion rules (`course:edit`)
- **Reuses as-is:** quiz/survey/assignment builders (same panel); grading is downstream (`/admin/grading`).
- **Net-new frontend, zero backend:** a **completion-rules builder** — course-level defaults here, per-lesson overrides in step 3. The whole engine (`services/completion.py`, validation in `courses_service._validate_completion_rules`) exists and is UI-dark. Fields: minimum time, watch %, quiz pass score, survey required, assignment approval. Server already rejects invalid shapes with specific messages.

### Step 5 — Certification (`course:edit`)
- **Reuses as-is:** `GET/POST /certificate-templates`, `GET/POST /badge-templates` (`routers/credentials.py`), and `PATCH /courses/{id}` with `certificate_template_id`/`badge_template_id` — **fully built API, zero UI today**; almost pure frontend (pick or inline-create a template, attach).
- **Backend fix (tiny):** `update_course` cannot clear a template FK (None = unchanged) — add explicit-null semantics so "no certificate" is choosable after attaching one.

### Step 6 — Pricing & access (`course:publish` + `product:manage`)
- **Reuses as-is:** `POST /courses/{id}/publish` must precede tenant assignment (service enforces it); `POST /courses/{id}/tenant-assignments`; `GET /catalogue/sellable-courses` (with `already_sold_as` to prevent accidental duplicates); `POST /catalogue/products` → `POST .../prices` → `PATCH` activate (guard: no activation without a price — already enforced); optionally add to a subscription bundle (`/admin/subscriptions` endpoints); free-preview selection = flipping one lesson's `access_level` to `public` (already inline-editable).
- **Permission split matters:** a `content_author` holds `course:edit` but **not** `course:publish` or `product:manage`. The wizard must render steps 6–7 as "hand off to an admin" (with a summary of what's ready) when the caller lacks them — mirroring server truth, same convention every admin page already follows.

### Step 7 — Review & publish (`course:publish`)
- **Reuses:** the validation already inside `publish_course` (module/lesson non-emptiness).
- **Backend addition (small, high value):** `GET /courses/{id}/readiness` — extract `publish_course`'s checks into a shared readiness function and extend it: every video lesson's asset `state == "ready"`; every quiz lesson's quiz has ≥1 question; completion rules referencing a subsystem actually have that activity attached; captions present (warning, not blocker — WCAG posture); certificate template attached (warning); tenant assigned; active priced product exists (or "not sellable yet" warning). Return `{blockers: [...], warnings: [...], score}`. Publish stays server-enforced; the endpoint just makes the same truth visible before the button.
- **Frontend:** checklist rendering + the existing publish/assign calls + link to `/preview/[lessonId]` per lesson.

---

## 3. Differentiators (ranked by value ÷ effort)

| # | Feature | Value | Effort | Grounding |
|---|---|---|---|---|
| 1 | **Course readiness checklist / score** | High (admin: no dead publishes; learner: no broken lessons) | **Low** — one endpoint refactored out of `publish_course` + checks over already-queryable data | `services/courses.py:126-138` already half-builds it |
| 2 | **Resumable draft wizard, autosave for free** | High | **Low** — no new state store; every step is a real write; "Continue setup" computes the furthest incomplete step from existing GETs; a "Draft courses" section on `/admin/courses` lists `state="draft"` rows (already returned) | Architecture already draft-safe (§1.5) |
| 3 | **Completion-rules builder UI** | High — the anti-bypass engine is the platform's signature and is un-authorable without curl | **Low-Med** — pure frontend + existing validation | `services/completion.py`; zero web references today |
| 4 | **Author draft preview** ("view as learner") | High | **Low-Med** — `/preview/[lessonId]` exists; add a `course:edit` bypass of the published/public constraints in `get_public_lesson_preview` (exact precedent: the `course:edit` fast-path added to `GET /surveys/{id}`, STATUS §9b item 1) | `courses_service.get_public_lesson_preview:326` |
| 5 | **Transcode status strip + non-blocking uploads** | Med-High | **Low** — states already served; add progress via XHR | `GET /video-assets`, panel's polling loop |
| 6 | **Drag-and-drop curriculum reorder** | High (admin) | **Med** — needs the atomic reorder endpoints (Step 2) + a dnd frontend (no dnd lib in `apps/web` today; native HTML5 DnD or dnd-kit) | position primitives exist; prerequisite chain makes order learner-facing |
| 7 | **Duplicate course as template** | Med-High (real TTLI shape: same course, bespoke tenant variants) | **Med** — `POST /courses/{id}/duplicate`: walk course→modules→lessons in one transaction; share `video_asset_id` FKs (assets are global), deep-copy quizzes/surveys/assignments; new slug via existing `_unique_slug`; result is `draft` | All reads/writes exist as service functions |
| 8 | **Completion-time estimates** | Med (learner-facing trust; feeds catalogue) | **Low-Med** — video `duration_seconds` already stored; documents via word count; quizzes via question count; sum surfaced on `GET /public/courses/{id}/curriculum` and the readiness screen | `VideoAsset.duration_seconds`, curriculum endpoint |
| 9 | **Free-preview nudge** | Med (funnel: preview → guest → lead is already built end-to-end) | **Low** — readiness warning "no lesson is marked public; free previews convert" + one-click flip | STATUS §9c free-preview infrastructure |
| 10 | **Bulk/zip content upload** (folder → modules/lessons) | Med | **Med-High** — feasible (unzip server-side, per-file ClamAV, create structure), but uploads are fully memory-buffered today; large zips want a presigned-upload path first (`generate_signed_url` exists for S3 but no upload variant, and Local/Azure parity needed) | `storage/s3.py:108`; memory-buffered `upload_video_asset` |
| 11 | **Auto-transcripts/captions (ASR)** | Med | **High + policy-blocked** — codebase explicitly declines ASR (`routers/media.py:137-139`); collides with the data-residency posture behind 01 §1.4 decision #4. Post-Phase-0 option, not wizard scope | media.py comment |
| 12 | **SCORM import** | — | **Do not build** — PRD decision #1 explicitly out of scope | 01 §1.4 |

---

## 4. Alignment analysis

| Wizard element | Status | Detail |
|---|---|---|
| Course create/edit (basics) | **ALREADY BUILT** | `routers/courses.py`, `services/courses.py`, existing form in `admin/courses/page.tsx` |
| Draft/publish lifecycle | **ALREADY BUILT** | `state` draft/published + publish validation (`in_review`/`approved`/`archived` enum values idle — optional future review step) |
| Module/lesson create/rename | **ALREADY BUILT** | courses router/service |
| Module/lesson **delete** | **MISSING** | no DELETE endpoints anywhere |
| Reordering | **PARTIAL** | per-item `position` PATCH exists; no atomic reorder endpoint, no UI |
| Video upload + transcode + poll + captions | **ALREADY BUILT** | `routers/media.py` + `lesson-activity-panel.tsx` video tab |
| Upload progress / large-file path | **PARTIAL** | works but memory-buffered, no progress events, no presigned upload |
| Quiz/survey/assignment authoring + attach | **ALREADY BUILT** | `routers/assessment.py` + panel tabs |
| Detach / revert lesson to document | **MISSING** | attach is one-way |
| Completion-rules engine | **ALREADY BUILT** (backend) / **MISSING** (UI) | `services/completion.py`; zero frontend references |
| Certificate/badge template CRUD | **ALREADY BUILT** | `routers/credentials.py`, `/admin/templates` |
| Template → course attachment | **PARTIAL** | API built (`PATCH /courses/{id}`), no UI; cannot clear once set |
| Tenant assignment | **ALREADY BUILT** | endpoint + button on courses page |
| Product + pricing + activation guards | **ALREADY BUILT** | `/catalogue/*` + `/admin/catalogue` (incl. sellable-courses picker) |
| Subscription bundling | **ALREADY BUILT** | `0021`, `/admin/subscriptions` |
| Free-preview lessons | **ALREADY BUILT** | `access_level="public"` + `/preview/[lessonId]` + public curriculum |
| Author draft preview | **PARTIAL** | preview route exists; blocked for drafts/non-public lessons — needs `course:edit` bypass |
| Readiness checklist | **PARTIAL** | publish-time structural checks exist server-side; no queryable report, no content-level checks |
| Resumable wizard/autosave | **PARTIAL** (effectively free) | all persistence exists; only the stepper shell + furthest-step derivation are new |
| Duplicate-as-template | **MISSING** | net-new clone endpoint |
| Time estimates | **PARTIAL** | video durations stored; aggregation + display new |
| Wizard stepper UI itself | **MISSING** | net-new frontend route composing existing components |

**Summary count:** of 22 elements — **11 ALREADY BUILT, 7 PARTIAL, 4 MISSING.**

---

## 5. Suggested build order

1. **API pass, one change set with tests:** readiness endpoint + delete/reorder/clear-template/detach backend additions (no new tables).
2. **Wizard shell + steps 1/2/6/7** (all reuse).
3. **Steps 3/5** including `lesson-activity-panel.tsx` extraction and template attachment.
4. **Completion-rules builder** (step 4).
5. **Differentiators 4–8** in ranked order.

Conventions to honour throughout (all already established in `docs/HANDOFF.md` §5): BFF-only fetches, server-side permission truth with the UI mirroring it, `api-client` regeneration for the CI drift gate, migration round-trips, and the live-smoke-test discipline — HANDOFF.md documents repeatedly that this project's real bugs were only ever caught that way.
