"use client";

/**
 * Step 1 — Basics. The only step that can run without a course id: the
 * first save is `POST /courses` (which auto-slugs), and from then on the
 * course id anchors the whole wizard in the URL, which is what makes the
 * flow resumable without any wizard-session store.
 *
 * Autosave is a real `PATCH /courses/{id}` on blur — there is no draft
 * buffer anywhere, because `state="draft"` already is the draft mechanism
 * (a course is invisible and unsellable until published *and* assigned
 * *and* wrapped in an active priced product).
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import {
  COURSE_FORMATS,
  COURSE_LEVELS,
  type CourseItem,
  HERO_COLOURS,
} from "../types";
import { readError, sendJson } from "../wizard-api";
import { type StepProps, WizardShell } from "../wizard-shell";

interface Draft {
  title: string;
  summary: string;
  description: string;
  level: string;
  topic: string;
  format: string;
  outcomes: string[];
  includes_workshop: boolean;
  hero_colour: string;
}

function draftFrom(course: CourseItem | null): Draft {
  return {
    title: course?.title ?? "",
    summary: course?.summary ?? "",
    description: course?.description ?? "",
    level: course?.level ?? "",
    topic: course?.topic ?? "",
    format: course?.format ?? "",
    outcomes: course?.outcomes ?? [],
    includes_workshop: course?.includes_workshop ?? false,
    hero_colour: course?.hero_colour ?? HERO_COLOURS[0],
  };
}

function payloadFrom(draft: Draft): Record<string, unknown> {
  return {
    title: draft.title.trim(),
    summary: draft.summary.trim() || null,
    description: draft.description.trim() || null,
    level: draft.level || null,
    topic: draft.topic.trim() || null,
    format: draft.format || null,
    outcomes: draft.outcomes.map((o) => o.trim()).filter(Boolean),
    includes_workshop: draft.includes_workshop,
    hero_colour: draft.hero_colour || null,
  };
}

export function StepBasics({ ctx, stepStates, onStep, savedAt, error, notice }: StepProps) {
  const router = useRouter();
  const [draft, setDraft] = useState<Draft>(() => draftFrom(ctx.course));
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (ctx.course) setDraft(draftFrom(ctx.course));
  }, [ctx.course]);

  function set<K extends keyof Draft>(key: K, value: Draft[K]) {
    setDraft((prev) => ({ ...prev, [key]: value }));
  }

  /** PATCH on blur. Silent when there is no course yet — the first write is
   * deliberately the explicit "Create & continue" below. Callers that
   * change state and save in the same handler pass the new draft
   * explicitly: `draft` in this closure is still the pre-change value. */
  async function autosave(next: Draft = draft) {
    if (!ctx.courseId || !ctx.canEdit || !next.title.trim()) return;
    const resp = await sendJson(`/api/bff/courses/${ctx.courseId}`, "PATCH", payloadFrom(next));
    if (!resp.ok) {
      ctx.setError(await readError(resp, "The course could not be saved."));
      return;
    }
    ctx.setError(null);
    ctx.markSaved();
    await ctx.reloadCourse();
  }

  async function createCourse() {
    setBusy(true);
    ctx.setError(null);
    const resp = await sendJson("/api/bff/courses", "POST", {
      ...payloadFrom(draft),
      completion_rules: {},
    });
    setBusy(false);
    if (!resp.ok) {
      ctx.setError(await readError(resp, "The course could not be created."));
      return;
    }
    const created = (await resp.json()) as CourseItem;
    router.push(`/admin/courses/${created.id}/edit?step=2`);
  }

  async function continueOn() {
    if (!ctx.courseId) {
      await createCourse();
      return;
    }
    setBusy(true);
    await autosave();
    setBusy(false);
    onStep(2);
  }

  const canContinue = draft.title.trim().length > 0 && ctx.canEdit && !busy;

  return (
    <WizardShell
      step={1}
      stepStates={stepStates}
      onStep={onStep}
      savedAt={savedAt}
      error={error}
      notice={notice}
      title="Basics"
      intro="What the course is, who it is for, and how it looks in the catalogue. Everything here is editable later."
      onContinue={continueOn}
      continueDisabled={!canContinue}
      continueLabel={ctx.courseId ? "Continue →" : "Create & continue →"}
    >
      {!ctx.canEdit ? (
        <div className="callout callout--warn">
          <b>Read-only</b>
          <p style={{ fontSize: "0.8125rem" }}>
            Hand off to an admin — you don&apos;t hold course:edit.
          </p>
        </div>
      ) : null}

      <div className="fields">
        <label>
          <b>Title</b>
          <input
            className="input"
            value={draft.title}
            disabled={!ctx.canEdit}
            placeholder="Leading Through Ambiguity"
            onChange={(e) => set("title", e.target.value)}
            onBlur={() => void autosave()}
          />
        </label>

        <label>
          <b>Summary</b>
          <input
            className="input"
            value={draft.summary}
            disabled={!ctx.canEdit}
            placeholder="One line for the catalogue card."
            onChange={(e) => set("summary", e.target.value)}
            onBlur={() => void autosave()}
          />
        </label>

        <label>
          <b>Description</b>
          <textarea
            className="input"
            rows={4}
            value={draft.description}
            disabled={!ctx.canEdit}
            placeholder="The full description shown on the programme page."
            onChange={(e) => set("description", e.target.value)}
            onBlur={() => void autosave()}
          />
        </label>
      </div>

      <div className="two mt-4">
        <label>
          <b>Level</b>
          <select
            className="input"
            value={draft.level}
            disabled={!ctx.canEdit}
            onChange={(e) => {
              const next = { ...draft, level: e.target.value };
              setDraft(next);
              void autosave(next);
            }}
          >
            <option value="">Not set</option>
            {COURSE_LEVELS.map((l) => (
              <option key={l.value} value={l.value}>
                {l.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <b>Format</b>
          <select
            className="input"
            value={draft.format}
            disabled={!ctx.canEdit}
            onChange={(e) => {
              const next = { ...draft, format: e.target.value };
              setDraft(next);
              void autosave(next);
            }}
          >
            <option value="">Not set</option>
            {COURSE_FORMATS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="two mt-4">
        <label>
          <b>Topic</b>
          <input
            className="input"
            value={draft.topic}
            disabled={!ctx.canEdit}
            placeholder="Leadership"
            onChange={(e) => set("topic", e.target.value)}
            onBlur={() => void autosave()}
          />
        </label>
        <label>
          <b>Includes a live workshop</b>
          <span className="flex items-center gap-2" style={{ fontSize: "0.8125rem" }}>
            <input
              type="checkbox"
              checked={draft.includes_workshop}
              disabled={!ctx.canEdit}
              onChange={(e) => {
                const next = { ...draft, includes_workshop: e.target.checked };
                setDraft(next);
                void autosave(next);
              }}
            />
            Shown as a catalogue facet
          </span>
        </label>
      </div>

      <div className="mt-6">
        <p className="eyebrow">Outcomes</p>
        <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
          What a learner can do afterwards. These are listed on the programme page.
        </p>
        <div className="mt-3 flex flex-col gap-2">
          {draft.outcomes.map((outcome, i) => (
            <div key={i} className="flex items-center gap-2">
              <span className="mono" style={{ color: "var(--faint)", fontSize: "0.75rem" }}>
                {i + 1}
              </span>
              <input
                className="input"
                value={outcome}
                disabled={!ctx.canEdit}
                aria-label={`Outcome ${i + 1}`}
                onChange={(e) =>
                  set(
                    "outcomes",
                    draft.outcomes.map((o, j) => (j === i ? e.target.value : o)),
                  )
                }
                onBlur={() => void autosave()}
              />
              <button
                type="button"
                className="btn btn--quiet"
                disabled={!ctx.canEdit || i === 0}
                title="Move up"
                onClick={() => {
                  const outcomes = [...draft.outcomes];
                  [outcomes[i - 1], outcomes[i]] = [outcomes[i], outcomes[i - 1]];
                  const next = { ...draft, outcomes };
                  setDraft(next);
                  void autosave(next);
                }}
              >
                ↑
              </button>
              <button
                type="button"
                className="btn btn--quiet"
                disabled={!ctx.canEdit || i === draft.outcomes.length - 1}
                title="Move down"
                onClick={() => {
                  const outcomes = [...draft.outcomes];
                  [outcomes[i], outcomes[i + 1]] = [outcomes[i + 1], outcomes[i]];
                  const next = { ...draft, outcomes };
                  setDraft(next);
                  void autosave(next);
                }}
              >
                ↓
              </button>
              <button
                type="button"
                className="btn btn--quiet"
                disabled={!ctx.canEdit}
                title="Remove"
                onClick={() => {
                  const next = { ...draft, outcomes: draft.outcomes.filter((_, j) => j !== i) };
                  setDraft(next);
                  void autosave(next);
                }}
              >
                ✕
              </button>
            </div>
          ))}
          <button
            type="button"
            className="btn btn--ghost"
            disabled={!ctx.canEdit}
            onClick={() => set("outcomes", [...draft.outcomes, ""])}
          >
            + Add an outcome
          </button>
        </div>
      </div>

      <div className="mt-6">
        <p className="eyebrow">Hero colour</p>
        <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
          The art block behind the course on the catalogue and programme pages.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          {HERO_COLOURS.map((colour) => (
            <button
              key={colour}
              type="button"
              aria-label={`Hero colour ${colour}`}
              aria-pressed={draft.hero_colour === colour}
              disabled={!ctx.canEdit}
              onClick={() => {
                const next = { ...draft, hero_colour: colour };
                setDraft(next);
                void autosave(next);
              }}
              style={{
                width: "2.4rem",
                height: "2.4rem",
                background: colour,
                border:
                  draft.hero_colour === colour
                    ? "3px solid var(--ink)"
                    : "1px solid var(--rule-2)",
                cursor: ctx.canEdit ? "pointer" : "default",
              }}
            />
          ))}
        </div>
      </div>
    </WizardShell>
  );
}
