"use client";

/**
 * `/admin/analyst/reports` — reports list (GET /reports), scoped to the
 * caller's own reports unless they hold report:review/assessment:run, the
 * same author-vs-reviewer split GET /reports/{id} enforces. Plus a
 * "create draft" form.
 */

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { useAdmin } from "../../admin-context";
import { authedFetch, readError, sendJson } from "../../courses/wizard-api";

const REPORT_SUBMIT = "report:submit";
const REPORT_REVIEW = "report:review";
const ASSESSMENT_ANALYSE = "assessment:analyse";
const ASSESSMENT_RUN = "assessment:run";

interface ReportItem {
  id: string;
  title: string;
  status: string;
  author_user_id: string;
  version: number;
  created_at: string;
}

const STATUS_TAG: Record<string, string> = {
  draft: "tag--mute",
  submitted: "tag--live",
  returned: "tag--warn",
  accepted: "tag--done",
  withdrawn: "tag--mute",
};

export default function AnalystReportsScreen() {
  const router = useRouter();
  const { me } = useAdmin();
  const canCreate = me.permissions.includes(REPORT_SUBMIT);
  const canView =
    me.permissions.includes(REPORT_SUBMIT) ||
    me.permissions.includes(REPORT_REVIEW) ||
    me.permissions.includes(ASSESSMENT_ANALYSE) ||
    me.permissions.includes(ASSESSMENT_RUN);

  const [reports, setReports] = useState<ReportItem[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);

  const [engagementId, setEngagementId] = useState("");
  const [title, setTitle] = useState("");
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  async function loadReports() {
    const resp = await authedFetch("/api/bff/reports");
    if (!resp.ok) {
      setListError(await readError(resp, "Reports could not be loaded."));
      setReports([]);
      return;
    }
    setReports((await resp.json()).items);
    setListError(null);
  }

  useEffect(() => {
    if (!canView) return;
    void (async () => {
      await loadReports();
    })();
  }, [canView]);

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

  const isReviewer =
    me.permissions.includes(REPORT_REVIEW) || me.permissions.includes(ASSESSMENT_RUN);

  return (
    <div className="dash">
      <div className="dash-top">
        <div>
          <p className="eyebrow">Assess</p>
          <h1>Reports</h1>
        </div>
        <Link className="btn btn--ghost" href="/admin/analyst">
          Engagements
        </Link>
      </div>

      <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
        {isReviewer
          ? "Every report in this tenant."
          : "Reports you authored. Reviewers and admins see every report."}
      </p>

      {listError ? (
        <div className="callout callout--warn mt-4" role="alert">
          <p style={{ fontSize: "0.8125rem" }}>{listError}</p>
        </div>
      ) : null}

      <div className="tablewrap mt-4">
        <table>
          <thead>
            <tr>
              <th scope="col">Title</th>
              <th scope="col">Status</th>
              <th scope="col">Version</th>
              <th scope="col" />
            </tr>
          </thead>
          <tbody>
            {reports === null ? (
              <tr>
                <td colSpan={4} style={{ color: "var(--faint)" }}>
                  Loading…
                </td>
              </tr>
            ) : null}
            {reports !== null && reports.length === 0 ? (
              <tr>
                <td colSpan={4} style={{ color: "var(--muted)" }}>
                  No reports yet.
                </td>
              </tr>
            ) : null}
            {(reports ?? []).map((report) => (
              <tr key={report.id}>
                <td>
                  <b>{report.title}</b>
                </td>
                <td>
                  <span className={`tag ${STATUS_TAG[report.status] ?? "tag--mute"}`}>
                    {report.status}
                  </span>
                </td>
                <td style={{ fontSize: "0.8125rem" }}>{report.version}</td>
                <td>
                  <Link className="btn btn--ghost" href={`/admin/analyst/reports/${report.id}`}>
                    Open
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {canCreate ? (
        <div className="card p-4 mt-6" style={{ maxWidth: "32rem" }}>
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
