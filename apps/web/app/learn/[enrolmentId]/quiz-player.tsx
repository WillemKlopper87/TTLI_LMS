"use client";

import { useEffect, useState } from "react";

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
}

interface QuizResult {
  attempt_id: string;
  score: string;
  passed: boolean | null;
}

/**
 * Quiz-taking (03 §6.5, REQ-ASSESS-01/02/03). Correct answers never
 * appear in the fetched attempt — the server grades on submit.
 */
export function QuizPlayer({ quizId, onGraded }: { quizId: string; onGraded: () => void }) {
  const [attempt, setAttempt] = useState<QuizAttempt | null>(null);
  const [answers, setAnswers] = useState<Record<string, string[] | string>>({});
  const [result, setResult] = useState<QuizResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
      if (!cancelled) setAttempt(await resp.json());
    }
    start();
    return () => {
      cancelled = true;
    };
  }, [quizId]);

  function setChoice(questionId: string, optionId: string, multi: boolean) {
    setAnswers((prev) => {
      if (!multi) return { ...prev, [questionId]: [optionId] };
      const current = new Set((prev[questionId] as string[] | undefined) ?? []);
      if (current.has(optionId)) current.delete(optionId);
      else current.add(optionId);
      return { ...prev, [questionId]: Array.from(current) };
    });
  }

  function setText(questionId: string, value: string) {
    setAnswers((prev) => ({ ...prev, [questionId]: value }));
  }

  async function submit() {
    if (!attempt) return;
    setBusy(true);
    setError(null);
    const token = getAccessToken();
    const resp = await fetch(`/api/bff/quiz-attempts/${attempt.attempt_id}/submit`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({
        answers: attempt.questions.map((q) => {
          const value = answers[q.question_id];
          const isText = q.question_type === "short_text" || q.question_type === "long_text";
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
      setError("Could not submit this attempt.");
      return;
    }
    setResult(await resp.json());
    onGraded();
  }

  if (error) return <p role="alert" style={{ fontSize: "0.8125rem", color: "var(--stop)" }}>{error}</p>;
  if (result) {
    return (
      <div className="card mt-3">
        <p style={{ fontSize: "0.9375rem", fontWeight: 600 }}>Score: {result.score}%</p>
        <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
          {result.passed === null
            ? "Awaiting manual grading of open-ended answers."
            : result.passed
              ? "Passed."
              : "Not yet passed — check the attempt limit before retrying."}
        </p>
      </div>
    );
  }
  if (!attempt) return <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>Loading quiz…</p>;

  return (
    <div className="card mt-3 flex flex-col gap-4">
      {attempt.questions.map((q) => (
        <div key={q.question_id}>
          <p style={{ fontSize: "0.875rem", fontWeight: 600 }}>{q.prompt}</p>
          {q.question_type === "short_text" || q.question_type === "long_text" ? (
            <textarea
              className="input mt-2"
              rows={q.question_type === "long_text" ? 4 : 1}
              aria-label={q.prompt}
              onChange={(e) => setText(q.question_id, e.target.value)}
            />
          ) : (
            <div className="mt-2 flex flex-col gap-1">
              {q.options.map((o) => (
                <label key={o.id} className="flex items-center gap-2" style={{ fontSize: "0.8125rem" }}>
                  <input
                    type={q.question_type === "multiple_choice" ? "checkbox" : "radio"}
                    name={q.question_id}
                    onChange={() =>
                      setChoice(q.question_id, o.id, q.question_type === "multiple_choice")
                    }
                  />
                  {o.text}
                </label>
              ))}
            </div>
          )}
        </div>
      ))}
      {error ? <p role="alert" style={{ fontSize: "0.8125rem", color: "var(--stop)" }}>{error}</p> : null}
      <button type="button" disabled={busy} onClick={submit} className="btn btn--primary">
        Submit quiz
      </button>
    </div>
  );
}
