# Handoff: TTLI LMS design kit (direction 1a — "The Institute")

## Overview

A visual direction and screen set for the TTLI LMS (`WillemKlopper87/TTLI_LMS`, branch `main`, web app at `apps/web`). It covers four surfaces: design foundations, the public storefront/catalogue, the learner course player, and the admin overview dashboard.

The direction is called **1a — The Institute**: restrained, authoritative, business-school register. Serif display type, hairline borders, no border radii, and a single accent — the real TTLI brand red already recorded in `docs/brand/ttli-brand-identity.md` and applied in `alembic/versions/0008_ttli_real_brand.py`.

Two other directions were explored and rejected (`TTLI UI Kit.dc.html` in this bundle shows all three side by side, ids `1a`, `1b`, `1c`). Only **1a** is being handed off. 1b and 1c are included for context only — do not implement them.

## About the design files

**The files in this bundle are design references created in HTML.** They are prototypes showing intended look and behaviour. They are **not** production code to copy.

The task is to **recreate these designs inside `apps/web`**, using that app's established environment and patterns: Next.js 16 App Router, TypeScript, Tailwind, the CSS custom properties in `apps/web/app/globals.css`, the tenant-theming mechanism in `apps/web/app/layout.tsx`, and the generated client in `packages/api-client`. Do not introduce a new styling approach, component library, or CSS-in-JS.

Two structural notes specific to this codebase:

1. **Colour must flow through tenant theming, not hardcoded hex.** The app already renders per-tenant `primary_color` / `secondary_color` from `tenant_themes` (see migration `0008_ttli_real_brand.py`) into CSS custom properties. Every red in this design must resolve to those properties, not literal `#8E151C`. The `acme` demo tenant exists to prove theming works — the redesign must not break it, so verify both `localhost:3010` and `meridian.localhost:3010`.
2. **The typography is a proposal, not an extraction.** `docs/brand/ttli-brand-identity.md` records that no brand typeface was identifiable from the live site. Newsreader + Archivo is a design recommendation. Confirm with the customer before adding webfonts; if they supply a real typeface, substitute it and keep the scale.

## Fidelity

**High-fidelity.** Final colours, type sizes, weights, line-heights, letter-spacing, and spacing are all specified below and present in the HTML. Recreate pixel-accurately using Tailwind utilities and the app's tokens. Where a value has no Tailwind step (e.g. `letter-spacing: .14em`, `font-size: 9px`), add it to the Tailwind theme rather than rounding it — do not snap `13px` to `text-sm`/`14px` or `11px` to `12px`.

Not covered, and out of scope for this handoff: responsive/mobile breakpoints (all screens are drawn at a fixed 1280px content width), dark mode, empty states, loading skeletons, and error states. Ask before inventing them.

---

## Design tokens

### Colour

Five values extracted from the live ttli.co.za CSS, with the role each one plays in this design:

| Token | Hex | Role |
|---|---|---|
| Primary | `#8E151C` | Primary buttons, current position (active nav, current lesson), progress fill, the one "needs attention" state |
| Bright | `#BC222A` | Primary hover, active nav underline, progress fill on dark backgrounds |
| Ink | `#16191B` | Headings, body-dark, dark app bars, admin sidebar, secondary-button border |
| Neutral grey | `#BCBEC0` | Storefront footer band, secondary series in charts |
| Light grey | `#E6E7E8` | Neutral fills |

Supporting neutrals derived for this design (warm, low-chroma — they read as paper, not as a second brand colour):

| Token | Hex | Role |
|---|---|---|
| Paper | `#F6F4EF` | Page and panel background |
| Surface | `#FFFFFF` | Cards, tables, inputs |
| Wash | `#EFEBE2` | Secondary panels, table headers, sidebars |
| Fill | `#E4E0D6` | Disabled buttons, progress tracks, image placeholders |
| Border | `#DCD7CC` | Structural 1px borders |
| Hairline | `#E4E0D6` | Row dividers inside cards and tables |
| Input border | `#CFC9BC` | Input, select and secondary-button borders |
| Body | `#3E4245` | Body copy |
| Muted | `#5C5A55` / `#6B6862` | Secondary copy / labels |
| Faint | `#8A8578` / `#969185` | Mono metadata, section eyebrows |
| Disabled | `#A5A199` | Disabled text |
| Page | `#EDEBE7` | Canvas behind the 1280px frame (prototype chrome only — not part of the app) |

