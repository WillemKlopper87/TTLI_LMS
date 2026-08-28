"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { authedFetch } from "@/lib/authed-fetch";
import { useRequireAuth } from "@/lib/session-context";

import { CredentialsPanel } from "../../[enrolmentId]/credentials-panel";

interface PathCourseProgress {
  course_id: string;
  course_title: string;
  // Null when this learner has no reachable enrolment for the course —
  // added to the path after purchase, or an expired entitlement (F2,
  // docs/research/p5-review-findings.md).
  enrolment_id: string | null;
  progress_percent: number;
  completed_at: string | null;
}

interface PathProgress {
  path_enrolment_id: string;
  learning_path_id: string;
  progress_percent: number;
  completed_at: string | null;
  courses: PathCourseProgress[];
}

/**
 * A learning path's own progress page (P5 phase 4) — the path
 * equivalent of `/learn/[enrolmentId]`, but there is no lesson player
 * here: a path has no lessons of its own, only member courses each with
 * their own player already reachable from `/learn`. This page shows the
 * rollup and links out to whichever member course needs attention next.
 */
export default function LearnPathEnrolmentPage() {
  const { ready } = useRequireAuth();
  const { pathEnrolmentId } = useParams<{ pathEnrolmentId: string }>();

  const [progress, setProgress] = useState<PathProgress | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const resp = await authedFetch(`/api/bff/path-enrolments/${pathEnrolmentId}/progress`);
    if (!resp.ok) {
      setError("This learning path could not be loaded.");
      return;
    }
    setProgress(await resp.json());
  }, [pathEnrolmentId]);

  useEffect(() => {
    if (!ready) return;
    void (async () => {
      await load();
    })();
  }, [ready, load]);

  if (error) {
    return (
      <main className="pad-lg">
        <p className="callout callout--stop" role="alert">
          {error}
        </p>
      </main>
    );
  }

  if (progress === null) {
    return (
      <main className="pad-lg">
        <p style={{ color: "var(--muted)" }}>Loading this learning path…</p>
      </main>
    );
  }

  return (
    <main className="pad-lg">
      <div style={{ display: "grid", gap: "1.5rem", maxWidth: "48rem" }}>
        <div>
          <p className="eyebrow">Learning path</p>
          <h1 className="serif" style={{ fontSize: "1.5rem", margin: "0.35rem 0 0.7rem" }}>
            Your progress
          </h1>
          <span
            className="bar"
            style={{ maxWidth: 340 }}
            role="progressbar"
            aria-valuenow={progress.progress_percent}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Learning path progress"
          >
            <i style={{ width: `${progress.progress_percent}%` }} />
          </span>
          <p style={{ fontSize: "0.8125rem", color: "var(--muted)", marginTop: "0.4rem" }}>
            {progress.progress_percent}% complete
            {progress.completed_at ? " · every course finished" : ""}
          </p>
        </div>

        <div className="rowlist">
          {progress.courses.map((c) => (
            <div className="rowitem" key={c.course_id}>
              <span
                className={`tag ${c.completed_at ? "tag--done" : c.enrolment_id ? "tag--live" : "tag--mute"}`}
              >
                {c.completed_at ? "Completed" : c.enrolment_id ? `${c.progress_percent}%` : "Not enrolled"}
              </span>
              <span className="t">{c.course_title}</span>
              {c.enrolment_id ? (
                <Link className="btn btn--ghost" href={`/learn/${c.enrolment_id}`}>
                  {c.completed_at ? "Review" : "Continue"}
                </Link>
              ) : null}
            </div>
          ))}
        </div>

        {progress.completed_at ? (
          <div id="certificate">
            <CredentialsPanel pathEnrolmentId={progress.path_enrolment_id} />
          </div>
        ) : null}

        <Link className="btn btn--quiet" href="/learn" style={{ justifySelf: "start" }}>
          ← My learning
        </Link>
      </div>
    </main>
  );
}
