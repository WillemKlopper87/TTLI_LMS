"use client";

/**
 * `/admin/paths` — the learning-path list/manage view (`docs/BACKLOG.md`
 * P5). Same `.dash-top` + `.stats` + `.tablewrap` idiom
 * `admin/courses/page.tsx` uses; a path has no seven-step wizard (no
 * lessons/content/assessments to author), so "Edit" opens the single-page
 * editor at `/admin/paths/{id}/edit` instead.
 */

import { useEffect, useState } from "react";

import { useAdmin } from "../admin-context";
import { authedFetch, readError } from "../courses/wizard-api";
import { STATE_TAG } from "../courses/types";

interface LearningPathItem {
  id: string;
  slug: string;
  title: string;
  description: string | null;
  state: string;
  certificate_template_id: string | null;
}

export default function LearningPathsScreen() {
  const { me } = useAdmin();
  const canEdit = me.permissions.includes("course:edit");

  const [paths, setPaths] = useState<LearningPathItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    const resp = await authedFetch("/api/bff/learning-paths");
    if (!resp.ok) {
      setError(await readError(resp, "Learning paths could not be loaded."));
      setPaths([]);
      return;
    }
    setPaths((await resp.json()).items);
  }

  useEffect(() => {
    void (async () => {
      await load();
    })();
  }, []);

  const drafts = (paths ?? []).filter((p) => p.state !== "published").length;
  const published = (paths ?? []).filter((p) => p.state === "published").length;

  return (
    <div className="dash">
      <div className="dash-top">
        <div>
          <p className="eyebrow">Teach</p>
          <h1>Learning paths</h1>
        </div>
        {canEdit ? (
          <a className="btn btn--primary" href="/admin/paths/new">
            New path
          </a>
        ) : null}
      </div>

      {error ? (
        <div className="callout callout--warn" role="alert">
          <p style={{ fontSize: "0.8125rem" }}>{error}</p>
        </div>
      ) : null}

      <dl className="stats">
        <div className="stat">
          <dt>Paths</dt>
          <dd>{paths?.length ?? "—"}</dd>
        </div>
        <div className="stat">
          <dt>In setup</dt>
          <dd>{paths === null ? "—" : drafts}</dd>
        </div>
        <div className="stat">
          <dt>Published</dt>
          <dd>{paths === null ? "—" : published}</dd>
        </div>
      </dl>

      <div className="tablewrap">
        <table>
          <thead>
            <tr>
              <th scope="col">Path</th>
              <th scope="col">State</th>
              <th scope="col" />
            </tr>
          </thead>
          <tbody>
            {paths === null ? (
              <tr>
                <td colSpan={3} style={{ color: "var(--faint)" }}>
                  Loading…
                </td>
              </tr>
            ) : null}
            {paths !== null && paths.length === 0 ? (
              <tr>
                <td colSpan={3} style={{ color: "var(--muted)" }}>
                  No learning paths yet. &ldquo;New path&rdquo; bundles existing courses into one.
                </td>
              </tr>
            ) : null}
            {(paths ?? []).map((path) => (
              <tr key={path.id}>
                <td>
                  <b>{path.title}</b>
                  <div style={{ fontSize: "0.6875rem", color: "var(--faint)" }}>
                    {path.description || path.slug}
                  </div>
                </td>
                <td>
                  <span className={`tag ${STATE_TAG[path.state] ?? "tag--mute"}`}>
                    {path.state}
                  </span>
                </td>
                <td>
                  <div className="flex flex-wrap justify-end gap-2">
                    <a className="btn btn--ghost" href={`/admin/paths/${path.id}/edit`}>
                      {path.state === "published" ? "Edit" : "Continue setup"}
                    </a>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
