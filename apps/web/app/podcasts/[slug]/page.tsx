"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

interface EpisodeDetail {
  id: string;
  kind: string;
  slug: string;
  title: string;
  description: string | null;
  show_notes: string | null;
  transcript: string | null;
  related_course_id: string | null;
  audio_url: string | null;
  duration_seconds: number | null;
  cover_image_url: string | null;
  external_platform: string | null;
  external_url: string | null;
  external_embed_id: string | null;
  curator_name: string | null;
  curator_note: string | null;
}

// Defense in depth for a raw <a href> — the backend already refuses
// anything but http(s):// at write time (services/podcasts.py's
// _validate_external_url), but external_url still reaches this
// component as untyped API JSON, and a bare `href={url}` would let a
// javascript:/data: URI execute on click if that first layer were ever
// bypassed. Belt and braces, the same layered posture the Payfast
// webhook's signature+confirm+amount checks already established.
function isSafeHttpUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

function logEvent(slug: string, eventName: string, extra: Record<string, unknown> = {}) {
  // Fire-and-forget, no auth — a dropped stat is not worth blocking the
  // listener on. GET /public/podcasts/{slug}/events, no response body.
  fetch(`/api/bff/public/podcasts/${slug}/events`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event_name: eventName, ...extra }),
  }).catch(() => undefined);
}

/**
 * A lazy, click-to-load Spotify embed — no iframe injected until the
 * visitor asks for it. Pending the cookie-consent banner this project
 * doesn't have yet (docs/research/podcast-platform-integration.md §9),
 * this is the self-contained mitigation: nothing crosses to Spotify
 * until an explicit click, regardless of when/whether a consent system
 * ships. Zero new dependencies — a plain <iframe>, not the Spotify Web
 * Playback SDK (which needs a listener's own Premium OAuth and is for
 * building a Spotify client, not embedding a show).
 */
function SpotifyEmbed({ embedId, slug }: { embedId: string; slug: string }) {
  const [loaded, setLoaded] = useState(false);

  if (!loaded) {
    return (
      <button
        type="button"
        className="btn btn--primary"
        onClick={() => {
          setLoaded(true);
          logEvent(slug, "podcast.embed.click_through", { external_platform: "spotify" });
        }}
      >
        Load the Spotify player
      </button>
    );
  }

  return (
    <iframe
      title="Spotify episode player"
      src={`https://open.spotify.com/embed/episode/${embedId}`}
      width="100%"
      height="152"
      style={{ border: 0, borderRadius: "12px" }}
      allow="encrypted-media"
      loading="lazy"
    />
  );
}

export default function PodcastEpisodePage() {
  const params = useParams<{ slug: string }>();
  const slug = params.slug;
  const [episode, setEpisode] = useState<EpisodeDetail | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [played, setPlayed] = useState(false);

  useEffect(() => {
    if (!slug) return;
    fetch(`/api/bff/public/podcasts/${slug}`)
      .then(async (resp) => {
        if (!resp.ok) {
          setNotFound(true);
          return;
        }
        const body: EpisodeDetail = await resp.json();
        setEpisode(body);
        logEvent(slug, "podcast.episode.viewed");
      })
      .catch(() => setNotFound(true));
  }, [slug]);

  if (notFound) {
    return (
      <main className="mx-auto max-w-2xl px-6 py-16 text-center">
        <h1 className="serif" style={{ fontSize: "1.5rem" }}>
          Episode not found
        </h1>
        <Link href="/podcasts" className="btn btn--ghost mt-4">
          Back to podcasts
        </Link>
      </main>
    );
  }

  if (!episode) {
    return (
      <main className="mx-auto max-w-2xl px-6 py-16">
        <p style={{ fontSize: "0.875rem", color: "var(--faint)" }}>Loading…</p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-2xl px-6 py-16">
      <Link href="/podcasts" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
        ← All podcasts
      </Link>

      <span className="tag mt-4" style={{ display: "inline-block" }}>
        {episode.kind === "curated" ? `Recommended by ${episode.curator_name}` : "TTLI"}
      </span>
      <h1 className="serif mt-2" style={{ fontSize: "1.75rem" }}>
        {episode.title}
      </h1>
      {episode.description ? (
        <p className="mt-2" style={{ fontSize: "0.9375rem", color: "var(--muted)" }}>
          {episode.description}
        </p>
      ) : null}

      <div className="mt-6">
        {episode.audio_url ? (
          <audio
            controls
            src={episode.audio_url}
            className="w-full"
            onPlay={() => {
              if (!played) {
                setPlayed(true);
                logEvent(slug, "podcast.play.started", { source: "self_hosted" });
              }
            }}
          />
        ) : null}
        {episode.external_embed_id ? (
          <div className={episode.audio_url ? "mt-3" : ""}>
            {episode.audio_url ? (
              <p className="mb-2" style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                Also on Spotify:
              </p>
            ) : null}
            <SpotifyEmbed embedId={episode.external_embed_id} slug={slug} />
          </div>
        ) : episode.external_url && isSafeHttpUrl(episode.external_url) ? (
          <a
            href={episode.external_url}
            target="_blank"
            rel="noreferrer"
            className="btn btn--primary"
            onClick={() =>
              logEvent(slug, "podcast.embed.click_through", {
                external_platform: episode.external_platform,
              })
            }
          >
            Listen on{" "}
            {episode.external_platform === "apple_podcasts" ? "Apple Podcasts" : "the original site"}
          </a>
        ) : null}
      </div>

      {episode.curator_note ? (
        <div className="card mt-6 p-4">
          <h2 style={{ fontSize: "0.8125rem", fontWeight: 600 }}>Why we recommend it</h2>
          <p className="mt-1" style={{ fontSize: "0.875rem" }}>
            {episode.curator_note}
          </p>
        </div>
      ) : null}

      {episode.show_notes ? (
        <div className="mt-6">
          <h2 className="serif" style={{ fontSize: "1.0625rem" }}>
            Show notes
          </h2>
          <p className="mt-2" style={{ fontSize: "0.875rem", whiteSpace: "pre-wrap" }}>
            {episode.show_notes}
          </p>
        </div>
      ) : null}

      {episode.related_course_id ? (
        <div className="card mt-6 p-4">
          <p style={{ fontSize: "0.875rem" }}>Want to go deeper on this topic?</p>
          <Link
            href={`/courses/${episode.related_course_id}`}
            className="btn btn--primary mt-2"
            onClick={() => logEvent(slug, "podcast.cta.course_clicked", {})}
          >
            View the related course
          </Link>
        </div>
      ) : null}

      {episode.transcript ? (
        <div className="mt-8">
          <h2 className="serif" style={{ fontSize: "1.0625rem" }}>
            Transcript
          </h2>
          <p className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--muted)", whiteSpace: "pre-wrap" }}>
            {episode.transcript}
          </p>
        </div>
      ) : null}
    </main>
  );
}
