import Link from "next/link";

import { formatClock } from "@/lib/format";
import { getPublicCourses, getPublicEpisodes } from "@/lib/server-api";

import { NewsletterSignup } from "./newsletter-signup";

/**
 * The resources hub (design doc §5 item 21). "Resources" used to point
 * straight at /podcasts — a bare list of episodes, which is a content
 * type rather than a section.
 *
 * This is the section: TTLI's own episodes, the third-party work the
 * faculty actually recommends (the podcast model already distinguishes
 * `authored` from `curated`), the book, and the newsletter. Articles are
 * specified in the design doc but not built — no table exists for them —
 * and this page deliberately does not fake a placeholder for something
 * that would render empty.
 */
export const metadata = {
  title: "Resources",
};

export default async function ResourcesPage() {
  const [episodes, courses] = await Promise.all([
    getPublicEpisodes().catch(() => []),
    getPublicCourses().catch(() => []),
  ]);

  const authored = episodes.filter((e) => e.kind === "authored");
  const curated = episodes.filter((e) => e.kind === "curated");
  const latest = authored[0] ?? episodes[0] ?? null;
  const rest = episodes.filter((e) => e.slug !== latest?.slug);

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
              {rest.length === 0 && !latest ? (
                <div className="callout">
                  <b>Nothing published yet</b>
                  Episodes appear here as they are released.
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

            {curated.length > 0 ? (
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
                  {curated.slice(0, 6).map((e) => (
                    <div className="rowitem" key={e.slug}>
                      <span className="t">{e.title}</span>
                      <span className="m">
                        {e.curator_name ? `Recommended by ${e.curator_name}` : ""}
                      </span>
                      <Link className="btn btn--ghost" href={`/podcasts/${e.slug}`}>
                        Open
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
              <Link className="btn btn--ghost btn--block" href="/lead-with-intent">
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
