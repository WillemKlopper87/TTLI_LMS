"use client";

import { Fragment, useEffect, useState } from "react";

import { readError } from "@/lib/api-error";
import { authedFetch } from "@/lib/authed-fetch";

import { useAdmin } from "../admin-context";

interface RecommendationItem {
  id: string;
  title: string;
  url: string;
  source_name: string | null;
  curator_name: string | null;
  curator_note: string | null;
  related_course_id: string | null;
  state: string;
  position: number;
}

interface SellableCourse {
  id: string;
  title: string;
}

/**
 * Recommendation authoring (`docs/research/resources-hub-design.md` §3) —
 * `podcast:manage`-gated (reused, same call as articles — see `0031`'s
 * migration docstring), structurally copied from `admin/articles/page.tsx`,
 * one size smaller: no body, no dek, just an external link and a note.
 * These merge with curated podcast episodes on the public `/resources`
 * page's "What our facilitators recommend" list.
 */
export default function RecommendationsAdminScreen() {
  const { me } = useAdmin();
  const canManage = me.permissions.includes("podcast:manage");

  const [recommendations, setRecommendations] = useState<RecommendationItem[] | null>(null);
  const [courses, setCourses] = useState<SellableCourse[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [sourceName, setSourceName] = useState("");
  const [curatorName, setCuratorName] = useState("");
  const [curatorNote, setCuratorNote] = useState("");
  const [createBusy, setCreateBusy] = useState(false);

  const [expandedId, setExpandedId] = useState<string | null>(null);

  async function load() {
    const [r, c] = await Promise.all([
      authedFetch("/api/bff/recommendations"),
      authedFetch("/api/bff/catalogue/sellable-courses"),
    ]);
    if (r.ok) setRecommendations((await r.json()).items);
    else setError("Recommendations could not be loaded.");
    if (c.ok) setCourses((await c.json()).items);
  }

  useEffect(() => {
    if (!canManage) return;
    void (async () => {
      await load();
    })();
  }, [canManage]);

  async function createRecommendation(event: React.FormEvent) {
    event.preventDefault();
    setCreateBusy(true);
    setError(null);
    setNotice(null);
    const resp = await authedFetch("/api/bff/recommendations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title,
        url,
        source_name: sourceName || null,
        curator_name: curatorName || null,
        curator_note: curatorNote || null,
      }),
    });
    setCreateBusy(false);
    if (!resp.ok) {
      setError(await readError(resp, "The recommendation could not be created."));
      return;
    }
    setTitle("");
    setUrl("");
    setSourceName("");
    setCuratorName("");
    setCuratorNote("");
    setNotice("Recommendation created as a draft.");
    load();
  }

  async function updateRecommendation(id: string, patch: Record<string, unknown>) {
    setError(null);
    setNotice(null);
    const resp = await authedFetch(`/api/bff/recommendations/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (!resp.ok) {
      setError(await readError(resp, "The recommendation could not be updated."));
      return;
    }
    load();
  }

  async function togglePublish(recommendation: RecommendationItem) {
    setError(null);
    setNotice(null);
    const action = recommendation.state === "published" ? "unpublish" : "publish";
    const resp = await authedFetch(`/api/bff/recommendations/${recommendation.id}/${action}`, {
      method: "POST",
    });
    if (!resp.ok) {
      setError(await readError(resp, `The recommendation could not be ${action}ed.`));
      return;
    }
    load();
  }

  if (!canManage) {
    return (
      <div>
        <h1 className="serif" style={{ fontSize: "1.5rem" }}>
          Recommendations
        </h1>
        <p className="mt-2" style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
          You do not have permission to manage recommendations.
        </p>
      </div>
    );
  }

  return (
    <div>
      <h1 className="serif" style={{ fontSize: "1.5rem" }}>
        Recommendations
      </h1>
      <p className="mt-1" style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
        External &ldquo;further reading&rdquo; links for the Resources hub — books, articles, papers by other
        people. For TTLI&rsquo;s own podcast, use Podcasts instead.
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
          New recommendation
        </h2>
        <form onSubmit={createRecommendation} className="mt-3 space-y-3">
          <input
            className="input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Title"
            aria-label="Title"
            required
          />
          <input
            className="input"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://..."
            aria-label="URL"
            required
          />
          <input
            className="input"
            value={sourceName}
            onChange={(e) => setSourceName(e.target.value)}
            placeholder="Source (e.g. Harvard Business Review) — optional"
            aria-label="Source name"
          />
          <input
            className="input"
            value={curatorName}
            onChange={(e) => setCuratorName(e.target.value)}
            placeholder="Recommended by (optional)"
            aria-label="Curator name"
          />
          <textarea
            className="input"
            value={curatorNote}
            onChange={(e) => setCuratorNote(e.target.value)}
            placeholder="Why it's worth reading (optional)"
            aria-label="Curator note"
            rows={2}
          />
          <button type="submit" disabled={createBusy} className="btn btn--primary">
            Create draft recommendation
          </button>
        </form>
      </section>

      <section className="mt-8">
        <h2 className="serif" style={{ fontSize: "1.1rem" }}>
          Recommendations
        </h2>
        {recommendations === null ? (
          <p className="mt-2" style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
            Loading…
          </p>
        ) : recommendations.length === 0 ? (
          <p className="mt-2" style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
            No recommendations yet.
          </p>
        ) : (
          <table className="mt-3 w-full" style={{ fontSize: "0.875rem" }}>
            <thead>
              <tr style={{ textAlign: "left", color: "var(--muted)" }}>
                <th className="py-2">Title</th>
                <th className="py-2">Source</th>
                <th className="py-2">State</th>
                <th className="py-2" />
              </tr>
            </thead>
            <tbody>
              {recommendations.map((r) => (
                <Fragment key={r.id}>
                  <tr style={{ borderTop: "1px solid var(--rule)" }}>
                    <td className="py-2">
                      {r.title}
                      <div style={{ fontSize: "0.75rem", color: "var(--muted)" }}>{r.url}</div>
                    </td>
                    <td className="py-2">{r.source_name ?? "—"}</td>
                    <td className="py-2">
                      <span className={r.state === "published" ? "tag tag--brand" : "tag"}>
                        {r.state}
                      </span>
                    </td>
                    <td className="py-2" style={{ textAlign: "right" }}>
                      <button
                        type="button"
                        className="btn btn--ghost"
                        onClick={() => setExpandedId(expandedId === r.id ? null : r.id)}
                      >
                        {expandedId === r.id ? "Close" : "Manage"}
                      </button>
                    </td>
                  </tr>
                  {expandedId === r.id ? (
                    <tr>
                      <td colSpan={4} style={{ background: "var(--surface-2)" }}>
                        <div className="p-4 space-y-4">
                          <div>
                            <h3 style={{ fontSize: "0.8125rem", fontWeight: 600 }}>URL</h3>
                            <input
                              className="input mt-1"
                              defaultValue={r.url}
                              aria-label="URL"
                              onBlur={(e) => updateRecommendation(r.id, { url: e.target.value })}
                            />

                            <h3 className="mt-3" style={{ fontSize: "0.8125rem", fontWeight: 600 }}>
                              Source
                            </h3>
                            <input
                              className="input mt-1"
                              defaultValue={r.source_name ?? ""}
                              aria-label="Source name"
                              onBlur={(e) =>
                                updateRecommendation(r.id, { source_name: e.target.value })
                              }
                            />

                            <h3 className="mt-3" style={{ fontSize: "0.8125rem", fontWeight: 600 }}>
                              Recommended by
                            </h3>
                            <input
                              className="input mt-1"
                              defaultValue={r.curator_name ?? ""}
                              aria-label="Curator name"
                              onBlur={(e) =>
                                updateRecommendation(r.id, { curator_name: e.target.value })
                              }
                            />

                            <h3 className="mt-3" style={{ fontSize: "0.8125rem", fontWeight: 600 }}>
                              Note
                            </h3>
                            <textarea
                              className="input mt-1"
                              defaultValue={r.curator_note ?? ""}
                              rows={2}
                              aria-label="Curator note"
                              onBlur={(e) =>
                                updateRecommendation(r.id, { curator_note: e.target.value })
                              }
                            />

                            <h3 className="mt-3" style={{ fontSize: "0.8125rem", fontWeight: 600 }}>
                              Related course
                            </h3>
                            <select
                              className="input mt-1"
                              style={{ maxWidth: "26rem" }}
                              value={r.related_course_id ?? ""}
                              onChange={(e) =>
                                updateRecommendation(r.id, {
                                  related_course_id: e.target.value || null,
                                })
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

                          <div>
                            {r.state === "published" ? (
                              <button
                                type="button"
                                className="btn btn--ghost"
                                onClick={() => togglePublish(r)}
                              >
                                Unpublish
                              </button>
                            ) : (
                              <button
                                type="button"
                                className="btn btn--primary"
                                onClick={() => togglePublish(r)}
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
