"use client";

import { useSearchParams } from "next/navigation";
import { useRef, useState } from "react";

import { getAccessToken } from "@/lib/session";
import { useRequireAuth } from "@/lib/session-context";

interface OrderResponse {
  id: string;
  status: string;
  currency: string;
  subtotal: string;
  tax_total: string;
  grand_total: string;
  payment_reference: string | null;
}

interface EftCheckoutResponse {
  payment_id: string;
  payment_reference: string;
  bank_name: string;
  account_name: string;
  account_number: string;
  branch_code: string;
  amount: string;
  currency: string;
}

interface CardCheckoutResponse {
  payment_id: string;
  action_url: string;
  fields: Record<string, string>;
}

type Step = "details" | "eft" | "redirecting" | "submitted";

/**
 * Card (Payfast hosted checkout) and EFT purchase paths (REQ-PAY-03),
 * wired to the backend built this sprint: POST /orders then either
 * POST /orders/{id}/checkout/card (redirect-and-auto-submit to Payfast)
 * or POST /orders/{id}/checkout/eft -> POST /orders/{id}/payment-proof.
 * PO checkout isn't offered here — 01 §4.3 workflow 5 routes that through
 * an admin/procurement flow, not this self-serve page.
 */
export default function CheckoutPage() {
  useRequireAuth();
  const priceId = useSearchParams().get("price");

  const [customerType, setCustomerType] = useState("individual");
  const [step, setStep] = useState<Step>("details");
  const [order, setOrder] = useState<OrderResponse | null>(null);
  const [eft, setEft] = useState<EftCheckoutResponse | null>(null);
  const [cardCheckout, setCardCheckout] = useState<CardCheckoutResponse | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState<"card" | "eft" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const cardFormRef = useRef<HTMLFormElement>(null);

  async function authedFetch(path: string, init: RequestInit = {}) {
    const token = getAccessToken();
    return fetch(path, {
      ...init,
      headers: { ...init.headers, Authorization: `Bearer ${token}` },
    });
  }

  async function createOrder(): Promise<OrderResponse | null> {
    if (!priceId) {
      setError("No programme selected — start from the catalogue.");
      return null;
    }
    const orderResp = await authedFetch("/api/bff/orders", {
      method: "POST",
      // Idempotency-Key (03 §1.6): a network retry of this exact click
      // must not create a second order. One key per attempt — generated
      // fresh here, not stored across retries, since a genuine second
      // click (not a retry) is a new, distinct purchase attempt.
      headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({
        currency: "ZAR",
        customer_type: customerType,
        lines: [{ price_id: priceId, quantity: 1 }],
      }),
    });
    if (!orderResp.ok) {
      const body = await orderResp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not create the order.");
      return null;
    }
    const createdOrder: OrderResponse = await orderResp.json();
    setOrder(createdOrder);
    return createdOrder;
  }

  async function payByCard() {
    setBusy("card");
    setError(null);
    const createdOrder = await createOrder();
    if (!createdOrder) {
      setBusy(null);
      return;
    }
    // No Idempotency-Key here — 03 §1.6 never names this endpoint
    // (core/idempotency.py's SCOPED_ROUTES docstring), because a
    // retried click is just a second hosted-checkout redirect the buyer
    // abandons, not a duplicate charge: Payfast itself, via the ITN
    // webhook, is the sole source of truth for whether money moved.
    const cardResp = await authedFetch(`/api/bff/orders/${createdOrder.id}/checkout/card`, {
      method: "POST",
    });
    if (!cardResp.ok) {
      setBusy(null);
      if (cardResp.status === 503) {
        setError("Card payment isn't switched on for this deployment yet — please use EFT below.");
      } else {
        const body = await cardResp.json().catch(() => null);
        setError(body?.error?.message ?? "Could not start card checkout.");
      }
      return;
    }
    setCardCheckout(await cardResp.json());
    setStep("redirecting");
    // Payfast's hosted checkout only accepts a real form POST, not a
    // fetch/redirect — submit once the hidden form below has rendered
    // with the returned fields.
    requestAnimationFrame(() => cardFormRef.current?.submit());
  }

  async function payByEft() {
    setBusy("eft");
    setError(null);
    const createdOrder = await createOrder();
    if (!createdOrder) {
      setBusy(null);
      return;
    }
    const eftResp = await authedFetch(`/api/bff/orders/${createdOrder.id}/checkout/eft`, {
      method: "POST",
    });
    setBusy(null);
    if (!eftResp.ok) {
      setError("Could not start EFT checkout.");
      return;
    }
    setEft(await eftResp.json());
    setStep("eft");
  }

  async function submitProof() {
    if (!order || !file) return;
    setBusy("eft");
    setError(null);
    const formData = new FormData();
    formData.append("file", file);
    const resp = await authedFetch(`/api/bff/orders/${order.id}/payment-proof`, {
      method: "POST",
      body: formData,
    });
    setBusy(null);
    if (!resp.ok) {
      setError("Could not upload the proof of payment.");
      return;
    }
    setStep("submitted");
  }

  if (step === "redirecting" && cardCheckout) {
    return (
      <main className="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center gap-3 px-6 text-center">
        <h1 className="serif" style={{ fontSize: "1.5rem" }}>
          Taking you to secure checkout&hellip;
        </h1>
        <p style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
          You&rsquo;ll pay on Payfast&rsquo;s own site — this platform never sees your card details.
        </p>
        {/* Hosted-checkout redirect: Payfast requires a real browser form
            POST with these exact fields, not a fetch or 3xx redirect. */}
        <form ref={cardFormRef} method="POST" action={cardCheckout.action_url} hidden>
          {Object.entries(cardCheckout.fields).map(([key, value]) => (
            <input key={key} type="hidden" name={key} value={value} />
          ))}
        </form>
      </main>
    );
  }

  if (step === "submitted") {
    return (
      <main className="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center gap-3 px-6 text-center">
        <h1 className="serif" style={{ fontSize: "1.5rem" }}>
          Submitted for approval
        </h1>
        <p style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
          Access opens once finance confirms the payment — typically within one business day.
        </p>
      </main>
    );
  }

  if (step === "eft" && order && eft) {
    return (
      <main className="mx-auto max-w-lg px-6 py-16">
        <div className="card" style={{ borderLeft: "3px solid var(--live)", background: "var(--live-wash)", padding: "1rem" }}>
          <b>Access opens after finance confirms the payment.</b>
          <p style={{ fontSize: "0.8125rem", marginTop: "0.2rem" }}>Not when the proof is uploaded.</p>
        </div>

        <div className="card mt-4 p-4" style={{ display: "grid", gap: "0.4rem", fontSize: "0.8125rem" }}>
          <Row k="Bank" v={eft.bank_name} />
          <Row k="Account name" v={eft.account_name} />
          <Row k="Account number" v={eft.account_number} />
          <Row k="Branch code" v={eft.branch_code} />
          <Row k="Amount" v={`${eft.currency} ${eft.amount}`} />
          <Row k="Your reference" v={eft.payment_reference} highlight />
        </div>
        <p className="mt-2" style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
          Use that reference exactly — it is how the payment is matched to your order.
        </p>

        <div className="mt-4">
          <label className="field">
            <b>Proof of payment</b>
            <input
              className="input"
              type="file"
              accept="application/pdf,image/*"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </label>
          {error ? <p role="alert" className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--stop)" }}>{error}</p> : null}
          <button
            type="button"
            className="btn btn--primary btn--block mt-3"
            disabled={!file || busy !== null}
            onClick={submitProof}
          >
            Submit for approval
          </button>
        </div>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-md px-6 py-16">
      <h1 className="serif" style={{ fontSize: "1.5rem" }}>
        How would you like to pay?
      </h1>
      <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
        Card is the fastest way in — access opens as soon as Payfast confirms the payment. Prefer a
        bank transfer instead? Choose EFT below.
      </p>

      <label className="field mt-6">
        <b>You are purchasing as</b>
        <select className="input" value={customerType} onChange={(e) => setCustomerType(e.target.value)}>
          <option value="individual">An individual</option>
          <option value="registered_business">A registered business</option>
          <option value="international">International (not yet supported)</option>
        </select>
      </label>

      {error ? <p role="alert" className="mt-3" style={{ fontSize: "0.8125rem", color: "var(--stop)" }}>{error}</p> : null}

      <button
        type="button"
        className="btn btn--primary btn--lg btn--block mt-4"
        disabled={busy !== null}
        onClick={payByCard}
      >
        {busy === "card" ? "Starting checkout…" : "Pay by card"}
      </button>
      <button
        type="button"
        className="btn btn--ghost btn--lg btn--block mt-2"
        disabled={busy !== null}
        onClick={payByEft}
      >
        {busy === "eft" ? "Starting checkout…" : "Pay by EFT instead"}
      </button>
    </main>
  );
}

function Row({ k, v, highlight }: { k: string; v: string | null; highlight?: boolean }) {
  return (
    <div className="flex justify-between gap-4">
      <span style={{ color: "var(--muted)" }}>{k}</span>
      <span className="mono" style={highlight ? { color: "var(--brand-ink)", fontWeight: 600 } : undefined}>
        {v}
      </span>
    </div>
  );
}
