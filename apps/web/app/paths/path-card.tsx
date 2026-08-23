/**
 * The `.ccard` idiom for a learning path — mirrors `catalogue/course-
 * card.tsx` closely (same class names, same reused-not-invented styling),
 * but shaped for what a path actually is: an ordered course count, not a
 * module/lesson breakdown.
 */
import Link from "next/link";

import { countLabel, formatMoney, vatSuffix } from "@/lib/format";
import type { PublicPathCard as PublicPathCardData } from "@/lib/server-api";

const FALLBACK_COLOURS = ["#2F4858", "#4A3A52", "#3E4A3C", "#8E151C", "#6B4A2F"];

function artColour(id: string): string {
  let hash = 0;
  for (let i = 0; i < id.length; i += 1) hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  return FALLBACK_COLOURS[hash % FALLBACK_COLOURS.length];
}

export function PathCard({ path }: { path: PublicPathCardData }) {
  const price = path.price;
  const meta = countLabel(path.course_count, "course");

  return (
    <Link className="ccard" href={`/paths/${path.id}`}>
      <span className="ccard-art" style={{ background: artColour(path.id) }}>
        <b>Learning path</b>
      </span>
      <span className="ccard-body">
        {path.has_certificate ? (
          <span className="ccard-meta">
            <span className="tag tag--brand">Certificate</span>
          </span>
        ) : null}
        <h4>{path.title}</h4>
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
