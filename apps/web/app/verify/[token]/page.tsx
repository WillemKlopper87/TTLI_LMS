"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

interface VerificationResult {
  found: boolean;
  holder_name: string | null;
  course_title: string | null;
  issued_at: string | null;
  expires_at: string | null;
  status: string | null;
}

const STATUS_COPY: Record<string, { label: string; tag: string }> = {
  valid: { label: "This credential is valid.", tag: "tag--done" },
  revoked: { label: "This credential has been revoked.", tag: "tag--stop" },
  expired: { label: "This credential has expired.", tag: "tag--mute" },
};

/**
 * REQ-CRED-03: the public, unauthenticated verification page a QR code on
 * a printed/PDF certificate resolves to. It calls the same public
 * `GET /verify/{token}` a phone camera would hit directly — this page
 * exists so the result reads as a page, not raw JSON, and so a private
 * certificate's owner can hand out the link deliberately (REQ-CRED-07).
 */
export default function VerifyPage() {
  const { token } = useParams<{ token: string }>();
  const [result, setResult] = useState<VerificationResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const resp = await fetch(`/api/bff/verify/${token}`);
      if (!resp.ok) {
        if (!cancelled) setError("This credential could not be checked right now.");
        return;
      }
      if (!cancelled) setResult(await resp.json());
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <main className="mx-auto flex min-h-screen max-w-lg flex-col justify-center gap-6 px-6 py-16">
      <div className="text-center">
        <p className="eyebrow">Credential verification</p>
        <h1 className="serif mt-2" style={{ fontSize: "1.75rem" }}>
          Verify a TTLI credential
        </h1>
      </div>

      {error ? (
        <p role="alert" className="card text-center" style={{ fontSize: "0.875rem", color: "var(--stop)" }}>
          {error}
        </p>
      ) : null}

      {!error && result === null ? (
        <p className="text-center" style={{ fontSize: "0.875rem", color: "var(--faint)" }}>
          Checking&hellip;
        </p>
      ) : null}

      {result && !result.found ? (
        <div className="card text-center">
          <span className="tag tag--stop" style={{ display: "inline-block" }}>
            Not found
          </span>
          <p className="mt-3" style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
            No valid, publicly verifiable credential matches this link. It may be private, revoked,
            or the link may be incorrect.
          </p>
        </div>
      ) : null}

      {result && result.found ? (
        <div className="card flex flex-col gap-3 text-center">
          <span
            className={`tag ${STATUS_COPY[result.status ?? ""]?.tag ?? "tag--mute"}`}
            style={{ display: "inline-block", alignSelf: "center" }}
          >
            {result.status}
          </span>
          <p style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
            {STATUS_COPY[result.status ?? ""]?.label ?? "This credential's status is unknown."}
          </p>
          <h2 className="serif" style={{ fontSize: "1.375rem" }}>
            {result.holder_name}
          </h2>
          <p style={{ fontSize: "0.9375rem", color: "var(--ink-2)" }}>{result.course_title}</p>
          <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>
            Issued{" "}
            {result.issued_at ? new Date(result.issued_at).toLocaleDateString() : "unknown date"}
            {result.expires_at
              ? ` · expires ${new Date(result.expires_at).toLocaleDateString()}`
              : ""}
          </p>
        </div>
      ) : null}

      <Link href="/" className="btn btn--ghost" style={{ alignSelf: "center" }}>
        Back to the homepage
      </Link>
    </main>
  );
}
