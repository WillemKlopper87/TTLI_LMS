"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { authedFetch } from "@/lib/authed-fetch";
import { getAccessToken } from "@/lib/session";
import { useRequireAuth } from "@/lib/session-context";

import { AssignmentUpload } from "./assignment-upload";
import { CredentialsPanel } from "./credentials-panel";
import { CurriculumRail } from "./curriculum-rail";
import { QuizPlayer } from "./quiz-player";
import { RefusalBox, RequirementsPanel } from "./requirements-panel";
import { SurveyForm } from "./survey-form";
import type { EnrolmentProgress, LessonLockedError, LessonProgress } from "./types";
import { VideoPlayer } from "./video-player";

const STATE_TAG: Record<string, string> = {
  locked: "tag--mute",
  available: "tag--live",
  in_progress: "tag--live",
  requirements_met: "tag--live",
  completed: "tag--done",
};

const STATE_LABEL: Record<string, string> = {
  locked: "Locked",
  available: "Not started",
  in_progress: "In progress",
  requirements_met: "Requirements met",
  completed: "Completed",
};

/**
 * The lesson player (03 §6.1/6.2/6.4, REQ-BYPASS-01) as the prototype's
 * two-pane layout: the whole curriculum on the left, one focused lesson
 * on the right.
 *
 * Every state, requirement and refusal shown here comes from the server.
 * This page renders the checklist; it never computes one, and it never
 * unlocks anything the API would refuse.
 */
