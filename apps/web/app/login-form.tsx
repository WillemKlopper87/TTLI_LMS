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

  const inputClass =
    "w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2";
  const buttonClass =
    "w-full rounded-md px-3 py-2 text-sm font-medium text-white disabled:opacity-50";

  if (mfaToken) {
    return (
      <form onSubmit={submitMfa} className="space-y-4">
        <p className="text-sm text-gray-600">
          Enter the code from your authenticator app, or a recovery code.
        </p>
        <input
          className={inputClass}
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="123456"
          autoFocus
          required
        />
        {error ? <p className="text-sm text-red-600">{error}</p> : null}
        <button
          type="submit"
          disabled={busy}
          className={buttonClass}
          style={{ backgroundColor: "var(--brand-primary)" }}
        >
          Verify
        </button>
      </form>
    );
  }

  return (
    <form onSubmit={submitLogin} className="space-y-4">
      <input
        className={inputClass}
        type="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="you@example.com"
        required
      />
      <input
        className={inputClass}
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        placeholder="Password"
        required
      />
      {error ? <p className="text-sm text-red-600">{error}</p> : null}
      <button
        type="submit"
        disabled={busy}
        className={buttonClass}
        style={{ backgroundColor: "var(--brand-primary)" }}
      >
        Sign in
      </button>
    </form>
  );
}
