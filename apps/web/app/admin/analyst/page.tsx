"use client";

/**
 * `/admin/analyst` — assign/revoke analyst engagements on assessment
 * instances. Backed by GET/POST /assessments/engagements and
 * POST /assessments/engagements/{id}/revoke, all admin-only
 * (assessment:run).
 */

import Link from "next/link";
import { useEffect, useState } from "react";

import { useAdmin } from "../admin-context";
import { authedFetch, readError, sendJson } from "../courses/wizard-api";

const ASSESSMENT_RUN = "assessment:run";
const REPORT_SUBMIT = "report:submit";
const REPORT_REVIEW = "report:review";

interface EngagementItem {
  id: string;
  instance_id: string | null;
  analyst_user_id: string;
  starts_at: string;
  ends_at: string;
  revoked_at: string | null;
  purpose: string;
  created_at: string;
}

export default function AnalystEngagementsScreen() {
  const { me } = useAdmin();
  const canManage = me.permissions.includes(ASSESSMENT_RUN);
  const canSeeReports =
    canManage || me.permissions.includes(REPORT_SUBMIT) || me.permissions.includes(REPORT_REVIEW);

  const [engagements, setEngagements] = useState<EngagementItem[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [revokeBusyId, setRevokeBusyId] = useState<string | null>(null);
  const [revokeError, setRevokeError] = useState<string | null>(null);

  const [analystUserId, setAnalystUserId] = useState("");
  const [instanceId, setInstanceId] = useState("");
  const [startsAt, setStartsAt] = useState("");
  const [endsAt, setEndsAt] = useState("");
  const [purpose, setPurpose] = useState("");
  const [assignBusy, setAssignBusy] = useState(false);
  const [assignError, setAssignError] = useState<string | null>(null);

  async function loadEngagements() {
    const resp = await authedFetch("/api/bff/assessments/engagements");
    if (!resp.ok) {
      setListError(await readError(resp, "Engagements could not be loaded."));
      setEngagements([]);
      return;
    }
    setEngagements((await resp.json()).items);
    setListError(null);
  }

  useEffect(() => {
    if (!canManage) return;
    void (async () => {
      await loadEngagements();
    })();
  }, [canManage]);

  async function assign(event: React.FormEvent) {
    event.preventDefault();
    if (!analystUserId.trim() || !instanceId.trim() || !startsAt || !endsAt || !purpose.trim()) {
      return;
    }
    setAssignBusy(true);
    setAssignError(null);
    const resp = await sendJson("/api/bff/assessments/engagements", "POST", {
      analyst_user_id: analystUserId.trim(),
      instance_id: instanceId.trim(),
      starts_at: startsAt,
      ends_at: endsAt,
      purpose: purpose.trim(),
    });
    setAssignBusy(false);
    if (!resp.ok) {
      setAssignError(await readError(resp, "The engagement could not be assigned."));
      return;
    }
    setAnalystUserId("");
    setInstanceId("");
    setStartsAt("");
    setEndsAt("");
    setPurpose("");
    await loadEngagements();
  }

  async function revoke(engagementId: string) {
    setRevokeBusyId(engagementId);
    setRevokeError(null);
    const resp = await sendJson(`/api/bff/assessments/engagements/${engagementId}/revoke`, "POST", {});
    setRevokeBusyId(null);
    if (!resp.ok) {
      setRevokeError(await readError(resp, "The engagement could not be revoked."));
      return;
    }
    await loadEngagements();
  }

  if (!canManage) {
    return (
      <div className="dash">
        <div className="dash-top">
          <div>
            <p className="eyebrow">Assess</p>
            <h1>Analyst engagements</h1>
          </div>
          {canSeeReports ? (
            <Link className="btn btn--ghost" href="/admin/analyst/reports">
              Reports
            </Link>
          ) : null}
        </div>
        <div className="callout callout--warn" role="alert">
          <p style={{ fontSize: "0.8125rem" }}>
            {canSeeReports
              ? "You do not have permission to assign or revoke analyst engagements — use Reports to author or review your reports."
              : "You do not have permission to manage analyst engagements."}
          </p>
        </div>
      </div>
    );
  }

  const activeCount = (engagements ?? []).filter((e) => e.revoked_at === null).length;

  return (
    <div className="dash">
      <div className="dash-top">
        <div>
          <p className="eyebrow">Assess</p>
          <h1>Analyst engagements</h1>
        </div>
        <Link className="btn btn--ghost" href="/admin/analyst/reports">
          Reports
        </Link>
      </div>

      <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
        An engagement grants an analyst time-windowed access to a closed
        assessment instance. Only one active engagement per analyst/instance
        pair is allowed.
      </p>

      {listError ? (
        <div className="callout callout--warn mt-4" role="alert">
          <p style={{ fontSize: "0.8125rem" }}>{listError}</p>
        </div>
      ) : null}

      <dl className="stats mt-4">
        <div className="stat">
          <dt>Engagements</dt>
          <dd>{engagements?.length ?? "—"}</dd>
        </div>
        <div className="stat">
          <dt>Active</dt>
          <dd>{engagements === null ? "—" : activeCount}</dd>
        </div>
      </dl>

      {revokeError ? (
        <div className="callout callout--warn" role="alert">
          <p style={{ fontSize: "0.8125rem" }}>{revokeError}</p>
        </div>
      ) : null}

      <div className="tablewrap">
        <table>
          <thead>
            <tr>
              <th scope="col">Analyst</th>
              <th scope="col">Instance</th>
              <th scope="col">Window</th>
              <th scope="col">Status</th>
              <th scope="col" />
            </tr>
          </thead>
          <tbody>
            {engagements === null ? (
              <tr>
                <td colSpan={5} style={{ color: "var(--faint)" }}>
                  Loading…
                </td>
              </tr>
            ) : null}
            {engagements !== null && engagements.length === 0 ? (
              <tr>
                <td colSpan={5} style={{ color: "var(--muted)" }}>
                  No engagements yet.
                </td>
              </tr>
            ) : null}
            {(engagements ?? []).map((engagement) => (
              <tr key={engagement.id}>
                <td className="mono" style={{ fontSize: "0.8125rem" }}>
                  {engagement.analyst_user_id}
                </td>
                <td className="mono" style={{ fontSize: "0.8125rem" }}>
                  {engagement.instance_id ?? "—"}
                </td>
                <td style={{ fontSize: "0.8125rem" }}>
                  {new Date(engagement.starts_at).toLocaleDateString()} –{" "}
                  {new Date(engagement.ends_at).toLocaleDateString()}
                </td>
                <td>
                  <span className={`tag ${engagement.revoked_at ? "tag--mute" : "tag--live"}`}>
                    {engagement.revoked_at ? "Revoked" : "Active"}
                  </span>
                </td>
                <td>
                  {engagement.revoked_at === null ? (
                    <button
                      type="button"
                      className="btn btn--ghost"
                      disabled={revokeBusyId === engagement.id}
                      onClick={() => void revoke(engagement.id)}
                    >
                      {revokeBusyId === engagement.id ? "Revoking…" : "Revoke"}
                    </button>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card p-4 mt-6" style={{ maxWidth: "32rem" }}>
        <b style={{ fontSize: "0.875rem" }}>Assign engagement</b>
        <form onSubmit={(e) => void assign(e)} className="mt-3">
          <label className="field">
            <b>Analyst user ID</b>
            <input
              className="input"
              value={analystUserId}
              onChange={(e) => setAnalystUserId(e.target.value)}
              placeholder="UUID of the analyst"
              required
            />
          </label>
          <label className="field mt-3">
            <b>Assessment instance ID</b>
            <input
              className="input"
              value={instanceId}
              onChange={(e) => setInstanceId(e.target.value)}
              placeholder="UUID of the closed instance"
              required
            />
          </label>
          <label className="field mt-3">
            <b>Starts at</b>
            <input
              className="input"
              type="datetime-local"
              value={startsAt}
              onChange={(e) => setStartsAt(e.target.value)}
              required
            />
          </label>
          <label className="field mt-3">
            <b>Ends at</b>
            <input
              className="input"
              type="datetime-local"
              value={endsAt}
              onChange={(e) => setEndsAt(e.target.value)}
              required
            />
          </label>
          <label className="field mt-3">
            <b>Purpose</b>
            <textarea
              className="input"
              value={purpose}
              onChange={(e) => setPurpose(e.target.value)}
              rows={2}
              placeholder="Reason for this engagement"
              required
            />
          </label>
          {assignError ? (
            <p role="alert" style={{ fontSize: "0.8125rem", color: "var(--stop)" }} className="mt-2">
              {assignError}
            </p>
          ) : null}
          <button
            type="submit"
            className="btn btn--primary mt-3"
            disabled={
              assignBusy ||
              !analystUserId.trim() ||
              !instanceId.trim() ||
              !startsAt ||
              !endsAt ||
              !purpose.trim()
            }
          >
            {assignBusy ? "Assigning…" : "Assign engagement"}
          </button>
        </form>
      </div>
    </div>
  );
}
