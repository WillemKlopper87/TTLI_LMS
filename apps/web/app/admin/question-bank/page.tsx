"use client";

import { useCallback, useEffect, useState } from "react";

import { authedFetch } from "@/lib/authed-fetch";

import { useAdmin } from "../admin-context";

interface BankItem {
  id: string;
  assessment_kind: "quiz" | "survey";
  question_type: string;
  prompt: string;
  options: { id: string; text: string; correct?: boolean }[];
  points: number;
}

const CHOICE_TYPES = new Set(["single_choice", "multiple_choice", "true_false"]);

export default function QuestionBankScreen() {
  const { me } = useAdmin();
  const canEdit = me.permissions.includes("course:edit");
  const [items, setItems] = useState<BankItem[] | null>(null);
  const [kind, setKind] = useState<"quiz" | "survey">("quiz");
  const [questionType, setQuestionType] = useState("single_choice");
  const [prompt, setPrompt] = useState("");
  const [points, setPoints] = useState(1);
  const [optionLines, setOptionLines] = useState("Option one\nOption two");
  const [correctIndex, setCorrectIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const response = await authedFetch("/api/bff/question-bank");
    if (!response.ok) {
      setError("Question bank could not be loaded.");
      return;
    }
    setItems((await response.json()).items);
  }, []);

  useEffect(() => {
    if (!canEdit) return;
    authedFetch("/api/bff/question-bank").then(async (response) => {
      if (!response.ok) {
        setError("Question bank could not be loaded.");
        return;
      }
      setItems((await response.json()).items);
    });
  }, [canEdit]);

  async function createItem(event: React.FormEvent) {
    event.preventDefault();
    const texts = optionLines.split("\n").map((line) => line.trim()).filter(Boolean);
    const options = CHOICE_TYPES.has(questionType)
      ? texts.map((text, index) => ({
          id: crypto.randomUUID(),
          text,
          ...(kind === "quiz" ? { correct: index === correctIndex } : {}),
        }))
      : [];
    setBusy(true);
    setError(null);
    const response = await authedFetch("/api/bff/question-bank", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        assessment_kind: kind,
        question_type: questionType,
        prompt: prompt.trim(),
        options,
        points,
      }),
    });
    setBusy(false);
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      setError(body?.error?.message ?? "Question could not be saved.");
      return;
    }
    setPrompt("");
    await load();
  }

  async function removeItem(id: string) {
    const response = await authedFetch(`/api/bff/question-bank/${id}`, { method: "DELETE" });
    if (response.ok) setItems((current) => current?.filter((item) => item.id !== id) ?? []);
  }

  if (!canEdit) return <p>Your role does not hold course:edit.</p>;

  return (
    <>
      <div className="dash-top">
        <div>
          <h1>Question bank</h1>
          <p className="mt-1" style={{ color: "var(--muted)", fontSize: "0.8125rem" }}>
            Save tenant-owned templates, then copy them into quizzes and surveys while authoring.
          </p>
        </div>
      </div>

      {error ? <div className="callout callout--warn mt-3" role="alert">{error}</div> : null}

      <form className="card mt-3 p-4" onSubmit={createItem}>
        <h2>Save a reusable question</h2>
        <div className="mt-3 flex flex-wrap gap-3">
          <label className="field"><b>Use in</b><select className="input" value={kind} onChange={(e) => setKind(e.target.value as "quiz" | "survey")}><option value="quiz">Quizzes</option><option value="survey">Surveys</option></select></label>
          <label className="field"><b>Type</b><select className="input" value={questionType} onChange={(e) => setQuestionType(e.target.value)}><option value="single_choice">Single choice</option><option value="multiple_choice">Multiple choice</option><option value="true_false">True or false</option><option value="short_text">Short text</option><option value="long_text">Long text</option></select></label>
          {kind === "quiz" ? <label className="field"><b>Points</b><input className="input" type="number" min={1} value={points} onChange={(e) => setPoints(Number(e.target.value) || 1)} /></label> : null}
        </div>
        <label className="field mt-3"><b>Prompt</b><textarea className="input" rows={2} value={prompt} onChange={(e) => setPrompt(e.target.value)} required /></label>
        {CHOICE_TYPES.has(questionType) ? (
          <div className="mt-3 flex flex-wrap items-end gap-3">
            <label className="field"><b>Options (one per line)</b><textarea className="input" rows={4} value={optionLines} onChange={(e) => setOptionLines(e.target.value)} /></label>
            {kind === "quiz" ? <label className="field"><b>Correct option number</b><input className="input" type="number" min={1} value={correctIndex + 1} onChange={(e) => setCorrectIndex(Math.max(0, Number(e.target.value) - 1))} /></label> : null}
          </div>
        ) : null}
        <button className="btn btn--primary mt-3" disabled={busy || !prompt.trim()}>Save to bank</button>
      </form>

      <div className="mt-4 flex flex-col gap-2">
        {(items ?? []).map((item) => (
          <div className="card flex items-center justify-between gap-3 p-3" key={item.id}>
            <div><span className="tag">{item.assessment_kind}</span> <span className="tag tag--mute">{item.question_type}</span> <b>{item.prompt}</b></div>
            <button className="btn btn--ghost" type="button" onClick={() => removeItem(item.id)}>Delete</button>
          </div>
        ))}
        {items?.length === 0 ? <p style={{ color: "var(--muted)" }}>No reusable questions yet.</p> : null}
      </div>
    </>
  );
}
