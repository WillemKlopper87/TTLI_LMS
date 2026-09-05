"use client";

/**
 * Guest access request (REQ-LEAD-01/04/05/06) — prototype screen 3.
 *
 * Posts straight to POST /api/bff/guest-access. The endpoint always
 * returns 204 whether or not the email is already known (enumeration
 * resistance), so this page shows the same "check your email" state
 * either way — and, as in the prototype, that state replaces only the
 * right-hand column: the pitch stays on screen.
 *
 * Progressive profiling (REQ-LEAD-02): first name, last name and email
 * are the only required fields; company, job title, team size and
 * training goal are optional and sent only when filled in.
 *
 * Split out of page.tsx (SEO/meta-titles pass) so the route can export
 * `metadata` — a "use client" file can't.
 */
import Link from "next/link";
import { useState } from "react";

import { bffFetch } from "@/lib/bff-fetch";

const TEAM_SIZES = ["Just me", "10–49", "50–249", "250+"];

const TRAINING_GOALS = [
  "Leading through uncertainty",
  "Difficult conversations",
  "Strategic planning",
  "Team engagement",
];

export function GuestAccessForm() {
  const [email, setEmail] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [company, setCompany] = useState("");
  const [jobTitle, setJobTitle] = useState("");
  const [teamSize, setTeamSize] = useState("");
  const [trainingGoal, setTrainingGoal] = useState("");
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
    const resp = await bffFetch("/api/bff/guest-access", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email,
        first_name: firstName,
        last_name: lastName,
        company: company || undefined,
        job_title: jobTitle || undefined,
        team_size: teamSize || undefined,
        training_goal: trainingGoal || undefined,
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

  return (
    <main className="split">
      <div className="split-pitch">
        <div>
          <p className="eyebrow" style={{ color: "inherit", opacity: 0.7 }}>
            Guest access
          </p>
          <h2>Try a real lesson before you spend anything.</h2>
        </div>
        <ul>
          <li>
            <b aria-hidden="true">✓</b>
            <span>One full sample lesson from Leading Through Ambiguity</span>
          </li>
          <li>
            <b aria-hidden="true">✓</b>
            <span>A sample assessment, marked the same way the real one is</span>
          </li>
          <li>
            <b aria-hidden="true">✓</b>
            <span>A preview of the certificate you would earn</span>
          </li>
          <li>
            <b aria-hidden="true">✓</b>
            <span>No payment details, no card, no automatic renewal</span>
          </li>
        </ul>
        <p className="note">
          Guest access runs for 14 days. Sample content is watermarked and no certificate is issued.
          If you go on to buy, your progress carries across to the paid enrolment.
        </p>
      </div>

      {sent ? (
        <div className="sent">
          <span className="sent-glyph" aria-hidden="true">
            ✉
          </span>
          <h2>Check your email</h2>
          <p>
            We sent a sign-in link to <b>{email}</b>. It works once and expires in fifteen minutes.
          </p>
          <div className="callout" style={{ textAlign: "left", maxWidth: "34rem" }}>
            <b>Why no password?</b>
            A link that expires cannot be reused, shared or leaked in a breach. You will set a
            password later if you decide to buy.
          </div>
          <Link href="/catalogue" className="btn btn--ghost">
            Continue to the catalogue &rarr;
          </Link>
        </div>
      ) : (
        <form className="form-wrap" onSubmit={submit}>
          <div>
            <h3 className="serif" style={{ fontSize: "1.35rem" }}>
              Create guest access
            </h3>
            <p style={{ fontSize: "0.8125rem", color: "var(--muted)", marginTop: "0.35rem" }}>
              Takes about forty seconds. We send a sign-in link rather than a password.
            </p>
          </div>

          <div className="fields">
            <div className="two">
              <label>
                <b>First name</b>
                <input
                  type="text"
                  value={firstName}
                  onChange={(e) => setFirstName(e.target.value)}
                  autoComplete="given-name"
                  required
                />
              </label>
              <label>
                <b>Last name</b>
                <input
                  type="text"
                  value={lastName}
                  onChange={(e) => setLastName(e.target.value)}
                  autoComplete="family-name"
                  required
                />
              </label>
            </div>
            <label>
              <b>Work email</b>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                required
              />
              <span>We use your work domain to match you to an existing corporate account.</span>
            </label>
            <div className="two">
              <label>
                <b>Company</b>
                <input
                  type="text"
                  value={company}
                  onChange={(e) => setCompany(e.target.value)}
                  autoComplete="organization"
                />
              </label>
              <label>
                <b>Job title</b>
                <input
                  type="text"
                  value={jobTitle}
                  onChange={(e) => setJobTitle(e.target.value)}
                  autoComplete="organization-title"
                />
              </label>
            </div>
            <div className="two">
              <label>
                <b>Team size</b>
                <select value={teamSize} onChange={(e) => setTeamSize(e.target.value)}>
                  <option value="">Prefer not to say</option>
                  {TEAM_SIZES.map((size) => (
                    <option key={size} value={size}>
                      {size}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <b>What are you hoping to change?</b>
                <select value={trainingGoal} onChange={(e) => setTrainingGoal(e.target.value)}>
                  <option value="">Prefer not to say</option>
                  {TRAINING_GOALS.map((goal) => (
                    <option key={goal} value={goal}>
                      {goal}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>

          <div style={{ display: "grid", gap: "0.6rem" }}>
            <div className="consent">
              <input
                type="checkbox"
                id="privacy-consent"
                checked={privacyConsent}
                onChange={(e) => setPrivacyConsent(e.target.checked)}
              />
              <label htmlFor="privacy-consent" style={{ display: "block" }}>
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
                <b style={{ display: "inline" }}>Required.</b>
              </label>
            </div>
            <div className="consent">
              <input
                type="checkbox"
                id="marketing-consent"
                checked={marketingConsent}
                onChange={(e) => setMarketingConsent(e.target.checked)}
              />
              <label htmlFor="marketing-consent" style={{ display: "block" }}>
                Send me occasional programme announcements. Separate from the worksheet — you can
                withdraw this at any time.
              </label>
            </div>
          </div>

          {error ? (
            <p role="alert" style={{ fontSize: "0.8125rem", color: "var(--stop)" }}>
              {error}
            </p>
          ) : null}

          <button type="submit" disabled={busy} className="btn btn--primary btn--lg btn--block">
            Send my sign-in link
          </button>
          <p style={{ fontSize: "0.6875rem", color: "var(--faint)", textAlign: "center" }}>
            Progressive profiling: only the first three fields are required. The rest improve the
            recommendation and are optional.
          </p>
        </form>
      )}
    </main>
  );
}