**Two semantic additions, flagged.** The live site publishes no semantic colours, and a red-only palette cannot distinguish "certified" from "failed". Both sit at the brand's chroma:

| Token | Hex | Role |
|---|---|---|
| Pass | `#3E6B4F` | Completed lessons, certified learners, settled payments, positive deltas |
| Pending | `#8A6E2E` | Awaiting grade, awaiting purchase order, warnings |

Confirm both with the customer before shipping.

### Typography

Google Fonts: **Newsreader** (400, 500, 600), **Archivo** (400, 500, 600), **IBM Plex Mono** (400, 500).

Rule of assignment — apply it consistently, it is the core of the direction:
- **Newsreader (serif)** — anything the learner reads as a *statement*: page titles, card titles, lesson titles, stat figures.
- **Archivo (grotesque)** — anything the learner *acts on*: buttons, labels, nav, body copy, table cells.
- **IBM Plex Mono** — anything the system *asserts as fact*: times, durations, references, amounts, IDs, state chips, section eyebrows.

| Role | Spec |
|---|---|
| Hero H1 | Newsreader 400, 52px / 1.08, `-0.02em` |
| Page title | Newsreader 400, 40px / 1.08, `-0.015em` |
| Section title | Newsreader 400, 30px / 1.1, `-0.01em` |
| Panel title | Newsreader 400, 25–26px / 1.1 |
| Card title | Newsreader 400, 22px / 1.15 |
| Sub-panel title | Newsreader 400, 17px / 1 |
| Stat figure | Newsreader 400, 27px / 1 |
| Body | Archivo 400, 15px / 1.6–1.7 (lesson prose 1.7) |
| Body small | Archivo 400, 13px / 1.55 |
| Caption | Archivo 400, 11–12px / 1.5 |
| Button / interface label | Archivo 500, 13px / 1 |
| Button small | Archivo 500, 12px / 1 |
| Nav link | Archivo 500, 12px / 1, `.02em` |
| Field label | Archivo 500, 11px / 1, `.04em` |
| Section eyebrow | IBM Plex Mono 500, 10px / 1, `.14em`, uppercase |
| Metadata | IBM Plex Mono 400, 10–11px / 1, `.06–.1em` |
| State chip | IBM Plex Mono 500, 9–10px / 1.2, `.08em`, uppercase |
| Numeric (tables, timecodes) | IBM Plex Mono 400–500, 11–12px |

Apply `text-wrap: pretty` to every multi-line paragraph and heading.

### Geometry

- **Border radius: 0 everywhere.** No exceptions. This is the direction's most load-bearing decision — a single rounded card breaks it.
- **Borders:** 1px solid. Structural `#DCD7CC`, in-card dividers `#E4E0D6`, inputs `#CFC9BC`.
- **Shadows: none.** Depth comes from borders and the paper/surface/wash tonal step.
- **Content width:** 1280px fixed.
- **Padding scale in use:** 44px (page gutters, storefront/foundations), 32px (admin main), 28px (option panels), 20–24px (cards, panels), 16–18px (stat tiles, table headers), 11–12px (table and list rows).
- **Gap scale in use:** 1px (grid hairline technique, below), 6, 8, 10, 12, 14, 18, 20, 22 px.
- **Hairline grid technique:** stat-tile groups use `display:grid; gap:1px; background:#DCD7CC; border:1px solid #DCD7CC` with white children, so the dividers are the background showing through. Reproduce this rather than per-child borders — it avoids doubled lines.

### Interaction states

