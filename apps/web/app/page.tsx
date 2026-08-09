import Image from "next/image";
import Link from "next/link";

import { getTheme } from "@/lib/server-api";

/**
 * The public marketing landing page (Phase 2, REQ-STORE-01/02/06).
 *
 * Content below — the About narrative, team, client list, "Lead with
 * Intent" book — is TTLI's real copy and imagery, extracted from
 * https://ttli.co.za/ at the customer's own request (docs/brand/
 * ttli-brand-identity.md has full provenance). It is intentionally not
 * theme-driven the way the logo/colors are: no CMS exists yet for a
 * second tenant to supply its own marketing copy, so this page is
 * TTLI-specific content wrapped in tenant-driven chrome.
 *
 * "Lead with Intent" (/lead-with-intent) and a working contact form
 * (/contact, source="contact_form" through POST /leads) are now real
 * pages. Still not built: Podcasts and "Cultivate with Intent" — no real
 * content was extracted for either (docs/brand/ttli-brand-identity.md
 * notes the real site names them in its nav but the extraction pass never
 * pulled episode/page content), so building them now would mean
 * fabricating copy. Genuinely blocked on the same content-inventory gap
 * as Phase 0 (01_PRD.md §1.4), not a missed task.
 */
export default async function LandingPage() {
  const theme = await getTheme();
  const name = theme?.tenant_name ?? "Themba Thandeka Leadership Institute";

  return (
    <>
      <header
        className="flex items-center justify-between px-6 py-4"
        style={{ borderBottom: "1px solid var(--rule)", background: "var(--surface)" }}
      >
        <Link href="/" className="flex items-center gap-2">
          {theme?.logo_url ? (
            <Image src={theme.logo_url} alt={name} width={120} height={63} priority />
          ) : (
            <span className="serif" style={{ fontSize: "1.0625rem", fontWeight: 600 }}>
              {name}
            </span>
          )}
        </Link>
        <nav className="hidden gap-6 md:flex" style={{ fontSize: "0.8125rem", color: "var(--ink-2)" }}>
          <a href="#about">About</a>
          <Link href="/lead-with-intent">Lead with Intent</Link>
          <a href="#partners">Clients</a>
          <Link href="/contact">Contact</Link>
        </nav>
        <div className="flex items-center gap-2">
          <Link href="/login" className="btn btn--ghost">
            Sign in
          </Link>
          <Link href="/guest-access" className="btn btn--primary">
            Try a free lesson
          </Link>
        </div>
      </header>

      <main>
        {/* ---- Hero ---- */}
        <div
          className="relative overflow-hidden px-6 py-20"
          style={{ background: "var(--brand)", color: "var(--on-brand)" }}
        >
          <Image
            src="/brand/hero-texture.jpg"
            alt=""
            fill
            className="pointer-events-none object-cover opacity-40"
            priority
          />
          <div className="relative mx-auto max-w-3xl text-center">
            <p className="eyebrow" style={{ color: "var(--on-brand)", opacity: 0.85 }}>
              Organisational Behaviour Consultancy
            </p>
            <h1 className="serif mt-3" style={{ fontSize: "clamp(1.9rem, 4vw, 2.9rem)" }}>
              {name}
            </h1>
            <p className="serif mt-4" style={{ fontSize: "1.125rem", opacity: 0.92 }}>
              We help business and organisations cultivate work environments that create value
              and unlock human potential. In short, we help align talent with strategy.
            </p>
            <div className="mt-8 flex justify-center gap-3">
              <Link href="/catalogue" className="btn btn--lg" style={{ background: "var(--on-brand)", color: "var(--brand)" }}>
                Browse programmes
              </Link>
              <Link href="/guest-access" className="btn btn--lg btn--ghost" style={{ borderColor: "var(--on-brand)", color: "var(--on-brand)" }}>
                Try a free lesson
              </Link>
            </div>
          </div>
        </div>

        {/* ---- About ---- */}
        <div id="about" className="mx-auto max-w-3xl px-6 py-16 text-center">
          <p className="eyebrow">About</p>
          <p className="serif mt-3" style={{ fontSize: "1.1875rem", color: "var(--ink-2)" }}>
            We train, consult and coach organisations in the essential skills needed to raise
            engagement. We offer value to customers through Engagement Analysis, Training,
            Consulting and Coaching within the spheres of Leadership, Strategy and Organisational
            Wellbeing.
          </p>
          <p className="mt-4" style={{ fontSize: "0.9375rem", color: "var(--muted)" }}>
            We hold a deep belief that to work is a gift, and that the workplace should be an
            environment that inspires people to share their talent, experience, ideas,
            uniqueness and enthusiasm.
          </p>
          <p className="tag tag--brand mt-6" style={{ display: "inline-block" }}>
            90+ organisations &middot; 19 countries
          </p>
        </div>

        {/* ---- Lead with Intent ---- */}
        <div id="programme" style={{ background: "var(--surface-2)", borderTop: "1px solid var(--rule)", borderBottom: "1px solid var(--rule)" }}>
          <div className="mx-auto flex max-w-4xl flex-col items-center gap-8 px-6 py-16 md:flex-row">
            <Image
              src="/brand/book-lead-with-intent.jpg"
              alt="Lead with Intent, by Hermann du Plessis"
              width={220}
              height={335}
              className="shrink-0 shadow-md"
            />
            <div>
              <p className="eyebrow">By founder Hermann du Plessis</p>
              <h2 className="serif mt-2" style={{ fontSize: "1.65rem" }}>
                Lead with Intent
              </h2>
              <p className="mt-3" style={{ fontSize: "0.9375rem", color: "var(--ink-2)" }}>
                A ground-breaking book that reveals nine leadership principles and practices that
                drive engagement and commitment in the workplace — the foundation the Institute's
                own programmes are built from.
              </p>
              <Link href="/lead-with-intent" className="btn btn--ghost mt-4">
                Read more
              </Link>
            </div>
          </div>
        </div>

        {/* ---- Client logos ---- */}
        <div id="partners" className="mx-auto max-w-5xl px-6 py-16 text-center">
          <p className="eyebrow">Organisations we've worked with</p>
          <div className="mt-8 grid grid-cols-2 items-center gap-8 sm:grid-cols-3 md:grid-cols-5">
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
                style={{ objectFit: "contain", width: "100%", height: "auto", opacity: 0.85 }}
              />
            ))}
          </div>
        </div>

        {/* ---- Team ---- */}
        <div style={{ background: "var(--surface-2)", borderTop: "1px solid var(--rule)", borderBottom: "1px solid var(--rule)" }}>
          <div className="mx-auto max-w-5xl px-6 py-16">
            <p className="eyebrow text-center">Facilitators</p>
            <div className="mt-8 grid grid-cols-2 gap-8 md:grid-cols-5">
              {[
                ["team-hermann-du-plessis", "Hermann du Plessis", "Founder"],
                ["team-sizwe-kuzwayo", "Sizwe Kuzwayo", "Sustainability & business consultant"],
                ["team-hano-du-plessis", "Hano du Plessis", "Training Manager"],
                ["team-agnes-hove", "Agnes Hove", "Strategist"],
                ["team-erika-botha", "Erika Botha", "Management consultant"],
              ].map(([file, person, role]) => (
                <div key={file} className="text-center">
                  <Image
                    src={`/brand/team/${file}.jpg`}
                    alt={person}
                    width={120}
                    height={160}
                    className="mx-auto"
                    style={{ objectFit: "cover", borderRadius: "4px" }}
                  />
                  <p className="mt-2" style={{ fontSize: "0.8125rem", fontWeight: 600 }}>
                    {person}
                  </p>
                  <p style={{ fontSize: "0.75rem", color: "var(--muted)" }}>{role}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </main>

      {/* ---- Footer / contact ---- */}
      <footer className="px-6 py-12" style={{ background: "var(--ink)", color: "var(--on-brand)" }}>
        <div className="mx-auto max-w-3xl text-center">
          <p className="eyebrow" style={{ color: "var(--on-brand)", opacity: 0.7 }}>
            Get in touch
          </p>
          <p className="serif mt-2" style={{ fontSize: "1.0625rem" }}>
            We would really like to hear from you.
          </p>
          <p className="mt-4" style={{ fontSize: "0.8125rem", opacity: 0.85 }}>
            30 Kasbah Ridge, Egale Canyon Golf Estate
          </p>
          <Link href="/contact" className="btn btn--ghost mt-4" style={{ borderColor: "var(--on-brand)", color: "var(--on-brand)" }}>
            Send us a message
          </Link>
          <p className="mt-6" style={{ fontSize: "0.75rem", opacity: 0.55 }}>
            Terms of usage &amp; privacy &middot; Copyright &copy; {name} 2026
          </p>
        </div>
      </footer>
    </>
  );
}