export default function LearnEnrolmentPage() {
  const { ready } = useRequireAuth();
  const { enrolmentId } = useParams<{ enrolmentId: string }>();
  const router = useRouter();
  const requestedLessonId = useSearchParams().get("lesson");

  const [progress, setProgress] = useState<EnrolmentProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<LessonLockedError | null>(null);
  const [shake, setShake] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!getAccessToken()) return;
    const resp = await authedFetch(`/api/bff/enrolments/${enrolmentId}/progress`);
    if (!resp.ok) {
      setError("This course could not be loaded.");
      return;
    }
    setProgress(await resp.json());
  }, [enrolmentId]);

  useEffect(() => {
    if (!ready) return;
    void (async () => {
      await load();
    })();
  }, [ready, load]);

  const lessons = useMemo(() => progress?.lessons ?? [], [progress]);

  // Which lesson is on the stage: the URL's choice when it is real and
  // reachable, else where the learner actually is.
  const current: LessonProgress | null = useMemo(() => {
    if (lessons.length === 0) return null;
    const requested = lessons.find(
      (l) => l.lesson_id === (selectedId ?? requestedLessonId) && l.state !== "locked",
    );
    if (requested) return requested;
    return (
      lessons.find((l) => l.state === "in_progress") ??
      lessons.find((l) => l.state === "requirements_met") ??
      lessons.find((l) => l.state === "available") ??
      lessons[0]
    );
  }, [lessons, selectedId, requestedLessonId]);

  const index = current ? lessons.findIndex((l) => l.lesson_id === current.lesson_id) : -1;
  const previous = index > 0 ? lessons[index - 1] : null;
  const next = index >= 0 && index < lessons.length - 1 ? lessons[index + 1] : null;
  const canAdvance =
    next !== null && (current?.state === "completed" || current?.state === "requirements_met");

  const completedCount = lessons.filter((l) => l.state === "completed").length;
  const progressPercent =
    progress?.progress_percent ??
    (lessons.length > 0 ? Math.round((completedCount / lessons.length) * 100) : 0);
  const courseComplete = lessons.length > 0 && completedCount === lessons.length;

  function select(lessonId: string) {
    setSelectedId(lessonId);
    setRefusal(null);
    // Keep the URL shareable/resumable without a navigation.
    router.replace(`/learn/${enrolmentId}?lesson=${lessonId}`, { scroll: false });
  }

  async function startLesson(lessonId: string) {
    setBusy(true);
    setRefusal(null);
    await authedFetch(`/api/bff/lessons/${lessonId}/start`, { method: "POST" });
    await load();
    setBusy(false);
  }

  async function completeLesson(lessonId: string) {
    setBusy(true);
    setRefusal(null);
    const resp = await authedFetch(`/api/bff/lessons/${lessonId}/complete`, { method: "POST" });
    if (!resp.ok) {
      // 423 LESSON_LOCKED — show the server's own reasons rather than
      // guessing client-side (REQ-BYPASS-01).
      const body = await resp.json().catch(() => null);
      const err = body?.error;
      setRefusal({
        code: err?.code ?? "LESSON_LOCKED",
        message: err?.message ?? "This lesson's requirements are not met yet.",
        checks: err?.details?.checks ?? [],
      });
      setShake(true);
      setTimeout(() => setShake(false), 320);
      await load();
      setBusy(false);
      return;
    }
    const body = await resp.json().catch(() => null);
    await load();
    setBusy(false);
    if (body?.next_lesson_id) select(body.next_lesson_id);
  }

  if (error) {
    return (
      <main className="pad-lg">
        <p className="callout callout--stop" role="alert">
          {error}
        </p>
      </main>
    );
  }

  if (progress === null || current === null) {
    return (
      <main className="pad-lg">
        <p style={{ color: "var(--muted)" }}>Loading this programme…</p>
      </main>
    );
  }

  const playable = current.state === "in_progress" || current.state === "requirements_met";
  const moduleNumber =
    lessons.filter((l, i) => i <= index && l.module_title !== lessons[i - 1]?.module_title).length ||
    1;
  const lessonNumber =
    lessons.slice(0, index + 1).filter((l) => l.module_title === current.module_title).length || 1;

  return (
    <main>
      <div className="playerlayout">
        <CurriculumRail
          courseTitle={progress.course_title}
          progressPercent={progressPercent}
          lessons={lessons}
          currentLessonId={current.lesson_id}
          onSelect={select}
        />

        <div className="stagearea">
          {current.activity_type === "video" && current.video_asset_id && playable ? (
            <VideoPlayer lessonId={current.lesson_id} videoAssetId={current.video_asset_id} />
          ) : null}

          <div className="underplayer">
            <div className="lesson-head">
              <div>
                <p className="eyebrow">
                  Module {moduleNumber} · Lesson {lessonNumber}
                </p>
                <h1 className="serif" style={{ fontSize: "1.35rem" }}>
                  {current.title}
                </h1>
              </div>
              <span className={`tag ${STATE_TAG[current.state] ?? "tag--mute"}`}>
                {STATE_LABEL[current.state] ?? current.state.replace(/_/g, " ")}
              </span>
            </div>

            {current.activity_type === "document" && current.body ? (
              <div className="prose">
                {current.body.split(/\n{2,}/).map((para, i) => (
                  <p key={i}>{para}</p>
                ))}
              </div>
            ) : null}

            {current.activity_type === "quiz" && current.quiz_id && playable ? (
              <QuizPlayer
                quizId={current.quiz_id}
                courseTitle={progress.course_title}
                moduleTitle={current.module_title}
                onGraded={load}
              />
            ) : null}
            {current.activity_type === "survey" && current.survey_id && playable ? (
              <SurveyForm surveyId={current.survey_id} onSubmitted={load} />
            ) : null}
            {current.activity_type === "assignment" && current.assignment_id && playable ? (
              <AssignmentUpload assignmentId={current.assignment_id} />
            ) : null}

            <RequirementsPanel
              checks={current.checks}
              unmetReasons={current.unmet_requirements}
            />

            {refusal ? <RefusalBox refusal={refusal} shake={shake} /> : null}

            <div style={{ display: "flex", gap: ".6rem", flexWrap: "wrap" }}>
              {current.state === "available" ? (
                <button
                  type="button"
                  className="btn btn--primary"
                  disabled={busy}
                  onClick={() => startLesson(current.lesson_id)}
                >
                  Start lesson
                </button>
              ) : null}
              {playable ? (
                <button
                  type="button"
                  className="btn btn--primary"
                  disabled={busy}
                  onClick={() => completeLesson(current.lesson_id)}
                >
                  Mark complete
                </button>
              ) : null}
              <Link className="btn btn--ghost" href={`/learn/${enrolmentId}/transcript`}>
                Transcript
              </Link>
              <Link className="btn btn--quiet" href="/learn">
                ← My learning
              </Link>
            </div>

            <div className="foot-nav">
              {previous ? (
                <button
                  type="button"
                  className="btn btn--ghost"
                  onClick={() => select(previous.lesson_id)}
                  disabled={previous.state === "locked"}
                >
                  ← Previous lesson
                </button>
              ) : (
                <span />
              )}
              {next ? (
                canAdvance ? (
                  <button
                    type="button"
                    className="btn btn--primary"
                    onClick={() => select(next.lesson_id)}
                  >
                    Next lesson →
                  </button>
                ) : (
                  <button
                    type="button"
                    className="btn btn--locked"
                    title="Finish this lesson's requirements to unlock the next one."
                    onClick={() => {
                      setShake(true);
                      setTimeout(() => setShake(false), 320);
                    }}
                  >
                    Next lesson 🔒
                  </button>
                )
              ) : (
                <span />
              )}
            </div>

            {courseComplete ? (
              <div id="certificate">
                <CredentialsPanel enrolmentId={enrolmentId} />
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </main>
  );
}
