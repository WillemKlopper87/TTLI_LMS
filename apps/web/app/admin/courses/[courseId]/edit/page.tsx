"use client";

/**
 * The course wizard, re-entered for an existing course:
 * `/admin/courses/{id}/edit?step=1..7`.
 *
 * There is no wizard-session store and no draft buffer — every step writes
 * real rows, and `state="draft"` is the draft mechanism. That is what makes
 * this resumable: the URL carries the course id and the step, and the rail
 * recomputes done/todo from the server on every load.
 */

import { Suspense, useCallback, useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";

import { useAdmin } from "../../../admin-context";
import { StepAssessments } from "../../steps/step-assessments";
import { StepBasics } from "../../steps/step-basics";
import { StepCertification } from "../../steps/step-certification";
import { StepContent } from "../../steps/step-content";
import { StepCurriculum } from "../../steps/step-curriculum";
import { StepPricing } from "../../steps/step-pricing";
import { StepReview } from "../../steps/step-review";
import type {
  CourseItem,
  CourseOutline,
  Readiness,
  SkipKey,
  WizardContext,
} from "../../types";
import { deriveStepStates, getJson, readSkips, writeSkip } from "../../wizard-api";
import { STEP_COUNT, type StepProps } from "../../wizard-shell";

function clampStep(raw: string | null): number {
  const n = Number(raw ?? 1);
  if (!Number.isFinite(n)) return 1;
  return Math.min(STEP_COUNT, Math.max(1, Math.round(n)));
}

function CourseWizard() {
  const params = useParams<{ courseId: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { me } = useAdmin();
  const courseId = params.courseId;

  const step = clampStep(searchParams.get("step"));

  const [course, setCourse] = useState<CourseItem | null>(null);
  const [outline, setOutline] = useState<CourseOutline | null>(null);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [skips, setSkips] = useState<Record<SkipKey, boolean>>({
    rules: false,
    certification: false,
  });
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);

  const canEdit = me.permissions.includes("course:edit");
  const canPublish = me.permissions.includes("course:publish");
  const canManageProducts = me.permissions.includes("product:manage");

  const reloadCourse = useCallback(async () => {
    const data = await getJson<CourseItem>(`/api/bff/courses/${courseId}`);
    if (data === null) {
      setMissing(true);
      return;
    }
    setCourse(data);
  }, [courseId]);

  const reloadOutline = useCallback(async () => {
    const data = await getJson<CourseOutline>(`/api/bff/courses/${courseId}/outline`);
    if (data !== null) setOutline(data);
  }, [courseId]);

  const reloadReadiness = useCallback(async () => {
    const data = await getJson<Readiness>(`/api/bff/courses/${courseId}/readiness`);
    if (data !== null) setReadiness(data);
  }, [courseId]);

  useEffect(() => {
    setSkips(readSkips(courseId));
    void reloadCourse();
    void reloadOutline();
    void reloadReadiness();
  }, [courseId, reloadCourse, reloadOutline, reloadReadiness]);

  function goToStep(n: number) {
    setError(null);
    setNotice(null);
    router.push(`/admin/courses/${courseId}/edit?step=${clampStep(String(n))}`);
  }

  const ctx: WizardContext = {
    courseId,
    course,
    outline,
    readiness,
    canEdit,
    canPublish,
    canManageProducts,
    skips,
    setSkip: (key, value) => setSkips(writeSkip(courseId, key, value)),
    reloadCourse,
    reloadOutline,
    reloadReadiness,
    markSaved: () => setSavedAt(Date.now()),
    setError,
    setNotice,
  };

  const stepProps: StepProps = {
    ctx,
    stepStates: deriveStepStates(course, outline, readiness, skips),
    onStep: goToStep,
    savedAt,
    error,
    notice,
  };

  if (missing) {
    return (
      <div className="dash">
        <h1 className="serif" style={{ fontSize: "1.5rem" }}>
          Course not found
        </h1>
        <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
          It may have been deleted, or you may not hold course:edit.
        </p>
      </div>
    );
  }

  return (
    <div className="dash">
      <div className="dash-top">
        <div>
          <p className="eyebrow">Course setup</p>
          <h1>{course?.title ?? "Loading…"}</h1>
        </div>
        <div className="flex items-center gap-2">
          {course ? (
            <span className={`tag ${course.state === "published" ? "tag--done" : "tag--mute"}`}>
              {course.state}
            </span>
          ) : null}
          <a className="btn btn--ghost" href="/admin/courses">
            All courses
          </a>
        </div>
      </div>

      {step === 1 ? <StepBasics {...stepProps} /> : null}
      {step === 2 ? <StepCurriculum {...stepProps} /> : null}
      {step === 3 ? <StepContent {...stepProps} /> : null}
      {step === 4 ? <StepAssessments {...stepProps} /> : null}
      {step === 5 ? <StepCertification {...stepProps} /> : null}
      {step === 6 ? <StepPricing {...stepProps} /> : null}
      {step === 7 ? <StepReview {...stepProps} /> : null}
    </div>
  );
}

export default function CourseWizardPage() {
  return (
    <Suspense fallback={<p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>Loading…</p>}>
      <CourseWizard />
    </Suspense>
  );
}
