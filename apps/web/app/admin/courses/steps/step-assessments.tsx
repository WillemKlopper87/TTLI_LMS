"use client";

/**
 * Step 4 — Assessments & completion rules.
 *
 * Course-level defaults on top, per-lesson overrides below. The override is
 * merged per-field, never wholesale (services/completion.py::merge_rules):
 * a lesson that sets only `quiz_pass_score` still inherits the course's
 * `minimum_time_seconds`. That is why the table shows the lesson's own
 * rules, not the merged result — it is what the author is editing.
 */

import { useState } from "react";

import { CompletionRulesBuilder, describeRules, summariseRules } from "../completion-rules-builder";
import { type CompletionRules, primaryActivityType } from "../types";
import { readError, sendJson } from "../wizard-api";
import { type StepProps, WizardShell } from "../wizard-shell";

export function StepAssessments({ ctx, stepStates, onStep, savedAt, error, notice }: StepProps) {
  const course = ctx.course;
  const outline = ctx.outline;
  const [ruleError, setRuleError] = useState<string | null>(null);
  const [openLessonId, setOpenLessonId] = useState<string | null>(null);

  const rows = (outline?.modules ?? []).flatMap((m) =>
    m.lessons.map((l) => ({ module: m.module, ...l })),
  );

  async function saveCourseRules(rules: CompletionRules) {
    if (!ctx.courseId) return;
    setRuleError(null);
    const resp = await sendJson(`/api/bff/courses/${ctx.courseId}`, "PATCH", {
      completion_rules: rules,
    });
    if (!resp.ok) {
      // COURSE_AUTHORING_ERROR carries the engine's own reason for
      // refusing a shape — shown inline rather than replaced.
      setRuleError(await readError(resp, "Those rules could not be saved."));
      return;
    }
    ctx.markSaved();
    ctx.setSkip("rules", false);
    await ctx.reloadCourse();
    await ctx.reloadReadiness();
  }

  async function saveLessonRules(lessonId: string, rules: CompletionRules) {
    setRuleError(null);
    const resp = await sendJson(`/api/bff/lessons/${lessonId}`, "PATCH", {
      completion_rules: rules,
    });
    if (!resp.ok) {
      setRuleError(await readError(resp, "That override could not be saved."));
      return;
    }
    ctx.markSaved();
    await ctx.reloadOutline();
    await ctx.reloadReadiness();
  }

  return (
    <WizardShell
      step={4}
      stepStates={stepStates}
      onStep={onStep}
      savedAt={savedAt}
      error={error}
      notice={notice}
      title="Assessments & completion rules"
      intro="What a learner must actually do before a lesson counts as complete. The server is the only thing that decides this — the player never does."
      onBack={() => onStep(3)}
      onContinue={() => onStep(5)}
    >
      {course === null ? (
        <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>Loading…</p>
      ) : (
        <>
          <section>
            <p className="eyebrow">Course default</p>
            <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
              Applies to every lesson unless that lesson overrides the field below.
            </p>
            <div className="mt-3">
              <CompletionRulesBuilder
                value={course.completion_rules}
                onSave={saveCourseRules}
                saveLabel="Save course rules"
                error={ruleError}
              />
            </div>
            <button
              type="button"
              className="btn btn--quiet mt-3"
              onClick={() => {
                ctx.setSkip("rules", true);
                ctx.setNotice(
                  "Marked as deliberately rule-free — opening a lesson will be enough to complete it.",
                );
              }}
            >
              This course needs no rules — skip
            </button>
          </section>

          <section className="mt-8">
            <p className="eyebrow">Per-lesson overrides</p>
            <div className="tablewrap mt-3">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Lesson</th>
                    <th scope="col">Type</th>
                    <th scope="col">Own rules</th>
                    <th scope="col" />
                  </tr>
                </thead>
                <tbody>
                  {rows.length === 0 ? (
                    <tr>
                      <td colSpan={4} style={{ color: "var(--muted)" }}>
                        No lessons yet.
                      </td>
                    </tr>
                  ) : null}
                  {rows.map((row) => (
                    <tr key={row.lesson.id}>
                      <td>
                        <b>{row.lesson.title}</b>
                        <div style={{ fontSize: "0.6875rem", color: "var(--faint)" }}>
                          {row.module.title}
                        </div>
                        {openLessonId === row.lesson.id ? (
                          <div className="mt-3" style={{ maxWidth: "38rem" }}>
                            <CompletionRulesBuilder
                              value={row.lesson.completion_rules}
                              onSave={(rules) => saveLessonRules(row.lesson.id, rules)}
                              saveLabel="Save override"
                              error={ruleError}
                            />
                          </div>
                        ) : null}
                      </td>
                      <td>
                        <span className="tag tag--mute">{primaryActivityType(row.lesson)}</span>
                      </td>
                      <td className="mono" style={{ fontSize: "0.6875rem" }}>
                        {summariseRules(row.lesson.completion_rules)}
                      </td>
                      <td>
                        <button
                          type="button"
                          className="btn btn--ghost"
                          disabled={!ctx.canEdit}
                          onClick={() =>
                            setOpenLessonId(openLessonId === row.lesson.id ? null : row.lesson.id)
                          }
                        >
                          {openLessonId === row.lesson.id ? "Close" : "Override…"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-3" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
              Course default: {describeRules(course.completion_rules)}
            </p>
          </section>
        </>
      )}
    </WizardShell>
  );
}
