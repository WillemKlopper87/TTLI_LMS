"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

interface EpisodeSummary {
  id: string;
  kind: string;
  slug: string;
  title: string;
  description: string | null;
  cover_image_url: string | null;
  curator_name: string | null;
  duration_seconds: number | null;
}

function formatDuration(seconds: number | null): string | null {
  if (!seconds) return null;
  const minutes = Math.round(seconds / 60);
  return `${minutes} min`;
}

/**
 * The public podcast listing (REQ-STORE-04) — TTLI's own episodes and
 * shows recommended with attribution, side by side. Backed by the real
 * GET /public/podcasts, published episodes only.
 */
export default function PodcastsPage() {
  const [episodes, setEpisodes] = useState<EpisodeSummary[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch("/api/bff/public/podcasts")
      .then(async (resp) => {
        if (!resp.ok) {
          setError(true);
          return;
        }
        setEpisodes((await resp.json()).items);
      })
      .catch(() => setError(true));
  }, []);

  return (
    <main className="mx-auto max-w-4xl px-6 py-16">
      <p className="eyebrow">Listen</p>
      <h1 className="serif mt-2" style={{ fontSize: "1.75rem" }}>
        Podcasts
      </h1>
      <p className="mt-2" style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
        Conversations from TTLI, and other shows worth your time.
      </p>

      {error ? (
        <p className="mt-6" style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
          Episodes could not be loaded. Try again shortly.
        </p>
      ) : episodes === null ? (
        <p className="mt-6" style={{ fontSize: "0.875rem", color: "var(--faint)" }}>
          Loading…
        </p>
      ) : episodes.length === 0 ? (
        <p className="mt-6" style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
          No episodes published yet.
        </p>
      ) : (
        <div className="mt-8 grid gap-4 md:grid-cols-2">
          {episodes.map((episode) => (
            <Link
              key={episode.id}
              href={`/podcasts/${episode.slug}`}
              className="card p-5"
              style={{ display: "block" }}
            >
              <span className="tag">
                {episode.kind === "curated" ? `Recommended by ${episode.curator_name}` : "TTLI"}
              </span>
              <h2 className="serif mt-2" style={{ fontSize: "1.0625rem" }}>
                {episode.title}
              </h2>
              {episode.description ? (
                <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
                  {episode.description}
                </p>
              ) : null}
              {formatDuration(episode.duration_seconds) ? (
                <p className="mt-2" style={{ fontSize: "0.75rem", color: "var(--faint)" }}>
                  {formatDuration(episode.duration_seconds)}
                </p>
              ) : null}
            </Link>
          ))}
        </div>
      )}
    </main>
  );
}
