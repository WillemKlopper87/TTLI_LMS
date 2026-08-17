"use client";

/**
 * Step 2 — Curriculum. Structure only: modules, lessons, their order and
 * their access level. Content (documents, video, quizzes) is step 3, which
 * is why a lesson created here always starts as a plain document — the API
 * deliberately keeps activity FKs owned by each subsystem's attach
 * endpoint.
 */

import { CurriculumOutline } from "../curriculum-outline";
import { formatMinutes } from "../wizard-api";
import { type StepProps, WizardShell } from "../wizard-shell";

export function StepCurriculum({ ctx, stepStates, onStep, savedAt, error, notice }: StepProps) {
  const outline = ctx.outline;
  const moduleCount = outline?.modules.length ?? 0;
  const emptyModules = (outline?.modules ?? []).filter((m) => m.lessons.length === 0).length;

  return (
    <WizardShell
      step={2}
      stepStates={stepStates}
      onStep={onStep}
      savedAt={savedAt}
      error={error}
      notice={notice}
      title="Curriculum"
      intro="Modules and lessons, in the order learners will meet them. Drag the ⋮⋮ handle to reorder — order is learner-facing, not cosmetic: prerequisites are walked in exactly this sequence."
      onBack={() => onStep(1)}
      onContinue={() => onStep(3)}
    >
      {outline === null ? (
        <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>Loading…</p>
      ) : (
        <>
          <dl className="stats" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
            <div className="stat">
              <dt>Modules</dt>
              <dd>{moduleCount}</dd>
            </div>
            <div className="stat">
              <dt>Lessons</dt>
              <dd>{outline.lesson_count}</dd>
            </div>
            <div className="stat">
              <dt>Estimated duration</dt>
              <dd>{formatMinutes(outline.estimated_minutes)}</dd>
            </div>
          </dl>

          {emptyModules > 0 ? (
            <div className="callout callout--warn mt-4">
              <b>
                {emptyModules} module{emptyModules === 1 ? "" : "s"} with no lessons
              </b>
              <p style={{ fontSize: "0.8125rem" }}>
                Publishing is refused while any module is empty — that check runs server-side.
              </p>
            </div>
          ) : null}

          <div className="mt-5">
            <CurriculumOutline
              courseId={ctx.courseId as string}
              outline={outline}
              canEdit={ctx.canEdit}
              onChanged={async () => {
                await ctx.reloadOutline();
                await ctx.reloadReadiness();
              }}
              onSaved={ctx.markSaved}
              onError={ctx.setError}
            />
          </div>
        </>
      )}
    </WizardShell>
  );
}
