"use client";

import { useEffect, useState } from "react";

import { authedFetch } from "@/lib/authed-fetch";

interface Deal {
  id: string;
  contact_email: string;
  title: string;
  stage: string;
  amount: string | null;
  currency: string | null;
  created_at: string;
}

interface DealsPage {
  items: Deal[];
  total: number;
  limit: number;
  offset: number;
}

interface Task {
  id: string;
  title: string;
  due_at: string | null;
  completed_at: string | null;
}

interface Note {
  id: string;
  body: string;
  author_email: string;
  created_at: string;
}

interface Activity {
  id: string;
  kind: string;
  detail: Record<string, unknown>;
  created_at: string;
}

interface DealDetail {
  deal: Deal;
  tasks: Task[];
  notes: Note[];
  activities: Activity[];
}

const STAGES = ["new", "qualified", "proposal", "won", "lost"];
const STAGE_TAG: Record<string, string> = {
  new: "tag--mute",
  qualified: "tag--live",
  proposal: "tag--live",
  won: "tag--done",
  lost: "tag--stop",
};
const PAGE_SIZE = 50;

/**
 * The deal-centric CRM (02 §10, REQ-CRM-01/02) — every task and note
 * hangs off a deal, and every mutation appears in that deal's own
 * append-only activity trail.
 */
