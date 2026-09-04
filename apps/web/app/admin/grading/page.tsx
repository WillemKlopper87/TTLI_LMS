"use client";

import { useEffect, useState } from "react";

import { authedDownload } from "@/lib/authed-download";
import { authedFetch } from "@/lib/authed-fetch";

import { useAdmin } from "../admin-context";

interface UngradedAnswer {
  answer_id: string;
  attempt_id: string;
  quiz_id: string;
  quiz_title: string;
  question_id: string;
  prompt: string;
  text_answer: string;
  points_possible: number;
  learner_email: string;
  submitted_at: string;
}

interface PendingSubmission {
  submission_id: string;
  assignment_id: string;
  assignment_title: string;
  learner_email: string;
  version: number;
  submitted_at: string;
}

/**
 * Backlog item 3/5: grading/review. Two independent queues — free-text
 * quiz answers awaiting a score (services/quiz.py's manual half of
 * REQ-ASSESS-03) and assignment submissions awaiting first review — both
 * gated on `quiz:grade`, the only grading-related permission seeded so
 * far (assignment review reuses it too, see routers/assessment.py's own
 * comment on why there's no dedicated `assignment:review` yet).
 */
export default function GradingScreen() {
  const { me } = useAdmin();
  const canGrade = me.permissions.includes("quiz:grade");

  const [answers, setAnswers] = useState<UngradedAnswer[] | null>(null);
  const [submissions, setSubmissions] = useState<PendingSubmission[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [points, setPoints] = useState<Record<string, string>>({});
  const [gradingId, setGradingId] = useState<string | null>(null);

  const [rejectReason, setRejectReason] = useState<Record<string, string>>({});
  const [reviewingId, setReviewingId] = useState<string | null>(null);

  async function loadAnswers() {
    const resp = await authedFetch("/api/bff/quiz-answers/ungraded");
    if (resp.ok) setAnswers((await resp.json()).items);
  }

  async function loadSubmissions() {
    const resp = await authedFetch("/api/bff/assignment-submissions/pending");
    if (resp.ok) setSubmissions((await resp.json()).items);
  }

  useEffect(() => {
    if (!canGrade) return;
    void (async () => {
      await loadAnswers();
    })();
    void (async () => {
      await loadSubmissions();
    })();
  }, [canGrade]);

  async function gradeAnswer(answer: UngradedAnswer) {
    const raw = points[answer.answer_id];
    const value = raw === undefined || raw === "" ? NaN : Number(raw);
    if (Number.isNaN(value) || value < 0 || value > answer.points_possible) {
      setError(`Points must be between 0 and ${answer.points_possible}.`);
      return;
    }
    setGradingId(answer.answer_id);
    setError(null);
    const resp = await authedFetch(`/api/bff/quiz-answers/${answer.answer_id}/grade`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ points_awarded: value }),
    });
    setGradingId(null);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not save that grade.");
      return;
    }
    await loadAnswers();
  }

  async function downloadSubmission(submission: PendingSubmission) {
    // Streamed through the API with the bearer (lib/authed-download.ts),
    // the same way the invoice PDF is. The previous shape — ask the API
    // for a storage "signed URL" and window.open it — only ever worked
    // when the storage backend could mint a browser-reachable URL: the
    // local backend returns file://, which a page on http:// cannot open,
    // so "Download submission" silently did nothing in every dev setup.
    const ok = await authedDownload(
      `/api/bff/assignment-submissions/${submission.submission_id}/download`,
      `submission-${submission.submission_id}`,
    );
    if (!ok) setError("Could not download that submission.");
  }

  async function reviewSubmission(submission: PendingSubmission, approve: boolean) {
    const reason = rejectReason[submission.submission_id]?.trim();
    if (!approve && !reason) {
      setError("A reason is required to reject a submission.");
      return;
    }
    setReviewingId(submission.submission_id);
    setError(null);
    const resp = await authedFetch(
      `/api/bff/assignment-submissions/${submission.submission_id}/review`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(approve ? { approve: true } : { approve: false, rejected_reason: reason }),
      },
    );
    setReviewingId(null);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not review that submission.");
      return;
    }
    await loadSubmissions();
  }

  if (!canGrade) {
    return (
      <div>
        <h1 className="serif" style={{ fontSize: "1.5rem" }}>
          Grading
        </h1>
        <p className="mt-2" style={{ color: "var(--muted)" }}>
          Your role doesn&apos;t hold <code>quiz:grade</code>, so there&apos;s nothing to show here.
        </p>
      </div>
    );
  }

  return (
    <div>
      <h1 className="serif" style={{ fontSize: "1.5rem" }}>
        Grading
      </h1>
      <p className="mt-1" style={{ color: "var(--muted)" }}>
        Open-ended quiz answers and assignment submissions waiting on a human.
      </p>
      {error ? (
        <p role="alert" className="mt-3" style={{ color: "var(--stop)" }}>
          {error}
        </p>
      ) : null}

      <section className="card mt-4 p-4">
        <b>Ungraded quiz answers ({answers?.length ?? "…"})</b>
        <div className="mt-3 flex flex-col gap-3">
          {(answers ?? []).map((a) => (
            <div key={a.answer_id} className="card p-3" style={{ background: "var(--bg)" }}>
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <b style={{ fontSize: "0.8125rem" }}>{a.quiz_title}</b>
                <span style={{ fontSize: "0.75rem", color: "var(--faint)" }}>{a.learner_email}</span>
              </div>
              <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
                {a.prompt}
              </p>
              <p
                className="mt-1"
                style={{ fontSize: "0.8125rem", whiteSpace: "pre-wrap", fontStyle: "italic" }}
              >
                {a.text_answer}
              </p>
              <div className="mt-2 flex items-end gap-2">
                <label className="field">
                  <b>Points (of {a.points_possible})</b>
                  <input
                    className="input"
                    type="number"
                    min={0}
                    max={a.points_possible}
                    style={{ maxWidth: "6rem" }}
                    value={points[a.answer_id] ?? ""}
                    onChange={(e) =>
                      setPoints((prev) => ({ ...prev, [a.answer_id]: e.target.value }))
                    }
                  />
                </label>
                <button
                  type="button"
                  className="btn btn--primary"
                  disabled={gradingId === a.answer_id}
                  onClick={() => gradeAnswer(a)}
                >
                  Award points
                </button>
              </div>
            </div>
          ))}
          {answers !== null && answers.length === 0 ? (
            <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>Nothing to grade.</p>
          ) : null}
        </div>
      </section>

      <section className="card mt-4 p-4">
        <b>Pending assignment submissions ({submissions?.length ?? "…"})</b>
        <div className="mt-3 flex flex-col gap-3">
          {(submissions ?? []).map((s) => (
            <div key={s.submission_id} className="card p-3" style={{ background: "var(--bg)" }}>
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <b style={{ fontSize: "0.8125rem" }}>
                  {s.assignment_title} — v{s.version}
                </b>
                <span style={{ fontSize: "0.75rem", color: "var(--faint)" }}>{s.learner_email}</span>
              </div>
              <button
                type="button"
                className="btn btn--ghost mt-2"
                onClick={() => downloadSubmission(s)}
              >
                Download submission
              </button>
              <div className="mt-2 flex flex-wrap items-end gap-2">
                <button
                  type="button"
                  className="btn btn--primary"
                  disabled={reviewingId === s.submission_id}
                  onClick={() => reviewSubmission(s, true)}
                >
                  Approve
                </button>
                <label className="field" style={{ flex: 1, minWidth: "12rem" }}>
                  <b>Rejection reason</b>
                  <input
                    className="input"
                    value={rejectReason[s.submission_id] ?? ""}
                    onChange={(e) =>
                      setRejectReason((prev) => ({ ...prev, [s.submission_id]: e.target.value }))
                    }
                  />
                </label>
                <button
                  type="button"
                  className="btn btn--ghost"
                  disabled={reviewingId === s.submission_id}
                  onClick={() => reviewSubmission(s, false)}
                >
                  Reject
                </button>
              </div>
            </div>
          ))}
          {submissions !== null && submissions.length === 0 ? (
            <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>Nothing pending.</p>
          ) : null}
        </div>
      </section>
    </div>
  );
}
