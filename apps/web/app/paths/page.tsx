/**
 * `/paths` — the public learning-path catalogue (`docs/BACKLOG.md` P5
 * Phase 4). Mirrors `/catalogue`'s server-rendered, anonymous-GET
 * structure, deliberately without a facet browser: `GET /catalogue`
 * exists because courses carry topic/level/format to filter on and can
 * run into the dozens; a tenant's paths are few and none of those
 * columns exist on `LearningPath`; a plain grid is the honest shape for
 * what's actually there.
 */
import { PathCard } from "@/app/paths/path-card";
import { getPublicPaths } from "@/lib/server-api";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "Learning paths",
  description: "Bundled programmes, completed in order, with one certificate at the end.",
  alternates: { canonical: "/paths" },
};

export default async function PathsPage() {
  const paths = await getPublicPaths();

  return (
    <main className="pad-lg">
      <p className="eyebrow">Learning paths</p>
      <h1 className="serif" style={{ fontSize: "1.5rem", marginTop: "0.35rem" }}>
        Bundled programmes, one credential
      </h1>
      <p style={{ fontSize: "0.875rem", color: "var(--muted)", marginTop: "0.5rem", maxWidth: "60ch" }}>
        A learning path bundles several courses into one purchase, completed in order, with its own
        certificate once every course in it is done.
      </p>

      {paths.length === 0 ? (
        <p style={{ fontSize: "0.875rem", color: "var(--muted)", marginTop: "1.5rem" }}>
          No learning paths are published for this site yet.
        </p>
      ) : (
        <div className="course-grid" style={{ marginTop: "1.75rem" }}>
          {paths.map((path) => (
            <PathCard key={path.id} path={path} />
          ))}
        </div>
      )}
    </main>
  );
}
