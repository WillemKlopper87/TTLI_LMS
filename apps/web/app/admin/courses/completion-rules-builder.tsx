"use client";

/**
 * The completion-rules builder — the UI for the platform's anti-bypass
 * engine (`apps/api/src/services/completion.py`), which until now was
 * authorable only by hand-writing JSON at the API.
 *
 * Each rule is an "apply" checkbox plus its value, because an *absent*
 * field and a zero-valued one mean different things to the engine: absent
 * = the rule does not apply, present = it must be satisfied. Minimum time
 * is entered in minutes and stored in seconds, the unit the engine uses.
 * The server re-validates the whole shape on write and its refusal text is
 * what the caller shows.
 */

import { useEffect, useState } from "react";

import type { CompletionRules } from "./types";

type RuleKey =
  | "minimum_time_seconds"
  | "video_watch_percentage"
  | "quiz_pass_score"
  | "quiz_max_attempts"
  | "survey_required"
  | "assignment_approval_required";

interface RuleField {
  key: RuleKey;
  label: string;
  kind: "minutes" | "percent" | "count" | "bool";
  fallback: number;
  hint: string;
}

const RULE_FIELDS: RuleField[] = [
  {
    key: "minimum_time_seconds",
    label: "Minimum time in the lesson",
    kind: "minutes",
    fallback: 10,
    hint: "Server-assigned timestamps only — the client never asserts elapsed time.",
  },
  {
    key: "video_watch_percentage",
    label: "Video watched",
    kind: "percent",
    fallback: 80,
    hint: "Measured from heartbeats and the seek ceiling, not from the player's own claim.",
  },
  {
    key: "quiz_pass_score",
    label: "Quiz pass score",
    kind: "percent",
    fallback: 70,
    hint: "The lesson's attached quiz must be passed at this score.",
  },
  {
    key: "quiz_max_attempts",
    label: "Maximum quiz attempts",
    kind: "count",
    fallback: 3,
    hint: "Attempts beyond this are refused.",
  },
  {
    key: "survey_required",
    label: "Survey submitted",
    kind: "bool",
    fallback: 1,
    hint: "The lesson's attached survey must be answered.",
  },
  {
    key: "assignment_approval_required",
    label: "Assignment approved by a reviewer",
    kind: "bool",
    fallback: 1,
    hint: "Submission alone is not enough — a grader must approve it.",
  },
];

function unitLabel(kind: RuleField["kind"]): string {
  if (kind === "minutes") return "minutes";
  if (kind === "percent") return "%";
  if (kind === "count") return "attempts";
  return "";
}

function toFormValue(field: RuleField, rules: CompletionRules): number {
  const raw = rules[field.key];
  if (raw === null || raw === undefined) return field.fallback;
  if (field.kind === "minutes") return Math.max(1, Math.round(Number(raw) / 60));
  if (field.kind === "bool") return 1;
  return Number(raw);
}

function isApplied(field: RuleField, rules: CompletionRules): boolean {
  const raw = rules[field.key];
  return raw !== null && raw !== undefined && raw !== false;
}

export function buildRules(
  applied: Record<RuleKey, boolean>,
  values: Record<RuleKey, number>,
): CompletionRules {
  const out: CompletionRules = {};
  for (const field of RULE_FIELDS) {
    if (!applied[field.key]) continue;
    if (field.kind === "bool") {
      out[field.key] = true as never;
    } else if (field.kind === "minutes") {
      out.minimum_time_seconds = Math.max(1, Math.round(values[field.key])) * 60;
    } else {
      out[field.key] = Math.max(0, Math.round(values[field.key])) as never;
    }
  }
  return out;
}

/** The plain-English sentence the design doc asks for — the same truth the
 * learner's `.reqs` panel will show, stated before it is saved. */
export function describeRules(rules: CompletionRules): string {
  const clauses: string[] = [];
  if (rules.minimum_time_seconds) {
    clauses.push(`spend at least ${Math.round(rules.minimum_time_seconds / 60)} minutes in it`);
  }
  if (rules.video_watch_percentage) {
    clauses.push(`watch ${rules.video_watch_percentage}% of the video`);
  }
  if (rules.quiz_pass_score) {
    clauses.push(`pass the quiz at ${rules.quiz_pass_score}%`);
  }
  if (rules.quiz_max_attempts) {
    clauses.push(`do so within ${rules.quiz_max_attempts} attempts`);
  }
  if (rules.survey_required) clauses.push("submit the survey");
  if (rules.assignment_approval_required) clauses.push("have their assignment approved");
  if (clauses.length === 0) {
    return "No rules apply — opening a lesson is enough to complete it.";
  }
  const last = clauses.pop() as string;
  const joined = clauses.length ? `${clauses.join(", ")} and ${last}` : last;
  return `Learners must ${joined}.`;
}

