"use client";

import { useEffect, useState } from "react";

import { getAccessToken } from "@/lib/session";

import { useAdmin } from "../admin-context";

interface CourseItem {
  id: string;
  slug: string;
  title: string;
  description: string | null;
  state: string;
}

interface ModuleItem {
  id: string;
  course_id: string;
  title: string;
  position: number;
}

interface LessonItem {
  id: string;
  module_id: string;
  title: string;
  position: number;
  activity_type: string;
  access_level: string;
}

const ACCESS_LEVELS = ["public", "gated", "guest", "paid", "corporate"];

const STATE_TAG: Record<string, string> = {
  draft: "tag--mute",
  published: "tag--done",
  archived: "tag--mute",
};

/**
 * Course/module/lesson authoring (02 §5, REQ-TEN-03) — the Phase 4
 * authoring gap. Content, publishing and tenant-assignment are all
 * `course:edit`/`course:publish`-gated server-side, mirrored here only
 * to hide forms a caller can't use, same convention as `/workshops`.
 * Quiz/survey/assignment/video attachment stay out of scope here — a
 * lesson created on this screen is always a plain "document" lesson;
 * attaching real content to it happens through the existing quiz/survey/
 * assignment/media authoring surfaces, not this one.
 */
export default function CoursesScreen() {
  const { me } = useAdmin();
  const canEdit = me.permissions.includes("course:edit");
  const canPublish = me.permissions.includes("course:publish");

  const [courses, setCourses] = useState<CourseItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [courseTitle, setCourseTitle] = useState("");
  const [courseDescription, setCourseDescription] = useState("");
  const [courseBusy, setCourseBusy] = useState(false);

  const [selectedCourseId, setSelectedCourseId] = useState<string | null>(null);
  const [modules, setModules] = useState<ModuleItem[] | null>(null);
  const [moduleTitle, setModuleTitle] = useState("");
  const [moduleBusy, setModuleBusy] = useState(false);

  const [selectedModuleId, setSelectedModuleId] = useState<string | null>(null);
  const [lessons, setLessons] = useState<LessonItem[] | null>(null);
  const [lessonTitle, setLessonTitle] = useState("");
  const [lessonAccessLevel, setLessonAccessLevel] = useState(ACCESS_LEVELS[3]);
  const [lessonBody, setLessonBody] = useState("");
  const [lessonBusy, setLessonBusy] = useState(false);

  const [publishBusy, setPublishBusy] = useState(false);
  const [assignBespoke, setAssignBespoke] = useState(false);
  const [assignBusy, setAssignBusy] = useState(false);

  async function authedFetch(path: string, init: RequestInit = {}) {
    const token = getAccessToken();
    return fetch(path, { ...init, headers: { ...init.headers, Authorization: `Bearer ${token}` } });
  }

  async function loadCourses() {
    const resp = await authedFetch("/api/bff/courses");
    if (resp.ok) setCourses((await resp.json()).items);
  }

  useEffect(() => {
    loadCourses();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function createCourse() {
    if (!courseTitle.trim()) return;
    setCourseBusy(true);
    setError(null);
    const resp = await authedFetch("/api/bff/courses", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: courseTitle.trim(),
        description: courseDescription.trim() || null,
      }),
    });
    setCourseBusy(false);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not create the course.");
      return;
    }
    setCourseTitle("");
    setCourseDescription("");
    await loadCourses();
  }

  async function selectCourse(courseId: string) {
    setSelectedCourseId(courseId);
    setModules(null);
    setSelectedModuleId(null);
    setLessons(null);
    const resp = await authedFetch(`/api/bff/courses/${courseId}/modules`);
    if (resp.ok) setModules((await resp.json()).items);
  }

  async function createModule() {
    if (!selectedCourseId || !moduleTitle.trim()) return;
    setModuleBusy(true);
    setError(null);
    const resp = await authedFetch(`/api/bff/courses/${selectedCourseId}/modules`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: moduleTitle.trim() }),
    });
    setModuleBusy(false);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not create the module.");
      return;
    }
    setModuleTitle("");
    await selectCourse(selectedCourseId);
  }

  async function selectModule(moduleId: string) {
    setSelectedModuleId(moduleId);
    setLessons(null);
    const resp = await authedFetch(`/api/bff/modules/${moduleId}/lessons`);
    if (resp.ok) setLessons((await resp.json()).items);
  }

  async function createLesson() {
    if (!selectedModuleId || !lessonTitle.trim()) return;
    setLessonBusy(true);
    setError(null);
    const resp = await authedFetch(`/api/bff/modules/${selectedModuleId}/lessons`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: lessonTitle.trim(),
        access_level: lessonAccessLevel,
        body: lessonBody.trim() || null,
      }),
    });
    setLessonBusy(false);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not create the lesson.");
      return;
    }
    setLessonTitle("");
    setLessonBody("");
    await selectModule(selectedModuleId);
  }

  async function togglePublish(course: CourseItem) {
    if (!canPublish) return;
    setPublishBusy(true);
    setError(null);
    const action = course.state === "published" ? "unpublish" : "publish";
    const resp = await authedFetch(`/api/bff/courses/${course.id}/${action}`, { method: "POST" });
    setPublishBusy(false);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? `Could not ${action} the course.`);
      return;
    }
    await loadCourses();
  }

  async function assignToTenant() {
    if (!selectedCourseId || !canPublish) return;
    setAssignBusy(true);
    setError(null);
    const resp = await authedFetch(`/api/bff/courses/${selectedCourseId}/tenant-assignments`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_bespoke: assignBespoke }),
    });
    setAssignBusy(false);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not assign this course to your tenant.");
      return;
    }
  }

  if (courses === null) {
    return <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>Loading…</p>;
  }

  const selectedCourse = courses.find((c) => c.id === selectedCourseId) ?? null;

  return (
    <>
      <h1 className="serif" style={{ fontSize: "1.5rem" }}>
        Courses
      </h1>

      {error ? (
        <p role="alert" className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--stop)" }}>
          {error}
        </p>
      ) : null}

      {canEdit ? (
        <section className="mt-6">
          <div className="card p-5">
            <b style={{ fontSize: "0.875rem" }}>Create a course</b>
            <label className="field mt-3">
              <b>Title</b>
              <input
                className="input"
                value={courseTitle}
                onChange={(e) => setCourseTitle(e.target.value)}
                placeholder="Executive Leadership Certificate"
              />
            </label>
            <label className="field mt-3">
              <b>Description</b>
              <input
                className="input"
                value={courseDescription}
                onChange={(e) => setCourseDescription(e.target.value)}
                placeholder="Optional"
              />
            </label>
            <button
              type="button"
              className="btn btn--primary mt-3"
              disabled={courseBusy || !courseTitle.trim()}
              onClick={createCourse}
            >
              Create
            </button>
          </div>
        </section>
      ) : null}

      <section className="mt-8">
        <b style={{ fontSize: "0.9375rem" }}>Courses</b>
        {courses.length === 0 ? (
          <p className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>
            No courses yet.
          </p>
        ) : (
          <div className="mt-3 flex flex-wrap gap-2">
            {courses.map((c) => (
              <button
                key={c.id}
                type="button"
                className={`btn ${selectedCourseId === c.id ? "btn--primary" : "btn--ghost"}`}
                onClick={() => selectCourse(c.id)}
              >
                {c.title}
                <span className={`tag ${STATE_TAG[c.state] ?? "tag--mute"} ml-2`}>{c.state}</span>
              </button>
            ))}
          </div>
        )}

        {selectedCourse ? (
          <div className="mt-4">
            {canPublish ? (
              <div className="card p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    className="btn btn--ghost"
                    disabled={publishBusy}
                    onClick={() => togglePublish(selectedCourse)}
                  >
                    {selectedCourse.state === "published" ? "Unpublish" : "Publish"}
                  </button>
                  <label className="flex items-center gap-2" style={{ fontSize: "0.8125rem" }}>
                    <input
                      type="checkbox"
                      checked={assignBespoke}
                      onChange={(e) => setAssignBespoke(e.target.checked)}
                    />
                    Bespoke to my tenant
                  </label>
                  <button
                    type="button"
                    className="btn btn--ghost"
                    disabled={assignBusy}
                    onClick={assignToTenant}
                  >
                    Assign to my tenant
                  </button>
                </div>
              </div>
            ) : null}

            {canEdit ? (
              <div className="card mt-3 p-4">
                <b style={{ fontSize: "0.8125rem" }}>Add a module</b>
                <div className="mt-2 flex flex-wrap items-end gap-2">
                  <label className="field">
                    <b>Title</b>
                    <input
                      className="input"
                      value={moduleTitle}
                      onChange={(e) => setModuleTitle(e.target.value)}
                      placeholder="Module 1: Foundations"
                    />
                  </label>
                  <button
                    type="button"
                    className="btn btn--primary"
                    disabled={moduleBusy || !moduleTitle.trim()}
                    onClick={createModule}
                  >
                    Add module
                  </button>
                </div>
              </div>
            ) : null}

            <div className="mt-4">
              {modules === null ? (
                <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>Loading modules…</p>
              ) : modules.length === 0 ? (
                <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>No modules yet.</p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {modules.map((m) => (
                    <button
                      key={m.id}
                      type="button"
                      className={`btn ${selectedModuleId === m.id ? "btn--primary" : "btn--ghost"}`}
                      onClick={() => selectModule(m.id)}
                    >
                      {m.title}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {selectedModuleId ? (
              <div className="mt-4">
                {canEdit ? (
                  <div className="card p-4">
                    <b style={{ fontSize: "0.8125rem" }}>Add a lesson</b>
                    <div className="mt-2 flex flex-wrap items-end gap-2">
                      <label className="field">
                        <b>Title</b>
                        <input
                          className="input"
                          value={lessonTitle}
                          onChange={(e) => setLessonTitle(e.target.value)}
                          placeholder="Lesson 1"
                        />
                      </label>
                      <label className="field">
                        <b>Access level</b>
                        <select
                          className="input"
                          value={lessonAccessLevel}
                          onChange={(e) => setLessonAccessLevel(e.target.value)}
                        >
                          {ACCESS_LEVELS.map((level) => (
                            <option key={level} value={level}>
                              {level}
                            </option>
                          ))}
                        </select>
                      </label>
                      <button
                        type="button"
                        className="btn btn--primary"
                        disabled={lessonBusy || !lessonTitle.trim()}
                        onClick={createLesson}
                      >
                        Add lesson
                      </button>
                    </div>
                    <label className="field mt-3">
                      <b>Document body (optional)</b>
                      <textarea
                        className="input"
                        rows={3}
                        value={lessonBody}
                        onChange={(e) => setLessonBody(e.target.value)}
                        placeholder="Plain-text lesson content. Quiz/survey/assignment/video content attaches through their own authoring flows."
                      />
                    </label>
                  </div>
                ) : null}

                <div className="table-wrap mt-4">
                  <table className="data">
                    <thead>
                      <tr>
                        <th scope="col">Title</th>
                        <th scope="col">Position</th>
                        <th scope="col">Type</th>
                        <th scope="col">Access</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(lessons ?? []).map((l) => (
                        <tr key={l.id}>
                          <td>{l.title}</td>
                          <td className="mono">{l.position}</td>
                          <td>
                            <span className="tag tag--mute">{l.activity_type}</span>
                          </td>
                          <td className="mono" style={{ fontSize: "0.75rem" }}>
                            {l.access_level}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : null}
          </div>
        ) : null}
      </section>
    </>
  );
}
