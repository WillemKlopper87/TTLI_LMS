"use client";

/**
 * `/admin/cohorts` — list of cohorts (scheduled runs of learning paths or
 * courses for organisations). Same `.dash-top` + `.stats` + `.tablewrap`
 * pattern as paths/courses list.
 */

import { useEffect, useState } from "react";

import { useAdmin } from "../admin-context";
import { authedFetch, readError } from "../courses/wizard-api";

interface CohortItem {
  id: string;
  title: string;
  learning_path_id: string | null;
  course_id: string | null;
  organisation_id: string | null;
  starts_at: string | null;
  ends_at: string | null;
  capacity: number | null;
  lead_facilitator_id: string | null;
  status: string;
  created_at: string;
}

export default function CohortsScreen() {
  const { me } = useAdmin();
  const canCreate = me.permissions.includes("cohort:run");
  // This is the tenant-wide console (no organisation_id filter), which the
  // backend only ever allows for cohort:run holders — an org admin's
  // narrower, org-scoped view (GET /cohorts?organisation_id=...) belongs on
  // that organisation's own page, the same pattern the partner portal uses,
  // not this generic list. "org:admin" was never a real permission code.
  const canList = me.permissions.includes("cohort:run");

  const [cohorts, setCohorts] = useState<CohortItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    const resp = await authedFetch("/api/bff/cohorts");
    if (!resp.ok) {
      setError(await readError(resp, "Cohorts could not be loaded."));
      setCohorts([]);
      return;
    }
    setCohorts((await resp.json()) as CohortItem[]);
  }

  useEffect(() => {
    if (!canList) return;
    void (async () => {
      await load();
    })();
  }, [canList]);

  if (!canList) {
    return (
      <div className="dash">
        <p style={{ color: "var(--muted)" }}>
          You do not have permission to view cohorts.
        </p>
      </div>
    );
  }

  const active = (cohorts ?? []).filter((c) => c.status !== "completed").length;
  const completed = (cohorts ?? []).filter((c) => c.status === "completed").length;

  return (
    <div className="dash">
      <div className="dash-top">
        <div>
          <p className="eyebrow">Teach</p>
          <h1>Cohorts</h1>
        </div>
        {canCreate ? (
          <a className="btn btn--primary" href="/admin/cohorts/new">
            New cohort
          </a>
        ) : null}
      </div>

      {error ? (
        <div className="callout callout--warn" role="alert">
          <p style={{ fontSize: "0.8125rem" }}>{error}</p>
        </div>
      ) : null}

      <dl className="stats">
        <div className="stat">
          <dt>Cohorts</dt>
          <dd>{cohorts?.length ?? "—"}</dd>
        </div>
        <div className="stat">
          <dt>Active</dt>
          <dd>{cohorts === null ? "—" : active}</dd>
        </div>
        <div className="stat">
          <dt>Completed</dt>
          <dd>{cohorts === null ? "—" : completed}</dd>
        </div>
      </dl>

      <div className="tablewrap">
        <table>
          <thead>
            <tr>
              <th scope="col">Cohort</th>
              <th scope="col">Status</th>
              <th scope="col">Dates</th>
              <th scope="col" />
            </tr>
          </thead>
          <tbody>
            {cohorts === null ? (
              <tr>
                <td colSpan={4} style={{ color: "var(--faint)" }}>
                  Loading…
                </td>
              </tr>
            ) : null}
            {cohorts !== null && cohorts.length === 0 ? (
              <tr>
                <td colSpan={4} style={{ color: "var(--muted)" }}>
                  No cohorts yet. Create one to schedule a learning path or course for an
                  organisation.
                </td>
              </tr>
            ) : null}
            {(cohorts ?? []).map((cohort) => (
              <tr key={cohort.id}>
                <td>
                  <b>{cohort.title}</b>
                  <div style={{ fontSize: "0.6875rem", color: "var(--faint)" }}>
                    {cohort.learning_path_id
                      ? `Path: ${cohort.learning_path_id.slice(0, 8)}`
                      : `Course: ${cohort.course_id?.slice(0, 8)}`}
                  </div>
                </td>
                <td>
                  <span
                    className={`tag ${
                      cohort.status === "active"
                        ? "tag--done"
                        : cohort.status === "pending"
                          ? "tag--live"
                          : "tag--mute"
                    }`}
                  >
                    {cohort.status}
                  </span>
                </td>
                <td>
                  <div style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
                    {cohort.starts_at ? (
                      <>
                        {new Date(cohort.starts_at).toLocaleDateString()} to{" "}
                        {cohort.ends_at ? new Date(cohort.ends_at).toLocaleDateString() : "—"}
                      </>
                    ) : (
                      "—"
                    )}
                  </div>
                </td>
                <td />
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
