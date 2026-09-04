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

import { courseArt } from "@/lib/course-art";
import { countLabel, formatDuration, formatLevel, formatMoney, joinMeta, vatSuffix } from "@/lib/format";
import type { PublicCourse } from "@/lib/server-api";

export function CourseCard({ course }: { course: PublicCourse }) {
  const meta = joinMeta([
    countLabel(course.module_count, "module"),
    formatDuration(course.estimated_minutes),
    formatLevel(course.level),
  ]);
  const price = course.price;
  // Generated art (lib/course-art.ts): gradient + pattern + monogram from
  // the course's own colour/id/topic, so every card looks designed with
  // nothing uploaded — the same treatment the course page's hero uses.
  const art = courseArt(course);

  return (
    <Link className="ccard" href={`/courses/${course.id}`}>
      <span className="ccard-art" style={art.style}>
        <span className="ccard-mono" aria-hidden="true">
          {art.monogram}
        </span>
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
