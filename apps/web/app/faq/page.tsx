import Link from "next/link";

import { getTheme } from "@/lib/server-api";

/**
 * FAQ (checklist item 8). Every answer below is drawn from what the
 * platform actually does elsewhere — guest-access/guest-access-form.tsx
 * (14 days, watermarked, no certificate), login/page.tsx (magic link,
 * no password), courses/[courseId]/page.tsx and terms/page.tsx
 * (server-verified completion, certificates, refunds), for-
 * organisations/page.tsx (seat pools, aggregate-only reporting),
 * privacy/page.tsx (survey threshold, first-party pageviews) — not
 * invented policy. `<details>` rather than a client accordion: no JS
 * needed for something this simple, and it's keyboard- and
 * screen-reader-accessible for free.
 */
export const metadata = {
  title: "FAQ",
  description: "Answers to common questions about courses, certificates, payment and privacy.",
  alternates: { canonical: "/faq" },
};

interface Question {
  q: string;
  a: React.ReactNode;
}

interface Section {
  title: string;
  questions: Question[];
}

export default async function FaqPage() {
  const theme = await getTheme();
  const name = theme?.tenant_name ?? "Themba Thandeka Leadership Institute";

  const sections: Section[] = [
    {
      title: "Getting started",
      questions: [
        {
          q: "Can I try a course before I pay?",
          a: (
            <>
              Yes. <Link href="/guest-access">Guest access</Link> gives you one full sample
              lesson and a sample assessment, marked the same way the real one is, for 14 days.
              Sample content is watermarked and no certificate is issued. If you go on to buy,
              your progress carries across to the paid enrolment.
            </>
          ),
        },
        {
          q: "Do I need a password?",
          a: (
            <>
              No. We send a one-time sign-in link to your email instead. It works once and
              expires after fifteen minutes, so there is no password to leak, forget or reuse.
            </>
          ),
        },
        {
          q: "What if my organisation already has an account?",
          a: (
            <>
              Guest access matches you to an existing corporate account by your work email
              domain. If your organisation has bought seats, ask your administrator to invite
              you directly instead.
            </>
          ),
        },
      ],
    },
    {
      title: "Courses, certificates and workshops",
      questions: [
        {
          q: "How is completion decided?",
          a: "Watch time, assessment scores and attendance are validated on our server — clicking through a lesson does not finish it.",
        },
        {
          q: "What do I get when I finish a course?",
          a: "A certificate carrying a QR code and a public verification page, so anyone can confirm it's valid, expired or revoked.",
        },
        {
          q: "What's a learning path?",
          a: "A bundle of several courses, completed in order as one purchase, with its own certificate once every course in it is done.",
        },
        {
          q: "What are the live workshops?",
          a: "Facilitated sessions — either a group cohort or one-on-one coaching — booked around real upcoming dates rather than on-demand.",
        },
      ],
    },
    {
      title: "Payment",
      questions: [
        {
          q: "How do I pay, and is it safe?",
          a: (
            <>
              Card and EFT payments are processed on Payfast&rsquo;s own hosted page &mdash; we
              never see or store your card details. Organisations can also pay by purchase
              order, with a pro-forma invoice issued immediately and a sequentially numbered tax
              invoice following approval.
            </>
          ),
        },
        {
          q: "Can I get a refund?",
          a: (
            <>
              Refunds are considered case-by-case &mdash;{" "}
              <Link href="/contact">contact us</Link> before a course starts if you need to
              request one. See our <Link href="/terms">terms of use</Link> for the full policy.
            </>
          ),
        },
        {
          q: "Do you offer subscriptions?",
          a: "Some tenants offer continuous access to a bundle of programmes, billed per period, alongside one-time course purchases.",
        },
      ],
    },
    {
      title: "For organisations",
      questions: [
        {
          q: "How do seat pools work?",
          a: "Buy a bundle of five or more seats, then invite your people by email one at a time or import a CSV. Seats are a pool — revoke someone who leaves and reassign the seat to their replacement.",
        },
        {
          q: "Can managers see individual results?",
          a: "Not by default. Managers see aggregate progress; individual assessment results stay private unless an administrator explicitly opens them for a specific course.",
        },
      ],
    },
    {
      title: "Privacy",
      questions: [
        {
          q: "Are my survey answers shared with my employer?",
          a: "Individual responses are protected by a minimum reporting threshold — your organisation only ever sees aggregated results, never your individual answers, unless the group is large enough that no one can be identified.",
        },
        {
          q: "Does the site track me?",
          a: (
            <>
              We count pageviews on our public pages first-party, with no persistent identifier
              and no third-party analytics or advertising cookies. See our{" "}
              <Link href="/privacy">privacy policy</Link> for the full picture.
            </>
          ),
        },
      ],
    },
  ];

  return (
    <main className="pad-lg">
      <div style={{ maxWidth: "42rem", marginInline: "auto" }}>
        <Link href="/" className="btn btn--ghost" style={{ marginBottom: "1.5rem" }}>
          &larr; Back to home
        </Link>
        <p className="eyebrow">Help</p>
        <h1 className="serif" style={{ fontSize: "2rem", marginTop: "0.5rem" }}>
          Frequently asked questions
        </h1>
        <p style={{ color: "var(--muted)", marginTop: "1rem" }}>
          Can&rsquo;t find what you&rsquo;re looking for?{" "}
          <Link href="/contact">Get in touch</Link> and {name} will answer directly.
        </p>

        {sections.map((section) => (
          <div key={section.title} style={{ marginTop: "2.5rem" }}>
            <h2 className="serif" style={{ fontSize: "1.25rem", marginBottom: "0.75rem" }}>
              {section.title}
            </h2>
            <div style={{ display: "grid", gap: "0.5rem" }}>
              {section.questions.map((item) => (
                <details
                  key={item.q}
                  style={{
                    border: "1px solid var(--rule)",
                    borderRadius: "var(--r)",
                    padding: "0.85rem 1rem",
                  }}
                >
                  <summary
                    style={{ cursor: "pointer", fontWeight: 600, color: "var(--ink)" }}
                  >
                    {item.q}
                  </summary>
                  <p style={{ marginTop: "0.6rem", color: "var(--ink-2)", fontSize: "0.9375rem" }}>
                    {item.a}
                  </p>
                </details>
              ))}
            </div>
          </div>
        ))}
      </div>
    </main>
  );
}
