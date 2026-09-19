"use client";

/**
 * `/admin/licences/new` — create a licence granting a course or learning
 * path to a licensee organisation. `POST /licences` requires exactly one
 * of course_id/learning_path_id.
 */

import { useState } from "react";
import { useRouter } from "next/navigation";

import { readError, sendJson } from "../../courses/wizard-api";

export default function NewLicencePage() {
  const router = useRouter();
  const [organisationId, setOrganisationId] = useState("");
  const [target, setTarget] = useState<"course" | "learning_path">("course");
  const [courseId, setCourseId] = useState("");
  const [learningPathId, setLearningPathId] = useState("");
  const [seatsPurchased, setSeatsPurchased] = useState("");
  const [startsAt, setStartsAt] = useState("");
  const [endsAt, setEndsAt] = useState("");
  const [pricePerSeatCents, setPricePerSeatCents] = useState("");
  const [currency, setCurrency] = useState("");
  const [royaltyPct, setRoyaltyPct] = useState("");
  const [orderId, setOrderId] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const targetId = target === "course" ? courseId : learningPathId;

  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (!organisationId.trim() || !targetId.trim() || !seatsPurchased || !startsAt || !endsAt) {
      return;
    }
    setBusy(true);
    setError(null);
    const body: Record<string, unknown> = {
      organisation_id: organisationId.trim(),
      seats_purchased: parseInt(seatsPurchased, 10),
      starts_at: startsAt,
      ends_at: endsAt,
      price_per_seat_cents: pricePerSeatCents ? parseInt(pricePerSeatCents, 10) : null,
      currency: currency.trim() || null,
      royalty_pct: royaltyPct ? parseFloat(royaltyPct) : null,
      order_id: orderId.trim() || null,
      notes: notes.trim() || null,
    };
    if (target === "course") {
      body.course_id = courseId.trim();
    } else {
      body.learning_path_id = learningPathId.trim();
    }
    const resp = await sendJson("/api/bff/licences", "POST", body);
    setBusy(false);
    if (!resp.ok) {
      setError(await readError(resp, "The licence could not be created."));
      return;
    }
    router.push("/admin/licences");
  }

  return (
    <div className="dash">
      <div className="dash-top">
        <div>
          <p className="eyebrow">Sales &amp; Licensing</p>
          <h1>New licence</h1>
        </div>
        <a className="btn btn--ghost" href="/admin/licences">
          All licences
        </a>
      </div>

      <form onSubmit={(e) => void create(e)} className="card p-4" style={{ maxWidth: "32rem" }}>
        <label className="field">
          <b>Organisation ID</b>
          <input
            className="input"
            value={organisationId}
            onChange={(e) => setOrganisationId(e.target.value)}
            placeholder="UUID of the licensee organisation"
            required
            autoFocus
          />
        </label>

        <label className="field mt-3">
          <b>Grants</b>
          <select
            className="input"
            value={target}
            onChange={(e) => setTarget(e.target.value as "course" | "learning_path")}
          >
            <option value="course">A course</option>
            <option value="learning_path">A learning path</option>
          </select>
        </label>

        {target === "course" ? (
          <label className="field mt-3">
            <b>Course ID</b>
            <input
              className="input"
              value={courseId}
              onChange={(e) => setCourseId(e.target.value)}
              placeholder="UUID of the course"
              required
            />
          </label>
        ) : (
          <label className="field mt-3">
            <b>Learning path ID</b>
            <input
              className="input"
              value={learningPathId}
              onChange={(e) => setLearningPathId(e.target.value)}
              placeholder="UUID of the learning path"
              required
            />
          </label>
        )}

        <label className="field mt-3">
          <b>Seats purchased</b>
          <input
            className="input"
            type="number"
            min={1}
            value={seatsPurchased}
            onChange={(e) => setSeatsPurchased(e.target.value)}
            required
          />
        </label>

        <label className="field mt-3">
          <b>Starts at</b>
          <input
            className="input"
            type="datetime-local"
            value={startsAt}
            onChange={(e) => setStartsAt(e.target.value)}
            required
          />
        </label>

        <label className="field mt-3">
          <b>Ends at</b>
          <input
            className="input"
            type="datetime-local"
            value={endsAt}
            onChange={(e) => setEndsAt(e.target.value)}
            required
          />
        </label>

        <label className="field mt-3">
          <b>Price per seat (cents)</b>
          <input
            className="input"
            type="number"
            min={0}
            value={pricePerSeatCents}
            onChange={(e) => setPricePerSeatCents(e.target.value)}
            placeholder="Optional"
          />
        </label>

        <label className="field mt-3">
          <b>Currency</b>
          <input
            className="input"
            value={currency}
            onChange={(e) => setCurrency(e.target.value.toUpperCase())}
            placeholder="Optional, e.g. ZAR"
            maxLength={3}
          />
        </label>

        <label className="field mt-3">
          <b>Royalty %</b>
          <input
            className="input"
            type="number"
            step="0.01"
            value={royaltyPct}
            onChange={(e) => setRoyaltyPct(e.target.value)}
            placeholder="Optional"
          />
        </label>

        <label className="field mt-3">
          <b>Order ID</b>
          <input
            className="input"
            value={orderId}
            onChange={(e) => setOrderId(e.target.value)}
            placeholder="Optional — UUID of the related order"
          />
        </label>

        <label className="field mt-3">
          <b>Notes</b>
          <textarea
            className="input"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            placeholder="Optional"
          />
        </label>

        {error ? (
          <p role="alert" style={{ fontSize: "0.8125rem", color: "var(--stop)" }} className="mt-2">
            {error}
          </p>
        ) : null}
        <button
          type="submit"
          className="btn btn--primary mt-3"
          disabled={
            busy || !organisationId.trim() || !targetId.trim() || !seatsPurchased || !startsAt || !endsAt
          }
        >
          {busy ? "Creating…" : "Create licence"}
        </button>
      </form>
    </div>
  );
}
