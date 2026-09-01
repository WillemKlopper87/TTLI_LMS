import Link from "next/link";

import { getTheme } from "@/lib/server-api";

/**
 * POPIA-oriented privacy notice (South Africa is this platform's home
 * jurisdiction — ttli.co.za, Payfast checkout, docs/brand/ttli-brand-
 * identity.md). Tenant name is read the same way layout.tsx and
 * manifest.ts do, since this is a white-label platform and the notice
 * must speak for whichever tenant is actually running it.
 *
 * Drafted from what the platform actually does today (contact/guest-
 * access leads, learner accounts, privacy-thresholded survey reporting,
 * Payfast-hosted payments, functional-only cookies) rather than generic
 * boilerplate — but this is a first draft, not legal advice. It needs
 * sign-off from the tenant and, ideally, a lawyer before it's relied on
 * in production. The contact address below is the tenant's own
 * admin-configured support_email (branding-panel.tsx) — falls back to
 * the /contact page when a tenant hasn't set one.
 */
export const metadata = {
  title: "Privacy policy",
  description: "How we collect, use and protect your personal information.",
  alternates: { canonical: "/privacy" },
};

export default async function PrivacyPage() {
  const theme = await getTheme();
  const name = theme?.tenant_name ?? "Themba Thandeka Leadership Institute";

  return (
    <main className="pad-lg">
      <div className="prose" style={{ marginInline: "auto" }}>
        <Link href="/" className="btn btn--ghost" style={{ marginBottom: "1.5rem" }}>
          &larr; Back to home
        </Link>
        <p className="eyebrow">Legal</p>
        <h1 className="serif" style={{ fontSize: "2rem", marginTop: "0.5rem" }}>
          Privacy policy
        </h1>
        <p className="lead">
          This notice explains what personal information {name} collects through this platform,
          why we collect it, and the choices and rights you have over it. It is written to comply
          with South Africa&rsquo;s Protection of Personal Information Act (POPIA).
        </p>

        <h2>Information we collect</h2>
        <ul>
          <li>
            <strong>Contact and enquiry details</strong> &mdash; name, email address, and message
            content when you use our contact form or request guest access, plus any optional
            details you choose to share (company, job title, team size, training goal).
          </li>
          <li>
            <strong>Account and learning data</strong> &mdash; name, email, enrolment history,
            course progress, assessment results and certificates once you register or are enrolled
            as a learner.
          </li>
          <li>
            <strong>Survey and coaching responses</strong> &mdash; where we run pre- and
            post-programme surveys, individual responses are protected by a minimum reporting
            threshold: your organisation only ever sees aggregated results, never your individual
            answers, unless the group is large enough that no individual can be identified.
          </li>
          <li>
            <strong>Payment information</strong> &mdash; course and workshop payments are processed
            by Payfast on their own hosted payment page. We never see or store your card details;
            we receive only confirmation that a payment succeeded or failed.
          </li>
          <li>
            <strong>Technical data</strong> &mdash; standard web server logs, the functional
            cookies described below, and a first-party count of which pages are viewed on our
            public site. Pageviews are not linked to your account or to each other &mdash; we do
            not use a tracking cookie or any other identifier to follow you across pages or
            visits, and we do not share this data with any third-party analytics provider.
          </li>
        </ul>

        <h2>Why we process it</h2>
        <p>We use your information to:</p>
        <ul>
          <li>respond to enquiries and provide guest access to preview content;</li>
          <li>create and administer learner accounts, enrolments and certificates;</li>
          <li>process payments for courses and workshops;</li>
          <li>
            report on programme engagement and outcomes to your organisation, subject to the
            privacy threshold described above;
          </li>
          <li>
            send you marketing communications, but only where you have separately opted in
            (marketing consent is always a distinct, optional choice from the consent required to
            submit a form);
          </li>
          <li>meet our legal, tax and regulatory obligations.</li>
        </ul>

        <h2>Cookies</h2>
        <p>
          This platform currently uses only <strong>strictly necessary, functional cookies</strong>
          &mdash; to keep you signed in and to remember your display preferences. We do not
          currently use analytics, advertising or other tracking cookies. If that changes, this
          notice and the site will be updated to ask for your consent before any non-essential
          cookie is set.
        </p>

        <h2>Sharing your information</h2>
        <p>
          We do not sell personal information. We share it only with service providers who help us
          run the platform &mdash; our payment processor (Payfast) and infrastructure/hosting
          providers &mdash; under agreements that require them to protect it, and only to the
          extent needed to provide the service.
        </p>

        <h2>How we protect it</h2>
        <p>
          Sensitive fields are encrypted at rest, access to learner and survey data is scoped and
          audited, and organisations only ever see each other&rsquo;s data if they choose to share
          it &mdash; each tenant&rsquo;s data is isolated from every other tenant on this platform.
        </p>

        <h2>How long we keep it</h2>
        <p>
          We keep personal information for as long as your account is active, plus any further
          period required to meet our legal, tax or regulatory obligations, after which it is
          deleted or anonymised.
        </p>

        <h2>Your rights</h2>
        <p>Under POPIA, you have the right to:</p>
        <ul>
          <li>ask us what personal information we hold about you and why;</li>
          <li>ask us to correct or update inaccurate information;</li>
          <li>ask us to delete your information, subject to our legal retention obligations;</li>
          <li>object to your information being used for marketing at any time;</li>
          <li>
            lodge a complaint with South Africa&rsquo;s Information Regulator if you believe we
            have not handled your information properly.
          </li>
        </ul>

        <h2>Contact us</h2>
        <p>
          To exercise any of these rights, or if you have questions about this notice, contact our
          Information Officer{" "}
          {theme?.support_email ? (
            <>
              at <a href={`mailto:${theme.support_email}`}>{theme.support_email}</a>
            </>
          ) : (
            <>via our <a href="/contact">contact page</a></>
          )}
          .
        </p>

        <h2>Changes to this notice</h2>
        <p>
          We may update this notice from time to time. The version published here always reflects
          our current practice.
        </p>
      </div>
    </main>
  );
}
