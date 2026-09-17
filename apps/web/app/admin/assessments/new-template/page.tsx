"use client";

/**
 * `/admin/assessments/new-template` — create a new assessment template.
 * POST /assessment-platform/templates with TemplateCreateRequest.
 * Requires assessment:author permission.
 */

import { useState } from "react";
import { useRouter } from "next/navigation";

import { readError, sendJson } from "../../courses/wizard-api";

export default function NewTemplateModal() {
  const router = useRouter();
  const [slug, setSlug] = useState("");
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState("org_survey");
  const [description, setDescription] = useState("");
  const [responseMode, setResponseMode] = useState("identified");
  const [minimumGroupSize, setMinimumGroupSize] = useState(5);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (!title.trim() || !slug.trim()) return;
    setBusy(true);
    setError(null);
    const resp = await sendJson("/api/bff/assessment-platform/templates", "POST", {
      slug: slug.trim(),
      title: title.trim(),
      kind,
      description: description.trim() || null,
      response_mode: responseMode,
      minimum_group_size: minimumGroupSize,
    });
    setBusy(false);
    if (!resp.ok) {
      setError(await readError(resp, "The template could not be created."));
      return;
    }
    const template = await resp.json();
    router.push(`/admin/assessments`);
  }

  return (
    <div className="dash">
      <div className="dash-top">
        <div>
          <p className="eyebrow">Template setup</p>
          <h1>New assessment template</h1>
        </div>
        <a className="btn btn--ghost" href="/admin/assessments">
          All assessments
        </a>
      </div>

      <form onSubmit={(e) => void create(e)} className="card p-4" style={{ maxWidth: "32rem" }}>
        <label className="field">
          <b>Title</b>
          <input
            className="input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. Leadership Assessment Q1 2024"
            required
            autoFocus
          />
        </label>

        <label className="field mt-3">
          <b>Slug</b>
          <input
            className="input"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            placeholder="e.g. leadership-q1-2024"
            required
          />
          <small style={{ color: "var(--muted)", display: "block", marginTop: "0.25rem" }}>
            URL-friendly identifier for the template
          </small>
        </label>

        <label className="field mt-3">
          <b>Kind</b>
          <select
            className="input"
            value={kind}
            onChange={(e) => setKind(e.target.value)}
          >
            <option value="org_survey">Organisation survey</option>
            <option value="multi_rater">Multi-rater (360)</option>
            <option value="individual">Individual</option>
            <option value="external_instrument">External instrument</option>
          </select>
        </label>

        <label className="field mt-3">
          <b>Response Mode</b>
          <select
            className="input"
            value={responseMode}
            onChange={(e) => setResponseMode(e.target.value)}
          >
            <option value="identified">Identified (names collected)</option>
            <option value="anonymous">Anonymous</option>
          </select>
        </label>

        <label className="field mt-3">
          <b>Minimum Group Size</b>
          <input
            className="input"
            type="number"
            value={minimumGroupSize}
            onChange={(e) => setMinimumGroupSize(parseInt(e.target.value) || 1)}
            min="1"
            required
          />
          <small style={{ color: "var(--muted)", display: "block", marginTop: "0.25rem" }}>
            Minimum respondents before results can be shown
          </small>
        </label>

        <label className="field mt-3">
          <b>Description (optional)</b>
          <textarea
            className="input"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            placeholder="Template purpose and guidelines"
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
          disabled={busy || !title.trim() || !slug.trim()}
        >
          {busy ? "Creating…" : "Create template"}
        </button>
      </form>
    </div>
  );
}
