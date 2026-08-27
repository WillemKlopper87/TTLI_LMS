"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { authedFetch } from "@/lib/authed-fetch";
import { formatDate, formatDateTime, weekdayLabel } from "@/lib/format";
import { getAccessToken } from "@/lib/session";
import { useRequireAuth } from "@/lib/session-context";

/**
 * The learner dashboard (design doc §4 screen 7). One call to
 * GET /learn/dashboard rather than N+1 from the browser: the server
 * already composes progress, credentials and upcoming commitments, and
 * anything derived here would be a second opinion on numbers the
 * completion engine owns.
 */

interface NextLesson {
  lesson_id: string;
  title: string;
  module_title: string;
  position_label: string;
}

interface DashboardEnrolment {
  enrolment_id: string;
  course_id: string;
  course_title: string;
  hero_colour: string | null;
  status: "not_started" | "in_progress" | "completed";
  progress_percent: number;
  lessons_total: number;
  lessons_completed: number;
  next_lesson: NextLesson | null;
  started_at: string | null;
  completed_at: string | null;
  certificate: {
    certificate_id: string;
    certificate_number: string;
    issued_at: string | null;
    status: string;
  } | null;
}

interface UpcomingItem {
  kind: "workshop" | "assessment";
  title: string;
  subtitle: string | null;
  starts_at: string | null;
  join_url: string | null;
  provider: string | null;
  enrolment_id: string | null;
  lesson_id: string | null;
  quiz_id: string | null;
  attempts_remaining: number | null;
}

const PROVIDER_LABEL: Record<string, string> = {
  teams: "Join on Teams",
  zoom: "Join on Zoom",
  meet: "Join on Meet",
  manual: "Join session",
};

interface Dashboard {
  first_name: string | null;
  initials: string;
  enrolments: DashboardEnrolment[];
  stats: {
    in_progress: number;
    completed: number;
    certificates: number;
    workshop_credits: number;
  };
  upcoming: UpcomingItem[];
}

/** `GET /path-enrolments` — fetched as its own call rather than folded
 * into `GET /learn/dashboard`'s composed payload: that endpoint's N+1
 * avoidance is already load-bearing for the existing enrolment/upcoming
 * blocks, and a path enrolment is rare enough (most learners have none)
 * that a second small request is cheaper than reworking that query. */
interface OwnPathEnrolment {
  path_enrolment_id: string;
  learning_path_id: string;
  learning_path_title: string;
  course_count: number;
  started_at: string;
  completed_at: string | null;
  has_certificate: boolean;
}

/** Only `#rrggbb`/`#rgb` reaches a style attribute — the colour is author
 * input, and anything else is dropped rather than interpolated. */
function safeColour(value: string | null): string | undefined {
  if (value && /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i.test(value)) return value;
  return undefined;
}

function resumeHref(e: DashboardEnrolment): string {
  return e.next_lesson
    ? `/learn/${e.enrolment_id}?lesson=${e.next_lesson.lesson_id}`
    : `/learn/${e.enrolment_id}`;
}

