"use client";

import Link from "next/link";
import { useState } from "react";

import { bffFetch } from "@/lib/bff-fetch";

/**
 * A real contact form (Phase 2 close-out). The live ttli.co.za site has a
 * "Get In Touch" contact page with no working form, just contact details —
 * this is a genuine improvement, not fabricated content, and posts through
 * the existing POST /leads (source="contact_form"), which already carries
 * consent, rate limiting and admin visibility (apps/web/app/admin/leads).
 *
 * Split out of page.tsx (SEO/meta-titles pass) so the route can export
 * `metadata` — a "use client" file can't.
 */
export function ContactForm() {
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [privacyConsent, setPrivacyConsent] = useState(false);
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
    const resp = await bffFetch("/api/bff/leads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email,
        first_name: firstName,
        last_name: lastName,
        message,
        privacy_consent: privacyConsent,
        marketing_consent: false,
        source: "contact_form",
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
          Thank you
        </h1>
        <p style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
          We&rsquo;ve received your message and will get back to you shortly.
        </p>
        <Link href="/" className="btn btn--ghost mt-4">
          Back to the homepage
        </Link>
      </main>
    );
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-lg flex-col justify-center gap-6 px-6 py-16">
      <div className="text-center">
        <p className="eyebrow">Get in touch</p>
        <h1 className="serif mt-2" style={{ fontSize: "1.75rem" }}>
          We would really like to hear from you.
        </h1>
        <p className="mt-3" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
          30 Kasbah Ridge, Egale Canyon Golf Estate
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
          <b>Email</b>
          <input
            className="input"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </label>
        <label className="field">
          <b>Message</b>
          <textarea
            className="input"
            rows={5}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            required
          />
        </label>

        <label className="mt-2 flex items-start gap-2" style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
          <input
            type="checkbox"
            checked={privacyConsent}
            onChange={(e) => setPrivacyConsent(e.target.checked)}
            style={{ marginTop: "0.2rem" }}
          />
          <span>
            I accept the{" "}
            <Link
              href="/privacy"
              target="_blank"
              rel="noopener noreferrer"
              style={{ textDecoration: "underline" }}
            >
              privacy policy
            </Link>{" "}
            and understand how my information is stored.{" "}
            <b style={{ color: "var(--ink-2)" }}>Required.</b>
          </span>
        </label>

        {error ? <p role="alert" style={{ fontSize: "0.8125rem", color: "var(--stop)" }}>{error}</p> : null}

        <button type="submit" disabled={busy} className="btn btn--primary btn--lg btn--block mt-2">
          Send message
        </button>
      </form>
    </main>
  );
}
