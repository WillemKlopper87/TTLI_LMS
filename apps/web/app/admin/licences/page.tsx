"use client";

/**
 * `/admin/licences` — list and manage licences for a licensee organisation.
 * Requires an organisation_id query parameter or input.
 * Gate on `tenant:manage`.
 */

import { useEffect, useState } from "react";

import { useAdmin } from "../admin-context";
import { authedFetch, readError } from "../courses/wizard-api";

interface LicenceItem {
  id: string;
  organisation_id: string;
  course_id: string | null;
  learning_path_id: string | null;
  status: string;
  seats_purchased: number;
  seats_used: number;
  starts_at: string;
  ends_at: string;
  price_per_seat_cents: number | null;
  currency: string | null;
  royalty_pct: number | null;
  order_id: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export default function LicencesScreen() {
  const { me } = useAdmin();
  const canManage = me.permissions.includes("tenant:manage");

  const [organisationId, setOrganisationId] = useState("");
  const [licences, setLicences] = useState<LicenceItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function loadLicences(orgId: string) {
    if (!orgId.trim()) {
      setLicences(null);
      return;
    }

    setLoading(true);
    setError(null);

    const resp = await authedFetch(`/api/bff/licences?organisation_id=${encodeURIComponent(orgId)}`);
    setLoading(false);

    if (!resp.ok) {
      setError(await readError(resp, "Licences could not be loaded."));
      setLicences([]);
      return;
    }

    const data = (await resp.json()) as { items: LicenceItem[] };
    setLicences(data.items);
  }

  async function handleSearch(event: React.FormEvent) {
    event.preventDefault();
    await loadLicences(organisationId);
  }

  const statusColor: Record<string, string> = {
    active: "tag--live",
    expired: "tag--mute",
    pending: "tag--live",
  };

  return (
    <div className="dash">
      <div className="dash-top">
        <div>
          <p className="eyebrow">Sales & Licensing</p>
          <h1>Licences</h1>
        </div>
        {canManage ? (
          <a className="btn btn--primary" href="/admin/licences/new">
            New licence
          </a>
        ) : null}
      </div>

      <form onSubmit={(e) => void handleSearch(e)} className="card p-4 mb-6" style={{ maxWidth: "32rem" }}>
        <label className="field">
          <b>Organisation ID</b>
          <input
            className="input"
            value={organisationId}
            onChange={(e) => setOrganisationId(e.target.value)}
            placeholder="Paste organisation UUID"
            type="text"
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
          disabled={loading || !organisationId.trim()}
        >
          {loading ? "Loading…" : "Search"}
        </button>
      </form>

      {licences !== null && (
        <>
          <dl className="stats">
            <div className="stat">
              <dt>Licences</dt>
              <dd>{licences.length}</dd>
            </div>
            <div className="stat">
              <dt>Total seats</dt>
              <dd>{licences.reduce((sum, l) => sum + l.seats_purchased, 0)}</dd>
            </div>
            <div className="stat">
              <dt>Seats in use</dt>
              <dd>{licences.reduce((sum, l) => sum + l.seats_used, 0)}</dd>
            </div>
          </dl>

          <div className="tablewrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Content</th>
                  <th scope="col">Status</th>
                  <th scope="col">Seats</th>
                  <th scope="col">Valid period</th>
                  <th scope="col" />
                </tr>
              </thead>
              <tbody>
                {licences.length === 0 ? (
                  <tr>
                    <td colSpan={5} style={{ color: "var(--muted)" }}>
                      No licences found for this organisation.
                    </td>
                  </tr>
                ) : null}
                {licences.map((licence) => (
                  <tr key={licence.id}>
                    <td>
                      <b>{licence.course_id ? "Course" : "Learning path"}</b>
                      <div style={{ fontSize: "0.6875rem", color: "var(--faint)" }}>
                        {licence.course_id || licence.learning_path_id}
                      </div>
                    </td>
                    <td>
                      <span className={`tag ${statusColor[licence.status] ?? "tag--mute"}`}>
                        {licence.status}
                      </span>
                    </td>
                    <td>
                      {licence.seats_used} / {licence.seats_purchased}
                    </td>
                    <td>
                      <div style={{ fontSize: "0.8125rem" }}>
                        {new Date(licence.starts_at).toLocaleDateString()} –{" "}
                        {new Date(licence.ends_at).toLocaleDateString()}
                      </div>
                    </td>
                    <td>
                      <div className="flex flex-wrap justify-end gap-2">
                        <a
                          className="btn btn--ghost"
                          href={`/admin/licences/${licence.id}/grant-seat`}
                        >
                          Grant seat
                        </a>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div style={{ marginTop: "2rem" }}>
            <a className="btn btn--ghost" href="/admin/licences/seat-grants">
              View all seat grants
            </a>
          </div>
        </>
      )}
    </div>
  );
}
