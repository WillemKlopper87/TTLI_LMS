"use client";

/**
 * The `.curriculum` outline in its two wizard roles.
 *
 * `CurriculumOutline` (step 2) is the editable tree: inline rename, native
 * HTML5 drag-and-drop onto the **atomic** reorder endpoints, add and delete.
 * Reordering is optimistic and rolls back on refusal — the ordering is
 * learner-facing (services/enrolment.py walks prerequisites by
 * `(module.position, lesson.position)`), so a half-applied sequence of
 * per-item position PATCHes is exactly what `POST .../reorder` exists to
 * avoid.
 *
 * `LessonPicker` (steps 3 and 4) is the same markup, read-only, with a
 * selected row — the outline pane beside the activity panel.
 */

import { type DragEvent, useEffect, useRef, useState } from "react";

import {
  type CourseOutline,
  type LessonOutlineRow,
  type ModuleOutlineRow,
  primaryActivityType,
  primaryMediaState,
  VIDEO_STATE_TAG,
} from "./types";
import { authedFetch, readError, sendJson } from "./wizard-api";

const ACTIVITY_ICON: Record<string, string> = {
  document: "▤",
  video: "▶",
  quiz: "▣",
  survey: "◆",
  assignment: "✎",
};

function activityIcon(activityType: string): string {
  return ACTIVITY_ICON[activityType] ?? "▤";
}

function moduleSummary(module: ModuleOutlineRow): string {
  const minutes = module.lessons.reduce((sum, l) => sum + l.estimated_minutes, 0);
  const count = module.lessons.length;
  return `${count} lesson${count === 1 ? "" : "s"} · ${minutes}m`;
}

interface DragRef {
  kind: "module" | "lesson";
  id: string;
  moduleId: string | null;
}

