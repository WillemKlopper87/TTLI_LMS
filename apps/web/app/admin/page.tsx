"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { authedFetch } from "@/lib/authed-fetch";

import { useAdmin } from "./admin-context";

/**
 * The admin home (design doc §5 screen 14, enterprise-gaps-plan Pass A).
 *
 * Replaces a 21-line "Welcome / here are your permissions" stub — the
 * first screen anyone with an admin role opens, and previously the least
 * informative page in the product. Everything here is one server-computed
 * read (`GET /analytics/overview`); the page does no aggregation of its
 * own, so what a manager sees and what the API believes cannot drift.
 *
 * Two rules this screen keeps deliberately:
 *
 * - Money is never summed across currencies (the API returns one figure
 *   per currency for that reason), so the revenue tile lists each.
 * - Learners are referenced, never named. Naming a learner is governed by
 *   REQ-TEN-03's manager-visibility rules and this screen carries no such
 *   gate; the at-risk rows link into the course screens that do.
 *
 * `analytics:view` is enforced server-side. The check here only hides a
 * screen the caller cannot use — the convention every admin page follows.
 */

interface Money {
  currency: string;
  amount: string;
}

interface Overview {
  generated_at: string;
  month_start: string;
  kpis: {
    revenue_mtd: Money[];
    active_learners: number;
    pending_approvals: number;
    completions_this_month: number;
    certificates_issued_this_month: number;
    upcoming_sessions: number;
    at_risk_learners: number;
  };
  payment_approvals: {
    order_id: string;
    order_number: string;
    status: string;
    currency: string;
    grand_total: number;
    buyer_email: string | null;
    waiting_since: string;
    hours_waiting: number;
  }[];
  ungraded_submissions: {
    submission_id: string;
    enrolment_id: string;
    assignment_title: string;
    course_title: string;
    submitted_at: string;
    hours_waiting: number;
  }[];
  failed_transcodes: {
    transcode_job_id: string;
    video_asset_id: string;
    lesson_title: string | null;
    course_title: string | null;
    error: string | null;
    failed_at: string | null;
  }[];
  at_risk: {
    enrolment_id: string;
    course_id: string;
    course_title: string;
    learner_reference: string;
    progress_percent: number;
    last_active_at: string | null;
    days_inactive: number;
  }[];
}

function money(rows: Money[]): string {
  if (rows.length === 0) return "—";
  return rows
    .map((r) => `${r.currency} ${Number(r.amount).toLocaleString("en-ZA")}`)
    .join(" · ");
}

