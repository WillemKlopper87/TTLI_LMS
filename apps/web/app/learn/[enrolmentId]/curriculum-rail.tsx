"use client";

import { formatDuration } from "@/lib/format";

import type { LessonProgress } from "./types";

/**
 * The prototype's `.curric-rail` (design doc §4 screen 8): the whole
 * programme at a glance with each lesson's real server state. A locked
 * row is genuinely not clickable — the server would refuse it anyway,
 * and offering the click would imply the client decides.
 */
export function CurriculumRail({
  courseTitle,
  progressPercent,
  lessons,
  currentLessonId,
  onSelect,
}: {
  courseTitle: string;
  progressPercent: number;
  lessons: LessonProgress[];
  currentLessonId: string | null;
  onSelect: (lessonId: string) => void;
}) {
  // Group into modules, preserving the server's (module, lesson) order.
  const modules: { title: string; lessons: LessonProgress[] }[] = [];
  for (const lesson of lessons) {
    const title = lesson.module_title ?? "Programme";
    const last = modules[modules.length - 1];
    if (last && last.title === title) last.lessons.push(lesson);
    else modules.push({ title, lessons: [lesson] });
  }

  return (
    <aside className="curric-rail">
      <div className="curric-head">
        <p className="eyebrow">Programme</p>
        <h2 className="serif" style={{ fontSize: ".9375rem" }}>
          {courseTitle}
        </h2>
        <span
          className="bar"
          role="progressbar"
          aria-valuenow={progressPercent}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Course progress"
        >
          <i style={{ width: `${progressPercent}%` }} />
        </span>
        <p style={{ fontSize: ".6875rem", color: "var(--muted)" }}>
          {progressPercent}% complete
        </p>
      </div>

      {modules.map((module, mi) => (
        <div key={`${module.title}-${mi}`}>
          <p className="curric-mod">
            Module {mi + 1} · {module.title}
          </p>
          {module.lessons.map((lesson) => {
            const locked = lesson.state === "locked";
            const done = lesson.state === "completed";
            const current = lesson.lesson_id === currentLessonId;
            const cls = done
              ? "lrow lrow--done"
              : current
                ? "lrow lrow--now"
                : locked
                  ? "lrow lrow--lock"
                  : "lrow";
            const duration = formatDuration(lesson.estimated_minutes ?? null);
            return (
              <button
                key={lesson.lesson_id}
                type="button"
                className={cls}
                disabled={locked}
                aria-current={current ? "true" : undefined}
                title={
                  locked
                    ? (lesson.unmet_requirements[0] ??
                      "Finish the previous lesson to unlock this one.")
                    : undefined
                }
                onClick={() => !locked && onSelect(lesson.lesson_id)}
              >
                <span className="mk" aria-hidden="true">
                  {done ? "✓" : current ? "▶" : locked ? "🔒" : "○"}
                </span>
                <span>{lesson.title}</span>
                <span className="dur">{duration ?? ""}</span>
              </button>
            );
          })}
        </div>
      ))}
    </aside>
  );
}
