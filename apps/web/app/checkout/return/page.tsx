"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { authedFetch } from "@/lib/authed-fetch";
import { getAccessToken } from "@/lib/session";
import { useRequireAuth } from "@/lib/session-context";

type PollStatus = "checking" | "pending" | "fulfilled" | "gave_up" | "error" | "no_order";

const POLL_INTERVAL_MS = 2000;
const MAX_ATTEMPTS = 8;

/**
 * Where Payfast's hosted checkout sends the buyer back to after a card
 * payment attempt (routers/orders.py's checkout_card return_url). This
 * page is never the fulfilment signal itself — the ITN webhook is (03
 * §5.7) — so it polls GET /orders/{id} rather than trusting the redirect,
 * since the webhook can genuinely arrive after the browser does.
 */
export default function CheckoutReturnPage() {
  const { ready } = useRequireAuth();
  const orderId = useSearchParams().get("order");
  const [status, setStatus] = useState<PollStatus>("checking");
  const [generation, setGeneration] = useState(0);

  useEffect(() => {
    if (!ready) return;
    if (!orderId) {
      setStatus("no_order");
      return;
    }
    if (!getAccessToken()) return;

    let cancelled = false;
    let attempts = 0;
    let timer: ReturnType<typeof setTimeout>;

    async function poll() {
      attempts += 1;
      const resp = await authedFetch(`/api/bff/orders/${orderId}`).catch(() => null);
      if (cancelled) return;
      if (!resp || !resp.ok) {
        setStatus("error");
        return;
      }
      const body = await resp.json();
      if (body.status === "fulfilled") {
        setStatus("fulfilled");
        return;
      }
      if (attempts >= MAX_ATTEMPTS) {
        setStatus("gave_up");
        return;
      }
      setStatus("pending");
      timer = setTimeout(poll, POLL_INTERVAL_MS);
    }

    setStatus("checking");
    timer = setTimeout(poll, 0);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [ready, orderId, generation]);

  const checkAgain = () => setGeneration((g) => g + 1);

  if (status === "fulfilled") {
    return (
      <Screen title="Payment confirmed">
        <p style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
          You&rsquo;re all set — your course is ready.
        </p>
        <Link href="/learn" className="btn btn--primary mt-2">
          Go to your courses
        </Link>
      </Screen>
    );
  }

  if (status === "gave_up") {
    return (
      <Screen title="Still confirming your payment">
        <p style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
          Payfast can take a little longer than this to notify us. This isn&rsquo;t a failure — no
          need to pay again. Access opens automatically the moment confirmation arrives, usually
          within a few minutes.
        </p>
        <div className="flex gap-2 mt-2" style={{ justifyContent: "center" }}>
          <button type="button" className="btn btn--ghost" onClick={checkAgain}>
            Check again
          </button>
          <Link href="/learn" className="btn btn--primary">
            Go to your courses
          </Link>
        </div>
      </Screen>
    );
  }

  if (status === "error" || status === "no_order") {
    return (
      <Screen title="Couldn’t confirm your payment">
        <p style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
          We couldn&rsquo;t check this order&rsquo;s status just now. If Payfast took your payment,
          it will still be matched up automatically — check your courses in a few minutes, or
          contact support with your order reference if it doesn&rsquo;t appear.
        </p>
        <div className="flex gap-2 mt-2" style={{ justifyContent: "center" }}>
          {orderId ? (
            <button type="button" className="btn btn--ghost" onClick={checkAgain}>
              Try again
            </button>
          ) : null}
          <Link href="/learn" className="btn btn--primary">
            Go to your courses
          </Link>
        </div>
      </Screen>
    );
  }

  return (
    <Screen title="Confirming your payment…">
      <p style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
        Hold on while we hear back from Payfast — this usually only takes a few seconds.
      </p>
    </Screen>
  );
}

function Screen({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center gap-3 px-6 text-center">
      <h1 className="serif" style={{ fontSize: "1.5rem" }}>
        {title}
      </h1>
      {children}
    </main>
  );
}
