"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";

type Step = "request" | "sent" | "confirm" | "done" | "error";

/**
 * Dual-mode: no ?token= is the request form; a token present is the
 * new-password form. Confirming revokes every existing session
 * (auth.py::confirm_password_reset -> tokens.revoke_all_for_user), so this
 * always sends the learner back to a real login rather than auto-signing
 * them in.
 */
export default function PasswordResetPage() {
  const token = useSearchParams().get("token");

  const [email, setEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState<Step>(token ? "confirm" : "request");

  async function requestReset(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const resp = await fetch("/api/bff/auth/password-reset", {
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

  async function confirmReset(event: React.FormEvent) {
    event.preventDefault();
    if (newPassword !== confirmPassword) {
      setError("Those passwords don't match.");
      return;
    }
    setBusy(true);
    setError(null);
    const resp = await fetch("/api/bff/auth/password-reset/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, new_password: newPassword }),
    });
    setBusy(false);
    if (!resp.ok) {
      setStep("error");
      return;
    }
    setStep("done");
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
          <Link href="/auth/password-reset" className="btn btn--primary mt-4">
            Request a new link
          </Link>
        </div>
      </main>
    );
  }

  if (step === "done") {
    return (
      <main className="flex min-h-screen items-center justify-center p-6">
        <div className="card w-full max-w-sm text-center" style={{ padding: "2rem" }}>
          <h1 className="serif" style={{ fontSize: "1.35rem" }}>
            Password changed
          </h1>
          <p className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
            All existing sessions were signed out. Sign in again with your new password.
          </p>
          <Link href="/login" className="btn btn--primary mt-4">
            Sign in
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
            If <b>{email}</b> is a valid address, we&rsquo;ve sent a password-reset link. It works
            once and expires shortly.
          </p>
          <Link href="/login" className="btn btn--ghost mt-4">
            Back to sign in
          </Link>
        </div>
      </main>
    );
  }

  if (step === "confirm") {
    return (
      <main className="flex min-h-screen items-center justify-center p-6">
        <div className="card w-full max-w-sm" style={{ padding: "2rem" }}>
          <h1 className="serif" style={{ fontSize: "1.35rem" }}>
            Choose a new password
          </h1>
          <form onSubmit={confirmReset} className="mt-4 space-y-4">
            <input
              className="input"
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="New password"
              aria-label="New password"
              autoComplete="new-password"
              minLength={12}
              required
            />
            <input
              className="input"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="Confirm new password"
              aria-label="Confirm new password"
              autoComplete="new-password"
              minLength={12}
              required
            />
            {error ? <p role="alert" style={{ fontSize: "0.8125rem", color: "var(--stop)" }}>{error}</p> : null}
            <button type="submit" disabled={busy} className="btn btn--primary btn--block">
              Set new password
            </button>
          </form>
        </div>
      </main>
    );
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="card w-full max-w-sm" style={{ padding: "2rem" }}>
        <h1 className="serif" style={{ fontSize: "1.35rem" }}>
          Reset your password
        </h1>
        <form onSubmit={requestReset} className="mt-4 space-y-4">
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
            Send reset link
          </button>
        </form>
        <p className="mt-4 text-center" style={{ fontSize: "0.8125rem" }}>
          <Link href="/login">Back to sign in</Link>
        </p>
      </div>
    </main>
  );
}
