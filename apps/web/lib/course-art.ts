/**
 * Generated course art — the catalogue card's `.ccard-art` band and the
 * course page's hero, from the same seed.
 *
 * There is no course image field, deliberately (see the research note in
 * docs/REMEDIATION_LEDGER.md's follow-ups): the platforms that make
 * creators upload cover photos (Udemy, Teachable, Skillshare) end up with
 * a visibly inconsistent catalogue, and most tenant admins authoring a
 * course here have no photography or designer to hand. So the art is
 * *generated*, the way Trello/Notion covers, GitHub identicons and
 * initials-avatars are: deterministic from the course, never blank, and
 * consistent across every course on the site. LinkedIn Learning's
 * restrained, templated B2B look is the register — not Skillshare's.
 *
 * Inputs, in priority order:
 *  - `hero_colour` (an admin override that already exists on the model),
 *    when it's a valid hex colour;
 *  - otherwise one of five brand-adjacent palette colours, picked by a
 *    stable hash of the course id so a course keeps its colour across
 *    renders, pages and deploys.
 * From that base the same hash also picks a gradient angle and one of
 * three low-opacity patterns, and the topic (or title) supplies a large
 * translucent monogram. Pure CSS — no image, no icon library, no upload.
 */

const FALLBACK_COLOURS = ["#8E151C", "#3E4A3C", "#4A3A52", "#2F4858", "#6B4A2F"];

const PATTERNS = ["dots", "lines", "rings"] as const;
type Pattern = (typeof PATTERNS)[number];

const PATTERN_LAYERS: Record<Pattern, { image: string; size: string }> = {
  dots: {
    image: "radial-gradient(rgba(255, 255, 255, 0.16) 1px, transparent 1.6px)",
    size: "14px 14px",
  },
  lines: {
    image:
      "repeating-linear-gradient(115deg, rgba(255, 255, 255, 0.1) 0 1px, transparent 1px 13px)",
    size: "auto",
  },
  rings: {
    image:
      "repeating-radial-gradient(circle at 88% 125%, rgba(255, 255, 255, 0.1) 0 1px, transparent 1px 18px)",
    size: "auto",
  },
};

function hashId(id: string): number {
  let hash = 0;
  for (let i = 0; i < id.length; i += 1) hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  return hash;
}

/** Only `#rgb` / `#rrggbb` reaches a style attribute: `hero_colour` is
 * operator-entered text, and anything else is dropped for the fallback. */
export function artColour(course: { id: string; hero_colour: string | null }): string {
  const raw = course.hero_colour?.trim() ?? "";
  if (/^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i.test(raw)) return raw;
  return FALLBACK_COLOURS[hashId(course.id) % FALLBACK_COLOURS.length];
}

export interface CourseArt {
  /** Inline style for the art container: pattern over a two-tone gradient. */
  style: { background: string; backgroundSize: string };
  /** One uppercase letter for the translucent background monogram. */
  monogram: string;
}

export function courseArt(course: {
  id: string;
  hero_colour: string | null;
  topic: string | null;
  title: string;
}): CourseArt {
  const base = artColour(course);
  const hash = hashId(course.id);
  const pattern = PATTERN_LAYERS[PATTERNS[(hash >>> 3) % PATTERNS.length]];
  const angle = 125 + (hash % 5) * 12;
  const deep = `color-mix(in srgb, ${base} 62%, #150c0e)`;
  const source = (course.topic ?? course.title).trim();
  return {
    style: {
      background: `${pattern.image}, linear-gradient(${angle}deg, ${base} 0%, ${deep} 100%)`,
      backgroundSize: `${pattern.size}, auto`,
    },
    monogram: (source.charAt(0) || "·").toUpperCase(),
  };
}
