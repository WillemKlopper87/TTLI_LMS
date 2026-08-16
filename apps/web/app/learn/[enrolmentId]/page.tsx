"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { getAccessToken } from "@/lib/session";
import { useRequireAuth } from "@/lib/session-context";

import { AssignmentUpload } from "./assignment-upload";
import { CredentialsPanel } from "./credentials-panel";
import { QuizPlayer } from "./quiz-player";
import { SurveyForm } from "./survey-form";
import { VideoPlayer } from "./video-player";

interface LessonProgress {
  lesson_id: string;
  module_title: string;
  title: string;
  position: number;
  activity_type: string;
  video_asset_id: string | null;
  quiz_id: string | null;
  survey_id: string | null;
  assignment_id: string | null;
  state: string;
  unmet_requirements: string[];
}

interface EnrolmentProgress {
  enrolment_id: string;
  course_id: string;
  course_title: string;
  lessons: LessonProgress[];
}

const STATE_TAG: Record<string, string> = {
  locked: "tag--mute",
  available: "tag--live",
  in_progress: "tag--live",
  requirements_met: "tag--live",
  completed: "tag--done",
};

/**
 * The lesson viewer (03 §6.1/6.2/6.4, REQ-BYPASS-01). Every state and
 * unmet-requirements reason shown here comes straight from the server —
 * this page renders a checklist, it does not compute one.
 */
export default function LearnEnrolmentPage() {
  const { ready } = useRequireAuth();
  const { enrolmentId } = useParams<{ enrolmentId: string }>();
  const [progress, setProgress] = useState<EnrolmentProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyLessonId, setBusyLessonId] = useState<string | null>(null);

  const load = useCallback(async () => {
    const token = getAccessToken();
    if (!token) return;
    const resp = await fetch(`/api/bff/enrolments/${enrolmentId}/progress`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!resp.ok) {
      setError("This course could not be loaded.");
      return;
    }
    setProgress(await resp.json());
  }, [enrolmentId]);

  useEffect(() => {
    if (!ready) return;
    load();
  }, [ready, load]);

  async function startLesson(lessonId: string) {
    const token = getAccessToken();
    setBusyLessonId(lessonId);
    await fetch(`/api/bff/lessons/${lessonId}/start`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
    await load();
    setBusyLessonId(null);
  }

  async function completeLesson(lessonId: string) {
    const token = getAccessToken();
    setBusyLessonId(lessonId);
    const resp = await fetch(`/api/bff/lessons/${lessonId}/complete`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!resp.ok) {
      // 423 LESSON_LOCKED — reload so the fresh unmet_requirements show
      // why, rather than guessing client-side (REQ-BYPASS-01).
      await load();
      setBusyLessonId(null);
      return;
    }
    await load();
    setBusyLessonId(null);
  }

  if (error) {
    return (
      <main className="mx-auto max-w-2xl px-6 py-16">
        <p role="alert" style={{ fontSize: "0.875rem", color: "var(--stop)" }}>{error}</p>
      </main>
    );
  }
  if (progress === null) {
    return (
      <main className="mx-auto max-w-2xl px-6 py-16">
        <p style={{ fontSize: "0.875rem", color: "var(--faint)" }}>Loading…</p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-2xl px-6 py-16">
      <div className="flex items-center justify-between">
        <Link href="/learn" className="btn btn--ghost">
          &larr; My courses
        </Link>
        <Link href={`/learn/${enrolmentId}/transcript`} className="btn btn--ghost">
          Transcript
        </Link>
      </div>
      <h1 className="serif mt-4" style={{ fontSize: "1.65rem" }}>
        {progress.course_title}
      </h1>

      <ul className="mt-6 flex flex-col gap-3">
        {progress.lessons.map((lesson) => (
          <li key={lesson.lesson_id} className="card">
            <div className="flex items-center justify-between">
              <div>
                <p style={{ fontSize: "0.75rem", color: "var(--faint)" }}>
                  {lesson.module_title}
                </p>
                <p className="serif" style={{ fontSize: "1.0625rem" }}>
                  {lesson.title}
                </p>
              </div>
              <span className={`tag ${STATE_TAG[lesson.state] ?? "tag--mute"}`}>
                {lesson.state.replace("_", " ")}
              </span>
            </div>

            {lesson.activity_type === "video" &&
            lesson.video_asset_id &&
            (lesson.state === "in_progress" || lesson.state === "requirements_met") ? (
              <VideoPlayer lessonId={lesson.lesson_id} videoAssetId={lesson.video_asset_id} />
            ) : null}

            {lesson.activity_type === "quiz" &&
            lesson.quiz_id &&
            (lesson.state === "in_progress" || lesson.state === "requirements_met") ? (
              <QuizPlayer quizId={lesson.quiz_id} onGraded={load} />
            ) : null}

            {lesson.activity_type === "survey" &&
            lesson.survey_id &&
            (lesson.state === "in_progress" || lesson.state === "requirements_met") ? (
              <SurveyForm surveyId={lesson.survey_id} onSubmitted={load} />
            ) : null}

            {lesson.activity_type === "assignment" &&
            lesson.assignment_id &&
            (lesson.state === "in_progress" || lesson.state === "requirements_met") ? (
              <AssignmentUpload assignmentId={lesson.assignment_id} />
            ) : null}

            {lesson.unmet_requirements.length > 0 ? (
              <ul className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
                {lesson.unmet_requirements.map((reason) => (
                  <li key={reason}>&bull; {reason}</li>
                ))}
              </ul>
            ) : null}

            {lesson.state === "available" ? (
              <button
                type="button"
                disabled={busyLessonId === lesson.lesson_id}
                onClick={() => startLesson(lesson.lesson_id)}
                className="btn btn--primary mt-3"
              >
                Start lesson
              </button>
            ) : null}
            {lesson.state === "in_progress" || lesson.state === "requirements_met" ? (
              <button
                type="button"
                disabled={busyLessonId === lesson.lesson_id}
                onClick={() => completeLesson(lesson.lesson_id)}
                className="btn btn--primary mt-3"
              >
                Mark complete
              </button>
            ) : null}
          </li>
        ))}
      </ul>

      <CredentialsPanel enrolmentId={enrolmentId} />
    </main>
  );
}