export default function LearnDashboardPage() {
  const { ready } = useRequireAuth();
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [paths, setPaths] = useState<OwnPathEnrolment[]>([]);

  useEffect(() => {
    if (!ready || !getAccessToken()) return;
    authedFetch("/api/bff/learn/dashboard")
      .then(async (resp) => {
        if (!resp.ok) {
          setError("Your learning could not be loaded. Try again shortly.");
          return;
        }
        setData(await resp.json());
      })
      .catch(() => setError("Your learning could not be loaded. Try again shortly."));
    authedFetch("/api/bff/path-enrolments")
      .then((resp) => (resp.ok ? resp.json() : []))
      .then((rows) => setPaths(rows ?? []))
      .catch(() => undefined);
  }, [ready]);

  if (error) {
    return (
      <main className="pad-lg">
        <p className="callout callout--warn" role="alert">
          {error}
        </p>
      </main>
    );
  }

  if (data === null) {
    return (
      <main className="pad-lg">
        <p style={{ color: "var(--muted)" }}>Loading your learning…</p>
      </main>
    );
  }

  const active = data.enrolments.filter((e) => e.status === "in_progress");
  const notStarted = data.enrolments.filter((e) => e.status === "not_started");
  const completed = data.enrolments.filter((e) => e.status === "completed");
  // The one to resume: furthest along among those actually started.
  const resume = active.slice().sort((a, b) => b.progress_percent - a.progress_percent)[0] ?? null;
  const hasAnything = data.enrolments.length > 0;

  return (
    <main className="pad-lg">
      <div className="dash">
        <div className="dash-top">
          <div>
            <p className="eyebrow">{weekdayLabel()}</p>
            <h1 className="serif" style={{ fontSize: "1.75rem" }}>
              {data.first_name ? `Welcome back, ${data.first_name}` : "Welcome back"}
            </h1>
          </div>
          <span className={`tag ${hasAnything ? "tag--done" : "tag--mute"}`}>
            {hasAnything ? "Enrolment active" : "No enrolments yet"}
          </span>
        </div>

        <dl className="stats">
          <div className="stat">
            <dt>In progress</dt>
            <dd>{data.stats.in_progress}</dd>
          </div>
          <div className="stat">
            <dt>Completed</dt>
            <dd>{data.stats.completed}</dd>
          </div>
          <div className="stat">
            <dt>Certificates</dt>
            <dd>{data.stats.certificates}</dd>
          </div>
          <div className="stat">
            <dt>Workshop credits</dt>
            <dd>{data.stats.workshop_credits}</dd>
          </div>
        </dl>

        {resume ? (
          <div className="continue">
            <span
              className="continue-art"
              style={{ background: safeColour(resume.hero_colour) }}
              aria-hidden="true"
            />
            <div style={{ display: "grid", gap: ".5rem" }}>
              <p className="eyebrow">Continue where you left off</p>
              <h2 className="serif" style={{ fontSize: "1.25rem" }}>
                {resume.course_title}
              </h2>
              {resume.next_lesson ? (
                <p style={{ fontSize: ".8125rem", color: "var(--muted)" }}>
                  {resume.next_lesson.position_label} · {resume.next_lesson.title}
                </p>
              ) : null}
              <span
                className="bar"
                style={{ maxWidth: 340 }}
                role="progressbar"
                aria-valuenow={resume.progress_percent}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label={`${resume.course_title} progress`}
              >
                <i style={{ width: `${resume.progress_percent}%` }} />
              </span>
              <p style={{ fontSize: ".75rem", color: "var(--muted)" }}>
                {resume.progress_percent}% complete · {resume.lessons_completed} of{" "}
                {resume.lessons_total} lessons
              </p>
            </div>
            <Link className="btn btn--primary btn--lg" href={resumeHref(resume)}>
              Resume
            </Link>
          </div>
        ) : null}

        {!hasAnything ? (
          <div className="callout">
            <b>Nothing enrolled yet</b>
            Once you enrol, this is where your progress, upcoming workshops and certificates
            appear. <Link href="/catalogue">Browse the programmes →</Link>
          </div>
        ) : null}

        <section id="workshops">
          <h2 className="serif" style={{ fontSize: "1.125rem", marginBottom: ".7rem" }}>
            Coming up
          </h2>
          {data.upcoming.length === 0 ? (
            <p style={{ fontSize: ".8125rem", color: "var(--muted)" }}>
              Nothing scheduled. Live workshop seats and module assessments show up here.
            </p>
          ) : (
            <div className="rowlist">
              {data.upcoming.map((item, i) => (
                <div className="rowitem" key={`${item.kind}-${item.lesson_id ?? item.title}-${i}`}>
                  <span className={`tag ${item.kind === "workshop" ? "tag--live" : "tag--mute"}`}>
                    {item.kind === "workshop" ? "Workshop" : "Assessment"}
                  </span>
                  <span className="t">{item.title}</span>
                  <span className="m">
                    {item.starts_at
                      ? formatDateTime(item.starts_at)
                      : item.attempts_remaining !== null
                        ? `${item.attempts_remaining} attempts remaining`
                        : (item.subtitle ?? "")}
                  </span>
                  {item.kind === "workshop" && item.join_url ? (
                    <a
                      className="btn btn--ghost"
                      href={item.join_url}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {PROVIDER_LABEL[item.provider ?? ""] ?? "Join session"}
                    </a>
                  ) : item.enrolment_id ? (
                    <Link
                      className="btn btn--ghost"
                      href={`/learn/${item.enrolment_id}${item.lesson_id ? `?lesson=${item.lesson_id}` : ""}`}
                    >
                      Start
                    </Link>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </section>

        {paths.length > 0 ? (
          <section>
            <h2 className="serif" style={{ fontSize: "1.125rem", marginBottom: ".7rem" }}>
              Learning paths
            </h2>
            <div className="rowlist">
              {paths.map((p) => (
                <div className="rowitem" key={p.path_enrolment_id}>
                  <span className={`tag ${p.completed_at ? "tag--done" : "tag--live"}`}>
                    {p.completed_at
                      ? p.has_certificate
                        ? "Certified"
                        : "Completed"
                      : "In progress"}
                  </span>
                  <span className="t">{p.learning_path_title}</span>
                  <span className="m">{p.course_count} courses</span>
                  <Link className="btn btn--ghost" href={`/learn/paths/${p.path_enrolment_id}`}>
                    {p.completed_at
                      ? p.has_certificate
                        ? "View certificate"
                        : "View path"
                      : "View progress"}
                  </Link>
                </div>
              ))}
            </div>
          </section>
        ) : null}

        {notStarted.length > 0 ? (
          <section>
            <h2 className="serif" style={{ fontSize: "1.125rem", marginBottom: ".7rem" }}>
              Not started
            </h2>
            <div className="rowlist">
              {notStarted.map((e) => (
                <div className="rowitem" key={e.enrolment_id}>
                  <span className="tag tag--mute">Enrolled</span>
                  <span className="t">{e.course_title}</span>
                  <span className="m">{e.lessons_total} lessons</span>
                  <Link className="btn btn--ghost" href={resumeHref(e)}>
                    Start
                  </Link>
                </div>
              ))}
            </div>
          </section>
        ) : null}

        {active.length > 1 ? (
          <section>
            <h2 className="serif" style={{ fontSize: "1.125rem", marginBottom: ".7rem" }}>
              In progress
            </h2>
            <div className="rowlist">
              {active
                .filter((e) => e.enrolment_id !== resume?.enrolment_id)
                .map((e) => (
                  <div className="rowitem" key={e.enrolment_id}>
                    <span className="tag tag--live">{e.progress_percent}%</span>
                    <span className="t">{e.course_title}</span>
                    <span className="m">
                      {e.lessons_completed} of {e.lessons_total} lessons
                    </span>
                    <Link className="btn btn--ghost" href={resumeHref(e)}>
                      Resume
                    </Link>
                  </div>
                ))}
            </div>
          </section>
        ) : null}

        <section id="completed">
          <h2 className="serif" style={{ fontSize: "1.125rem", marginBottom: ".7rem" }}>
            Completed
          </h2>
          {completed.length === 0 ? (
            <p style={{ fontSize: ".8125rem", color: "var(--muted)" }}>
              Nothing finished yet. A certificate is issued the moment every completion rule on a
              programme is met.
            </p>
          ) : (
            <div className="rowlist">
              {completed.map((e) => (
                <div className="rowitem" key={e.enrolment_id}>
                  <span className="tag tag--done">
                    {e.certificate ? "Certified" : "Completed"}
                  </span>
                  <span className="t">{e.course_title}</span>
                  <span className="m">
                    {e.certificate?.issued_at
                      ? `Issued ${formatDate(e.certificate.issued_at)}`
                      : e.completed_at
                        ? `Completed ${formatDate(e.completed_at)}`
                        : ""}
                  </span>
                  <Link className="btn btn--ghost" href={`/learn/${e.enrolment_id}#certificate`}>
                    {e.certificate ? "View certificate" : "Review"}
                  </Link>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
