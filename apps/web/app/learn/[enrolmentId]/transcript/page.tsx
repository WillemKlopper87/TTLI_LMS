"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { getAccessToken } from "@/lib/session";
import { useRequireAuth } from "@/lib/session-context";

interface TranscriptLesson {
  module_title: string;
  title: string;
  position: number;
  completed_at: string | null;
}

interface Transcript {
  learner_name: string;
  course_title: string;
  enrolled_at: string;
  completed_at: string | null;
  certificate_number: string | null;
  lessons: TranscriptLesson[];
}

/**
 * REQ-LMS-06: a printable transcript. Browser print (window.print via a
 * @media print rule in globals.css), not a generated PDF — the transcript's
 * job is to be a correct, printable record, not to duplicate the
 * certificate's own PDF+QR treatment (credentials-panel.tsx).
 */
export default function TranscriptPage() {
  const { ready } = useRequireAuth();
  const { enrolmentId } = useParams<{ enrolmentId: string }>();
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    async function load() {
      const token = getAccessToken();
      if (!token) return;
      const resp = await fetch(`/api/bff/enrolments/${enrolmentId}/transcript`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!resp.ok) {
        if (!cancelled) setError("This transcript could not be loaded.");
        return;
      }
      if (!cancelled) setTranscript(await resp.json());
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [ready, enrolmentId]);

  if (error) {
    return (
      <main className="mx-auto max-w-2xl px-6 py-16">
        <p role="alert" style={{ fontSize: "0.875rem", color: "var(--stop)" }}>{error}</p>
      </main>
    );
  }
  if (transcript === null) {
    return (
      <main className="mx-auto max-w-2xl px-6 py-16">
        <p style={{ fontSize: "0.875rem", color: "var(--faint)" }}>Loading…</p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-2xl px-6 py-16">
      <div className="no-print flex items-center justify-between">
        <Link href={`/learn/${enrolmentId}`} className="btn btn--ghost">
          &larr; Back to course
        </Link>
        <button type="button" onClick={() => window.print()} className="btn btn--primary">
          Print transcript
        </button>
      </div>

      <div className="card mt-6 flex flex-col gap-4">
        <div>
          <p className="eyebrow">Learning transcript</p>
          <h1 className="serif mt-1" style={{ fontSize: "1.5rem" }}>
            {transcript.course_title}
          </h1>
        </div>

        <dl className="grid grid-cols-2 gap-3" style={{ fontSize: "0.8125rem" }}>
          <div>
            <dt style={{ color: "var(--faint)" }}>Learner</dt>
            <dd>{transcript.learner_name}</dd>
          </div>
          <div>
            <dt style={{ color: "var(--faint)" }}>Enrolled</dt>
            <dd>{new Date(transcript.enrolled_at).toLocaleDateString()}</dd>
          </div>
          <div>
            <dt style={{ color: "var(--faint)" }}>Course completed</dt>
            <dd>
              {transcript.completed_at
                ? new Date(transcript.completed_at).toLocaleDateString()
                : "In progress"}
            </dd>
          </div>
          {transcript.certificate_number ? (
            <div>
              <dt style={{ color: "var(--faint)" }}>Certificate</dt>
              <dd>{transcript.certificate_number}</dd>
            </div>
          ) : null}
        </dl>

        <div className="table-wrap">
          <table className="data">
            <caption className="sr-only">Completed lessons for {transcript.course_title}</caption>
            <thead>
              <tr>
                <th scope="col">Module</th>
                <th scope="col">Lesson</th>
                <th scope="col">Completed</th>
              </tr>
            </thead>
            <tbody>
              {transcript.lessons.length === 0 ? (
                <tr>
                  <td colSpan={3} style={{ color: "var(--faint)" }}>
                    No lessons completed yet.
                  </td>
                </tr>
              ) : (
                transcript.lessons.map((lesson) => (
                  <tr key={lesson.position}>
                    <td>{lesson.module_title}</td>
                    <td>{lesson.title}</td>
                    <td>
                      {lesson.completed_at ? new Date(lesson.completed_at).toLocaleDateString() : ""}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </main>
  );
}