export function CurriculumOutline({
  courseId,
  outline,
  canEdit,
  onChanged,
  onSaved,
  onError,
}: {
  courseId: string;
  outline: CourseOutline;
  canEdit: boolean;
  onChanged: () => Promise<void> | void;
  onSaved: () => void;
  onError: (message: string | null) => void;
}) {
  // A local mirror so a drop can repaint before the server answers, and be
  // put back exactly as it was if the server refuses.
  const [modules, setModules] = useState<ModuleOutlineRow[]>(outline.modules);
  const [busy, setBusy] = useState(false);
  const [newModuleTitle, setNewModuleTitle] = useState("");
  const [newLessonTitle, setNewLessonTitle] = useState<Record<string, string>>({});
  const dragRef = useRef<DragRef | null>(null);

  useEffect(() => {
    void (async () => {
      setModules(outline.modules);
    })();
  }, [outline]);

  function startDrag(event: DragEvent, payload: DragRef) {
    dragRef.current = payload;
    event.dataTransfer.effectAllowed = "move";
    // Firefox refuses to start a drag with no payload set.
    event.dataTransfer.setData("text/plain", payload.id);
  }

  function allowDrop(event: DragEvent) {
    if (!dragRef.current) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }

  async function reorderModules(targetModuleId: string) {
    const drag = dragRef.current;
    dragRef.current = null;
    if (!drag || drag.kind !== "module" || drag.id === targetModuleId) return;
    const previous = modules;
    const from = previous.findIndex((m) => m.module.id === drag.id);
    const to = previous.findIndex((m) => m.module.id === targetModuleId);
    if (from < 0 || to < 0) return;
    const next = [...previous];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    setModules(next);
    onError(null);
    setBusy(true);
    const resp = await sendJson(`/api/bff/courses/${courseId}/modules/reorder`, "POST", {
      ordered_ids: next.map((m) => m.module.id),
    });
    setBusy(false);
    if (!resp.ok) {
      setModules(previous);
      onError(await readError(resp, "The modules could not be reordered."));
      return;
    }
    onSaved();
    await onChanged();
  }

  async function reorderLessons(moduleId: string, targetLessonId: string) {
    const drag = dragRef.current;
    dragRef.current = null;
    if (!drag || drag.kind !== "lesson" || drag.id === targetLessonId) return;
    // Moving a lesson between modules would be a re-parent, not a reorder —
    // no endpoint does that, so the drop is simply ignored.
    if (drag.moduleId !== moduleId) {
      onError("A lesson can only be reordered inside its own module.");
      return;
    }
    const previous = modules;
    const moduleRow = previous.find((m) => m.module.id === moduleId);
    if (!moduleRow) return;
    const from = moduleRow.lessons.findIndex((l) => l.lesson.id === drag.id);
    const to = moduleRow.lessons.findIndex((l) => l.lesson.id === targetLessonId);
    if (from < 0 || to < 0) return;
    const nextLessons = [...moduleRow.lessons];
    const [moved] = nextLessons.splice(from, 1);
    nextLessons.splice(to, 0, moved);
    setModules(
      previous.map((m) => (m.module.id === moduleId ? { ...m, lessons: nextLessons } : m)),
    );
    onError(null);
    setBusy(true);
    const resp = await sendJson(`/api/bff/modules/${moduleId}/lessons/reorder`, "POST", {
      ordered_ids: nextLessons.map((l) => l.lesson.id),
    });
    setBusy(false);
    if (!resp.ok) {
      setModules(previous);
      onError(await readError(resp, "The lessons could not be reordered."));
      return;
    }
    onSaved();
    await onChanged();
  }

  async function renameModule(moduleId: string, title: string, original: string) {
    if (!title.trim() || title.trim() === original) return;
    onError(null);
    const resp = await sendJson(`/api/bff/modules/${moduleId}`, "PATCH", { title: title.trim() });
    if (!resp.ok) {
      onError(await readError(resp, "The module could not be renamed."));
      return;
    }
    onSaved();
    await onChanged();
  }

  async function renameLesson(lessonId: string, title: string, original: string) {
    if (!title.trim() || title.trim() === original) return;
    onError(null);
    const resp = await sendJson(`/api/bff/lessons/${lessonId}`, "PATCH", { title: title.trim() });
    if (!resp.ok) {
      onError(await readError(resp, "The lesson could not be renamed."));
      return;
    }
    onSaved();
    await onChanged();
  }

  async function addModule() {
    if (!newModuleTitle.trim()) return;
    onError(null);
    setBusy(true);
    const resp = await sendJson(`/api/bff/courses/${courseId}/modules`, "POST", {
      title: newModuleTitle.trim(),
    });
    setBusy(false);
    if (!resp.ok) {
      onError(await readError(resp, "The module could not be added."));
      return;
    }
    setNewModuleTitle("");
    onSaved();
    await onChanged();
  }

  async function addLesson(moduleId: string) {
    const title = (newLessonTitle[moduleId] ?? "").trim();
    if (!title) return;
    onError(null);
    setBusy(true);
    const resp = await sendJson(`/api/bff/modules/${moduleId}/lessons`, "POST", {
      title,
      access_level: "paid",
    });
    setBusy(false);
    if (!resp.ok) {
      onError(await readError(resp, "The lesson could not be added."));
      return;
    }
    setNewLessonTitle((prev) => ({ ...prev, [moduleId]: "" }));
    onSaved();
    await onChanged();
  }

  async function deleteModule(moduleId: string, title: string) {
    if (!window.confirm(`Delete "${title}" and every lesson in it? This cannot be undone.`)) return;
    onError(null);
    setBusy(true);
    const resp = await authedFetch(`/api/bff/modules/${moduleId}`, { method: "DELETE" });
    setBusy(false);
    if (!resp.ok) {
      onError(await readError(resp, "The module could not be deleted."));
      return;
    }
    onSaved();
    await onChanged();
  }

  async function deleteLesson(lessonId: string, title: string) {
    if (!window.confirm(`Delete "${title}"? This cannot be undone.`)) return;
    onError(null);
    setBusy(true);
    const resp = await authedFetch(`/api/bff/lessons/${lessonId}`, { method: "DELETE" });
    setBusy(false);
    if (!resp.ok) {
      // 400 COURSE_AUTHORING_ERROR when learners already have progress on
      // this lesson — the server's sentence is the one worth reading.
      onError(await readError(resp, "The lesson could not be deleted."));
      return;
    }
    onSaved();
    await onChanged();
  }

  return (
    <div>
      <div className="curriculum">
        {modules.length === 0 ? (
          <div className="pad-lg" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
            No modules yet. A course needs at least one module, and every module at least one
            lesson, before it can be published.
          </div>
        ) : null}

        {modules.map((m, mi) => (
          <div
            key={m.module.id}
            className="mod"
            onDragOver={allowDrop}
            onDrop={(e) => {
              e.preventDefault();
              void reorderModules(m.module.id);
            }}
          >
            <div className="mod-head">
              <span className="flex flex-1 items-center gap-2" style={{ minWidth: 0 }}>
                {canEdit ? (
                  <span
                    draggable
                    onDragStart={(e) =>
                      startDrag(e, { kind: "module", id: m.module.id, moduleId: null })
                    }
                    title="Drag to reorder this module"
                    aria-label="Drag to reorder this module"
                    style={{ cursor: "grab", color: "var(--faint)", fontFamily: "var(--mono)" }}
                  >
                    ⋮⋮
                  </span>
                ) : null}
                <span style={{ fontFamily: "var(--mono)", color: "var(--faint)" }}>{mi + 1}</span>
                {canEdit ? (
                  <input
                    className="input"
                    defaultValue={m.module.title}
                    aria-label={`Module ${mi + 1} title`}
                    style={{
                      fontWeight: 600,
                      fontSize: "0.8125rem",
                      padding: "0.15rem 0.35rem",
                      maxWidth: "22rem",
                    }}
                    onBlur={(e) => void renameModule(m.module.id, e.target.value, m.module.title)}
                  />
                ) : (
                  <span style={{ color: "var(--ink)" }}>{m.module.title}</span>
                )}
              </span>
              <span className="flex items-center gap-3">
                {moduleSummary(m)}
                {canEdit ? (
                  <button
                    type="button"
                    className="btn btn--quiet"
                    disabled={busy}
                    title="Delete this module"
                    onClick={() => void deleteModule(m.module.id, m.module.title)}
                  >
                    ✕
                  </button>
                ) : null}
              </span>
            </div>

            <ul>
              {m.lessons.map((l) => (
                <li
                  key={l.lesson.id}
                  onDragOver={allowDrop}
                  onDrop={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    void reorderLessons(m.module.id, l.lesson.id);
                  }}
                >
                  {canEdit ? (
                    <span
                      draggable
                      onDragStart={(e) =>
                        startDrag(e, {
                          kind: "lesson",
                          id: l.lesson.id,
                          moduleId: m.module.id,
                        })
                      }
                      title="Drag to reorder this lesson"
                      aria-label="Drag to reorder this lesson"
                      style={{ cursor: "grab", color: "var(--faint)", fontFamily: "var(--mono)" }}
                    >
                      ⋮⋮
                    </span>
                  ) : null}
                  <span className="ic">{activityIcon(primaryActivityType(l.lesson))}</span>
                  {canEdit ? (
                    <input
                      className="input"
                      defaultValue={l.lesson.title}
                      aria-label="Lesson title"
                      style={{ padding: "0.15rem 0.35rem", maxWidth: "20rem" }}
                      onBlur={(e) => void renameLesson(l.lesson.id, e.target.value, l.lesson.title)}
                    />
                  ) : (
                    <span>{l.lesson.title}</span>
                  )}
                  <span className="tag tag--mute">{l.lesson.access_level}</span>
                  {primaryMediaState(l) ? (
                    <span
                      className={`tag ${VIDEO_STATE_TAG[primaryMediaState(l) as string] ?? "tag--mute"}`}
                    >
                      {primaryMediaState(l)}
                    </span>
                  ) : null}
                  <span className="dur">{l.estimated_minutes}m</span>
                  {canEdit ? (
                    <button
                      type="button"
                      className="btn btn--quiet"
                      disabled={busy}
                      title="Delete this lesson"
                      onClick={() => void deleteLesson(l.lesson.id, l.lesson.title)}
                    >
                      ✕
                    </button>
                  ) : null}
                </li>
              ))}

              {canEdit ? (
                <li>
                  <span className="ic">+</span>
                  <input
                    className="input"
                    placeholder="Add a lesson…"
                    aria-label={`Add a lesson to ${m.module.title}`}
                    style={{ padding: "0.15rem 0.35rem", maxWidth: "20rem" }}
                    value={newLessonTitle[m.module.id] ?? ""}
                    onChange={(e) =>
                      setNewLessonTitle((prev) => ({ ...prev, [m.module.id]: e.target.value }))
                    }
                    onKeyDown={(e) => {
                      if (e.key === "Enter") void addLesson(m.module.id);
                    }}
                  />
                  <button
                    type="button"
                    className="btn btn--ghost"
                    disabled={busy || !(newLessonTitle[m.module.id] ?? "").trim()}
                    onClick={() => void addLesson(m.module.id)}
                  >
                    Add lesson
                  </button>
                </li>
              ) : null}
            </ul>
          </div>
        ))}
      </div>

      {canEdit ? (
        <div className="mt-4 flex flex-wrap items-end gap-2">
          <label className="field" style={{ flex: "1 1 18rem" }}>
            <b>New module</b>
            <input
              className="input"
              value={newModuleTitle}
              placeholder="Module 1: Foundations"
              onChange={(e) => setNewModuleTitle(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void addModule();
              }}
            />
          </label>
          <button
            type="button"
            className="btn btn--primary"
            disabled={busy || !newModuleTitle.trim()}
            onClick={() => void addModule()}
          >
            Add module
          </button>
        </div>
      ) : null}
    </div>
  );
}

