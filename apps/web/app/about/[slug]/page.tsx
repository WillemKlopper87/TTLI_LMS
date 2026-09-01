import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";

import { FACILITATORS, getFacilitator } from "@/lib/facilitators";

/**
 * One facilitator's bio page. `bio`/`credentials`/`linkedin` are `null`
 * for everyone today (see `lib/facilitators.ts`'s own docstring on why —
 * no such copy exists yet, and this project doesn't fabricate biographical
 * content about real, named people). The page renders honestly around
 * that: photo, name, role, and a note that the fuller profile is on its
 * way, rather than an invented paragraph. Fields fill in here once real
 * copy exists, and this page picks it up automatically.
 */
export function generateStaticParams() {
  return FACILITATORS.map((f) => ({ slug: f.slug }));
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const person = getFacilitator(slug);
  if (!person) return { title: "Facilitator" };
  return {
    title: person.name,
    description: `${person.name}, ${person.role}.`,
    alternates: { canonical: `/about/${person.slug}` },
  };
}

export default async function FacilitatorPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const person = getFacilitator(slug);
  if (!person) notFound();

  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <Link href="/about" className="btn btn--ghost">
        &larr; Back to the team
      </Link>

      <div className="mt-8 flex flex-col items-center gap-8 text-center md:flex-row md:text-left">
        <Image
          src={`/brand/team/${person.photo}.jpg`}
          alt={person.name}
          width={220}
          height={330}
          className="mx-auto shrink-0 shadow-md md:mx-0"
          style={{ objectFit: "cover", borderRadius: "4px" }}
        />
        <div>
          <p className="eyebrow">{person.role}</p>
          <h1 className="serif mt-2" style={{ fontSize: "2rem" }}>
            {person.name}
          </h1>

          {person.bio ? (
            <p className="mt-4" style={{ fontSize: "1rem", color: "var(--ink-2)" }}>
              {person.bio}
            </p>
          ) : (
            <p className="mt-4" style={{ fontSize: "0.9375rem", color: "var(--muted)" }}>
              A fuller profile for {person.name.split(" ")[0]} is on its way.
            </p>
          )}

          {person.credentials ? (
            <p className="mt-3" style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
              {person.credentials}
            </p>
          ) : null}

          {person.linkedin ? (
            <p className="mt-3">
              <a
                href={person.linkedin}
                target="_blank"
                rel="noreferrer"
                className="btn btn--ghost"
              >
                LinkedIn
              </a>
            </p>
          ) : null}
        </div>
      </div>

      <div className="mt-16 flex justify-center gap-3">
        <Link href="/catalogue" className="btn btn--primary btn--lg">
          Browse programmes
        </Link>
        <Link href="/contact" className="btn btn--ghost btn--lg">
          Get in touch
        </Link>
      </div>
    </main>
  );
}
