"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { getAccessToken } from "@/lib/session";
import { useRequireAuth } from "@/lib/session-context";

interface SubscriptionResponse {
  id: string;
  plan_id: string;
  pending_plan_id: string | null;
  status: string;
  current_period_start: string | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
}

interface SubscriptionOrderResponse {
  subscription: SubscriptionResponse;
  order_id: string | null;
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

async function authedFetch(path: string, init: RequestInit = {}) {
  const token = getAccessToken();
  return fetch(path, { ...init, headers: { ...init.headers, Authorization: `Bearer ${token}` } });
}

function EftPanel({ orderId, onDone }: { orderId: string; onDone: () => void }) {
  const [eft, setEft] = useState<EftCheckoutResponse | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    authedFetch(`/api/bff/orders/${orderId}/checkout/eft`, { method: "POST" }).then(async (resp) => {
      if (resp.ok) setEft(await resp.json());
    });
  }, [orderId]);

  async function submitProof() {
    if (!file) return;
    setBusy(true);
    const form = new FormData();
    form.append("file", file);
    const resp = await authedFetch(`/api/bff/orders/${orderId}/payment-proof`, {
      method: "POST",
      body: form,
    });
    setBusy(false);
    if (resp.ok) {
      setSubmitted(true);
      onDone();
    }
  }

  if (submitted) {
    return (
      <p className="mt-3" style={{ fontSize: "0.875rem" }}>
        Proof submitted — your subscription activates once finance approves the payment.
      </p>
    );
  }
  if (eft === null) {
    return <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>Loading bank details…</p>;
  }
  return (
    <div className="card mt-3 p-4">
      <b style={{ fontSize: "0.8125rem" }}>Pay by EFT</b>
      <p className="mt-1" style={{ fontSize: "0.8125rem" }}>
        {eft.currency} {Number(eft.amount).toLocaleString()} — ref {eft.payment_reference}
      </p>
      <p style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
        {eft.bank_name} · {eft.account_name} · {eft.account_number} · {eft.branch_code}
      </p>
      <label className="field mt-2">
        <b>Proof of payment</b>
        <input
          type="file"
          className="input"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
      </label>
      <button
        type="button"
        className="btn btn--primary mt-2"
        disabled={!file || busy}
        onClick={submitProof}
      >
        Submit proof
      </button>
    </div>
  );
}

/**
 * Learner-facing subscription management. Arriving with `?plan=<id>`
 * (from the catalogue's "Subscribe" button) starts a new subscription;
 * otherwise shows the existing one. Renewal/upgrade both fund a real
 * Order through the same EFT flow as any other purchase — there's no
 * separate "subscription checkout," just the same primitive reused
 * (services/subscriptions.py's own docstring).
 */
export default function SubscriptionAccountPage() {
  const requestedPlanId = useSearchParams().get("plan");
  const { ready } = useRequireAuth();

  const [subscription, setSubscription] = useState<SubscriptionResponse | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [pendingOrderId, setPendingOrderId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!ready || !getAccessToken()) return;
    authedFetch("/api/bff/subscriptions/me")
      .then(async (resp) => {
        if (resp.ok) setSubscription(await resp.json());
      })
      .finally(() => setLoaded(true));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);

  async function startSubscribe(planId: string) {
    setBusy(true);
    setError(null);
    const resp = await authedFetch("/api/bff/subscriptions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan_id: planId, currency: "ZAR", customer_type: "individual" }),
    });
    setBusy(false);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not start that subscription.");
      return;
    }
    const data: SubscriptionOrderResponse = await resp.json();
    setSubscription(data.subscription);
    setPendingOrderId(data.order_id);
  }

  async function renew() {
    setBusy(true);
    setError(null);
    const resp = await authedFetch("/api/bff/subscriptions/me/renew", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ currency: "ZAR", customer_type: "individual" }),
    });
    setBusy(false);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not start a renewal.");
      return;
    }
    const data: SubscriptionOrderResponse = await resp.json();
    setSubscription(data.subscription);
    setPendingOrderId(data.order_id);
  }

  async function cancel() {
    setBusy(true);
    const resp = await authedFetch("/api/bff/subscriptions/me/cancel", { method: "POST" });
    setBusy(false);
    if (resp.ok) setSubscription(await resp.json());
  }

  async function resume() {
    setBusy(true);
    const resp = await authedFetch("/api/bff/subscriptions/me/resume", { method: "POST" });
    setBusy(false);
    if (resp.ok) setSubscription(await resp.json());
  }

  if (!loaded) {
    return (
      <main className="mx-auto max-w-2xl px-6 py-16">
        <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>Loading…</p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-2xl px-6 py-16">
      <p className="eyebrow">Account</p>
      <h1 className="serif mt-2" style={{ fontSize: "1.5rem" }}>
        Subscription
      </h1>

      {error ? (
        <p role="alert" className="mt-3" style={{ color: "var(--stop)" }}>
          {error}
        </p>
      ) : null}

      {subscription === null && requestedPlanId ? (
        <div className="card mt-4 p-4">
          <p style={{ fontSize: "0.875rem" }}>Start this subscription?</p>
          <button
            type="button"
            className="btn btn--primary mt-2"
            disabled={busy}
            onClick={() => startSubscribe(requestedPlanId)}
          >
            Subscribe
          </button>
        </div>
      ) : subscription === null ? (
        <p className="mt-4" style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
          You don&apos;t have a subscription yet — pick a plan from the catalogue.
        </p>
      ) : (
        <div className="card mt-4 p-4">
          <p style={{ fontSize: "0.875rem" }}>
            Status: <span className="tag tag--brand">{subscription.status}</span>
          </p>
          {subscription.current_period_end ? (
            <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
              {subscription.cancel_at_period_end ? "Access ends" : "Renews"}{" "}
              {new Date(subscription.current_period_end).toLocaleDateString()}
            </p>
          ) : null}
          {subscription.pending_plan_id ? (
            <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
              A plan downgrade is queued for your next renewal.
            </p>
          ) : null}

          <div className="mt-3 flex flex-wrap gap-2">
            {subscription.status === "active" && !subscription.cancel_at_period_end ? (
              <button type="button" className="btn btn--ghost" disabled={busy} onClick={cancel}>
                Cancel at period end
              </button>
            ) : null}
            {subscription.cancel_at_period_end ? (
              <button type="button" className="btn btn--ghost" disabled={busy} onClick={resume}>
                Resume
              </button>
            ) : null}
            {subscription.status === "active" ? (
              <button type="button" className="btn btn--primary" disabled={busy} onClick={renew}>
                Renew now
              </button>
            ) : null}
          </div>
        </div>
      )}

      {pendingOrderId ? <EftPanel orderId={pendingOrderId} onDone={() => setPendingOrderId(null)} /> : null}
    </main>
  );
}