| Element | Default | Hover | Disabled |
|---|---|---|---|
| Primary button | `#8E151C` bg, `#F6F4EF` text | bg → `#6F1016` (on dark hero: → `#BC222A`) | `#E4E0D6` bg, `#A5A199` text |
| Secondary button | transparent, 1px `#16191B`, `#16191B` text | bg → `#16191B`, text → `#F6F4EF` | as above |
| Tertiary/link button | transparent, `#8E151C` text, 1px bottom border | text + border → `#BC222A` | — |
| Filter chip | transparent, 1px `#CFC9BC` | border → `#16191B` | — |
| Selected filter chip | `#16191B` bg, `#F6F4EF` text | — | — |
| Input / select | `#FFFFFF`, 1px `#CFC9BC` | focus: border → `#8E151C`, `outline:none` | — |
| Checkbox | `accent-color: #8E151C` | — | — |
| Nav link (light) | `#16191B` | `#BC222A` | — |
| Nav link, active (light) | `#8E151C` + 2px `#BC222A` bottom border, 3px offset | — | — |
| Sidebar item (dark) | `rgba(246,244,239,.72)` | `#F6F4EF` | — |
| Sidebar item, active | `#8E151C` bg, `#F6F4EF` text, 3px `#BC222A` left border | — | — |
| Anchor (global) | `#8E151C` | `#BC222A`, underline | — |

No transitions are specified in the prototype. If the codebase has a convention, follow it; otherwise use a 120ms ease on colour only. No transforms, no lifts, no scale-on-press.

### State chips

Four forms, all IBM Plex Mono 500, 9–10px, `.08em`, uppercase, 5px/10px padding, no radius:

- **Solid pass** — `#3E6B4F` bg, `#F6F4EF` text → CERTIFIED, FREE, settled
- **Solid primary** — `#8E151C` bg, `#F6F4EF` text → IN PROGRESS, CPD credits, current module
- **Outline pending** — 1px `#8A6E2E`, `#8A6E2E` text → AWAITING GRADE, overdue
- **Outline neutral** — 1px `#CFC9BC`, `#8A8578` text → LOCKED, GROUP, today

---

## Screens

### 1. Foundations

**Purpose:** internal reference; not a shipped route. Use it as the source of truth for tokens. If you want it in-repo, a Storybook page or a `/_design` route is appropriate — do not ship it publicly.

**Layout:** 1280px panel on `#F6F4EF` with `#DCD7CC` border. Header band (36/44px padding) with title block left, `ttli-logo.png` at 220px wide right. Then a 2-column `1fr 1fr` hairline grid: colour roles left, type scale right. Then a full-width components band (28/44px padding).

Content is documented in the Design tokens section above — the screen is a rendering of it.

### 2. Storefront

**Purpose:** the public sales path. Corresponds to `apps/web/app/page.tsx`, `apps/web/app/catalogue/page.tsx`, `catalogue-browser.tsx` and `course-card.tsx`.

**Layout, top to bottom:**

1. **Header** — 76px tall, 44px side padding, `#F6F4EF`, 1px `#DCD7CC` bottom border. `ttli-logo.png` at 44px height left. Nav right, 22px gap, real site wording: Lead With Intent / Cultivate with Intent / Engagement / **Programmes** (active) / Podcasts / About. Then an 8px-offset group: "Sign in" text link (`#6B6862`) and a primary button "Request a quote" (9/16px padding, 12px type).
2. **Hero** — 392px tall, `overflow:hidden`. `hero-texture.jpg` as an absolutely positioned `object-fit:cover` layer, then a gradient scrim `linear-gradient(90deg, rgba(22,25,27,.92) 0%, rgba(22,25,27,.78) 46%, rgba(22,25,27,.32) 100%)`. Content is vertically centred, 44px side padding, 20px gap:
   - Eyebrow, mono 10px `.16em` uppercase, `#D9B9BB`: "Organisational behaviour consultancy"
   - H1, Newsreader 52px, `#F6F4EF`, max-width 640px: "We align talent with strategy."
   - Paragraph, Archivo 15/1.65, `rgba(246,244,239,.82)`, max-width 520px — adapted from the site's real hero subheadline
   - Buttons: primary "Browse programmes" (13/24px padding), and a ghost "Watch a free lesson" (transparent, 1px `rgba(246,244,239,.42)`, hover → `#F6F4EF`)
   - Trust line, mono 11px `.08em`, `rgba(246,244,239,.62)`: "TRUSTED BY MORE THAN 90 ORGANISATIONS IN 19 COUNTRIES" — this is the site's only published quantitative claim. Do not add invented stats.
