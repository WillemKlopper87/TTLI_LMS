"use client";

import { useEffect, useState } from "react";

import { authedFetch } from "@/lib/authed-fetch";

interface SurveyQuestionView {
  question_id: string;
  question_type: string;
  prompt: string;
  options: { id: string; text: string }[];
}

interface SurveyView {
  survey_id: string;
  title: string;
  response_mode: string;
  questions: SurveyQuestionView[];
}

/**
 * Survey response form (03 §6.6, REQ-ASSESS-05). `response_mode` is shown
 * to the learner so an anonymous survey reads as genuinely anonymous, not
 * as a UI detail nobody mentioned.
 */
export function SurveyForm({ surveyId, onSubmitted }: { surveyId: string; onSubmitted: () => void }) {
  const [survey, setSurvey] = useState<SurveyView | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const resp = await authedFetch(`/api/bff/surveys/${surveyId}`);
      if (!resp.ok) {
        if (!cancelled) setError("This survey could not be loaded.");
        return;
      }
      if (!cancelled) setSurvey(await resp.json());
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [surveyId]);

  async function submit() {
    if (!survey) return;
    setBusy(true);
    setError(null);
    const resp = await authedFetch(`/api/bff/surveys/${surveyId}/responses`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        answers: survey.questions.map((q) => ({
          question_id: q.question_id,
          value: values[q.question_id] ?? "",
        })),
      }),
    });
    setBusy(false);
    if (!resp.ok) {
      setError(
        resp.status === 400
          ? "A response has already been submitted for this survey."
          : "Could not submit this response."
      );
      return;
    }
    setSubmitted(true);
    onSubmitted();
  }

  if (error) return <p role="alert" style={{ fontSize: "0.8125rem", color: "var(--stop)" }}>{error}</p>;
  if (submitted) {
    return (
      <p className="card mt-3" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
        Thank you — your response has been recorded.
      </p>
    );
  }
  if (!survey) return <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>Loading survey…</p>;

  return (
    <div className="card mt-3 flex flex-col gap-4">
      {survey.response_mode === "anonymous" ? (
        <p className="tag tag--mute" style={{ display: "inline-block" }}>
          This survey is anonymous — your name is never recorded.
        </p>
      ) : null}
      {survey.questions.map((q) => (
        <div key={q.question_id}>
          <p style={{ fontSize: "0.875rem", fontWeight: 600 }}>{q.prompt}</p>
          {q.options.length > 0 ? (
            <div className="mt-2 flex flex-col gap-1">
              {q.options.map((o) => (
                <label key={o.id} className="flex items-center gap-2" style={{ fontSize: "0.8125rem" }}>
                  <input
                    type="radio"
                    name={q.question_id}
                    onChange={() => setValues((prev) => ({ ...prev, [q.question_id]: o.id }))}
                  />
                  {o.text}
                </label>
              ))}
            </div>
          ) : (
            <textarea
              className="input mt-2"
              rows={3}
              aria-label={q.prompt}
              onChange={(e) => setValues((prev) => ({ ...prev, [q.question_id]: e.target.value }))}
            />
          )}
        </div>
      ))}
      <button type="button" disabled={busy} onClick={submit} className="btn btn--primary">
        Submit response
      </button>
    </div>
  );
}
