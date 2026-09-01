/**
 * A published learning path's public page — backed by the anonymous
 * `GET /public/learning-paths/{id}`. Mirrors `courses/[courseId]/
 * page.tsx`'s buybox structure closely (same `.detail`/`.buybox`/
 * `.buybox-list` idiom, same "no price yet" degrade), swapping the
 * curriculum block for an ordered course list — a path has no
 * modules/lessons of its own to show, only its member courses in
 * completion order.
 */
import Link from "next/link";

import { countLabel, formatLevel, formatMoney, joinMeta, vatLine } from "@/lib/format";
import { getPublicPathDetail } from "@/lib/server-api";

export const dynamic = "force-dynamic";

interface PathPageProps {
  params: Promise<{ pathId: string }>;
}

export async function generateMetadata({ params }: PathPageProps) {
  const { pathId } = await params;
  const path = await getPublicPathDetail(pathId);
  if (!path) return { title: "Learning path" };
  return {
    title: path.title,
    description: path.description ?? undefined,
    alternates: { canonical: `/paths/${pathId}` },
  };
}

export default async function PathDetailPage({ params }: PathPageProps) {
  const { pathId } = await params;
  const path = await getPublicPathDetail(pathId);

  if (!path) {
    return (
      <main className="pad-lg">
        <p style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
          This learning path could not be found.{" "}
          <Link href="/paths" style={{ color: "var(--brand-ink)" }}>
            Back to learning paths
          </Link>
          .
        </p>
      </main>
    );
  }

  const sizeTag = countLabel(path.courses.length, "course");
  const price = path.price;

  return (
    <main className="pad-lg">
      <div className="detail">
        <div style={{ display: "grid", gap: "1.75rem" }}>
          <div>
            <p className="eyebrow">Learning path</p>
            <h1 style={{ margin: "0.5rem 0 0.8rem" }}>{path.title}</h1>
            {path.description ? (
              <p
                style={{
                  fontFamily: "var(--serif)",
                  fontSize: "1.0625rem",
                  color: "var(--ink-2)",
                  maxWidth: "56ch",
                }}
              >
                {path.description}
              </p>
            ) : null}
            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem", marginTop: "1rem" }}>
              {path.has_certificate ? (
                <span className="tag tag--brand">Certificate on completion</span>
              ) : null}
              {sizeTag ? <span className="tag tag--mute">{sizeTag}</span> : null}
            </div>
          </div>

          {path.courses.length > 0 ? (
            <div>
              <h3 className="serif" style={{ fontSize: "1.1875rem", marginBottom: "0.7rem" }}>
                What&rsquo;s included, in order
              </h3>
              <ol style={{ display: "grid", gap: "0.6rem", listStyle: "none", padding: 0 }}>
                {path.courses.map((course, index) => (
                  <li
                    key={course.course_id}
                    style={{
                      border: "1px solid var(--rule)",
                      padding: "0.85rem 1rem",
                      display: "flex",
                      gap: "0.75rem",
                      alignItems: "baseline",
                    }}
                  >
                    <span style={{ fontFamily: "var(--mono)", color: "var(--faint)" }}>
                      {index + 1}
                    </span>
                    <div>
                      <b>{course.title}</b>
                      <div style={{ fontSize: "0.8125rem", color: "var(--muted)", marginTop: "0.2rem" }}>
                        {joinMeta([course.topic, formatLevel(course.level)]) || course.summary}
                      </div>
                    </div>
                  </li>
                ))}
              </ol>
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
                <div className="vat">This path is not on sale online yet.</div>
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
                <Link className="btn btn--primary btn--lg btn--block" href="/paths">
                  See other paths
                </Link>
              )}
              <Link className="btn btn--ghost btn--block" href="/organisations">
                Request an invoice for a team
              </Link>
              <ul className="buybox-list" style={{ marginTop: "0.3rem" }}>
                <li>
                  <b aria-hidden="true">✓</b>
                  <span>Every course in this path, completed in order</span>
                </li>
                {path.has_certificate ? (
                  <li>
                    <b aria-hidden="true">✓</b>
                    <span>Verifiable certificate on completing the whole path</span>
                  </li>
                ) : null}
                <li>
                  <b aria-hidden="true">✓</b>
                  <span>7-day refund if under 20% complete</span>
                </li>
              </ul>
            </div>
          </div>

          {path.has_certificate ? (
            <div className="cert-preview">
              <p className="eyebrow">You will earn</p>
              <div className="cert-mini">
                <div className="cl">Certificate of completion</div>
                <div className="cn">{path.title}</div>
                <div className="cl">Verifiable &middot; QR &middot; Revocable</div>
              </div>
              <p style={{ fontSize: "0.6875rem", color: "var(--muted)" }}>
                Issued only once every course in the path is complete.
              </p>
            </div>
          ) : null}
        </div>
      </div>
    </main>
  );
}
