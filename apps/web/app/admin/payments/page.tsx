"use client";

import { useEffect, useState } from "react";

import { authedDownload } from "@/lib/authed-download";
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

  const [refundOrderId, setRefundOrderId] = useState("");
  const [refundReason, setRefundReason] = useState("");
  const [refundBusy, setRefundBusy] = useState(false);
  const [refundResult, setRefundResult] = useState<string | null>(null);
  const [refundError, setRefundError] = useState<string | null>(null);

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
      // Idempotency-Key (03 §1.6): finance clicking twice on a slow
      // connection must not issue two invoices for one payment.
      headers: { Authorization: `Bearer ${token}`, "Idempotency-Key": crypto.randomUUID() },
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
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
        "Idempotency-Key": crypto.randomUUID(),
      },
      body: JSON.stringify({ reason: text }),
    });
    setBusyId(null);
    if (resp.ok) await load();
  }

  async function refund() {
    const orderId = refundOrderId.trim();
    const text = refundReason.trim();
    if (!orderId || !text) return;
    setRefundBusy(true);
    setRefundError(null);
    setRefundResult(null);
    const token = getAccessToken();
    const resp = await fetch(`/api/bff/orders/${orderId}/refund`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
        "Idempotency-Key": crypto.randomUUID(),
      },
      body: JSON.stringify({ reason: text }),
    });
    setRefundBusy(false);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setRefundError(body?.error?.message ?? "The refund could not be processed.");
      return;
    }
    const body = await resp.json();
    setRefundResult(
      `Refunded ${body.currency} ${body.amount} — credit note ${body.credit_note_number}.`
    );
    setRefundOrderId("");
    setRefundReason("");
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
      <div className="dash-top">
        <div>
          <h1 className="serif" style={{ fontSize: "1.5rem" }}>
            Payments
          </h1>
          <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
            {page.total} awaiting a decision
          </p>
        </div>
        {/* The accounting exports 05_COMMERCIAL §3 promises from the Team
            tier up. Fetched with the bearer rather than linked — the
            access token is in memory, so a plain <a href> navigation
            sends no Authorization header and gets a 401
            (lib/authed-download.ts). Gated server-side on invoice:create,
            which finance holds. */}
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <button
            type="button"
            className="btn btn--quiet"
            onClick={() => void authedDownload("/api/bff/invoices/export.csv", "invoices.csv")}
          >
            Invoices CSV
          </button>
          <button
            type="button"
            className="btn btn--quiet"
            onClick={() => void authedDownload("/api/bff/ledger/export.csv", "ledger.csv")}
          >
            Ledger CSV
          </button>
        </div>
      </div>

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

      <section className="card mt-8 p-4">
        <h2 className="serif" style={{ fontSize: "1.1rem" }}>
          Refund a fulfilled order
        </h2>
        <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
          Full refund only — credits the order&rsquo;s invoice in full, revokes the access it
          granted, and records the refund. Needs the order&rsquo;s id (not the payment id above);
          find it on the buyer&rsquo;s own order confirmation or support request.
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input
            className="input"
            style={{ maxWidth: "20rem" }}
            placeholder="Order id"
            aria-label="Order id to refund"
            value={refundOrderId}
            onChange={(e) => setRefundOrderId(e.target.value)}
          />
          <input
            className="input"
            style={{ maxWidth: "18rem" }}
            placeholder="Reason for the refund"
            aria-label="Reason for the refund"
            value={refundReason}
            onChange={(e) => setRefundReason(e.target.value)}
          />
          <button
            type="button"
            className="btn btn--primary"
            disabled={refundBusy || !refundOrderId.trim() || !refundReason.trim()}
            onClick={refund}
          >
            Refund
          </button>
        </div>
        {refundResult ? (
          <p className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--done)" }}>
            {refundResult}
          </p>
        ) : null}
        {refundError ? (
          <p role="alert" className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--stop)" }}>
            {refundError}
          </p>
        ) : null}
      </section>
    </>
  );
}
