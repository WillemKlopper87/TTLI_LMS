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
  requires_credit: boolean;
  meeting_provider: string;
}

interface PriceRow {
  id: string;
  currency: string;
  unit_amount: string;
  tax_behaviour: string;
}

interface CreditProduct {
  id: string;
  name: string;
  is_active: boolean;
  workshop_id: string | null;
  prices: PriceRow[];
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
  const canManageProducts = me.permissions.includes("product:manage");

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

  const [cancelBusy, setCancelBusy] = useState<string | null>(null);
  const [facilitatorsSessionId, setFacilitatorsSessionId] = useState<string | null>(null);
  const [sessionFacilitators, setSessionFacilitators] = useState<Facilitator[] | null>(null);
  const [addCoFacilitatorId, setAddCoFacilitatorId] = useState("");
  const [coFacilitatorBusy, setCoFacilitatorBusy] = useState(false);

  const [requiresCreditBusy, setRequiresCreditBusy] = useState(false);
  const [creditProduct, setCreditProduct] = useState<CreditProduct | null>(null);
  const [creditProductBusy, setCreditProductBusy] = useState(false);
  const [creditPriceAmount, setCreditPriceAmount] = useState("");
  const [creditPriceCurrency, setCreditPriceCurrency] = useState("ZAR");

