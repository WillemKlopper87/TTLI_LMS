"use client";

/**
 * `/admin/cohorts/new` — schedule a cohort (a run of a learning path or
 * course for an organisation). `POST /cohorts` requires exactly one of
 * learning_path_id/course_id (XOR, enforced server-side), then straight
 * back to `/admin/cohorts` — there's no cohort detail view in this slice
 * (the router has no GET /cohorts/{id} yet), so there's nowhere else to go.
 */

import { useState } from "react";
import { useRouter } from "next/navigation";

import { readError, sendJson } from "../../courses/wizard-api";

export default function NewCohortPage() {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [target, setTarget] = useState<"learning_path" | "course">("learning_path");
  const [learningPathId, setLearningPathId] = useState("");
  const [courseId, setCourseId] = useState("");
  const [organisationId, setOrganisationId] = useState("");
  const [startsAt, setStartsAt] = useState("");
  const [endsAt, setEndsAt] = useState("");
  const [capacity, setCapacity] = useState("");
  const [leadFacilitatorId, setLeadFacilitatorId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const targetId = target === "learning_path" ? learningPathId : courseId;

  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (!title.trim() || !targetId.trim()) return;
    setBusy(true);
    setError(null);
    const body: Record<string, unknown> = {
      title: title.trim(),
      organisation_id: organisationId.trim() || null,
      starts_at: startsAt || null,
      ends_at: endsAt || null,
      capacity: capacity ? parseInt(capacity, 10) : null,
      lead_facilitator_id: leadFacilitatorId.trim() || null,
    };
    if (target === "learning_path") {
      body.learning_path_id = learningPathId.trim();
    } else {
      body.course_id = courseId.trim();
    }
    const resp = await sendJson("/api/bff/cohorts", "POST", body);
    setBusy(false);
    if (!resp.ok) {
      setError(await readError(resp, "The cohort could not be created."));
      return;
    }
    router.push("/admin/cohorts");
  }

  return (
    <div className="dash">
      <div className="dash-top">
        <div>
          <p className="eyebrow">Teach</p>
          <h1>New cohort</h1>
        </div>
        <a className="btn btn--ghost" href="/admin/cohorts">
          All cohorts
        </a>
      </div>

      <form onSubmit={(e) => void create(e)} className="card p-4" style={{ maxWidth: "32rem" }}>
        <label className="field">
          <b>Title</b>
          <input
            className="input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. Leadership Fundamentals — Q1 cohort"
            required
            autoFocus
          />
        </label>

        <label className="field mt-3">
          <b>Runs</b>
          <select
            className="input"
            value={target}
            onChange={(e) => setTarget(e.target.value as "learning_path" | "course")}
          >
            <option value="learning_path">A learning path</option>
            <option value="course">A course</option>
          </select>
        </label>

        {target === "learning_path" ? (
          <label className="field mt-3">
            <b>Learning path ID</b>
            <input
              className="input"
              value={learningPathId}
              onChange={(e) => setLearningPathId(e.target.value)}
              placeholder="UUID of the learning path"
              required
            />
          </label>
        ) : (
          <label className="field mt-3">
            <b>Course ID</b>
            <input
              className="input"
              value={courseId}
              onChange={(e) => setCourseId(e.target.value)}
              placeholder="UUID of the course"
              required
            />
          </label>
        )}

        <label className="field mt-3">
          <b>Organisation ID</b>
          <input
            className="input"
            value={organisationId}
            onChange={(e) => setOrganisationId(e.target.value)}
            placeholder="UUID of the organisation running this cohort"
          />
        </label>

        <label className="field mt-3">
          <b>Starts at</b>
          <input
            className="input"
            type="datetime-local"
            value={startsAt}
            onChange={(e) => setStartsAt(e.target.value)}
          />
        </label>

        <label className="field mt-3">
          <b>Ends at</b>
          <input
            className="input"
            type="datetime-local"
            value={endsAt}
            onChange={(e) => setEndsAt(e.target.value)}
          />
        </label>

        <label className="field mt-3">
          <b>Capacity</b>
          <input
            className="input"
            type="number"
            min={1}
            value={capacity}
            onChange={(e) => setCapacity(e.target.value)}
            placeholder="Optional seat limit"
          />
        </label>

        <label className="field mt-3">
          <b>Lead facilitator ID</b>
          <input
            className="input"
            value={leadFacilitatorId}
            onChange={(e) => setLeadFacilitatorId(e.target.value)}
            placeholder="Optional — UUID of the facilitator"
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
          disabled={busy || !title.trim() || !targetId.trim()}
        >
          {busy ? "Creating…" : "Create cohort"}
        </button>
      </form>
    </div>
  );
}
