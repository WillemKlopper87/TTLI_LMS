import Link from "next/link";

import { getTheme } from "@/lib/server-api";

/**
 * Terms of use — companion to /privacy (see that file's header comment
 * for the same caveats: drafted from real platform behaviour, tenant
 * name resolved the same way, but a first draft that needs the tenant's
 * and ideally a lawyer's sign-off before launch).
 */
export const metadata = {
  title: "Terms of use",
  description: "The terms that govern your use of this platform.",
  alternates: { canonical: "/terms" },
};

export default async function TermsPage() {
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
          Terms of use
        </h1>
        <p className="lead">
          These terms govern your use of this platform, operated by {name}. By creating an
          account, enrolling in a course or workshop, or otherwise using this site, you agree to
          them.
        </p>

        <h2>Accounts</h2>
        <p>
          You are responsible for keeping your login credentials confidential and for all activity
          under your account. Tell us immediately if you suspect unauthorised access. You must
          provide accurate information when registering or enrolling.
        </p>

        <h2>Courses, workshops and content</h2>
        <p>
          Course materials, videos, workshop content, articles and podcasts made available through
          this platform are owned by {name} or its licensors and are provided for your personal,
          non-commercial learning use only. You may not copy, redistribute, resell or publicly
          share this content without our written permission.
        </p>
        <p>
          Access to a course, learning path or workshop is granted for the enrolment period stated
          at the time of purchase or assignment. Certificates are issued on successful completion
          of the relevant assessment criteria.
        </p>

        <h2>Payments and refunds</h2>
        <p>
          Payments are processed securely by Payfast on their own hosted payment page; we never
          receive or store your card details. Prices are shown before you confirm a purchase.
          Refunds are considered on a case-by-case basis &mdash; contact us before a course starts
          if you need to request one.
        </p>

        <h2>Acceptable use</h2>
        <p>You agree not to:</p>
        <ul>
          <li>use the platform for any unlawful purpose;</li>
          <li>attempt to gain unauthorised access to another user&rsquo;s account or data;</li>
          <li>upload content that is harmful, infringing, or that you do not have the right to share;</li>
          <li>interfere with or disrupt the platform&rsquo;s operation or security.</li>
        </ul>

        <h2>Surveys and assessments</h2>
        <p>
          Where a course includes pre- or post-programme surveys, your individual responses are
          protected by a minimum reporting threshold, as described in our{" "}
          <a href="/privacy">privacy policy</a>. Assessment results may be shared with your
          organisation where you are enrolled through them.
        </p>

        <h2>Availability</h2>
        <p>
          We aim to keep the platform available at all times but do not guarantee uninterrupted
          access. We may suspend access for maintenance, security, or to comply with legal
          obligations.
        </p>

        <h2>Liability</h2>
        <p>
          The platform and its content are provided &ldquo;as is&rdquo;. To the extent permitted by
          law, {name} is not liable for indirect or consequential loss arising from your use of the
          platform. Nothing in these terms limits liability that cannot be excluded under South
          African law.
        </p>

        <h2>Termination</h2>
        <p>
          We may suspend or terminate your account if you breach these terms. You may stop using
          the platform at any time; this does not entitle you to a refund except as described
          above.
        </p>

        <h2>Governing law</h2>
        <p>These terms are governed by the laws of South Africa.</p>

        <h2>Changes to these terms</h2>
        <p>
          We may update these terms from time to time. Continued use of the platform after a
          change means you accept the updated terms.
        </p>

        <h2>Contact us</h2>
        <p>
          Questions about these terms can be sent{" "}
          {theme?.support_email ? (
            <>to <a href={`mailto:${theme.support_email}`}>{theme.support_email}</a></>
          ) : (
            <>via our <a href="/contact">contact page</a></>
          )}
          .
        </p>
      </div>
    </main>
  );
}
