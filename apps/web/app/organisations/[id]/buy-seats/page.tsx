"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { getAccessToken } from "@/lib/session";
import { useRequireAuth } from "@/lib/session-context";

interface PriceSummary {
  id: string;
  currency: string;
  unit_amount: string;
  tax_behaviour: string;
}

interface ProductSummary {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  kind: string;
  prices: PriceSummary[];
}

interface OrderResponse {
  id: string;
  grand_total: string;
  currency: string;
}

interface PoCheckoutResponse {
  payment_id: string;
  po_number: string;
  amount: string;
  currency: string;
}

type Step = "select" | "po" | "submitted";

/**
 * The org seat-purchase path (02 §4.5, REQ-TEN-02, 0016's PO checkout) —
 * the org-scoped sibling of /checkout. PO number and document are
 * captured together in one step here, unlike EFT: a purchase order
 * document exists from the moment it's raised, so there's no separate
 * "reference now, proof later" split.
 */
export default function BuySeatsPage() {
  const params = useParams<{ id: string }>();
  const { ready } = useRequireAuth();
  const orgId = params.id;

  const [products, setProducts] = useState<ProductSummary[] | null>(null);
  const [priceId, setPriceId] = useState("");
  const [quantity, setQuantity] = useState(1);
  const [step, setStep] = useState<Step>("select");
  const [order, setOrder] = useState<OrderResponse | null>(null);
  const [poNumber, setPoNumber] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PoCheckoutResponse | null>(null);

  async function authedFetch(path: string, init: RequestInit = {}) {
    const token = getAccessToken();
    return fetch(path, { ...init, headers: { ...init.headers, Authorization: `Bearer ${token}` } });
  }

  useEffect(() => {
    if (!ready || !getAccessToken()) return;
    fetch("/api/bff/products")
      .then(async (resp) => (resp.ok ? setProducts((await resp.json()).items) : setProducts([])))
      .catch(() => setProducts([]));
  }, [ready]);

  async function createOrder() {
    if (!priceId) {
      setError("Choose a programme first.");
      return;
    }
    setBusy(true);
    setError(null);
    const resp = await authedFetch("/api/bff/orders", {
      method: "POST",
      // Idempotency-Key (03 §1.6) — same reasoning as app/checkout/page.tsx.
      headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({
        currency: "ZAR",
        customer_type: "registered_business",
        lines: [{ price_id: priceId, quantity }],
        organisation_id: orgId,
      }),
    });
    setBusy(false);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not create the order.");
      return;
    }
    setOrder(await resp.json());
    setStep("po");
  }

  async function submitPo() {
    if (!order || !poNumber.trim() || !file) return;
    setBusy(true);
    setError(null);
    const formData = new FormData();
    formData.append("po_number", poNumber.trim());
    formData.append("file", file);
    const resp = await authedFetch(`/api/bff/orders/${order.id}/checkout/po`, {
      method: "POST",
      body: formData,
    });
    setBusy(false);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not submit the purchase order.");
      return;
    }
    setResult(await resp.json());
    setStep("submitted");
  }

  if (step === "submitted" && result) {
    return (
      <main className="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center gap-3 px-6 text-center">
        <h1 className="serif" style={{ fontSize: "1.5rem" }}>
          Submitted for approval
        </h1>
        <p style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
          Seats activate once finance confirms PO {result.po_number} — typically within one
          business day.
        </p>
        <a href={`/organisations/${orgId}`} className="btn btn--ghost mt-4">
          Back to the organisation
        </a>
      </main>
    );
  }

  if (step === "po" && order) {
    return (
      <main className="mx-auto max-w-md px-6 py-16">
        <h1 className="serif" style={{ fontSize: "1.5rem" }}>
          Purchase order details
        </h1>
        <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
          Order total: {order.currency} {Number(order.grand_total).toLocaleString()}
        </p>

        <label className="field mt-6">
          <b>PO number</b>
          <input
            className="input"
            value={poNumber}
            onChange={(e) => setPoNumber(e.target.value)}
            placeholder="PO-2026-0142"
          />
        </label>

        <label className="field mt-3">
          <b>Purchase order document</b>
          <input
            className="input"
            type="file"
            accept="application/pdf,image/*"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>

        {error ? (
          <p role="alert" className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--stop)" }}>
            {error}
          </p>
        ) : null}

        <button
          type="button"
          className="btn btn--primary btn--block mt-4"
          disabled={busy || !poNumber.trim() || !file}
          onClick={submitPo}
        >
          Submit for approval
        </button>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-md px-6 py-16">
      <h1 className="serif" style={{ fontSize: "1.5rem" }}>
        Buy seats
      </h1>
      <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
        Seats are purchased against a purchase order — the only path organisations use today.
      </p>

      {products === null ? (
        <p className="mt-6" style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>
          Loading…
        </p>
      ) : (
        <>
          <label className="field mt-6">
            <b>Programme</b>
            <select className="input" value={priceId} onChange={(e) => setPriceId(e.target.value)}>
              <option value="">Choose a programme…</option>
              {products.flatMap((product) =>
                product.prices.map((price) => (
                  <option key={price.id} value={price.id}>
                    {product.name} — {price.currency} {Number(price.unit_amount).toLocaleString()}
                  </option>
                )),
              )}
            </select>
          </label>

          <label className="field mt-3">
            <b>Number of seats</b>
            <input
              className="input"
              type="number"
              min={1}
              max={20}
              value={quantity}
              onChange={(e) => setQuantity(Math.max(1, Math.min(20, Number(e.target.value) || 1)))}
            />
          </label>

          {error ? (
            <p role="alert" className="mt-3" style={{ fontSize: "0.8125rem", color: "var(--stop)" }}>
              {error}
            </p>
          ) : null}

          <button
            type="button"
            className="btn btn--primary btn--lg btn--block mt-4"
            disabled={busy || !priceId}
            onClick={createOrder}
          >
            Continue to PO details
          </button>
        </>
      )}
    </main>
  );
}
