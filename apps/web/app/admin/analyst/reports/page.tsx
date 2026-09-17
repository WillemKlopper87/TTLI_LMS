"use client";

/**
 * `/admin/analyst/reports` — there is no GET /reports list endpoint in
 * this branch's backend (only GET /reports/{id}), so this screen is a
 * "look up a report by ID" form plus a "create draft" form, not a
 * managed list.
 */

import { useState } from "react";
import { useRouter } from "next/navigation";

import { useAdmin } from "../../admin-context";
import { readError, sendJson } from "../../courses/wizard-api";

const REPORT_SUBMIT = "report:submit";
const REPORT_REVIEW = "report:review";
const ASSESSMENT_ANALYSE = "assessment:analyse";
const ASSESSMENT_RUN = "assessment:run";

export default function AnalystReportsScreen() {
  const router = useRouter();
  const { me } = useAdmin();
  const canCreate = me.permissions.includes(REPORT_SUBMIT);
  const canView =
    me.permissions.includes(REPORT_SUBMIT) ||
    me.permissions.includes(REPORT_REVIEW) ||
    me.permissions.includes(ASSESSMENT_ANALYSE) ||
    me.permissions.includes(ASSESSMENT_RUN);

  const [lookupId, setLookupId] = useState("");

  const [engagementId, setEngagementId] = useState("");
  const [title, setTitle] = useState("");
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  function lookup(event: React.FormEvent) {
    event.preventDefault();
    if (!lookupId.trim()) return;
    router.push(`/admin/analyst/reports/${lookupId.trim()}`);
  }

  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (!engagementId.trim() || !title.trim()) return;
    setCreateBusy(true);
    setCreateError(null);
    const resp = await sendJson("/api/bff/reports", "POST", {
      engagement_id: engagementId.trim(),
      title: title.trim(),
    });
    setCreateBusy(false);
    if (!resp.ok) {
      setCreateError(await readError(resp, "The report could not be created."));
      return;
    }
    const report = await resp.json();
    router.push(`/admin/analyst/reports/${report.id}`);
  }

  if (!canView) {
    return (
      <div className="dash">
        <div className="dash-top">
          <div>
            <p className="eyebrow">Assess</p>
            <h1>Reports</h1>
          </div>
        </div>
        <div className="callout callout--warn" role="alert">
          <p style={{ fontSize: "0.8125rem" }}>You do not have permission to view reports.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="dash">
      <div className="dash-top">
        <div>
          <p className="eyebrow">Assess</p>
          <h1>Reports</h1>
        </div>
        <a className="btn btn--ghost" href="/admin/analyst">
          Engagements
        </a>
      </div>

      <div className="card p-4 mt-4" style={{ maxWidth: "32rem" }}>
        <b style={{ fontSize: "0.875rem" }}>Open a report</b>
        <form onSubmit={lookup} className="mt-3">
          <label className="field">
            <b>Report ID</b>
            <input
              className="input"
              value={lookupId}
              onChange={(e) => setLookupId(e.target.value)}
              placeholder="UUID of the report"
              required
            />
          </label>
          <button type="submit" className="btn btn--primary mt-3" disabled={!lookupId.trim()}>
            Open
          </button>
        </form>
      </div>

      {canCreate ? (
        <div className="card p-4 mt-4" style={{ maxWidth: "32rem" }}>
          <b style={{ fontSize: "0.875rem" }}>Create draft report</b>
          <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
            One open draft is allowed per engagement.
          </p>
          <form onSubmit={(e) => void create(e)} className="mt-3">
            <label className="field">
              <b>Engagement ID</b>
              <input
                className="input"
                value={engagementId}
                onChange={(e) => setEngagementId(e.target.value)}
                placeholder="UUID of your engagement"
                required
              />
            </label>
            <label className="field mt-3">
              <b>Title</b>
              <input
                className="input"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Report title"
                required
              />
            </label>
            {createError ? (
              <p role="alert" style={{ fontSize: "0.8125rem", color: "var(--stop)" }} className="mt-2">
                {createError}
              </p>
            ) : null}
            <button
              type="submit"
              className="btn btn--primary mt-3"
              disabled={createBusy || !engagementId.trim() || !title.trim()}
            >
              {createBusy ? "Creating…" : "Create draft"}
            </button>
          </form>
        </div>
      ) : null}
    </div>
  );
}
