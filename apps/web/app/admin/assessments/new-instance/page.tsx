"use client";

/**
 * `/admin/assessments/new-instance` — create a new assessment instance.
 * POST /assessment-platform/instances with InstanceCreateRequest.
 * Requires assessment:run permission.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { authedFetch, readError, sendJson } from "../../courses/wizard-api";

interface TemplateItem {
  id: string;
  slug: string;
  title: string;
}

export default function NewInstancePage() {
  const router = useRouter();
  const [templates, setTemplates] = useState<TemplateItem[] | null>(null);
  const [templateId, setTemplateId] = useState("");
  const [organisationId, setOrganisationId] = useState("");
  const [title, setTitle] = useState("");
  const [evaluationRole, setEvaluationRole] = useState("standalone");
  const [levelsEnabled, setLevelsEnabled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadTemplates() {
      const resp = await authedFetch("/api/bff/assessment-platform/templates");
      if (!resp.ok) {
        setError(await readError(resp, "Could not load templates."));
        setTemplates([]);
        return;
      }
      setTemplates((await resp.json()).items);
    }
    void loadTemplates();
  }, []);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (!title.trim() || !templateId || !organisationId) return;
    setBusy(true);
    setError(null);
    const resp = await sendJson("/api/bff/assessment-platform/instances", "POST", {
      template_id: templateId,
      organisation_id: organisationId,
      title: title.trim(),
      evaluation_role: evaluationRole,
      levels_enabled: levelsEnabled,
    });
    setBusy(false);
    if (!resp.ok) {
      setError(await readError(resp, "The instance could not be created."));
      return;
    }
    router.push(`/admin/assessments`);
  }

  return (
    <div className="dash">
      <div className="dash-top">
        <div>
          <p className="eyebrow">Instance setup</p>
          <h1>New assessment instance</h1>
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
            placeholder="e.g. Q1 2024 Leadership Assessment - Marketing Dept"
            required
            autoFocus
          />
          <small style={{ color: "var(--muted)", display: "block", marginTop: "0.25rem" }}>
            Name for this assessment instance
          </small>
        </label>

        <label className="field mt-3">
          <b>Template</b>
          <select
            className="input"
            value={templateId}
            onChange={(e) => setTemplateId(e.target.value)}
            required
          >
            <option value="">Select a template…</option>
            {(templates ?? []).map((t) => (
              <option key={t.id} value={t.id}>
                {t.title} ({t.slug})
              </option>
            ))}
          </select>
          {templates === null && (
            <small style={{ color: "var(--muted)", display: "block", marginTop: "0.25rem" }}>
              Loading templates…
            </small>
          )}
        </label>

        <label className="field mt-3">
          <b>Organisation ID</b>
          <input
            className="input"
            value={organisationId}
            onChange={(e) => setOrganisationId(e.target.value)}
            placeholder="UUID of the target organisation"
            required
          />
          <small style={{ color: "var(--muted)", display: "block", marginTop: "0.25rem" }}>
            UUID of the organisation running this assessment
          </small>
        </label>

        <label className="field mt-3">
          <b>Evaluation Role</b>
          <select
            className="input"
            value={evaluationRole}
            onChange={(e) => setEvaluationRole(e.target.value)}
          >
            <option value="standalone">Standalone</option>
            <option value="pre">Pre-assessment</option>
            <option value="post">Post-assessment</option>
          </select>
        </label>

        <label className="field mt-3" style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <input
            type="checkbox"
            checked={levelsEnabled}
            onChange={(e) => setLevelsEnabled(e.target.checked)}
          />
          <b>Enable levels</b>
        </label>

        {error ? (
          <p role="alert" style={{ fontSize: "0.8125rem", color: "var(--stop)" }} className="mt-2">
            {error}
          </p>
        ) : null}

        <button
          type="submit"
          className="btn btn--primary mt-3"
          disabled={busy || !title.trim() || !templateId || !organisationId}
        >
          {busy ? "Creating…" : "Create instance"}
        </button>
      </form>
    </div>
  );
}
