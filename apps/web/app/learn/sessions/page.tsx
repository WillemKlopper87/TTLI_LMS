"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { authedDownload } from "@/lib/authed-download";
import { formatDateTime } from "@/lib/format";
import { getAccessToken } from "@/lib/session";
import { useRequireAuth } from "@/lib/session-context";

interface OwnBooking {
  booking_id: string;
  session_id: string;
  workshop_id: string;
  workshop_title: string;
  facilitator_names: string[];
  starts_at: string;
  ends_at: string;
  status: "registered" | "waitlisted" | "cancelled";
  session_status: "scheduled" | "cancelled" | "completed";
  join_url: string | null;
  provider: string | null;
  can_manage: boolean;
}

interface OtherSession {
  id: string;
  starts_at: string;
  ends_at: string;
  status: string;
  registered: number;
  capacity: number;
}

const PROVIDER_LABEL: Record<string, string> = {
  teams: "Join on Teams",
  zoom: "Join on Zoom",
  meet: "Join on Meet",
  manual: "Join session",
};

const STATUS_TAG: Record<string, string> = {
  registered: "tag--done",
  waitlisted: "tag--live",
  cancelled: "tag--mute",
};

/**
 * The learner's own bookings, past and future (P7 phase 2) — the "my
 * sessions" page the backlog asks for. `/learn`'s "Coming up" rowlist
 * stays as it is (a quick glance across workshops + assessments); this
 * page is where cancel/reschedule actually happen, which that
 * read-only rowlist never offered.
 */
