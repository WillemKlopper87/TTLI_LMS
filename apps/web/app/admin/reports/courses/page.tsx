"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { getAccessToken } from "@/lib/session";

import { useAdmin } from "../../admin-context";

/**
 * Course reports index (enterprise-gaps-plan Pass A, gap #40) — the
 * screen the previously-inert "Reports" nav item now points at.
 *
 * One row per course this tenant can see, with the numbers that decide
 * whether a course is worth opening: how many enrolled, how many
 * finished, and how many are stalling. Server-computed
 * (`GET /analytics/courses`); the page sorts and renders, nothing else.
 */

interface CourseRow {
  course_id: string;
  title: string;
  state: string;
  enrolled: number;
  completed: number;
  completion_rate: number;
  at_risk: number;
}

export default function CourseReports() {
  const { me } = useAdmin();
  const canView = me.permissions.includes("analytics:view");

  const [rows, setRows] = useState<CourseRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const resp = await fetch("/api/bff/analytics/courses", {
        headers: { Authorization: `Bearer ${getAccessToken() ?? ""}` },
      });
      if (!resp.ok) {
        setError("The course report could not be loaded.");
        return;
      }
      const body = (await resp.json()) as { courses: CourseRow[] };
      setRows(body.courses);
      setError(null);
    } catch {
      setError("The course report could not be loaded.");
    }
  }, []);

  useEffect(() => {
    if (canView) void load();
  }, [canView, load]);

  if (!canView) {
    return (
      <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
        Your role does not hold <span className="mono">analytics:view</span>.
      </p>
    );
  }

  return (
    <>
      <div className="dash-top">
        <div>
          <h1>Course reports</h1>
          <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
            Enrolment and completion across every course assigned to this tenant.
          </p>
        </div>
        <Link href="/admin" className="btn btn--ghost">
          Back to operations
        </Link>
      </div>

      {error ? (
        <div className="callout callout--warn mt-3" role="status">
          {error}
        </div>
      ) : null}

      {rows === null && !error ? (
        <p className="mt-3" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
          Loading…
        </p>
      ) : null}

      {rows !== null ? (
        rows.length === 0 ? (
          <p className="mt-3" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
            No courses are assigned to this tenant yet.
          </p>
        ) : (
          <div className="table-wrap mt-3">
            <table>
              <thead>
                <tr>
                  <th scope="col">Course</th>
                  <th scope="col">State</th>
                  <th scope="col">Enrolled</th>
                  <th scope="col">Completed</th>
                  <th scope="col">Completion</th>
                  <th scope="col">At risk</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.course_id}>
                    <td>
                      <Link href={`/admin/reports/courses/${row.course_id}`}>{row.title}</Link>
                    </td>
                    <td>
                      <span className="tag">{row.state}</span>
                    </td>
                    <td style={{ fontVariantNumeric: "tabular-nums" }}>{row.enrolled}</td>
                    <td style={{ fontVariantNumeric: "tabular-nums" }}>{row.completed}</td>
                    <td style={{ fontVariantNumeric: "tabular-nums" }}>
                      {row.completion_rate}%
                    </td>
                    <td style={{ fontVariantNumeric: "tabular-nums" }}>{row.at_risk}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      ) : null}
    </>
  );
}