export function summariseRules(rules: CompletionRules): string {
  const bits: string[] = [];
  if (rules.minimum_time_seconds) bits.push(`${Math.round(rules.minimum_time_seconds / 60)}m`);
  if (rules.video_watch_percentage) bits.push(`watch ${rules.video_watch_percentage}%`);
  if (rules.quiz_pass_score) bits.push(`quiz ${rules.quiz_pass_score}%`);
  if (rules.quiz_max_attempts) bits.push(`${rules.quiz_max_attempts} attempts`);
  if (rules.survey_required) bits.push("survey");
  if (rules.assignment_approval_required) bits.push("approval");
  return bits.length ? bits.join(" · ") : "—";
}

export function CompletionRulesBuilder({
  value,
  onSave,
  saveLabel = "Save rules",
  error,
}: {
  value: CompletionRules;
  onSave: (rules: CompletionRules) => Promise<void>;
  saveLabel?: string;
  error?: string | null;
}) {
  const [applied, setApplied] = useState<Record<RuleKey, boolean>>(() =>
    Object.fromEntries(RULE_FIELDS.map((f) => [f.key, isApplied(f, value)])) as Record<
      RuleKey,
      boolean
    >,
  );
  const [values, setValues] = useState<Record<RuleKey, number>>(() =>
    Object.fromEntries(RULE_FIELDS.map((f) => [f.key, toFormValue(f, value)])) as Record<
      RuleKey,
      number
    >,
  );
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setApplied(
      Object.fromEntries(RULE_FIELDS.map((f) => [f.key, isApplied(f, value)])) as Record<
        RuleKey,
        boolean
      >,
    );
    setValues(
      Object.fromEntries(RULE_FIELDS.map((f) => [f.key, toFormValue(f, value)])) as Record<
        RuleKey,
        number
      >,
    );
  }, [value]);

  const draft = buildRules(applied, values);

  async function save() {
    setBusy(true);
    await onSave(draft);
    setBusy(false);
  }

  return (
    <div>
      <div className="reqs">
        <div className="reqs-head">
          <h4>Completion rules</h4>
          <span className="tag tag--mute">
            {Object.values(applied).filter(Boolean).length} applied
          </span>
        </div>
        {RULE_FIELDS.map((field) => (
          <div key={field.key} className={`req${applied[field.key] ? " met" : ""}`}>
            <span className="mk">
              <input
                type="checkbox"
                aria-label={`Apply: ${field.label}`}
                checked={applied[field.key]}
                onChange={(e) =>
                  setApplied((prev) => ({ ...prev, [field.key]: e.target.checked }))
                }
              />
            </span>
            <span className="lbl">
              {field.label}
              <span className="block" style={{ fontSize: "0.6875rem", color: "var(--faint)" }}>
                {field.hint}
              </span>
            </span>
            <span className="val">
              {field.kind === "bool" ? (
                applied[field.key] ? (
                  "required"
                ) : (
                  "—"
                )
              ) : (
                <>
                  <input
                    className="input"
                    type="number"
                    min={field.kind === "percent" ? 0 : 1}
                    max={field.kind === "percent" ? 100 : undefined}
                    aria-label={`${field.label} value`}
                    disabled={!applied[field.key]}
                    style={{ maxWidth: "5rem", padding: "0.15rem 0.35rem" }}
                    value={values[field.key]}
                    onChange={(e) =>
                      setValues((prev) => ({
                        ...prev,
                        [field.key]: Number(e.target.value) || 0,
                      }))
                    }
                  />{" "}
                  {unitLabel(field.kind)}
                </>
              )}
            </span>
          </div>
        ))}
      </div>

      <div className="callout mt-3">
        <b>What this means</b>
        <p style={{ fontSize: "0.8125rem" }}>{describeRules(draft)}</p>
      </div>

      {error ? (
        <div className="callout callout--warn mt-3" role="alert">
          <p style={{ fontSize: "0.8125rem" }}>{error}</p>
        </div>
      ) : null}

      <button type="button" className="btn btn--primary mt-3" disabled={busy} onClick={save}>
        {saveLabel}
      </button>
    </div>
  );
}
