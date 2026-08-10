"use client";

import { useEffect, useState } from "react";

import { getAccessToken } from "@/lib/session";

import { useAdmin } from "../admin-context";

interface Facilitator {
  id: string;
  user_id: string;
  email: string;
  bio: string | null;
  timezone: string;
}

interface AvailabilityWindow {
  id: string;
  day_of_week: number;
  start_time: string;
  end_time: string;
}

interface WorkshopItem {
  id: string;
  title: string;
  description: string | null;
  session_type: string;
  default_duration_minutes: number;
}

interface SessionItem {
  id: string;
  workshop_id: string;
  facilitator_id: string;
  starts_at: string;
  ends_at: string;
  capacity: number;
  status: string;
  registered: number;
  waitlisted: number;
}

interface RosterRow {
  booking_id: string;
  user_id: string;
  email: string;
  booking_status: string;
  attendance_status: string;
}

const DAY_LABEL = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const SESSION_TYPES = ["one_on_one", "group_workshop", "cohort_session", "assessment_debrief"];
const ATTENDANCE_STATES = [
  "registered",
  "joined",
  "attended",
  "partially_attended",
  "no_show",
  "cancelled",
  "rescheduled",
];

const BOOKING_TAG: Record<string, string> = {
  registered: "tag--done",
  waitlisted: "tag--live",
  cancelled: "tag--mute",
};

/**
 * Workshops, facilitators, booking (02 §9, REQ-WS-01 through REQ-WS-09).
 * Create/manage is `workshop:manage`-only (checked server-side, mirrored
 * here only to hide forms a caller can't use); booking a session is
 * self-service for any authenticated user; a session's roster is gated
 * on being that session's own facilitator or holding `workshop:manage`
 * — a facilitator without manage rights still sees exactly their own
 * sessions' rosters, everything else 403s the same way `/organisations`
 * screens already handle a refused fetch.
 */
