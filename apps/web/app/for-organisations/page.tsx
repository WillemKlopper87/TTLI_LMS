import Link from "next/link";

import { getPublicCourses } from "@/lib/server-api";

/**
 * The corporate pitch (design doc §5 item 17). This used to be
 * `/organisations`, which calls `useRequireAuth()` — so a prospective
 * buyer clicking "For Organisations" was bounced to a login screen
 * before reading a word. The management screens stay behind auth at
 * /organisations; this is the page that sells.
 *
 * Every claim below is something the platform actually does, and links
 * to where it does it. Nothing here is aspirational copy.
 */
export const metadata = {
  title: "For organisations",
};

const STEPS = [
  {
    n: "1",
    title: "Buy a seat pool",
    body: "Pay by card, EFT or purchase order. A pro-forma invoice is issued immediately for PO orders; the tax invoice follows on approval, sequentially numbered.",
  },
  {
    n: "2",
    title: "Invite your people",
    body: "Invite by email one at a time, or import a CSV. Seats are a pool — revoke someone who leaves and reassign the seat to their replacement.",
  },
  {
    n: "3",
    title: "Watch progress, not scores",
    body: "Managers see who has completed the work. Individual assessment results stay private unless an administrator opens them for a specific course.",
  },
];

export default async function ForOrganisationsPage() {
  const courses = await getPublicCourses().catch(() => []);
  const workshopCount = courses.filter((c) => c.includes_workshop).length;

  return (
    <main>
      <div className="pad-lg">
        <div className="hero">
          <div>
            <p className="eyebrow">For organisations</p>
            <h1>Training your people can finish — and you can prove they did.</h1>
            <p className="sub">
              Seat bundles from five learners, invoiced the way your finance team already works,
              with a completion report that means something because the server decided it, not the
              learner.
            </p>
            <div className="hero-cta">
              <Link className="btn btn--primary btn--lg" href="/organisations">
                Set up an organisation
              </Link>
              <Link className="btn btn--ghost btn--lg" href="/contact">
                Talk to us first
              </Link>
            </div>
            <div className="hero-trust">
              <div>
                <strong>5+</strong>
                <span>Seats per bundle</span>
              </div>
              <div>
                <strong>{courses.length}</strong>
                <span>Programmes available</span>
              </div>
              <div>
                <strong>{workshopCount}</strong>
                <span>With a live workshop</span>
              </div>
            </div>
          </div>

          <div className="hero-card">
            <p className="eyebrow">Already set up?</p>
            <h2 className="serif" style={{ fontSize: "1.1875rem" }}>
              Sign in to your workspace
            </h2>
            <p style={{ fontSize: ".8125rem", color: "var(--muted)" }}>
              White-label organisations sign in at their own address, with their own branding and
              catalogue.
            </p>
            <Link className="btn btn--ghost btn--block" href="/login">
              Organisation sign-in
            </Link>
          </div>
        </div>
      </div>

      <div className="band">
        <div className="pad">
          <div className="cols-3">
            {STEPS.map((step) => (
              <div className="cell" key={step.n}>
                <p className="eyebrow">Step {step.n}</p>
                <h3>{step.title}</h3>
                <p>{step.body}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="pad-lg">
        <div className="detail">
          <div style={{ display: "grid", gap: "1.75rem" }}>
            <div>
              <h2 className="serif" style={{ fontSize: "1.5rem", marginBottom: ".5rem" }}>
                What your managers see
              </h2>
              <ul className="outcomes">
                <li>
                  <b>✓</b>
                  <span>
                    Who is enrolled, how far they have got, and who has stalled — as participation,
                    not as marks
                  </span>
                </li>
                <li>
                  <b>✓</b>
                  <span>
                    Assessment scores stay hidden unless an administrator opens them for a
                    particular course, with a documented reason
                  </span>
                </li>
                <li>
                  <b>✓</b>
                  <span>
                    A completion report that reflects enforced watch time, assessment scores and
                    attendance — not clicking Next
                  </span>
                </li>
                <li>
                  <b>✓</b>
                  <span>
                    Every certificate publicly verifiable, and revocable if it needs to be
                  </span>
                </li>
              </ul>
            </div>

            <div>
              <h2 className="serif" style={{ fontSize: "1.5rem", marginBottom: ".5rem" }}>
                How the money works
              </h2>
              <div className="rowlist">
                <div className="rowitem">
                  <span className="tag tag--mute">Card</span>
                  <span className="t">Immediate access once the gateway confirms</span>
                </div>
                <div className="rowitem">
                  <span className="tag tag--mute">EFT</span>
                  <span className="t">
                    Access opens when finance confirms the payment, not when proof is uploaded
                  </span>
                </div>
                <div className="rowitem">
                  <span className="tag tag--mute">Purchase order</span>
                  <span className="t">
                    Pro-forma immediately, tax invoice on approval, seats locked until then
                  </span>
                </div>
              </div>
              <p style={{ fontSize: ".75rem", color: "var(--muted)", marginTop: ".6rem" }}>
                Invoices are sequentially numbered with no gaps, and refunds issue credit notes on
                their own series.
              </p>
            </div>
          </div>

          <div style={{ display: "grid", gap: "1rem" }}>
            <div className="buybox">
              <div className="buybox-price">
                <div className="amt">Seat bundles</div>
                <div className="vat">From five learners · priced per programme</div>
              </div>
              <div className="buybox-body">
                <Link className="btn btn--primary btn--lg btn--block" href="/organisations">
                  Set up an organisation
                </Link>
                <Link className="btn btn--ghost btn--block" href="/catalogue">
                  Browse the catalogue
                </Link>
                <ul className="buybox-list">
                  <li>
                    <b>✓</b>
                    <span>Manager dashboard with aggregate progress</span>
                  </li>
                  <li>
                    <b>✓</b>
                    <span>Bulk invite and CSV import</span>
                  </li>
                  <li>
                    <b>✓</b>
                    <span>Revoke and reassign seats as people move</span>
                  </li>
                  <li>
                    <b>✓</b>
                    <span>Invoice, EFT and purchase-order payment</span>
                  </li>
                </ul>
              </div>
            </div>

            <div className="callout">
              <b>White-label is available</b>
              Your own subdomain, your own branding and your own catalogue. Ask us about it when
              you set the account up.
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
