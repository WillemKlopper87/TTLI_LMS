"use client";

/**
 * Step 7 — Review & publish. The readiness report is the same truth
 * `publish_course` enforces, made visible before the button; the button
 * stays server-enforced regardless of what this screen renders.
 *
 * "Duplicate as template" is the TTLI-shaped move: one course, several
 * bespoke tenant variants. The copy always lands as a draft.
 */

import { useState } from "react";
import { useRouter } from "next/navigation";

import { ReadinessPanel } from "../readiness-panel";
import type { CourseItem } from "../types";
import { readError, sendJson } from "../wizard-api";
import { type StepProps, WizardShell } from "../wizard-shell";

export function StepReview({ ctx, stepStates, onStep, savedAt, error, notice }: StepProps) {
  const router = useRouter();
  const course = ctx.course;
  const readiness = ctx.readiness;
  const [busy, setBusy] = useState(false);
  const [published, setPublished] = useState<string | null>(null);

  async function togglePublish() {
    if (!course || !ctx.canPublish) return;
    const action = course.state === "published" ? "unpublish" : "publish";
    setBusy(true);
    ctx.setError(null);
    setPublished(null);
    const resp = await sendJson(`/api/bff/courses/${ctx.courseId}/${action}`, "POST", {});
    setBusy(false);
    if (!resp.ok) {
      ctx.setError(await readError(resp, `The course could not be ${action}ed.`));
      return;
    }
    ctx.markSaved();
    setPublished(
      action === "publish"
        ? "Published. Assign it to a tenant and price it (step 6) before learners can find it."
        : "Unpublished — back to draft. Existing enrolments are untouched.",
    );
    await ctx.reloadCourse();
    await ctx.reloadReadiness();
  }

  async function duplicate() {
    if (!course) return;
    setBusy(true);
    ctx.setError(null);
    const resp = await sendJson(`/api/bff/courses/${ctx.courseId}/duplicate`, "POST", {
      title: `${course.title} (copy)`,
    });
    setBusy(false);
    if (!resp.ok) {
      ctx.setError(await readError(resp, "The course could not be duplicated."));
      return;
    }
    const copy = (await resp.json()) as CourseItem;
    router.push(`/admin/courses/${copy.id}/edit?step=1`);
  }

  return (
    <WizardShell
      step={7}
      stepStates={stepStates}
      onStep={onStep}
      savedAt={savedAt}
      error={error}
      notice={notice}
      title="Review & publish"
      intro="Everything the server checks before it will accept a publish, listed before you press the button."
      onBack={() => onStep(6)}
      onContinue={() => router.push("/admin/courses")}
      continueLabel="Done — back to courses"
    >
      {readiness === null || course === null ? (
        <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>Loading readiness…</p>
      ) : (
        <>
          <ReadinessPanel readiness={readiness} />

          {published ? (
            <div className="callout callout--done mt-5">
              <b>{course.state === "published" ? "Published" : "Unpublished"}</b>
              <p style={{ fontSize: "0.8125rem" }}>{published}</p>
            </div>
          ) : null}

          <div className="mt-6 flex flex-wrap items-center gap-3">
            {ctx.canPublish ? (
              course.state === "published" ? (
                <button
                  type="button"
                  className="btn btn--ghost"
                  disabled={busy}
                  onClick={() => void togglePublish()}
                >
                  Unpublish
                </button>
              ) : (
                <button
                  type="button"
                  className="btn btn--primary btn--lg"
                  disabled={busy || !readiness.publishable}
                  onClick={() => void togglePublish()}
                >
                  Publish this course
                </button>
              )
            ) : null}

            <button
              type="button"
              className="btn btn--ghost"
              disabled={busy || !ctx.canEdit}
              onClick={() => void duplicate()}
            >
              Duplicate as template
            </button>
          </div>

          {!ctx.canPublish ? (
            <div className="callout callout--warn mt-4">
              <b>Hand off to an admin — you don&apos;t hold course:publish.</b>
              <p style={{ fontSize: "0.8125rem" }}>
                The course is saved and ready; an administrator can publish it from this screen.
              </p>
            </div>
          ) : !readiness.publishable ? (
            <p className="mt-3" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
              Publishing stays disabled while a blocker is outstanding — the server would refuse it
              anyway.
            </p>
          ) : null}
        </>
      )}
    </WizardShell>
  );
}