export function LessonPicker({
  outline,
  selectedLessonId,
  onSelect,
}: {
  outline: CourseOutline;
  selectedLessonId: string | null;
  onSelect: (row: LessonOutlineRow) => void;
}) {
  return (
    <div className="curriculum">
      {outline.modules.length === 0 ? (
        <div className="pad-lg" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
          Build the curriculum first (step 2).
        </div>
      ) : null}
      {outline.modules.map((m, mi) => (
        <div key={m.module.id} className="mod">
          <div className="mod-head">
            <span style={{ color: "var(--ink)" }}>
              {mi + 1}&nbsp;&nbsp;{m.module.title}
            </span>
            <span>{moduleSummary(m)}</span>
          </div>
          <ul>
            {m.lessons.map((l) => {
              const selected = l.lesson.id === selectedLessonId;
              return (
                <li
                  key={l.lesson.id}
                  style={
                    selected
                      ? { background: "var(--brand-wash)", cursor: "pointer" }
                      : { cursor: "pointer" }
                  }
                  onClick={() => onSelect(l)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onSelect(l);
                    }
                  }}
                >
                  <span className="ic">{activityIcon(primaryActivityType(l.lesson))}</span>
                  <span style={{ fontWeight: selected ? 600 : 400 }}>{l.lesson.title}</span>
                  <span className="tag tag--mute">{primaryActivityType(l.lesson)}</span>
                  {primaryMediaState(l) ? (
                    <span
                      className={`tag ${VIDEO_STATE_TAG[primaryMediaState(l) as string] ?? "tag--mute"}`}
                    >
                      {primaryMediaState(l)}
                    </span>
                  ) : null}
                  <span className="dur">{l.estimated_minutes}m</span>
                </li>
              );
            })}
            {m.lessons.length === 0 ? (
              <li>
                <span className="ic">·</span>
                <span style={{ color: "var(--faint)" }}>No lessons in this module.</span>
              </li>
            ) : null}
          </ul>
        </div>
      ))}
    </div>
  );
}
