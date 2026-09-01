# Client Intake Checklist

**Purpose:** everything still needed *from the customer* (not engineering)
before launch — compiled from real open items already tracked across this
repo (`01_PRD.md` §1.4's open-decisions register, `.env.example`'s blank
third-party credentials, the course-publishing runbook, this session's
own privacy/terms/deployment work), not a generic launch checklist. Where
a row cites a source, that's where to look for the full context.

Track status by editing the checkbox as items come in. Items are grouped
by who on the customer's side actually owns the answer.

---

## 1. Legal, compliance and governance

- [ ] **Information Officer** — name, email, and physical address for
  POPIA correspondence. The published privacy policy (`/privacy`)
  currently falls back to a generic contact-page link because no
  specific person/address has been provided. *(Required before the
  privacy policy can be considered final, not just a first draft.)*
- [ ] **Legal sign-off on `/privacy` and `/terms`** — both were drafted
  from what the platform actually does (Payfast, survey-privacy
  thresholds, tenant isolation), but neither has had a lawyer's review.
  Do this before real user data is collected.
- [ ] **CPD/accreditation body**, if any — determines mandatory
  certificate fields and whether CPD points are tracked at all.
  (`01_PRD.md` §1.4 #7 — still open.)
- [ ] **SCORM/xAPI required?** — changes the content model at its root
  if yes. Asked once already and never answered. (§1.4 #1.)
- [ ] **Guest access duration** — 7 or 14 days? Currently shipped as 14
  days as a reasonable default, never explicitly confirmed. (§1.4 #6.)
- [ ] **DRM acceptance** — is signed HLS + a visible watermark
  acceptable as "industry standard" for launch, or is a dedicated DRM
  provider (EZDRM, PallyCon, Mux) required? Changes the cost model if
  the latter. (§1.4 #3.)

## 2. Accounting and finance

- [ ] **VAT treatment on international digital services** — the tax
  engine cannot be finished on a guess; the customer's own accountants
  need to give a definitive answer. (§1.4 #2.)
- [ ] **Invoice numbering start point** — the sequential tax-invoice
  series needs a starting number that doesn't collide with any existing
  manual invoicing the business already does.
- [ ] **SARS export format** — confirm the accounting export
  (`06_OPERATIONS.md` §7.3) matches what the customer's bookkeeper or
  accounting software actually ingests.
- [ ] **Bank account details for EFT** — the real account name, number,
  branch code and bank shown to learners paying by EFT (currently
  placeholder values in every deployment doc/demo built this session).
- [ ] **Refund policy specifics** — `/terms` currently says refunds are
  "considered case-by-case." If there's an actual policy (time window,
  eligible circumstances), it should be written into the real terms, not
  left as case-by-case indefinitely.

## 3. Payment gateway

- [ ] **Payfast merchant ID, merchant key, and passphrase** — card
  checkout is currently, deliberately disabled (`PAYFAST_MERCHANT_ID`
  etc. are blank in every environment file) specifically because no
  sandbox or live account exists yet. EFT and purchase-order checkout
  work today without this.
- [ ] **Which Payfast account tier / business verification** — affects
  payout timing and any per-transaction limits worth knowing before
  launch volume hits them.

## 4. Content — courses and curriculum

- [ ] **The actual course catalogue** — titles, descriptions, learning
  outcomes, module/lesson structure. Everything demoed this session used
  either real extracted `ttli.co.za` copy or clearly-labelled synthetic
  data — the real catalogue has never been supplied as structured
  content.
- [ ] **Source video files**, per course — resolution, format, and
  total runtime per lesson (drives the transcode job sizing referenced
  in the Azure cost estimate this session produced).
- [ ] **Certificate template(s)** — the visual design (logo placement,
  layout, signature block) for the certificate PDF. The publishing
  runbook (`06_OPERATIONS.md` §7.6) requires a template be assigned
  before a course can be published at all — right now nothing is.
- [ ] **Badge design(s)**, if badges are wanted alongside certificates.
- [ ] **Quiz/assessment content** per course — questions, correct
  answers, pass thresholds — wherever completion is gated by an
  assessment rather than watch-time alone.
- [ ] **Survey questions**, for courses using pre/post surveys, plus a
  decision on anonymity mode per survey — `06_OPERATIONS.md` §7.6 flags
  this specifically as **unchangeable once responses exist**, so it
  needs to be right before the first learner takes it, not after.

## 5. Content — marketing and site copy

- [ ] **FAQ content** — the live `/faq` page was drafted from facts
  already established elsewhere in the app (guest access terms, Payfast
  handling, seat-pool mechanics). If there are real, commonly-asked
  questions from the existing business, they should replace or extend it.
- [ ] **About/team copy and photos** for any facilitators not already
  extracted from the live `ttli.co.za` site.
- [ ] **Executive-programmes and for-organisations page copy** — confirm
  the extracted copy still matches current positioning; these pages
  haven't been revisited since the original site extraction.
- [ ] **Brand and design system** — colours, logo files (vector +
  raster), typography if there's a real brand typeface. Recorded as TBA
  in the original scoping and never formally supplied — the current
  brand palette was reverse-engineered from the live site's CSS, not
  handed over as a style guide. (§1.4 #8.)

## 6. Podcasts and articles

- [ ] **Spotify account / API credentials** (`SPOTIFY_CLIENT_ID`,
  `SPOTIFY_CLIENT_SECRET`) — blank today, meaning the admin curation
  workflow falls back to manual metadata entry instead of Spotify
  autofill. Needed only if Spotify-hosted episodes will be curated
  through that flow.
- [ ] **Owned podcast episodes** — audio files, show notes, transcripts,
  for any TTLI-authored (not just curated third-party) episodes.
- [ ] **Article content**, if the resources hub should launch with
  actual articles rather than just podcasts.

## 7. Email and notifications

- [ ] **A real transactional-email provider account** (SendGrid,
  Mailgun, Brevo, Azure Communication Services, etc.) with SMTP-AUTH
  credentials. The application's own SMTP code has no authentication
  path — it can only speak to an unauthenticated local relay
  (`docs/research/single-vm-deployment.md` §5) — so this is a hard
  blocker for magic-link/password-reset emails actually being delivered
  in any real deployment, not just a nice-to-have.
- [ ] **Sending domain SPF/DKIM/DMARC setup** — whoever owns DNS for the
  sending domain needs to add these records, or the ESP above will
  reject or the recipient will spam-file everything.
- [ ] **From-address and reply-to** the business wants learners to see.

## 8. Infrastructure and accounts

- [ ] **A Sentry account (or self-hosted instance) and its DSN** — the
  API refuses to start in production without one
  (`check_production_safety()`); someone needs to own this account.
- [ ] **Domain registrar / DNS access** — for the main domain and any
  per-organisation custom domains (see §9).
- [ ] **Cloud provider account** (Azure, if following the documented
  target) with billing already set up, or sign-off to proceed on the
  single-VM shape first.
- [ ] **Who holds the `rclone` backup destination credentials** — the
  off-VM backup target needs an owner who isn't only the engineer who
  set it up.

## 9. Organisations (corporate customers)

For each of the initial organisation/corporate customers:

- [ ] **Legal entity name** and **custom domain**, if they want their
  own branded subdomain or domain.
- [ ] **Logo and theme colours** for their white-labelled view.
- [ ] **Seat count** and **billing method** (EFT, purchase order — card
  auto-billing isn't built for subscriptions per `01_PRD.md` §1.4 #5).
- [ ] **Primary admin contact** who will invite their own staff.
- [ ] **Manager-visibility preference** — do managers see individual
  learner scores, or aggregate only? Defaults to aggregate-only
  (`allow_manager_individual_results = false`) unless told otherwise.

## 10. AI features (if in scope)

- [ ] **Which AI provider** — OpenAI, Anthropic, Google Gemini, or
  Azure OpenAI/Copilot — and confirmation of a signed DPA with them.
- [ ] **Data residency sign-off** — may redacted prompt data leave South
  Africa to reach the chosen provider? This determines whether AI
  insights can ship at all under the stated residency requirement.
  (§1.4 #4 — explicitly needs legal input, not just a technical answer.)
- [ ] **Per-tenant AI token budget** — a starting monthly cap, if AI
  insights launch at all.

## 11. Timing

- [ ] **Launch date target** — recorded as TBA in original scoping,
  drives phase sequencing and which of the above become hard blockers
  versus post-launch cleanup. (§1.4 #9.)
- [ ] **Budget**, if it hasn't already been settled separately — same
  §1.4 #9 item, listed here because it's still open in the source
  document this whole project traces back to.

---

## Notes on using this list

Most rows above link back to a real, specific gap already found in the
codebase or docs — not a generic "things LMS platforms usually need"
list. When an item is resolved, it's worth updating the referenced
file/page directly (the privacy policy, the terms page, `.env.prod`,
etc.) rather than only checking the box here, so this document doesn't
drift from what's actually configured.
