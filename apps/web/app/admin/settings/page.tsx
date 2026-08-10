"use client";

import { useEffect, useState } from "react";

import { getAccessToken } from "@/lib/session";

interface Course {
  id: string;
  title: string;
  manager_visibility: string;
}

const VISIBILITY_LABEL: Record<string, string> = {
  aggregate_only: "Aggregate only",
  individual_enabled: "Individual results enabled",
  disabled: "Disabled entirely",
};

/**
 * REQ-TEN-03's two admin-facing toggles: the tenant-wide setting and,
 * per course, the manager_visibility field. Both must be on — together
 * with the viewer being an organisation's own manager/admin — before a
 * manager sees any individual learner's result (services/reports.py).
 */
export default function SettingsScreen() {
  const [courses, setCourses] = useState<Course[] | null>(null);
  const [tenantAllows, setTenantAllows] = useState<boolean | null>(null);
  const [error, setError] = useState<"forbidden" | "unknown" | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function authedFetch(path: string, init: RequestInit = {}) {
    const token = getAccessToken();
    return fetch(path, { ...init, headers: { ...init.headers, Authorization: `Bearer ${token}` } });
  }

  async function load() {
    const [coursesResp, settingResp] = await Promise.all([
      authedFetch("/api/bff/courses"),
      authedFetch("/api/bff/tenant/settings/manager-visibility"),
    ]);
    if (coursesResp.status === 403 || settingResp.status === 403) {
      setError("forbidden");
      return;
    }
    if (!coursesResp.ok || !settingResp.ok) {
      setError("unknown");
      return;
    }
    setCourses((await coursesResp.json()).items);
    setTenantAllows((await settingResp.json()).allow_manager_individual_results);
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function setCourseVisibility(courseId: string, value: string) {
    setBusy(courseId);
    const resp = await authedFetch(`/api/bff/courses/${courseId}/manager-visibility`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ manager_visibility: value }),
    });
    setBusy(null);
    if (resp.ok) await load();
  }

  async function setTenantSetting(value: boolean) {
    setBusy("tenant");
    const resp = await authedFetch("/api/bff/tenant/settings/manager-visibility", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ allow_manager_individual_results: value }),
    });
    setBusy(null);
    if (resp.ok) await load();
  }

  if (error === "forbidden") {
    return (
      <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
        Your account does not have permission to change these settings.
      </p>
    );
  }
  if (error === "unknown" || courses === null || tenantAllows === null) {
    return (
      <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>
        {error === "unknown" ? "Settings could not be loaded." : "Loading…"}
      </p>
    );
  }

  return (
    <>
      <h1 className="serif" style={{ fontSize: "1.5rem" }}>
        Settings
      </h1>

      <section className="card mt-6 p-5">
        <b style={{ fontSize: "0.9375rem" }}>Manager visibility of individual results</b>
        <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
          Off by default, to prevent a manager seeing individual scores and using them to pressure
          learners. Both this tenant-wide switch and a course&rsquo;s own toggle below must be on
          before any manager sees individual rows.
        </p>
        <label className="mt-4 flex items-center gap-2" style={{ fontSize: "0.875rem" }}>
          <input
            type="checkbox"
            checked={tenantAllows}
            disabled={busy === "tenant"}
            onChange={(e) => setTenantSetting(e.target.checked)}
          />
          Allow managers to view individual learner results, tenant-wide
        </label>
      </section>

      <section className="mt-6">
        <b style={{ fontSize: "0.9375rem" }}>Per-course visibility</b>
        {courses.length === 0 ? (
          <p className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>
            No courses exist yet.
          </p>
        ) : (
          <div className="mt-4 flex flex-col gap-2">
            {courses.map((course) => (
              <div key={course.id} className="card flex items-center justify-between gap-2 p-3">
                <span style={{ fontSize: "0.875rem" }}>{course.title}</span>
                <select
                  className="input"
                  style={{ maxWidth: "16rem" }}
                  value={course.manager_visibility}
                  disabled={busy === course.id}
                  onChange={(e) => setCourseVisibility(course.id, e.target.value)}
                >
                  {Object.entries(VISIBILITY_LABEL).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>
            ))}
          </div>
        )}
      </section>
    </>
  );
}
