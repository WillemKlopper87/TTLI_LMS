"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { formatClock } from "@/lib/format";
import { getAccessToken } from "@/lib/session";

interface QuizQuestionView {
  question_id: string;
  question_type: string;
  prompt: string;
  options: { id: string; text: string }[];
  points: number;
}

interface QuizAttempt {
  attempt_id: string;
  quiz_id: string;
  attempt_number: number;
  time_limit_seconds: number | null;
  questions: QuizQuestionView[];
  quiz_title?: string | null;
  pass_score?: number | null;
  max_attempts?: number | null;
  randomise_questions?: boolean;
  randomise_options?: boolean;
  attempts_remaining?: number | null;
}

interface QuizResult {
  attempt_id: string;
  score: string;
  passed: boolean | null;
}

const OPTION_KEYS = "ABCDEFGH";
const TEXT_TYPES = new Set(["short_text", "long_text"]);

/**
 * Quiz-taking (03 §6.5, REQ-ASSESS-01/02/03) as the prototype's
 * assessment screen: one question on screen at a time, lettered options,
 * and the attempt/pass-mark facts a learner needs before answering.
 *
 * Correct answers never appear in the fetched attempt — the server
 * grades on submit, and a timed attempt submits itself at zero rather
 * than letting the clock run out silently.
 */
