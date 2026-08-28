"use client";

import { useEffect, useState } from "react";

import { authedFetch } from "@/lib/authed-fetch";
import { getAccessToken } from "@/lib/session";

interface LeadSummary {
  lead_id: string;
  contact_id: string;
  email: string;
  first_name: string | null;
  last_name: string | null;
  company: string | null;
  job_title: string | null;
  message: string | null;
  source: string | null;
  score: number;
  stage: string;
  created_at: string;
}

interface LeadsPage {
  items: LeadSummary[];
  total: number;
  limit: number;
  offset: number;
}

const PAGE_SIZE = 50;

const STAGE_TAG: Record<string, string> = {
  new: "tag--mute",
  contacted: "tag--live",
  qualified: "tag--done",
};

export default function LeadsScreen() {
  const [page, setPage] = useState<LeadsPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState<"forbidden" | "unknown" | null>(null);

  useEffect(() => {
    if (!getAccessToken()) return;
    void (async () => {
      setError(null);
      try {
        const resp = await authedFetch(`/api/bff/leads?limit=${PAGE_SIZE}&offset=${offset}`);
        if (resp.status === 403) {
          setError("forbidden");
          return;
        }
        if (!resp.ok) {
          setError("unknown");
          return;
        }
        setPage(await resp.json());
      } catch {
        setError("unknown");
      }
    })();
  }, [offset]);

  if (error === "forbidden") {
    return (
      <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
        Your account does not have permission to view leads.
      </p>
    );
  }
  if (error === "unknown") {
    return (
      <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
        Leads could not be loaded. Try again shortly.
      </p>
    );
  }
  if (page === null) {
    return <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>Loading…</p>;
  }

  const name = (lead: LeadSummary) =>
    [lead.first_name, lead.last_name].filter(Boolean).join(" ") || "—";

  return (
    <>
      <h1 className="serif" style={{ fontSize: "1.5rem" }}>
        Leads
      </h1>
      <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
        {page.total} captured
      </p>

      {page.items.length === 0 ? (
        <p className="mt-6" style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>
          No leads captured yet.
        </p>
      ) : (
        <div className="table-wrap mt-6">
          <table className="data">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Email</th>
                <th scope="col">Company</th>
                <th scope="col">Message</th>
                <th scope="col">Source</th>
                <th scope="col">Stage</th>
                <th scope="col">Score</th>
                <th scope="col">Captured</th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((lead) => (
                <tr key={lead.lead_id}>
                  <td>{name(lead)}</td>
                  <td className="mono" style={{ fontSize: "0.75rem" }}>
                    {lead.email}
                  </td>
                  <td>{lead.company ?? "—"}</td>
                  <td
                    style={{ maxWidth: "22ch", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                    title={lead.message ?? undefined}
                  >
                    {lead.message ?? "—"}
                  </td>
                  <td>{lead.source ?? "—"}</td>
                  <td>
                    <span className={`tag ${STAGE_TAG[lead.stage] ?? "tag--mute"}`}>
                      {lead.stage}
                    </span>
                  </td>
                  <td className="mono">{lead.score}</td>
                  <td className="mono" style={{ fontSize: "0.75rem", color: "var(--faint)" }}>
                    {new Date(lead.created_at).toLocaleDateString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {page.total > PAGE_SIZE ? (
        <div className="mt-4 flex items-center gap-3">
          <button
            type="button"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            className="btn btn--ghost"
          >
            Previous
          </button>
          <button
            type="button"
            disabled={offset + PAGE_SIZE >= page.total}
            onClick={() => setOffset(offset + PAGE_SIZE)}
            className="btn btn--ghost"
          >
            Next
          </button>
        </div>
      ) : null}
    </>
  );
}
