"use client";

import { useEffect, useRef, useState } from "react";

import { getAccessToken } from "@/lib/session";

import type { LessonItem } from "./types";

type ActivityKind = "quiz" | "survey" | "assignment" | "video";
type VideoUploadPhase = "idle" | "uploading" | "polling" | "ready" | "failed";

const QUESTION_TYPES = [
  { value: "single_choice", label: "Single choice" },
  { value: "multiple_choice", label: "Multiple choice" },
  { value: "true_false", label: "True or false" },
  { value: "short_text", label: "Short text (manual grading)" },
  { value: "long_text", label: "Long text (manual grading)" },
];
const CHOICE_TYPES = new Set(["single_choice", "multiple_choice", "true_false"]);

interface OptionRow {
  id: string;
  text: string;
  correct: boolean;
}

interface QuizListItem {
  id: string;
  title: string;
  pass_score: number;
  max_attempts: number;
  time_limit_seconds: number | null;
  question_count: number;
}

interface QuizQuestionAdminView {
  question_id: string;
  question_type: string;
  prompt: string;
  options: { id: string; text: string; correct: boolean }[];
  position: number;
  points: number;
}

interface QuizDetail {
  id: string;
  title: string;
  pass_score: number;
  max_attempts: number;
  time_limit_seconds: number | null;
  questions: QuizQuestionAdminView[];
}

interface SurveyListItem {
  id: string;
  title: string;
  response_mode: string;
  minimum_group_size: number;
  question_count: number;
}

interface SurveyQuestionView {
  question_id: string;
  question_type: string;
  prompt: string;
  options: { id: string; text: string }[];
}

interface SurveyDetail {
  survey_id: string;
  title: string;
  response_mode: string;
  questions: SurveyQuestionView[];
}

interface AssignmentListItem {
  id: string;
  title: string;
  max_score: number;
  approval_required: boolean;
}

interface VideoAssetListItem {
  id: string;
  state: string;
  duration_seconds: number | null;
  has_captions: boolean;
}

function newOptionRow(): OptionRow {
  return { id: crypto.randomUUID(), text: "", correct: false };
}

function defaultOptionsFor(type: string): OptionRow[] {
  if (type === "true_false") {
    return [
      { id: "true", text: "True", correct: false },
      { id: "false", text: "False", correct: false },
    ];
  }
  if (CHOICE_TYPES.has(type)) return [newOptionRow(), newOptionRow()];
  return [];
}

/**
 * Authors and attaches quiz/survey/assignment content for one lesson
 * (backlog item 1 — the frontend audit's confirmed gap: the creation
 * endpoints existed, nothing called them). `course:edit` is checked
 * server-side on every write here; `canEdit` only hides forms a caller
 * couldn't use anyway, same convention as the parent page.
 */