export default function DealsScreen() {
  const [page, setPage] = useState<DealsPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState<"forbidden" | "unknown" | null>(null);

  const [email, setEmail] = useState("");
  const [title, setTitle] = useState("");
  const [amount, setAmount] = useState("");
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const [expandedDealId, setExpandedDealId] = useState<string | null>(null);
  const [detail, setDetail] = useState<DealDetail | null>(null);
  const [taskTitle, setTaskTitle] = useState("");
  const [noteBody, setNoteBody] = useState("");

  async function load() {
    const resp = await authedFetch(`/api/bff/deals?limit=${PAGE_SIZE}&offset=${offset}`);
    if (resp.status === 403) {
      setError("forbidden");
      return;
    }
    if (!resp.ok) {
      setError("unknown");
      return;
    }
    setPage(await resp.json());
  }

  useEffect(() => {
    void (async () => {
      await load();
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offset]);

  async function createDeal() {
    if (!email.trim() || !title.trim()) return;
    setCreateBusy(true);
    setCreateError(null);
    const resp = await authedFetch("/api/bff/deals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: email.trim(),
        title: title.trim(),
        amount: amount.trim() || null,
        currency: amount.trim() ? "ZAR" : null,
      }),
    });
    setCreateBusy(false);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setCreateError(body?.error?.message ?? "Could not create the deal.");
      return;
    }
    setEmail("");
    setTitle("");
    setAmount("");
    await load();
  }

  async function loadDetail(dealId: string) {
    const resp = await authedFetch(`/api/bff/deals/${dealId}`);
    if (resp.ok) setDetail(await resp.json());
  }

  async function toggleDetail(dealId: string) {
    if (expandedDealId === dealId) {
      setExpandedDealId(null);
      setDetail(null);
      return;
    }
    setExpandedDealId(dealId);
    setDetail(null);
    await loadDetail(dealId);
  }

  async function setStage(dealId: string, stage: string) {
    const resp = await authedFetch(`/api/bff/deals/${dealId}/stage`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stage }),
    });
    if (resp.ok) {
      await load();
      await loadDetail(dealId);
    }
  }

  async function addTask(dealId: string) {
    if (!taskTitle.trim()) return;
    const resp = await authedFetch(`/api/bff/deals/${dealId}/tasks`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: taskTitle.trim() }),
    });
    if (resp.ok) {
      setTaskTitle("");
      await loadDetail(dealId);
    }
  }

  async function completeTask(dealId: string, taskId: string) {
    const resp = await authedFetch(`/api/bff/tasks/${taskId}/complete`, { method: "POST" });
    if (resp.ok) await loadDetail(dealId);
  }

  async function addNote(dealId: string) {
    if (!noteBody.trim()) return;
    const resp = await authedFetch(`/api/bff/deals/${dealId}/notes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body: noteBody.trim() }),
    });
    if (resp.ok) {
      setNoteBody("");
      await loadDetail(dealId);
    }
  }

  if (error === "forbidden") {
    return (
      <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
        Your account does not have permission to view deals.
      </p>
    );
  }
  if (error === "unknown" || page === null) {
    return (
      <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>
        {error === "unknown" ? "Deals could not be loaded." : "Loading…"}
      </p>
    );
  }

  return (
    <>
      <h1 className="serif" style={{ fontSize: "1.5rem" }}>
        Deals
      </h1>
      <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
        {page.total} in the pipeline
      </p>

      <div className="card mt-6 p-5">
        <b style={{ fontSize: "0.875rem" }}>New deal</b>
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <label className="field">
            <b>Contact email</b>
            <input className="input" value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label className="field">
            <b>Title</b>
            <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} />
          </label>
          <label className="field">
            <b>Amount (ZAR)</b>
            <input
              className="input"
              style={{ maxWidth: "8rem" }}
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
            />
          </label>
          <button
            type="button"
            className="btn btn--primary"
            disabled={createBusy || !email.trim() || !title.trim()}
            onClick={createDeal}
          >
            Create
          </button>
        </div>
        {createError ? (
          <p role="alert" className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--stop)" }}>
            {createError}
          </p>
        ) : null}
      </div>

      {page.items.length === 0 ? (
        <p className="mt-6" style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>
          No deals yet.
        </p>
      ) : (
        <div className="table-wrap mt-6">
          <table className="data">
            <thead>
              <tr>
                <th scope="col">Contact</th>
                <th scope="col">Title</th>
                <th scope="col">Stage</th>
                <th scope="col">Amount</th>
                <th scope="col"></th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((deal) => (
                <tr key={deal.id}>
                  <td className="mono" style={{ fontSize: "0.75rem" }}>
                    {deal.contact_email}
                  </td>
                  <td>{deal.title}</td>
                  <td>
                    <span className={`tag ${STAGE_TAG[deal.stage] ?? "tag--mute"}`}>
                      {deal.stage}
                    </span>
                  </td>
                  <td className="mono">
                    {deal.amount ? `${deal.currency} ${deal.amount}` : "—"}
                  </td>
                  <td>
                    <button
                      type="button"
                      className="btn btn--ghost"
                      onClick={() => toggleDetail(deal.id)}
                    >
                      {expandedDealId === deal.id ? "Hide" : "Open"}
                    </button>
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
            className="btn btn--ghost"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          >
            Previous
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            disabled={offset + PAGE_SIZE >= page.total}
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            Next
          </button>
        </div>
      ) : null}

      {expandedDealId ? (
        <div className="card mt-6 p-5">
          {detail === null ? (
            <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>Loading…</p>
          ) : (
            <>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <b style={{ fontSize: "0.9375rem" }}>{detail.deal.title}</b>
                <select
                  className="input"
                  style={{ maxWidth: "12rem" }}
                  value={detail.deal.stage}
                  onChange={(e) => setStage(expandedDealId, e.target.value)}
                >
                  {STAGES.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </div>

              <div className="mt-4 grid gap-4 md:grid-cols-2">
                <div>
                  <b style={{ fontSize: "0.8125rem" }}>Tasks</b>
                  <div className="mt-2 flex flex-col gap-2">
                    {detail.tasks.map((t) => (
                      <div key={t.id} className="flex items-center justify-between gap-2">
                        <span style={{ fontSize: "0.8125rem" }}>{t.title}</span>
                        {t.completed_at ? (
                          <span className="tag tag--done">done</span>
                        ) : (
                          <button
                            type="button"
                            className="btn btn--ghost"
                            onClick={() => completeTask(expandedDealId, t.id)}
                          >
                            Complete
                          </button>
                        )}
                      </div>
                    ))}
                    {detail.tasks.length === 0 ? (
                      <p style={{ fontSize: "0.75rem", color: "var(--faint)" }}>No tasks yet.</p>
                    ) : null}
                  </div>
                  <div className="mt-2 flex gap-2">
                    <input
                      className="input"
                      value={taskTitle}
                      onChange={(e) => setTaskTitle(e.target.value)}
                      placeholder="Send proposal"
                    />
                    <button
                      type="button"
                      className="btn btn--ghost"
                      disabled={!taskTitle.trim()}
                      onClick={() => addTask(expandedDealId)}
                    >
                      Add
                    </button>
                  </div>
                </div>

                <div>
                  <b style={{ fontSize: "0.8125rem" }}>Notes</b>
                  <div className="mt-2 flex flex-col gap-2">
                    {detail.notes.map((n) => (
                      <div key={n.id} style={{ fontSize: "0.8125rem" }}>
                        <p>{n.body}</p>
                        <p style={{ fontSize: "0.6875rem", color: "var(--muted)" }}>
                          {n.author_email}
                        </p>
                      </div>
                    ))}
                    {detail.notes.length === 0 ? (
                      <p style={{ fontSize: "0.75rem", color: "var(--faint)" }}>No notes yet.</p>
                    ) : null}
                  </div>
                  <div className="mt-2 flex gap-2">
                    <input
                      className="input"
                      value={noteBody}
                      onChange={(e) => setNoteBody(e.target.value)}
                      placeholder="Client wants a Q4 start date."
                    />
                    <button
                      type="button"
                      className="btn btn--ghost"
                      disabled={!noteBody.trim()}
                      onClick={() => addNote(expandedDealId)}
                    >
                      Add
                    </button>
                  </div>
                </div>
              </div>

              <div className="mt-4">
                <b style={{ fontSize: "0.8125rem" }}>Activity</b>
                <ul className="mt-2 flex flex-col gap-1">
                  {detail.activities.map((a) => (
                    <li key={a.id} className="mono" style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                      {new Date(a.created_at).toLocaleString()} — {a.kind.replace(/_/g, " ")}
                    </li>
                  ))}
                </ul>
              </div>
            </>
          )}
        </div>
      ) : null}
    </>
  );
}
