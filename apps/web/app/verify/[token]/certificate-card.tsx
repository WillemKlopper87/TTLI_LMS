"use client";

import QRCode from "qrcode";
import { useEffect, useState } from "react";

import { formatDate } from "@/lib/format";

/**
 * The rendered certificate (design doc §4 screen 10) — the same artefact
 * the PDF prints, drawn in the page so a holder and a verifier see the
 * credential itself rather than a description of it.
 *
 * The QR encodes the verification URL, generated client-side: the page
 * already knows the URL it is on, and round-tripping to the server for an
 * image of a string this page owns would be a needless dependency.
 */
export function CertificateCard({
  issuerName,
  holderName,
  programmeTitle,
  issuedAt,
  credentialId,
  cpdPoints,
  verifyUrl,
}: {
  issuerName: string | null;
  holderName: string | null;
  programmeTitle: string | null;
  issuedAt: string | null;
  credentialId: string | null;
  cpdPoints: number | null;
  verifyUrl: string | null;
}) {
  const [qr, setQr] = useState<string | null>(null);

  useEffect(() => {
    if (!verifyUrl) return;
    let cancelled = false;
    QRCode.toDataURL(verifyUrl, { margin: 1, width: 320 })
      .then((url) => {
        if (!cancelled) setQr(url);
      })
      .catch(() => {
        // A missing QR is cosmetic — every field below still verifies.
        if (!cancelled) setQr(null);
      });
    return () => {
      cancelled = true;
    };
  }, [verifyUrl]);

  return (
    <div className="certificate">
      <p className="cert-issuer">{issuerName ?? "Themba Thandeka Leadership Institute"}</p>
      <p className="cert-title">Certificate of Completion</p>
      <p style={{ fontSize: ".8125rem", color: "var(--muted)" }}>This is to certify that</p>
      <span className="cert-name">{holderName ?? "—"}</span>
      <p style={{ fontSize: ".8125rem", color: "var(--muted)" }}>
        has completed all assessed requirements for
      </p>
      <p className="serif" style={{ fontSize: "1.25rem" }}>
        {programmeTitle ?? "—"}
      </p>
      {qr ? (
        // eslint-disable-next-line @next/next/no-img-element -- a data: URI generated in the browser
        <img className="qr" src={qr} alt="Scan to verify this credential" />
      ) : null}
      <dl className="cert-grid">
        <div>
          <dt>Issued</dt>
          <dd>{issuedAt ? formatDate(issuedAt) : "—"}</dd>
        </div>
        <div>
          <dt>Credential ID</dt>
          <dd className="mono" style={{ fontSize: ".6875rem" }}>
            {credentialId ?? "—"}
          </dd>
        </div>
        {cpdPoints !== null ? (
          <div>
            <dt>CPD points</dt>
            <dd>{cpdPoints}</dd>
          </div>
        ) : null}
      </dl>
    </div>
  );
}
