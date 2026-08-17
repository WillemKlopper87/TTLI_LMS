"use client";

/**
 * Step 5 — Certification. The endpoints for this were built long ago and
 * had no UI at all: `GET/POST /certificate-templates`, `GET/POST
 * /badge-templates` and `PATCH /courses/{id}` with the template FK.
 * Detaching needs the wizard's `POST /courses/{id}/clear-templates`,
 * because `PATCH` reads `None` as "leave unchanged" and so can never null
 * an FK back out.
 */

import { useEffect, useState } from "react";

import type { BadgeTemplate, CertificateTemplate } from "../types";
import { getJson, readError, sendJson } from "../wizard-api";
import { type StepProps, WizardShell } from "../wizard-shell";

export function StepCertification({ ctx, stepStates, onStep, savedAt, error, notice }: StepProps) {
  const course = ctx.course;
  const [certificates, setCertificates] = useState<CertificateTemplate[] | null>(null);
  const [badges, setBadges] = useState<BadgeTemplate[] | null>(null);
  const [busy, setBusy] = useState(false);

  const [showCertForm, setShowCertForm] = useState(false);
  const [certTitle, setCertTitle] = useState("");
  const [certIssuer, setCertIssuer] = useState("");
  const [certSignatory, setCertSignatory] = useState("");
  const [certSignatoryTitle, setCertSignatoryTitle] = useState("");
  const [certCpd, setCertCpd] = useState("");

  const [showBadgeForm, setShowBadgeForm] = useState(false);
  const [badgeTitle, setBadgeTitle] = useState("");
  const [badgeCriteria, setBadgeCriteria] = useState("");
  const [badgeIssuer, setBadgeIssuer] = useState("");
  const [badgeLevel, setBadgeLevel] = useState("");

  async function loadTemplates() {
    const [c, b] = await Promise.all([
      getJson<{ items: CertificateTemplate[] }>("/api/bff/certificate-templates"),
      getJson<{ items: BadgeTemplate[] }>("/api/bff/badge-templates"),
    ]);
    setCertificates(c?.items ?? []);
    setBadges(b?.items ?? []);
  }

  useEffect(() => {
    void loadTemplates();
  }, []);

  async function attach(field: "certificate_template_id" | "badge_template_id", id: string) {
    if (!ctx.courseId) return;
    setBusy(true);
    ctx.setError(null);
    const resp = await sendJson(`/api/bff/courses/${ctx.courseId}`, "PATCH", { [field]: id });
    setBusy(false);
    if (!resp.ok) {
      ctx.setError(await readError(resp, "That template could not be attached."));
      return;
    }
    ctx.markSaved();
    ctx.setSkip("certification", false);
    await ctx.reloadCourse();
    await ctx.reloadReadiness();
  }

  async function clear(kind: "certificate" | "badge") {
    if (!ctx.courseId) return;
    setBusy(true);
    ctx.setError(null);
    const resp = await sendJson(`/api/bff/courses/${ctx.courseId}/clear-templates`, "POST", {
      [kind]: true,
    });
    setBusy(false);
    if (!resp.ok) {
      ctx.setError(await readError(resp, "That template could not be removed."));
      return;
    }
    ctx.markSaved();
    await ctx.reloadCourse();
    await ctx.reloadReadiness();
  }

  async function createCertificate() {
    setBusy(true);
    ctx.setError(null);
    const resp = await sendJson("/api/bff/certificate-templates", "POST", {
      title: certTitle.trim(),
      issuer_name: certIssuer.trim(),
      signatory_name: certSignatory.trim(),
      signatory_title: certSignatoryTitle.trim(),
      cpd_points: certCpd.trim() ? Number(certCpd) : null,
    });
    setBusy(false);
    if (!resp.ok) {
      ctx.setError(await readError(resp, "The certificate template could not be created."));
      return;
    }
    const created = (await resp.json()) as CertificateTemplate;
    setShowCertForm(false);
    setCertTitle("");
    await loadTemplates();
    await attach("certificate_template_id", created.id);
  }

  async function createBadge() {
    setBusy(true);
    ctx.setError(null);
    const resp = await sendJson("/api/bff/badge-templates", "POST", {
      title: badgeTitle.trim(),
      criteria: badgeCriteria.trim(),
      issuer_name: badgeIssuer.trim(),
      level: badgeLevel.trim() || null,
    });
    setBusy(false);
    if (!resp.ok) {
      ctx.setError(await readError(resp, "The badge template could not be created."));
      return;
    }
    const created = (await resp.json()) as BadgeTemplate;
    setShowBadgeForm(false);
    setBadgeTitle("");
    await loadTemplates();
    await attach("badge_template_id", created.id);
  }

  const attachedCertificate =
    (certificates ?? []).find((t) => t.id === course?.certificate_template_id) ?? null;
  const attachedBadge = (badges ?? []).find((t) => t.id === course?.badge_template_id) ?? null;

  return (
    <WizardShell
      step={5}
      stepStates={stepStates}
      onStep={onStep}
      savedAt={savedAt}
      error={error}
      notice={notice}
      title="Certification"
      intro="What a learner walks away with. Issuance is automatic once every completion rule is met — there is no manual issue button, by design."
      onBack={() => onStep(4)}
      onContinue={() => onStep(6)}
    >
      {course === null ? (
        <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>Loading…</p>
      ) : (
        <div className="flex flex-col gap-6 lg:flex-row">
          <div className="flex-1" style={{ minWidth: 0 }}>
            <section>
              <p className="eyebrow">Certificate</p>
              <div className="rowlist mt-2">
                <label className="rowitem" style={{ cursor: "pointer" }}>
                  <input
                    type="radio"
                    name="certificate"
                    checked={course.certificate_template_id === null}
                    disabled={!ctx.canEdit || busy}
                    onChange={() => void clear("certificate")}
                  />
                  <span className="t">No certificate</span>
                  <span className="m">Completion is still recorded</span>
                </label>
                {(certificates ?? []).map((t) => (
                  <label key={t.id} className="rowitem" style={{ cursor: "pointer" }}>
                    <input
                      type="radio"
                      name="certificate"
                      checked={course.certificate_template_id === t.id}
                      disabled={!ctx.canEdit || busy}
                      onChange={() => void attach("certificate_template_id", t.id)}
                    />
                    <span className="t">{t.title}</span>
                    <span className="m">
                      {t.issuer_name} · {t.signatory_name}
                      {t.cpd_points != null ? ` · ${t.cpd_points} CPD` : ""}
                    </span>
                  </label>
                ))}
                {certificates !== null && certificates.length === 0 ? (
                  <div className="rowitem">
                    <span className="m">No certificate templates exist yet.</span>
                  </div>
                ) : null}
              </div>

              {ctx.canEdit ? (
                <button
                  type="button"
                  className="btn btn--ghost mt-3"
                  onClick={() => setShowCertForm(!showCertForm)}
                >
                  {showCertForm ? "Cancel" : "Create new certificate template"}
                </button>
              ) : null}

              {showCertForm ? (
                <div className="fields mt-3">
                  <label>
                    <b>Title</b>
                    <input
                      className="input"
                      value={certTitle}
                      onChange={(e) => setCertTitle(e.target.value)}
                      placeholder="Certificate of Completion"
                    />
                  </label>
                  <div className="two">
                    <label>
                      <b>Issuer</b>
                      <input
                        className="input"
                        value={certIssuer}
                        onChange={(e) => setCertIssuer(e.target.value)}
                      />
                    </label>
                    <label>
                      <b>CPD points (optional)</b>
                      <input
                        className="input"
                        type="number"
                        min={0}
                        value={certCpd}
                        onChange={(e) => setCertCpd(e.target.value)}
                      />
                    </label>
                  </div>
                  <div className="two">
                    <label>
                      <b>Signatory name</b>
                      <input
                        className="input"
                        value={certSignatory}
                        onChange={(e) => setCertSignatory(e.target.value)}
                      />
                    </label>
                    <label>
                      <b>Signatory title</b>
                      <input
                        className="input"
                        value={certSignatoryTitle}
                        onChange={(e) => setCertSignatoryTitle(e.target.value)}
                      />
                    </label>
                  </div>
                  <button
                    type="button"
                    className="btn btn--primary"
                    disabled={
                      busy ||
                      !certTitle.trim() ||
                      !certIssuer.trim() ||
                      !certSignatory.trim() ||
                      !certSignatoryTitle.trim()
                    }
                    onClick={() => void createCertificate()}
                  >
                    Create & attach
                  </button>
                </div>
              ) : null}
            </section>

            <section className="mt-8">
              <p className="eyebrow">Badge</p>
              <div className="rowlist mt-2">
                <label className="rowitem" style={{ cursor: "pointer" }}>
                  <input
                    type="radio"
                    name="badge"
                    checked={course.badge_template_id === null}
                    disabled={!ctx.canEdit || busy}
                    onChange={() => void clear("badge")}
                  />
                  <span className="t">No badge</span>
                </label>
                {(badges ?? []).map((t) => (
                  <label key={t.id} className="rowitem" style={{ cursor: "pointer" }}>
                    <input
                      type="radio"
                      name="badge"
                      checked={course.badge_template_id === t.id}
                      disabled={!ctx.canEdit || busy}
                      onChange={() => void attach("badge_template_id", t.id)}
                    />
                    <span className="t">{t.title}</span>
                    <span className="m">
                      {t.issuer_name}
                      {t.level ? ` · ${t.level}` : ""}
                    </span>
                  </label>
                ))}
                {badges !== null && badges.length === 0 ? (
                  <div className="rowitem">
                    <span className="m">No badge templates exist yet.</span>
                  </div>
                ) : null}
              </div>

              {ctx.canEdit ? (
                <button
                  type="button"
                  className="btn btn--ghost mt-3"
                  onClick={() => setShowBadgeForm(!showBadgeForm)}
                >
                  {showBadgeForm ? "Cancel" : "Create new badge template"}
                </button>
              ) : null}

              {showBadgeForm ? (
                <div className="fields mt-3">
                  <label>
                    <b>Title</b>
                    <input
                      className="input"
                      value={badgeTitle}
                      onChange={(e) => setBadgeTitle(e.target.value)}
                    />
                  </label>
                  <label>
                    <b>Criteria</b>
                    <textarea
                      className="input"
                      rows={2}
                      value={badgeCriteria}
                      onChange={(e) => setBadgeCriteria(e.target.value)}
                    />
                  </label>
                  <div className="two">
                    <label>
                      <b>Issuer</b>
                      <input
                        className="input"
                        value={badgeIssuer}
                        onChange={(e) => setBadgeIssuer(e.target.value)}
                      />
                    </label>
                    <label>
                      <b>Level (optional)</b>
                      <input
                        className="input"
                        value={badgeLevel}
                        onChange={(e) => setBadgeLevel(e.target.value)}
                      />
                    </label>
                  </div>
                  <button
                    type="button"
                    className="btn btn--primary"
                    disabled={
                      busy || !badgeTitle.trim() || !badgeCriteria.trim() || !badgeIssuer.trim()
                    }
                    onClick={() => void createBadge()}
                  >
                    Create & attach
                  </button>
                </div>
              ) : null}
            </section>

            <button
              type="button"
              className="btn btn--quiet mt-6"
              onClick={() => {
                ctx.setSkip("certification", true);
                ctx.setNotice("Marked as deliberately uncertificated.");
              }}
            >
              This course issues nothing — skip
            </button>
          </div>

          <aside className="lg:w-[16rem] lg:shrink-0">
            <p className="eyebrow">Preview</p>
            <div className="cert-mini mt-2">
              <div className="cl">
                {attachedCertificate ? attachedCertificate.title : "No certificate"}
              </div>
              <div className="cn">{course.title || "Untitled course"}</div>
              <div className="cl">
                {attachedCertificate
                  ? `${attachedCertificate.issuer_name} · Verifiable · Revocable`
                  : "Completion recorded only"}
              </div>
            </div>
            {attachedCertificate ? (
              <p className="mt-2" style={{ fontSize: "0.6875rem", color: "var(--muted)" }}>
                Signed {attachedCertificate.signatory_name}, {attachedCertificate.signatory_title}
                {attachedCertificate.cpd_points != null
                  ? ` · ${attachedCertificate.cpd_points} CPD points`
                  : ""}
                . Issued only once every completion rule is met.
              </p>
            ) : null}
            {attachedBadge ? (
              <p className="mt-3" style={{ fontSize: "0.6875rem", color: "var(--muted)" }}>
                Badge: <b>{attachedBadge.title}</b> — {attachedBadge.criteria}
              </p>
            ) : null}
          </aside>
        </div>
      )}
    </WizardShell>
  );
}
