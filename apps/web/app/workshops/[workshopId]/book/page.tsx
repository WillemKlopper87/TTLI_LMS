"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { formatDate } from "@/lib/format";
import { useRequireAuth } from "@/lib/session-context";

interface Workshop {
  id: string;
  title: string;
  description: string | null;
  session_type: string;
  default_duration_minutes: number;
}

interface Facilitator {
  id: string;
  display_name: string;
  bio: string | null;
  timezone: string;
}

interface OpenSlot {
  starts_at: string;
  ends_at: string;
}

interface BookingConfirmation {
  id: string;
  status: "registered" | "waitlisted";
  join_url: string | null;
}

const OPEN_SLOT_RANGE_DAYS = 14;

function toDateParam(d: Date): string {
  return d.toISOString().slice(0, 10);
}

/**
 * Calendly-style self-service booking for a `one_on_one` workshop
 * (P13): pick a facilitator, pick one of their real open slots
 * (`FacilitatorAvailability` minus what they're already booked for),
 * confirm. Every other session type still goes through the admin-
 * scheduled RSVP model on `/workshops` — this page only makes sense
 * for `session_type === "one_on_one"`, checked below before anything
 * renders a picker.
 */
export default function BookOneOnOnePage() {
  const { workshopId } = useParams<{ workshopId: string }>();
  const { accessToken, ready } = useRequireAuth();

  const [workshop, setWorkshop] = useState<Workshop | null | undefined>(undefined);
  const [facilitators, setFacilitators] = useState<Facilitator[] | null>(null);
  const [selectedFacilitatorId, setSelectedFacilitatorId] = useState("");
  const [slots, setSlots] = useState<OpenSlot[] | null>(null);
  const [slotsLoading, setSlotsLoading] = useState(false);
  const [booking, setBooking] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<BookingConfirmation | null>(null);
  const [error, setError] = useState<string | null>(null);

  const authedFetch = useCallback(
    (path: string, init: RequestInit = {}) => {
      if (!accessToken) throw new Error("An authenticated session is required.");
      return fetch(path, {
        ...init,
        headers: { ...init.headers, Authorization: `Bearer ${accessToken}` },
      });
    },
    [accessToken],
  );

  useEffect(() => {
    if (!ready || !workshopId) return;
    (async () => {
      const [workshopsResp, facilitatorsResp] = await Promise.all([
        authedFetch("/api/bff/workshops"),
        authedFetch(`/api/bff/workshops/${workshopId}/coaches`),
      ]);
      if (workshopsResp.ok) {
        const found = (await workshopsResp.json()).items.find(
          (w: Workshop) => w.id === workshopId,
        );
        setWorkshop(found ?? null);
      } else {
        setWorkshop(null);
      }
      setFacilitators(facilitatorsResp.ok ? (await facilitatorsResp.json()).items : []);
    })();
  }, [ready, workshopId, authedFetch]);

  const loadSlots = useCallback(
    async (facilitatorId: string) => {
      setSlotsLoading(true);
      setError(null);
      const from = new Date();
      const to = new Date(from.getTime() + OPEN_SLOT_RANGE_DAYS * 24 * 60 * 60 * 1000);
      const params = new URLSearchParams({
        facilitator_id: facilitatorId,
        from_date: toDateParam(from),
        to_date: toDateParam(to),
      });
      const resp = await authedFetch(
        `/api/bff/workshops/${workshopId}/open-slots?${params.toString()}`,
      );
      setSlotsLoading(false);
      if (!resp.ok) {
        setError("This facilitator's availability could not be loaded.");
        setSlots(null);
        return;
      }
      setSlots((await resp.json()).items);
    },
    [workshopId, authedFetch],
  );

  function selectFacilitator(facilitatorId: string) {
    setSelectedFacilitatorId(facilitatorId);
    setSlots(null);
    if (facilitatorId) void loadSlots(facilitatorId);
  }

  async function bookSlot(startsAt: string) {
    setBooking(startsAt);
    setError(null);
    const resp = await authedFetch(`/api/bff/workshops/${workshopId}/book-slot`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ facilitator_id: selectedFacilitatorId, starts_at: startsAt }),
    });
    setBooking(null);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(
        body?.error?.message ?? "That slot was just taken — please pick another.",
      );
      void loadSlots(selectedFacilitatorId);
      return;
    }
    setConfirmation(await resp.json());
  }

  if (!ready || workshop === undefined) {
    return (
      <main className="pad-lg">
        <p style={{ color: "var(--muted)" }}>Loading…</p>
      </main>
    );
  }

  if (workshop === null) {
    return (
      <main className="pad-lg">
        <p className="callout callout--stop">This coaching workshop could not be found.</p>
        <p className="mt-3">
          <Link href="/workshops">← Back to workshops</Link>
        </p>
      </main>
    );
  }

  if (workshop.session_type !== "one_on_one") {
    return (
      <main className="pad-lg">
        <p className="callout callout--stop">
          This workshop doesn&rsquo;t use self-service booking — see it on the workshops page
          instead.
        </p>
        <p className="mt-3">
          <Link href="/workshops">← Back to workshops</Link>
        </p>
      </main>
    );
  }

  if (confirmation) {
    return (
      <main className="pad-lg">
        <div style={{ maxWidth: "32rem" }}>
          <p className="eyebrow">Booked</p>
          <h1 className="serif" style={{ fontSize: "1.5rem", margin: ".4rem 0 1rem" }}>
            {confirmation.status === "waitlisted" ? "You're on the waitlist" : "You're booked"}
          </h1>
          <p style={{ color: "var(--muted)" }}>
            {workshop.title} with{" "}
            {facilitators?.find((f) => f.id === selectedFacilitatorId)?.display_name ??
              "your coach"}.
          </p>
          {confirmation.join_url ? (
            <p className="mt-3">
              <a
                className="btn btn--primary"
                href={confirmation.join_url}
                target="_blank"
                rel="noopener noreferrer"
              >
                Join link
              </a>
            </p>
          ) : null}
          <p className="mt-3">
            <Link className="btn btn--ghost" href="/learn/sessions">
              View in my sessions
            </Link>
          </p>
        </div>
      </main>
    );
  }

  const slotsByDay = new Map<string, OpenSlot[]>();
  for (const slot of slots ?? []) {
    const day = slot.starts_at.slice(0, 10);
    const list = slotsByDay.get(day) ?? [];
    list.push(slot);
    slotsByDay.set(day, list);
  }

  return (
    <main className="pad-lg">
      <div style={{ maxWidth: "40rem" }}>
        <p className="eyebrow">One-on-one coaching</p>
        <h1 className="serif" style={{ fontSize: "1.5rem", margin: ".4rem 0 .5rem" }}>
          {workshop.title}
        </h1>
        {workshop.description ? (
          <p style={{ color: "var(--muted)" }}>{workshop.description}</p>
        ) : null}

        {error ? (
          <p role="alert" className="mt-3" style={{ fontSize: "0.8125rem", color: "var(--stop)" }}>
            {error}
          </p>
        ) : null}

        <label className="field mt-4">
          <b>Choose a coach</b>
          <select
            className="input"
            value={selectedFacilitatorId}
            onChange={(e) => selectFacilitator(e.target.value)}
          >
            <option value="">Select…</option>
            {(facilitators ?? []).map((f) => (
              <option key={f.id} value={f.id}>
                {f.display_name}
                {f.bio ? ` — ${f.bio}` : ""}
              </option>
            ))}
          </select>
        </label>

        {selectedFacilitatorId ? (
          <div className="mt-4">
            <b style={{ fontSize: "0.875rem" }}>Pick a time</b>
            {slotsLoading ? (
              <p className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>
                Loading open times…
              </p>
            ) : !slots || slots.length === 0 ? (
              <p className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>
                No open times in the next {OPEN_SLOT_RANGE_DAYS} days for this coach.
              </p>
            ) : (
              <div className="mt-2" style={{ display: "grid", gap: "1rem" }}>
                {[...slotsByDay.entries()].map(([day, daySlots]) => (
                  <div key={day}>
                    <p style={{ fontSize: "0.75rem", color: "var(--muted)", marginBottom: ".35rem" }}>
                      {formatDate(day)}
                    </p>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: ".5rem" }}>
                      {daySlots.map((slot) => (
                        <button
                          key={slot.starts_at}
                          type="button"
                          className="btn btn--ghost"
                          disabled={booking === slot.starts_at}
                          onClick={() => bookSlot(slot.starts_at)}
                        >
                          {new Date(slot.starts_at).toLocaleTimeString("en-ZA", {
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : null}

        <p className="mt-4">
          <Link href="/workshops">← Back to workshops</Link>
        </p>
      </div>
    </main>
  );
}
