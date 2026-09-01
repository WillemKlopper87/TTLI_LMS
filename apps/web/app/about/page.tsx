import Image from "next/image";
import Link from "next/link";

import { FACILITATORS } from "@/lib/facilitators";

/**
 * About Us — the narrative already on the homepage (`app/page.tsx`'s
 * `#about` band, real ttli.co.za copy per docs/brand/ttli-brand-identity.
 * md), plus the facilitator grid at the same larger size as the homepage
 * teaser, each card linking to its own /about/[slug] page.
 */
export const metadata = {
  title: "About us",
  description:
    "We train, consult and coach organisations in the essential skills needed to raise engagement.",
  alternates: { canonical: "/about" },
};

export default function AboutPage() {
  return (
    <main>
      <div className="pad-lg">
        <div style={{ maxWidth: "48rem", marginInline: "auto", textAlign: "center" }}>
          <p className="eyebrow">About</p>
          <h1 className="serif" style={{ fontSize: "2rem", marginTop: "0.5rem" }}>
            Themba Thandeka Leadership Institute
          </h1>
          <p
            className="serif"
            style={{ fontSize: "1.1875rem", color: "var(--ink-2)", marginTop: "1rem" }}
          >
            We train, consult and coach organisations in the essential skills needed to raise
            engagement. We offer value to customers through Engagement Analysis, Training,
            Consulting and Coaching within the spheres of Leadership, Strategy and Organisational
            Wellbeing.
          </p>
          <p style={{ fontSize: "0.9375rem", color: "var(--muted)", marginTop: "1rem" }}>
            We hold a deep belief that to work is a gift, and that the workplace should be an
            environment that inspires people to share their talent, experience, ideas, uniqueness
            and enthusiasm.
          </p>
          <p className="tag tag--brand" style={{ display: "inline-block", marginTop: "1.5rem" }}>
            90+ organisations &middot; 19 countries
          </p>
        </div>
      </div>

      <div className="pad-lg">
        <p className="eyebrow" style={{ textAlign: "center" }}>
          Facilitators
        </p>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(13rem, 1fr))",
            gap: "2rem",
            marginTop: "2rem",
            maxWidth: "56rem",
            marginInline: "auto",
          }}
        >
          {FACILITATORS.map((person) => (
            <Link
              key={person.slug}
              href={`/about/${person.slug}`}
              style={{ textAlign: "center", color: "inherit", textDecoration: "none" }}
              className="facilitator-card"
            >
              <Image
                src={`/brand/team/${person.photo}.jpg`}
                alt={person.name}
                width={220}
                height={330}
                style={{
                  objectFit: "cover",
                  borderRadius: "4px",
                  marginInline: "auto",
                  width: "100%",
                  height: "auto",
                }}
              />
              <p style={{ fontSize: "0.9375rem", fontWeight: 600, marginTop: "0.75rem" }}>
                {person.name}
              </p>
              <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>{person.role}</p>
            </Link>
          ))}
        </div>
      </div>

      <div className="pad-lg" style={{ textAlign: "center" }}>
        <Link href="/contact" className="btn btn--primary btn--lg">
          Get in touch
        </Link>
      </div>
    </main>
  );
}