  const [teamsConfigured, setTeamsConfigured] = useState(false);
  const [zoomConfigured, setZoomConfigured] = useState(false);
  const [meetConfigured, setMeetConfigured] = useState(false);
  const [providerBusy, setProviderBusy] = useState(false);

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
    if (resp.ok) {
      const body = await resp.json();
      setWorkshops(body.items);
      setTeamsConfigured(Boolean(body.teams_configured));
      setZoomConfigured(Boolean(body.zoom_configured));
      setMeetConfigured(Boolean(body.meet_configured));
    }
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
    setCreditProduct(null);
    const resp = await authedFetch(`/api/bff/workshops/${workshopId}/sessions`);
    if (resp.ok) setSessions((await resp.json()).items);
    if (canManageProducts) await loadCreditProduct(workshopId);
  }

  async function loadCreditProduct(workshopId: string) {
    const resp = await authedFetch("/api/bff/catalogue/products");
    if (!resp.ok) return;
    const items: CreditProduct[] = (await resp.json()).items;
    setCreditProduct(items.find((p) => p.workshop_id === workshopId) ?? null);
  }

  async function toggleRequiresCredit(workshop: WorkshopItem) {
    setRequiresCreditBusy(true);
    setError(null);
    const resp = await authedFetch(`/api/bff/workshops/${workshop.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ requires_credit: !workshop.requires_credit }),
    });
    setRequiresCreditBusy(false);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not update this workshop.");
      return;
    }
    await loadWorkshops();
  }

  async function changeMeetingProvider(workshopId: string, provider: string) {
    setProviderBusy(true);
    setError(null);
    const resp = await authedFetch(`/api/bff/workshops/${workshopId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ meeting_provider: provider }),
    });
    setProviderBusy(false);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not update this workshop's meeting provider.");
      return;
    }
    await loadWorkshops();
  }

  async function createCreditProduct(workshop: WorkshopItem) {
    setCreditProductBusy(true);
    setError(null);
    const resp = await authedFetch("/api/bff/catalogue/products", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        slug: `${workshop.title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "")}-credit`,
        name: `${workshop.title} — session credit`,
        workshop_id: workshop.id,
      }),
    });
    setCreditProductBusy(false);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not create the credit product.");
      return;
    }
    await loadCreditProduct(workshop.id);
  }

  async function addCreditPrice() {
    if (!creditProduct || !creditPriceAmount) return;
    setCreditProductBusy(true);
    setError(null);
    const resp = await authedFetch(`/api/bff/catalogue/products/${creditProduct.id}/prices`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ currency: creditPriceCurrency, unit_amount: creditPriceAmount }),
    });
    setCreditProductBusy(false);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not add that price.");
      return;
    }
    setCreditPriceAmount("");
    if (selectedWorkshopId) await loadCreditProduct(selectedWorkshopId);
  }

  async function setCreditProductActive(isActive: boolean) {
    if (!creditProduct) return;
    setCreditProductBusy(true);
    setError(null);
    const resp = await authedFetch(`/api/bff/catalogue/products/${creditProduct.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_active: isActive }),
    });
    setCreditProductBusy(false);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not update the credit product.");
      return;
    }
    if (selectedWorkshopId) await loadCreditProduct(selectedWorkshopId);
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

  async function cancelSession(sessionId: string) {
    const reason = window.prompt("Why is this session being cancelled?");
    if (reason === null) return;
    setCancelBusy(sessionId);
    setError(null);
    const resp = await authedFetch(`/api/bff/sessions/${sessionId}/cancel`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: reason.trim() || "No reason given." }),
    });
    setCancelBusy(null);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not cancel that session.");
      return;
    }
    if (selectedWorkshopId) await selectWorkshop(selectedWorkshopId);
  }

  async function viewSessionFacilitators(sessionId: string) {
    if (facilitatorsSessionId === sessionId) {
      setFacilitatorsSessionId(null);
      setSessionFacilitators(null);
      return;
    }
    setFacilitatorsSessionId(sessionId);
    setSessionFacilitators(null);
    const resp = await authedFetch(`/api/bff/sessions/${sessionId}/facilitators`);
    if (resp.ok) setSessionFacilitators((await resp.json()).items);
  }

  async function addCoFacilitator(sessionId: string) {
    if (!addCoFacilitatorId) return;
    setCoFacilitatorBusy(true);
    setError(null);
    const resp = await authedFetch(`/api/bff/sessions/${sessionId}/facilitators`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ facilitator_id: addCoFacilitatorId }),
    });
    setCoFacilitatorBusy(false);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not add that facilitator.");
      return;
    }
    setAddCoFacilitatorId("");
    setSessionFacilitators((await resp.json()).items);
  }

  async function removeCoFacilitator(sessionId: string, facilitatorId: string) {
    setError(null);
    const resp = await authedFetch(
      `/api/bff/sessions/${sessionId}/facilitators/${facilitatorId}`,
      { method: "DELETE" },
    );
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not remove that facilitator.");
      return;
    }
    setSessionFacilitators((await resp.json()).items);
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
            {(() => {
              const selectedWorkshop = workshops.find((w) => w.id === selectedWorkshopId);
              if (!selectedWorkshop || (!canManage && !canManageProducts)) return null;
              return (
                <div className="card p-4">
                  <b style={{ fontSize: "0.8125rem" }}>Booking</b>
                  {canManage ? (
                    <label
                      className="mt-2 flex items-center gap-2"
                      style={{ fontSize: "0.8125rem" }}
                    >
                      <input
                        type="checkbox"
                        checked={selectedWorkshop.requires_credit}
                        disabled={requiresCreditBusy}
                        onChange={() => void toggleRequiresCredit(selectedWorkshop)}
                      />
                      Requires a credit to book
                    </label>
                  ) : null}

                  {canManage ? (
                    <div className="mt-3">
                      <label className="field" style={{ maxWidth: "12rem" }}>
                        <span style={{ fontSize: "0.8125rem" }}>Meeting provider</span>
                        <select
                          className="input"
                          value={selectedWorkshop.meeting_provider}
                          disabled={providerBusy}
                          onChange={(e) =>
                            void changeMeetingProvider(selectedWorkshop.id, e.target.value)
                          }
                        >
                          <option value="manual">Manual (facilitator supplies a link)</option>
                          <option value="teams">Microsoft Teams</option>
                          <option value="zoom">Zoom</option>
                          <option value="meet">Google Meet</option>
                        </select>
                      </label>
                      {selectedWorkshop.meeting_provider === "teams" && !teamsConfigured ? (
                        <p
                          role="alert"
                          className="mt-1"
                          style={{ fontSize: "0.75rem", color: "var(--stop)" }}
                        >
                          Microsoft Teams is not configured on this platform — bookings on this
                          workshop will fail until an admin sets the GRAPH_* settings. Use Manual
                          until then.
                        </p>
                      ) : null}
                      {selectedWorkshop.meeting_provider === "zoom" && !zoomConfigured ? (
                        <p
                          role="alert"
                          className="mt-1"
                          style={{ fontSize: "0.75rem", color: "var(--stop)" }}
                        >
                          Zoom is not configured on this platform — bookings on this workshop
                          will fail until an admin sets the ZOOM_* settings. Use Manual until
                          then.
                        </p>
                      ) : null}
                      {selectedWorkshop.meeting_provider === "meet" && !meetConfigured ? (
                        <p
                          role="alert"
                          className="mt-1"
                          style={{ fontSize: "0.75rem", color: "var(--stop)" }}
                        >
                          Google Meet is not configured on this platform — bookings on this
                          workshop will fail until an admin sets the GOOGLE_* settings. Use
                          Manual until then.
                        </p>
                      ) : null}
                    </div>
                  ) : null}

                  {canManageProducts && selectedWorkshop.requires_credit ? (
                    <div className="mt-3 border-t pt-3" style={{ borderColor: "var(--rule)" }}>
                      <b style={{ fontSize: "0.8125rem" }}>Sell credits</b>
                      {creditProduct === null ? (
                        <>
                          <p
                            className="mt-1"
                            style={{ fontSize: "0.8125rem", color: "var(--muted)" }}
                          >
                            No credit product yet — learners cannot buy a seat until one exists.
                          </p>
                          <button
                            type="button"
                            className="btn btn--primary mt-2"
                            disabled={creditProductBusy}
                            onClick={() => void createCreditProduct(selectedWorkshop)}
                          >
                            Create credit product
                          </button>
                        </>
                      ) : (
                        <>
                          <p
                            className="mt-1 flex items-center gap-2"
                            style={{ fontSize: "0.8125rem" }}
                          >
                            <span>{creditProduct.name}</span>
                            <span
                              className={`tag ${creditProduct.is_active ? "tag--done" : "tag--mute"}`}
                            >
                              {creditProduct.is_active ? "on sale" : "inactive"}
                            </span>
                          </p>
                          <ul className="mt-2 flex flex-col gap-1">
                            {creditProduct.prices.map((p) => (
                              <li key={p.id} style={{ fontSize: "0.8125rem" }}>
                                {p.currency} {p.unit_amount}
                              </li>
                            ))}
                            {creditProduct.prices.length === 0 ? (
                              <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>
                                No price yet.
                              </p>
                            ) : null}
                          </ul>
                          <div className="mt-2 flex items-end gap-2">
                            <label className="field">
                              <span>Currency</span>
                              <input
                                className="input"
                                style={{ width: "5rem" }}
                                value={creditPriceCurrency}
                                onChange={(e) =>
                                  setCreditPriceCurrency(e.target.value.toUpperCase())
                                }
                                maxLength={3}
                              />
                            </label>
                            <label className="field">
                              <span>Amount</span>
                              <input
                                className="input"
                                value={creditPriceAmount}
                                onChange={(e) => setCreditPriceAmount(e.target.value)}
                                placeholder="e.g. 500.00"
                              />
                            </label>
                            <button
                              type="button"
                              className="btn btn--ghost"
                              disabled={creditProductBusy || !creditPriceAmount}
                              onClick={() => void addCreditPrice()}
                            >
                              Add price
                            </button>
                          </div>
                          <button
                            type="button"
                            className="btn btn--ghost mt-2"
                            disabled={creditProductBusy || creditProduct.prices.length === 0}
                            onClick={() => void setCreditProductActive(!creditProduct.is_active)}
                          >
                            {creditProduct.is_active ? "Take off sale" : "Put on sale"}
                          </button>
                        </>
                      )}
                    </div>
                  ) : null}
                </div>
              );
            })()}

            {canManage ? (
              <div className="card p-4 mt-4">
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
                    <th scope="col"></th>
                    {canManage ? <th scope="col"></th> : null}
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
                      <td>
                        <button
                          type="button"
                          className="btn btn--ghost"
                          onClick={() => viewSessionFacilitators(s.id)}
                        >
                          {facilitatorsSessionId === s.id ? "Hide facilitators" : "Facilitators"}
                        </button>
                      </td>
                      {canManage ? (
                        <td>
                          <button
                            type="button"
                            className="btn btn--ghost"
                            disabled={cancelBusy === s.id || s.status === "cancelled"}
                            onClick={() => cancelSession(s.id)}
                          >
                            Cancel session
                          </button>
                        </td>
                      ) : null}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {facilitatorsSessionId ? (
              <div className="card mt-3 p-4">
                <b style={{ fontSize: "0.8125rem" }}>Facilitators on this session</b>
                {sessionFacilitators === null ? (
                  <p className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>
                    Loading…
                  </p>
                ) : (
                  <div className="mt-2 flex flex-col gap-2">
                    {sessionFacilitators.map((f) => {
                      const isPrimary =
                        (sessions ?? []).find((s) => s.id === facilitatorsSessionId)
                          ?.facilitator_id === f.id;
                      return (
                        <div
                          key={f.id}
                          className="flex flex-wrap items-center justify-between gap-2"
                        >
                          <span className="mono" style={{ fontSize: "0.8125rem" }}>
                            {f.email} {isPrimary ? <span className="tag tag--mute">primary</span> : null}
                          </span>
                          {canManage && !isPrimary ? (
                            <button
                              type="button"
                              className="btn btn--ghost"
                              onClick={() => removeCoFacilitator(facilitatorsSessionId, f.id)}
                            >
                              Remove
                            </button>
                          ) : null}
                        </div>
                      );
                    })}
                  </div>
                )}
                {canManage ? (
                  <div className="mt-3 flex flex-wrap items-end gap-2">
                    <label className="field">
                      <b>Add a co-facilitator</b>
                      <select
                        className="input"
                        value={addCoFacilitatorId}
                        onChange={(e) => setAddCoFacilitatorId(e.target.value)}
                      >
                        <option value="">Choose…</option>
                        {facilitators
                          .filter((f) => !(sessionFacilitators ?? []).some((sf) => sf.id === f.id))
                          .map((f) => (
                            <option key={f.id} value={f.id}>
                              {f.email}
                            </option>
                          ))}
                      </select>
                    </label>
                    <button
                      type="button"
                      className="btn btn--primary"
                      disabled={coFacilitatorBusy || !addCoFacilitatorId}
                      onClick={() => addCoFacilitator(facilitatorsSessionId)}
                    >
                      Add
                    </button>
                  </div>
                ) : null}
              </div>
            ) : null}

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
