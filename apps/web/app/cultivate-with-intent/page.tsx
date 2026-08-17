import Image from "next/image";
import Link from "next/link";

/**
 * A dedicated page for "Cultivate with Intent" — founder Hermann du
 * Plessis's second book, closing the gap `docs/STATUS.md` had flagged
 * since Phase 2 ("the real site names it in its nav, but no page content
 * was ever extracted... building it now would mean fabricating copy").
 * Content here is real, not invented: title, subtitle, cover, description
 * and the Brand Pretorius blurb come from the book's own retail listing
 * (https://exclusivebooks.co.za/products/9781049251486), supplied by the
 * customer — the same "verbatim from a real source, cited" standard
 * `docs/brand/ttli-brand-identity.md` set for "Lead with Intent".
 *
 * The "90 organisations / 19 countries" line on the homepage and on
 * /lead-with-intent is TTLI's own site copy; this book's retail
 * description separately says "130+ organizations in 23 countries" —
 * different sources, likely different points in time. Left as the book's
 * own jacket copy rather than silently reconciled with the site's number.
 */
export default function CultivateWithIntentPage() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <Link href="/" className="btn btn--ghost">
        &larr; Back
      </Link>

      <div className="mt-8 flex flex-col items-center gap-8 text-center md:flex-row md:text-left">
        <Image
          src="/brand/book-cultivate-with-intent.jpg"
          alt="Cultivate with Intent, by Hermann du Plessis"
          width={260}
          height={361}
          className="mx-auto shrink-0 shadow-md md:mx-0"
        />
        <div>
          <p className="eyebrow">By founder Hermann du Plessis</p>
          <h1 className="serif mt-2" style={{ fontSize: "2rem" }}>
            Cultivate with Intent
          </h1>
          <p className="mt-1" style={{ fontSize: "0.9375rem", color: "var(--muted)" }}>
            A Blueprint for Leaders to Become Worldclass Cultural Architects
          </p>
          <p className="mt-4" style={{ fontSize: "1rem", color: "var(--ink-2)" }}>
            Organisational culture as the environment people swim in every day. Drawing on more
            than 30 years of experience across 130+ organisations in 23 countries, the book
            identifies common cultural pitfalls and sets out practical strategies for building
            healthier workplaces — positioning leaders as the cultural architects who design the
            environments their people and organisations actually flourish in. Builds on the ideas
            in his earlier book, <Link href="/lead-with-intent">Lead with Intent</Link>.
          </p>
        </div>
      </div>

      <div className="mt-12">
        <blockquote
          className="prose"
          style={{
            borderLeft: "3px solid var(--rule)",
            paddingLeft: "1.25rem",
            fontStyle: "italic",
            color: "var(--muted)",
          }}
        >
          &ldquo;Hermann positions leaders as cultural architects &mdash; visionaries who
          consciously design environments that elevate engagement and drive excellence.
          Insightful, practical, and transformative reading for all executives.&rdquo;
          <footer style={{ marginTop: "0.5rem", fontStyle: "normal", fontSize: "0.8125rem" }}>
            &mdash; Brand Pretorius
          </footer>
        </blockquote>
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
