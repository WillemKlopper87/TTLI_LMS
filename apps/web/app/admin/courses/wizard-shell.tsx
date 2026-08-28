"use client";

/**
 * The course wizard's frame (design doc §5 screen 15): a seven-circle step
 * rail on the left whose done/current/todo marks are derived from real data
 * — never from "which steps has this session visited" — and, on the right,
 * the step header (`Step n of 7` eyebrow, serif title, autosave stamp) and
 * the `.foot-nav` Back/Continue pair.
 *
 * `.step` is the prototype's rail circle. app/globals.css is owned by
 * another surface and does not currently carry it, so the geometry is
 * declared inline here; the class name stays so the shared rule takes over
 * unchanged the moment it lands.
 */

import { type CSSProperties, type ReactNode, useEffect, useState } from "react";

import type { StepState, WizardContext } from "./types";

export type { StepState };

export const WIZARD_STEPS = [
  { n: 1, label: "Basics" },
  { n: 2, label: "Curriculum" },
  { n: 3, label: "Content" },
  { n: 4, label: "Assessments & rules" },
  { n: 5, label: "Certification" },
  { n: 6, label: "Pricing & access" },
  { n: 7, label: "Review & publish" },
] as const;

export const STEP_COUNT = WIZARD_STEPS.length;

/** What every step component receives from the wizard host. Each step owns
 * its own `<WizardShell>` so it can decide what "Continue" means (a PATCH,
 * a POST-then-navigate, a publish). */
export interface StepProps {
  ctx: WizardContext;
  stepStates: StepState[];
  onStep: (n: number) => void;
  savedAt: number | null;
  error: string | null;
  notice: string | null;
}

/** "just now" for the first minute, then whole minutes — re-rendered on a
 * timer so the stamp doesn't silently go stale while the author works. */
function useSavedLabel(savedAt: number | null): string | null {
  // The tick state IS the clock the render reads — calling Date.now()
  // during render is impure (react-hooks/purity) and the compiler may
  // cache the result; keeping "now" in state makes the re-render carry
  // the new time instead of hoping the render re-reads the wall clock.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (savedAt === null) return;
    void (async () => {
      setNow(Date.now());
    })();
    const id = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(id);
  }, [savedAt]);
  if (savedAt === null) return null;
  const seconds = Math.max(0, Math.round((now - savedAt) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  return `${Math.round(minutes / 60)} h ago`;
}

export function WizardShell({
  step,
  stepStates,
  onStep,
  title,
  intro,
  savedAt,
  error,
  notice,
  onBack,
  onContinue,
  continueLabel = "Continue →",
  continueDisabled = false,
  children,
}: {
  step: number;
  stepStates: StepState[];
  onStep: (n: number) => void;
  title: string;
  intro?: ReactNode;
  savedAt: number | null;
  error?: string | null;
  notice?: string | null;
  onBack?: () => void;
  onContinue?: () => void;
  continueLabel?: string;
  continueDisabled?: boolean;
  children: ReactNode;
}) {
  const savedLabel = useSavedLabel(savedAt);

  return (
    <div className="wizard">
      <nav aria-label="Course setup steps">
        <p className="eyebrow">Course setup</p>
        <ol className="step-rail" style={{ marginTop: ".75rem" }}>
          {WIZARD_STEPS.map((s, i) => {
            const state: StepState = s.n === step ? "current" : (stepStates[i] ?? "todo");
            return (
              <li
                key={s.n}
                className="step-rail-item"
                aria-current={s.n === step ? "true" : undefined}
              >
                <button
                  type="button"
                  className="step"
                  data-state={state}
                  aria-current={s.n === step ? "true" : undefined}
                  aria-label={`Step ${s.n}: ${s.label}${state === "done" ? " (done)" : ""}`}
                  onClick={() => onStep(s.n)}
                >
                  {state === "done" ? "✓" : s.n}
                </button>
                <span>{s.label}</span>
              </li>
            );
          })}
        </ol>
      </nav>

      <section style={{ minWidth: 0 }}>
        <header>
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <p className="eyebrow">
              Step {step} of {STEP_COUNT}
            </p>
            {savedLabel ? (
              <p className="eyebrow" style={{ color: "var(--done)" }}>
                Saved · {savedLabel}
              </p>
            ) : null}
          </div>
          <h2 className="serif mt-1" style={{ fontSize: "1.35rem" }}>
            {title}
          </h2>
          {intro ? (
            <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
              {intro}
            </p>
          ) : null}
        </header>

        {error ? (
          <div className="callout callout--warn mt-4" role="alert">
            <b>That didn&apos;t save.</b>
            <p style={{ fontSize: "0.8125rem" }}>{error}</p>
          </div>
        ) : null}
        {notice ? (
          <div className="callout callout--done mt-4">
            <p style={{ fontSize: "0.8125rem" }}>{notice}</p>
          </div>
        ) : null}

        <div className="mt-5">{children}</div>

        <div className="foot-nav mt-8">
          <button
            type="button"
            className="btn btn--ghost"
            disabled={!onBack}
            onClick={() => onBack?.()}
          >
            ← Back
          </button>
          <button
            type="button"
            className="btn btn--primary"
            disabled={continueDisabled || !onContinue}
            onClick={() => onContinue?.()}
          >
            {continueLabel}
          </button>
        </div>
      </section>
    </div>
  );
}
