import Image from "next/image";
import Link from "next/link";

import { CourseCard } from "@/app/catalogue/course-card";
import { FACILITATORS } from "@/lib/facilitators";
import { formatClock } from "@/lib/format";
import { getPublicCourses, getPublicEpisodes, getTheme } from "@/lib/server-api";

/**
 * The public marketing landing page (Phase 2, REQ-STORE-01/02/06) —
 * prototype screen 1.
 *
 * The page no longer renders a header of its own: components/
 * site-header.tsx puts the prototype's `.site-head` on every non-admin
 * route, and a second bar underneath it was the last piece of the old
 * layout still competing with it.
 *
 * Content below the programmes grid — the About narrative, team, client
 * list, "Lead with Intent" book — is TTLI's real copy and imagery,
 * extracted from https://ttli.co.za/ at the customer's own request
 * (docs/brand/ttli-brand-identity.md has full provenance). It is
 * intentionally not theme-driven the way the logo/colors are: no CMS
 * exists yet for a second tenant to supply its own marketing copy, so
 * this page is TTLI-specific content wrapped in tenant-driven chrome.
 *
 * "Lead with Intent" (/lead-with-intent) and a working contact form
 * (/contact, source="contact_form" through POST /leads) are real pages.
 * Podcasts (/podcasts) is a real platform too — own episodes plus
 * admin-curated third-party recommendations — but genuinely empty of
 * TTLI content today (01_PRD.md §1.4), which is why the hero card falls
 * back to a plain invitation when no episode is published.
 */

// Static bar heights for the `.wave` — decoration, not a waveform: the
// API exposes no peak data, and inventing one per episode would imply a
// precision that isn't there.
const WAVE = [30, 55, 80, 45, 95, 60, 35, 70, 100, 50, 75, 40, 85, 30, 65, 45, 90, 55, 25, 60];

// Real content only — see docs/brand/ttli-brand-identity.md ("Lead with
// Intent") and cultivate-with-intent/page.tsx's own docstring (sourced
// from the book's retail listing) for provenance. coverHeight preserves
// each cover's real aspect ratio at width=160 rather than distorting it.
const BOOKS = [
  {
    href: "/lead-with-intent",
    title: "Lead with Intent",
    cover: "/brand/book-lead-with-intent.jpg",
    coverHeight: 244,
    blurb:
      "A ground-breaking book that reveals nine leadership principles and practices that drive engagement and commitment in the workplace — the foundation the Institute's own programmes are built from.",
  },
  {
    href: "/cultivate-with-intent",
    title: "Cultivate with Intent",
    cover: "/brand/book-cultivate-with-intent.jpg",
    coverHeight: 222,
    blurb:
      "A blueprint for leaders to become worldclass cultural architects — practical strategies for building healthier workplaces, drawn from 30+ years across 130+ organisations.",
  },
];

export const dynamic = "force-dynamic";