export function LessonActivityPanel({
  lesson,
  canEdit,
  onChanged,
}: {
  lesson: LessonItem;
  canEdit: boolean;
  onChanged: () => void;
}) {
  const initialTab: ActivityKind =
    lesson.activity_type === "survey"
      ? "survey"
      : lesson.activity_type === "assignment"
        ? "assignment"
        : lesson.activity_type === "video"
          ? "video"
          : "quiz";
  const [tab, setTab] = useState<ActivityKind>(initialTab);
  const [error, setError] = useState<string | null>(null);

  // --- existing-entity lists, loaded once per tab ---
  const [quizzes, setQuizzes] = useState<QuizListItem[] | null>(null);
  const [surveys, setSurveys] = useState<SurveyListItem[] | null>(null);
  const [assignments, setAssignments] = useState<AssignmentListItem[] | null>(null);
  const [videos, setVideos] = useState<VideoAssetListItem[] | null>(null);
  const [attachExistingId, setAttachExistingId] = useState("");

  // --- the entity currently open for editing (freshly created, or picked
  // from "attach existing") ---
  const [workingId, setWorkingId] = useState<string | null>(null);
  const [quizDetail, setQuizDetail] = useState<QuizDetail | null>(null);
  const [surveyDetail, setSurveyDetail] = useState<SurveyDetail | null>(null);

  const [attachBusy, setAttachBusy] = useState(false);

  // --- create-new forms ---
  const [quizTitle, setQuizTitle] = useState("");
  const [quizPassScore, setQuizPassScore] = useState(70);
  const [quizMaxAttempts, setQuizMaxAttempts] = useState(3);
  const [quizTimeLimit, setQuizTimeLimit] = useState("");
  const [quizRandomiseQuestions, setQuizRandomiseQuestions] = useState(false);
  const [quizRandomiseOptions, setQuizRandomiseOptions] = useState(false);
  const [createQuizBusy, setCreateQuizBusy] = useState(false);

  const [surveyTitle, setSurveyTitle] = useState("");
  const [surveyResponseMode, setSurveyResponseMode] = useState("identified");
  const [surveyMinGroupSize, setSurveyMinGroupSize] = useState(5);
  const [createSurveyBusy, setCreateSurveyBusy] = useState(false);

  const [assignmentTitle, setAssignmentTitle] = useState("");
  const [assignmentInstructions, setAssignmentInstructions] = useState("");
  const [assignmentMaxScore, setAssignmentMaxScore] = useState(100);
  const [assignmentApprovalRequired, setAssignmentApprovalRequired] = useState(true);
  const [createAssignmentBusy, setCreateAssignmentBusy] = useState(false);

  // --- video upload/transcode state machine ---
  // idle -> uploading -> polling -> ready | failed. No fine-grained
  // progress % exists anywhere in the API (only TranscodeJob.progress_pct,
  // never exposed via a route) — state alone drives this UI.
  const [videoPhase, setVideoPhase] = useState<VideoUploadPhase>("idle");
  const [uploadingAssetId, setUploadingAssetId] = useState<string | null>(null);
  const [videoDetail, setVideoDetail] = useState<VideoAssetListItem | null>(null);
  const [captionsBusy, setCaptionsBusy] = useState(false);
  const [captionsError, setCaptionsError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // --- add-question form (quiz/survey tabs) ---
  const [qType, setQType] = useState(QUESTION_TYPES[0].value);
  const [qPrompt, setQPrompt] = useState("");
  const [qPoints, setQPoints] = useState(1);
  const [qOptions, setQOptions] = useState<OptionRow[]>(defaultOptionsFor(QUESTION_TYPES[0].value));
  const [questionBusy, setQuestionBusy] = useState(false);

  async function authedFetch(path: string, init: RequestInit = {}) {
    const token = getAccessToken();
    return fetch(path, { ...init, headers: { ...init.headers, Authorization: `Bearer ${token}` } });
  }

  async function loadExisting(kind: ActivityKind) {
    if (kind === "quiz") {
      const resp = await authedFetch("/api/bff/quizzes");
      if (resp.ok) setQuizzes((await resp.json()).items);
    } else if (kind === "survey") {
      const resp = await authedFetch("/api/bff/surveys");
      if (resp.ok) setSurveys((await resp.json()).items);
    } else if (kind === "assignment") {
      const resp = await authedFetch("/api/bff/assignments");
      if (resp.ok) setAssignments((await resp.json()).items);
    } else {
      const resp = await authedFetch("/api/bff/video-assets");
      if (resp.ok) setVideos((await resp.json()).items);
    }
  }

  useEffect(() => {
    setWorkingId(null);
    setQuizDetail(null);
    setSurveyDetail(null);
    setAttachExistingId("");
    setError(null);
    // Stops any running poll: this changes videoPhase, and the poll
    // effect's own cleanup (keyed on videoPhase) tears the interval down
    // in response — switching tabs mid-poll must not leave it running.
    setVideoPhase("idle");
    setUploadingAssetId(null);
    setVideoDetail(null);
    setCaptionsError(null);
    loadExisting(tab);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  useEffect(() => {
    if (videoPhase !== "polling" || !uploadingAssetId) return;
    const id = uploadingAssetId;
    pollRef.current = setInterval(async () => {
      const resp = await authedFetch(`/api/bff/video-assets/${id}`);
      if (!resp.ok) return; // transient error — try again next tick
      const data: VideoAssetListItem = await resp.json();
      if (data.state === "ready") {
        setVideoDetail(data);
        setVideoPhase("ready");
      } else if (data.state === "failed") {
        setVideoPhase("failed");
      }
      // "uploaded"/"transcoding" — keep polling, no state change.
    }, 4000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoPhase, uploadingAssetId]);

  function resetQuestionForm(nextType = QUESTION_TYPES[0].value) {
    setQType(nextType);
    setQPrompt("");
    setQPoints(1);
    setQOptions(defaultOptionsFor(nextType));
  }

  async function openQuiz(id: string) {
    setWorkingId(id);
    setSurveyDetail(null);
    const resp = await authedFetch(`/api/bff/quizzes/${id}`);
    if (resp.ok) setQuizDetail(await resp.json());
    resetQuestionForm();
  }

  async function openSurvey(id: string) {
    setWorkingId(id);
    setQuizDetail(null);
    const resp = await authedFetch(`/api/bff/surveys/${id}`);
    if (resp.ok) setSurveyDetail(await resp.json());
    resetQuestionForm();
  }

  async function attachExisting() {
    if (!attachExistingId) return;
    if (tab === "quiz") await openQuiz(attachExistingId);
    else if (tab === "survey") await openSurvey(attachExistingId);
    else if (tab === "video") {
      const picked = (videos ?? []).find((v) => v.id === attachExistingId);
      setWorkingId(attachExistingId);
      setUploadingAssetId(attachExistingId);
      if (picked?.state === "ready") {
        setVideoDetail(picked);
        setVideoPhase("ready");
      } else {
        setVideoPhase("polling");
      }
    } else setWorkingId(attachExistingId);
  }

  async function createQuiz() {
    if (!quizTitle.trim()) return;
    setCreateQuizBusy(true);
    setError(null);
    const resp = await authedFetch("/api/bff/quizzes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: quizTitle.trim(),
        pass_score: quizPassScore,
        max_attempts: quizMaxAttempts,
        time_limit_seconds: quizTimeLimit.trim() ? Number(quizTimeLimit) : null,
        randomise_questions: quizRandomiseQuestions,
        randomise_options: quizRandomiseOptions,
      }),
    });
    setCreateQuizBusy(false);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not create the quiz.");
      return;
    }
    const created = await resp.json();
    setQuizTitle("");
    await loadExisting("quiz");
    await openQuiz(created.id);
  }

  async function createSurvey() {
    if (!surveyTitle.trim()) return;
    setCreateSurveyBusy(true);
    setError(null);
    const resp = await authedFetch("/api/bff/surveys", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: surveyTitle.trim(),
        response_mode: surveyResponseMode,
        minimum_group_size: surveyMinGroupSize,
      }),
    });
    setCreateSurveyBusy(false);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not create the survey.");
      return;
    }
    const created = await resp.json();
    setSurveyTitle("");
    await loadExisting("survey");
    await openSurvey(created.id);
  }

  async function createAssignment() {
    if (!assignmentTitle.trim()) return;
    setCreateAssignmentBusy(true);
    setError(null);
    const resp = await authedFetch("/api/bff/assignments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: assignmentTitle.trim(),
        instructions: assignmentInstructions.trim() || null,
        max_score: assignmentMaxScore,
        approval_required: assignmentApprovalRequired,
      }),
    });
    setCreateAssignmentBusy(false);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not create the assignment.");
      return;
    }
    const created = await resp.json();
    setAssignmentTitle("");
    await loadExisting("assignment");
    setWorkingId(created.id);
  }

  async function uploadVideo(file: File) {
    setVideoPhase("uploading");
    setError(null);
    // FormData, no explicit Content-Type — the browser sets the multipart
    // boundary itself. The BFF proxy forwards the incoming content-type
    // verbatim and reads the body via arrayBuffer(), the same mechanism
    // already proven for payment-proof uploads, so this is safe end to end.
    const form = new FormData();
    form.append("file", file);
    const resp = await authedFetch("/api/bff/video-assets", { method: "POST", body: form });
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not upload that video.");
      setVideoPhase("idle");
      return;
    }
    const created: VideoAssetListItem = await resp.json();
    setUploadingAssetId(created.id);
    setWorkingId(created.id);
    setVideoPhase("polling");
  }

  async function uploadCaptions(file: File) {
    // The server rejects anything not literally starting with "WEBVTT" —
    // check client-side first to avoid a pointless round trip on the
    // common mistake (wrong file picked). Doesn't replicate the server's
    // lstrip() on leading whitespace; real .vtt files don't have any, and
    // the server stays the source of truth regardless.
    const head = await file.slice(0, 6).text();
    if (head !== "WEBVTT") {
      setCaptionsError("That file doesn't look like a WebVTT (.vtt) track — it must start with WEBVTT.");
      return;
    }
    if (!workingId) return;
    setCaptionsBusy(true);
    setCaptionsError(null);
    const form = new FormData();
    form.append("file", file);
    const resp = await authedFetch(`/api/bff/video-assets/${workingId}/captions`, {
      method: "POST",
      body: form,
    });
    setCaptionsBusy(false);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setCaptionsError(body?.error?.message ?? "Could not upload that caption file.");
      return;
    }
    setVideoDetail((prev) => (prev ? { ...prev, has_captions: true } : prev));
  }

  async function attachToLesson() {
    if (!workingId) return;
    setAttachBusy(true);
    setError(null);
    const param = tab === "video" ? "video_asset_id" : `${tab}_id`;
    const resp = await authedFetch(`/api/bff/lessons/${lesson.id}/${tab}?${param}=${workingId}`, {
      method: "POST",
    });
    setAttachBusy(false);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? `Could not attach this ${tab} to the lesson.`);
      return;
    }
    onChanged();
  }

  function updateOptionText(index: number, text: string) {
    setQOptions((prev) => prev.map((o, i) => (i === index ? { ...o, text } : o)));
  }

  function toggleOptionCorrect(index: number) {
    setQOptions((prev) =>
      prev.map((o, i) => {
        if (tab === "quiz" && qType === "multiple_choice") {
          return i === index ? { ...o, correct: !o.correct } : o;
        }
        // single_choice / true_false: exclusive, exactly one winner.
        return { ...o, correct: i === index };
      }),
    );
  }

  function addOptionRow() {
    setQOptions((prev) => [...prev, newOptionRow()]);
  }

  function removeOptionRow(index: number) {
    setQOptions((prev) => (prev.length > 2 ? prev.filter((_, i) => i !== index) : prev));
  }

  const isChoiceType = CHOICE_TYPES.has(qType);
  const nextPosition = tab === "quiz" ? (quizDetail?.questions.length ?? 0) : (surveyDetail?.questions.length ?? 0);
  const questionValid =
    qPrompt.trim().length > 0 &&
    (!isChoiceType ||
      (qOptions.every((o) => o.text.trim().length > 0) &&
        (tab !== "quiz" || qOptions.some((o) => o.correct))));

  async function addQuestion() {
    if (!workingId || !questionValid) return;
    setQuestionBusy(true);
    setError(null);
    const options = isChoiceType
      ? qOptions.map((o) => (tab === "quiz" ? { id: o.id, text: o.text, correct: o.correct } : { id: o.id, text: o.text }))
      : [];
    const path = tab === "quiz" ? `/api/bff/quizzes/${workingId}/questions` : `/api/bff/surveys/${workingId}/questions`;
    const body: Record<string, unknown> = {
      question_type: qType,
      prompt: qPrompt.trim(),
      options,
      position: nextPosition,
    };
    if (tab === "quiz") body.points = qPoints;
    const resp = await authedFetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    setQuestionBusy(false);
    if (!resp.ok) {
      const respBody = await resp.json().catch(() => null);
      setError(respBody?.error?.message ?? "Could not add that question.");
      return;
    }
    resetQuestionForm();
    if (tab === "quiz") await openQuiz(workingId);
    else await openSurvey(workingId);
  }

  return (
    <div className="card mt-4 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <b style={{ fontSize: "0.875rem" }}>Manage content for &ldquo;{lesson.title}&rdquo;</b>
        {lesson.activity_type !== "document" ? (
          <span className="tag tag--done">Currently: {lesson.activity_type}</span>
        ) : null}
      </div>

      <div className="mt-3 flex gap-2">
        {(["quiz", "survey", "assignment", "video"] as ActivityKind[]).map((k) => (
          <button
            key={k}
            type="button"
            className={`btn ${tab === k ? "btn--primary" : "btn--ghost"}`}
            onClick={() => setTab(k)}
          >
            {k[0].toUpperCase() + k.slice(1)}
          </button>
        ))}
      </div>

      {error ? (
        <p role="alert" className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--stop)" }}>
          {error}
        </p>
      ) : null}

      <div className="mt-3 flex flex-wrap items-end gap-2">
        <label className="field">
          <b>Attach an existing {tab}</b>
          <select
            className="input"
            value={attachExistingId}
            onChange={(e) => setAttachExistingId(e.target.value)}
          >
            <option value="">Choose…</option>
            {tab === "quiz" &&
              (quizzes ?? []).map((q) => (
                <option key={q.id} value={q.id}>
                  {q.title} ({q.question_count} questions)
                </option>
              ))}
            {tab === "survey" &&
              (surveys ?? []).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.title} ({s.question_count} questions)
                </option>
              ))}
            {tab === "assignment" &&
              (assignments ?? []).map((a) => (
                <option key={a.id} value={a.id}>
                  {a.title}
                </option>
              ))}
            {tab === "video" &&
              (videos ?? []).map((v) => (
                <option key={v.id} value={v.id}>
                  {v.id.slice(0, 8)}… — {v.state}
                  {v.duration_seconds != null ? ` — ${v.duration_seconds}s` : ""}
                  {v.has_captions ? " — captions" : ""}
                </option>
              ))}
          </select>
        </label>
        <button
          type="button"
          className="btn btn--ghost"
          disabled={!attachExistingId}
          onClick={attachExisting}
        >
          Open
        </button>
      </div>

      {canEdit ? (
        <div className="card mt-3 p-4" style={{ background: "var(--bg)" }}>
          {tab === "quiz" ? (
            <>
              <b style={{ fontSize: "0.8125rem" }}>Create a new quiz</b>
              <div className="mt-2 flex flex-wrap items-end gap-2">
                <label className="field">
                  <b>Title</b>
                  <input
                    className="input"
                    value={quizTitle}
                    onChange={(e) => setQuizTitle(e.target.value)}
                    placeholder="Module 1 knowledge check"
                  />
                </label>
                <label className="field">
                  <b>Pass score %</b>
                  <input
                    className="input"
                    type="number"
                    min={0}
                    max={100}
                    style={{ maxWidth: "6rem" }}
                    value={quizPassScore}
                    onChange={(e) => setQuizPassScore(Number(e.target.value) || 0)}
                  />
                </label>
                <label className="field">
                  <b>Max attempts</b>
                  <input
                    className="input"
                    type="number"
                    min={1}
                    style={{ maxWidth: "6rem" }}
                    value={quizMaxAttempts}
                    onChange={(e) => setQuizMaxAttempts(Number(e.target.value) || 1)}
                  />
                </label>
                <label className="field">
                  <b>Time limit (s, optional)</b>
                  <input
                    className="input"
                    type="number"
                    min={1}
                    style={{ maxWidth: "8rem" }}
                    value={quizTimeLimit}
                    onChange={(e) => setQuizTimeLimit(e.target.value)}
                  />
                </label>
                <label className="flex items-center gap-2" style={{ fontSize: "0.8125rem" }}>
                  <input
                    type="checkbox"
                    checked={quizRandomiseQuestions}
                    onChange={(e) => setQuizRandomiseQuestions(e.target.checked)}
                  />
                  Randomise questions
                </label>
                <label className="flex items-center gap-2" style={{ fontSize: "0.8125rem" }}>
                  <input
                    type="checkbox"
                    checked={quizRandomiseOptions}
                    onChange={(e) => setQuizRandomiseOptions(e.target.checked)}
                  />
                  Randomise options
                </label>
                <button
                  type="button"
                  className="btn btn--primary"
                  disabled={createQuizBusy || !quizTitle.trim()}
                  onClick={createQuiz}
                >
                  Create
                </button>
              </div>
            </>
          ) : null}

          {tab === "survey" ? (
            <>
              <b style={{ fontSize: "0.8125rem" }}>Create a new survey</b>
              <div className="mt-2 flex flex-wrap items-end gap-2">
                <label className="field">
                  <b>Title</b>
                  <input
                    className="input"
                    value={surveyTitle}
                    onChange={(e) => setSurveyTitle(e.target.value)}
                    placeholder="Course feedback"
                  />
                </label>
                <label className="field">
                  <b>Response mode</b>
                  <select
                    className="input"
                    value={surveyResponseMode}
                    onChange={(e) => setSurveyResponseMode(e.target.value)}
                  >
                    <option value="identified">Identified</option>
                    <option value="anonymous">Anonymous</option>
                  </select>
                </label>
                <label className="field">
                  <b>Minimum group size</b>
                  <input
                    className="input"
                    type="number"
                    min={1}
                    style={{ maxWidth: "6rem" }}
                    value={surveyMinGroupSize}
                    onChange={(e) => setSurveyMinGroupSize(Number(e.target.value) || 1)}
                  />
                </label>
                <button
                  type="button"
                  className="btn btn--primary"
                  disabled={createSurveyBusy || !surveyTitle.trim()}
                  onClick={createSurvey}
                >
                  Create
                </button>
              </div>
            </>
          ) : null}

          {tab === "assignment" ? (
            <>
              <b style={{ fontSize: "0.8125rem" }}>Create a new assignment</b>
              <div className="mt-2 flex flex-wrap items-end gap-2">
                <label className="field">
                  <b>Title</b>
                  <input
                    className="input"
                    value={assignmentTitle}
                    onChange={(e) => setAssignmentTitle(e.target.value)}
                    placeholder="Case study write-up"
                  />
                </label>
                <label className="field">
                  <b>Max score</b>
                  <input
                    className="input"
                    type="number"
                    min={1}
                    style={{ maxWidth: "6rem" }}
                    value={assignmentMaxScore}
                    onChange={(e) => setAssignmentMaxScore(Number(e.target.value) || 1)}
                  />
                </label>
                <label className="flex items-center gap-2" style={{ fontSize: "0.8125rem" }}>
                  <input
                    type="checkbox"
                    checked={assignmentApprovalRequired}
                    onChange={(e) => setAssignmentApprovalRequired(e.target.checked)}
                  />
                  Approval required
                </label>
                <button
                  type="button"
                  className="btn btn--primary"
                  disabled={createAssignmentBusy || !assignmentTitle.trim()}
                  onClick={createAssignment}
                >
                  Create
                </button>
              </div>
              <label className="field mt-3">
                <b>Instructions (optional)</b>
                <textarea
                  className="input"
                  rows={3}
                  value={assignmentInstructions}
                  onChange={(e) => setAssignmentInstructions(e.target.value)}
                />
              </label>
            </>
          ) : null}

          {tab === "video" && videoPhase === "idle" ? (
            <>
              <b style={{ fontSize: "0.8125rem" }}>Upload a new video</b>
              <input
                type="file"
                accept="video/*"
                className="input mt-2"
                onChange={(e) => e.target.files?.[0] && uploadVideo(e.target.files[0])}
              />
            </>
          ) : null}
          {tab === "video" && videoPhase === "uploading" ? (
            <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>Uploading…</p>
          ) : null}
          {tab === "video" && videoPhase === "failed" ? (
            <>
              <p role="alert" style={{ fontSize: "0.8125rem", color: "var(--stop)" }}>
                Transcoding failed for this video.
              </p>
              <button
                type="button"
                className="btn btn--ghost mt-2"
                onClick={() => {
                  setVideoPhase("idle");
                  setWorkingId(null);
                  setUploadingAssetId(null);
                }}
              >
                Upload a different file
              </button>
            </>
          ) : null}
        </div>
      ) : null}

      {workingId ? (
        <div className="card mt-3 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <b style={{ fontSize: "0.8125rem" }}>
              {tab === "quiz" && quizDetail ? quizDetail.title : null}
              {tab === "survey" && surveyDetail ? surveyDetail.title : null}
              {tab === "assignment" ? "Selected assignment" : null}
              {tab === "video" ? `Video — ${videoPhase}` : null}
            </b>
            <button
              type="button"
              className="btn btn--primary"
              disabled={attachBusy || (tab === "video" && videoPhase !== "ready")}
              onClick={attachToLesson}
            >
              Attach to lesson
            </button>
          </div>

          {tab === "video" && (videoPhase === "uploading" || videoPhase === "polling") ? (
            <p className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>
              {videoPhase === "uploading"
                ? "Uploading…"
                : "Transcoding — this can take a few minutes…"}
            </p>
          ) : null}

          {tab === "video" && videoPhase === "ready" && videoDetail ? (
            <div className="mt-2 flex flex-col gap-2">
              <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
                {videoDetail.duration_seconds != null
                  ? `Duration: ${videoDetail.duration_seconds}s`
                  : "Duration: unknown"}
                {" — "}
                {videoDetail.has_captions ? "Captions attached" : "No captions"}
              </p>
              {canEdit ? (
                <label className="field">
                  <b>{videoDetail.has_captions ? "Replace captions (.vtt)" : "Upload captions (.vtt)"}</b>
                  <input
                    type="file"
                    accept=".vtt,text/vtt"
                    className="input"
                    disabled={captionsBusy}
                    onChange={(e) => e.target.files?.[0] && uploadCaptions(e.target.files[0])}
                  />
                </label>
              ) : null}
              {captionsBusy ? (
                <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>Uploading captions…</p>
              ) : null}
              {captionsError ? (
                <p role="alert" style={{ fontSize: "0.8125rem", color: "var(--stop)" }}>
                  {captionsError}
                </p>
              ) : null}
            </div>
          ) : null}

          {(tab === "quiz" || tab === "survey") && (
            <div className="mt-3 flex flex-col gap-1">
              {(tab === "quiz" ? quizDetail?.questions : surveyDetail?.questions)?.map((q) => (
                <div key={q.question_id} style={{ fontSize: "0.8125rem" }}>
                  <span className="mono" style={{ color: "var(--faint)" }}>
                    #{"position" in q ? (q as QuizQuestionAdminView).position : ""}
                  </span>{" "}
                  <span className="tag tag--mute">{q.question_type}</span> {q.prompt}
                  {tab === "quiz" ? (
                    <span style={{ color: "var(--muted)" }}>
                      {" "}
                      —{" "}
                      {(q as QuizQuestionAdminView).options
                        .map((o) => (o.correct ? `${o.text} ✓` : o.text))
                        .join(", ")}
                    </span>
                  ) : null}
                </div>
              ))}
              {((tab === "quiz" ? quizDetail?.questions.length : surveyDetail?.questions.length) ??
                0) === 0 ? (
                <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>No questions yet.</p>
              ) : null}
            </div>
          )}

          {canEdit && (tab === "quiz" || tab === "survey") ? (
            <div className="card mt-3 p-3" style={{ background: "var(--bg)" }}>
              <b style={{ fontSize: "0.8125rem" }}>Add a question</b>
              <div className="mt-2 flex flex-wrap items-end gap-2">
                <label className="field">
                  <b>Type</b>
                  <select
                    className="input"
                    value={qType}
                    onChange={(e) => resetQuestionForm(e.target.value)}
                  >
                    {QUESTION_TYPES.map((t) => (
                      <option key={t.value} value={t.value}>
                        {t.label}
                      </option>
                    ))}
                  </select>
                </label>
                {tab === "quiz" ? (
                  <label className="field">
                    <b>Points</b>
                    <input
                      className="input"
                      type="number"
                      min={1}
                      style={{ maxWidth: "5rem" }}
                      value={qPoints}
                      onChange={(e) => setQPoints(Number(e.target.value) || 1)}
                    />
                  </label>
                ) : null}
              </div>
              <label className="field mt-2">
                <b>Prompt</b>
                <textarea
                  className="input"
                  rows={2}
                  value={qPrompt}
                  onChange={(e) => setQPrompt(e.target.value)}
                />
              </label>

              {isChoiceType ? (
                <div className="mt-2 flex flex-col gap-2">
                  <b style={{ fontSize: "0.75rem" }}>
                    Options {tab === "quiz" ? "— mark the correct one(s)" : ""}
                  </b>
                  {qOptions.map((o, i) => (
                    <div key={o.id} className="flex items-center gap-2">
                      {tab === "quiz" ? (
                        <input
                          type={qType === "multiple_choice" ? "checkbox" : "radio"}
                          name="correct-option"
                          checked={o.correct}
                          onChange={() => toggleOptionCorrect(i)}
                        />
                      ) : null}
                      <input
                        className="input"
                        value={o.text}
                        disabled={qType === "true_false"}
                        onChange={(e) => updateOptionText(i, e.target.value)}
                        placeholder={`Option ${i + 1}`}
                      />
                      {qType !== "true_false" && qOptions.length > 2 ? (
                        <button
                          type="button"
                          className="btn btn--ghost"
                          onClick={() => removeOptionRow(i)}
                        >
                          Remove
                        </button>
                      ) : null}
                    </div>
                  ))}
                  {qType !== "true_false" ? (
                    <button type="button" className="btn btn--ghost" onClick={addOptionRow}>
                      + Add option
                    </button>
                  ) : null}
                </div>
              ) : null}

              <button
                type="button"
                className="btn btn--primary mt-3"
                disabled={questionBusy || !questionValid}
                onClick={addQuestion}
              >
                Add question
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