export default function LearnSessionsPage() {
  const { ready } = useRequireAuth();
  const [bookings, setBookings] = useState<OwnBooking[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const [rescheduling, setRescheduling] = useState<OwnBooking | null>(null);
  const [otherSessions, setOtherSessions] = useState<OtherSession[] | null>(null);
  const [targetSessionId, setTargetSessionId] = useState("");

  const load = useCallback(async () => {
    const token = getAccessToken();
    if (!token) return;
    const resp = await fetch("/api/bff/bookings", { headers: { Authorization: `Bearer ${token}` } });
    if (!resp.ok) {
      setError("Your sessions could not be loaded.");
      return;
    }
    setBookings((await resp.json()).items);
  }, []);

  useEffect(() => {
    if (!ready) return;
    void load();
  }, [ready, load]);

  async function cancelBooking(bookingId: string) {
    setBusy(bookingId);
    setError(null);
    const token = getAccessToken();
    const resp = await fetch(`/api/bff/bookings/${bookingId}/cancel`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
    setBusy(null);
    if (!resp.ok) {
      setError("That booking could not be cancelled.");
      return;
    }
    await load();
  }

  async function downloadCalendar(bookingId: string) {
    setError(null);
    const ok = await authedDownload(
      `/api/bff/bookings/${bookingId}/calendar.ics`,
      "session.ics",
    );
    if (!ok) setError("The calendar invite could not be downloaded.");
  }

  async function openReschedule(booking: OwnBooking) {
    setRescheduling(booking);
    setOtherSessions(null);
    setTargetSessionId("");
    const token = getAccessToken();
    const resp = await fetch(`/api/bff/workshops/${booking.workshop_id}/sessions`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!resp.ok) return;
    const items: OtherSession[] = (await resp.json()).items;
    setOtherSessions(
      items.filter((s) => s.id !== booking.session_id && s.status === "scheduled"),
    );
  }

  async function confirmReschedule() {
    if (!rescheduling || !targetSessionId) return;
    setBusy(rescheduling.booking_id);
    setError(null);
    const token = getAccessToken();
    const resp = await fetch(`/api/bff/bookings/${rescheduling.booking_id}/reschedule`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ target_session_id: targetSessionId }),
    });
    setBusy(null);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "That session could not be rescheduled.");
      return;
    }
    setRescheduling(null);
    await load();
  }

  if (error) {
    return (
      <main className="pad-lg">
        <p className="callout callout--stop" role="alert">
          {error}
        </p>
      </main>
    );
  }

  if (bookings === null) {
    return (
      <main className="pad-lg">
        <p style={{ color: "var(--muted)" }}>Loading your sessions…</p>
      </main>
    );
  }

  const upcoming = bookings.filter(
    (b) => b.status !== "cancelled" && new Date(b.starts_at) > new Date(),
  );
  const past = bookings.filter(
    (b) => b.status === "cancelled" || new Date(b.starts_at) <= new Date(),
  );

  return (
    <main className="pad-lg">
      <div style={{ display: "grid", gap: "1.5rem", maxWidth: "56rem" }}>
        <div>
          <p className="eyebrow">Workshops</p>
          <h1 className="serif" style={{ fontSize: "1.5rem", margin: "0.35rem 0 0.7rem" }}>
            My sessions
          </h1>
        </div>

        <section>
          <h2 className="serif" style={{ fontSize: "1.125rem", marginBottom: ".7rem" }}>
            Upcoming
          </h2>
          {upcoming.length === 0 ? (
            <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
              Nothing booked yet. <Link href="/workshops">Browse live workshops →</Link>
            </p>
          ) : (
            <div className="rowlist">
              {upcoming.map((b) => (
                <div className="rowitem" key={b.booking_id}>
                  <span className={`tag ${STATUS_TAG[b.status] ?? "tag--mute"}`}>{b.status}</span>
                  <span className="t">{b.workshop_title}</span>
                  <span className="m">
                    {formatDateTime(b.starts_at)}
                    {b.facilitator_names.length > 0 ? ` · ${b.facilitator_names.join(", ")}` : ""}
                  </span>
                  {b.join_url ? (
                    <a
                      className="btn btn--ghost"
                      href={b.join_url}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {PROVIDER_LABEL[b.provider ?? ""] ?? "Join session"}
                    </a>
                  ) : null}
                  {b.status !== "cancelled" ? (
                    <button
                      type="button"
                      className="btn btn--ghost"
                      onClick={() => downloadCalendar(b.booking_id)}
                    >
                      Add to calendar
                    </button>
                  ) : null}
                  {b.can_manage ? (
                    <>
                      <button
                        type="button"
                        className="btn btn--ghost"
                        disabled={busy === b.booking_id}
                        onClick={() => openReschedule(b)}
                      >
                        Reschedule
                      </button>
                      <button
                        type="button"
                        className="btn btn--ghost"
                        disabled={busy === b.booking_id}
                        onClick={() => cancelBooking(b.booking_id)}
                      >
                        Cancel
                      </button>
                    </>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </section>

        {rescheduling ? (
          <div className="card p-4">
            <b style={{ fontSize: "0.875rem" }}>Reschedule &ldquo;{rescheduling.workshop_title}&rdquo;</b>
            {otherSessions === null ? (
              <p className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>
                Loading other sessions…
              </p>
            ) : otherSessions.length === 0 ? (
              <p className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>
                No other scheduled sessions for this workshop yet.
              </p>
            ) : (
              <label className="field mt-2">
                <b>Move to</b>
                <select
                  className="input"
                  value={targetSessionId}
                  onChange={(e) => setTargetSessionId(e.target.value)}
                >
                  <option value="">Choose a session…</option>
                  {otherSessions.map((s) => (
                    <option key={s.id} value={s.id}>
                      {new Date(s.starts_at).toLocaleString()} ({s.registered}/{s.capacity} booked)
                    </option>
                  ))}
                </select>
              </label>
            )}
            <div className="mt-3 flex gap-2">
              <button
                type="button"
                className="btn btn--primary"
                disabled={!targetSessionId || busy === rescheduling.booking_id}
                onClick={confirmReschedule}
              >
                Confirm reschedule
              </button>
              <button
                type="button"
                className="btn btn--quiet"
                onClick={() => setRescheduling(null)}
              >
                Cancel
              </button>
            </div>
          </div>
        ) : null}

        <section>
          <h2 className="serif" style={{ fontSize: "1.125rem", marginBottom: ".7rem" }}>
            Past &amp; cancelled
          </h2>
          {past.length === 0 ? (
            <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>Nothing here yet.</p>
          ) : (
            <div className="rowlist">
              {past.map((b) => (
                <div className="rowitem" key={b.booking_id}>
                  <span className={`tag ${STATUS_TAG[b.status] ?? "tag--mute"}`}>{b.status}</span>
                  <span className="t">{b.workshop_title}</span>
                  <span className="m">{formatDateTime(b.starts_at)}</span>
                </div>
              ))}
            </div>
          )}
        </section>

        <Link className="btn btn--quiet" href="/learn" style={{ justifySelf: "start" }}>
          ← My learning
        </Link>
      </div>
    </main>
  );
}
