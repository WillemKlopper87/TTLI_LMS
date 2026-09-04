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

/** Stands in for an interactive block on a lesson that is already
 * finished — the content is accounted for rather than silently absent,
 * without re-offering an action the server would refuse. */
function DoneNote({ text }: { text: string }) {
  return (
    <p className="card mt-3" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
      {text}
    </p>
  );
}

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

  // Two different questions, previously conflated into one flag:
  //
  // `playable` — may the learner still ACT on this lesson (mark it
  //   complete, sit the quiz, submit the assignment)? Only while it is
  //   open, i.e. started but not yet finished.
  // `revealed` — may the learner SEE this lesson's content at all? True
  //   for anything that isn't locked or unopened.
  //
  // Gating the content on `playable` meant every video, quiz, survey and
  // assignment silently disappeared the moment the lesson was completed,
  // leaving only its text blocks — so a learner could never re-watch a
  // video they had finished, on a programme whose own course page sells
  // "lifetime access to this cohort's material". The child components
  // already render their own completed/submitted states (a graded
  // attempt, "response recorded", the uploaded file), so they only need
  // to know whether further input is still accepted.
  const playable = current.state === "in_progress" || current.state === "requirements_met";
  const revealed = current.state !== "locked" && current.state !== "available";
  // The first video block, if any, gets the hero slot above the title —
  // same placement the old single-activity-per-lesson layout gave a
  // video lesson. Every other block (any number, any type, in order)
  // renders below inside `underplayer`.
  const heroVideo = current.blocks.find((b) => b.block_type === "video" && b.video_asset_id) ?? null;
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
          {heroVideo && revealed ? (
            <VideoPlayer
              lessonId={current.lesson_id}
              blockId={heroVideo.block_id}
              videoAssetId={heroVideo.video_asset_id as string}
            />
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

            {current.blocks
              .filter((block) => block.block_id !== heroVideo?.block_id)
              .map((block) => {
                if (block.block_type === "text" && block.body) {
                  return (
                    <div className="prose" key={block.block_id}>
                      {block.body.split(/\n{2,}/).map((para, i) => (
                        <p key={i}>{para}</p>
                      ))}
                    </div>
                  );
                }
                if (block.block_type === "video" && block.video_asset_id && revealed) {
                  // Not the hero (first) video block — a lesson can hold
                  // more than one — still rendered, just further down.
                  return (
                    <VideoPlayer
                      key={block.block_id}
                      lessonId={current.lesson_id}
                      blockId={block.block_id}
                      videoAssetId={block.video_asset_id}
                    />
                  );
                }
                if (block.block_type === "quiz" && block.quiz_id && revealed) {
                  // Deliberately NOT mounted once the lesson is done:
                  // QuizPlayer POSTs a new attempt on mount, so simply
                  // revealing it would silently burn one of the
                  // learner's remaining attempts every time they
                  // reopened a finished lesson. The score itself is
                  // already shown by RequirementsPanel below whenever
                  // the course sets a pass-score rule.
                  return playable ? (
                    <QuizPlayer
                      key={block.block_id}
                      quizId={block.quiz_id}
                      courseTitle={progress.course_title}
                      moduleTitle={current.module_title}
                      onGraded={load}
                    />
                  ) : (
                    <DoneNote key={block.block_id} text="You have completed this quiz." />
                  );
                }
                if (block.block_type === "survey" && block.survey_id && revealed) {
                  // Same reasoning as the quiz: re-showing the form
                  // invites a second submission the API would refuse.
                  return playable ? (
                    <SurveyForm key={block.block_id} surveyId={block.survey_id} onSubmitted={load} />
                  ) : (
                    <DoneNote key={block.block_id} text="Your response has been recorded." />
                  );
                }
                if (block.block_type === "assignment" && block.assignment_id && revealed) {
                  return <AssignmentUpload key={block.block_id} assignmentId={block.assignment_id} />;
                }
                return null;
              })}

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
                {/* CredentialsPanel renders nothing at all when the
                    course issues neither a certificate nor a badge, so
                    finishing such a programme used to end on the last
                    lesson's "← Previous lesson" and nothing else — no
                    acknowledgement, no way onward. This banner is the
                    part that is always true; the panel adds the
                    credential to it when there is one. */}
                <div className="callout callout--done mt-3">
                  <b>You&rsquo;ve finished {progress.course_title}.</b>
                  Every lesson is complete. Your transcript records what you did and when.
                </div>
                <div style={{ display: "flex", gap: ".6rem", flexWrap: "wrap", marginTop: ".7rem" }}>
                  <Link className="btn btn--ghost" href={`/learn/${enrolmentId}/transcript`}>
                    View transcript
                  </Link>
                  <Link className="btn btn--ghost" href="/learn">
                    Back to my learning
                  </Link>
                  <Link className="btn btn--ghost" href="/catalogue">
                    Browse other programmes
                  </Link>
                </div>
                <CredentialsPanel enrolmentId={enrolmentId} />
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </main>
  );
}
