"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { getAccessToken } from "@/lib/session";
import { useRequireAuth } from "@/lib/session-context";

interface Organisation {
  id: string;
  name: string;
}

interface Member {
  user_id: string;
  email: string;
  relationship: string;
}

interface SeatSummary {
  course_id: string;
  course_title: string;
  purchased: number;
  assigned: number;
  available: number;
}

interface SeatAssignmentResult {
  email: string;
  ok: boolean;
  reason: string | null;
}

interface AssignedSeat {
  entitlement_id: string;
  user_id: string;
  email: string;
  granted_at: string;
}

interface LearnerRow {
  user_id: string;
  email: string;
  status: string;
  completed_at: string | null;
  best_quiz_score: string | null;
}

interface ProgressReport {
  course_id: string;
  course_title: string;
  enrolled: number;
  completed: number;
  completion_rate: number;
  individual_visible: boolean;
  learners: LearnerRow[];
}

const STATUS_TAG: Record<string, string> = {
  completed: "tag--done",
  in_progress: "tag--live",
  not_started: "tag--mute",
};

const RELATIONSHIP_TAG: Record<string, string> = {
  admin: "tag--brand",
  manager: "tag--live",
  member: "tag--mute",
};

/**
 * Org admin's home base (02 §4.5): members, the seat pool per course, and
 * the two bulk-invite paths (typed emails, CSV import). Every mutating
 * action here is gated server-side on `require_admin` — a non-admin
 * member sees the same 403-driven read-only fallback used elsewhere
 * (payments/leads screens), not a client-side permission guess.
 */
