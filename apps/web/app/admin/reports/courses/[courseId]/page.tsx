"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { authedFetch } from "@/lib/authed-fetch";

import { useAdmin } from "../../../admin-context";

/**
 * One course's analytics (enterprise-gaps-plan Pass A, gap #40).
 *
 * Three questions, in the order an author asks them: does anyone finish
 * it, where do they stop, and did the assessment behave. The drop-off
 * table is the point — a lesson where "reached" collapses relative to
 * the one before it is where the course loses people, and that is
 * invisible in any aggregate completion figure.
 *
 * Quiz scores render as a five-bucket histogram rather than an average,
 * because an average of 70 hides the difference between "everyone
 * roughly passed" and "half aced it, half failed" — and only the second
 * one means the quiz is miscalibrated.
 */

interface Analytics {
  course_id: string;
  course_title: string;
  generated_at: string;
  funnel: { enrolled: number; started: number; completed: number };
  completion_rate: number;
  median_days_to_complete: number | null;
  lesson_dropoff: {
    lesson_id: string;
    title: string;
    position: number;
    module_title: string;
    reached: number;
    completed: number;
    completion_rate: number;
  }[];
  quiz_scores: {
    quiz_id: string;
    lesson_title: string;
    attempts: number;
    average_score: number | null;
    pass_rate: number | null;
    score_buckets: number[];
  }[];
  at_risk: {
    enrolment_id: string;
    learner_reference: string;
    progress_percent: number;
    days_inactive: number;
  }[];
}

const BUCKET_LABELS = ["0–19", "20–39", "40–59", "60–79", "80–100"];

export default function CourseAnalyticsPage() {
  const params = useParams<{ courseId: string }>();
  const courseId = params.courseId;
  const { me } = useAdmin();
  const canView = me.permissions.includes("analytics:view");

  const [data, setData] = useState<Analytics | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const resp = await authedFetch(`/api/bff/analytics/courses/${courseId}`);
      if (resp.status === 404) {
        setError("That course is not available to this tenant.");
        return;
      }
      if (!resp.ok) {
        setError("The course analytics could not be loaded.");
        return;
      }
      setData((await resp.json()) as Analytics);
      setError(null);
    } catch {
      setError("The course analytics could not be loaded.");
    }
  }, [courseId]);

  useEffect(() => {
    if (canView) void (async () => {
      await load();
    })();
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
          <h1>{data?.course_title ?? "Course analytics"}</h1>
          <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
            Enrolment funnel, drop-off and assessment behaviour.
          </p>
        </div>
        <Link href="/admin/reports/courses" className="btn btn--ghost">
          All courses
        </Link>
      </div>

      {error ? (
        <div className="callout callout--warn mt-3" role="status">
          {error}
        </div>
      ) : null}

      {data ? (
        <>
          <dl className="stats mt-3">
            <div className="stat">
              <dt>Enrolled</dt>
              <dd>{data.funnel.enrolled}</dd>
            </div>
            <div className="stat">
              <dt>Started</dt>
              <dd>{data.funnel.started}</dd>
            </div>
            <div className="stat">
              <dt>Completed</dt>
              <dd>{data.funnel.completed}</dd>
            </div>
            <div className="stat">
              <dt>Completion rate</dt>
              <dd>{data.completion_rate}%</dd>
            </div>
          </dl>

          <p className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
            {data.median_days_to_complete === null
              ? "No one has finished this course yet, so there is no typical duration to report."
              : `Typical time to finish: ${data.median_days_to_complete} days (median).`}
          </p>

          <section className="mt-4">
            <h2 className="serif" style={{ fontSize: "1.05rem" }}>
              Where learners stop
            </h2>
            <div className="table-wrap mt-2">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Module</th>
                    <th scope="col">Lesson</th>
                    <th scope="col">Reached</th>
                    <th scope="col">Completed</th>
                    <th scope="col">Rate</th>
                  </tr>
                </thead>
                <tbody>
                  {data.lesson_dropoff.map((lesson) => (
                    <tr key={lesson.lesson_id}>
                      <td className="m">{lesson.module_title}</td>
                      <td>{lesson.title}</td>
                      <td style={{ fontVariantNumeric: "tabular-nums" }}>{lesson.reached}</td>
                      <td style={{ fontVariantNumeric: "tabular-nums" }}>{lesson.completed}</td>
                      <td style={{ fontVariantNumeric: "tabular-nums" }}>
                        {lesson.completion_rate}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {data.quiz_scores.length > 0 ? (
            <section className="mt-4">
              <h2 className="serif" style={{ fontSize: "1.05rem" }}>
                Assessment
              </h2>
              <div className="table-wrap mt-2">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Quiz</th>
                      <th scope="col">Attempts</th>
                      <th scope="col">Average</th>
                      <th scope="col">Pass rate</th>
                      <th scope="col">Distribution</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.quiz_scores.map((quiz) => (
                      <tr key={quiz.quiz_id}>
                        <td>{quiz.lesson_title}</td>
                        <td style={{ fontVariantNumeric: "tabular-nums" }}>{quiz.attempts}</td>
                        <td style={{ fontVariantNumeric: "tabular-nums" }}>
                          {quiz.average_score === null ? "—" : `${quiz.average_score}%`}
                        </td>
                        <td style={{ fontVariantNumeric: "tabular-nums" }}>
                          {quiz.pass_rate === null ? "—" : `${quiz.pass_rate}%`}
                        </td>
                        <td>
                          {quiz.attempts === 0 ? (
                            <span className="m">no attempts</span>
                          ) : (
                            <span className="mono" style={{ fontSize: "0.6875rem" }}>
                              {quiz.score_buckets
                                .map((n, i) => `${BUCKET_LABELS[i]}: ${n}`)
                                .join("  ")}
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ) : null}

          <section className="mt-4">
            <h2 className="serif" style={{ fontSize: "1.05rem" }}>
              At risk ({data.at_risk.length})
            </h2>
            {data.at_risk.length === 0 ? (
              <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
                No one on this course is stalling.
              </p>
            ) : (
              <div className="rowlist mt-2">
                {data.at_risk.map((row) => (
                  <div key={row.enrolment_id} className="rowitem">
                    <span className="t mono" style={{ fontSize: "0.6875rem" }}>
                      {row.learner_reference}
                    </span>
                    <span className="m">{row.progress_percent}% done</span>
                    <span className="m">quiet {row.days_inactive}d</span>
                  </div>
                ))}
              </div>
            )}
          </section>
        </>
      ) : null}
    </>
  );
}
