"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { getAccessToken } from "@/lib/session";

import { VideoPlayer } from "../../learn/[enrolmentId]/video-player";

interface LessonPreview {
  id: string;
  title: string;
  activity_type: string;
  body: string | null;
  video_asset_id: string | null;
  quiz_id: string | null;
  survey_id: string | null;
  assignment_id: string | null;
}

interface QuizQuestionView {
  question_id: string;
  question_type: string;
  prompt: string;
  options: { id: string; text: string }[];
}

interface SurveyQuestionView {
  question_id: string;
  question_type: string;
  prompt: string;
  options: { id: string; text: string }[];
}

async function authedFetch(path: string) {
  const token = getAccessToken();
  return fetch(path, { headers: { Authorization: `Bearer ${token}` } });
}

function SignInGate() {
  return (
    <div className="card mt-4 p-5">
      <p style={{ fontSize: "0.875rem" }}>Sign in free to preview this part of the lesson.</p>
      <Link href="/login" className="btn btn--primary mt-3">
        Sign in
      </Link>
    </div>
  );
}

function QuizPreview({ quizId }: { quizId: string }) {
  const [quiz, setQuiz] = useState<{ title: string; questions: QuizQuestionView[] } | null>(null);
  useEffect(() => {
    authedFetch(`/api/bff/quizzes/${quizId}/preview`).then(async (resp) => {
      if (resp.ok) setQuiz(await resp.json());
    });
  }, [quizId]);
  if (quiz === null) return <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>Loading…</p>;
  return (
    <div className="mt-4 flex flex-col gap-3">
      {quiz.questions.map((q, i) => (
        <div key={q.question_id} className="card p-3">
          <b style={{ fontSize: "0.8125rem" }}>
            {i + 1}. {q.prompt}
          </b>
          <ul className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
            {q.options.map((o) => (
              <li key={o.id}>{o.text}</li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

function SurveyPreview({ surveyId }: { surveyId: string }) {
  const [survey, setSurvey] = useState<{ title: string; questions: SurveyQuestionView[] } | null>(
    null,
  );
  useEffect(() => {
    authedFetch(`/api/bff/surveys/${surveyId}`).then(async (resp) => {
      if (resp.ok) setSurvey(await resp.json());
    });
  }, [surveyId]);
  if (survey === null) return <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>Loading…</p>;
  return (
    <div className="mt-4 flex flex-col gap-3">
      {survey.questions.map((q, i) => (
        <div key={q.question_id} className="card p-3">
          <b style={{ fontSize: "0.8125rem" }}>
            {i + 1}. {q.prompt}
          </b>
        </div>
      ))}
    </div>
  );
}

function AssignmentPreview({ assignmentId }: { assignmentId: string }) {
  const [assignment, setAssignment] = useState<{
    title: string;
    instructions: string | null;
  } | null>(null);
  useEffect(() => {
    authedFetch(`/api/bff/assignments/${assignmentId}/preview`).then(async (resp) => {
      if (resp.ok) setAssignment(await resp.json());
    });
  }, [assignmentId]);
  if (assignment === null)
    return <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>Loading…</p>;
  return (
    <div className="card mt-4 p-4">
      <p style={{ fontSize: "0.875rem" }}>{assignment.instructions ?? "No instructions provided."}</p>
    </div>
  );
}

/**
 * A free-preview lesson's content (`access_level="public"`). Document
 * lessons render for anyone, no auth; video/quiz/survey/assignment need
 * any signed-in account (no purchase) — preview is view-only, it never
 * starts/completes the lesson or submits anything
 * (services/enrolment.py's own scope decision).
 */
export default function PreviewPage() {
  const params = useParams<{ lessonId: string }>();
  const router = useRouter();
  const [lesson, setLesson] = useState<LessonPreview | null>(null);
  const [error, setError] = useState(false);
  const [signedIn, setSignedIn] = useState(false);

  useEffect(() => {
    setSignedIn(!!getAccessToken());
    fetch(`/api/bff/public/lessons/${params.lessonId}/preview`)
      .then(async (resp) => {
        if (!resp.ok) {
          setError(true);
          return;
        }
        setLesson(await resp.json());
      })
      .catch(() => setError(true));
  }, [params.lessonId]);

  return (
    <main className="mx-auto max-w-2xl px-6 py-16">
      {error ? (
        <p style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
          This preview isn&apos;t available.{" "}
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => router.back()}
            style={{ display: "inline" }}
          >
            Go back
          </button>
        </p>
      ) : lesson === null ? (
        <p style={{ fontSize: "0.875rem", color: "var(--faint)" }}>Loading…</p>
      ) : (
        <>
          <p className="eyebrow">Free preview</p>
          <h1 className="serif mt-2" style={{ fontSize: "1.5rem" }}>
            {lesson.title}
          </h1>

          {lesson.activity_type === "document" ? (
            <p className="mt-4" style={{ fontSize: "0.9375rem", whiteSpace: "pre-wrap" }}>
              {lesson.body}
            </p>
          ) : !signedIn ? (
            <SignInGate />
          ) : lesson.activity_type === "video" && lesson.video_asset_id ? (
            <VideoPlayer lessonId={lesson.id} videoAssetId={lesson.video_asset_id} />
          ) : lesson.activity_type === "quiz" && lesson.quiz_id ? (
            <QuizPreview quizId={lesson.quiz_id} />
          ) : lesson.activity_type === "survey" && lesson.survey_id ? (
            <SurveyPreview surveyId={lesson.survey_id} />
          ) : lesson.activity_type === "assignment" && lesson.assignment_id ? (
            <AssignmentPreview assignmentId={lesson.assignment_id} />
          ) : null}
        </>
      )}
    </main>
  );
}
