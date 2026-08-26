"use client";

import { useEffect, useState } from "react";

import { getAccessToken } from "@/lib/session";

import { useAdmin } from "../admin-context";

interface CertificateTemplateItem {
  id: string;
  title: string;
  issuer_name: string;
  signatory_name: string;
  signatory_title: string;
  cpd_points: number | null;
  cpd_body: string | null;
  cpd_reference: string | null;
  cpd_validity_months: number | null;
}

interface BadgeTemplateItem {
  id: string;
  title: string;
  criteria: string;
  issuer_name: string;
  level: string | null;
}

/**
 * Certificate/badge template authoring — the other half of Phase 4's
 * authoring gap alongside `/courses`. `course:edit`-gated the same way
 * course/quiz/survey/assignment authoring is; templates are global, not
 * tenant-scoped, matching `Course` itself. No edit-in-place here — the
 * API has `PATCH` support for later, this screen only needs create+list
 * to close the stated gap.
 */
export default function TemplatesScreen() {
  const { me } = useAdmin();
  const canEdit = me.permissions.includes("course:edit");

  const [certificateTemplates, setCertificateTemplates] = useState<
    CertificateTemplateItem[] | null
  >(null);
  const [badgeTemplates, setBadgeTemplates] = useState<BadgeTemplateItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [certTitle, setCertTitle] = useState("");
  const [certIssuer, setCertIssuer] = useState("");
  const [certSignatoryName, setCertSignatoryName] = useState("");
  const [certSignatoryTitle, setCertSignatoryTitle] = useState("");
  const [certCpdPoints, setCertCpdPoints] = useState("");
  const [certCpdBody, setCertCpdBody] = useState("");
  const [certCpdReference, setCertCpdReference] = useState("");
  const [certCpdValidityMonths, setCertCpdValidityMonths] = useState("");
  const [certBusy, setCertBusy] = useState(false);

  const [badgeTitle, setBadgeTitle] = useState("");
  const [badgeCriteria, setBadgeCriteria] = useState("");
  const [badgeIssuer, setBadgeIssuer] = useState("");
  const [badgeLevel, setBadgeLevel] = useState("");
  const [badgeBusy, setBadgeBusy] = useState(false);

  async function authedFetch(path: string, init: RequestInit = {}) {
    const token = getAccessToken();
    return fetch(path, { ...init, headers: { ...init.headers, Authorization: `Bearer ${token}` } });
  }

  async function loadCertificateTemplates() {
    const resp = await authedFetch("/api/bff/certificate-templates");
    if (resp.ok) setCertificateTemplates((await resp.json()).items);
  }

  async function loadBadgeTemplates() {
    const resp = await authedFetch("/api/bff/badge-templates");
    if (resp.ok) setBadgeTemplates((await resp.json()).items);
  }

  useEffect(() => {
    loadCertificateTemplates();
    loadBadgeTemplates();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function createCertificateTemplate() {
    if (!certTitle.trim() || !certIssuer.trim() || !certSignatoryName.trim() || !certSignatoryTitle.trim())
      return;
    setCertBusy(true);
    setError(null);
    const resp = await authedFetch("/api/bff/certificate-templates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: certTitle.trim(),
        issuer_name: certIssuer.trim(),
        signatory_name: certSignatoryName.trim(),
        signatory_title: certSignatoryTitle.trim(),
        cpd_points: certCpdPoints.trim() ? Number(certCpdPoints) : null,
        cpd_body: certCpdBody.trim() || null,
        cpd_reference: certCpdReference.trim() || null,
        cpd_validity_months: certCpdValidityMonths.trim() ? Number(certCpdValidityMonths) : null,
      }),
    });
    setCertBusy(false);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not create the certificate template.");
      return;
    }
    setCertTitle("");
    setCertIssuer("");
    setCertSignatoryName("");
    setCertSignatoryTitle("");
    setCertCpdPoints("");
    setCertCpdBody("");
    setCertCpdReference("");
    setCertCpdValidityMonths("");
    await loadCertificateTemplates();
  }

  async function createBadgeTemplate() {
    if (!badgeTitle.trim() || !badgeCriteria.trim() || !badgeIssuer.trim()) return;
    setBadgeBusy(true);
    setError(null);
    const resp = await authedFetch("/api/bff/badge-templates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: badgeTitle.trim(),
        criteria: badgeCriteria.trim(),
        issuer_name: badgeIssuer.trim(),
        level: badgeLevel.trim() || null,
      }),
    });
    setBadgeBusy(false);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not create the badge template.");
      return;
    }
    setBadgeTitle("");
    setBadgeCriteria("");
    setBadgeIssuer("");
    setBadgeLevel("");
    await loadBadgeTemplates();
  }

  if (certificateTemplates === null || badgeTemplates === null) {
    return <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>Loading…</p>;
  }

  return (
    <>
      <h1 className="serif" style={{ fontSize: "1.5rem" }}>
        Templates
      </h1>

      {error ? (
        <p role="alert" className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--stop)" }}>
          {error}
        </p>
      ) : null}

      <section className="mt-6 grid gap-4 md:grid-cols-2">
        <div>
          {canEdit ? (
            <div className="card p-5">
              <b style={{ fontSize: "0.875rem" }}>Create a certificate template</b>
              <label className="field mt-3">
                <b>Title</b>
                <input
                  className="input"
                  value={certTitle}
                  onChange={(e) => setCertTitle(e.target.value)}
                  placeholder="Executive Leadership Certificate"
                />
              </label>
              <label className="field mt-3">
                <b>Issuer</b>
                <input
                  className="input"
                  value={certIssuer}
                  onChange={(e) => setCertIssuer(e.target.value)}
                  placeholder="Themba Thandeka Leadership Institute"
                />
              </label>
              <label className="field mt-3">
                <b>Signatory name</b>
                <input
                  className="input"
                  value={certSignatoryName}
                  onChange={(e) => setCertSignatoryName(e.target.value)}
                  placeholder="Dr. Thandeka Themba"
                />
              </label>
              <label className="field mt-3">
                <b>Signatory title</b>
                <input
                  className="input"
                  value={certSignatoryTitle}
                  onChange={(e) => setCertSignatoryTitle(e.target.value)}
                  placeholder="Programme Director"
                />
              </label>
              <label className="field mt-3">
                <b>CPD points (optional)</b>
                <input
                  className="input"
                  type="number"
                  min={0}
                  value={certCpdPoints}
                  onChange={(e) => setCertCpdPoints(e.target.value)}
                />
              </label>
              <label className="field mt-3">
                <b>What the accreditation covers (optional)</b>
                <input
                  className="input"
                  value={certCpdBody}
                  onChange={(e) => setCertCpdBody(e.target.value)}
                  placeholder="Continuing professional development in executive leadership"
                />
              </label>
              <label className="field mt-3">
                <b>Accreditation reference (optional)</b>
                <input
                  className="input"
                  value={certCpdReference}
                  onChange={(e) => setCertCpdReference(e.target.value)}
                  placeholder="The accrediting body's own reference number"
                />
              </label>
              <label className="field mt-3">
                <b>Valid for, in months (optional)</b>
                <input
                  className="input"
                  type="number"
                  min={1}
                  value={certCpdValidityMonths}
                  onChange={(e) => setCertCpdValidityMonths(e.target.value)}
                  placeholder="Leave blank for a certificate that never expires"
                />
              </label>
              <button
                type="button"
                className="btn btn--primary mt-3"
                disabled={
                  certBusy ||
                  !certTitle.trim() ||
                  !certIssuer.trim() ||
                  !certSignatoryName.trim() ||
                  !certSignatoryTitle.trim()
                }
                onClick={createCertificateTemplate}
              >
                Create
              </button>
            </div>
          ) : null}

          <div className="mt-4 flex flex-col gap-2">
            {certificateTemplates.length === 0 ? (
              <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>
                No certificate templates yet.
              </p>
            ) : (
              certificateTemplates.map((t) => (
                <div key={t.id} className="card p-3">
                  <b style={{ fontSize: "0.8125rem" }}>{t.title}</b>
                  <p className="mt-1" style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                    {t.issuer_name} · {t.signatory_name}, {t.signatory_title}
                    {t.cpd_points !== null ? ` · ${t.cpd_points} CPD points` : ""}
                    {t.cpd_validity_months !== null
                      ? ` · valid ${t.cpd_validity_months} month${t.cpd_validity_months === 1 ? "" : "s"}`
                      : ""}
                  </p>
                  {t.cpd_body ? (
                    <p className="mt-1" style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                      {t.cpd_body}
                    </p>
                  ) : null}
                  {t.cpd_reference ? (
                    <p className="mt-1" style={{ fontSize: "0.75rem", color: "var(--faint)" }}>
                      Reference: {t.cpd_reference}
                    </p>
                  ) : null}
                </div>
              ))
            )}
          </div>
        </div>

        <div>
          {canEdit ? (
            <div className="card p-5">
              <b style={{ fontSize: "0.875rem" }}>Create a badge template</b>
              <label className="field mt-3">
                <b>Title</b>
                <input
                  className="input"
                  value={badgeTitle}
                  onChange={(e) => setBadgeTitle(e.target.value)}
                  placeholder="Leadership Foundations"
                />
              </label>
              <label className="field mt-3">
                <b>Criteria</b>
                <input
                  className="input"
                  value={badgeCriteria}
                  onChange={(e) => setBadgeCriteria(e.target.value)}
                  placeholder="Completed the Executive Leadership Certificate"
                />
              </label>
              <label className="field mt-3">
                <b>Issuer</b>
                <input
                  className="input"
                  value={badgeIssuer}
                  onChange={(e) => setBadgeIssuer(e.target.value)}
                  placeholder="TTLI"
                />
              </label>
              <label className="field mt-3">
                <b>Level (optional)</b>
                <input
                  className="input"
                  value={badgeLevel}
                  onChange={(e) => setBadgeLevel(e.target.value)}
                  placeholder="foundation"
                />
              </label>
              <button
                type="button"
                className="btn btn--primary mt-3"
                disabled={badgeBusy || !badgeTitle.trim() || !badgeCriteria.trim() || !badgeIssuer.trim()}
                onClick={createBadgeTemplate}
              >
                Create
              </button>
            </div>
          ) : null}

          <div className="mt-4 flex flex-col gap-2">
            {badgeTemplates.length === 0 ? (
              <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>No badge templates yet.</p>
            ) : (
              badgeTemplates.map((t) => (
                <div key={t.id} className="card p-3">
                  <b style={{ fontSize: "0.8125rem" }}>{t.title}</b>
                  <p className="mt-1" style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                    {t.criteria} · {t.issuer_name}
                    {t.level ? ` · ${t.level}` : ""}
                  </p>
                </div>
              ))
            )}
          </div>
        </div>
      </section>
    </>
  );
}
