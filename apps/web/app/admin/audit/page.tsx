"use client";

import { useCallback, useEffect, useState } from "react";

import { authedFetch } from "@/lib/authed-fetch";

import { useAdmin } from "../admin-context";

/**
 * The audit log browser (enterprise-gaps-plan Pass B, gap #52).
 *
 * `audit_events` has been written to since migration 0001 and, until
 * this screen, the only way to read one was psql — while
 * `05_COMMERCIAL.md` §3 sells "advanced audit logs" in the Enterprise
 * column. Filters mirror the API's exactly, and "Export CSV" hands the
 * same filters to the export endpoint so the file can never disagree
 * with what is on screen.
 *
 * Paging is cursor-based, forward-only, for the reason the API is:
 * the log only grows, and an offset walk over a table being written to
 * repeats or skips rows. "Load more" appends; there is no page number
 * to jump to, because a stable one does not exist.
 */

interface AuditRow {
  id: string;
  created_at: string;
  action: string;
  actor_user_id: string | null;
  actor_role: string | null;
  actor_email: string | null;
  entity_type: string | null;
  entity_id: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  ip: string | null;
  user_agent: string | null;
}

export default function AuditLog() {
  const { me } = useAdmin();
  const canRead = me.permissions.includes("audit:read");

  const [rows, setRows] = useState<AuditRow[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [actions, setActions] = useState<string[]>([]);
  const [action, setAction] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const query = useCallback(
    (extra?: Record<string, string>) => {
      const params = new URLSearchParams({ limit: "50", ...extra });
      if (action) params.set("action", action);
      if (dateFrom) params.set("date_from", dateFrom);
      if (dateTo) params.set("date_to", dateTo);
      return params;
    },
    [action, dateFrom, dateTo],
  );

  const load = useCallback(
    async (append: boolean) => {
      setLoading(true);
      try {
        const params = query(append && cursor ? { cursor } : undefined);
        const resp = await authedFetch(`/api/bff/audit-events?${params.toString()}`);
        if (!resp.ok) {
          setError("The audit log could not be loaded.");
          return;
        }
        const body = (await resp.json()) as { items: AuditRow[]; next_cursor: string | null };
        setRows((previous) => (append ? [...previous, ...body.items] : body.items));
        setCursor(body.next_cursor);
        setError(null);
      } catch {
        setError("The audit log could not be loaded.");
      } finally {
        setLoading(false);
      }
    },
    [cursor, query],
  );

  useEffect(() => {
    if (!canRead) return;
    void (async () => {
      try {
        const resp = await authedFetch("/api/bff/audit-events/actions");
        if (resp.ok) setActions(((await resp.json()) as { actions: string[] }).actions);
      } catch {
        // The dropdown degrades to "any action"; the log itself still loads.
      }
    })();
  }, [canRead]);

  useEffect(() => {
    // Deps are the filters, deliberately not `load` or `cursor`: a
    // filter change starts a new walk from the head of the log, while a
    // cursor change is "load more" appending to the walk already in
    // progress. Including either would restart the list on every page.
    if (canRead) void load(false);
  }, [canRead, action, dateFrom, dateTo]);

  if (!canRead) {
    return (
      <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
        Your role does not hold <span className="mono">audit:read</span>.
      </p>
    );
  }

  const exportHref = `/api/bff/audit-events/export.csv?${query().toString()}`;

  return (
    <>
      <div className="dash-top">
        <div>
          <h1>Audit log</h1>
          <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
            Append-only. A correction is a new row, never an edit — the database refuses
            UPDATE and DELETE on this table.
          </p>
        </div>
      </div>

      <div className="fields mt-3" style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem" }}>
        <label className="field">
          Action
          <select value={action} onChange={(e) => setAction(e.target.value)}>
            <option value="">Any action</option>
            {actions.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          From
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        </label>
        <label className="field">
          To
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </label>
        <a className="btn btn--ghost" href={exportHref} style={{ alignSelf: "end" }}>
          Export CSV
        </a>
      </div>

      {error ? (
        <div className="callout callout--warn mt-3" role="status">
          {error}
        </div>
      ) : null}

      <div className="table-wrap mt-3">
        <table>
          <thead>
            <tr>
              <th scope="col">When</th>
              <th scope="col">Action</th>
              <th scope="col">Actor</th>
              <th scope="col">Entity</th>
              <th scope="col">IP</th>
              <th scope="col">Detail</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td style={{ whiteSpace: "nowrap" }}>
                  {new Date(row.created_at).toLocaleString("en-ZA")}
                </td>
                <td className="mono" style={{ fontSize: "0.6875rem" }}>
                  {row.action}
                </td>
                <td>
                  {row.actor_email ?? <span className="m">—</span>}
                  {row.actor_role ? <span className="tag ml-1">{row.actor_role}</span> : null}
                </td>
                <td className="m">
                  {row.entity_type ? `${row.entity_type} ${(row.entity_id ?? "").slice(0, 8)}` : "—"}
                </td>
                <td className="mono" style={{ fontSize: "0.6875rem" }}>
                  {row.ip ?? "—"}
                </td>
                <td>
                  {row.before || row.after ? (
                    <button
                      type="button"
                      className="btn btn--quiet"
                      aria-expanded={expanded === row.id}
                      onClick={() => setExpanded(expanded === row.id ? null : row.id)}
                    >
                      {expanded === row.id ? "Hide" : "Show"}
                    </button>
                  ) : (
                    <span className="m">—</span>
                  )}
                </td>
              </tr>
            ))}
            {rows.map((row) =>
              expanded === row.id ? (
                <tr key={`${row.id}-detail`}>
                  <td colSpan={6}>
                    <pre
                      className="mono"
                      style={{ fontSize: "0.6875rem", whiteSpace: "pre-wrap", margin: 0 }}
                    >
                      {JSON.stringify({ before: row.before, after: row.after }, null, 2)}
                    </pre>
                  </td>
                </tr>
              ) : null,
            )}
          </tbody>
        </table>
      </div>

      {rows.length === 0 && !loading ? (
        <p className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
          Nothing matches those filters.
        </p>
      ) : null}

      <div className="mt-3">
        {cursor ? (
          <button
            type="button"
            className="btn btn--ghost"
            disabled={loading}
            onClick={() => void load(true)}
          >
            {loading ? "Loading…" : "Load more"}
          </button>
        ) : rows.length > 0 ? (
          <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>End of the log.</p>
        ) : null}
      </div>
    </>
  );
}
