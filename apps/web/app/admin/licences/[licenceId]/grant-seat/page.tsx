"use client";

/**
 * `/admin/licences/{licenceId}/grant-seat` — grant a seat under this
 * licence to a learner. `POST /licences/{licenceId}/grant-seat` validates
 * its body against GrantSeatRequest, which repeats licence_id even though
 * it's already in the URL — both are sent to satisfy that schema.
 */

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { readError, sendJson } from "../../../courses/wizard-api";

export default function GrantSeatPage() {
  const params = useParams<{ licenceId: string }>();
  const router = useRouter();
  const licenceId = params.licenceId;

  const [learnerUserId, setLearnerUserId] = useState("");
  const [entitlementId, setEntitlementId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [granted, setGranted] = useState(false);

  async function grant(event: React.FormEvent) {
    event.preventDefault();
    if (!learnerUserId.trim()) return;
    setBusy(true);
    setError(null);
    setGranted(false);
    const resp = await sendJson(`/api/bff/licences/${licenceId}/grant-seat`, "POST", {
      licence_id: licenceId,
      learner_user_id: learnerUserId.trim(),
      entitlement_id: entitlementId.trim() || null,
    });
    setBusy(false);
    if (!resp.ok) {
      setError(await readError(resp, "The seat could not be granted."));
      return;
    }
    setGranted(true);
    setLearnerUserId("");
    setEntitlementId("");
  }

  return (
    <div className="dash">
      <div className="dash-top">
        <div>
          <p className="eyebrow">Sales &amp; Licensing</p>
          <h1>Grant seat</h1>
        </div>
        <a className="btn btn--ghost" href="/admin/licences">
          All licences
        </a>
      </div>

      <form onSubmit={(e) => void grant(e)} className="card p-4" style={{ maxWidth: "32rem" }}>
        <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
          Licence: <span className="mono">{licenceId}</span>
        </p>
        <label className="field mt-3">
          <b>Learner user ID</b>
          <input
            className="input"
            value={learnerUserId}
            onChange={(e) => setLearnerUserId(e.target.value)}
            placeholder="UUID of the learner"
            required
            autoFocus
          />
        </label>
        <label className="field mt-3">
          <b>Entitlement ID</b>
          <input
            className="input"
            value={entitlementId}
            onChange={(e) => setEntitlementId(e.target.value)}
            placeholder="Optional"
          />
        </label>
        {error ? (
          <p role="alert" style={{ fontSize: "0.8125rem", color: "var(--stop)" }} className="mt-2">
            {error}
          </p>
        ) : null}
        {granted ? (
          <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }} className="mt-2">
            Seat granted.
          </p>
        ) : null}
        <button
          type="submit"
          className="btn btn--primary mt-3"
          disabled={busy || !learnerUserId.trim()}
        >
          {busy ? "Granting…" : "Grant seat"}
        </button>
      </form>
    </div>
  );
}
