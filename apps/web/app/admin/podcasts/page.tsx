"use client";

import { Fragment, useEffect, useState } from "react";

import { readError } from "@/lib/api-error";
import { authedFetch } from "@/lib/authed-fetch";

import { useAdmin } from "../admin-context";

interface EpisodeItem {
  id: string;
  kind: string;
  slug: string;
  title: string;
  description: string | null;
  state: string;
  show_notes: string | null;
  transcript: string | null;
  related_course_id: string | null;
  audio_url: string | null;
  duration_seconds: number | null;
  cover_image_url: string | null;
  external_platform: string | null;
  external_url: string | null;
  curator_name: string | null;
  curator_note: string | null;
  position: number;
}

interface SellableCourse {
  id: string;
  title: string;
}

/**
 * Podcast curation (REQ-STORE-04, docs/research/podcast-platform-
 * integration.md) — `podcast:manage`-gated, mirrored here only to hide a
 * form a caller can't use, the same convention every other admin
 * authoring screen follows (see admin/catalogue/page.tsx). "authored"
 * episodes are TTLI's own, self-hosted audio; "curated" ones are a
 * third-party episode recommended with attribution, embed-only.
 */
export default function PodcastsAdminScreen() {
  const { me } = useAdmin();
  const canManage = me.permissions.includes("podcast:manage");

  const [episodes, setEpisodes] = useState<EpisodeItem[] | null>(null);
  const [courses, setCourses] = useState<SellableCourse[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [kind, setKind] = useState<"authored" | "curated">("curated");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [externalUrl, setExternalUrl] = useState("");
  const [curatorName, setCuratorName] = useState("");
  const [curatorNote, setCuratorNote] = useState("");
  const [createBusy, setCreateBusy] = useState(false);
  const [lookupBusy, setLookupBusy] = useState(false);

  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [audioBusy, setAudioBusy] = useState(false);

  async function load() {
    const [e, c] = await Promise.all([
      authedFetch("/api/bff/podcasts"),
      authedFetch("/api/bff/catalogue/sellable-courses"),
    ]);
    if (e.ok) setEpisodes((await e.json()).items);
    else setError("Episodes could not be loaded.");
    if (c.ok) setCourses((await c.json()).items);
  }

  useEffect(() => {
    if (!canManage) return;
    load();
  }, [canManage]);

  async function lookupSpotify() {
    if (!externalUrl) return;
    setLookupBusy(true);
    setError(null);
    const resp = await authedFetch(
      `/api/bff/podcasts/spotify-lookup?url=${encodeURIComponent(externalUrl)}`,
    );
    setLookupBusy(false);
    if (!resp.ok) {
      setError(await readError(resp, "The lookup failed."));
      return;
    }
    const body = await resp.json();
    if (!body.configured) {
      setNotice("Spotify lookup isn't switched on for this deployment — fill the fields in by hand.");
      return;
    }
    if (body.title) setTitle(body.title);
    if (body.description) setDescription(body.description);
  }

  async function createEpisode(event: React.FormEvent) {
    event.preventDefault();
    setCreateBusy(true);
    setError(null);
    setNotice(null);
    const resp = await authedFetch("/api/bff/podcasts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        kind,
        title,
        description: description || null,
        external_url: externalUrl || null,
        curator_name: kind === "curated" ? curatorName : null,
        curator_note: kind === "curated" ? curatorNote || null : null,
      }),
    });
    setCreateBusy(false);
    if (!resp.ok) {
      setError(await readError(resp, "The episode could not be created."));
      return;
    }
    setTitle("");
    setDescription("");
    setExternalUrl("");
    setCuratorName("");
    setCuratorNote("");
    setNotice("Episode created as a draft.");
    load();
  }

  async function updateEpisode(id: string, patch: Record<string, unknown>) {
    setError(null);
    setNotice(null);
    const resp = await authedFetch(`/api/bff/podcasts/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (!resp.ok) {
      setError(await readError(resp, "The episode could not be updated."));
      return;
    }
    load();
  }

  async function togglePublish(episode: EpisodeItem) {
    setError(null);
    setNotice(null);
    const action = episode.state === "published" ? "unpublish" : "publish";
    const resp = await authedFetch(`/api/bff/podcasts/${episode.id}/${action}`, { method: "POST" });
    if (!resp.ok) {
      setError(await readError(resp, `The episode could not be ${action}ed.`));
      return;
    }
    load();
  }

  async function uploadAudio(episodeId: string, file: File) {
    setAudioBusy(true);
    setError(null);
    setNotice(null);
    const formData = new FormData();
    formData.append("file", file);
    const resp = await authedFetch(`/api/bff/podcasts/${episodeId}/audio`, {
      method: "POST",
      body: formData,
    });
    setAudioBusy(false);
    if (!resp.ok) {
      setError(await readError(resp, "The audio upload was rejected."));
      return;
    }
    setNotice("Audio uploaded.");
    load();
  }

  if (!canManage) {
    return (
      <div>
        <h1 className="serif" style={{ fontSize: "1.5rem" }}>
          Podcasts
        </h1>
        <p className="mt-2" style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
          You do not have permission to manage podcasts.
        </p>
      </div>
    );
  }

  return (
    <div>
      <h1 className="serif" style={{ fontSize: "1.5rem" }}>
        Podcasts
      </h1>
      <p className="mt-1" style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
        TTLI&rsquo;s own episodes, plus other shows recommended with attribution.
      </p>

      {error ? (
        <p role="alert" className="mt-4" style={{ fontSize: "0.8125rem", color: "var(--stop)" }}>
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="mt-4" style={{ fontSize: "0.8125rem", color: "var(--done)" }}>
          {notice}
        </p>
      ) : null}

      <section className="card mt-6" style={{ padding: "1.25rem" }}>
        <h2 className="serif" style={{ fontSize: "1.1rem" }}>
          New episode
        </h2>
        <form onSubmit={createEpisode} className="mt-3 space-y-3">
          <div className="flex gap-2" role="radiogroup" aria-label="Episode type">
            <button
              type="button"
              className={kind === "curated" ? "btn btn--primary" : "btn btn--ghost"}
              onClick={() => setKind("curated")}
              aria-pressed={kind === "curated"}
            >
              Recommend another show
            </button>
            <button
              type="button"
              className={kind === "authored" ? "btn btn--primary" : "btn btn--ghost"}
              onClick={() => setKind("authored")}
              aria-pressed={kind === "authored"}
            >
              TTLI&rsquo;s own episode
            </button>
          </div>

          {kind === "curated" ? (
            <div className="flex gap-2">
              <input
                className="input"
                value={externalUrl}
                onChange={(e) => setExternalUrl(e.target.value)}
                placeholder="https://open.spotify.com/episode/..."
                aria-label="Spotify episode URL"
              />
              <button
                type="button"
                className="btn btn--ghost"
                onClick={lookupSpotify}
                disabled={!externalUrl || lookupBusy}
              >
                {lookupBusy ? "Looking up…" : "Look up from Spotify"}
              </button>
            </div>
          ) : null}

          <input
            className="input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Episode title"
            aria-label="Episode title"
            required
          />
          <textarea
            className="input"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Short description"
            aria-label="Description"
            rows={2}
          />

          {kind === "curated" ? (
            <>
              <input
                className="input"
                value={curatorName}
                onChange={(e) => setCuratorName(e.target.value)}
                placeholder="Recommended by (host or show name)"
                aria-label="Curator name"
                required
              />
              <textarea
                className="input"
                value={curatorNote}
                onChange={(e) => setCuratorNote(e.target.value)}
                placeholder="Why it's worth a listen (optional)"
                aria-label="Curator note"
                rows={2}
              />
            </>
          ) : (
            <input
              className="input"
              value={externalUrl}
              onChange={(e) => setExternalUrl(e.target.value)}
              placeholder="Also on Spotify? Paste the link (optional)"
              aria-label="Spotify cross-post URL"
            />
          )}

          <button type="submit" disabled={createBusy} className="btn btn--primary">
            Create draft episode
          </button>
        </form>
      </section>

      <section className="mt-8">
        <h2 className="serif" style={{ fontSize: "1.1rem" }}>
          Episodes
        </h2>
        {episodes === null ? (
          <p className="mt-2" style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
            Loading…
          </p>
        ) : episodes.length === 0 ? (
          <p className="mt-2" style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
            No episodes yet.
          </p>
        ) : (
          <table className="mt-3 w-full" style={{ fontSize: "0.875rem" }}>
            <thead>
              <tr style={{ textAlign: "left", color: "var(--muted)" }}>
                <th className="py-2">Title</th>
                <th className="py-2">Type</th>
                <th className="py-2">State</th>
                <th className="py-2" />
              </tr>
            </thead>
            <tbody>
              {episodes.map((ep) => (
                <Fragment key={ep.id}>
                  <tr style={{ borderTop: "1px solid var(--rule)" }}>
                    <td className="py-2">
                      {ep.title}
                      <div style={{ fontSize: "0.75rem", color: "var(--muted)" }}>{ep.slug}</div>
                    </td>
                    <td className="py-2">
                      {ep.kind === "curated" ? `Recommended (${ep.curator_name ?? "—"})` : "TTLI"}
                    </td>
                    <td className="py-2">
                      <span className={ep.state === "published" ? "tag tag--brand" : "tag"}>
                        {ep.state}
                      </span>
                    </td>
                    <td className="py-2" style={{ textAlign: "right" }}>
                      <button
                        type="button"
                        className="btn btn--ghost"
                        onClick={() => setExpandedId(expandedId === ep.id ? null : ep.id)}
                      >
                        {expandedId === ep.id ? "Close" : "Manage"}
                      </button>
                    </td>
                  </tr>
                  {expandedId === ep.id ? (
                    <tr>
                      <td colSpan={4} style={{ background: "var(--surface-2)" }}>
                        <div className="p-4 space-y-4">
                          {ep.kind === "authored" ? (
                            <div>
                              <h3 style={{ fontSize: "0.8125rem", fontWeight: 600 }}>Audio</h3>
                              {ep.audio_url ? (
                                <audio controls src={ep.audio_url} className="mt-1 w-full" />
                              ) : (
                                <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
                                  No audio uploaded yet — needed before this episode can publish.
                                </p>
                              )}
                              <input
                                className="input mt-2"
                                type="file"
                                accept="audio/*"
                                aria-label="Upload episode audio"
                                disabled={audioBusy}
                                onChange={(e) => {
                                  const file = e.target.files?.[0];
                                  if (file) uploadAudio(ep.id, file);
                                }}
                              />

                              <h3 className="mt-3" style={{ fontSize: "0.8125rem", fontWeight: 600 }}>
                                Show notes
                              </h3>
                              <textarea
                                className="input mt-1"
                                defaultValue={ep.show_notes ?? ""}
                                rows={3}
                                aria-label="Show notes"
                                onBlur={(e) => updateEpisode(ep.id, { show_notes: e.target.value })}
                              />

                              <h3 className="mt-3" style={{ fontSize: "0.8125rem", fontWeight: 600 }}>
                                Transcript
                              </h3>
                              <textarea
                                className="input mt-1"
                                defaultValue={ep.transcript ?? ""}
                                rows={4}
                                aria-label="Transcript"
                                onBlur={(e) => updateEpisode(ep.id, { transcript: e.target.value })}
                              />

                              <h3 className="mt-3" style={{ fontSize: "0.8125rem", fontWeight: 600 }}>
                                Related course
                              </h3>
                              <select
                                className="input mt-1"
                                style={{ maxWidth: "26rem" }}
                                value={ep.related_course_id ?? ""}
                                onChange={(e) =>
                                  updateEpisode(ep.id, { related_course_id: e.target.value || null })
                                }
                                aria-label="Related course"
                              >
                                <option value="">No related course</option>
                                {(courses ?? []).map((c) => (
                                  <option key={c.id} value={c.id}>
                                    {c.title}
                                  </option>
                                ))}
                              </select>
                            </div>
                          ) : (
                            <div>
                              <h3 style={{ fontSize: "0.8125rem", fontWeight: 600 }}>
                                Why recommended
                              </h3>
                              <textarea
                                className="input mt-1"
                                defaultValue={ep.curator_note ?? ""}
                                rows={3}
                                aria-label="Curator note"
                                onBlur={(e) => updateEpisode(ep.id, { curator_note: e.target.value })}
                              />
                            </div>
                          )}

                          <div>
                            {ep.state === "published" ? (
                              <button
                                type="button"
                                className="btn btn--ghost"
                                onClick={() => togglePublish(ep)}
                              >
                                Unpublish
                              </button>
                            ) : (
                              <button
                                type="button"
                                className="btn btn--primary"
                                onClick={() => togglePublish(ep)}
                              >
                                Publish
                              </button>
                            )}
                          </div>
                        </div>
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
