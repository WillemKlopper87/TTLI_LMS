"use client";

import { useCallback, useEffect, useState } from "react";

import { authedFetch } from "@/lib/authed-fetch";

interface CertificateInfo {
  id: string;
  certificate_number: string;
  status: string;
  visibility: string;
  issued_at: string;
  revoked_reason: string | null;
  pdf_available: boolean;
}

interface BadgeInfo {
  id: string;
  visibility: string;
  evidence_url: string | null;
}

interface EnrolmentCredentials {
  certificate: CertificateInfo | null;
  badge: BadgeInfo | null;
}

const STATUS_TAG: Record<string, string> = {
  valid: "tag--done",
  revoked: "tag--stop",
  expired: "tag--mute",
};

const VISIBILITY_LABEL: Record<string, string> = {
  private: "Private — only you can see this",
  public: "Public — anyone with the link can verify it",
  link_only: "Link-only — verifiable, but not listed anywhere",
};

/**
 * Certificate/badge issuance is a side effect of completing the course
 * (services/enrolment.py::complete_lesson), not something this page
 * requests — it only asks whether one exists yet (REQ-CRED-01…08). Nothing
 * renders until `certificate`/`badge` come back non-null, which is the
 * normal state for any course still in progress or with no template
 * attached.
 */
interface CredentialsPanelProps {
  enrolmentId?: string;
  pathEnrolmentId?: string;
}

/** Exactly one of `enrolmentId`/`pathEnrolmentId` is set by the caller —
 * a course enrolment's credentials come from `GET /enrolments/{id}/
 * credentials`, a path enrolment's from the P5 sibling endpoint; both
 * shapes are identical (`EnrolmentCredentials`), so one panel serves
 * both rather than a near-duplicate path-only component. */
export function CredentialsPanel({ enrolmentId, pathEnrolmentId }: CredentialsPanelProps) {
  const [data, setData] = useState<EnrolmentCredentials | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [shareUrl, setShareUrl] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    const path = pathEnrolmentId
      ? `/api/bff/path-enrolments/${pathEnrolmentId}/credentials`
      : `/api/bff/enrolments/${enrolmentId}/credentials`;
    const resp = await authedFetch(path);
    if (!resp.ok) return;
    setData(await resp.json());
  }, [enrolmentId, pathEnrolmentId]);

  useEffect(() => {
    void (async () => {
      await load();
    })();
  }, [load]);

  async function downloadCertificate() {
    if (!data?.certificate) return;
    setBusy(true);
    setError(null);
    const resp = await authedFetch(`/api/bff/certificates/${data.certificate.id}/pdf`);
    setBusy(false);
    if (!resp.ok) {
      setError("The certificate PDF could not be retrieved.");
      return;
    }
    const { pdf_url: pdfUrl } = await resp.json();
    window.open(pdfUrl, "_blank", "noopener,noreferrer");
  }

  async function setCertificateVisibility(visibility: string) {
    if (!data?.certificate) return;
    setBusy(true);
    setError(null);
    const resp = await authedFetch(`/api/bff/certificates/${data.certificate.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ visibility }),
    });
    setBusy(false);
    if (!resp.ok) {
      setError("Could not update the certificate's visibility.");
      return;
    }
    await load();
  }

  async function setBadgeVisibility(visibility: string) {
    if (!data?.badge) return;
    setBusy(true);
    setError(null);
    const resp = await authedFetch(`/api/bff/badges/${data.badge.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ visibility }),
    });
    setBusy(false);
    if (!resp.ok) {
      setError("Could not update the badge's visibility.");
      return;
    }
    await load();
  }

  async function shareOnLinkedIn() {
    // A badge shares itself (it carries its own evidence_url alongside
    // the certificate); a certificate-only course — no badge template
    // attached — shares the certificate directly instead (P13, audit
    // #17). Same response shape either way.
    const path = data?.badge
      ? `/api/bff/badges/${data.badge.id}/share/linkedin`
      : data?.certificate
        ? `/api/bff/certificates/${data.certificate.id}/share/linkedin`
        : null;
    if (!path) return;
    setBusy(true);
    setError(null);
    const resp = await authedFetch(path);
    setBusy(false);
    if (!resp.ok) {
      setError("Sharing is only available once this certificate has been issued.");
      return;
    }
    const fields = await resp.json();
    setShareUrl(fields.credential_url);
    window.open(fields.add_to_profile_url, "_blank", "noopener,noreferrer");
  }

  async function copyLink() {
    if (!shareUrl) return;
    await navigator.clipboard.writeText(shareUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  if (!data || (!data.certificate && !data.badge)) return null;

  return (
    <section className="card mt-6 flex flex-col gap-4">
      <h2 className="serif" style={{ fontSize: "1.25rem" }}>
        Your credentials
      </h2>

      {data.certificate ? (
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <p style={{ fontSize: "0.9375rem", fontWeight: 600 }}>Certificate of completion</p>
            <span className={`tag ${STATUS_TAG[data.certificate.status] ?? "tag--mute"}`}>
              {data.certificate.status}
            </span>
          </div>
          <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>
            {data.certificate.certificate_number} &middot; issued{" "}
            {new Date(data.certificate.issued_at).toLocaleDateString()}
          </p>
          {data.certificate.revoked_reason ? (
            <p style={{ fontSize: "0.8125rem", color: "var(--stop)" }}>
              Revoked: {data.certificate.revoked_reason}
            </p>
          ) : null}

          <label className="field mt-1">
            <b>Who can verify this certificate?</b>
            <select
              className="input"
              value={data.certificate.visibility}
              disabled={busy}
              onChange={(e) => setCertificateVisibility(e.target.value)}
            >
              {Object.entries(VISIBILITY_LABEL).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>

          <button
            type="button"
            disabled={busy || !data.certificate.pdf_available}
            onClick={downloadCertificate}
            className="btn btn--primary mt-1"
          >
            {data.certificate.pdf_available ? "Download certificate (PDF)" : "Certificate PDF pending…"}
          </button>

          {!data.badge ? (
            <>
              <button
                type="button"
                disabled={busy}
                onClick={shareOnLinkedIn}
                className="btn btn--ghost mt-1"
              >
                Share on LinkedIn
              </button>
              {shareUrl ? (
                <button type="button" onClick={copyLink} className="btn btn--ghost">
                  {copied ? "Link copied" : "Copy verification link"}
                </button>
              ) : null}
            </>
          ) : null}
        </div>
      ) : null}

      {data.badge ? (
        <div className="flex flex-col gap-2 border-t pt-4" style={{ borderColor: "var(--rule-2)" }}>
          <p style={{ fontSize: "0.9375rem", fontWeight: 600 }}>Digital badge</p>

          <label className="field">
            <b>Who can see this badge?</b>
            <select
              className="input"
              value={data.badge.visibility}
              disabled={busy}
              onChange={(e) => setBadgeVisibility(e.target.value)}
            >
              {Object.entries(VISIBILITY_LABEL).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>

          <button
            type="button"
            disabled={busy}
            onClick={shareOnLinkedIn}
            className="btn btn--ghost mt-1"
          >
            Share on LinkedIn
          </button>
          {shareUrl ? (
            <button type="button" onClick={copyLink} className="btn btn--ghost">
              {copied ? "Link copied" : "Copy verification link"}
            </button>
          ) : null}
        </div>
      ) : null}

      {error ? <p role="alert" style={{ fontSize: "0.8125rem", color: "var(--stop)" }}>{error}</p> : null}
    </section>
  );
}
