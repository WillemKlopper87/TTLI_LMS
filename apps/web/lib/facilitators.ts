/**
 * TTLI's facilitators — shared between the homepage teaser, `/about`, and
 * `/about/[slug]`. Real names/roles/photos only, extracted at the same
 * time and from the same source as the rest of `apps/web/app/page.tsx`'s
 * marketing content (see that file's own docstring on why this is static
 * TTLI-specific content, not tenant/theme-driven).
 *
 * `bio`/`credentials`/`linkedin` are deliberately `null` for everyone —
 * no such copy was ever extracted from the real site, and this project's
 * own convention (docs/brand/ttli-brand-identity.md's "Explicitly not
 * present on the site, so not fabricated here") is to never invent
 * biographical content about real, named people. `/about/[slug]` renders
 * gracefully without these fields rather than showing a fabricated
 * paragraph; fill them in here once real copy exists.
 */

export interface Facilitator {
  slug: string;
  photo: string;
  name: string;
  role: string;
  bio: string | null;
  credentials: string | null;
  linkedin: string | null;
}

export const FACILITATORS: Facilitator[] = [
  {
    slug: "hermann-du-plessis",
    photo: "team-hermann-du-plessis",
    name: "Hermann du Plessis",
    role: "Founder",
    bio: null,
    credentials: null,
    linkedin: null,
  },
  {
    slug: "sizwe-kuzwayo",
    photo: "team-sizwe-kuzwayo",
    name: "Sizwe Kuzwayo",
    role: "Sustainability & business consultant",
    bio: null,
    credentials: null,
    linkedin: null,
  },
  {
    slug: "hano-du-plessis",
    photo: "team-hano-du-plessis",
    name: "Hano du Plessis",
    role: "Training Manager",
    bio: null,
    credentials: null,
    linkedin: null,
  },
  {
    slug: "agnes-hove",
    photo: "team-agnes-hove",
    name: "Agnes Hove",
    role: "Strategist",
    bio: null,
    credentials: null,
    linkedin: null,
  },
  {
    slug: "erika-botha",
    photo: "team-erika-botha",
    name: "Erika Botha",
    role: "Management consultant",
    bio: null,
    credentials: null,
    linkedin: null,
  },
];

export function getFacilitator(slug: string): Facilitator | null {
  return FACILITATORS.find((f) => f.slug === slug) ?? null;
}
