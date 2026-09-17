"use client";

/**
 * `/admin/licences/seat-grants` — seat grants for a licensee organisation.
 * `GET /organisations/{organisation_id}/licences/seat-grants` requires an
 * organisation_id in the URL, so this screen needs the same organisation
 * picker the licences list uses.
 */

import { useState } from "react";

import { authedFetch, readError } from "../../courses/wizard-api";

interface SeatGrantItem {
  id: string;
  licence_id: string;
  learner_user_id: string;
  entitlement_id: string | null;
  granted_at: string;
  revoked_at: string | null;
}

export default function SeatGrantsScreen() {
  const [organisationId, setOrganisationId] = useState("");
  const [includeRevoked, setIncludeRevoked] = useState(false);
  const [grants, setGrants] = useState<SeatGrantItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function search(event: React.FormEvent) {
    event.preventDefault();
    if (!organisationId.trim()) return;
    setLoading(true);
    setError(null);
    const resp = await authedFetch(
      `/api/bff/organisations/${encodeURIComponent(organisationId.trim())}/licences/seat-grants?include_revoked=${includeRevoked}`,
    );
    setLoading(false);
    if (!resp.ok) {
      setError(await readError(resp, "Seat grants could not be loaded."));
      setGrants([]);
      return;
    }
    const data = (await resp.json()) as { items: SeatGrantItem[] };
    setGrants(data.items);
  }

  return (
    <div className="dash">
      <div className="dash-top">
        <div>
          <p className="eyebrow">Sales &amp; Licensing</p>
          <h1>Seat grants</h1>
        </div>
        <a className="btn btn--ghost" href="/admin/licences">
          All licences
        </a>
      </div>

      <form onSubmit={(e) => void search(e)} className="card p-4 mb-6" style={{ maxWidth: "32rem" }}>
        <label className="field">
          <b>Organisation ID</b>
          <input
            className="input"
            value={organisationId}
            onChange={(e) => setOrganisationId(e.target.value)}
            placeholder="Paste organisation UUID"
            required
          />
        </label>
        <label className="field mt-3 flex flex-row items-center gap-2">
          <input
            type="checkbox"
            checked={includeRevoked}
            onChange={(e) => setIncludeRevoked(e.target.checked)}
          />
          <span>Include revoked</span>
        </label>
        {error ? (
          <p role="alert" style={{ fontSize: "0.8125rem", color: "var(--stop)" }} className="mt-2">
            {error}
          </p>
        ) : null}
        <button
          type="submit"
          className="btn btn--primary mt-3"
          disabled={loading || !organisationId.trim()}
        >
          {loading ? "Loading…" : "Search"}
        </button>
      </form>

      {grants !== null ? (
        <div className="tablewrap">
          <table>
            <thead>
              <tr>
                <th scope="col">Learner</th>
                <th scope="col">Licence</th>
                <th scope="col">Granted</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {grants.length === 0 ? (
                <tr>
                  <td colSpan={4} style={{ color: "var(--muted)" }}>
                    No seat grants found for this organisation.
                  </td>
                </tr>
              ) : null}
              {grants.map((grant) => (
                <tr key={grant.id}>
                  <td className="mono" style={{ fontSize: "0.8125rem" }}>
                    {grant.learner_user_id}
                  </td>
                  <td className="mono" style={{ fontSize: "0.8125rem" }}>
                    {grant.licence_id}
                  </td>
                  <td style={{ fontSize: "0.8125rem" }}>
                    {new Date(grant.granted_at).toLocaleDateString()}
                  </td>
                  <td>
                    <span className={`tag ${grant.revoked_at ? "tag--mute" : "tag--live"}`}>
                      {grant.revoked_at ? "Revoked" : "Active"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
