"use client";

/**
 * `/admin/paths/new` — a title and an optional description, nothing
 * else: unlike a course, a path has no content of its own to author at
 * creation time, so there's no reason for a multi-step wizard here.
 * `POST /learning-paths` then straight to `/admin/paths/{id}/edit`,
 * where courses get added.
 */

import { useState } from "react";
import { useRouter } from "next/navigation";

import { readError, sendJson } from "../../courses/wizard-api";

export default function NewLearningPathPage() {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (!title.trim()) return;
    setBusy(true);
    setError(null);
    const resp = await sendJson("/api/bff/learning-paths", "POST", {
      title: title.trim(),
      description: description.trim() || null,
    });
    setBusy(false);
    if (!resp.ok) {
      setError(await readError(resp, "The learning path could not be created."));
      return;
    }
    const path = await resp.json();
    router.push(`/admin/paths/${path.id}/edit`);
  }

  return (
    <div className="dash">
      <div className="dash-top">
        <div>
          <p className="eyebrow">Path setup</p>
          <h1>New learning path</h1>
        </div>
        <a className="btn btn--ghost" href="/admin/paths">
          All paths
        </a>
      </div>

      <form onSubmit={(e) => void create(e)} className="card p-4" style={{ maxWidth: "32rem" }}>
        <label className="field">
          <b>Title</b>
          <input
            className="input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. Leadership Fundamentals"
            required
            autoFocus
          />
        </label>
        <label className="field mt-3">
          <b>Description</b>
          <textarea
            className="input"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            placeholder="Shown on the catalogue card once published."
          />
        </label>
        {error ? (
          <p role="alert" style={{ fontSize: "0.8125rem", color: "var(--stop)" }} className="mt-2">
            {error}
          </p>
        ) : null}
        <button
          type="submit"
          className="btn btn--primary mt-3"
          disabled={busy || !title.trim()}
        >
          {busy ? "Creating…" : "Create and add courses"}
        </button>
      </form>
    </div>
  );
}
