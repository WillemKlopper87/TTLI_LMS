# Implementing "1a — The Institute" in `apps/web`

Companion to `README.md` (the designer's handoff). That file says what
the direction is; this one records what was actually built, what was
changed on the way in and why, and what is still outstanding.

## It ships as a *skin*, switchable at runtime

Both looks are live at once. `lib/skin.ts` defines two skins, `classic`
(the app as built) and `institute`; the root layout reads a `ttli_skin`
cookie and stamps `data-skin` onto `<html>`, and `globals.css` carries a
`:root[data-skin="institute"]` block that redeclares tokens.

**Nothing renders conditionally on the skin.** There is no second
component tree, no `if (skin === …)` in a page. That was the constraint
worth holding onto: two component trees drift apart, and within a month
one of them has a bug fix the other doesn't. A token block cannot drift,
and every screen built after this lands gets both looks for free.

The switch itself (`components/skin-switcher.tsx`) is a demo affordance
and renders only when `NEXT_PUBLIC_SKIN_SWITCHER=1`. The skin is still
reachable by cookie without it, which is why the e2e spec covers the
skin rather than the switch.

Why a cookie and not `localStorage`: the root layout is a server
component, and the look has to be in the HTML it sends. Reading the
choice on the client would mean a frame of the wrong skin on every
navigation.

### What the token layer had to grow

The colour vocabulary was already fully tokenised. Two things were not,
and were tokenised as part of this:

* **Radii.** Twenty-one hardcoded `border-radius` values (`2px`, `8px`,
  `999px`, `50%`, `1px`) became six tokens — `--r`, `--r-sm`, `--r-lg`,
  `--r-hair`, `--r-pill`, `--r-round`. The direction's most load-bearing
  rule is "radius 0 everywhere, no exceptions", and it now costs six
  declarations instead of an audit.
* **Dark mode's scope.** The `prefers-color-scheme` block is now guarded
  with `:not([data-skin="institute"])`. See the third departure below.

## Three departures from the handoff, and the numbers behind them

Each one is a case where the handoff's literal value fails a check this
codebase already enforces in CI. None is a matter of taste.

### 1. Four ink and status values are darkened

Measured with the WCAG relative-luminance formula against every surface
in the Institute palette (`#ffffff`, `#f6f4ef`, `#efebe2`, `#e4e0d6`):

| Handoff | Role | Was | Shipped | Now |
|---|---|---|---|---|
| `#8A8578` | faint — 10px mono metadata, eyebrows | 3.68 / 3.35 / 3.09 / 2.79 | `#676359` | 5.99 / 5.45 / 5.04 / 4.54 |
| `#969185` | faint, second step | 2.86 / 2.64 | folded into `#676359` | — |
| `#8A6E2E` | pending — awaiting grade, overdue | 4.83 / 4.39 / 4.06 / 3.66 | `#796028` | 5.97 / 5.43 / 5.02 / 4.53 |
| `#CFC9BC` | input and control borders | 1.65 / 1.50 | `#998c71` | 3.31 / 3.01 |

Each replacement keeps the original hue and saturation and moves only
lightness, so the palette still reads as the designer drew it. The
border value is held to 3:1 rather than 4.5:1 because WCAG 1.4.11 is the
rule that applies to a control boundary.

`#3E6B4F` (pass) needed no change — it clears 4.5:1 everywhere.

`#A5A199` disabled text on `#E4E0D6` measures 1.95:1 and was **kept as
designed**: WCAG exempts disabled controls, and dimming is how a control
says it is unavailable.

### 2. The chart's second series is not `#BCBEC0`

`#BCBEC0` against a white chart surface is 1.86:1 — a mark a
low-vision reader cannot locate. It ships as `#929599` (3.01:1).

Re-stepped, it still reads as grey, and the palette validator FAILs it
on the chroma floor for exactly that reason. That is the intent here:
it is the recessive series, opposite the tenant's brand red. The relief
the validator requires for a sub-3:1 or low-chroma slot is a table view,
and the revenue chart already ships one (`<details>` fallback). CVD
separation against the red is comfortable — ΔE 25.1 deutan, 29.7 normal.

### 3. Dark mode is not defined for this skin

The handoff excludes dark mode, and inventing a dark palette for someone
else's direction is inventing design. The skin pins itself to
`color-scheme: light` and the `prefers-color-scheme` block is scoped to
exclude it. A reviewer on a dark-set machine sees the Institute skin
light, deliberately.

**This is the open question for the customer**: the classic skin has a
full, contrast-corrected dark mode, so the app loses a capability when
you switch. Either the direction gets a dark palette drawn for it, or
the Institute skin is documented as light-only.

## What is *not* built yet

The skin changes the app's whole character — type, colour, geometry — on
every page. It does **not** yet reproduce the four handoff screens
structurally. Outstanding, roughly in order of visible payoff:

1. **Storefront hero** — **partially done 2026-08-23**: the image hero
   with the gradient scrim, the greyscaled partner band, and a "buying
   for a team?" CTA band are built on `app/page.tsx` (STATUS.md has the
   pass). Still outstanding: the catalogue page's own header row
   (eyebrow + filter chips) and the three-variant course card (flagship
   / group / free taster) — `course-card.tsx` still wears Institute
   tokens on the classic card shape.
2. **Admin overview** — the dark 216px sidebar, the 1px-gap hairline
   stat grid, and the payments table with mono numerics.
3. **Course player** — the `290px 1fr 300px` grid, the dark app bar, the
   dashed-remainder scrub track (which is how the design says "seeking
   ahead is disabled"), and the requirements column.
4. **Type scale** — the handoff specifies exact sizes (52 / 40 / 30 / 25
   / 22 / 17px) and letter-spacing. Only the family assignment and
   heading weight/tracking are in. The sizes need either a tokenised
   scale or per-section overrides.
5. **Foundations screen** — reference only; if it is wanted in-repo it
   belongs behind `/_design`, not on a public route.

Two things the handoff flags that still need a customer decision, and
neither should be built on assumption:

* **Webfonts.** Newsreader + Archivo + IBM Plex Mono are the designer's
  proposal, not an extraction — `docs/brand/ttli-brand-identity.md`
  records that no brand typeface was identifiable from the live site.
  They are wired through `next/font` (self-hosted, so `font-src 'self'`
  in `proxy.ts` is untouched) and are trivially swappable if a real
  typeface arrives.
* **The two semantic colours** (`pass`, `pending`). The live site
  publishes none, and a red-only palette cannot separate "certified"
  from "failed".

## Verifying it

`apps/web/e2e/skin.spec.ts` runs the same axe WCAG A/AA gate under the
Institute skin that `public.spec.ts` runs under the default, and asserts
the three things the direction *is* — its serif, radius 0, warm paper —
so that a future edit dropping the skin block fails loudly instead of
silently rendering the classic look.

It also pins the rule the handoff is most explicit about: the brand red
resolves from the tenant theme, never from the skin. `meridian.localhost`
keeps its own colour under both skins.
