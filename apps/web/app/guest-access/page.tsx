"use client";

import Link from "next/link";
import { useState } from "react";

/**
 * Guest access request (REQ-LEAD-01/04/05/06). Posts straight to
 * POST /api/v1/guest-access — the endpoint always returns 204 whether or
 * not the email is already known (enumeration resistance), so this page
 * shows the same "check your email" state either way.
 */
export default function GuestAccessPage() {
  const [email, setEmail] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [company, setCompany] = useState("");
  const [jobTitle, setJobTitle] = useState("");
  const [privacyConsent, setPrivacyConsent] = useState(false);
  const [marketingConsent, setMarketingConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!privacyConsent) {
      setError("Accept the privacy policy to continue.");
      return;
    }
    setBusy(true);
    setError(null);
    const resp = await fetch("/api/bff/guest-access", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email,
        first_name: firstName,
        last_name: lastName,
        company: company || undefined,
        job_title: jobTitle || undefined,
        privacy_consent: privacyConsent,
        marketing_consent: marketingConsent,
        source: "guest_access_page",
      }),
    });
    setBusy(false);
    if (!resp.ok) {
      setError("Something went wrong. Try again shortly.");
      return;
    }
    setSent(true);
  }

  if (sent) {
    return (
      <main className="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center gap-3 px-6 text-center">
        <h1 className="serif" style={{ fontSize: "1.65rem" }}>
          Check your email
        </h1>
        <p style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
          If <b>{email}</b> is a valid address, we&rsquo;ve sent a sign-in link. It works once and
          expires shortly.
        </p>
        <Link href="/" className="btn btn--ghost mt-4">
          Back to the homepage
        </Link>
      </main>
    );
  }

  return (
    <main className="grid min-h-screen md:grid-cols-2">
      <div
        className="flex flex-col justify-center gap-6 px-8 py-16"
        style={{ background: "var(--brand)", color: "var(--on-brand)" }}
      >
        <div>
          <p className="eyebrow" style={{ color: "var(--on-brand)", opacity: 0.75 }}>
            Guest access
          </p>
          <h2 className="serif mt-2" style={{ fontSize: "1.75rem" }}>
            Try a real lesson before you spend anything.
          </h2>
        </div>
        <ul className="space-y-2" style={{ fontSize: "0.875rem", opacity: 0.92 }}>
          <li>No payment details, no card, no automatic renewal</li>
          <li>We send a sign-in link rather than a password</li>
          <li>If you go on to buy, your progress carries across</li>
        </ul>
      </div>

      <div className="flex flex-col justify-center gap-4 px-8 py-16">
        <div>
          <h1 className="serif" style={{ fontSize: "1.35rem" }}>
            Create guest access
          </h1>
          <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
            Takes about forty seconds.
          </p>
        </div>

        <form onSubmit={submit} className="flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-3">
            <label className="field">
              <b>First name</b>
              <input
                className="input"
                value={firstName}
                onChange={(e) => setFirstName(e.target.value)}
                required
              />
            </label>
            <label className="field">
              <b>Last name</b>
              <input
                className="input"
                value={lastName}
                onChange={(e) => setLastName(e.target.value)}
                required
              />
            </label>
          </div>
          <label className="field">
            <b>Work email</b>
            <input
              className="input"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="field">
              <b>Company</b>
              <input className="input" value={company} onChange={(e) => setCompany(e.target.value)} />
            </label>
            <label className="field">
              <b>Job title</b>
              <input className="input" value={jobTitle} onChange={(e) => setJobTitle(e.target.value)} />
            </label>
          </div>

          <label className="mt-2 flex items-start gap-2" style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
            <input
              type="checkbox"
              checked={privacyConsent}
              onChange={(e) => setPrivacyConsent(e.target.checked)}
              style={{ marginTop: "0.2rem" }}
            />
            <span>
              I accept the privacy policy and understand how my information is stored.{" "}
              <b style={{ color: "var(--ink-2)" }}>Required.</b>
            </span>
          </label>
          <label className="flex items-start gap-2" style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
            <input
              type="checkbox"
              checked={marketingConsent}
              onChange={(e) => setMarketingConsent(e.target.checked)}
              style={{ marginTop: "0.2rem" }}
            />
            <span>Send me occasional programme announcements.</span>
          </label>

          {error ? <p style={{ fontSize: "0.8125rem", color: "var(--stop)" }}>{error}</p> : null}

          <button type="submit" disabled={busy} className="btn btn--primary btn--lg btn--block mt-2">
            Send my sign-in link
          </button>
        </form>
      </div>
    </main>
  );
}
