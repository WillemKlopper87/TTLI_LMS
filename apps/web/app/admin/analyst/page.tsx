"use client";

/**
 * `/admin/analyst` — assign/revoke analyst engagements on assessment
 * instances. There is no GET /assessments/engagements list endpoint in
 * this branch's backend, so this screen is a standalone "assign" form
 * plus a "revoke by ID" form rather than a managed list — the same
 * shape docs/superpowers/specs/2026-09-11-analyst-workspace-design.md's
 * first slice takes on the backend side (create/revoke, no listing yet).
 */

import Link from "next/link";
import { useState } from "react";

import { useAdmin } from "../admin-context";
import { readError, sendJson } from "../courses/wizard-api";

const ASSESSMENT_RUN = "assessment:run";

export default function AnalystEngagementsScreen() {
  const { me } = useAdmin();
  const canManage = me.permissions.includes(ASSESSMENT_RUN);

  const [analystUserId, setAnalystUserId] = useState("");
  const [instanceId, setInstanceId] = useState("");
  const [startsAt, setStartsAt] = useState("");
  const [endsAt, setEndsAt] = useState("");
  const [purpose, setPurpose] = useState("");
  const [assignBusy, setAssignBusy] = useState(false);
  const [assignError, setAssignError] = useState<string | null>(null);
  const [assignedId, setAssignedId] = useState<string | null>(null);

  const [revokeId, setRevokeId] = useState("");
  const [revokeBusy, setRevokeBusy] = useState(false);
  const [revokeError, setRevokeError] = useState<string | null>(null);
  const [revoked, setRevoked] = useState(false);

  async function assign(event: React.FormEvent) {
    event.preventDefault();
    if (!analystUserId.trim() || !instanceId.trim() || !startsAt || !endsAt || !purpose.trim()) {
      return;
    }
    setAssignBusy(true);
    setAssignError(null);
    setAssignedId(null);
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
    const engagement = await resp.json();
    setAssignedId(engagement.id);
    setAnalystUserId("");
    setInstanceId("");
    setStartsAt("");
    setEndsAt("");
    setPurpose("");
  }

  async function revoke(event: React.FormEvent) {
    event.preventDefault();
    if (!revokeId.trim()) return;
    setRevokeBusy(true);
    setRevokeError(null);
    setRevoked(false);
    const resp = await sendJson(`/api/bff/assessments/engagements/${revokeId.trim()}/revoke`, "POST", {});
    setRevokeBusy(false);
    if (!resp.ok) {
      setRevokeError(await readError(resp, "The engagement could not be revoked."));
      return;
    }
    setRevoked(true);
    setRevokeId("");
  }

  if (!canManage) {
    return (
      <div className="dash">
        <div className="dash-top">
          <div>
            <p className="eyebrow">Assess</p>
            <h1>Analyst engagements</h1>
          </div>
        </div>
        <div className="callout callout--warn" role="alert">
          <p style={{ fontSize: "0.8125rem" }}>
            You do not have permission to manage analyst engagements.
          </p>
        </div>
      </div>
    );
  }

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

      <div className="card p-4 mt-4" style={{ maxWidth: "32rem" }}>
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
          {assignedId ? (
            <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }} className="mt-2">
              Engagement assigned (ID: {assignedId}).
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

      <div className="card p-4 mt-4" style={{ maxWidth: "32rem" }}>
        <b style={{ fontSize: "0.875rem" }}>Revoke engagement</b>
        <form onSubmit={(e) => void revoke(e)} className="mt-3">
          <label className="field">
            <b>Engagement ID</b>
            <input
              className="input"
              value={revokeId}
              onChange={(e) => setRevokeId(e.target.value)}
              placeholder="UUID of the engagement to revoke"
              required
            />
          </label>
          {revokeError ? (
            <p role="alert" style={{ fontSize: "0.8125rem", color: "var(--stop)" }} className="mt-2">
              {revokeError}
            </p>
          ) : null}
          {revoked ? (
            <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }} className="mt-2">
              Engagement revoked.
            </p>
          ) : null}
          <button
            type="submit"
            className="btn btn--ghost mt-3"
            disabled={revokeBusy || !revokeId.trim()}
          >
            {revokeBusy ? "Revoking…" : "Revoke engagement"}
          </button>
        </form>
      </div>
    </div>
  );
}
