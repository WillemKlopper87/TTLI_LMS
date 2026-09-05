"use client";

import { useState } from "react";

import { bffFetch } from "@/lib/bff-fetch";

/**
 * Newsletter signup, on the existing lead-capture flow
 * (`POST /leads`, REQ-LEAD-01..03). There is no separate "subscriber"
 * concept in the data model and inventing one would duplicate consent
 * handling that already works: a subscriber *is* a lead with marketing
 * consent, and the campaign engine already refuses to send to anyone
 * without it or on the suppression list.
 *
 * Marketing consent is therefore the point of this form and is required
 * here — unlike guest access, where it is genuinely optional.
 */
export function NewsletterSignup() {
  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [email, setEmail] = useState("");
  const [privacy, setPrivacy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!privacy) {
      setError("Please accept the privacy policy so we know how to store your details.");
      return;
    }
    setBusy(true);
    setError(null);
    const resp = await bffFetch("/api/bff/leads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email,
        first_name: first,
        last_name: last,
        privacy_consent: true,
        // The whole purpose of this form; the campaign engine will not
        // send to a lead without it.
        marketing_consent: true,
        utm_source: "resources",
        utm_medium: "newsletter",
      }),
    });
    setBusy(false);
    if (!resp.ok) {
      setError("That could not be submitted. Try again shortly.");
      return;
    }
    setDone(true);
  }

  if (done) {
    return (
      <div className="callout callout--done">
        <b>You&rsquo;re on the list</b>
        We send occasional notes on leadership practice — never more than we would want to
        receive. Every email carries a one-click unsubscribe.
      </div>
    );
  }

  return (
    <div className="aside-card">
      <p className="eyebrow">Newsletter</p>
      <h3 className="serif" style={{ fontSize: "1.0625rem" }}>
        Occasional notes, not a drip campaign
      </h3>
      <p style={{ fontSize: ".8125rem", color: "var(--muted)" }}>
        What we are reading, what came up in the last cohort, and when a new episode lands.
      </p>
      <div className="fields">
        <div className="two">
          <label className="field">
            <b>First name</b>
            <input className="input" value={first} onChange={(e) => setFirst(e.target.value)} />
          </label>
          <label className="field">
            <b>Last name</b>
            <input className="input" value={last} onChange={(e) => setLast(e.target.value)} />
          </label>
        </div>
        <label className="field">
          <b>Email</b>
          <input
            className="input"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
      </div>
      <div className="consent">
        <input
          type="checkbox"
          id="newsletter-privacy"
          checked={privacy}
          onChange={(e) => setPrivacy(e.target.checked)}
        />
        <label htmlFor="newsletter-privacy">
          I accept the privacy policy and understand how my information is stored, and I&rsquo;m
          happy to receive the newsletter. You can unsubscribe from any email.
        </label>
      </div>
      {error ? (
        <p role="alert" style={{ fontSize: ".75rem", color: "var(--stop)" }}>
          {error}
        </p>
      ) : null}
      <button
        type="button"
        className="btn btn--primary btn--block"
        disabled={busy || !email || !first || !last}
        onClick={submit}
      >
        {busy ? "Signing you up…" : "Sign me up"}
      </button>
    </div>
  );
}