3. **Partner band** — `#EFEBE2`, 20/44px padding, 38px gap, six logos at 22–26px height, `opacity:.55; filter:grayscale(1)`.
4. **Catalogue** — 36/44/44px padding. Header row: eyebrow "CATALOGUE · 11 PROGRAMMES" + Newsreader 30px "Executive & leadership programmes" left; five filter chips right (All selected / Leadership / Strategy / Wellbeing / Free); 16px bottom padding above a `#DCD7CC` rule. Then a 3-column grid, 20px gap.
5. **Team CTA band** — `#16191B`, 28/32px padding, flex space-between. Newsreader 24px `#F6F4EF` "Buying for a team?" + supporting copy at `rgba(246,244,239,.72)`; paper-coloured button "Talk to us" right.
6. **Footer** — `#BCBEC0` band, 20/44px padding, mono 10px `.10em`, `#3A3C3E`, space-between: "TERMS OF USAGE & PRIVACY" and "COPYRIGHT © THEMBA THANDEKA LEADERSHIP INSTITUTE 2023". Both verbatim from the live site.

**Course card** (three variants shown):

- Container: `#FFFFFF`, 1px `#DCD7CC`, column flex, no radius.
- Media: 200px tall. Cards 1 and 2 use the real book covers (`object-fit:cover`); card 3 uses a placeholder — `repeating-linear-gradient(135deg, #E4E0D6 0 8px, #EFEBE2 8px 16px)` with a centred mono 10px `.10em` uppercase `#8A8578` label naming what belongs there. **Every placeholder in this bundle is a request for a real asset, not a design element.**
- Body: 20px padding, 10px gap, `flex:1`.
  - Meta row: mono 10px `.10em` `#8A8578` kicker + a state chip
  - Title: Newsreader 22/1.15
  - Description: Archivo 13/1.55 `#5C5A55`, `flex:1`
  - Price row: 12px top padding, 1px `#E4E0D6` top border, space-between, baseline-aligned. Price Newsreader 22px + mono 10px `#8A8578` qualifier (`EXCL VAT` / `PER SEAT`). Button right.
- The three variants carry distinct commercial states: flagship individual purchase (CPD chip, "Enrol"), group/seat purchase ("Add seats"), and free guest-access taster (pass-green FREE chip, secondary "Start" button, "No charge" in place of a price). Keep all three.

### 3. Course player

**Purpose:** lesson delivery with enforced completion. Corresponds to `apps/web/app/learn/[enrolmentId]/page.tsx` and its siblings (`curriculum-rail.tsx`, `video-player.tsx`, `requirements-panel.tsx`, `credentials-panel.tsx`).

**Layout:** 60px dark app bar, then `grid-template-columns: 290px 1fr 300px`, min-height 640px.

**App bar** — `#16191B`, 24px side padding. Left: `ttli-mark.png` 28px, a 1px `rgba(246,244,239,.22)` divider, Newsreader 15px `#F6F4EF` programme name, and a solid-primary chip "MODULE 2 OF 6". Right: mono 10px percentage + a 120×3px track (`rgba(246,244,239,.2)`, fill `#BC222A`), "Transcript" link, and a 28px square `#8E151C` avatar with white 11px initials.

**Curriculum rail (290px)** — `#EFEBE2`, 1px `#DCD7CC` right border.
- Header: eyebrow "CURRICULUM", 16/20px padding, bottom border.
- Module headings: Archivo 500 11px `.06em` uppercase, 14/20/8px padding. Colour encodes state — completed `#8A8578`, current `#8E151C`, locked `#A5A199`.
- Lesson rows: 11/20px padding, 11px gap, 1px `#E4E0D6` bottom border. Left a 17px square status marker, centre the title (Archivo 13/1.3), right a mono 10px duration or type token (`14:02`, `SURVEY`, `UPLOAD`, `TEAMS`, `LOCKED`).
- Marker states: complete = `#3E6B4F` fill, `✓`; current = `#8E151C` fill, lesson number; upcoming = 1px `#CFC9BC` outline, number; locked-module = 1px `#E4E0D6` outline, number.
- Current row: `#F6F4EF` background, **3px `#8E151C` left border**, title at weight 500, duration in `#8E151C`.
- Locked rows: text `#A5A199`; rows in a locked module `#BFBAB0`.
- Footer, pinned with `margin-top:auto`: `#E4E0D6`, 16/20px, Archivo 11/1.5 `#6B6862` — "Modules unlock in sequence. Completion is measured on watched time, not clicks."

