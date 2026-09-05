"use client";

/**
 * The last resort: a throw in the root layout itself, which `error.tsx`
 * sits inside and therefore cannot catch. It replaces the whole document,
 * so it ships its own <html>/<body> and cannot use any of the app's
 * styling — the root layout is exactly what failed.
 *
 * Kept deliberately plain for that reason: no fonts, no theme variables,
 * no components, nothing that could throw a second time.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: "system-ui, sans-serif",
          background: "#ffffff",
          color: "#1a1a1a",
        }}
      >
        <main style={{ maxWidth: "32rem", padding: "2rem", textAlign: "center" }}>
          <h1 style={{ fontSize: "1.5rem", marginBottom: "1rem" }}>This page didn&rsquo;t load.</h1>
          <p style={{ color: "#5a5a5a", marginBottom: "1.5rem" }}>
            Something failed before the page could be built. Reloading usually clears it.
          </p>
          {error.digest ? (
            <p style={{ fontFamily: "monospace", fontSize: "0.75rem", color: "#5a5a5a" }}>
              Reference {error.digest}
            </p>
          ) : null}
          <button
            type="button"
            onClick={reset}
            style={{
              marginTop: "1.5rem",
              padding: "0.625rem 1.25rem",
              fontSize: "1rem",
              cursor: "pointer",
              border: "1px solid #1a1a1a",
              borderRadius: "0.375rem",
              background: "#1a1a1a",
              color: "#ffffff",
            }}
          >
            Reload
          </button>
        </main>
      </body>
    </html>
  );
}
