/**
 * The public podcast listing (REQ-STORE-04) — TTLI's own episodes and
 * shows recommended with attribution, side by side. Backed by the real
 * anonymous GET /public/podcasts, published episodes only.
 *
 * Rendered on the server (nothing here needs the session) as the
 * prototype's `.rowlist`: an episode list is a list, and the `.ccard`
 * grid next door is for programmes with art and a price.
 */
import Link from "next/link";

import { formatDuration } from "@/lib/format";
import { getPublicEpisodes } from "@/lib/server-api";

export const dynamic = "force-dynamic";

export default async function PodcastsPage() {
  const episodes = await getPublicEpisodes();

  return (
    <main className="pad-lg">
      <p className="eyebrow">Listen</p>
      <h1 className="serif" style={{ fontSize: "1.5rem", marginTop: "0.35rem" }}>
        Podcasts
      </h1>
      <p style={{ fontSize: "0.8125rem", color: "var(--muted)", margin: "0.35rem 0 1.5rem" }}>
        Conversations from TTLI, and other shows worth your time. Free, no account.
      </p>

      {episodes.length === 0 ? (
        <p style={{ fontSize: "0.875rem", color: "var(--muted)" }}>No episodes published yet.</p>
      ) : (
        <ul className="rowlist">
          {episodes.map((episode) => {
            const minutes = episode.duration_seconds
              ? formatDuration(Math.round(episode.duration_seconds / 60))
              : null;
            return (
              <li className="rowitem" key={episode.id}>
                <span className={episode.kind === "curated" ? "tag tag--mute" : "tag tag--brand"}>
                  {episode.kind === "curated" ? "Recommended" : "TTLI"}
                </span>
                <span className="t">{episode.title}</span>
                {episode.curator_name || minutes ? (
                  <span className="m">
                    {[episode.curator_name ? `Curated by ${episode.curator_name}` : null, minutes]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                ) : null}
                <Link href={`/podcasts/${episode.slug}`} className="btn btn--ghost">
                  Listen
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </main>
  );
}
