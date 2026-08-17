"use client";

import type { CompletionCheck, LessonLockedError } from "./types";

/**
 * The prototype's `.reqs` and `.refusal` (design doc §4 screen 8) — the
 * visible half of REQ-BYPASS-01.
 *
 * Every row here is the server's own evaluation. Met rules stay on
 * screen rather than disappearing, so a learner can see what the
 * programme actually asks of them instead of only what they still owe.
 * When the API predates `checks`, the unmet reason strings are rendered
 * as unmet rows — fewer facts, never invented ones.
 */
export function RequirementsPanel({
  checks,
  unmetReasons,
}: {
  checks: CompletionCheck[] | undefined;
  unmetReasons: string[];
}) {
  const rows: CompletionCheck[] =
    checks && checks.length > 0
      ? checks
      : unmetReasons.map((reason) => ({
          rule: reason,
          met: false,
          reason,
          current: null,
          required: null,
        }));

  if (rows.length === 0) {
    return (
      <div className="reqs">
        <div className="reqs-head">
          <h3>Completion requirements</h3>
          <span className="tag tag--done">No rules</span>
        </div>
        <div className="req met">
          <span className="mk" aria-hidden="true">
            ✓
          </span>
          <span className="lbl">This lesson completes as soon as you mark it done.</span>
          <span className="val" />
        </div>
      </div>
    );
  }

  const met = rows.filter((r) => r.met).length;

  return (
    <div className="reqs">
      <div className="reqs-head">
        <h3>Completion requirements</h3>
        <span className={`tag ${met === rows.length ? "tag--done" : "tag--mute"}`}>
          {met} of {rows.length} met
        </span>
      </div>
      {rows.map((row, i) => (
        <div className={row.met ? "req met" : "req"} key={`${row.rule}-${i}`}>
          <span className="mk" aria-hidden="true">
            {row.met ? "✓" : "○"}
          </span>
          <span className="lbl">{row.reason}</span>
          <span className="val">
            {row.met
              ? "Done"
              : row.current && row.required
                ? `${row.current} / ${row.required}`
                : (row.current ?? "")}
          </span>
        </div>
      ))}
    </div>
  );
}

/** Shown only after the server has actually refused — never predicted. */
export function RefusalBox({ refusal, shake }: { refusal: LessonLockedError; shake: boolean }) {
  return (
    <div className={shake ? "refusal shake" : "refusal"} role="alert">
      <span className="code">423 · {refusal.code}</span>
      <p>{refusal.message}</p>
      {refusal.checks.length > 0 ? (
        <ul>
          {refusal.checks
            .filter((c) => !c.met)
            .map((c, i) => (
              <li key={`${c.rule}-${i}`}>
                <span aria-hidden="true">•</span>
                <span>{c.reason}</span>
              </li>
            ))}
        </ul>
      ) : null}
      <p className="src">Decision made server-side. The player never decides this.</p>
    </div>
  );
}
