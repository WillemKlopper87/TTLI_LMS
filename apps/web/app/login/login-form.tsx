"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { setAccessToken } from "@/lib/session";

export function LoginForm() {
  const router = useRouter();
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
    setAccessToken((await resp.json()).access_token);
    router.push("/admin");
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
    setAccessToken((await resp.json()).access_token);
    router.push("/admin");
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
          autoFocus
          required
        />
        {error ? <p style={{ fontSize: "0.8125rem", color: "var(--stop)" }}>{error}</p> : null}
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
        required
      />
      <input
        className="input"
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        placeholder="Password"
        required
      />
      {error ? <p style={{ fontSize: "0.8125rem", color: "var(--stop)" }}>{error}</p> : null}
      <button type="submit" disabled={busy} className="btn btn--primary btn--block">
        Sign in
      </button>
    </form>
  );
}
