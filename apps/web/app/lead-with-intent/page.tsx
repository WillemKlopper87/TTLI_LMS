import Image from "next/image";
import Link from "next/link";

export const metadata = {
  title: "Lead with Intent",
  description:
    "Nine leadership principles and practices that drive engagement and commitment in the workplace — by founder Hermann du Plessis.",
  alternates: { canonical: "/lead-with-intent" },
};

/**
 * A dedicated page for "Lead with Intent" (Phase 2 close-out) — the real
 * site's top-level nav item and founder Hermann du Plessis's book. Content
 * is verbatim from docs/brand/ttli-brand-identity.md's second extraction
 * pass; nothing here is invented.
 */
export default function LeadWithIntentPage() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <Link href="/" className="btn btn--ghost">
        &larr; Back
      </Link>

      <div className="mt-8 flex flex-col items-center gap-8 text-center md:flex-row md:text-left">
        <Image
          src="/brand/book-lead-with-intent.jpg"
          alt="Lead with Intent, by Hermann du Plessis"
          width={260}
          height={395}
          className="mx-auto shrink-0 shadow-md md:mx-0"
        />
        <div>
          <p className="eyebrow">By founder Hermann du Plessis</p>
          <h1 className="serif mt-2" style={{ fontSize: "2rem" }}>
            Lead with Intent
          </h1>
          <p className="mt-4" style={{ fontSize: "1rem", color: "var(--ink-2)" }}>
            A ground-breaking book that reveals nine leadership principles and practices that
            drive engagement and commitment in the workplace — the foundation the Institute&rsquo;s
            own programmes are built from.
          </p>
        </div>
      </div>

      <div className="mt-16">
        <p className="eyebrow">About the author</p>
        <div className="mt-4 flex items-start gap-6">
          <Image
            src="/brand/team/team-hermann-du-plessis.jpg"
            alt="Hermann du Plessis"
            width={100}
            height={130}
            style={{ objectFit: "cover", borderRadius: "4px" }}
            className="shrink-0"
          />
          <p style={{ fontSize: "0.9375rem", color: "var(--ink-2)" }}>
            Hermann du Plessis is the founder of Themba Thandeka Leadership Institute, with 20
            years&rsquo; experience and more than 15,000 coaching hours. The Institute has worked
            with more than 90 organisations in 19 countries.
          </p>
        </div>
      </div>

      <div className="mt-16 flex justify-center gap-3">
        <Link href="/catalogue" className="btn btn--primary btn--lg">
          Browse programmes
        </Link>
        <Link href="/contact" className="btn btn--ghost btn--lg">
          Get in touch
        </Link>
      </div>
    </main>
  );
}
