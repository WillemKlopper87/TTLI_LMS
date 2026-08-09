# TTLI brand identity — extracted reference

**Source:** https://ttli.co.za/ (live, public homepage)
**Extracted:** 2026-08-09, by fetching the page's rendered HTML/CSS and the
linked logo/favicon assets directly (`curl`, then grepped for hex colors and
downloaded the image files — not a design brief, not a style guide the
customer handed over; everything below is *inferred from the live site* and
should be confirmed with the customer before anything ships to them).

This doc is the provenance record. `apps/api/alembic/versions/0008_ttli_real_brand.py`
and `apps/web/public/brand/` are where it's actually applied — see "Applied where" below.

## Company

- **Legal/full name:** Themba Thandeka Leadership Institute
- **Short form used on-site:** TTLI (matches this repo's existing naming)
- **Positioning line (site `<title>` and OG tags):** "Organisational Behaviour Consultancy"
- **Hero subheadline (exact text):** "We help business and organisations
  cultivate work environments that create value and unlock human potential.
  In short, we align talent with strategy."
- **Meta description (exact text):** "We consult and coach leaders and their
  organisations in the essentials skills needed to raise engagement."
- **Footer copyright (exact text):** "COPYRIGHT © THEMBA THANDEKA LEADERSHIP
  INSTITUTE 2023"
- **Nav wording (exact, top-level):** Home / Lead With Intent / Cultivate
  with Intent / Engagement / Services / Podcasts / About / Contact

## Colors

Extracted from the site's inline `<style id="et-critical-inline-css">` block
(a Divi WordPress theme) and cross-checked against the fill colors used
inside the logo SVG itself — the two sources agree closely, which is why
these read as genuine brand colors rather than theme defaults:

| Role | Hex | Where seen on ttli.co.za |
|---|---|---|
| **Primary (brand red/maroon)** | `#8E151C` | Links, buttons, headings, borders — the color used most consistently across the whole site |
| **Secondary (brighter accent red)** | `#BC222A` | Sticky header background, active nav-item highlight |
| **Neutral grey** | `#BCBEC0` | Footer background, hover-block background |
| **Light grey** | `#E6E7E8` | Hover-block text background |
| **Near-black (wordmark/text)** | `#231F20` | "Themba" half of the logo wordmark, body text |

The logo's own fill colors (`#9C1519` → `#BE1F24`, used as a gradient on the
starfish mark and the "Thandeka" wordmark) sit inside the same red family as
the site CSS — treat `#8E151C` / `#BC222A` as the two canonical values to
reuse; the logo gradient is closer to `#BE1F24` at its lightest, which is
why the two don't match byte-for-byte.

One color from the Gutenberg default palette (`#2ea3f2`, a blue) also
appears repeatedly in the CSS but is the WordPress/Divi *editor's* stock
"blue" swatch, not something distinct to this brand — excluded here.

## Logo & mark

- **Full logo (wordmark + starfish icon):** sourced from the page's
  `og:image` meta tag, `https://ttli.co.za/wp-content/uploads/2017/12/themba-logo.png`
  (950×502 PNG, transparent background). Saved as
  [`apps/web/public/brand/ttli-logo.png`](../../apps/web/public/brand/ttli-logo.png).
- **Vector logo:** `https://ttli.co.za/wp-content/uploads/2017/12/Logo.svg`,
  the file the site itself uses in its header. Saved as
  [`apps/web/public/brand/ttli-logo.svg`](../../apps/web/public/brand/ttli-logo.svg).
- **Standalone mark (starfish icon only):** the site favicon,
  `https://ttli.co.za/wp-content/uploads/2017/12/fav.png`. Saved as
  [`apps/web/public/brand/ttli-mark.png`](../../apps/web/public/brand/ttli-mark.png)
  and also copied to `apps/web/app/icon.png`, which Next.js's app-router
  file convention serves automatically as the site favicon.
- The wordmark itself renders "Themba" in near-black, "Thandeka" in the red
  gradient, and "LEADERSHIP INSTITUTE" in a light, letter-spaced, all-caps
  near-black — not reproduced as text anywhere in this repo; we use the logo
  image rather than re-setting the wordmark in a web font, since no brand
  typeface was identified from the site (see below).

## Typography

No `@font-face` or a named brand typeface was identifiable from the fetched
CSS — the site relies on Divi/WordPress default font stacks. Not treated as
a brand signal; `apps/web` keeps its existing Tailwind default font stack.

## Content — home, about, contact (extracted 2026-08-09, second pass)

Fetched `https://ttli.co.za/about/` and `https://ttli.co.za/contact/` in
addition to the homepage, at the user's explicit request to carry the real
site's content — copy, images, team, partners — into the new design rather
than the placeholder copy the interface prototype used. Quoted verbatim
except where noted.

**Nav (top-level, exact):** Home / Lead With Intent (submenu: Coaching
Guide) / Cultivate with Intent / Engagement / Services (submenu: Strategy,
Learning Programs, Coaching) / Podcasts / About / Contact

