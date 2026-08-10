"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { getAccessToken } from "@/lib/session";

interface OwnEnrolment {
  enrolment_id: string;
  course_id: string;
  course_title: string;
  started_at: string | null;
  completed_at: string | null;
}

/**
 * "My courses" (REQ-LMS-03) — lists the caller's own enrolments via
 * GET /enrolments, sourced from an entitlement (services/orders.py's
 * approve_eft), never anything the client asserts.
 */
export default function LearnIndexPage() {
  const router = useRouter();
  const [enrolments, setEnrolments] = useState<OwnEnrolment[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    fetch("/api/bff/enrolments", { headers: { Authorization: `Bearer ${token}` } })
      .then(async (resp) => {
        if (!resp.ok) {
          setError("Your courses could not be loaded. Try again shortly.");
          return;
        }
        setEnrolments(await resp.json());
      })
      .catch(() => setError("Your courses could not be loaded. Try again shortly."));
  }, [router]);

  return (
    <main className="mx-auto max-w-2xl px-6 py-16">
      <h1 className="serif" style={{ fontSize: "1.65rem" }}>
        My courses
      </h1>

      {error ? (
        <p role="alert" className="mt-6" style={{ fontSize: "0.875rem", color: "var(--stop)" }}>
          {error}
        </p>
      ) : enrolments === null ? (
        <p className="mt-6" style={{ fontSize: "0.875rem", color: "var(--faint)" }}>
          Loading…
        </p>
      ) : enrolments.length === 0 ? (
        <p className="mt-6" style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
          You are not enrolled in anything yet.{" "}
          <Link href="/catalogue">Browse programmes</Link>.
        </p>
      ) : (
        <ul className="mt-6 flex flex-col gap-3">
          {enrolments.map((e) => (
            <li key={e.enrolment_id} className="card">
              <Link href={`/learn/${e.enrolment_id}`} className="flex items-center justify-between">
                <span className="serif" style={{ fontSize: "1.0625rem" }}>
                  {e.course_title}
                </span>
                <span className={`tag ${e.completed_at ? "tag--done" : "tag--live"}`}>
                  {e.completed_at ? "Completed" : e.started_at ? "In progress" : "Not started"}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
