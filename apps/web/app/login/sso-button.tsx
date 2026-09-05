"use client";

/**
 * The entry point to single sign-on, and the only thing that was
 * missing from an otherwise complete flow (fable5.1 review H-15).
 *
 * Shown only when this tenant actually has an IdP configured:
 * `GET /auth/sso/available` answers that for an anonymous caller, and
 * deliberately says nothing else — not the issuer, not the client id,
 * not the allowed domains. A tenant without SSO renders nothing at all,
 * rather than a button that would 404 on the way to a provider that
 * does not exist.
 *
 * The redirect URI is never sent from here. The API derives it from the
 * tenant it resolved from the Host header and ignores anything a caller
 * says about it — see `routers/sso.py::callback_url` for why that matters
 * against a provider with a loose redirect registration.
 */
import { useEffect, useState } from "react";

import { bffFetch } from "@/lib/bff-fetch";

interface Available {
  available: boolean;
  display_name: string | null;
}

export function SsoButton() {
  const [available, setAvailable] = useState<Available | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      const resp = await bffFetch("/api/bff/auth/sso/available");
      if (!resp.ok) return; // No SSO offered is the safe reading of any failure.
      setAvailable((await resp.json().catch(() => null)) as Available | null);
    })();
  }, []);

  if (!available?.available) return null;

  async function start() {
    setBusy(true);
    setError(null);
    // Carried through the round-trip so a deep link survives the detour
    // to the IdP. The API sanitises it before parking it, and it is
    // never read back off this page's own query string on the way in.
    const next = new URLSearchParams(window.location.search).get("next");
    const resp = await bffFetch(
      `/api/bff/auth/sso/start${next ? `?next=${encodeURIComponent(next)}` : ""}`,
      { method: "POST" },
    );
    if (!resp.ok) {
      setBusy(false);
      setError("Single sign-on is not available right now. Sign in with your password instead.");
      return;
    }
    const body = (await resp.json()) as { authorization_url?: string };
    if (!body.authorization_url) {
      setBusy(false);
      setError("Single sign-on is not available right now. Sign in with your password instead.");
      return;
    }
    // Leaving this origin, so `busy` is never cleared on the happy path
    // — the button stays disabled until the browser is gone, which is
    // exactly the behaviour a second click should get.
    window.location.assign(body.authorization_url);
  }

  return (
    <div className="mb-4">
      <button
        type="button"
        className="btn btn--primary btn--block"
        disabled={busy}
        onClick={() => void start()}
      >
        {busy ? "Redirecting…" : `Continue with ${available.display_name ?? "single sign-on"}`}
      </button>
      {error ? (
        <p className="callout callout--warn mt-2" role="status" style={{ fontSize: "0.8125rem" }}>
          {error}
        </p>
      ) : null}
      <p
        className="mt-3"
        style={{ fontSize: "0.75rem", color: "var(--muted)", textAlign: "center" }}
      >
        or sign in with your password
      </p>
    </div>
  );
}
