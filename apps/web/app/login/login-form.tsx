"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { postLoginRedirect } from "@/lib/post-login-redirect";
import { useSession } from "@/lib/session-context";

export function LoginForm() {
  const router = useRouter();
  const { setSession } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submitLogin(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const resp = await fetch("/api/bff/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    setBusy(false);
    if (resp.status === 202) {
      setMfaToken((await resp.json()).mfa_token);
      return;
    }
    if (!resp.ok) {
      setError("Those credentials are not valid.");
      return;
    }
    const body = await resp.json();
    setSession(body);
    await postLoginRedirect(router, body.access_token);
  }

  async function submitMfa(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const resp = await fetch("/api/bff/auth/mfa/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mfa_token: mfaToken, code }),
    });
    setBusy(false);
    if (!resp.ok) {
      setError(resp.status === 429 ? "Too many attempts. Try again later." : "That code is not valid.");
      return;
    }
    const body = await resp.json();
    setSession(body);
    await postLoginRedirect(router, body.access_token);
  }

  if (mfaToken) {
    return (
      <form onSubmit={submitMfa} className="space-y-4">
        <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
          Enter the code from your authenticator app, or a recovery code.
        </p>
        <input
          className="input"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="123456"
          aria-label="Authentication code"
          autoComplete="one-time-code"
          autoFocus
          required
        />
        {error ? <p role="alert" style={{ fontSize: "0.8125rem", color: "var(--stop)" }}>{error}</p> : null}
        <button type="submit" disabled={busy} className="btn btn--primary btn--block">
          Verify
        </button>
      </form>
    );
  }

  return (
    <form onSubmit={submitLogin} className="space-y-4">
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
      <input
        className="input"
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        placeholder="Password"
        aria-label="Password"
        autoComplete="current-password"
        required
      />
      {error ? <p role="alert" style={{ fontSize: "0.8125rem", color: "var(--stop)" }}>{error}</p> : null}
      <button type="submit" disabled={busy} className="btn btn--primary btn--block">
        Sign in
      </button>
    </form>
  );
}
