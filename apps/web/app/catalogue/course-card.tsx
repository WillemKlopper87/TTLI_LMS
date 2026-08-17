/**
 * The prototype's `.ccard` — one programme, as it appears in the
 * catalogue grid and in "Popular programmes" on the landing page.
 * Shared by both so the two grids can never drift apart.
 *
 * Everything below the title is optional: the presentation columns
 * (topic / level / estimated_minutes / hero_colour / price) are all
 * nullable on `GET /public/courses`, and a course with none of them set
 * renders a plain card rather than an empty tag or the string "null".
 */
import Link from "next/link";

import { countLabel, formatDuration, formatLevel, formatMoney, joinMeta, vatSuffix } from "@/lib/format";
import type { PublicCourse } from "@/lib/server-api";

// Stable per-course fallbacks for `hero_colour`, picked from the
// prototype's own art blocks. Chosen by a hash of the course id so a
// given course keeps the same colour across renders and across pages.
const FALLBACK_COLOURS = ["#8E151C", "#3E4A3C", "#4A3A52", "#2F4858", "#6B4A2F"];

/** Only `#rgb` / `#rrggbb` reaches a style attribute: `hero_colour` is
 * operator-entered text, and anything else is dropped for the fallback. */
function artColour(course: Pick<PublicCourse, "id" | "hero_colour">): string {
  const raw = course.hero_colour?.trim() ?? "";
  if (/^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i.test(raw)) return raw;
  let hash = 0;
  for (let i = 0; i < course.id.length; i += 1) hash = (hash * 31 + course.id.charCodeAt(i)) >>> 0;
  return FALLBACK_COLOURS[hash % FALLBACK_COLOURS.length];
}

export function CourseCard({ course }: { course: PublicCourse }) {
  const meta = joinMeta([
    countLabel(course.module_count, "module"),
    formatDuration(course.estimated_minutes),
    formatLevel(course.level),
  ]);
  const price = course.price;

  return (
    <Link className="ccard" href={`/courses/${course.id}`}>
      <span className="ccard-art" style={{ background: artColour(course) }}>
        {course.topic ? <b>{course.topic}</b> : null}
      </span>
      <span className="ccard-body">
        {course.has_certificate || course.includes_workshop || course.cpd_points ? (
          <span className="ccard-meta">
            {course.has_certificate ? <span className="tag tag--brand">Certificate</span> : null}
            {course.includes_workshop ? <span className="tag tag--mute">Live workshop</span> : null}
            {course.cpd_points ? <span className="tag tag--mute">CPD</span> : null}
          </span>
        ) : null}
        <h4>{course.title}</h4>
        {meta ? <span className="ccard-meta">{meta}</span> : null}
        {price ? (
          <span className="ccard-price">
            {formatMoney(price.unit_amount, price.currency)} <small>{vatSuffix(price.includes_vat)}</small>
          </span>
        ) : null}
      </span>
    </Link>
  );
}
