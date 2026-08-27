"use client";

import { Fragment, useEffect, useState } from "react";

import { readError } from "@/lib/api-error";
import { authedFetch } from "@/lib/authed-fetch";

import { useAdmin } from "../admin-context";

interface ArticleItem {
  id: string;
  slug: string;
  title: string;
  dek: string | null;
  body: string;
  cover_image_url: string | null;
  author_name: string | null;
  related_course_id: string | null;
  state: string;
  published_at: string | null;
  reading_minutes: number | null;
  position: number;
}

interface SellableCourse {
  id: string;
  title: string;
}

/**
 * Article authoring (`docs/research/resources-hub-design.md` §2) —
 * `podcast:manage`-gated (reused, not a new permission — see `0030`'s
 * migration docstring), structurally copied from `admin/podcasts/page.tsx`
 * minus the audio-upload path. `body` is markdown, rendered on the public
 * side through `react-markdown`, so it's a plain textarea here — no rich
 * editor, matching how show_notes/transcript are authored too.
 */
export default function ArticlesAdminScreen() {
  const { me } = useAdmin();
  const canManage = me.permissions.includes("podcast:manage");

  const [articles, setArticles] = useState<ArticleItem[] | null>(null);
  const [courses, setCourses] = useState<SellableCourse[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [title, setTitle] = useState("");
  const [dek, setDek] = useState("");
  const [body, setBody] = useState("");
  const [authorName, setAuthorName] = useState("");
  const [createBusy, setCreateBusy] = useState(false);

  const [expandedId, setExpandedId] = useState<string | null>(null);

  async function load() {
    const [a, c] = await Promise.all([
      authedFetch("/api/bff/articles"),
      authedFetch("/api/bff/catalogue/sellable-courses"),
    ]);
    if (a.ok) setArticles((await a.json()).items);
    else setError("Articles could not be loaded.");
    if (c.ok) setCourses((await c.json()).items);
  }

  useEffect(() => {
    if (!canManage) return;
    load();
  }, [canManage]);

  async function createArticle(event: React.FormEvent) {
    event.preventDefault();
    setCreateBusy(true);
    setError(null);
    setNotice(null);
    const resp = await authedFetch("/api/bff/articles", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title,
        dek: dek || null,
        body,
        author_name: authorName || null,
      }),
    });
    setCreateBusy(false);
    if (!resp.ok) {
      setError(await readError(resp, "The article could not be created."));
      return;
    }
    setTitle("");
    setDek("");
    setBody("");
    setAuthorName("");
    setNotice("Article created as a draft.");
    load();
  }

  async function updateArticle(id: string, patch: Record<string, unknown>) {
    setError(null);
    setNotice(null);
    const resp = await authedFetch(`/api/bff/articles/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (!resp.ok) {
      setError(await readError(resp, "The article could not be updated."));
      return;
    }
    load();
  }

  async function togglePublish(article: ArticleItem) {
    setError(null);
    setNotice(null);
    const action = article.state === "published" ? "unpublish" : "publish";
    const resp = await authedFetch(`/api/bff/articles/${article.id}/${action}`, {
      method: "POST",
    });
    if (!resp.ok) {
      setError(await readError(resp, `The article could not be ${action}ed.`));
      return;
    }
    load();
  }

  if (!canManage) {
    return (
      <div>
        <h1 className="serif" style={{ fontSize: "1.5rem" }}>
          Articles
        </h1>
        <p className="mt-2" style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
          You do not have permission to manage articles.
        </p>
      </div>
    );
  }

  return (
    <div>
      <h1 className="serif" style={{ fontSize: "1.5rem" }}>
        Articles
      </h1>
      <p className="mt-1" style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
        Long-form writing for the Resources hub. Body is markdown.
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
          New article
        </h2>
        <form onSubmit={createArticle} className="mt-3 space-y-3">
          <input
            className="input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Article title"
            aria-label="Article title"
            required
          />
          <input
            className="input"
            value={dek}
            onChange={(e) => setDek(e.target.value)}
            placeholder="One-line summary (optional)"
            aria-label="Dek"
          />
          <input
            className="input"
            value={authorName}
            onChange={(e) => setAuthorName(e.target.value)}
            placeholder="Author name (optional)"
            aria-label="Author name"
          />
          <textarea
            className="input"
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="Body — markdown (## headings, lists, **bold**, links)"
            aria-label="Body"
            rows={8}
            required
          />
          <button type="submit" disabled={createBusy} className="btn btn--primary">
            Create draft article
          </button>
        </form>
      </section>

      <section className="mt-8">
        <h2 className="serif" style={{ fontSize: "1.1rem" }}>
          Articles
        </h2>
        {articles === null ? (
          <p className="mt-2" style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
            Loading…
          </p>
        ) : articles.length === 0 ? (
          <p className="mt-2" style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
            No articles yet.
          </p>
        ) : (
          <table className="mt-3 w-full" style={{ fontSize: "0.875rem" }}>
            <thead>
              <tr style={{ textAlign: "left", color: "var(--muted)" }}>
                <th className="py-2">Title</th>
                <th className="py-2">Reading time</th>
                <th className="py-2">State</th>
                <th className="py-2" />
              </tr>
            </thead>
            <tbody>
              {articles.map((a) => (
                <Fragment key={a.id}>
                  <tr style={{ borderTop: "1px solid var(--rule)" }}>
                    <td className="py-2">
                      {a.title}
                      <div style={{ fontSize: "0.75rem", color: "var(--muted)" }}>{a.slug}</div>
                    </td>
                    <td className="py-2">
                      {a.reading_minutes ? `${a.reading_minutes} min` : "—"}
                    </td>
                    <td className="py-2">
                      <span className={a.state === "published" ? "tag tag--brand" : "tag"}>
                        {a.state}
                      </span>
                    </td>
                    <td className="py-2" style={{ textAlign: "right" }}>
                      <button
                        type="button"
                        className="btn btn--ghost"
                        onClick={() => setExpandedId(expandedId === a.id ? null : a.id)}
                      >
                        {expandedId === a.id ? "Close" : "Manage"}
                      </button>
                    </td>
                  </tr>
                  {expandedId === a.id ? (
                    <tr>
                      <td colSpan={4} style={{ background: "var(--surface-2)" }}>
                        <div className="p-4 space-y-4">
                          <div>
                            <h3 style={{ fontSize: "0.8125rem", fontWeight: 600 }}>Dek</h3>
                            <input
                              className="input mt-1"
                              defaultValue={a.dek ?? ""}
                              aria-label="Dek"
                              onBlur={(e) => updateArticle(a.id, { dek: e.target.value })}
                            />

                            <h3 className="mt-3" style={{ fontSize: "0.8125rem", fontWeight: 600 }}>
                              Body (markdown)
                            </h3>
                            <textarea
                              className="input mt-1"
                              defaultValue={a.body}
                              rows={8}
                              aria-label="Body"
                              onBlur={(e) => updateArticle(a.id, { body: e.target.value })}
                            />

                            <h3 className="mt-3" style={{ fontSize: "0.8125rem", fontWeight: 600 }}>
                              Author
                            </h3>
                            <input
                              className="input mt-1"
                              defaultValue={a.author_name ?? ""}
                              aria-label="Author name"
                              onBlur={(e) => updateArticle(a.id, { author_name: e.target.value })}
                            />

                            <h3 className="mt-3" style={{ fontSize: "0.8125rem", fontWeight: 600 }}>
                              Related course
                            </h3>
                            <select
                              className="input mt-1"
                              style={{ maxWidth: "26rem" }}
                              value={a.related_course_id ?? ""}
                              onChange={(e) =>
                                updateArticle(a.id, { related_course_id: e.target.value || null })
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
                            {a.state === "published" ? (
                              <button
                                type="button"
                                className="btn btn--ghost"
                                onClick={() => togglePublish(a)}
                              >
                                Unpublish
                              </button>
                            ) : (
                              <button
                                type="button"
                                className="btn btn--primary"
                                onClick={() => togglePublish(a)}
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