export default function WorkshopsScreen() {
  const { me } = useAdmin();
  const canManage = me.permissions.includes("workshop:manage");

  const [facilitators, setFacilitators] = useState<Facilitator[] | null>(null);
  const [workshops, setWorkshops] = useState<WorkshopItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [facilitatorEmail, setFacilitatorEmail] = useState("");
  const [facilitatorBio, setFacilitatorBio] = useState("");
  const [facilitatorBusy, setFacilitatorBusy] = useState(false);

  const [availFacilitatorId, setAvailFacilitatorId] = useState("");
  const [availDay, setAvailDay] = useState(1);
  const [availStart, setAvailStart] = useState("09:00");
  const [availEnd, setAvailEnd] = useState("17:00");
  const [availBusy, setAvailBusy] = useState(false);
  const [windows, setWindows] = useState<Record<string, AvailabilityWindow[]>>({});

  const [workshopTitle, setWorkshopTitle] = useState("");
  const [workshopType, setWorkshopType] = useState(SESSION_TYPES[0]);
  const [workshopBusy, setWorkshopBusy] = useState(false);

  const [selectedWorkshopId, setSelectedWorkshopId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionItem[] | null>(null);

  const [sessionFacilitatorId, setSessionFacilitatorId] = useState("");
  const [sessionStartsAt, setSessionStartsAt] = useState("");
  const [sessionCapacity, setSessionCapacity] = useState(5);
  const [sessionBusy, setSessionBusy] = useState(false);

  const [bookBusy, setBookBusy] = useState<string | null>(null);
  const [rosterSessionId, setRosterSessionId] = useState<string | null>(null);
  const [roster, setRoster] = useState<RosterRow[] | null>(null);

  async function authedFetch(path: string, init: RequestInit = {}) {
    const token = getAccessToken();
    return fetch(path, { ...init, headers: { ...init.headers, Authorization: `Bearer ${token}` } });
  }

  async function loadFacilitators() {
    const resp = await authedFetch("/api/bff/facilitators");
    if (resp.ok) setFacilitators((await resp.json()).items);
  }

  async function loadWorkshops() {
    const resp = await authedFetch("/api/bff/workshops");
    if (resp.ok) setWorkshops((await resp.json()).items);
  }

  useEffect(() => {
    loadFacilitators();
    loadWorkshops();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function loadWindows(facilitatorId: string) {
    const resp = await authedFetch(`/api/bff/facilitators/${facilitatorId}/availability`);
    if (resp.ok) {
      const items = (await resp.json()).items;
      setWindows((prev) => ({ ...prev, [facilitatorId]: items }));
    }
  }

  async function createFacilitator() {
    if (!facilitatorEmail.trim()) return;
    setFacilitatorBusy(true);
    setError(null);
    const resp = await authedFetch("/api/bff/facilitators", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: facilitatorEmail.trim(), bio: facilitatorBio.trim() || null }),
    });
    setFacilitatorBusy(false);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not create the facilitator.");
      return;
    }
    setFacilitatorEmail("");
    setFacilitatorBio("");
    await loadFacilitators();
  }

  async function addAvailability() {
    if (!availFacilitatorId) return;
    setAvailBusy(true);
    setError(null);
    const resp = await authedFetch(`/api/bff/facilitators/${availFacilitatorId}/availability`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ day_of_week: availDay, start_time: availStart, end_time: availEnd }),
    });
    setAvailBusy(false);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not add that availability window.");
      return;
    }
    await loadWindows(availFacilitatorId);
  }

  async function createWorkshop() {
    if (!workshopTitle.trim()) return;
    setWorkshopBusy(true);
    setError(null);
    const resp = await authedFetch("/api/bff/workshops", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: workshopTitle.trim(), session_type: workshopType }),
    });
    setWorkshopBusy(false);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not create the workshop.");
      return;
    }
    setWorkshopTitle("");
    await loadWorkshops();
  }

  async function selectWorkshop(workshopId: string) {
    setSelectedWorkshopId(workshopId);
    setSessions(null);
    setRosterSessionId(null);
    const resp = await authedFetch(`/api/bff/workshops/${workshopId}/sessions`);
    if (resp.ok) setSessions((await resp.json()).items);
  }

  async function createSession() {
    if (!selectedWorkshopId || !sessionFacilitatorId || !sessionStartsAt) return;
    setSessionBusy(true);
    setError(null);
    const starts = new Date(sessionStartsAt);
    const ends = new Date(starts.getTime() + 60 * 60 * 1000);
    const resp = await authedFetch(`/api/bff/workshops/${selectedWorkshopId}/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        facilitator_id: sessionFacilitatorId,
        starts_at: starts.toISOString(),
        ends_at: ends.toISOString(),
        capacity: sessionCapacity,
      }),
    });
    setSessionBusy(false);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not create the session.");
      return;
    }
    await selectWorkshop(selectedWorkshopId);
  }

  async function bookSession(sessionId: string) {
    setBookBusy(sessionId);
    setError(null);
    const resp = await authedFetch(`/api/bff/sessions/${sessionId}/book`, { method: "POST" });
    setBookBusy(null);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not book that session.");
      return;
    }
    if (selectedWorkshopId) await selectWorkshop(selectedWorkshopId);
  }

  async function viewRoster(sessionId: string) {
    if (rosterSessionId === sessionId) {
      setRosterSessionId(null);
      setRoster(null);
      return;
    }
    setRosterSessionId(sessionId);
    setRoster(null);
    const resp = await authedFetch(`/api/bff/sessions/${sessionId}/roster`);
    if (resp.status === 403) {
      setError("You do not have access to this session's roster.");
      return;
    }
    if (resp.ok) setRoster((await resp.json()).items);
  }

  async function markAttendance(sessionId: string, userId: string, status: string) {
    const resp = await authedFetch(`/api/bff/sessions/${sessionId}/attendance`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, status }),
    });
    if (resp.ok) await viewRoster(sessionId).then(() => viewRoster(sessionId));
  }

  if (facilitators === null || workshops === null) {
    return <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>Loading…</p>;
  }

  return (
    <>
      <h1 className="serif" style={{ fontSize: "1.5rem" }}>
        Workshops
      </h1>

      {error ? (
        <p role="alert" className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--stop)" }}>
          {error}
        </p>
      ) : null}

      {canManage ? (
        <section className="mt-6 grid gap-4 md:grid-cols-2">
          <div className="card p-5">
            <b style={{ fontSize: "0.875rem" }}>Register a facilitator</b>
            <label className="field mt-3">
              <b>Email (existing account)</b>
              <input
                className="input"
                value={facilitatorEmail}
                onChange={(e) => setFacilitatorEmail(e.target.value)}
                placeholder="facilitator@example.com"
              />
            </label>
            <label className="field mt-3">
              <b>Bio</b>
              <input
                className="input"
                value={facilitatorBio}
                onChange={(e) => setFacilitatorBio(e.target.value)}
                placeholder="Leadership coach, 10 years"
              />
            </label>
            <button
              type="button"
              className="btn btn--primary mt-3"
              disabled={facilitatorBusy || !facilitatorEmail.trim()}
              onClick={createFacilitator}
            >
              Register
            </button>
          </div>

          <div className="card p-5">
            <b style={{ fontSize: "0.875rem" }}>Create a workshop</b>
            <label className="field mt-3">
              <b>Title</b>
              <input
                className="input"
                value={workshopTitle}
                onChange={(e) => setWorkshopTitle(e.target.value)}
                placeholder="Executive Coaching Debrief"
              />
            </label>
            <label className="field mt-3">
              <b>Session type</b>
              <select
                className="input"
                value={workshopType}
                onChange={(e) => setWorkshopType(e.target.value)}
              >
                {SESSION_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t.replace(/_/g, " ")}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="btn btn--primary mt-3"
              disabled={workshopBusy || !workshopTitle.trim()}
              onClick={createWorkshop}
            >
              Create
            </button>
          </div>
        </section>
      ) : null}

      <section className="mt-8">
        <b style={{ fontSize: "0.9375rem" }}>Facilitators</b>
        <div className="mt-3 flex flex-col gap-2">
          {facilitators.length === 0 ? (
            <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>No facilitators yet.</p>
          ) : (
            facilitators.map((f) => (
              <div key={f.id} className="card p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="mono" style={{ fontSize: "0.8125rem" }}>
                    {f.email}
                  </span>
                  {f.bio ? (
                    <span style={{ fontSize: "0.75rem", color: "var(--muted)" }}>{f.bio}</span>
                  ) : null}
                </div>
                {canManage ? (
                  <button
                    type="button"
                    className="btn btn--ghost mt-2"
                    onClick={() => {
                      setAvailFacilitatorId(f.id);
                      loadWindows(f.id);
                    }}
                  >
                    Manage availability
                  </button>
                ) : null}
                {windows[f.id] ? (
                  <ul className="mt-2 flex flex-col gap-1">
                    {windows[f.id].map((w) => (
                      <li key={w.id} className="mono" style={{ fontSize: "0.75rem" }}>
                        {DAY_LABEL[w.day_of_week]} {w.start_time}–{w.end_time}
                      </li>
                    ))}
                    {windows[f.id].length === 0 ? (
                      <li style={{ fontSize: "0.75rem", color: "var(--faint)" }}>
                        No availability set yet.
                      </li>
                    ) : null}
                  </ul>
                ) : null}
              </div>
            ))
          )}
        </div>

        {canManage && availFacilitatorId ? (
          <div className="card mt-3 p-4">
            <b style={{ fontSize: "0.8125rem" }}>Add a weekly availability window</b>
            <div className="mt-2 flex flex-wrap items-end gap-2">
              <label className="field">
                <b>Day</b>
                <select
                  className="input"
                  value={availDay}
                  onChange={(e) => setAvailDay(Number(e.target.value))}
                >
                  {DAY_LABEL.map((label, i) => (
                    <option key={label} value={i}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <b>Start</b>
                <input
                  className="input"
                  type="time"
                  value={availStart}
                  onChange={(e) => setAvailStart(e.target.value)}
                />
              </label>
              <label className="field">
                <b>End</b>
                <input
                  className="input"
                  type="time"
                  value={availEnd}
                  onChange={(e) => setAvailEnd(e.target.value)}
                />
              </label>
              <button
                type="button"
                className="btn btn--primary"
                disabled={availBusy}
                onClick={addAvailability}
              >
                Add window
              </button>
            </div>
          </div>
        ) : null}
      </section>

      <section className="mt-8">
        <b style={{ fontSize: "0.9375rem" }}>Workshops</b>
        {workshops.length === 0 ? (
          <p className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>
            No workshops yet.
          </p>
        ) : (
          <div className="mt-3 flex flex-wrap gap-2">
            {workshops.map((w) => (
              <button
                key={w.id}
                type="button"
                className={`btn ${selectedWorkshopId === w.id ? "btn--primary" : "btn--ghost"}`}
                onClick={() => selectWorkshop(w.id)}
              >
                {w.title}
              </button>
            ))}
          </div>
        )}

        {selectedWorkshopId ? (
          <div className="mt-4">
            {canManage ? (
              <div className="card p-4">
                <b style={{ fontSize: "0.8125rem" }}>Schedule a session</b>
                <div className="mt-2 flex flex-wrap items-end gap-2">
                  <label className="field">
                    <b>Facilitator</b>
                    <select
                      className="input"
                      value={sessionFacilitatorId}
                      onChange={(e) => setSessionFacilitatorId(e.target.value)}
                    >
                      <option value="">Choose…</option>
                      {facilitators.map((f) => (
                        <option key={f.id} value={f.id}>
                          {f.email}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="field">
                    <b>Starts</b>
                    <input
                      className="input"
                      type="datetime-local"
                      value={sessionStartsAt}
                      onChange={(e) => setSessionStartsAt(e.target.value)}
                    />
                  </label>
                  <label className="field">
                    <b>Capacity</b>
                    <input
                      className="input"
                      type="number"
                      min={1}
                      style={{ maxWidth: "6rem" }}
                      value={sessionCapacity}
                      onChange={(e) => setSessionCapacity(Number(e.target.value) || 1)}
                    />
                  </label>
                  <button
                    type="button"
                    className="btn btn--primary"
                    disabled={sessionBusy || !sessionFacilitatorId || !sessionStartsAt}
                    onClick={createSession}
                  >
                    Schedule (1 hour)
                  </button>
                </div>
              </div>
            ) : null}

            <div className="table-wrap mt-4">
              <table className="data">
                <thead>
                  <tr>
                    <th scope="col">Starts</th>
                    <th scope="col">Capacity</th>
                    <th scope="col">Registered</th>
                    <th scope="col">Waitlisted</th>
                    <th scope="col">Status</th>
                    <th scope="col"></th>
                    <th scope="col"></th>
                  </tr>
                </thead>
                <tbody>
                  {(sessions ?? []).map((s) => (
                    <tr key={s.id}>
                      <td className="mono" style={{ fontSize: "0.75rem" }}>
                        {new Date(s.starts_at).toLocaleString()}
                      </td>
                      <td className="mono">{s.capacity}</td>
                      <td className="mono">{s.registered}</td>
                      <td className="mono">{s.waitlisted}</td>
                      <td>
                        <span className="tag tag--mute">{s.status}</span>
                      </td>
                      <td>
                        <button
                          type="button"
                          className="btn btn--ghost"
                          disabled={bookBusy === s.id || s.status !== "scheduled"}
                          onClick={() => bookSession(s.id)}
                        >
                          Book
                        </button>
                      </td>
                      <td>
                        <button
                          type="button"
                          className="btn btn--ghost"
                          onClick={() => viewRoster(s.id)}
                        >
                          {rosterSessionId === s.id ? "Hide roster" : "Roster"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {rosterSessionId ? (
              <div className="card mt-3 p-4">
                <b style={{ fontSize: "0.8125rem" }}>Roster</b>
                {roster === null ? (
                  <p className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>
                    Loading…
                  </p>
                ) : roster.length === 0 ? (
                  <p className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>
                    No bookings yet.
                  </p>
                ) : (
                  <div className="mt-2 flex flex-col gap-2">
                    {roster.map((r) => (
                      <div
                        key={r.booking_id}
                        className="flex flex-wrap items-center justify-between gap-2"
                      >
                        <span className="mono" style={{ fontSize: "0.8125rem" }}>
                          {r.email}
                        </span>
                        <span className="flex items-center gap-2">
                          <span className={`tag ${BOOKING_TAG[r.booking_status] ?? "tag--mute"}`}>
                            {r.booking_status}
                          </span>
                          <select
                            className="input"
                            style={{ maxWidth: "12rem" }}
                            value={r.attendance_status}
                            onChange={(e) =>
                              markAttendance(rosterSessionId, r.user_id, e.target.value)
                            }
                          >
                            {ATTENDANCE_STATES.map((state) => (
                              <option key={state} value={state}>
                                {state.replace(/_/g, " ")}
                              </option>
                            ))}
                          </select>
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : null}
          </div>
        ) : null}
      </section>
    </>
  );
}
