/**
 * A published course's public page — prototype screen 5, backed by the
 * anonymous `GET /public/courses/{id}/curriculum`.
 *
 * Server-rendered so the curriculum is in the HTML for search engines
 * and for anyone deciding whether to buy; only the "show remaining
 * modules" fold is a client component.
 *
 * Every presentation field is optional in the data (a course seeded
 * before the presentation pass has no summary, level, topic, outcomes,
 * hero colour or price), so each block is omitted rather than rendered
 * empty, and a course with no price offers "See enrolment options"
 * instead of a buy button.
 */
import Link from "next/link";

import { Curriculum } from "@/app/courses/[courseId]/curriculum";
import {
  countLabel,
  formatDuration,
  formatFormat,
  formatLevel,
  formatMoney,
  joinMeta,
  vatLine,
} from "@/lib/format";
import { getPublicCurriculum } from "@/lib/server-api";

export const dynamic = "force-dynamic";

interface CoursePageProps {
  params: Promise<{ courseId: string }>;
}

export default async function CourseDetailPage({ params }: CoursePageProps) {
  const { courseId } = await params;
  const course = await getPublicCurriculum(courseId);

  if (!course) {
    return (
      <main className="pad-lg">
        <p style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
          This course could not be found.{" "}
          <Link href="/catalogue" style={{ color: "var(--brand-ink)" }}>
            Back to the catalogue
          </Link>
          .
        </p>
      </main>
    );
  }

  const eyebrow = joinMeta([course.topic, formatLevel(course.level), formatFormat(course.format)]);
  const sizeTag = joinMeta([
    countLabel(course.modules.length, "module"),
    formatDuration(course.estimated_minutes),
  ]);
  const outcomes = course.outcomes ?? [];
  const price = course.price;

  return (
    <main className="pad-lg">
      <div className="detail">
        <div style={{ display: "grid", gap: "1.75rem" }}>
          <div>
            {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
            <h1 style={{ margin: "0.5rem 0 0.8rem" }}>{course.title}</h1>
            {course.summary ? (
              <p
                style={{
                  fontFamily: "var(--serif)",
                  fontSize: "1.0625rem",
                  color: "var(--ink-2)",
                  maxWidth: "56ch",
                }}
              >
                {course.summary}
              </p>
            ) : null}
            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem", marginTop: "1rem" }}>
              {course.has_certificate ? (
                <span className="tag tag--brand">Certificate on completion</span>
              ) : null}
              {course.includes_workshop ? (
                <span className="tag tag--mute">One live workshop seat</span>
              ) : null}
              {course.cpd_points ? (
                <span className="tag tag--mute">{course.cpd_points} CPD points</span>
              ) : null}
              {sizeTag ? <span className="tag tag--mute">{sizeTag}</span> : null}
            </div>
          </div>

          {outcomes.length > 0 ? (
            <div>
              <h3 className="serif" style={{ fontSize: "1.1875rem", marginBottom: "0.3rem" }}>
                What you will be able to do
              </h3>
              <ul className="outcomes">
                {outcomes.map((outcome) => (
                  <li key={outcome}>
                    <b aria-hidden="true">✓</b>
                    <span>{outcome}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {course.modules.length > 0 || course.includes_workshop ? (
            <div>
              <h3 className="serif" style={{ fontSize: "1.1875rem", marginBottom: "0.7rem" }}>
                Curriculum
              </h3>
              <Curriculum modules={course.modules} includesWorkshop={course.includes_workshop} />
            </div>
          ) : null}
        </div>

        <div style={{ display: "grid", gap: "1rem" }}>
          <div className="buybox">
            <div className="buybox-price">
              {price ? (
                <>
                  <div className="amt">{formatMoney(price.unit_amount, price.currency)}</div>
                  <div className="vat">{vatLine(price.includes_vat, price.currency)}</div>
                </>
              ) : (
                <div className="vat">This programme is not on sale online yet.</div>
              )}
            </div>
            <div className="buybox-body">
              {price ? (
                <Link
                  className="btn btn--primary btn--lg btn--block"
                  href={`/checkout?price=${price.price_id}`}
                >
                  Enrol now
                </Link>
              ) : (
                <Link className="btn btn--primary btn--lg btn--block" href="/catalogue">
                  See enrolment options
                </Link>
              )}
              <Link className="btn btn--ghost btn--block" href="/organisations">
                Request an invoice for a team
              </Link>
              <ul className="buybox-list" style={{ marginTop: "0.3rem" }}>
                <li>
                  <b aria-hidden="true">✓</b>
                  <span>Lifetime access to this cohort&rsquo;s material</span>
                </li>
                {course.includes_workshop ? (
                  <li>
                    <b aria-hidden="true">✓</b>
                    <span>One live workshop seat</span>
                  </li>
                ) : null}
                {course.has_certificate ? (
                  <li>
                    <b aria-hidden="true">✓</b>
                    <span>Verifiable certificate and shareable badge</span>
                  </li>
                ) : null}
                {course.cpd_points ? (
                  <li>
                    <b aria-hidden="true">✓</b>
                    <span>{course.cpd_points} CPD points on completion</span>
                  </li>
                ) : null}
                <li>
                  <b aria-hidden="true">✓</b>
                  <span>7-day refund if under 20% complete</span>
                </li>
              </ul>
            </div>
          </div>

          {course.has_certificate ? (
            <div className="cert-preview">
              <p className="eyebrow">You will earn</p>
              <div className="cert-mini">
                <div className="cl">Certificate of completion</div>
                <div className="cn">{course.title}</div>
                <div className="cl">Verifiable &middot; QR &middot; Revocable</div>
              </div>
              <p style={{ fontSize: "0.6875rem", color: "var(--muted)" }}>
                Issued only once every completion rule is met.
              </p>
            </div>
          ) : null}
        </div>
      </div>
    </main>
  );
}
