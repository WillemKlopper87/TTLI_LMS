"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { postLoginRedirect } from "@/lib/post-login-redirect";
import { useSession } from "@/lib/session-context";

type Step = "request" | "sent" | "consuming" | "error";

/**
 * Dual-mode like /auth/password-reset: no ?token= is the request form,
 * a token auto-consumes on mount. The email link itself
 * (`https://{host}/auth/magic-link?token=...`) is minted by
 * apps/api/src/routers/auth.py's request_magic_link.
 */
export default function MagicLinkPage() {
  const router = useRouter();
  const { setSession } = useSession();
  const token = useSearchParams().get("token");

  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState<Step>(token ? "consuming" : "request");

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    (async () => {
      const resp = await fetch("/api/bff/auth/magic-link/consume", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      });
      if (cancelled) return;
      if (resp.status === 202) {
        // MFA is enforced on this account — the challenge token has nowhere
        // to go from here, so send them to a normal login instead.
        router.replace("/login");
        return;
      }
      if (!resp.ok) {
        setStep("error");
        return;
      }
      const body = await resp.json();
      setSession(body);
      await postLoginRedirect(router, body.access_token);
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  async function requestLink(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const resp = await fetch("/api/bff/auth/magic-link", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });
    setBusy(false);
    if (!resp.ok) {
      setError("Something went wrong. Try again shortly.");
      return;
    }
    setStep("sent");
  }

  if (step === "consuming") {
    return (
      <main className="flex min-h-screen items-center justify-center p-6">
        <p style={{ fontSize: "0.875rem", color: "var(--muted)" }}>Signing you in…</p>
      </main>
    );
  }

  if (step === "error") {
    return (
      <main className="flex min-h-screen items-center justify-center p-6">
        <div className="card w-full max-w-sm text-center" style={{ padding: "2rem" }}>
          <h1 className="serif" style={{ fontSize: "1.35rem" }}>
            That link isn&rsquo;t valid
          </h1>
          <p className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
            It may have already been used, or expired.
          </p>
          <Link href="/auth/magic-link" className="btn btn--primary mt-4">
            Request a new link
          </Link>
        </div>
      </main>
    );
  }

  if (step === "sent") {
    return (
      <main className="flex min-h-screen items-center justify-center p-6">
        <div className="card w-full max-w-sm text-center" style={{ padding: "2rem" }}>
          <h1 className="serif" style={{ fontSize: "1.35rem" }}>
            Check your email
          </h1>
          <p className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
            If <b>{email}</b> is a valid address, we&rsquo;ve sent a sign-in link. It works once and
            expires shortly.
          </p>
          <Link href="/login" className="btn btn--ghost mt-4">
            Back to sign in
          </Link>
        </div>
      </main>
    );
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="card w-full max-w-sm" style={{ padding: "2rem" }}>
        <h1 className="serif" style={{ fontSize: "1.35rem" }}>
          Sign in with a link
        </h1>
        <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
          No password — we&rsquo;ll email you a one-time sign-in link.
        </p>
        <form onSubmit={requestLink} className="mt-4 space-y-4">
          <input
            className="input"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            aria-label="Email address"
            autoComplete="email"
            required
          />
          {error ? <p role="alert" style={{ fontSize: "0.8125rem", color: "var(--stop)" }}>{error}</p> : null}
          <button type="submit" disabled={busy} className="btn btn--primary btn--block">
            Send my sign-in link
          </button>
        </form>
        <p className="mt-4 text-center" style={{ fontSize: "0.8125rem" }}>
          <Link href="/login">Back to sign in</Link>
        </p>
      </div>
    </main>
  );
}
