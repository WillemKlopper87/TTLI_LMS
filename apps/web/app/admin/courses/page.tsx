"use client";

/**
 * `/admin/courses` — the list/manage view. Authoring itself moved into the
 * seven-step wizard (`/admin/courses/new`, `/admin/courses/{id}/edit`), so
 * what remains here is the operator idiom every admin list uses: `.dash-top`
 * + `.stats` + `.tablewrap`, with per-row entry points into the wizard.
 *
 * `LessonActivityPanel` stays exactly where it was and is imported by the
 * wizard's Content step; `LessonItem` moved to `./types` when this file
 * stopped being a component module worth importing types from.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { useAdmin } from "../admin-context";
import { type CourseItem, STATE_TAG } from "./types";
import { authedFetch, readError, sendJson } from "./wizard-api";

export default function CoursesScreen() {
  const { me } = useAdmin();
  const router = useRouter();
  const canEdit = me.permissions.includes("course:edit");

  const [courses, setCourses] = useState<CourseItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  async function load() {
    const resp = await authedFetch("/api/bff/courses");
    if (!resp.ok) {
      setError(await readError(resp, "Courses could not be loaded."));
      setCourses([]);
      return;
    }
    setCourses((await resp.json()).items);
  }

  useEffect(() => {
    void (async () => {
      await load();
    })();
  }, []);

  async function duplicate(course: CourseItem) {
    setBusyId(course.id);
    setError(null);
    const resp = await sendJson(`/api/bff/courses/${course.id}/duplicate`, "POST", {
      title: `${course.title} (copy)`,
    });
    setBusyId(null);
    if (!resp.ok) {
      setError(await readError(resp, "The course could not be duplicated."));
      return;
    }
    const copy = (await resp.json()) as CourseItem;
    router.push(`/admin/courses/${copy.id}/edit?step=1`);
  }

  const drafts = (courses ?? []).filter((c) => c.state !== "published").length;
  const published = (courses ?? []).filter((c) => c.state === "published").length;
  const certificated = (courses ?? []).filter((c) => c.certificate_template_id !== null).length;

  return (
    <div className="dash">
      <div className="dash-top">
        <div>
          <p className="eyebrow">Teach</p>
          <h1>Courses</h1>
        </div>
        {canEdit ? (
          <a className="btn btn--primary" href="/admin/courses/new">
            New course
          </a>
        ) : null}
      </div>

      {error ? (
        <div className="callout callout--warn" role="alert">
          <p style={{ fontSize: "0.8125rem" }}>{error}</p>
        </div>
      ) : null}

      <dl className="stats">
        <div className="stat">
          <dt>Courses</dt>
          <dd>{courses?.length ?? "—"}</dd>
        </div>
        <div className="stat">
          <dt>In setup</dt>
          <dd>{courses === null ? "—" : drafts}</dd>
        </div>
        <div className="stat">
          <dt>Published</dt>
          <dd>{courses === null ? "—" : published}</dd>
        </div>
        <div className="stat">
          <dt>With a certificate</dt>
          <dd>{courses === null ? "—" : certificated}</dd>
        </div>
      </dl>

      <div className="tablewrap">
        <table>
          <thead>
            <tr>
              <th scope="col">Course</th>
              <th scope="col">State</th>
              <th scope="col">Shape</th>
              <th scope="col" />
            </tr>
          </thead>
          <tbody>
            {courses === null ? (
              <tr>
                <td colSpan={4} style={{ color: "var(--faint)" }}>
                  Loading…
                </td>
              </tr>
            ) : null}
            {courses !== null && courses.length === 0 ? (
              <tr>
                <td colSpan={4} style={{ color: "var(--muted)" }}>
                  No courses yet. &ldquo;New course&rdquo; opens the seven-step setup.
                </td>
              </tr>
            ) : null}
            {(courses ?? []).map((course) => (
              <tr key={course.id}>
                <td>
                  <b>{course.title}</b>
                  <div style={{ fontSize: "0.6875rem", color: "var(--faint)" }}>
                    {course.summary || course.slug}
                  </div>
                </td>
                <td>
                  <span className={`tag ${STATE_TAG[course.state] ?? "tag--mute"}`}>
                    {course.state}
                  </span>
                </td>
                <td style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                  {[course.level, course.format?.replace("_", " "), course.topic]
                    .filter(Boolean)
                    .join(" · ") || "—"}
                  {course.includes_workshop ? " · workshop" : ""}
                </td>
                <td>
                  <div className="flex flex-wrap justify-end gap-2">
                    <a
                      className="btn btn--ghost"
                      href={`/admin/courses/${course.id}/edit?step=${
                        course.state === "published" ? 1 : 2
                      }`}
                    >
                      {course.state === "published" ? "Edit" : "Continue setup"}
                    </a>
                    <a className="btn btn--quiet" href={`/admin/courses/${course.id}/edit?step=7`}>
                      Review
                    </a>
                    {canEdit ? (
                      <button
                        type="button"
                        className="btn btn--quiet"
                        disabled={busyId === course.id}
                        onClick={() => void duplicate(course)}
                      >
                        Duplicate
                      </button>
                    ) : null}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
