"use client";

/**
 * `/admin/analyst/reports/{reportId}` — a report's detail view plus its
 * state-machine actions (submit/return/resubmit/accept/withdraw/release).
 * Each action button is gated on both the permission the router checks
 * AND the report's current status, so a button that would just 400 never
 * renders enabled.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { useAdmin } from "../../../admin-context";
import { authedFetch, readError, sendJson } from "../../../courses/wizard-api";

const REPORT_SUBMIT = "report:submit";
const REPORT_REVIEW = "report:review";

interface ReportAttachment {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  uploaded_at: string;
  scanned_at: string | null;
  scan_result: string | null;
}

interface ReportView {
  id: string;
  engagement_id: string;
  instance_id: string;
  author_user_id: string;
  status: string;
  title: string;
  summary: string | null;
  version: number;
  submitted_at: string | null;
  decided_at: string | null;
  decided_by: string | null;
  decision_note: string | null;
  released_at: string | null;
  created_at: string;
  updated_at: string;
  attachments: ReportAttachment[];
}

const STATUS_TAG: Record<string, string> = {
  draft: "tag--mute",
  submitted: "tag--live",
  returned: "tag--warn",
  accepted: "tag--done",
  withdrawn: "tag--mute",
};

export default function ReportDetailPage() {
  const params = useParams<{ reportId: string }>();
  const reportId = params.reportId;
  const { me } = useAdmin();
  const canSubmit = me.permissions.includes(REPORT_SUBMIT);
  const canReview = me.permissions.includes(REPORT_REVIEW);

  const [report, setReport] = useState<ReportView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [decisionNote, setDecisionNote] = useState("");

  const [summaryDraft, setSummaryDraft] = useState("");
  const [summaryBusy, setSummaryBusy] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);

  const [uploadBusy, setUploadBusy] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  async function load() {
    const resp = await authedFetch(`/api/bff/reports/${reportId}`);
    if (!resp.ok) {
      setError(await readError(resp, "This report could not be loaded."));
      return;
    }
    const body = (await resp.json()) as ReportView;
    setReport(body);
    setSummaryDraft(body.summary ?? "");
    setError(null);
  }

  useEffect(() => {
    void (async () => {
      await load();
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reportId]);

  async function runAction(path: string, body: Record<string, unknown> = {}) {
    setBusy(true);
    setActionError(null);
    const resp = await sendJson(`/api/bff/reports/${reportId}/${path}`, "POST", body);
    setBusy(false);
    if (!resp.ok) {
      setActionError(await readError(resp, "That action could not be completed."));
      return;
    }
    setDecisionNote("");
    await load();
  }

  const isAuthor = report !== null && report.author_user_id === me.user_id;
  const canEditNow =
    canSubmit && isAuthor && (report?.status === "draft" || report?.status === "returned");

  async function saveSummary(event: React.FormEvent) {
    event.preventDefault();
    if (!summaryDraft.trim()) return;
    setSummaryBusy(true);
    setSummaryError(null);
    const resp = await sendJson(`/api/bff/reports/${reportId}`, "PATCH", {
      summary: summaryDraft.trim(),
    });
    setSummaryBusy(false);
    if (!resp.ok) {
      setSummaryError(await readError(resp, "The summary could not be saved."));
      return;
    }
    await load();
  }

  async function uploadAttachment(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setUploadBusy(true);
    setUploadError(null);
    const form = new FormData();
    form.append("file", file);
    const resp = await authedFetch(`/api/bff/reports/${reportId}/attachments`, {
      method: "POST",
      body: form,
    });
    setUploadBusy(false);
    if (!resp.ok) {
      setUploadError(await readError(resp, "The file could not be uploaded."));
      return;
    }
    await load();
  }

  if (error) {
    return (
      <div className="dash">
        <div className="dash-top">
          <div>
            <p className="eyebrow">Assess</p>
            <h1>Report</h1>
          </div>
          <Link className="btn btn--ghost" href="/admin/analyst/reports">
            Back
          </Link>
        </div>
        <div className="callout callout--warn" role="alert">
          <p style={{ fontSize: "0.8125rem" }}>{error}</p>
        </div>
      </div>
    );
  }

  if (report === null) {
    return (
      <div className="dash">
        <p style={{ color: "var(--faint)" }}>Loading…</p>
      </div>
    );
  }

  const canSubmitNow = canSubmit && isAuthor && report.status === "draft";
  const canResubmitNow = canSubmit && isAuthor && report.status === "returned";
  const canWithdrawNow =
    canSubmit && isAuthor && (report.status === "draft" || report.status === "returned");
  const canReturnNow = canReview && report.status === "submitted";
  const canAcceptNow = canReview && report.status === "submitted";
  const canReleaseNow = canReview && report.status === "accepted";

  return (
    <div className="dash">
      <div className="dash-top">
        <div>
          <p className="eyebrow">Assess</p>
          <h1>{report.title}</h1>
        </div>
        <Link className="btn btn--ghost" href="/admin/analyst/reports">
          Back
        </Link>
      </div>

      <div className="card p-4">
        <dl className="flex flex-col gap-2">
          <div className="flex justify-between">
            <dt style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>Status</dt>
            <dd>
              <span className={`tag ${STATUS_TAG[report.status] ?? "tag--mute"}`}>
                {report.status}
              </span>
            </dd>
          </div>
          <div className="flex justify-between">
            <dt style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>Version</dt>
            <dd style={{ fontSize: "0.8125rem" }}>{report.version}</dd>
          </div>
          <div className="flex justify-between">
            <dt style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>Engagement</dt>
            <dd className="mono" style={{ fontSize: "0.8125rem" }}>{report.engagement_id}</dd>
          </div>
          {report.summary && !canEditNow ? (
            <div className="flex justify-between">
              <dt style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>Summary</dt>
              <dd style={{ fontSize: "0.8125rem" }}>{report.summary}</dd>
            </div>
          ) : null}
          {report.decision_note ? (
            <div className="flex justify-between">
              <dt style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>Decision note</dt>
              <dd style={{ fontSize: "0.8125rem" }}>{report.decision_note}</dd>
            </div>
          ) : null}
        </dl>
      </div>

      {canEditNow ? (
        <div className="card p-4 mt-4" style={{ maxWidth: "32rem" }}>
          <b style={{ fontSize: "0.875rem" }}>Summary</b>
          <form onSubmit={(e) => void saveSummary(e)} className="mt-3">
            <textarea
              className="input"
              value={summaryDraft}
              onChange={(e) => setSummaryDraft(e.target.value)}
              rows={5}
              placeholder="Write the report summary here — a non-empty summary or at least one clean attachment is required to submit."
            />
            {summaryError ? (
              <p role="alert" style={{ fontSize: "0.8125rem", color: "var(--stop)" }} className="mt-2">
                {summaryError}
              </p>
            ) : null}
            <button
              type="submit"
              className="btn btn--primary mt-3"
              disabled={summaryBusy || !summaryDraft.trim() || summaryDraft === (report.summary ?? "")}
            >
              {summaryBusy ? "Saving…" : "Save summary"}
            </button>
          </form>
        </div>
      ) : null}

      <div className="card p-4 mt-4" style={{ maxWidth: "32rem" }}>
        <b style={{ fontSize: "0.875rem" }}>Attachments</b>
        {report.attachments.length === 0 ? (
          <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }} className="mt-2">
            No attachments yet.
          </p>
        ) : (
          <ul className="mt-2 flex flex-col gap-1">
            {report.attachments.map((a) => (
              <li key={a.id} style={{ fontSize: "0.8125rem" }} className="flex justify-between">
                <span>{a.filename}</span>
                <span style={{ color: "var(--muted)" }}>
                  {a.scan_result === "clean" ? "Clean" : (a.scan_result ?? "Pending scan")}
                </span>
              </li>
            ))}
          </ul>
        )}
        {canEditNow ? (
          <div className="mt-3">
            <input
              type="file"
              accept=".pdf,.ppt,.pptx"
              disabled={uploadBusy}
              onChange={(e) => void uploadAttachment(e)}
            />
            {uploadBusy ? (
              <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }} className="mt-2">
                Uploading and scanning…
              </p>
            ) : null}
            {uploadError ? (
              <p role="alert" style={{ fontSize: "0.8125rem", color: "var(--stop)" }} className="mt-2">
                {uploadError}
              </p>
            ) : null}
          </div>
        ) : null}
      </div>

      {actionError ? (
        <div className="callout callout--warn mt-4" role="alert">
          <p style={{ fontSize: "0.8125rem" }}>{actionError}</p>
        </div>
      ) : null}

      <div className="mt-4 flex flex-wrap gap-2">
        {canSubmitNow ? (
          <button
            type="button"
            className="btn btn--primary"
            disabled={busy}
            onClick={() => void runAction("submit")}
          >
            Submit
          </button>
        ) : null}
        {canResubmitNow ? (
          <button
            type="button"
            className="btn btn--primary"
            disabled={busy}
            onClick={() => void runAction("resubmit")}
          >
            Resubmit
          </button>
        ) : null}
        {canWithdrawNow ? (
          <button
            type="button"
            className="btn btn--ghost"
            disabled={busy}
            onClick={() => void runAction("withdraw")}
          >
            Withdraw
          </button>
        ) : null}
        {canAcceptNow ? (
          <button
            type="button"
            className="btn btn--primary"
            disabled={busy}
            onClick={() => void runAction("accept")}
          >
            Accept
          </button>
        ) : null}
        {canReleaseNow ? (
          <button
            type="button"
            className="btn btn--primary"
            disabled={busy}
            onClick={() => void runAction("release")}
          >
            Release
          </button>
        ) : null}
      </div>

      {canReturnNow ? (
        <div className="card p-4 mt-4" style={{ maxWidth: "32rem" }}>
          <b style={{ fontSize: "0.875rem" }}>Return to analyst</b>
          <form
            className="mt-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (!decisionNote.trim()) return;
              void runAction("return", { decision_note: decisionNote.trim() });
            }}
          >
            <label className="field">
              <b>Decision note</b>
              <textarea
                className="input"
                value={decisionNote}
                onChange={(e) => setDecisionNote(e.target.value)}
                rows={3}
                placeholder="Why is this report being returned?"
                required
              />
            </label>
            <button
              type="submit"
              className="btn btn--primary mt-3"
              disabled={busy || !decisionNote.trim()}
            >
              Return
            </button>
          </form>
        </div>
      ) : null}
    </div>
  );
}
