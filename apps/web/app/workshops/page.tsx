import Link from "next/link";

import { formatDateTime, formatDuration } from "@/lib/format";
import { getPublicCourses, getPublicWorkshops } from "@/lib/server-api";

import { BookButton } from "./book-button";

/**
 * Live workshops (design doc §5 item 13). This nav item used to point at
 * `/catalogue#workshops` — an anchor that does not exist — so it landed
 * on the unfiltered catalogue and looked identical to "Courses".
 *
 * It is now a product page for the facilitated offering, with the real
 * upcoming sessions underneath it and a booking action that calls the
 * booking API that has existed since Phase 5 but had no learner UI.
 */
export const metadata = {
  title: "Live workshops",
};

const SESSION_TYPE_LABEL: Record<string, string> = {
  group: "Group cohort",
  one_on_one: "One-on-one",
};

export default async function WorkshopsPage() {
  const [{ sessions, oneOnOneWorkshops }, courses] = await Promise.all([
    getPublicWorkshops().catch(() => ({ sessions: [], oneOnOneWorkshops: [] })),
    getPublicCourses().catch(() => []),
  ]);
  const withWorkshop = courses.filter((c) => c.includes_workshop);

  return (
    <main>
      <div className="pad-lg">
        <div className="hero">
          <div>
            <p className="eyebrow">Live workshops</p>
            <h1>The part that doesn&rsquo;t work on your own.</h1>
            <p className="sub">
              A facilitated session with a real cohort, where you practise the conversation you
              have been avoiding rather than watch someone describe it. Included with the blended
              programmes, and bookable on its own.
            </p>
            <div className="hero-cta">
              <a className="btn btn--primary btn--lg" href="#upcoming">
                See upcoming sessions
              </a>
              <Link className="btn btn--ghost btn--lg" href="/catalogue?format=blended">
                Programmes that include one
              </Link>
            </div>
            <div className="hero-trust">
              <div>
                <strong>{sessions.length}</strong>
                <span>Sessions scheduled</span>
              </div>
              <div>
                <strong>{withWorkshop.length}</strong>
                <span>Programmes include a seat</span>
              </div>
              <div>
                <strong>90m</strong>
                <span>Typical session</span>
              </div>
            </div>
          </div>

          <div className="hero-card">
            <p className="eyebrow">How a session runs</p>
            <ul className="buybox-list">
              <li>
                <b>✓</b>
                <span>A facilitator who has led the programme, not a presenter</span>
              </li>
              <li>
                <b>✓</b>
                <span>Capped cohort, so everyone speaks</span>
              </li>
              <li>
                <b>✓</b>
                <span>Attendance recorded and counted toward completion</span>
              </li>
              <li>
                <b>✓</b>
                <span>Waitlist that promotes automatically when a seat frees</span>
              </li>
            </ul>
          </div>
        </div>
      </div>

      <div className="band">
        <div className="pad">
          <div className="cols-3">
            <div className="cell">
              <h3>Practise, not watch</h3>
              <p>
                The session is built around the situations delegates bring. Nobody sits through a
                recap of the material they already completed.
              </p>
            </div>
            <div className="cell">
              <h3>It counts</h3>
              <p>
                Attendance is recorded by the facilitator and feeds the same completion engine as
                watch time and assessments — a programme that requires attendance is not complete
                without it.
              </p>
            </div>
            <div className="cell">
              <h3>Held to a size</h3>
              <p>
                Sessions are capped. When one fills, the waitlist promotes the next person
                automatically if someone cancels, rather than quietly overbooking the room.
              </p>
            </div>
          </div>
        </div>
      </div>

      <div className="pad-lg" id="upcoming">
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "baseline",
            gap: "1rem",
            flexWrap: "wrap",
            marginBottom: "1.1rem",
          }}
        >
          <h2 className="serif" style={{ fontSize: "1.5rem" }}>
            Upcoming sessions
          </h2>
          {sessions.length > 0 ? (
            <span style={{ fontSize: ".8125rem", color: "var(--muted)" }}>
              Times shown in your own timezone
            </span>
          ) : null}
        </div>

        {sessions.length === 0 ? (
          <div className="callout">
            <b>No sessions scheduled just yet</b>
            Live workshops are scheduled per cohort. Enrol on a blended programme and your seat is
            included, or <Link href="/contact">ask us when the next cohort runs</Link>.
          </div>
        ) : (
          <div className="rowlist">
            {sessions.map((s) => (
              <div className="rowitem" key={s.session_id}>
                <span className={s.is_full ? "tag tag--stop" : "tag tag--live"}>
                  {s.is_full ? "Waitlist" : "Open"}
                </span>
                <span className="t">
                  {s.title}
                  {s.facilitator_name ? (
                    <span
                      style={{ display: "block", fontWeight: 400, color: "var(--muted)" }}
                    >
                      with {s.facilitator_name}
                    </span>
                  ) : null}
                </span>
                <span className="m">
                  {formatDateTime(s.starts_at)}
                  {formatDuration(s.duration_minutes)
                    ? ` · ${formatDuration(s.duration_minutes)}`
                    : ""}
                  {" · "}
                  {SESSION_TYPE_LABEL[s.session_type] ?? s.session_type}
                </span>
                <BookButton
                  sessionId={s.session_id}
                  isFull={s.is_full}
                  seatsLeft={s.seats_left}
                />
              </div>
            ))}
          </div>
        )}

        {withWorkshop.length > 0 ? (
          <div className="callout" style={{ marginTop: "1.5rem" }}>
            <b>A seat is included with these programmes</b>
            {withWorkshop.map((c, i) => (
              <span key={c.id}>
                {i > 0 ? ", " : ""}
                <Link href={`/courses/${c.id}`}>{c.title}</Link>
              </span>
            ))}
          </div>
        ) : null}
      </div>

      {oneOnOneWorkshops.length > 0 ? (
        <div className="pad-lg" id="coaching">
          <h2 className="serif" style={{ fontSize: "1.5rem", marginBottom: "1.1rem" }}>
            One-on-one coaching
          </h2>
          <div className="cols-3">
            {oneOnOneWorkshops.map((w) => (
              <div className="cell" key={w.id}>
                <h3>{w.title}</h3>
                <p>
                  {w.description ?? "A private coaching session, booked at a time that suits you."}
                </p>
                <p style={{ fontSize: ".8125rem", color: "var(--muted)", marginTop: ".5rem" }}>
                  {formatDuration(w.default_duration_minutes)}
                </p>
                <Link
                  className="btn btn--primary mt-3"
                  href={`/workshops/${w.id}/book`}
                  style={{ display: "inline-block" }}
                >
                  Pick a time
                </Link>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </main>
  );
}
