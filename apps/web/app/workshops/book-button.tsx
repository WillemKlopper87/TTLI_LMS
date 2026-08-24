"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { authedDownload } from "@/lib/authed-download";
import { getAccessToken } from "@/lib/session";
import { useSession } from "@/lib/session-context";

/**
 * The learner-facing booking action (REQ-WS-*). The API has had
 * `POST /sessions/{id}/book` since Phase 5 — capacity, waitlist
 * promotion and the meeting link are all server-side — but nothing
 * outside the admin screens ever called it.
 *
 * A full session still books: the server puts the learner on the
 * waitlist and promotes them if someone cancels, so the button says
 * "Join the waitlist" rather than going dead.
 */
export function BookButton({
  sessionId,
  isFull,
  seatsLeft,
}: {
  sessionId: string;
  isFull: boolean;
  seatsLeft: number;
}) {
  const router = useRouter();
  const { status } = useSession();
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{
    bookingId: string;
    status: string;
    joinUrl: string | null;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function book() {
    if (status !== "authenticated") {
      // Come back here after signing in rather than dumping them on /learn.
      router.push(`/login?next=${encodeURIComponent("/workshops")}`);
      return;
    }
    setBusy(true);
    setError(null);
    const resp = await fetch(`/api/bff/sessions/${sessionId}/book`, {
      method: "POST",
      headers: { Authorization: `Bearer ${getAccessToken()}` },
    });
    setBusy(false);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "That booking could not be completed.");
      return;
    }
    const booking = await resp.json();
    setResult({ bookingId: booking.id, status: booking.status, joinUrl: booking.join_url ?? null });
    router.refresh();
  }

  async function downloadCalendar() {
    if (!result) return;
    const ok = await authedDownload(
      `/api/bff/bookings/${result.bookingId}/calendar.ics`,
      "session.ics",
    );
    if (!ok) setError("The calendar invite could not be downloaded.");
  }

  if (result) {
    const waitlisted = result.status === "waitlisted";
    return (
      <div style={{ display: "grid", gap: ".4rem", justifyItems: "start" }}>
        <span className={waitlisted ? "tag tag--live" : "tag tag--done"}>
          {waitlisted ? "On the waitlist" : "Booked"}
        </span>
        {waitlisted ? (
          <span style={{ fontSize: ".75rem", color: "var(--muted)" }}>
            We will move you up automatically if a seat frees.
          </span>
        ) : result.joinUrl ? (
          <a
            className="btn btn--ghost"
            href={result.joinUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            Join link
          </a>
        ) : (
          <span style={{ fontSize: ".75rem", color: "var(--muted)" }}>
            The joining details are in your dashboard.
          </span>
        )}
        <button type="button" className="btn btn--ghost" onClick={downloadCalendar}>
          Add to calendar
        </button>
        {error ? (
          <span role="alert" style={{ fontSize: ".75rem", color: "var(--stop)" }}>
            {error}
          </span>
        ) : null}
      </div>
    );
  }

  return (
    <div style={{ display: "grid", gap: ".35rem", justifyItems: "start" }}>
      <button type="button" className="btn btn--primary" disabled={busy} onClick={book}>
        {busy ? "Booking…" : isFull ? "Join the waitlist" : "Book a seat"}
      </button>
      {!isFull && seatsLeft <= 3 ? (
        <span style={{ fontSize: ".75rem", color: "var(--live)" }}>
          {seatsLeft} {seatsLeft === 1 ? "seat" : "seats"} left
        </span>
      ) : null}
      {error ? (
        <span role="alert" style={{ fontSize: ".75rem", color: "var(--stop)" }}>
          {error}
        </span>
      ) : null}
    </div>
  );
}
