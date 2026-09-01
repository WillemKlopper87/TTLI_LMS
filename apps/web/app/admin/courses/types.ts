/**
 * Shared shapes for the course-authoring surface (list page + the seven
 * wizard steps + the reused lesson activity panel).
 *
 * `LessonItem` used to be exported from `page.tsx`; it moved here when the
 * page became a plain list view, so that `lesson-activity-panel.tsx` and the
 * wizard steps import a type rather than a route module. The field set
 * mirrors the API's `LessonResponse` (apps/api/src/schemas/courses.py).
 */

export interface CourseItem {
  id: string;
  slug: string;
  title: string;
  description: string | null;
  state: string;
  manager_visibility: string;
  completion_rules: CompletionRules;
  certificate_template_id: string | null;
  badge_template_id: string | null;
  summary: string | null;
  level: string | null;
  topic: string | null;
  format: string | null;
  outcomes: string[];
  includes_workshop: boolean;
  hero_colour: string | null;
}

export interface ModuleItem {
  id: string;
  course_id: string;
  title: string;
  position: number;
}

export interface LessonItem {
  id: string;
  module_id: string;
  title: string;
  position: number;
  activity_type: string;
  access_level: string;
  body: string | null;
  completion_rules: CompletionRules;
  video_asset_id: string | null;
  quiz_id: string | null;
  survey_id: string | null;
  assignment_id: string | null;
}

/** `services/completion.py::CompletionRules` — every field optional; an
 * absent field means the rule does not apply. */
export interface CompletionRules {
  minimum_time_seconds?: number | null;
  video_watch_percentage?: number | null;
  quiz_pass_score?: number | null;
  quiz_max_attempts?: number | null;
  survey_required?: boolean | null;
  assignment_approval_required?: boolean | null;
  live_attendance_required?: boolean | null;
  minimum_interval_seconds?: number | null;
}

export interface LessonOutlineRow {
  lesson: LessonItem;
  video_state: string | null;
  video_duration_seconds: number | null;
  video_has_captions: boolean;
  question_count: number | null;
  estimated_minutes: number;
}

export interface ModuleOutlineRow {
  module: ModuleItem;
  lessons: LessonOutlineRow[];
}

export interface CourseOutline {
  course_id: string;
  modules: ModuleOutlineRow[];
  estimated_minutes: number;
  lesson_count: number;
}

export type ReadinessLevel = "blocker" | "warning" | "info";

export interface ReadinessCheck {
  code: string;
  level: ReadinessLevel;
  ok: boolean;
  message: string;
}

export interface Readiness {
  course_id: string;
  publishable: boolean;
  score: number;
  estimated_minutes: number;
  module_count: number;
  lesson_count: number;
  checks: ReadinessCheck[];
}

export interface CertificateTemplate {
  id: string;
  title: string;
  issuer_name: string;
  signatory_name: string;
  signatory_title: string;
  cpd_points: number | null;
}

export interface BadgeTemplate {
  id: string;
  title: string;
  criteria: string;
  issuer_name: string;
  level: string | null;
}

export interface TenantAssignmentRow {
  id: string;
  course_id: string;
  course_title: string;
  is_bespoke: boolean;
}

export interface PriceRow {
  id: string;
  currency: string;
  unit_amount: string;
  tax_behaviour: string;
}

export interface ProductItem {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  kind: string;
  is_active: boolean;
  course_id: string | null;
  course_title: string | null;
  learning_path_id: string | null;
  learning_path_title: string | null;
  workshop_id: string | null;
  workshop_title: string | null;
  subscription_plan_id: string | null;
  prices: PriceRow[];
}

export interface SellableCourse {
  id: string;
  title: string;
  state: string;
  already_sold_as: string | null;
}

/** Steps 4 and 5 can legitimately end with nothing written; "skipped" is a
 * local authoring decision the rail honours (see `wizard-api.ts`). */
export type SkipKey = "rules" | "certification";

export type StepState = "done" | "current" | "todo";

/**
 * Everything the seven steps share. The host route
 * (`[courseId]/edit/page.tsx`) owns the loads and the autosave stamp; each
 * step reads what it needs and calls back to refresh.
 */
export interface WizardContext {
  courseId: string | null;
  course: CourseItem | null;
  outline: CourseOutline | null;
  readiness: Readiness | null;
  canEdit: boolean;
  canPublish: boolean;
  canManageProducts: boolean;
  skips: Record<SkipKey, boolean>;
  setSkip: (key: SkipKey, value: boolean) => void;
  reloadCourse: () => Promise<void>;
  reloadOutline: () => Promise<void>;
  reloadReadiness: () => Promise<void>;
  markSaved: () => void;
  setError: (message: string | null) => void;
  setNotice: (message: string | null) => void;
}

export const ACCESS_LEVELS = ["public", "gated", "guest", "paid", "corporate"] as const;

export const COURSE_LEVELS = [
  { value: "introductory", label: "Introductory" },
  { value: "intermediate", label: "Intermediate" },
  { value: "executive", label: "Executive" },
];

export const COURSE_FORMATS = [
  { value: "self_paced", label: "Self-paced" },
  { value: "blended", label: "Blended" },
  { value: "live_cohort", label: "Live cohort" },
];

/** The prototype's art-block palette (app/globals.css `--brand` first). */
export const HERO_COLOURS = [
  "#8E151C",
  "#3E4A3C",
  "#4A3A52",
  "#2E4A5B",
  "#5B4A2E",
  "#3F3F3F",
];

export const STATE_TAG: Record<string, string> = {
  draft: "tag--mute",
  in_review: "tag--live",
  approved: "tag--live",
  published: "tag--done",
  archived: "tag--mute",
};

/** `video_state` is the transcoder's own state machine (media pipeline). */
export const VIDEO_STATE_TAG: Record<string, string> = {
  draft: "tag--mute",
  uploaded: "tag--live",
  transcoding: "tag--live",
  ready: "tag--done",
  failed: "tag--stop",
};

// "draft" is deliberately excluded — it blocks on an explicit admin
// decision (the finalize call), not backend processing, so it shouldn't
// trigger the outline-level background poll the way uploaded/transcoding do.
export const IN_FLIGHT_VIDEO_STATES = new Set(["uploaded", "transcoding"]);

// Ordered slowest connection first — the order the decision panel and
// video-settings checkboxes render in (0040).
export const RUNG_LABEL: Record<string, string> = {
  "360p": "Slow connections",
  "480p": "Medium",
  "720p": "Fast",
  "1080p": "Fastest / highest quality",
};
