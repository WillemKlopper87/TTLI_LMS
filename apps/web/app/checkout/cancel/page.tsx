"use client";

import Link from "next/link";

import { useRequireAuth } from "@/lib/session-context";

/**
 * Where Payfast sends the buyer back to if they cancel the hosted
 * checkout (routers/orders.py's checkout_card cancel_url) — standard
 * hosted-checkout semantics: reached only when the buyer backs out
 * before completing payment, so there is nothing to reconcile here.
 */
export default function CheckoutCancelPage() {
  useRequireAuth();

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center gap-3 px-6 text-center">
      <h1 className="serif" style={{ fontSize: "1.5rem" }}>
        Checkout cancelled
      </h1>
      <p style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
        No payment was made and your order wasn&rsquo;t completed. You can start again whenever
        you&rsquo;re ready.
      </p>
      <Link href="/catalogue" className="btn btn--primary mt-2">
        Back to catalogue
      </Link>
    </main>
  );
}
