/**
 * The public catalogue (REQ-STORE-01) — prototype screen 4.
 *
 * Server-rendered: `GET /public/courses` is anonymous, so the whole
 * faceted grid exists in the first HTML response rather than after a
 * client round trip. Only the interactive parts (facet toggles, sort,
 * the subscription CTA that needs the session) are client components.
 *
 * `?topic=` and `?level=` preselect a facet — the header's "Executive
 * Programmes" item is /catalogue?level=executive. The browser is keyed
 * on those params so arriving from that link re-seeds the selection.
 */
import { CatalogueBrowser } from "@/app/catalogue/catalogue-browser";
import { Subscriptions } from "@/app/catalogue/subscriptions";
import { getPublicCourses, getPublicProducts } from "@/lib/server-api";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "Course catalogue",
  description: "Browse courses, executive programmes and subscription plans.",
  alternates: { canonical: "/catalogue" },
};

interface CataloguePageProps {
  searchParams: Promise<{ topic?: string | string[]; level?: string | string[] }>;
}

function first(value: string | string[] | undefined): string | null {
  if (Array.isArray(value)) return value[0] ?? null;
  return value ?? null;
}

export default async function CataloguePage({ searchParams }: CataloguePageProps) {
  const [{ topic, level }, courses, products] = await Promise.all([
    searchParams,
    getPublicCourses(),
    getPublicProducts(),
  ]);

  const initialTopic = first(topic);
  const initialLevel = first(level)?.toLowerCase() ?? null;
  const subscriptions = products.filter((product) => product.subscription_plan_id !== null);

  return (
    <main>
      <div className="pad-lg">
        {courses.length === 0 ? (
          <>
            <p className="eyebrow">Programmes</p>
            <h1 className="serif" style={{ fontSize: "1.5rem", marginTop: "0.35rem" }}>
              The catalogue is not open yet
            </h1>
            <p style={{ fontSize: "0.875rem", color: "var(--muted)", marginTop: "0.5rem" }}>
              No programmes are published for this site yet. Try again shortly.
            </p>
          </>
        ) : (
          <CatalogueBrowser
            key={`${initialTopic ?? ""}|${initialLevel ?? ""}`}
            courses={courses}
            initialTopic={initialTopic}
            initialLevel={initialLevel}
          />
        )}
      </div>

      <Subscriptions products={subscriptions} />
    </main>
  );
}
