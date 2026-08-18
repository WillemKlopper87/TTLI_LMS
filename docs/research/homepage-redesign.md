# TTLI — Homepage & About Us: Research and Build Record

**Written:** 2026-08-18, following a research pass on five homepage ideas the customer raised (book carousel, scrollable client-logo wall, footer social links, bigger facilitator photos, an About Us section with per-person bio pages). Four of the five were built the same day; one remains blocked on real input.

**Method note:** A dispatched research agent read the current code (`apps/web/app/page.tsx`, `apps/web/app/globals.css`, `docs/brand/ttli-brand-identity.md`) and looked at how comparable executive-education/leadership-consultancy sites (IMD, Center for Creative Leadership, Korn Ferry, Egon Zehnder, INSEAD Executive Education) handle each pattern, sized to TTLI's actual content volume rather than assuming scale that doesn't exist yet.

---

## 1. The two things the agent flagged before building anything

**"A few books that have been written."** `docs/brand/ttli-brand-identity.md` only documents one book extracted from the real ttli.co.za site — *Lead with Intent*. The customer supplied a second, real source in-conversation: https://exclusivebooks.co.za/products/9781049251486, confirming a genuine second title, *Cultivate with Intent* (Hermann du Plessis, "A Blueprint for Leaders to Become Worldclass Cultural Architects"). This also closes a gap `docs/STATUS.md` had explicitly named since Phase 2: *"'Cultivate with Intent' as a dedicated route — the real site names it in its nav, but no page content was ever extracted, so building it now would mean fabricating copy."* That block is now lifted — the retail listing is a legitimate, citable, real source, not fabrication.

**"Add social media links."** The real site has no company social profile links at all (`ttli-brand-identity.md`: only a LinkedIn *share* button and a Linktree QR code). **Still open** — no URLs have been supplied, so the footer carries none. Ask the customer for the actual platform URLs (or the Linktree link, matching what the real site does) before building this.

## 2. Per-idea recommendation and what was actually built

### Book carousel → a static two-book shelf, not a carousel
**Recommendation (unchanged by the second book arriving):** a carousel's arrows/dots only earn their keep past ~4-5 items; for two, they'd be a control with nowhere real to go. Built `apps/web/app/page.tsx`'s `BOOKS` array feeding a static `grid-template-columns: repeat(auto-fit, minmax(20rem, 1fr))` — both covers side by side, same visual weight, no motion. Revisit as an actual carousel only once a third title is confirmed and two columns stop being a comfortable fit.

New page: `apps/web/app/cultivate-with-intent/page.tsx`, structurally identical to the existing `/lead-with-intent/page.tsx`. Cover image downloaded from the retail listing to `apps/web/public/brand/book-cultivate-with-intent.jpg` (620×860, native aspect ratio preserved at every render size used). Copy (title, subtitle, description, the Brand Pretorius blurb) is the retail listing's own text, not invented. The listing's "130+ organisations in 23 countries" is left as *that book's own jacket copy* — deliberately not reconciled with the site's separate "90+ organisations / 19 countries" line, since they're different sources possibly from different points in time.

### Client-logo wall → left as-is, recommendation still stands
At 9 logos the existing static grid already fits comfortably — no scrolling need exists yet. **Not built**: a "show all" expand toggle would be the right upgrade *if* the logo count grows meaningfully; a scroll/carousel treatment only once it's 20+. Revisit when there's an actual volume problem to solve, not preemptively.

### Facilitator photos → resized and fixed a real display bug
Built. Went from 120×160 (which didn't even match the source photos' real 2:3 ratio — `objectFit: cover` was silently cropping every one) to 220×330 at the true ratio, in a tighter `minmax(13rem, 1fr)` grid rather than "as many as fit." Each card is now a real `<Link>` to `/about/[slug]`, with a `.facilitator-card` hover/focus affordance in `globals.css` (a 2px lift + outline — matching the site's flat, no-shadow visual language rather than a drop shadow).

### Footer social links → still blocked
Not built. Needs real URLs from the customer (see §1). The footer (`apps/web/app/page.tsx`'s `<footer>`) is the right place, icon-only per the researched register (Egon Zehnder/Korn Ferry/IMD favour small, muted, icon-only over icon+label buttons for this "serious/professional" tone) — not built yet since there's nothing real to link to.

### About Us + per-person bio pages → built, honestly
Built:
- `apps/web/lib/facilitators.ts` — the single shared data source now used by the homepage teaser, `/about`, and `/about/[slug]` (previously a duplicated `[photo, name, role]` tuple array inline in `page.tsx`). Carries `bio`/`credentials`/`linkedin` fields, all `null` today.
- `apps/web/app/about/page.tsx` — the real About narrative already on the homepage (`#about` band, verbatim ttli.co.za copy), plus the same enlarged facilitator grid, each card linking out.
- `apps/web/app/about/[slug]/page.tsx` — one page per person. Renders `bio`/`credentials`/`linkedin` when present; when absent (today, for everyone), shows *"A fuller profile for {name} is on its way"* rather than a fabricated paragraph. This matches the project's own established rule — `ttli-brand-identity.md`'s "Explicitly not present on the site, so not fabricated here" — extended to biographical content about real, named people. Filling in real bio copy later is a one-line edit per person in `lib/facilitators.ts`; nothing else needs to change.
- `PUBLIC_NAV` in `components/site-header.tsx` gained an "About" entry.

**Why static data, not a database model:** `page.tsx`'s own docstring is explicit that this marketing content is intentionally not tenant/theme-driven — no CMS exists yet for a second tenant to supply its own copy. A DB-backed, admin-editable facilitator model would be solving a problem TTLI doesn't have yet (a second tenant needing its own team page) at the cost of real complexity (migration, RLS, admin CRUD) for content that changes rarely. Revisit only if TTLI itself gets an admin-editable CMS for its own copy — a separate, bigger decision this pass didn't presuppose.

## 3. A real screenshot-methodology lesson from this pass

Verifying the facilitator grid and book shelf, a first full-page screenshot (`Page.captureScreenshot` after `Emulation.setDeviceMetricsOverride` to the full page height) showed both broken: facilitator photos entirely missing (only name/role text visible, in correctly-spaced rows) and the second book cover rendering at a fraction of the first's size. Neither was a real bug — `next/image`'s default lazy loading uses an `IntersectionObserver`, and suddenly resizing the CDP viewport to the full page height right before capturing races that observer for images that were "below the fold" a moment earlier. A second screenshot using a normal 1440×900 viewport with an actual `window.scrollTo` (giving the observer real time to fire) showed everything rendering correctly at every section. Worth remembering for any future full-page verification screenshot on an image-heavy page: prefer scroll-and-capture over the resize-to-full-height trick, or add a longer settle delay.

## 4. Verified state

`apps/web` `tsc --noEmit` clean. Live smoke test through the restarted dev servers, logged in as the demo `super_admin`: `/`, `/about`, `/about/hermann-du-plessis`, `/cultivate-with-intent` all render correctly (screenshotted); the admin `/admin/articles` and `/admin/recommendations` screens (built the same pass — see `docs/HANDOFF.md`) were exercised end to end through real button clicks, not just API calls — create → publish → confirmed on the public endpoint → unpublish, for both content types.

Not run this pass: `next build` (a production build must never run in the same checkout as a live `next dev` you intend to keep serving — both write `.next/`; this exact collision took the live site down mid-session earlier the same day, see `docs/HANDOFF.md`'s entry for the recovery).
