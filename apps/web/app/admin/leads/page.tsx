"use client";

import { useEffect, useState } from "react";

import { getAccessToken } from "@/lib/session";

interface LeadSummary {
  lead_id: string;
  contact_id: string;
  email: string;
  first_name: string | null;
  last_name: string | null;
  company: string | null;
  job_title: string | null;
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

export default function LeadsScreen() {
  const [page, setPage] = useState<LeadsPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState<"forbidden" | "unknown" | null>(null);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) return;
    setError(null);
    fetch(`/api/bff/leads?limit=${PAGE_SIZE}&offset=${offset}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(async (resp) => {
        if (resp.status === 403) {
          setError("forbidden");
          return;
        }
        if (!resp.ok) {
          setError("unknown");
          return;
        }
        setPage(await resp.json());
      })
      .catch(() => setError("unknown"));
  }, [offset]);

  if (error === "forbidden") {
    return (
      <p className="text-sm text-gray-600">
        Your account does not have permission to view leads.
      </p>
    );
  }
  if (error === "unknown") {
    return <p className="text-sm text-gray-600">Leads could not be loaded. Try again shortly.</p>;
  }
  if (page === null) {
    return <p className="text-sm text-gray-500">Loading…</p>;
  }

  const name = (lead: LeadSummary) =>
    [lead.first_name, lead.last_name].filter(Boolean).join(" ") || "—";

  return (
    <>
      <h1 className="text-xl font-semibold">Leads</h1>
      <p className="mt-1 text-sm text-gray-600">{page.total} captured</p>

      {page.items.length === 0 ? (
        <p className="mt-6 text-sm text-gray-500">No leads captured yet.</p>
      ) : (
        <div className="mt-6 overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead>
              <tr className="text-left text-xs font-medium uppercase tracking-wide text-gray-500">
                <th className="py-2 pr-4">Name</th>
                <th className="py-2 pr-4">Email</th>
                <th className="py-2 pr-4">Company</th>
                <th className="py-2 pr-4">Source</th>
                <th className="py-2 pr-4">Stage</th>
                <th className="py-2 pr-4">Score</th>
                <th className="py-2 pr-4">Captured</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {page.items.map((lead) => (
                <tr key={lead.lead_id}>
                  <td className="py-2 pr-4">{name(lead)}</td>
                  <td className="py-2 pr-4 font-mono text-xs">{lead.email}</td>
                  <td className="py-2 pr-4">{lead.company ?? "—"}</td>
                  <td className="py-2 pr-4">{lead.source ?? "—"}</td>
                  <td className="py-2 pr-4">{lead.stage}</td>
                  <td className="py-2 pr-4">{lead.score}</td>
                  <td className="py-2 pr-4 text-gray-500">
                    {new Date(lead.created_at).toLocaleDateString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {page.total > PAGE_SIZE ? (
        <div className="mt-4 flex items-center gap-3 text-sm">
          <button
            type="button"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            className="rounded-md border border-gray-300 px-3 py-1 disabled:opacity-40"
          >
            Previous
          </button>
          <button
            type="button"
            disabled={offset + PAGE_SIZE >= page.total}
            onClick={() => setOffset(offset + PAGE_SIZE)}
            className="rounded-md border border-gray-300 px-3 py-1 disabled:opacity-40"
          >
            Next
          </button>
        </div>
      ) : null}
    </>
  );
}
