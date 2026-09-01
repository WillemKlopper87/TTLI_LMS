import Link from "next/link";

import { formatDuration, formatMoney, joinMeta } from "@/lib/format";
import { getPublicCourses } from "@/lib/server-api";

import { CourseCard } from "../catalogue/course-card";

/**
 * The executive tier (design doc §5). This nav item used to be
 * `/catalogue?level=executive` — a filter, which made it indistinguishable
 * from "Courses" and sold nothing. It is now a page about what the
 * executive tier *is*, with the qualifying programmes underneath.
 *
 * The programme list is still derived from real data (`level ===
 * "executive"`), so nothing here can drift from the catalogue.
 */
export const metadata = {
  title: "Executive programmes",
  description: "Programmes built for senior leaders, with certification and cohort workshops.",
  alternates: { canonical: "/executive-programmes" },
};

export default async function ExecutiveProgrammesPage() {
  const courses = await getPublicCourses().catch(() => []);
  const executive = courses.filter((c) => c.level === "executive");
  const totalMinutes = executive.reduce((sum, c) => sum + (c.estimated_minutes ?? 0), 0);
  const withWorkshop = executive.filter((c) => c.includes_workshop).length;
  const cheapest = executive
    .map((c) => (c.price ? Number(c.price.unit_amount) : null))
    .filter((n): n is number => n !== null)
    .sort((a, b) => a - b)[0];

  return (
    <main>
      <div className="pad-lg">
        <div className="hero">
          <div>
            <p className="eyebrow">Executive tier</p>
            <h1>For the decisions that don&rsquo;t have a right answer.</h1>
            <p className="sub">
              Written for people who already know how to manage, and are now accountable for
              direction — committing before the information is complete, and holding a team steady
              while it changes.
            </p>
            <div className="hero-cta">
              <a className="btn btn--primary btn--lg" href="#programmes">
                See the programmes
              </a>
              <Link className="btn btn--ghost btn--lg" href="/for-organisations">
                Buying for a team
              </Link>
            </div>
            <div className="hero-trust">
              <div>
                <strong>{executive.length}</strong>
                <span>Executive programmes</span>
              </div>
              <div>
                <strong>{withWorkshop}</strong>
                <span>Include a live workshop</span>
              </div>
              {cheapest ? (
                <div>
                  <strong>{formatMoney(cheapest)}</strong>
                  <span>From, incl. VAT</span>
                </div>
              ) : null}
            </div>
          </div>

          <div className="hero-card">
            <p className="eyebrow">What makes it executive</p>
            <ul className="buybox-list">
              <li>
                <b>✓</b>
                <span>Situations with genuine trade-offs, not model answers</span>
              </li>
              <li>
                <b>✓</b>
                <span>A facilitated cohort of peers at the same level</span>
              </li>
              <li>
                <b>✓</b>
                <span>CPD points and a verifiable certificate</span>
              </li>
              <li>
                <b>✓</b>
                <span>Completion the server enforces, so the record stands up</span>
              </li>
            </ul>
          </div>
        </div>
      </div>

      <div className="band">
        <div className="pad">
          <div className="cols-3">
            <div className="cell">
              <h3>Built on the ambiguity</h3>
              <p>
                Every programme starts from a decision that could reasonably go either way. The
                material is about how you decide and communicate it, not which option was correct.
              </p>
            </div>
            <div className="cell">
              <h3>Peers, not an audience</h3>
              <p>
                The live session is capped so everyone speaks. You practise with people carrying
                the same weight, and the facilitator has led the programme themselves.
              </p>
            </div>
            <div className="cell">
              <h3>A record that survives scrutiny</h3>
              <p>
                Watch time, assessment scores and attendance are validated server-side, and the
                certificate carries a QR to a public verification page that shows valid, expired or
                revoked.
              </p>
            </div>
          </div>
        </div>
      </div>

      <div className="pad-lg" id="programmes">
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
          <div>
            <h2 className="serif" style={{ fontSize: "1.5rem" }}>
              The executive programmes
            </h2>
            <p style={{ fontSize: ".8125rem", color: "var(--muted)", marginTop: ".2rem" }}>
              {joinMeta([
                `${executive.length} ${executive.length === 1 ? "programme" : "programmes"}`,
                formatDuration(totalMinutes),
              ])}
            </p>
          </div>
          <Link className="btn btn--quiet" href="/catalogue">
            Browse everything &rarr;
          </Link>
        </div>

        {executive.length === 0 ? (
          <div className="callout">
            <b>No executive programmes are published yet</b>
            <Link href="/catalogue">Browse the full catalogue</Link> in the meantime.
          </div>
        ) : (
          <div className="course-grid">
            {executive.map((course) => (
              <CourseCard key={course.id} course={course} />
            ))}
          </div>
        )}

        <div className="callout" style={{ marginTop: "1.5rem" }}>
          <b>Sponsoring a cohort?</b>
          Seat bundles from five learners include a manager dashboard, invoice or EFT payment and
          purchase-order support. <Link href="/for-organisations">How corporate accounts work</Link>
          .
        </div>
      </div>
    </main>
  );
}
