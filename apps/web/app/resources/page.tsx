import Link from "next/link";

import { formatClock } from "@/lib/format";
import {
  getPublicArticles,
  getPublicCourses,
  getPublicEpisodes,
  getPublicRecommendations,
} from "@/lib/server-api";

import { NewsletterSignup } from "./newsletter-signup";

// Defense in depth for a raw <a href> — the backend already refuses
// anything but http(s):// at write time (both podcasts' external_url and
// recommendations' url), but the value still reaches this component as
// untyped API JSON. Same check `podcasts/[slug]/page.tsx` already has.
function isSafeHttpUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

/**
 * The resources hub (design doc §5 item 21, stages 2-3 per
 * `docs/research/resources-hub-design.md`). "Resources" used to point
 * straight at /podcasts — a bare list of episodes, which is a content
 * type rather than a section.
 *
 * This is the section: TTLI's own episodes, the third-party work the
 * faculty actually recommends (curated podcast episodes *and* the
 * structured `recommendations` list, merged into one visual list per the
 * design doc §3.2 — the reader doesn't need "recommended episode" and
 * "recommended link" as two separate headings), articles, the book, and
 * the newsletter. Articles and recommendations are folded straight into
 * this page rather than given their own listing route yet — the design
 * doc's own recommendation, matching the pattern the podcast section
 * itself used before volume justified `/podcasts` as a separate page.
 */
export const metadata = {
  title: "Resources",
  description: "Podcasts, articles and recommendations from TTLI's faculty.",
  alternates: { canonical: "/resources" },
};