function waited(hours: number): string {
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

export default function AdminOverview() {
  const { me } = useAdmin();
  const canView = me.permissions.includes("analytics:view");

  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await authedFetch("/api/bff/analytics/overview");
      if (!resp.ok) {
        setError("The overview could not be loaded.");
        return;
      }
      setData((await resp.json()) as Overview);
      setError(null);
    } catch {
      setError("The overview could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void (async () => {
      if (canView) {
        await load();
      } else {
        setLoading(false);
      }
    })();
  }, [canView, load]);

  if (!canView) {
    return (
      <>
        <h1 className="serif" style={{ fontSize: "1.5rem" }}>
          Welcome
        </h1>
        <p className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
          Signed in as <span className="mono">{me.email}</span>. Your role does not hold{" "}
          <span className="mono">analytics:view</span>, so the operations overview is hidden —
          the sections in the sidebar are still yours to use.
        </p>
      </>
    );
  }

  const kpis = data?.kpis;
  const attentionCount =
    (data?.payment_approvals.length ?? 0) +
    (data?.ungraded_submissions.length ?? 0) +
    (data?.failed_transcodes.length ?? 0);

  return (
    <>
      <div className="dash-top">
        <div>
          <h1>Operations</h1>
          <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
            {data
              ? `Month to date, as at ${new Date(data.generated_at).toLocaleString("en-ZA")}`
              : "Month to date"}
          </p>
        </div>
        <Link href="/admin/reports/courses" className="btn btn--ghost">
          Course reports
        </Link>
      </div>

      {error ? (
        <div className="callout callout--warn mt-3" role="status">
          {error}{" "}
          <button type="button" className="btn btn--quiet" onClick={() => void load()}>
            Try again
          </button>
        </div>
      ) : null}

      {loading && !data ? (
        <p className="mt-3" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
          Loading…
        </p>
      ) : null}

      {kpis ? (
        <>
          <dl className="stats mt-3">
            <div className="stat">
              <dt>Revenue MTD</dt>
              <dd style={{ fontSize: "1.05rem" }}>{money(kpis.revenue_mtd)}</dd>
            </div>
            <div className="stat">
              <dt>Active learners</dt>
              <dd>{kpis.active_learners}</dd>
            </div>
            <div className="stat">
              <dt>Awaiting approval</dt>
              <dd>{kpis.pending_approvals}</dd>
            </div>
            <div className="stat">
              <dt>At risk</dt>
              <dd>{kpis.at_risk_learners}</dd>
            </div>
          </dl>
          <dl className="stats">
            <div className="stat">
              <dt>Completions MTD</dt>
              <dd>{kpis.completions_this_month}</dd>
            </div>
            <div className="stat">
              <dt>Certificates MTD</dt>
              <dd>{kpis.certificates_issued_this_month}</dd>
            </div>
            <div className="stat">
              <dt>Sessions, next 30 days</dt>
              <dd>{kpis.upcoming_sessions}</dd>
            </div>
            <div className="stat">
              <dt>Needs attention</dt>
              <dd>{attentionCount}</dd>
            </div>
          </dl>
        </>
      ) : null}

      {data ? (
        <>
          <section className="mt-4">
            <div className="dash-top">
              <h2 className="serif" style={{ fontSize: "1.05rem" }}>
                Payments awaiting approval
              </h2>
              <Link href="/admin/payments" style={{ fontSize: "0.8125rem" }}>
                Open the queue
              </Link>
            </div>
            {data.payment_approvals.length === 0 ? (
              <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
                Nothing waiting.
              </p>
            ) : (
              <div className="rowlist mt-2">
                {data.payment_approvals.map((row) => (
                  <div key={row.order_id} className="rowitem">
                    <span className="t">{row.buyer_email ?? "No address on file"}</span>
                    <span className="mono" style={{ fontSize: "0.6875rem" }}>
                      {row.order_number}
                    </span>
                    <span className="m">
                      {row.currency} {row.grand_total.toLocaleString("en-ZA")}
                    </span>
                    <span className="tag">{row.status.replace(/_/g, " ")}</span>
                    <span className="m">waiting {waited(row.hours_waiting)}</span>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="mt-4">
            <div className="dash-top">
              <h2 className="serif" style={{ fontSize: "1.05rem" }}>
                Submissions awaiting review
              </h2>
              <Link href="/admin/grading" style={{ fontSize: "0.8125rem" }}>
                Open grading
              </Link>
            </div>
            {data.ungraded_submissions.length === 0 ? (
              <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
                Nothing waiting.
              </p>
            ) : (
              <div className="rowlist mt-2">
                {data.ungraded_submissions.map((row) => (
                  <div key={row.submission_id} className="rowitem">
                    <span className="t">{row.assignment_title}</span>
                    <span className="m">{row.course_title}</span>
                    <span className="m">waiting {waited(row.hours_waiting)}</span>
                  </div>
                ))}
              </div>
            )}
          </section>

          {data.failed_transcodes.length > 0 ? (
            <section className="mt-4">
              <h2 className="serif" style={{ fontSize: "1.05rem" }}>
                Failed video processing
              </h2>
              <div className="rowlist mt-2">
                {data.failed_transcodes.map((row) => (
                  <div key={row.transcode_job_id} className="rowitem">
                    <span className="t">{row.lesson_title ?? "Unattached video"}</span>
                    <span className="m">{row.course_title ?? "—"}</span>
                    <span className="m">{row.error ?? "no error recorded"}</span>
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          <section className="mt-4">
            <h2 className="serif" style={{ fontSize: "1.05rem" }}>
              Learners at risk
            </h2>
            <p className="mt-1" style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
              Enrolled but never opened, or opened and gone quiet with little progress.
              Referenced rather than named — open the course to see who, where the
              visibility rules apply.
            </p>
            {data.at_risk.length === 0 ? (
              <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
                No one is stalling.
              </p>
            ) : (
              <div className="rowlist mt-2">
                {data.at_risk.map((row) => (
                  <div key={row.enrolment_id} className="rowitem">
                    <span className="t">
                      <Link href={`/admin/reports/courses/${row.course_id}`}>
                        {row.course_title}
                      </Link>
                    </span>
                    <span className="mono" style={{ fontSize: "0.6875rem" }}>
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
