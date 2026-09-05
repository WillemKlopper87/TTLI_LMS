"use client";

/**
 * The route-level error boundary.
 *
 * Its absence is what turned one render-time throw into a whole-tenant
 * outage: a tenant that uploaded a logo got an unrenderable `next/image`
 * src on `/login` and in the admin shell, and with nothing to catch it
 * every visitor saw Next's own 500 page (fable5.1 review H-16, H-17).
 * The throw itself is fixed; this exists so the next one — a slow API, a
 * malformed payload, a component that assumed a field was present — costs
 * one route rather than the site.
 *
 * `reset()` re-renders the segment without a full reload, which is
 * genuinely enough for the transient cases (a failed fetch on the way in),
 * so it is offered first.
 */
import Link from "next/link";
import { useEffect } from "react";

export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Next logs this server-side already; this is what puts it in the
    // browser console for anyone debugging a report from a real user.
    console.error("Route error boundary caught:", error);
  }, [error]);

  return (
    <main className="pad-lg" style={{ textAlign: "center" }}>
      <div style={{ maxWidth: "32rem", marginInline: "auto" }}>
        <p className="eyebrow">Something went wrong</p>
        <h1 className="serif" style={{ fontSize: "2rem", marginTop: "0.5rem" }}>
          This page didn&rsquo;t load.
        </h1>
        <p style={{ color: "var(--muted)", marginTop: "1rem" }}>
          The rest of the site is unaffected. Try again — if it keeps happening, the reference
          below is what support needs to find it in the logs.
        </p>
        {error.digest ? (
          <p className="mono" style={{ fontSize: "0.75rem", color: "var(--muted)", marginTop: "0.75rem" }}>
            Reference {error.digest}
          </p>
        ) : null}
        <div
          style={{
            marginTop: "2rem",
            display: "flex",
            gap: "1rem",
            justifyContent: "center",
            flexWrap: "wrap",
          }}
        >
          <button type="button" onClick={reset} className="btn btn--primary btn--lg">
            Try again
          </button>
          <Link href="/" className="btn btn--ghost btn--lg">
            Back to home
          </Link>
        </div>
      </div>
    </main>
  );
}
