# TTLI LMS — User Guide

This is the guide for people **using** TTLI LMS: individual learners,
corporate/organisation administrators, and workshop facilitators or
attendees. It assumes no engineering knowledge and does not cover how the
platform is built or deployed — for that, see
[README.md](../README.md) and [docs/HOWTO.md](HOWTO.md).

> **Status note.** TTLI LMS is currently in guided end-to-end user
> acceptance testing, not a general production launch. Screens described
> here match what is implemented today; a few areas (marked below) are
> still being finished or validated. If something in this guide doesn't
> match what you see, tell your TTLI contact — the platform is still being
> hardened before public launch.

## Who this guide is for

| Role | What you can do |
|---|---|
| **Learner** | Browse the catalogue, buy or redeem access to courses/paths/workshops, complete self-paced learning, attend live workshops, earn certificates |
| **Organisation / corporate admin** | Everything a learner can do, plus manage your organisation's members, allocate seats, and view team reporting |
| **Facilitator** | Deliver live workshop sessions and see attendance for sessions you're running |

Your account can hold more than one of these roles depending on what your
organisation has granted you.

---

## 1. Finding and choosing training

- **Public catalogue** (`/catalogue`) — browse all publicly listed courses,
  learning paths and workshops for your tenant. Each course/workshop has its
  own detail page (`/courses/{course}`, `/workshops/{workshop}`) with a
  description, curriculum outline, pricing and upcoming session dates.
- **Learning paths** (`/paths`) — a curated, ordered bundle of courses sold
  and tracked as a single programme.
- **Executive programmes and thematic pages** — `/executive-programmes`,
  `/lead-with-intent`, `/cultivate-with-intent` and `/for-organisations`
  give a narrative view of flagship programmes for prospective corporate
  buyers.
- **Resources** (`/resources`, `/resources/articles`) — free articles and
  supporting material, not gated behind purchase.
- **Podcasts** (`/podcasts`) — audio content linked to programme themes.

## 2. Getting access

TTLI LMS supports several ways to get into a course, depending on how your
organisation or TTLI has set things up:

- **Buy it yourself** — add a course, path or workshop to checkout
  (`/checkout`) and pay by card, EFT or purchase order (South African VAT is
  applied automatically). You'll land on `/checkout/return` on success or
  `/checkout/cancel` if you back out.
- **Guest access** — some content allows a time-limited guest session
  (`/guest-access`) without creating a full account first.
- **Organisation seat** — if your employer has bought seats on your behalf,
  you'll receive an email invitation. Following its link takes you to
  `/verify/{token}` to activate your account, or `/auth/magic-link` if your
  organisation uses passwordless sign-in.
- **Single sign-on (SSO)** — organisations with SAML/OIDC configured sign in
  via `/auth/sso`, which redirects to your organisation's identity provider
  and returns through `/auth/sso/callback`.

### Signing in

- `/login` — email/password, or a link to request a magic link instead.
- `/auth/magic-link` — request a one-time sign-in link sent to your email;
  no password needed.
- `/auth/password-reset` — forgot your password? Request a reset link here.
- Multi-factor authentication (TOTP, e.g. Google Authenticator/Authy) can be
  required by your organisation's security policy; you'll be prompted for a
  code after your password or magic link.

If you no longer want emails from TTLI, every notification includes an
unsubscribe link (`/unsubscribe/{id}`).

## 3. Learning

- **Your enrolments** (`/learn`) — everything you're enrolled in: courses,
  paths and any workshop sessions you've booked.
- **Taking a course** (`/learn/{enrolment}`) — watch video lessons (with
  captions), read text lessons, and complete embedded quizzes, surveys and
  assignments as you go. Video playback is protected against skipping ahead
  of unwatched content where the course requires it.
- **Learning-path progress** (`/learn/paths/{pathEnrolment}`) — see your
  position across every course inside a path and what's left to finish it.
- **Live workshop sessions** (`/learn/sessions`) — your booked or attended
  workshop sessions, with joining details for online sessions.
- **Transcript** (`/learn/[enrolment]/transcript`) — a record of what you've
  completed inside a course, useful for compliance/CPD-style reporting.
- **Certificates** — issued automatically on completing a course, path or
  workshop that awards one; available from your account area once earned.
- **Preview** (`/preview/{lesson}`) — a limited, unauthenticated preview of
  a lesson, used for marketing/sample content rather than full delivery.

## 4. Booking and attending workshops

- Find a workshop on its detail page (`/workshops/{workshop}`) and book a
  session (`/workshops/{workshop}/book`). Available session dates, capacity
  and facilitator are shown before you confirm.
- After booking, the session appears under `/learn/sessions`. If the
  workshop runs online, join details (including any Microsoft Teams link)
  are provided there closer to the session date.
- Attendance is recorded by the facilitator during/after the session and
  feeds into your transcript and any certificate the workshop awards.

## 5. Managing your account

- **Account home** (`/account`) — your profile and personal details.
- **Invoices** (`/account/invoices`) — download invoices for anything
  you've purchased directly (not seat-based access granted by an
  organisation).
- **Subscription** (`/account/subscription`) — manage an active
  subscription plan, if your access is subscription-based rather than a
  one-off purchase.

## 6. Organisation / corporate administration

If you administer an organisation's TTLI account, you have an additional
area at `/organisations/{your-organisation}`:

- **Members** — see everyone in your organisation and their role:
  - `member` — can use seats allocated to them, no admin rights.
  - `manager` — can be granted visibility into their team's individual
    learning results, if your organisation admin has enabled manager
    visibility (off by default — individual results are otherwise hidden
    from anyone but the learner and an organisation admin).
  - `admin` — full organisation management: invite/remove members, allocate
    seats, configure manager visibility, view reporting.
- **Seats** — see how many seats you've bought per course/path/workshop and
  how many are in use. Buy more seats from `/organisations/{id}/buy-seats`.
- **Invitations** — invite people by email; they receive a link to activate
  their account and consume a seat once they accept.
- **Reporting** (`/admin/reports`, `/admin/reports/courses`) — completion
  and progress reporting across your organisation's members, for admins and
  managers with visibility enabled.

## 7. Facilitators

If you deliver workshops, your facilitator view shows the sessions you're
assigned to, expected attendees, and where to mark attendance. Facilitator
scheduling/availability and session management are administered by the
platform team on your behalf during this UAT phase; self-service facilitator
tools are on the platform roadmap.

## 8. Getting help

- **FAQ** (`/faq`) — answers to common questions about the platform,
  courses and billing.
- **Contact** (`/contact`) — reach the TTLI team directly.
- **Privacy** (`/privacy`) and **Terms** (`/terms`) — data handling and
  terms of use, including your rights under South Africa's POPIA (right to
  request an export or deletion of your personal data — contact TTLI
  support to exercise these).

## Known gaps during UAT

The items below are genuinely not finished yet — this section exists so
you don't assume something you can't find is a bug in your own account:

- **Partner/reseller self-service portal** (partner organisations managing
  their own client organisations) is still backend-only; there's no partner
  UI to sign into yet.
- **Independent assessment platform and analyst report workflow** (used by
  TTLI's own assessment analysts, not by learners or organisation admins)
  are backend-only and not reachable from any screen yet.
- **Facilitator licensing and xAPI export** for external LMS interoperability
  is backend-only.
- Live payment-gateway certification, Microsoft Teams live validation, and
  formal accessibility/launch acceptance testing are still in progress —
  you may see rough edges in those specific flows during UAT.

If you hit something that looks broken and isn't listed above, please report
it via `/contact` rather than assuming it's expected.
