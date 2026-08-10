"use client";

import { useEffect, useState } from "react";

import { getAccessToken } from "@/lib/session";

interface PendingPayment {
  payment_id: string;
  order_id: string;
  buyer_email: string;
  amount: string;
  currency: string;
  payment_reference: string | null;
  provider: string;
  po_number: string | null;
  proof_uploaded: boolean;
  created_at: string;
}

interface PendingPaymentsPage {
  items: PendingPayment[];
  total: number;
}

/**
 * The finance approval queue (REQ-PAY-03). There is no automated approval
 * path — every row here needs a human decision, gated on `payment:approve`.
 */
export default function PaymentsScreen() {
  const [page, setPage] = useState<PendingPaymentsPage | null>(null);
  const [error, setError] = useState<"forbidden" | "unknown" | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [reason, setReason] = useState<Record<string, string>>({});

  async function load() {
    const token = getAccessToken();
    if (!token) return;
    setError(null);
    const resp = await fetch("/api/bff/payments", { headers: { Authorization: `Bearer ${token}` } });
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
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function approve(paymentId: string) {
    setBusyId(paymentId);
    const token = getAccessToken();
    const resp = await fetch(`/api/bff/payments/${paymentId}/approve`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
    setBusyId(null);
    if (resp.ok) await load();
  }

  async function reject(paymentId: string) {
    const text = reason[paymentId]?.trim();
    if (!text) return;
    setBusyId(paymentId);
    const token = getAccessToken();
    const resp = await fetch(`/api/bff/payments/${paymentId}/reject`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ reason: text }),
    });
    setBusyId(null);
    if (resp.ok) await load();
  }

  if (error === "forbidden") {
    return (
      <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
        Your account does not have permission to review payments.
      </p>
    );
  }
  if (error === "unknown") {
    return (
      <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
        The queue could not be loaded. Try again shortly.
      </p>
    );
  }
  if (page === null) {
    return <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>Loading…</p>;
  }

  return (
    <>
      <h1 className="serif" style={{ fontSize: "1.5rem" }}>
        Payments
      </h1>
      <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
        {page.total} awaiting a decision
      </p>

      {page.items.length === 0 ? (
        <p className="mt-6" style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>
          Nothing waiting on finance right now.
        </p>
      ) : (
        <div className="mt-6 flex flex-col gap-3">
          {page.items.map((payment) => (
            <div key={payment.payment_id} className="card p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p style={{ fontWeight: 600, fontSize: "0.875rem" }}>{payment.buyer_email}</p>
                  <p className="mono" style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                    {payment.provider === "po" ? payment.po_number : payment.payment_reference}
                    &middot; {payment.currency} {payment.amount}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <span className="tag tag--mute">{payment.provider === "po" ? "PO" : "EFT"}</span>
                  {payment.provider === "po" ? null : (
                    <span className={`tag ${payment.proof_uploaded ? "tag--live" : "tag--mute"}`}>
                      {payment.proof_uploaded ? "Proof uploaded" : "Awaiting proof"}
                    </span>
                  )}
                </div>
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  className="btn btn--primary"
                  disabled={busyId === payment.payment_id}
                  onClick={() => approve(payment.payment_id)}
                >
                  Approve
                </button>
                <input
                  className="input"
                  style={{ maxWidth: "16rem" }}
                  placeholder="Reason for rejection"
                  aria-label={`Reason for rejecting payment ${payment.payment_id}`}
                  value={reason[payment.payment_id] ?? ""}
                  onChange={(e) => setReason({ ...reason, [payment.payment_id]: e.target.value })}
                />
                <button
                  type="button"
                  className="btn btn--ghost"
                  disabled={busyId === payment.payment_id || !reason[payment.payment_id]?.trim()}
                  onClick={() => reject(payment.payment_id)}
                >
                  Reject
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
