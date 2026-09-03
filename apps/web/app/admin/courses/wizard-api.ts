/**
 * The wizard's transport helpers. Everything goes through the BFF proxy
 * (`/api/bff/<path>` → API `/api/v1/<path>`) with the in-memory bearer —
 * no direct API origin is ever contacted from the browser.
 *
 * `authedFetch` and `readError` moved to `lib/authed-fetch.ts` and
 * `lib/api-error.ts` when the nineteen private copies of the first and the
 * five of the second were consolidated. They are re-exported here rather
 * than repointed at the source in all twelve consumers: this module is the
 * wizard's transport surface, and that is still the honest place for a
 * wizard step to import them from.
 */

import { authedFetch } from "@/lib/authed-fetch";

import {
  type CourseItem,
  type CourseOutline,
  lessonHasContent,
  type Readiness,
  type SkipKey,
  type StepState,
} from "./types";

export { authedFetch };
// Surfaces the API's own refusal text rather than a generic message. Every
// refusal this surface can hit — `COURSE_AUTHORING_ERROR` on a delete with
// learner progress, a publish with an empty module, an invalid
// `completion_rules` shape, activating a product with no price — already
// carries a specific, actionable reason written server-side.
export { readError } from "@/lib/api-error";

export async function getJson<T>(path: string): Promise<T | null> {
  const resp = await authedFetch(path);
  if (!resp.ok) return null;
  return (await resp.json()) as T;
}

export async function sendJson(
  path: string,
  method: "POST" | "PATCH" | "PUT",
  body: unknown,
): Promise<Response> {
  return authedFetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
}

/**
 * Steps 4 and 5 can legitimately end with nothing written — a course may
 * deliberately have no completion rules and no certificate. "Skipped" is a
 * local authoring decision with no server representation, so it lives in
 * localStorage keyed by course id; losing it only means the rail shows the
 * step as todo again, never that data is lost.
 */
function skipStorageKey(courseId: string): string {
  return `ttli-wizard-skip:${courseId}`;
}

export function readSkips(courseId: string): Record<SkipKey, boolean> {
  const empty: Record<SkipKey, boolean> = { rules: false, certification: false };
  if (typeof window === "undefined") return empty;
  try {
    const raw = window.localStorage.getItem(skipStorageKey(courseId));
    if (!raw) return empty;
    const parsed = JSON.parse(raw) as Partial<Record<SkipKey, boolean>>;
    return { rules: !!parsed.rules, certification: !!parsed.certification };
  } catch {
    return empty;
  }
}

export function writeSkip(courseId: string, key: SkipKey, value: boolean): Record<SkipKey, boolean> {
  const next = { ...readSkips(courseId), [key]: value };
  if (typeof window !== "undefined") {
    try {
      window.localStorage.setItem(skipStorageKey(courseId), JSON.stringify(next));
    } catch {
      /* storage disabled — the rail just recomputes from server data */
    }
  }
  return next;
}

function checkOk(readiness: Readiness | null, code: string): boolean {
  return readiness?.checks.find((c) => c.code === code)?.ok ?? false;
}

/**
 * The rail's done/todo marks, derived from what the server actually holds —
 * never from "which steps has this session visited". A step the author
 * jumped over but which is genuinely satisfied reads as done; one they sat
 * on but left empty does not.
 */
export function deriveStepStates(
  course: CourseItem | null,
  outline: CourseOutline | null,
  readiness: Readiness | null,
  skips: Record<SkipKey, boolean>,
): StepState[] {
  const lessons = (outline?.modules ?? []).flatMap((m) => m.lessons);

  const basics = !!course && course.title.trim().length > 0;
  const curriculum =
    !!outline &&
    outline.modules.length > 0 &&
    outline.modules.every((m) => m.lessons.length > 0);
  const content = lessons.length > 0 && lessons.every((l) => lessonHasContent(l.lesson));
  const rules =
    skips.rules || Object.keys(course?.completion_rules ?? {}).length > 0;
  const certification =
    skips.certification ||
    !!course?.certificate_template_id ||
    !!course?.badge_template_id;
  const commerce =
    checkOk(readiness, "is_published") &&
    checkOk(readiness, "assigned_to_tenant") &&
    checkOk(readiness, "sellable");
  const review = readiness?.publishable ?? false;

  return [basics, curriculum, content, rules, certification, commerce, review].map((done) =>
    done ? "done" : "todo",
  );
}

export function formatMinutes(minutes: number): string {
  if (minutes < 60) return `${minutes}m`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}
