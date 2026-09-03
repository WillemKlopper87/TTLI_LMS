/** Shapes returned by GET /enrolments/{id}/progress. Shared by the
 * player page, the curriculum rail and the requirements panel so the
 * three cannot drift apart. */

/** One completion rule, evaluated server-side. `current`/`required` are
 * short display values ("41%" / "80%") and are null when the rule has no
 * meaningful measure. */
export interface CompletionCheck {
  rule: string;
  met: boolean;
  reason: string;
  current: string | null;
  required: string | null;
}

/** One block of a lesson's content (0041) — a lesson holds an ordered
 * list of these instead of the single activity_type/video_asset_id/...
 * fields it used to. `block_id` names the block that owns this content,
 * needed wherever a request has to say *which* block (e.g. the video
 * heartbeat, `POST /lessons/{id}/heartbeat`). */
export interface LessonBlock {
  block_id: string;
  position: number;
  block_type: string;
  body: string | null;
  video_asset_id: string | null;
  audio_asset_id: string | null;
  quiz_id: string | null;
  survey_id: string | null;
  assignment_id: string | null;
}

export interface LessonProgress {
  lesson_id: string;
  module_id?: string | null;
  module_title: string;
  module_position?: number | null;
  title: string;
  position: number;
  blocks: LessonBlock[];
  state: string;
  unmet_requirements: string[];
  checks?: CompletionCheck[];
  estimated_minutes?: number | null;
}

export interface EnrolmentProgress {
  enrolment_id: string;
  course_id: string;
  course_title: string;
  lessons: LessonProgress[];
  progress_percent?: number;
  next_lesson_id?: string | null;
  estimated_minutes?: number;
}

/** The 423 body `POST /lessons/{id}/complete` returns when the server
 * refuses. The player never decides this — it only renders it. */
export interface LessonLockedError {
  code: string;
  message: string;
  checks: CompletionCheck[];
}
