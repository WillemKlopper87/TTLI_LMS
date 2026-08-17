# TTLI_LMS — Enterprise LMS Interface Design (v2)

**Scope:** The interface direction for the whole platform, extending the approved 11-screen prototype ("TTLI — Interface Prototype", Discover → Decide → Learn → Oversee) into a complete enterprise LMS: the same visual language and page structures for every learner-facing screen, plus the operator surfaces the prototype never drew — the admin console, the course-authoring wizard, payment & revenue analytics, people & organisations, learning paths, workshops calendar, reports/compliance, notifications and tenant branding.

**Audience:** The user (product owner) for sign-off; the engineering agents implementing it. Every element below either (a) reproduces a prototype screen one-for-one, (b) composes prototype components into a screen the prototype implied but did not draw, or (c) is a net-new enterprise element — marked **[new]** — that the 05_COMMERCIAL feature matrix promises. Nothing here changes the design tokens; the prototype's tokens are already `apps/web/app/globals.css`.

**Status (2026-08-16):** written mid-build. Section 6 records what is being implemented in this pass and what is design-only.

---

## 1. Design principles (carried from the prototype, made explicit)

1. **Proof over polish.** Every learner-facing surface makes the anti-bypass model *visible* — completion requirements listed with current/required values, refusals shown as server decisions (`423 · LESSON_LOCKED`), watermarks that drift, certificates that verify publicly. The UI never pretends the client decides.
2. **One vocabulary, many screens.** ~110 component classes (`.stats`, `.rowlist`, `.ccard`, `.curric-rail`, `.reqs`, `.callout`, `.tabs`, `.buybox`, `.certificate`, `.tablewrap` …) compose every page. New enterprise screens reuse them before inventing anything.
3. **Stone, ink, one brand red.** `--stone` page ground, white `--surface` blocks with 1px `--rule` borders and square (3px) corners; `--brand` (#8E151C) is reserved for primary actions, the current-item marker and the art blocks; `--done/--live/--stop` are the only status colours. Charter serif for headings, numerals and prices; mono small-caps for eyebrows and tags.
4. **Privacy is a layout decision.** Manager views show participation, never scores, unless an administrator opened them per course; that state is a visible `.privacy-note`, not a hidden toggle. AI insight callouts always state how many identifiers were removed.
5. **Guided where the work is long, dense where the work is repetitive.** Multi-step tasks (creating a course, buying seats, guest signup) are wizards with a rail and a review step; operator lists (payments, leads, learners) are dense tables with facets — the two idioms never mix on one screen.
6. **Every screen resumable.** Wizards write real rows on every step (draft state *is* the save), dashboards say where you left off, checkout remembers the path chosen.

## 2. Screen map

The prototype's four journey groups stay; two operator groups are added.

| Group | # | Screen | Route | Source |
|---|---|---|---|---|
| Discover | 1 | Landing | `/` | prototype s1 |
| Discover | 2 | Podcast / resource | `/podcasts/[slug]` | prototype s2 |
| Discover | 3 | Guest access | `/guest-access` | prototype s3 |
| Decide | 4 | Catalogue (facets) | `/catalogue` | prototype s4 |
| Decide | 5 | Programme detail (buybox) | `/courses/[courseId]` | prototype s5 |
| Decide | 6 | Checkout (Card / EFT / PO) | `/checkout` | prototype s6 |
| Learn | 7 | Learner dashboard | `/learn` | prototype s7 |
| Learn | 8 | Player (rail + stage + requirements) | `/learn/[enrolmentId]` | prototype s8 |
| Learn | 9 | Assessment | inside 8, `?lesson=` | prototype s9 |
| Learn | 10 | Certificate + verification | `/verify/[token]`, credentials in 8 | prototype s10 |
| Oversee | 11 | Manager / team | `/organisations/[id]` | prototype s11 |
| Oversee | 12 | **[new]** Learning paths | `/learn/paths`, `/admin/paths` | matrix "Learning paths" |
| Oversee | 13 | **[new]** Workshops calendar | `/workshops`, `/admin/workshops` | matrix "Scheduling and calendar" |
| Operate | 14 | Admin home (operations overview) | `/admin` | composes s7/s11 idioms |
| Operate | 15 | **Course wizard** (7 steps) | `/admin/courses/new`, `/admin/courses/[id]/edit` | wizard research doc |
| Operate | 16 | **Payment & revenue analytics** | `/admin/analytics` | analytics research doc |
| Operate | 17 | People & organisations | `/admin/people`, `/organisations` | matrix "Seat management / Bulk import / Departments" |
| Operate | 18 | Reports & compliance | `/admin/reports` | matrix "Audit logs / Accounting export / Individual manager reporting" |
| Operate | 19 | Notifications centre | header bell + `/account/notifications` | push (01 §5.9) |
| Operate | 20 | Tenant branding & settings | `/admin/settings` | matrix "Custom branding / subdomain / SSO" |

## 3. Shared shell

- **Public / learner header** = prototype `.site-head`: brand mark + name/small-caps line; `.site-nav` (public: Courses · Executive Programmes · Live Workshops · Resources · For Organisations; learner: My learning · Catalogue · Workshops · Achievements); `.head-actions` (signed out: Sign in + Try a free lesson; guest: `Guest · N days left` tag + avatar; learner: notification bell **[new]** + avatar). White-label tenants swap the mark for `.tenant-logo` and "Powered by TTLI".
- **Operator shell** (`/admin/*`): the existing left sidebar keeps its brand-gradient rail; its sections are regrouped into *Sell* (Leads, Deals, Campaigns, Catalogue, Subscriptions, Payments, Analytics), *Teach* (Courses → wizard, Templates, Grading, Workshops, Podcasts, Learning paths), *People* (Learners, Organisations), *Govern* (Reports, Settings). Every admin list page adopts `.dash-top` + `.stats` + `.tablewrap` (the prototype's s11 idiom) instead of ad-hoc lists.
- **Notifications** **[new]**: a bell in `.head-actions` opening a `.rowlist` popover (payment approved, certificate issued, workshop reminder — the same three push triggers), fed by a `GET /notifications` feed; unread count as a `.tag--brand`.

## 4. Screens 1–11 — alignment specification

Each item names the prototype structure that becomes the page's structure and the data contract that feeds it (the "presentation" API pass adds what was missing).

- **1 Landing.** `.hero` two-column: left eyebrow / serif h1 "Leadership training that can prove someone actually did it." / sub / `.hero-cta` (Explore courses → `/catalogue`, Try a free lesson → `/guest-access`) / `.hero-trust` (programme count, facilitator count, "100% server-verified completion" — counts from `GET /public/courses` and `GET /facilitators` where available); right `.hero-card` "Latest episode" from `GET /public/podcasts` with `.wave` + Listen. `.band > .cols-3` three pillars. "Popular programmes" `.course-grid` of `.ccard` from `GET /public/courses` (art block colour = `hero_colour`, tags Certificate / Live workshop / CPD, meta "n modules · Xh Ym · Level", price). The existing About / book / clients / team blocks move below the fold, kept.
- **2 Podcast.** `.article` (1fr / 300px): eyebrow "Podcast · Episode · Free to everyone", serif h1, `.player-strip` (round play + `.bar` + `.times`) driving the `<audio>` element, `.prose` with `.lead`, `.gate` lead-magnet → `/guest-access`, aside `.aside-card`s (Facilitator/curator, Related programme with View programme, In this episode from show notes).
- **3 Guest access.** `.split`: `.split-pitch` with four ✓ bullets + `.note`; `.form-wrap` with the API's full field set (first/last, work email + helper, company/job title, Team size, What are you hoping to change?), two `.consent` rows, "Send my sign-in link", progressive-profiling footnote; the `.sent` state (glyph, "Check your email", "Why no password?" `.callout`, Continue to the catalogue) replaces only the right column.
- **4 Catalogue.** `.cat` (210px / 1fr): `.facets` Topic / Format / Includes / Level with counts computed from `GET /public/courses`; result header + sort; `.course-grid` of `.ccard` linking to `/courses/[id]`; team `.callout`. Products without a course (subscriptions) render as a second grid below.
- **5 Programme detail.** `.detail` (1fr / 310px): eyebrow (topic · level · format), h1, serif summary, tag row; "What you will be able to do" `.outcomes`; `.curriculum > .mod` with `.mod-head` (n lessons · duration), lesson rows with activity icon + duration, "Show remaining modules" collapse after two, Live workshop module when `includes_workshop`; right rail `.buybox` (price + VAT line, Enrol now → `/checkout?price=`, Request an invoice for a team → `/organisations`, `.buybox-list`), `.cert-preview` when `has_certificate`.
- **6 Checkout.** `.checkout` (1fr / 300px): h1 "How would you like to pay?", `.tabs` Card / EFT / Purchase order → three `.panel`s exactly as drawn (Payfast `.callout` + billing fields; `.callout--warn` + `.bank` + `.dropzone` proof + Submit for approval; PO number/seats/AP email + `.dropzone` + Request pro-forma invoice) over the existing three API paths; right `.summary` (line, VAT 15%, total) + Included `.aside-card` + guest-carry-over note.
- **7 Dashboard.** `.dash`: `.dash-top` (weekday eyebrow, "Welcome back, {first_name}", enrolment tag), `.stats` (In progress / Completed / Certificates / Workshop credits), `.continue` (art, next lesson label, `.bar`, "% complete · x of y lessons", Resume), "Coming up" `.rowlist` (workshops with Join, assessments with attempts remaining), "Completed" `.rowlist` (Certified · issued · View certificate) — all from `GET /learn/dashboard`.
- **8 Player.** `.playerlayout`: `.curric-rail` (programme, `.bar` %, `.curric-mod` headings, `.lrow--done/--now/--lock` with durations — click switches the stage; locked rows explain why on hover), `.stagearea` with the `.video` 16:9 stage (existing hls.js player inside; native seek disabled; `.scrub` with `.played` + `.ceiling` from heartbeat `furthest_position_seconds`; "41% watched · 80% required" from `watched_percentage/required_percentage`; drifting two-line `.watermark`), `.underplayer`: `.lesson-head` (module · lesson eyebrow, h2, state tag), `.reqs` panel with every check (met/unmet, current/required), `.refusal` box rendered from a real 423 (`code`, message, checks list, "Decision made server-side"), `.foot-nav` (Previous / Next lesson with `.btn--locked` until requirements are met). Document lessons render `.prose` in the stage; quiz/survey/assignment render their components in the stage.
- **9 Assessment.** `.quizwrap`: eyebrow programme · module, serif h1 quiz title, `.quiz-meta` (Question x of N · Attempt a of b · Pass mark p%), countdown `.tag--live` when timed, `.bar`, one `.qcard` at a time with `.opt` A–D (`aria-pressed`), randomised `.callout` when flags are set, `.foot-nav` Previous / Next question / Submit on the last.
- **10 Certificate.** `.certpage` (1.25fr / .75fr): rendered `.certificate` (issuer small-caps, title, name, programme, QR of the verification URL, `.cert-grid` Issued / Credential ID / CPD) beside `.verify` (✓ Valid credential + k/v rows) and, for the holder, `.share` (LinkedIn / PDF / copy link) + Visibility `.aside-card`. The public `/verify/[token]` shows the same without the holder controls.
- **11 Manager.** `.mgr`: `.tenant-strip` (white-label tenant line from `/tenant/theme`), `.dash-top` (department · n learners, "Team progress", programme select), `.stats` (Enrolled / Completed / Average progress / At risk), `.privacy-note` when scores are hidden, `.tablewrap` learner table (Progress `.minibar`, Status tag, Assessment score or `.hidden-cell`, Last active), aggregate-insight `.callout` (Phase 6, rendered inert with "not yet enabled" copy until `ai_enabled`).

## 5. New enterprise screens

- **14 Admin home.** `.dash-top` (tenant, today), `.stats` row (Revenue MTD, Pending approvals, Active learners, Completion rate — from analytics + reports endpoints), "Needs attention" `.rowlist` (EFT proofs awaiting approval, ungraded submissions, at-risk learners, transcode failures), "Recent" `.rowlist`. Replaces the current tile grid.
- **15 Course wizard.** Route `/admin/courses/new` → after step 1 `/admin/courses/[id]/edit?step=n`. Left **step rail** (the prototype's `.step` circles, vertical on desktop, horizontal on mobile) with the seven steps — Basics · Curriculum · Content · Assessments & rules · Certification · Pricing & access · Review & publish — each marked done/current/todo from real data (the readiness report drives it). Right: the step. Every step is a real API write (autosave); a "Saved · just now" `.eyebrow` sits in the step header. **Curriculum** = a `.curriculum` outline with drag handles (HTML5 DnD → atomic reorder), inline rename, add module/lesson, delete with the progress guard's message. **Content** = the outline on the left, the existing lesson activity panel (extracted) on the right for the selected lesson, an "n videos transcoding" strip, and a View as learner link (`/preview/[lessonId]` with the author bypass). **Assessments & rules** = the completion-rules builder (minimum time, watch %, quiz pass score, max attempts, survey required, assignment approval) with plain-language previews ("Learners must watch 80% and pass the module quiz at 70%"), course-level plus per-lesson overrides. **Certification** = pick/create a certificate and badge template (`.cert-mini` live preview), or none. **Pricing & access** = publish state, tenant assignment, free-preview lesson picker, product + price (or "hand off to an admin" when the caller lacks `product:manage`). **Review & publish** = the readiness checklist (`.reqs` idiom: blockers/warnings/info, `.bar` score), estimated duration, and Publish / Unpublish. Duplicate-as-template lives on the course list ("Duplicate" on each row).
- **16 Payment & revenue analytics.** `.dash-top` + range selector, `.stats` KPIs, revenue-over-time and method-mix charts, tables (top products, pending EFT/PO, refunds) per the analytics research doc; export CSV.
- **17 People & organisations.** Learners table with facets (status, organisation, course), bulk import (`.dropzone` CSV), organisation detail = screen 11 plus seat pool, invite, departments **[new: `organisation_units` table]**.
- **18 Reports & compliance.** Audit-log browser (`.tablewrap` with actor/action/entity/when, filters), completion/CPD report per course with CSV export, "individual manager reporting" toggle per course with the documented reason captured (`.privacy-note` explains the consequence), accounting export.
- **19 Notifications centre.** Bell popover + full page; preferences (push on/off per trigger, email digest).
- **20 Tenant branding & settings.** Logo, colours (live preview of `.site-head` and a `.ccard`), subdomain, SSO connection (Entra ID / SAML) **[new]**, VAPID/keys/status readouts.
- **12 Learning paths [new].** An ordered set of courses with a `.curriculum`-style outline, progress `.bar`, path certificate on completion; admin editor reuses the wizard's Curriculum idiom (drag to order courses).
- **13 Workshops calendar [new].** Month grid + `.rowlist` agenda; booking flow reuses `.buybox` (Book a seat / Join waitlist), facilitator availability editor for admins.

## 6. What this pass implements vs. design-only

**Implemented in this pass (2026-08-16):** shared shell + full component CSS port; screens 1–11 realigned; presentation API (course metadata, `/public/courses`, `/learn/dashboard`, structured checks, quiz meta, participation-level manager rows, verify metadata, `/auth/me` names); wizard (15) with its backend; payment analytics (16). **Design-only, next:** 12, 13, 14 (partial: admin home restyle), 17 (departments), 18, 19, 20 (SSO). The 05_COMMERCIAL feature-matrix audit (`docs/research/feature-matrix-coverage.md`, produced alongside this document) is the backlog source for those.