**About narrative (verbatim, from the About page):**
> We train, consult and coach organisations in the Essentials Skills needed
> to raise engagement. We offer value to customers through Engagement
> Analysis, Training, Consulting and Coaching within the spheres of
> Leadership, Strategy and Organisational Wellbeing. We have built a
> reputation as a Catalyst that guide organisations towards a sustainable
> increase in their profitability. We hold a deep belief that to work is a
> gift and that the workplace should be an environment that inspire people
> to share their talent, experience, ideas, uniqueness and enthusiasm.

**Track record claim (verbatim):** "more than 90 organizations in 19
countries" — the only quantitative claim on the site; no other stats
(client count, years trading, etc.) are published.

**Team** (About page; photos saved to `apps/web/public/brand/team/`):

| Name | Role | Photo file |
|---|---|---|
| Hermann du Plessis | Founder — 20 years' experience, 15,000+ coaching hours; author of *Lead with Intent* | `team-hermann-du-plessis.jpg` |
| Sizwe Kuzwayo | Sustainability practitioner and business consultant, 20+ years in leadership | `team-sizwe-kuzwayo.jpg` |
| Hano du Plessis | Training Manager | `team-hano-du-plessis.jpg` |
| Agnes Hove | Strategist — Master's in Strategy, Bachelor's in Business Management | `team-agnes-hove.jpg` |
| Erika Botha | Management consultant and learning facilitator | `team-erika-botha.jpg` |

**Contact details (verbatim, About + Contact pages):**
- Hermann du Plessis — `hermann@ttli.co.za` — +27 82 853 7463
- Sizwe Kuzwayo — `sizwe@ttli.co.za` — +27 79 779 8626
- Hano du Plessis — `hano@ttli.co.za` — +27 74 722 0773
- Physical address: "30 Kasbah Ridge, Egale Canyon Golf Estate"
- Contact page heading: "Get In Touch" / "We would really like to hear from you."

These are personal names, direct cellphone numbers and personal work
emails of named individuals — sensitive even though the company itself
publishes them on its own public marketing site. They're carried into this
build because that is the explicit, narrow purpose here (rebuilding this
company's own site with its own real content, for the same company) — not
a general licence to redistribute them. Re-check before this ever leaves
an internal/demo context.

**Client / partner logos** (homepage; saved to
`apps/web/public/brand/partners/`, greyscale originals as published):
Standard Bank, HENSOLDT, De'Longhi, Floorworx, ITEC Evolve, Shangoni
Management Services, Earthlab, TWK, Barberton Mines. No testimonial
quotes accompany these — the site displays logos only, no attributed text.

**"Lead with Intent"** — a book by founder Hermann du Plessis. Site copy:
"A ground-breaking book by Hermann du Plessis that reveals nine leadership
principles and practices that drive engagement and commitment in the
workplace." Cover saved as `apps/web/public/brand/book-lead-with-intent.jpg`.
Also the name of the site's top-level nav item and a services offering —
treated here as the closest real analogue to a flagship "product," used as
such in the new catalogue/landing content.

**Footer (verbatim):** "TERMS OF USAGE & PRIVACY | COPYRIGHT © THEMBA
THANDEKA LEADERSHIP INSTITUTE 2023." No footer contact block, no listed
social profile URLs (a LinkedIn *share* button is present, not a company
profile link) — a Linktree QR code is the only additional-links surface.

**Explicitly not present on the site, so not fabricated here:** customer
testimonials/quotes, numeric stats beyond the "90 organisations / 19
countries" line, a company social media profile URL, and — per the first
extraction pass — a distinct brand typeface.

## What was deliberately not extracted

- **Full color palette beyond the five above:** the WordPress block-editor's
  stock Gutenberg palette (reds/oranges/greens/purples used by the page
  builder's default color picker) also appears in the HTML but is not part
  of this brand — excluded.

## Applied where

- `apps/api/alembic/versions/0008_ttli_real_brand.py` — updates the `demo`
  tenant's `tenants.name` to "Themba Thandeka Leadership Institute" and its
  `tenant_themes` row's `primary_color`/`secondary_color`/`logo_url` from
  migration 0006's navy/gold placeholder to the real values above. `logo_url`
  points at the PNG (`/brand/ttli-logo.png`), not the SVG — Next.js's
  `next/image` disables SVG optimization by default as an XSS precaution,
  and the PNG needs no config change to render safely. The `acme` demo
  tenant is untouched — it exists specifically to prove per-tenant theming
  works, and giving it TTLI's own brand would defeat that.
- `apps/web/app/globals.css` and `apps/web/app/layout.tsx` — fallback CSS
  custom properties (used only before a tenant's theme loads, or for a
  tenant with no theme row at all) updated from the navy/gold placeholder
  to `#8E151C` / `#BC222A`.
- `apps/web/app/page.tsx` (login) and `apps/web/app/admin/page.tsx` (admin
  shell header) — render `theme.logo_url` when a tenant has one, falling
  back to the existing text treatment (`theme.tenant_name` / tenant slug)
  for tenants without a logo, e.g. `acme`.
