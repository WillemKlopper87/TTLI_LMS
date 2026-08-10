"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

/**
 * The real preference-centre link embedded in every campaign email
 * (02 §10, REQ-CRM-04) — public, unauthenticated, resolves the same
 * `GET /unsubscribe/{id}` a plain email client's "click to unsubscribe"
 * would hit directly. No confirmation step: a second click by someone
 * else on an already-unsubscribed link is harmless (idempotent), and a
 * forced confirmation page is exactly the friction real anti-spam
 * conventions (one-click unsubscribe, RFC 8058) tell you to avoid.
 */
export default function UnsubscribePage() {
  const { id } = useParams<{ id: string }>();
  const [state, setState] = useState<"pending" | "done" | "error">("pending");

  useEffect(() => {
    let cancelled = false;
    async function run() {
      const resp = await fetch(`/api/bff/unsubscribe/${id}`);
      if (!cancelled) setState(resp.ok ? "done" : "error");
    }
    run();
    return () => {
      cancelled = true;
    };
  }, [id]);

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center gap-4 px-6 text-center">
      {state === "pending" ? (
        <p style={{ fontSize: "0.875rem", color: "var(--faint)" }}>Updating your preferences&hellip;</p>
      ) : null}
      {state === "done" ? (
        <>
          <h1 className="serif" style={{ fontSize: "1.5rem" }}>
            You&rsquo;re unsubscribed
          </h1>
          <p style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
            You won&rsquo;t receive further marketing emails from us. Transactional messages about
            your own account or purchases are unaffected.
          </p>
        </>
      ) : null}
      {state === "error" ? (
        <>
          <h1 className="serif" style={{ fontSize: "1.5rem" }}>
            Something went wrong
          </h1>
          <p style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
            This link may be incorrect or already expired. Contact us if you keep receiving
            emails you don&rsquo;t want.
          </p>
        </>
      ) : null}
      <Link href="/" className="btn btn--ghost mt-2">
        Back to the homepage
      </Link>
    </main>
  );
}
