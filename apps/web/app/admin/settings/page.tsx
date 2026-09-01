"use client";

import { useEffect, useState } from "react";

import { authedFetch } from "@/lib/authed-fetch";

import { useAdmin } from "../admin-context";
import { RUNG_LABEL } from "../courses/types";

import BrandingPanel from "./branding-panel";

interface Course {
  id: string;
  title: string;
  manager_visibility: string;
  video_settings: { rungs?: string[]; allow_bypass?: boolean };
}

interface VideoDefaults {
  rungs: string[];
  allow_bypass: boolean;
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
  const { me } = useAdmin();
  const canManageTenant = me.permissions.includes("tenant:manage");
  const [courses, setCourses] = useState<Course[] | null>(null);
  const [tenantAllows, setTenantAllows] = useState<boolean | null>(null);
  const [videoDefaults, setVideoDefaultsState] = useState<VideoDefaults | null>(null);
  const [error, setError] = useState<"forbidden" | "unknown" | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function load() {
    const [coursesResp, settingResp, videoResp] = await Promise.all([
      authedFetch("/api/bff/courses"),
      authedFetch("/api/bff/tenant/settings/manager-visibility"),
      authedFetch("/api/bff/tenant/settings/video-defaults"),
    ]);
    if (coursesResp.status === 403 || settingResp.status === 403 || videoResp.status === 403) {
      setError("forbidden");
      return;
    }
    if (!coursesResp.ok || !settingResp.ok || !videoResp.ok) {
      setError("unknown");
      return;
    }
    setCourses((await coursesResp.json()).items);
    setTenantAllows((await settingResp.json()).allow_manager_individual_results);
    setVideoDefaultsState(await videoResp.json());
  }

  useEffect(() => {
    void (async () => {
      await load();
    })();
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

  async function saveVideoDefaults(next: VideoDefaults) {
    setBusy("video-defaults");
    const resp = await authedFetch("/api/bff/tenant/settings/video-defaults", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(next),
    });
    setBusy(null);
    if (resp.ok) await load();
  }

  function toggleTenantRung(rung: string) {
    if (!videoDefaults) return;
    const rungs = videoDefaults.rungs.includes(rung)
      ? videoDefaults.rungs.filter((r) => r !== rung)
      : [...videoDefaults.rungs, rung];
    saveVideoDefaults({ ...videoDefaults, rungs });
  }

  async function saveCourseVideoSettings(
    courseId: string,
    updates: { rungs?: string[]; allow_bypass?: boolean | null },
  ) {
    setBusy(courseId);
    const resp = await authedFetch(`/api/bff/courses/${courseId}/video-settings`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    });
    setBusy(null);
    if (resp.ok) await load();
  }

  function toggleCourseRung(course: Course, rung: string) {
    const current = course.video_settings.rungs ?? [];
    const rungs = current.includes(rung) ? current.filter((r) => r !== rung) : [...current, rung];
    saveCourseVideoSettings(course.id, { rungs });
  }

  if (error === "forbidden") {
    return (
      <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
        Your account does not have permission to change these settings.
      </p>
    );
  }
  if (error === "unknown" || courses === null || tenantAllows === null || videoDefaults === null) {
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

      {/* Branding and custom domains, both gated on tenant:manage
          server-side. Rendered only for a caller who holds it so the
          panel does not load two endpoints that would 403. */}
      {canManageTenant ? <BrandingPanel /> : null}

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

      <section className="card mt-6 p-5">
        <b style={{ fontSize: "0.9375rem" }}>Video defaults</b>
        <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
          Pre-fills the resolution picker shown on every new video upload, tenant-wide. A course
          override below takes precedence; either way, the admin can still change it per video at
          upload time.
        </p>
        <div className="mt-4 flex flex-col gap-1">
          {Object.entries(RUNG_LABEL).map(([rung, label]) => (
            <label key={rung} className="flex items-center gap-2" style={{ fontSize: "0.875rem" }}>
              <input
                type="checkbox"
                checked={videoDefaults.rungs.includes(rung)}
                disabled={busy === "video-defaults"}
                onChange={() => toggleTenantRung(rung)}
              />
              {rung} — {label}
            </label>
          ))}
        </div>
        <label className="mt-3 flex items-center gap-2" style={{ fontSize: "0.875rem" }}>
          <input
            type="checkbox"
            checked={videoDefaults.allow_bypass}
            disabled={busy === "video-defaults"}
            onChange={(e) => saveVideoDefaults({ ...videoDefaults, allow_bypass: e.target.checked })}
          />
          Allow uploading a video as-is, without transcoding
        </label>
      </section>

      <section className="mt-6">
        <b style={{ fontSize: "0.9375rem" }}>Per-course video settings</b>
        <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
          Unchecked resolutions fall back to the tenant default above, not to nothing.
        </p>
        {courses.length === 0 ? (
          <p className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>
            No courses exist yet.
          </p>
        ) : (
          <div className="mt-4 flex flex-col gap-2">
            {courses.map((course) => (
              <div key={course.id} className="card p-3">
                <span style={{ fontSize: "0.875rem" }}>{course.title}</span>
                <div className="mt-2 flex flex-wrap gap-3">
                  {Object.keys(RUNG_LABEL).map((rung) => (
                    <label
                      key={rung}
                      className="flex items-center gap-2"
                      style={{ fontSize: "0.8125rem" }}
                    >
                      <input
                        type="checkbox"
                        checked={(course.video_settings.rungs ?? []).includes(rung)}
                        disabled={busy === course.id}
                        onChange={() => toggleCourseRung(course, rung)}
                      />
                      {rung}
                    </label>
                  ))}
                  <select
                    className="input"
                    style={{ maxWidth: "14rem" }}
                    value={
                      course.video_settings.allow_bypass === undefined
                        ? "inherit"
                        : String(course.video_settings.allow_bypass)
                    }
                    disabled={busy === course.id}
                    onChange={(e) => {
                      const v = e.target.value;
                      saveCourseVideoSettings(course.id, {
                        allow_bypass: v === "inherit" ? null : v === "true",
                      });
                    }}
                  >
                    <option value="inherit">As-is upload: inherit tenant default</option>
                    <option value="true">As-is upload: always allow</option>
                    <option value="false">As-is upload: never allow</option>
                  </select>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </>
  );
}
