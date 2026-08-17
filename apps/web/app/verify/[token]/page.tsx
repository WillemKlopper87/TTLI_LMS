"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { formatDate } from "@/lib/format";

import { CertificateCard } from "./certificate-card";

interface VerificationResult {
  found: boolean;
  holder_name: string | null;
  course_title: string | null;
  programme_title: string | null;
  issued_at: string | null;
  expires_at: string | null;
  status: string | null;
  credential_id: string | null;
  issuer_name: string | null;
  cpd_points: number | null;
  visibility: string | null;
}

const STATUS: Record<string, { head: string; glyph: string; tone: string }> = {
  valid: { head: "Valid credential", glyph: "✓", tone: "" },
  revoked: { head: "Revoked credential", glyph: "✕", tone: "verify-head--stop" },
  expired: { head: "Expired credential", glyph: "!", tone: "verify-head--live" },
};

/**
 * REQ-CRED-03: the public, unauthenticated page a certificate's QR code
 * resolves to (design doc §4 screen 10). It calls the same public
 * `GET /verify/{token}` a phone camera would hit, and shows the
 * credential as a credential — a rendered certificate beside the
 * verification record — rather than as raw JSON.
 *
 * A private certificate is deliberately indistinguishable from a miss:
 * the API returns the same "not found" shape either way, so this page
 * cannot leak the existence of a credential its holder chose to hide.
 */
export default function VerifyPage() {
  const { token } = useParams<{ token: string }>();
  const [result, setResult] = useState<VerificationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [href, setHref] = useState<string | null>(null);

  useEffect(() => {
    setHref(window.location.href);
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetch(`/api/bff/verify/${token}`)
      .then(async (resp) => {
        if (!resp.ok) {
          if (!cancelled) setError("This credential could not be checked right now.");
          return;
        }
        if (!cancelled) setResult(await resp.json());
      })
      .catch(() => {
        if (!cancelled) setError("This credential could not be checked right now.");
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  if (error) {
    return (
      <main className="pad-lg">
        <p className="callout callout--stop" role="alert">
          <b>Could not verify</b>
          {error}
        </p>
      </main>
    );
  }

  if (result === null) {
    return (
      <main className="pad-lg">
        <p style={{ color: "var(--muted)" }}>Checking this credential…</p>
      </main>
    );
  }

  if (!result.found) {
    return (
      <main className="pad-lg">
        <div style={{ maxWidth: "42rem" }}>
          <p className="eyebrow">Credential verification</p>
          <h1 className="serif" style={{ fontSize: "1.75rem", margin: ".4rem 0 1rem" }}>
            No credential matches this link
          </h1>
          <div className="callout callout--stop">
            <b>Not found</b>
            The link may be mistyped or expired, or the holder may have set the credential to
            private. TTLI cannot confirm whether a private credential exists.
          </div>
          <p style={{ marginTop: "1rem" }}>
            <Link href="/">Back to the home page</Link>
          </p>
        </div>
      </main>
    );
  }

  const status = STATUS[result.status ?? "valid"] ?? STATUS.valid;
  const programme = result.programme_title ?? result.course_title;

  return (
    <main className="pad-lg">
      <div className="certpage">
        <CertificateCard
          issuerName={result.issuer_name}
          holderName={result.holder_name}
          programmeTitle={programme}
          issuedAt={result.issued_at}
          credentialId={result.credential_id}
          cpdPoints={result.cpd_points}
          verifyUrl={href}
        />

        <div style={{ display: "grid", gap: "1.15rem" }}>
          <div className="verify">
            <div className={`verify-head ${status.tone}`}>
              <span aria-hidden="true">{status.glyph}</span>
              <span>{status.head}</span>
            </div>
            <div className="verify-body">
              <div>
                <span className="k">Holder</span>
                <span className="v">{result.holder_name ?? "—"}</span>
              </div>
              <div>
                <span className="k">Programme</span>
                <span className="v">{programme ?? "—"}</span>
              </div>
              <div>
                <span className="k">Issued</span>
                <span className="v">{result.issued_at ? formatDate(result.issued_at) : "—"}</span>
              </div>
              <div>
                <span className="k">Expires</span>
                <span className="v">
                  {result.expires_at ? formatDate(result.expires_at) : "No expiry"}
                </span>
              </div>
              <div>
                <span className="k">Issuer</span>
                <span className="v">
                  {result.issuer_name ?? "Themba Thandeka Leadership Institute"}
                </span>
              </div>
              <div>
                <span className="k">Status</span>
                <span
                  className="v"
                  style={{
                    color: result.status === "valid" ? "var(--done)" : "var(--stop)",
                    fontWeight: 600,
                  }}
                >
                  {(result.status ?? "valid").replace(/^./, (c) => c.toUpperCase())}
                </span>
              </div>
            </div>
          </div>

          <p style={{ fontSize: ".75rem", color: "var(--muted)" }}>
            Anyone can check this page without an account. Revoking the credential changes what
            they see here immediately.
          </p>
        </div>
      </div>
    </main>
  );
}
