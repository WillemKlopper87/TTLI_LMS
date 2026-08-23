"use client";

/**
 * `GET /courses/{id}/readiness` rendered in the prototype's `.reqs` idiom.
 *
 * The endpoint is the same truth `publish_course` enforces, extracted so it
 * can be *seen* before the button is pressed — this panel never decides
 * anything. Blockers are what the server will actually refuse on; warnings
 * and info are advice (missing captions, no free-preview lesson, not
 * sellable yet) that never blocks a publish.
 */

import type { ReactNode } from "react";

import type { Readiness, ReadinessCheck, ReadinessLevel } from "./types";
import { formatMinutes } from "./wizard-api";

const GROUPS: { level: ReadinessLevel; heading: string }[] = [
  { level: "blocker", heading: "Blockers" },
  { level: "warning", heading: "Warnings" },
  { level: "info", heading: "Info" },
];

function mark(check: ReadinessCheck): string {
  if (check.ok) return "✓";
  return check.level === "blocker" ? "!" : "○";
}

export function ReadinessPanel({
  readiness,
  actions,
}: {
  readiness: Readiness;
  /** Keyed by check code, rendered next to an unmet check's row. Optional
      — the panel still renders nothing here on its own, it only reserves
      the slot; the caller decides what (if anything) fixing a check
      looks like. Kept out of course_wizard.py entirely: this is a UI
      convenience action, not a server-enforced rule. */
  actions?: Partial<Record<string, ReactNode>>;
}) {
  return (
    <div className="flex flex-col gap-5">
      <div>
        <div className="flex items-baseline justify-between gap-3">
          <p className="eyebrow">Readiness score</p>
          <span
            className="serif"
            style={{ fontSize: "1.5rem", fontVariantNumeric: "tabular-nums" }}
          >
            {readiness.score}%
          </span>
        </div>
        <div className={`bar mt-2${readiness.publishable ? " bar--done" : ""}`}>
          <i style={{ width: `${Math.max(0, Math.min(100, readiness.score))}%` }} />
        </div>
        <p className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
          {readiness.publishable
            ? "Everything the server checks at publish time passes."
            : "At least one blocker below will refuse a publish."}
        </p>
      </div>

      <dl className="stats" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
        <div className="stat">
          <dt>Modules</dt>
          <dd>{readiness.module_count}</dd>
        </div>
        <div className="stat">
          <dt>Lessons</dt>
          <dd>{readiness.lesson_count}</dd>
        </div>
        <div className="stat">
          <dt>Estimated duration</dt>
          <dd>{formatMinutes(readiness.estimated_minutes)}</dd>
        </div>
      </dl>

      {GROUPS.map((group) => {
        const checks = readiness.checks.filter((c) => c.level === group.level);
        if (checks.length === 0) return null;
        const met = checks.filter((c) => c.ok).length;
        return (
          <div key={group.level} className="reqs">
            <div className="reqs-head">
              <h4>{group.heading}</h4>
              <span
                className={`tag ${
                  met === checks.length
                    ? "tag--done"
                    : group.level === "blocker"
                      ? "tag--stop"
                      : "tag--mute"
                }`}
              >
                {met} of {checks.length} met
              </span>
            </div>
            {checks.map((check) => (
              <div key={check.code} className={`req${check.ok ? " met" : ""}`}>
                <span className="mk">{mark(check)}</span>
                <span className="lbl">{check.message}</span>
                {!check.ok && actions?.[check.code] ? actions[check.code] : (
                  <span className="val">{check.code}</span>
                )}
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}