export function QuizPlayer({
  quizId,
  courseTitle,
  moduleTitle,
  onGraded,
}: {
  quizId: string;
  courseTitle?: string;
  moduleTitle?: string;
  onGraded: () => void;
}) {
  const [attempt, setAttempt] = useState<QuizAttempt | null>(null);
  const [answers, setAnswers] = useState<Record<string, string[] | string>>({});
  const [result, setResult] = useState<QuizResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [index, setIndex] = useState(0);
  const [remaining, setRemaining] = useState<number | null>(null);
  const submittedRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    async function start() {
      const token = getAccessToken();
      const resp = await fetch(`/api/bff/quizzes/${quizId}/attempts`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!resp.ok) {
        if (!cancelled) setError("This quiz could not be started.");
        return;
      }
      const body: QuizAttempt = await resp.json();
      if (cancelled) return;
      setAttempt(body);
      setRemaining(body.time_limit_seconds ?? null);
    }
    void start();
    return () => {
      cancelled = true;
    };
  }, [quizId]);

  const submit = useCallback(async () => {
    if (!attempt || submittedRef.current) return;
    submittedRef.current = true;
    setBusy(true);
    setError(null);
    const token = getAccessToken();
    const resp = await fetch(`/api/bff/quiz-attempts/${attempt.attempt_id}/submit`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({
        answers: attempt.questions.map((q) => {
          const value = answers[q.question_id];
          const isText = TEXT_TYPES.has(q.question_type);
          return {
            question_id: q.question_id,
            selected_option_ids: isText ? null : ((value as string[] | undefined) ?? []),
            text_answer: isText ? ((value as string | undefined) ?? "") : null,
          };
        }),
      }),
    });
    setBusy(false);
    if (!resp.ok) {
      submittedRef.current = false;
      setError("Could not submit this attempt.");
      return;
    }
    setResult(await resp.json());
    onGraded();
  }, [attempt, answers, onGraded]);

  // A timed attempt submits what exists at zero — the server's limit is
  // the real one, so running out must not silently discard the answers.
  useEffect(() => {
    if (remaining === null || result !== null) return;
    if (remaining <= 0) {
      void submit();
      return;
    }
    const id = setTimeout(() => setRemaining((r) => (r === null ? null : r - 1)), 1000);
    return () => clearTimeout(id);
  }, [remaining, result, submit]);

  function setChoice(questionId: string, optionId: string, multi: boolean) {
    setAnswers((prev) => {
      if (!multi) return { ...prev, [questionId]: [optionId] };
      const current = new Set((prev[questionId] as string[] | undefined) ?? []);
      if (current.has(optionId)) current.delete(optionId);
      else current.add(optionId);
      return { ...prev, [questionId]: Array.from(current) };
    });
  }

  if (error && !attempt) {
    return (
      <p className="callout callout--stop" role="alert">
        {error}
      </p>
    );
  }

  if (result) {
    const tone = result.passed === null ? "" : result.passed ? " callout--done" : " callout--stop";
    return (
      <div className={`callout${tone}`}>
        <b>Score: {result.score}%</b>
        {result.passed === null
          ? "Awaiting manual grading of open-ended answers."
          : result.passed
            ? "Passed."
            : "Not yet passed — check the attempt limit before retrying."}
      </div>
    );
  }

  if (!attempt) return <p style={{ color: "var(--muted)" }}>Loading the assessment…</p>;

  const total = attempt.questions.length;
  const question = attempt.questions[index];
  const isText = TEXT_TYPES.has(question.question_type);
  const multi = question.question_type === "multiple_choice";
  const selected = (answers[question.question_id] as string[] | undefined) ?? [];
  const last = index === total - 1;
  const randomised = attempt.randomise_questions || attempt.randomise_options;

  return (
    <div className="quizwrap">
      <div>
        {courseTitle || moduleTitle ? (
          <p className="eyebrow">{[courseTitle, moduleTitle].filter(Boolean).join(" · ")}</p>
        ) : null}
        <h2 className="serif" style={{ fontSize: "1.5rem", marginTop: ".35rem" }}>
          {attempt.quiz_title ?? "Assessment"}
        </h2>
      </div>

      <div className="quiz-meta">
        <span>
          Question {index + 1} of {total}
        </span>
        <span>
          {attempt.max_attempts
            ? `Attempt ${attempt.attempt_number} of ${attempt.max_attempts}`
            : `Attempt ${attempt.attempt_number}`}
          {attempt.pass_score != null ? ` · Pass mark ${attempt.pass_score}%` : ""}
        </span>
        {remaining !== null ? (
          <span className="tag tag--live mono">{formatClock(remaining)} remaining</span>
        ) : null}
      </div>

      <span
        className="bar"
        role="progressbar"
        aria-valuenow={index + 1}
        aria-valuemin={1}
        aria-valuemax={total}
        aria-label="Assessment progress"
      >
        <i style={{ width: `${((index + 1) / total) * 100}%` }} />
      </span>

      <div className="qcard">
        <h3 className="serif">{question.prompt}</h3>

        {isText ? (
          <textarea
            className="input"
            rows={question.question_type === "long_text" ? 5 : 2}
            aria-label={question.prompt}
            value={(answers[question.question_id] as string | undefined) ?? ""}
            onChange={(e) =>
              setAnswers((prev) => ({ ...prev, [question.question_id]: e.target.value }))
            }
          />
        ) : (
          <div className="opts">
            {question.options.map((option, i) => {
              const on = selected.includes(option.id);
              return (
                <button
                  key={option.id}
                  type="button"
                  className="opt"
                  aria-pressed={on}
                  onClick={() => setChoice(question.question_id, option.id, multi)}
                >
                  <span className="key" aria-hidden="true">
                    {OPTION_KEYS[i] ?? i + 1}
                  </span>
                  <span>{option.text}</span>
                </button>
              );
            })}
          </div>
        )}
        {multi ? (
          <p style={{ fontSize: ".75rem", color: "var(--muted)" }}>Select every answer that applies.</p>
        ) : null}
      </div>

      {randomised ? (
        <div className="callout">
          <b>Question order is randomised</b>
          Questions and options are drawn in a different order for every attempt, so answers cannot
          usefully be shared between colleagues.
        </div>
      ) : null}

      {error ? (
        <p className="callout callout--stop" role="alert">
          {error}
        </p>
      ) : null}

      <div className="foot-nav">
        <button
          type="button"
          className="btn btn--ghost"
          disabled={index === 0}
          onClick={() => setIndex((i) => Math.max(0, i - 1))}
        >
          ← Previous
        </button>
        {last ? (
          <button type="button" className="btn btn--primary" disabled={busy} onClick={submit}>
            {busy ? "Submitting…" : "Submit answers"}
          </button>
        ) : (
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => setIndex((i) => Math.min(total - 1, i + 1))}
          >
            Next question →
          </button>
        )}
      </div>
    </div>
  );
}