export default async function LandingPage() {
  const [theme, courses, episodes] = await Promise.all([
    getTheme(),
    getPublicCourses(),
    getPublicEpisodes(),
  ]);
  const name = theme?.tenant_name ?? "Themba Thandeka Leadership Institute";

  // `GET /public/podcasts` is ordered by the curator's own `position`, so
  // the first row is what the site leads with.
  const latest = episodes[0] ?? null;
  const executiveCount = courses.filter((course) => course.level === "executive").length;

  // "Popular" has no signal behind it yet (no enrolment counts on the
  // public endpoint), so the three cards shown are the most completely
  // presented courses — the ones with art, topic and level filled in —
  // newest first. A catalogue of bare test rows therefore still renders
  // three plausible cards rather than three blank ones.
  const popular = [...courses]
    .sort((a, b) => {
      const score = (c: (typeof courses)[number]) =>
        (c.hero_colour ? 1 : 0) + (c.topic ? 1 : 0) + (c.level ? 1 : 0) + (c.summary ? 1 : 0);
      return score(b) - score(a) || b.id.localeCompare(a.id);
    })
    .slice(0, 3);

  return (
    <main>
      {/* ---- Hero ----
          Full-bleed hero-texture.jpg behind a scrim, per the design
          handoff (docs/design/institute/README.md §"2. Storefront"). The
          scrim's stops are mixed from --ink via color-mix rather than the
          handoff's literal rgba(22,25,27,…) — same numeric value under
          the institute skin (#16191B), but tenant/skin-correct instead of
          hardcoded. Copy and links are unchanged from before this pass;
          only the container and its text colours (now light-on-dark)
          moved. hero-card keeps its own opaque surface and needs no
          colour override. */}
      <div className="hero-band">
        <Image
          src="/brand/hero-texture.jpg"
          alt=""
          fill
          priority
          sizes="100vw"
          className="hero-band__bg"
          style={{ objectFit: "cover" }}
        />
        <div className="hero-band__scrim" aria-hidden="true" />
        <div className="pad-lg hero-band__content">
          <div className="hero">
            <div>
              <p className="eyebrow">Leadership &middot; Strategy &middot; Organisational behaviour</p>
              <h1>Leadership training that can prove someone actually did it.</h1>
              <p className="sub">
                Executive programmes with enforced completion, verifiable certificates and live
                facilitated workshops. Built for individuals and for organisations that need the
                completion report to mean something.
              </p>
              <div className="hero-cta">
                <Link href="/catalogue" className="btn btn--primary btn--lg">
                  Explore courses
                </Link>
                <Link href="/guest-access" className="btn btn--ghost btn--lg">
                  Try a free lesson
                </Link>
              </div>
              <div className="hero-trust">
                <div>
                  <strong>{executiveCount}</strong>
                  <span>Executive programmes</span>
                </div>
                <div>
                  <strong>{FACILITATORS.length}</strong>
                  <span>Facilitators</span>
                </div>
                <div>
                  <strong>100%</strong>
                  <span>Server-verified completion</span>
                </div>
              </div>
            </div>

            <div className="hero-card">
              <p className="eyebrow">{latest ? "Latest episode" : "Podcast"}</p>
              <h3 className="serif" style={{ fontSize: "1.1875rem" }}>
                {latest ? latest.title : "Conversations on leadership, free to everyone"}
              </h3>
              <div className="wave" aria-hidden="true">
                {WAVE.map((height, index) => (
                  <i key={index} style={{ height: `${height}%` }} />
                ))}
              </div>
              {latest?.duration_seconds ? (
                <div className="times">
                  <span>00:00</span>
                  <span>{formatClock(latest.duration_seconds)}</span>
                </div>
              ) : null}
              <Link
                href={latest ? `/podcasts/${latest.slug}` : "/podcasts"}
                className="btn btn--ghost btn--block"
              >
                Listen &middot; free, no account
              </Link>
            </div>
          </div>
        </div>
      </div>

      {/* ---- Three pillars ---- */}
      <div className="band">
        <div className="pad">
          <div className="cols-3">
            <div className="cell">
              <h3>Completion you can audit</h3>
              <p>
                Watch time, assessment scores and attendance are validated on the server. Clicking
                Next eleven times does not finish a course.
              </p>
            </div>
            <div className="cell">
              <h3>Certificates that verify</h3>
              <p>
                Every certificate carries a QR code and a public verification page showing valid,
                expired or revoked.
              </p>
            </div>
            <div className="cell">
              <h3>Reporting that respects staff</h3>
              <p>
                Managers see team progress in aggregate. Individual scores stay private unless an
                administrator opens them per course.
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* ---- Popular programmes ---- */}
      {popular.length > 0 ? (
        <div className="pad-lg">
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "baseline",
              gap: "1rem",
              flexWrap: "wrap",
              marginBottom: "1.1rem",
            }}
          >
            <h2 className="serif" style={{ fontSize: "1.5rem" }}>
              Popular programmes
            </h2>
            <Link href="/catalogue" className="btn btn--quiet">
              View all {courses.length} &rarr;
            </Link>
          </div>
          <div className="course-grid">
            {popular.map((course) => (
              <CourseCard key={course.id} course={course} />
            ))}
          </div>
        </div>
      ) : null}

      {/* ---- About ---- */}
      <div className="band">
        <div className="pad-lg" id="about">
          <div style={{ maxWidth: "48rem", marginInline: "auto", textAlign: "center" }}>
            <p className="eyebrow">About</p>
            <p className="serif" style={{ fontSize: "1.1875rem", color: "var(--ink-2)", marginTop: "0.75rem" }}>
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
      </div>

      {/* ---- The books ----
          Two titles, so this is a static side-by-side shelf, not a
          carousel: a carousel's arrows/dots earn their keep past ~4-5
          items, and for two they'd just look like a control with nowhere
          real to go. Revisit as a carousel only once a third title is
          confirmed and this stops fitting comfortably in one row. */}
      <div className="pad-lg" id="programme">
        <p className="eyebrow" style={{ textAlign: "center" }}>
          By founder Hermann du Plessis
        </p>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(20rem, 1fr))",
            gap: "2.5rem",
            maxWidth: "56rem",
            marginInline: "auto",
            marginTop: "1.25rem",
          }}
        >
          {BOOKS.map((book) => (
            <div
              key={book.href}
              style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "1.5rem" }}
            >
              <Image
                src={book.cover}
                alt={`${book.title}, by Hermann du Plessis`}
                width={160}
                height={book.coverHeight}
                style={{ flex: "none", boxShadow: "var(--shadow-2)" }}
              />
              <div style={{ flex: "1 1 12rem" }}>
                <h2 className="serif" style={{ fontSize: "1.375rem" }}>
                  {book.title}
                </h2>
                <p style={{ fontSize: "0.875rem", color: "var(--ink-2)", marginTop: "0.6rem" }}>
                  {book.blurb}
                </p>
                <Link href={book.href} className="btn btn--ghost" style={{ marginTop: "0.85rem" }}>
                  Read more
                </Link>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ---- Client logos ---- */}
      <div className="band">
        <div className="pad-lg" id="partners">
          <p className="eyebrow" style={{ textAlign: "center" }}>
            Organisations we&rsquo;ve worked with
          </p>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(7rem, 1fr))",
              gap: "2.375rem",
              alignItems: "center",
              marginTop: "2rem",
            }}
          >
            {[
              ["standard-bank", "Standard Bank"],
              ["hensoldt", "HENSOLDT"],
              ["delonghi", "De'Longhi"],
              ["floorworx", "Floorworx"],
              ["itec-evolve", "ITEC Evolve"],
              ["shangoni", "Shangoni Management Services"],
              ["earthlab", "Earthlab"],
              ["twk", "TWK"],
              ["barberton-mines", "Barberton Mines"],
            ].map(([file, alt]) => (
              <Image
                key={file}
                src={`/brand/partners/${file}.png`}
                alt={alt}
                width={140}
                height={60}
                style={{
                  objectFit: "contain",
                  width: "100%",
                  height: "auto",
                  opacity: 0.55,
                  filter: "grayscale(1)",
                }}
              />
            ))}
          </div>
        </div>
      </div>

      {/* ---- Buying for a team? ----
          Same message as the seat-bundle callout on /catalogue
          (catalogue-browser.tsx), promoted to a dark CTA band per the
          design handoff — copy reused verbatim, not reinvented. */}
      <div className="cta-band">
        <div>
          <h2 className="serif">Buying for a team?</h2>
          <p>
            Seat bundles from five learners include a manager dashboard, invoice or EFT payment
            and purchase-order support.
          </p>
        </div>
        <Link
          href="/organisations"
          className="btn"
          style={{ background: "var(--on-brand)", color: "var(--ink)", flex: "none" }}
        >
          Talk to us
        </Link>
      </div>

      {/* ---- Facilitators ----
          This is a teaser, not the team showcase — /about is that page,
          and keeps the larger 220x330 treatment. On the homepage, sized
          back down close to the original 120x160 footprint (user
          feedback: 220x330 felt "overpowering" here) but at 112x168, the
          source photos' real 2:3 ratio — the original 120x160 wasn't
          that ratio, so objectFit:cover was quietly cropping every one. */}
      <div className="pad-lg">
        <p className="eyebrow" style={{ textAlign: "center" }}>
          Facilitators
        </p>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(9rem, 1fr))",
            gap: "1.75rem",
            marginTop: "2rem",
            maxWidth: "48rem",
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
                width={112}
                height={168}
                style={{
                  objectFit: "cover",
                  borderRadius: "4px",
                  marginInline: "auto",
                  width: "100%",
                  height: "auto",
                }}
              />
              <p style={{ fontSize: "0.8125rem", fontWeight: 600, marginTop: "0.5rem" }}>
                {person.name}
              </p>
              <p style={{ fontSize: "0.75rem", color: "var(--muted)" }}>{person.role}</p>
            </Link>
          ))}
        </div>
        <p style={{ textAlign: "center", marginTop: "2rem" }}>
          <Link href="/about" className="btn btn--ghost">
            Meet the whole team
          </Link>
        </p>
      </div>

      {/* ---- Footer / contact ---- */}
      <footer className="pad-lg" style={{ background: "var(--ink)", color: "var(--on-brand)" }}>
        <div style={{ maxWidth: "40rem", marginInline: "auto", textAlign: "center" }}>
          <p className="eyebrow" style={{ color: "var(--on-brand)", opacity: 0.7 }}>
            Get in touch
          </p>
          <p className="serif" style={{ fontSize: "1.0625rem", marginTop: "0.5rem" }}>
            We would really like to hear from you.
          </p>
          <p style={{ fontSize: "0.8125rem", opacity: 0.85, marginTop: "1rem" }}>
            30 Kasbah Ridge, Egale Canyon Golf Estate
          </p>
          <Link
            href="/contact"
            className="btn btn--ghost"
            style={{ borderColor: "var(--on-brand)", color: "var(--on-brand)", marginTop: "1rem" }}
          >
            Send us a message
          </Link>
          <p style={{ fontSize: "0.75rem", opacity: 0.55, marginTop: "1.5rem" }}>
            Terms of usage &amp; privacy &middot; Copyright &copy; {name} 2026
          </p>
        </div>
      </footer>
    </main>
  );
}
