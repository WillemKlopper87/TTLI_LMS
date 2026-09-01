"use client";

/**
 * A published podcast episode — prototype screen 2.
 *
 * Still a client page: the view/play/click-through analytics events, the
 * click-to-load Spotify embed and the player itself all live in the
 * browser, and the episode is fetched through the BFF like every other
 * browser-side read.
 *
 * The player is the prototype's `.player-strip` driving a real `<audio>`
 * element. The element stays — it is what actually plays, what fires
 * `podcast.play.started`, and what a screen reader or a keyboard user
 * lands on if scripting fails midway — but its native chrome is hidden
 * so the strip is the only visible control.
 */
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { countLabel, formatClock, joinMeta } from "@/lib/format";

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

interface RelatedCourse {
  title: string;
  modules: unknown[];
  has_certificate: boolean;
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
  // listener on. POST /public/podcasts/{slug}/events, no response body.
  fetch(`/api/bff/public/podcasts/${slug}/events`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event_name: eventName, ...extra }),
  }).catch(() => undefined);
}

/** Show notes are free text. Any line that opens with a timestamp is
 * treated as a chapter marker ("02:10 Why delay compounds"); if none do,
 * the "In this episode" card is simply not rendered. */
function parseChapters(showNotes: string | null): Array<{ at: string; label: string }> {
  if (!showNotes) return [];
  const chapters: Array<{ at: string; label: string }> = [];
  for (const line of showNotes.split(/\r?\n/)) {
    const match = /^\s*\(?(\d{1,2}:\d{2}(?::\d{2})?)\)?\s*[-–—:]?\s*(.+?)\s*$/.exec(line);
    if (match && match[2]) chapters.push({ at: match[1], label: match[2] });
  }
  return chapters;
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
        className="btn btn--ghost"
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

export function EpisodeDetail() {
  const params = useParams<{ slug: string }>();
  const slug = params.slug;
  const [episode, setEpisode] = useState<EpisodeDetail | null>(null);
  const [related, setRelated] = useState<RelatedCourse | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [played, setPlayed] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const [duration, setDuration] = useState<number | null>(null);
  const audioRef = useRef<HTMLAudioElement>(null);

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
        setDuration(body.duration_seconds);
        logEvent(slug, "podcast.episode.viewed");
      })
      .catch(() => setNotFound(true));
  }, [slug]);

  // The related programme's own title/size for the aside card — the
  // episode carries only the course id.
  useEffect(() => {
    const courseId = episode?.related_course_id;
    if (!courseId) return;
    let cancelled = false;
    fetch(`/api/bff/public/courses/${courseId}/curriculum`)
      .then((resp) => (resp.ok ? resp.json() : null))
      .then((data) => {
        if (cancelled || !data) return;
        setRelated({
          title: data.title,
          modules: data.modules ?? [],
          has_certificate: Boolean(data.has_certificate),
        });
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [episode?.related_course_id]);

  if (notFound) {
    return (
      <main className="pad-lg" style={{ textAlign: "center" }}>
        <h1 className="serif" style={{ fontSize: "1.5rem" }}>
          Episode not found
        </h1>
        <Link href="/podcasts" className="btn btn--ghost" style={{ marginTop: "1rem" }}>
          Back to podcasts
        </Link>
      </main>
    );
  }

  if (!episode) {
    return (
      <main className="pad-lg">
        <p style={{ fontSize: "0.875rem", color: "var(--faint)" }}>Loading…</p>
      </main>
    );
  }

  const chapters = parseChapters(episode.show_notes);
  const total = duration ?? episode.duration_seconds;
  const progress = total && total > 0 ? Math.min(100, (position / total) * 100) : 0;
  const eyebrow = joinMeta([
    episode.kind === "curated" ? "Recommended listening" : "Podcast",
    episode.curator_name && episode.kind === "curated" ? `Curated by ${episode.curator_name}` : null,
    "Free to everyone",
  ]);

  function togglePlay() {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) {
      void audio.play();
    } else {
      audio.pause();
    }
  }

  return (
    <main className="pad-lg">
      <div className="article">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h1
            className="serif"
            style={{
              fontSize: "clamp(1.6rem, 3.2vw, 2.3rem)",
              letterSpacing: "-0.018em",
              margin: "0.5rem 0 1.15rem",
            }}
          >
            {episode.title}
          </h1>

          {episode.audio_url ? (
            <>
              <div className="player-strip">
                <button
                  type="button"
                  className="play-round"
                  aria-label={playing ? "Pause episode" : "Play episode"}
                  onClick={togglePlay}
                >
                  <span aria-hidden="true">{playing ? "❚❚" : "▶"}</span>
                </button>
                <div>
                  <div
                    className="bar"
                    role="progressbar"
                    aria-label="Playback position"
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={Math.round(progress)}
                  >
                    <i style={{ width: `${progress}%` }} />
                  </div>
                  <div className="times">
                    <span>{formatClock(position)}</span>
                    <span>{total ? `−${formatClock(Math.max(0, total - position))}` : "--:--"}</span>
                  </div>
                </div>
              </div>
              {/* Kept, and kept functional: the strip above is a skin over
                  this element, which is what actually plays the audio. */}
              <audio
                ref={audioRef}
                src={episode.audio_url}
                preload="metadata"
                style={{ display: "none" }}
                onPlay={() => {
                  setPlaying(true);
                  if (!played) {
                    setPlayed(true);
                    logEvent(slug, "podcast.play.started", { source: "self_hosted" });
                  }
                }}
                onPause={() => setPlaying(false)}
                onEnded={() => setPlaying(false)}
                onTimeUpdate={(event) => setPosition(event.currentTarget.currentTime)}
                onLoadedMetadata={(event) => {
                  const value = event.currentTarget.duration;
                  if (Number.isFinite(value)) setDuration(value);
                }}
              />
            </>
          ) : null}

          {episode.description ? (
            <div className="prose" style={{ marginTop: "1.5rem" }}>
              <p className="lead">{episode.description}</p>
            </div>
          ) : null}

          {episode.external_embed_id ? (
            <div style={{ marginTop: "1.5rem" }}>
              {episode.audio_url ? (
                <p style={{ fontSize: "0.75rem", color: "var(--muted)", marginBottom: "0.5rem" }}>
                  Also on Spotify:
                </p>
              ) : null}
              <SpotifyEmbed embedId={episode.external_embed_id} slug={slug} />
            </div>
          ) : episode.external_url && isSafeHttpUrl(episode.external_url) ? (
            <div style={{ marginTop: "1.5rem" }}>
              <a
                href={episode.external_url}
                target="_blank"
                rel="noreferrer"
                className="btn btn--ghost"
                onClick={() =>
                  logEvent(slug, "podcast.embed.click_through", {
                    external_platform: episode.external_platform,
                  })
                }
              >
                Listen on{" "}
                {episode.external_platform === "apple_podcasts"
                  ? "Apple Podcasts"
                  : "the original site"}
              </a>
            </div>
          ) : null}

          <div className="gate" style={{ marginTop: "1.5rem" }}>
            <p className="eyebrow" style={{ color: "var(--brand-ink)" }}>
              Mentioned in this episode
            </p>
            <h4>Try the lesson this conversation comes from</h4>
            <p>
              One full sample lesson and a marked sample assessment, free. No card, no automatic
              renewal — we just need somewhere to send the sign-in link.
            </p>
            <Link
              href="/guest-access"
              className="btn btn--primary"
              style={{ justifySelf: "start" }}
              onClick={() => logEvent(slug, "podcast.cta.guest_access_clicked")}
            >
              Try a free lesson
            </Link>
          </div>

          {episode.show_notes ? (
            <div style={{ marginTop: "2rem" }}>
              <h2 className="serif" style={{ fontSize: "1.0625rem", marginBottom: "0.5rem" }}>
                Show notes
              </h2>
              <div className="prose">
                <p style={{ fontSize: "0.875rem", whiteSpace: "pre-wrap" }}>{episode.show_notes}</p>
              </div>
            </div>
          ) : null}

          {episode.transcript ? (
            <div style={{ marginTop: "2rem" }}>
              <h2 className="serif" style={{ fontSize: "1.0625rem", marginBottom: "0.5rem" }}>
                Transcript
              </h2>
              <div className="prose">
                <p style={{ fontSize: "0.8125rem", whiteSpace: "pre-wrap" }}>{episode.transcript}</p>
              </div>
            </div>
          ) : null}
        </div>

        <aside style={{ display: "grid", gap: "1rem", alignContent: "start" }}>
          {episode.curator_name || episode.curator_note ? (
            <div className="aside-card">
              <p className="eyebrow">{episode.kind === "curated" ? "Curated by" : "Facilitator"}</p>
              {episode.curator_name ? (
                <h4 className="serif" style={{ fontSize: "1.0625rem" }}>
                  {episode.curator_name}
                </h4>
              ) : null}
              {episode.curator_note ? (
                <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>{episode.curator_note}</p>
              ) : null}
            </div>
          ) : null}

          {episode.related_course_id ? (
            <div className="aside-card">
              <p className="eyebrow">Related programme</p>
              <h4 className="serif" style={{ fontSize: "1.0625rem" }}>
                {related?.title ?? "The programme this comes from"}
              </h4>
              {related ? (
                <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
                  {joinMeta([
                    countLabel(related.modules.length, "module"),
                    related.has_certificate ? "certificate" : null,
                  ])}
                </p>
              ) : null}
              <Link
                href={`/courses/${episode.related_course_id}`}
                className="btn btn--ghost btn--block"
                onClick={() => logEvent(slug, "podcast.cta.course_clicked", {})}
              >
                View programme
              </Link>
            </div>
          ) : null}

          {chapters.length > 0 ? (
            <div className="aside-card">
              <p className="eyebrow">In this episode</p>
              <ul style={{ fontSize: "0.8125rem", color: "var(--ink-2)", display: "grid", gap: "0.35rem" }}>
                {chapters.map((chapter) => (
                  <li key={`${chapter.at}-${chapter.label}`}>
                    <span className="mono" style={{ color: "var(--faint)" }}>
                      {chapter.at}
                    </span>
                    &nbsp;&nbsp;{chapter.label}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </aside>
      </div>
    </main>
  );
}