export default async function ResourcesPage() {
  const [episodes, courses, articles, recommendations] = await Promise.all([
    getPublicEpisodes().catch(() => []),
    getPublicCourses().catch(() => []),
    getPublicArticles().catch(() => []),
    getPublicRecommendations().catch(() => []),
  ]);

  const authored = episodes.filter((e) => e.kind === "authored");
  const curated = episodes.filter((e) => e.kind === "curated");
  const latest = authored[0] ?? episodes[0] ?? null;
  const rest = episodes.filter((e) => e.slug !== latest?.slug);

  const recommended = [
    ...curated.map((e) => ({
      key: `episode:${e.slug}`,
      title: e.title,
      note: e.curator_name ? `Recommended by ${e.curator_name}` : "",
      href: `/podcasts/${e.slug}`,
      external: false,
    })),
    ...recommendations.map((r) => ({
      key: `link:${r.id}`,
      title: r.title,
      note: [r.source_name, r.curator_name ? `via ${r.curator_name}` : null]
        .filter(Boolean)
        .join(" · "),
      href: r.url,
      external: true,
    })),
  ];

  return (
    <main>
      <div className="pad-lg">
        <div className="hero">
          <div>
            <p className="eyebrow">Resources</p>
            <h1>Everything we publish, free.</h1>
            <p className="sub">
              The podcast, the reading we recommend, and the book the programmes are built from.
              No account needed for any of it — the paid part is the programme, not the thinking.
            </p>
            <div className="hero-cta">
              {latest ? (
                <Link className="btn btn--primary btn--lg" href={`/podcasts/${latest.slug}`}>
                  Listen to the latest
                </Link>
              ) : null}
              <Link className="btn btn--ghost btn--lg" href="/lead-with-intent">
                Read about the book
              </Link>
            </div>
          </div>

          {latest ? (
            <div className="hero-card">
              <p className="eyebrow">Latest episode</p>
              <h2 className="serif" style={{ fontSize: "1.1875rem" }}>
                {latest.title}
              </h2>
              {latest.description ? (
                <p style={{ fontSize: ".8125rem", color: "var(--muted)" }}>
                  {latest.description}
                </p>
              ) : null}
              <div className="wave" aria-hidden="true">
                {[30, 55, 80, 45, 95, 60, 35, 70, 100, 50, 75, 40, 85, 30, 65, 45, 90, 55, 25, 60].map(
                  (h, i) => (
                    <i key={i} style={{ height: `${h}%` }} />
                  ),
                )}
              </div>
              {latest.duration_seconds ? (
                <div className="times">
                  <span>00:00</span>
                  <span>{formatClock(latest.duration_seconds)}</span>
                </div>
              ) : null}
              <Link className="btn btn--ghost btn--block" href={`/podcasts/${latest.slug}`}>
                Listen · free, no account
              </Link>
            </div>
          ) : null}
        </div>
      </div>

      <div className="pad-lg">
        <div className="article">
          <div style={{ display: "grid", gap: "2rem" }}>
            <section>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "baseline",
                  gap: "1rem",
                  marginBottom: ".7rem",
                }}
              >
                <h2 className="serif" style={{ fontSize: "1.25rem" }}>
                  The podcast
                </h2>
                <Link className="btn btn--quiet" href="/podcasts">
                  All episodes &rarr;
                </Link>
              </div>
              {rest.length === 0 ? (
                // One episode (or none) means the hero card above is
                // already showing everything there is; a heading over an
                // empty grid reads as a broken section.
                <div className="callout">
                  <b>{latest ? "That's the whole series so far" : "Nothing published yet"}</b>
                  {latest
                    ? "New episodes land every few weeks — the newsletter is the quickest way to hear about them."
                    : "Episodes appear here as they are released."}
                </div>
              ) : (
                <div className="rowlist">
                  {rest.slice(0, 6).map((e) => (
                    <div className="rowitem" key={e.slug}>
                      <span className={e.kind === "curated" ? "tag tag--mute" : "tag tag--brand"}>
                        {e.kind === "curated" ? "Recommended" : "TTLI"}
                      </span>
                      <span className="t">{e.title}</span>
                      <span className="m">
                        {e.duration_seconds ? formatClock(e.duration_seconds) : ""}
                      </span>
                      <Link className="btn btn--ghost" href={`/podcasts/${e.slug}`}>
                        Listen
                      </Link>
                    </div>
                  ))}
                </div>
              )}
            </section>

            {recommended.length > 0 ? (
              <section>
                <h2 className="serif" style={{ fontSize: "1.25rem", marginBottom: ".35rem" }}>
                  What our facilitators recommend
                </h2>
                <p
                  style={{ fontSize: ".8125rem", color: "var(--muted)", marginBottom: ".7rem" }}
                >
                  Work by other people that we keep sending delegates to.
                </p>
                <div className="rowlist">
                  {recommended.slice(0, 8).map((r) =>
                    r.external ? (
                      <div className="rowitem" key={r.key}>
                        <span className="t">{r.title}</span>
                        <span className="m">{r.note}</span>
                        {isSafeHttpUrl(r.href) ? (
                          <a
                            className="btn btn--ghost"
                            href={r.href}
                            target="_blank"
                            rel="noreferrer"
                          >
                            Open
                          </a>
                        ) : null}
                      </div>
                    ) : (
                      <div className="rowitem" key={r.key}>
                        <span className="t">{r.title}</span>
                        <span className="m">{r.note}</span>
                        <Link className="btn btn--ghost" href={r.href}>
                          Open
                        </Link>
                      </div>
                    ),
                  )}
                </div>
              </section>
            ) : null}

            {articles.length > 0 ? (
              <section>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "baseline",
                    gap: "1rem",
                    marginBottom: ".7rem",
                  }}
                >
                  <h2 className="serif" style={{ fontSize: "1.25rem" }}>
                    Writing
                  </h2>
                </div>
                <div className="rowlist">
                  {articles.slice(0, 6).map((a) => (
                    <div className="rowitem" key={a.slug}>
                      <span className="t">{a.title}</span>
                      <span className="m">
                        {[a.author_name, a.reading_minutes ? `${a.reading_minutes} min` : null]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>
                      <Link className="btn btn--ghost" href={`/resources/articles/${a.slug}`}>
                        Read
                      </Link>
                    </div>
                  ))}
                </div>
              </section>
            ) : null}

            <section>
              <h2 className="serif" style={{ fontSize: "1.25rem", marginBottom: ".7rem" }}>
                Where to go next
              </h2>
              <div className="cols-3">
                <div className="cell">
                  <h3>Try a real lesson</h3>
                  <p>
                    A full sample lesson and a marked assessment, with no card and no automatic
                    renewal.
                  </p>
                  <p style={{ marginTop: ".5rem" }}>
                    <Link href="/guest-access">Get guest access &rarr;</Link>
                  </p>
                </div>
                <div className="cell">
                  <h3>Sit in on a cohort</h3>
                  <p>
                    Live facilitated workshops run per cohort, capped so everyone speaks.
                  </p>
                  <p style={{ marginTop: ".5rem" }}>
                    <Link href="/workshops">See upcoming sessions &rarr;</Link>
                  </p>
                </div>
                <div className="cell">
                  <h3>Bring it to your team</h3>
                  <p>
                    Seat bundles, a manager dashboard and invoicing that suits your finance team.
                  </p>
                  <p style={{ marginTop: ".5rem" }}>
                    <Link href="/for-organisations">For organisations &rarr;</Link>
                  </p>
                </div>
              </div>
            </section>
          </div>

          <aside style={{ display: "grid", gap: "1rem", alignContent: "start" }}>
            <NewsletterSignup />

            <div className="aside-card">
              <p className="eyebrow">The book</p>
              <h3 className="serif" style={{ fontSize: "1.0625rem" }}>
                Lead with Intent
              </h3>
              <p style={{ fontSize: ".8125rem", color: "var(--muted)" }}>
                Nine leadership principles that drive engagement and commitment — the foundation
                the Institute&rsquo;s own programmes are built from.
              </p>
              <Link
                className="btn btn--ghost btn--block"
                href="/lead-with-intent"
                aria-label="Read more about Lead with Intent"
              >
                Read more
              </Link>
            </div>

            {courses.length > 0 ? (
              <div className="aside-card">
                <p className="eyebrow">Programmes</p>
                <h3 className="serif" style={{ fontSize: "1.0625rem" }}>
                  {courses.length} available
                </h3>
                <p style={{ fontSize: ".8125rem", color: "var(--muted)" }}>
                  Every programme carries a verifiable certificate and enforced completion.
                </p>
                <Link className="btn btn--ghost btn--block" href="/catalogue">
                  Browse the catalogue
                </Link>
              </div>
            ) : null}
          </aside>
        </div>
      </div>
    </main>
  );
}