export default function OrganisationDetailPage() {
  const params = useParams<{ id: string }>();
  const { ready } = useRequireAuth();
  const orgId = params.id;

  const [org, setOrg] = useState<Organisation | null>(null);
  const [members, setMembers] = useState<Member[] | null>(null);
  const [seats, setSeats] = useState<SeatSummary[] | null>(null);
  const [error, setError] = useState<"forbidden" | "unknown" | null>(null);

  const [inviteCourseId, setInviteCourseId] = useState("");
  const [inviteEmails, setInviteEmails] = useState("");
  const [inviteBusy, setInviteBusy] = useState(false);
  const [inviteResults, setInviteResults] = useState<SeatAssignmentResult[] | null>(null);

  const [csvCourseId, setCsvCourseId] = useState("");
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvBusy, setCsvBusy] = useState(false);

  const [expandedCourseId, setExpandedCourseId] = useState<string | null>(null);
  const [holders, setHolders] = useState<AssignedSeat[] | null>(null);
  const [revokeBusy, setRevokeBusy] = useState<string | null>(null);

  const [reportCourseId, setReportCourseId] = useState<string | null>(null);
  const [report, setReport] = useState<ProgressReport | null>(null);

  async function authedFetch(path: string, init: RequestInit = {}) {
    const token = getAccessToken();
    return fetch(path, { ...init, headers: { ...init.headers, Authorization: `Bearer ${token}` } });
  }

  async function load() {
    const [orgResp, membersResp, seatsResp] = await Promise.all([
      authedFetch(`/api/bff/organisations/${orgId}`),
      authedFetch(`/api/bff/organisations/${orgId}/members`),
      authedFetch(`/api/bff/organisations/${orgId}/seats`),
    ]);
    if (orgResp.status === 403 || membersResp.status === 403 || seatsResp.status === 403) {
      setError("forbidden");
      return;
    }
    if (!orgResp.ok || !membersResp.ok || !seatsResp.ok) {
      setError("unknown");
      return;
    }
    setOrg(await orgResp.json());
    setMembers((await membersResp.json()).items);
    setSeats((await seatsResp.json()).items);
  }

  useEffect(() => {
    if (!ready || !getAccessToken()) return;
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, orgId]);

  async function invite() {
    const emails = inviteEmails
      .split(/[\n,]/)
      .map((e) => e.trim())
      .filter(Boolean);
    if (!inviteCourseId.trim() || emails.length === 0) return;
    setInviteBusy(true);
    setInviteResults(null);
    const resp = await authedFetch(`/api/bff/organisations/${orgId}/seats/invite`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ course_id: inviteCourseId.trim(), emails }),
    });
    setInviteBusy(false);
    if (resp.ok) {
      setInviteResults((await resp.json()).items);
      setInviteEmails("");
      await load();
    }
  }

  async function importCsv() {
    if (!csvCourseId.trim() || !csvFile) return;
    setCsvBusy(true);
    const formData = new FormData();
    formData.append("file", csvFile);
    const resp = await authedFetch(
      `/api/bff/organisations/${orgId}/seats/import?course_id=${encodeURIComponent(csvCourseId.trim())}`,
      { method: "POST", body: formData },
    );
    setCsvBusy(false);
    if (resp.ok) {
      setInviteResults((await resp.json()).items);
      setCsvFile(null);
      await load();
    }
  }

  async function loadHolders(courseId: string) {
    const resp = await authedFetch(`/api/bff/organisations/${orgId}/seats/${courseId}/assignments`);
    if (resp.ok) setHolders((await resp.json()).items);
  }

  async function toggleHolders(courseId: string) {
    if (expandedCourseId === courseId) {
      setExpandedCourseId(null);
      setHolders(null);
      return;
    }
    setExpandedCourseId(courseId);
    setHolders(null);
    await loadHolders(courseId);
  }

  async function toggleReport(courseId: string) {
    if (reportCourseId === courseId) {
      setReportCourseId(null);
      setReport(null);
      return;
    }
    setReportCourseId(courseId);
    setReport(null);
    const resp = await authedFetch(
      `/api/bff/organisations/${orgId}/reports/progress?course_id=${courseId}`,
    );
    if (resp.ok) setReport(await resp.json());
  }

  async function revoke(entitlementId: string) {
    setRevokeBusy(entitlementId);
    const resp = await authedFetch(`/api/bff/organisations/${orgId}/seats/${entitlementId}/revoke`, {
      method: "POST",
    });
    setRevokeBusy(null);
    if (resp.ok) {
      await load();
      if (expandedCourseId) await loadHolders(expandedCourseId);
    }
  }

  if (error === "forbidden") {
    return (
      <main className="mx-auto max-w-3xl px-6 py-16">
        <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
          You are not a member of this organisation.
        </p>
      </main>
    );
  }
  if (error === "unknown" || org === null || members === null || seats === null) {
    return (
      <main className="mx-auto max-w-3xl px-6 py-16">
        <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>
          {error === "unknown" ? "This organisation could not be loaded." : "Loading…"}
        </p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <p className="eyebrow">Organisation</p>
      <h1 className="serif mt-2" style={{ fontSize: "1.75rem" }}>
        {org.name}
      </h1>

      <div className="mt-6 flex flex-wrap gap-2">
        <Link href={`/organisations/${orgId}/buy-seats`} className="btn btn--primary">
          Buy seats
        </Link>
      </div>

      <section className="mt-10">
        <h2 className="serif" style={{ fontSize: "1.125rem" }}>
          Seats
        </h2>
        {seats.length === 0 ? (
          <p className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>
            No seats purchased yet — start with &ldquo;Buy seats&rdquo; above.
          </p>
        ) : (
          <div className="table-wrap mt-4">
            <table className="data">
              <thead>
                <tr>
                  <th scope="col">Course</th>
                  <th scope="col">Purchased</th>
                  <th scope="col">Assigned</th>
                  <th scope="col">Available</th>
                  <th scope="col"></th>
                  <th scope="col"></th>
                </tr>
              </thead>
              <tbody>
                {seats.map((row) => (
                  <tr key={row.course_id}>
                    <td>{row.course_title}</td>
                    <td className="mono">{row.purchased}</td>
                    <td className="mono">{row.assigned}</td>
                    <td className="mono">{row.available}</td>
                    <td>
                      {row.assigned > 0 ? (
                        <button
                          type="button"
                          className="btn btn--ghost"
                          onClick={() => toggleHolders(row.course_id)}
                        >
                          {expandedCourseId === row.course_id ? "Hide" : "Manage"}
                        </button>
                      ) : null}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn--ghost"
                        onClick={() => toggleReport(row.course_id)}
                      >
                        {reportCourseId === row.course_id ? "Hide report" : "Report"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {expandedCourseId ? (
          <div className="card mt-3 p-4">
            <b style={{ fontSize: "0.8125rem" }}>Seat holders</b>
            {holders === null ? (
              <p className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>
                Loading…
              </p>
            ) : holders.length === 0 ? (
              <p className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>
                No one holds a seat for this course.
              </p>
            ) : (
              <div className="mt-2 flex flex-col gap-2">
                {holders.map((h) => (
                  <div key={h.entitlement_id} className="flex items-center justify-between gap-2">
                    <span className="mono" style={{ fontSize: "0.8125rem" }}>
                      {h.email}
                    </span>
                    <button
                      type="button"
                      className="btn btn--ghost"
                      disabled={revokeBusy === h.entitlement_id}
                      onClick={() => revoke(h.entitlement_id)}
                    >
                      Revoke
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : null}

        {reportCourseId ? (
          <div className="card mt-3 p-4">
            <b style={{ fontSize: "0.8125rem" }}>Progress report</b>
            {report === null ? (
              <p className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>
                Loading…
              </p>
            ) : (
              <>
                <div className="mt-2 flex flex-wrap gap-4" style={{ fontSize: "0.8125rem" }}>
                  <span>
                    Enrolled <b className="mono">{report.enrolled}</b>
                  </span>
                  <span>
                    Completed <b className="mono">{report.completed}</b>
                  </span>
                  <span>
                    Completion rate{" "}
                    <b className="mono">{Math.round(report.completion_rate * 100)}%</b>
                  </span>
                </div>
                {report.individual_visible ? (
                  <div className="mt-3 flex flex-col gap-2">
                    {report.learners.map((row) => (
                      <div
                        key={row.user_id}
                        className="flex flex-wrap items-center justify-between gap-2"
                      >
                        <span className="mono" style={{ fontSize: "0.8125rem" }}>
                          {row.email}
                        </span>
                        <span className="flex items-center gap-2">
                          {row.best_quiz_score !== null ? (
                            <span className="mono" style={{ fontSize: "0.75rem" }}>
                              {row.best_quiz_score}%
                            </span>
                          ) : null}
                          <span className={`tag ${STATUS_TAG[row.status] ?? "tag--mute"}`}>
                            {row.status.replace("_", " ")}
                          </span>
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="mt-3" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
                    Individual results are hidden — an admin has not enabled manager visibility
                    for this course.
                  </p>
                )}
              </>
            )}
          </div>
        ) : null}
      </section>

      <section className="mt-10 grid gap-4 md:grid-cols-2">
        <div className="card p-5">
          <b style={{ fontSize: "0.875rem" }}>Invite by email</b>
          <label className="field mt-3">
            <b>Course ID</b>
            <input
              className="input"
              value={inviteCourseId}
              onChange={(e) => setInviteCourseId(e.target.value)}
              placeholder="course UUID"
            />
          </label>
          <label className="field mt-3">
            <b>Email addresses</b>
            <textarea
              className="input"
              style={{ minHeight: "5rem" }}
              value={inviteEmails}
              onChange={(e) => setInviteEmails(e.target.value)}
              placeholder="one per line, or comma-separated"
            />
          </label>
          <button
            type="button"
            className="btn btn--primary mt-3"
            disabled={inviteBusy || !inviteCourseId.trim() || !inviteEmails.trim()}
            onClick={invite}
          >
            Assign seats
          </button>
        </div>

        <div className="card p-5">
          <b style={{ fontSize: "0.875rem" }}>Import from CSV</b>
          <label className="field mt-3">
            <b>Course ID</b>
            <input
              className="input"
              value={csvCourseId}
              onChange={(e) => setCsvCourseId(e.target.value)}
              placeholder="course UUID"
            />
          </label>
          <label className="field mt-3">
            <b>File</b>
            <input
              className="input"
              type="file"
              accept=".csv,text/csv"
              onChange={(e) => setCsvFile(e.target.files?.[0] ?? null)}
            />
          </label>
          <button
            type="button"
            className="btn btn--primary mt-3"
            disabled={csvBusy || !csvCourseId.trim() || !csvFile}
            onClick={importCsv}
          >
            Import
          </button>
        </div>
      </section>

      {inviteResults ? (
        <section className="mt-6">
          <b style={{ fontSize: "0.8125rem" }}>Result</b>
          <ul className="mt-2 flex flex-col gap-1">
            {inviteResults.map((r) => (
              <li key={r.email} style={{ fontSize: "0.8125rem" }}>
                <span className={`tag ${r.ok ? "tag--done" : "tag--stop"}`}>{r.ok ? "ok" : "failed"}</span>{" "}
                <span className="mono">{r.email}</span>
                {r.reason ? <span style={{ color: "var(--muted)" }}> — {r.reason}</span> : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="mt-10">
        <h2 className="serif" style={{ fontSize: "1.125rem" }}>
          Members
        </h2>
        <div className="mt-4 flex flex-col gap-2">
          {members.map((m) => (
            <div key={m.user_id} className="card flex items-center justify-between gap-2 p-3">
              <span className="mono" style={{ fontSize: "0.8125rem" }}>
                {m.email}
              </span>
              <span className={`tag ${RELATIONSHIP_TAG[m.relationship] ?? "tag--mute"}`}>
                {m.relationship}
              </span>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
