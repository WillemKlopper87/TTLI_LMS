"use client";

import { useSearchParams } from "next/navigation";
import { useState } from "react";

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

type Step = "details" | "eft" | "submitted";

/**
 * The EFT purchase path (REQ-PAY-03), wired to the real backend built this
 * sprint: POST /orders -> POST /orders/{id}/checkout/eft ->
 * POST /orders/{id}/payment-proof. Card (Payfast/Netcash) and PO checkout
 * aren't built — see 0009's migration docstring for why — so this page
 * only offers EFT.
 */
export default function CheckoutPage() {
  useRequireAuth();
  const priceId = useSearchParams().get("price");

  const [customerType, setCustomerType] = useState("individual");
  const [step, setStep] = useState<Step>("details");
  const [order, setOrder] = useState<OrderResponse | null>(null);
  const [eft, setEft] = useState<EftCheckoutResponse | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function authedFetch(path: string, init: RequestInit = {}) {
    const token = getAccessToken();
    return fetch(path, {
      ...init,
      headers: { ...init.headers, Authorization: `Bearer ${token}` },
    });
  }

  async function createOrderAndCheckout() {
    if (!priceId) {
      setError("No programme selected — start from the catalogue.");
      return;
    }
    setBusy(true);
    setError(null);
    const orderResp = await authedFetch("/api/bff/orders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        currency: "ZAR",
        customer_type: customerType,
        lines: [{ price_id: priceId, quantity: 1 }],
      }),
    });
    if (!orderResp.ok) {
      setBusy(false);
      const body = await orderResp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not create the order.");
      return;
    }
    const createdOrder: OrderResponse = await orderResp.json();
    setOrder(createdOrder);

    const eftResp = await authedFetch(`/api/bff/orders/${createdOrder.id}/checkout/eft`, {
      method: "POST",
    });
    setBusy(false);
    if (!eftResp.ok) {
      setError("Could not start EFT checkout.");
      return;
    }
    setEft(await eftResp.json());
    setStep("eft");
  }

  async function submitProof() {
    if (!order || !file) return;
    setBusy(true);
    setError(null);
    const formData = new FormData();
    formData.append("file", file);
    const resp = await authedFetch(`/api/bff/orders/${order.id}/payment-proof`, {
      method: "POST",
      body: formData,
    });
    setBusy(false);
    if (!resp.ok) {
      setError("Could not upload the proof of payment.");
      return;
    }
    setStep("submitted");
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
            disabled={!file || busy}
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
        Direct EFT is the only path available today — card checkout needs live payment-gateway
        credentials that aren&rsquo;t configured yet.
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
        disabled={busy}
        onClick={createOrderAndCheckout}
      >
        Continue to EFT details
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