**Main column** — `#F6F4EF`, 24/28px padding, 20px gap.
- **Player**: `aspect-ratio:16/9`, `#16191B`. Video surface is a placeholder — `repeating-linear-gradient(135deg, #1D2124 0 10px, #22262A 10px 20px)` labelled "HLS VIDEO · SIGNED MANIFEST". Control bar absolutely positioned at the bottom, 14/16px padding, `linear-gradient(180deg, rgba(22,25,27,0), rgba(22,25,27,.9))`, 9px gap:
  - Scrub track 3px `rgba(246,244,239,.24)`; watched portion 37% solid `#BC222A`; **the unwatched remainder is overlaid with `repeating-linear-gradient(90deg, rgba(246,244,239,.3) 0 3px, transparent 3px 6px)`** — the dashed remainder is how the design communicates that seeking ahead is disabled. Keep it.
  - Below: pause glyph, mono `08:31 / 22:40`, mono `1.0×` at `rgba(246,244,239,.45)`; right-aligned mono 10px `.08em` `rgba(246,244,239,.5)`: "SEEK AHEAD DISABLED · WATERMARKED FOR N. MOKOENA".
- Title block: mono kicker "LESSON 4 OF 6 · PRINCIPLE THREE", then Newsreader 30/1.15.
- Tabs: 26px gap, 1px `#DCD7CC` bottom border, 10px bottom padding. Active = `#8E151C` + 2px `#8E151C` underline; inactive = `#6B6862`, with counts in mono 10px `#A5A199`. Tabs: Overview (active) / Transcript / Resources 3 / Discussion 12.
- Body: Archivo 15/1.7 `#3E4245`, max-width 600px.
- Callout: `#EFEBE2`, **3px `#8E151C` left border**, 16/18px padding, max-width 600px, Archivo 13/1.6, with a weight-500 lead-in. (This left-accent bar is used exactly twice in the design — the current lesson row and this callout — and both mean "you are here / attend to this". Don't spread it further.)

**Requirements column (300px)** — `#EFEBE2`, 1px `#DCD7CC` left border, 20px padding, 20px gap.
1. "TO COMPLETE THIS MODULE" — a four-item checklist, 9px gap, each a 15px marker + Archivo 12/1.45. Markers: done `#3E6B4F` fill `✓`; in-progress 1px `#8E151C` outline `◗` with `#8E151C` text; not-started 1px `#CFC9BC` outline `·` with `#8A8578` text.
2. "Progress is verified" panel — `#F6F4EF`, 1px `#DCD7CC`, 14px padding. Weight-500 11px title, 11/1.5 `#6B6862` body explaining the heartbeat, then mono 9px `.08em` `#A5A199` "LAST HEARTBEAT 00:14 AGO". This panel is the UI surface of the anti-bypass contract in `docs/03_API_SPEC.md` — the numbers must come from the real heartbeat endpoint, not be decorative.
3. Credential card — **1px dashed `#CFC9BC`**, 16/14px padding. Newsreader 16px `#8A8578` title, 11/1.5 `#8A8578` body, disabled button "4 modules remaining". Dashed = not yet earned; switch to a solid `#DCD7CC` border and enable the button on issue.
4. Actions, pinned with `margin-top:auto`, 8px gap, both full-width: primary "Resume lesson 4", secondary "Ask the facilitator" (1px `#CFC9BC`, hover border → `#16191B`).

### 4. Admin overview

**Purpose:** the operator's landing view. Corresponds to `apps/web/app/admin/layout.tsx` and `apps/web/app/admin/page.tsx`, with tables reflecting `admin/grading/page.tsx` and `admin/payments/page.tsx`.

**Layout:** `grid-template-columns: 216px 1fr`, min-height 720px.

**Sidebar (216px)** — `#16191B`, 18px vertical padding, column flex.
- Brand block: 18px side padding, 18px bottom, 1px `rgba(246,244,239,.14)` bottom border. `ttli-mark.png` 26px + a two-line stack: Archivo 500 11px `#F6F4EF` "TTLI", mono 9px `rgba(246,244,239,.5)` "TENANT · DEMO". The tenant line matters — this is a multi-tenant admin.
- Group headings: mono 9px `.14em` `rgba(246,244,239,.4)`, 16/18/8px padding — DELIVERY, COMMERCIAL, INSIGHT.
- Items: 9/18px padding, Archivo 12px. Inactive `rgba(246,244,239,.72)` weight 400; active weight 500, `#8E151C` background, 3px `#BC222A` left border. Item names map to real routes: Overview, Courses, Catalogue, Workshops, Grading (with a `#E39A9E` mono count), Payments, Subscriptions, Deals, Leads, Campaigns, Analytics, Audit log, Settings.
- Footer, `margin-top:auto`: 1px top border, mono 10/1.5 `rgba(246,244,239,.42)` — "POPIA · DATA IN ZA / AI REDACTION ON". A standing compliance reminder; keep it.

**Header** — 20/32px padding, 1px `#DCD7CC` bottom border. Eyebrow "OVERVIEW · LAST 30 DAYS" + Newsreader 25px greeting left; a period `<select>` and a primary "New programme" button right.

**Body** — 24/32/32px padding, 22px gap.
1. **Stat tiles** — 4-column hairline grid (see the technique in Design tokens). Each tile 16/18px padding, 7px gap: mono 10px `.08em` `#8A8578` label, Newsreader 27px figure, then an 11px weight-500 delta coloured semantically (`#3E6B4F` positive, `#6B6862` neutral, `#8A6E2E` pending, `#8E151C` needs attention). Tiles: recognised revenue, seats in use, completion rate, outstanding invoices.
2. **Two-column row**, `1.35fr 1fr`, 20px gap.
   - **Revenue chart** — `#FFFFFF`, 1px `#DCD7CC`, 20px padding. Title Newsreader 17px + a mono legend (`#8E151C` PROGRAMMES / `#BCBEC0` SUBSCRIPTIONS). The chart is CSS-only: ten equal flex columns, 14px gap, 172px tall, each a bottom-aligned stack of two percentage-height divs, over a 1px `#E4E0D6` baseline. **The final (current, incomplete) month is rendered in a 4px diagonal stripe of the same hues** — that's the projection convention; carry it into whatever charting library the app uses. Month labels below in mono 9px `#A5A199`.
   - **Grading queue** — `#FFFFFF`, 1px `#DCD7CC`. Title row 18/20/14px + a "View all" link. Four rows, each 12/20px with a 1px `#E4E0D6` top border: name (Archivo 13px) over a mono 10px `#8A8578` artefact line, with an outline age chip right (`#8E151C` when overdue, `#8A6E2E` at 2 days, neutral for today). Footer `margin-top:auto`, `#EFEBE2`, 14/20px, Archivo 11/1.5 `#6B6862`: "Managers see cohort averages only. Individual scores stay with the learner and the facilitator." This states the ABAC rule from `docs/04_SECURITY_AND_COMPLIANCE.md` in the UI — keep it visible.
3. **Payments table** — `#FFFFFF`, 1px `#DCD7CC`. Title row 16/20px + two secondary buttons ("Export CSV", "Reconcile EFT"). Column template `1.4fr 1fr 1fr .8fr .9fr .8fr`. Header row 9/20px, `#EFEBE2`, mono 500 10px `.08em` `#6B6862`, with AMOUNT and STATUS right-aligned. Body rows 12/20px, 1px `#E4E0D6` bottom border, Archivo 12/1.3; **reference, seats and amount cells are IBM Plex Mono** (11–12px); status is weight 500 and colour-coded — Settled `#3E6B4F`, Awaiting PO `#8A6E2E`, Unmatched `#8E151C`. The four rows deliberately cover all four payment methods the platform supports (purchase order, Payfast, direct EFT, Netcash).

---

## Interactions & behaviour

The prototype implements one interaction only: the four-tab screen switcher at the top, which is **prototype chrome and must not be built**. It exists so the reviewer can page between screens.

Everything else is presentational. Real behaviour to wire up when implementing, all of it already specified in the repo's own docs:

- **Completion gating** — lesson rows are not navigable until prior requirements pass; module headings and rows reflect lock state. Source: the completion-rules model and `docs/01_PRD.md` workflow state machines. The UI must never render a locked lesson as clickable-but-rejecting.
- **Heartbeat** — the player reports watched segments on an interval; the "Progress is verified" panel reflects the last successful beat. Contract in `docs/03_API_SPEC.md` (anti-bypass heartbeat). Seek-ahead is disabled in the control surface, not merely discouraged.
- **Credential issue** — the credential card transitions from dashed/disabled to solid/enabled when all modules complete and grade. Certificate and LinkedIn badge per the existing `verify/[token]` route.
- **Manager visibility** — cohort aggregates only, individual scores withheld, per-course override by a system administrator. Enforce server-side; the footer note is a reminder, not the control.
- **Tenant theming** — every red resolves from the tenant's theme properties; the logo falls back to a text treatment for tenants without one (as `apps/web/app/page.tsx` already does for `acme`).
- **Filter chips** (storefront) — single-select in the prototype; confirm whether the real catalogue is single- or multi-facet before building.

No animations, transitions, transforms or loading states are specified. Ask before adding any.

## State

The prototype's only state is `screen: "foundations" | "storefront" | "learn" | "admin"` — prototype chrome, not app state. No app state is prescribed by this handoff; use whatever the existing routes already do (server components + the generated `packages/api-client`).

## Assets

All in `assets/` in this bundle, copied unmodified from `apps/web/public/brand/` in the repo — they are already in the codebase at those paths, so reference them there rather than re-adding them.

| File | Used in | Notes |
|---|---|---|
| `ttli-logo.png` | Foundations header, storefront header | 950×502 transparent PNG. The repo deliberately uses the PNG over the SVG because `next/image` disables SVG optimisation by default. |
| `ttli-mark.png` | Course player app bar, admin sidebar | Starfish mark only (the site favicon). |
| `hero-texture.jpg` | Storefront hero | Behind the gradient scrim. |
| `book-lead-with-intent.jpg` | Storefront card 1 | Real book cover. |
| `book-cultivate-with-intent.jpg` | Storefront card 2 | Real book cover. |
| `partners/*.png` (6) | Storefront partner band | Greyscale as published; the design also dims to `.55`. |

**Placeholders that need real assets before launch:** the third catalogue card's media ("FACILITATOR PHOTOGRAPHY") and the lesson video surface. Both are striped fills with mono labels naming what belongs there — they are requests for material, not design elements. Ask the customer.

**Copy provenance:** the hero eyebrow, hero subheadline, trust line, footer text and nav wording are verbatim or lightly adapted from the live ttli.co.za, recorded in `docs/brand/ttli-brand-identity.md`. Programme names ("Lead with Intent", "Cultivate with Intent") are real. Prices, learner names, organisation names, revenue figures, references and dates are **invented sample data** — replace all of them. Note that `docs/05_COMMERCIAL.md` states no price is quotable until a unit-cost model exists, so treat the R-values as layout ballast only.

## Files

| File | What it is |
|---|---|
| `TTLI Design Kit.dc.html` | The handoff design. Four screens; open it in a browser and use the tab strip. |
| `TTLI UI Kit.dc.html` | The three explored directions (`1a`, `1b`, `1c`). Context only — 1b and 1c were rejected. |
| `assets/` | Brand assets, as listed above. |
| `screenshots/` | Full-frame 2× captures of each screen — `01-foundations.png`, `02-storefront.png`, `03-course-player.png`, `04-admin.png`. Reference only; measure from the README and the HTML, not from the pixels. |

Both HTML files are self-contained apart from the Google Fonts links and the `assets/` images; the asset paths inside them point at `apps/web/public/brand/...`, matching the repo layout.

## Suggested first prompt for Claude Code

> Read `design_handoff_ttli_design_kit/README.md`, then open `TTLI Design Kit.dc.html` in a browser to see the intended result. Implement the **storefront** screen first in `apps/web`, using the existing Tailwind setup and the tenant-theme CSS custom properties from `apps/web/app/globals.css` — no hardcoded hex for the brand red. Add the Newsreader / Archivo / IBM Plex Mono families and any missing type steps to the Tailwind theme rather than rounding the specified values. Do not build the four-tab switcher; it is prototype chrome. Show me the diff before touching `catalogue-browser.tsx`.

Then work outward: storefront → course player → admin. The foundations screen is reference, not a route.
