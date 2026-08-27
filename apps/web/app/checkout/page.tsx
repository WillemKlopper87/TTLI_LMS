"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { authedFetch } from "@/lib/authed-fetch";
import { formatDuration, formatMoney } from "@/lib/format";
import { useRequireAuth } from "@/lib/session-context";

interface OrderResponse {
  id: string;
  status: string;
  currency: string;
  subtotal: string;
  tax_total: string;
  grand_total: string;
  payment_reference: string | null;
}

interface EftCheckoutResponse {
  payment_id: string;
  payment_reference: string;
  bank_name: string;
  account_name: string;
  account_number: string;
  branch_code: string;
  amount: string;
  currency: string;
}

interface CardCheckoutResponse {
  payment_id: string;
  action_url: string;
  fields: Record<string, string>;
}

/** The course this price belongs to — resolved from /public/courses,
 * which carries its own price (ProductSummary has no course link). */
interface PricedCourse {
  id: string;
  title: string;
  module_count: number;
  lesson_count: number;
  estimated_minutes: number;
  includes_workshop: boolean;
  has_certificate: boolean;
  price: {
    price_id: string;
    currency: string;
    unit_amount: string;
    tax_behaviour: string;
    includes_vat: boolean;
  } | null;
}

type Method = "card" | "eft" | "po";
type Step = "details" | "eft" | "redirecting" | "submitted" | "po_submitted";

const VAT_RATE = 0.15;

/**
 * The three purchase paths (REQ-PAY-03), as the prototype's tabbed
 * checkout (design doc §4 screen 6): card via Payfast's hosted page, EFT
 * with a proof upload that finance approves, and purchase order with a
 * pro-forma invoice. All three produce a sequentially numbered tax
 * invoice; none of them opens access before the money is confirmed.
 */
export default function CheckoutPage() {
  useRequireAuth();
  const priceId = useSearchParams().get("price");

  const [method, setMethod] = useState<Method>("card");
  const [customerType, setCustomerType] = useState("individual");
  const [step, setStep] = useState<Step>("details");
  const [order, setOrder] = useState<OrderResponse | null>(null);
  const [eft, setEft] = useState<EftCheckoutResponse | null>(null);
  const [cardCheckout, setCardCheckout] = useState<CardCheckoutResponse | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [poFile, setPoFile] = useState<File | null>(null);
  const [poNumber, setPoNumber] = useState("");
  const [seats, setSeats] = useState("1");
  const [busy, setBusy] = useState<Method | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [course, setCourse] = useState<PricedCourse | null>(null);
  const cardFormRef = useRef<HTMLFormElement>(null);

  // Resolve what is being bought so the summary can show a real line and
  // total before an order exists (the order endpoint is the authority
  // once one does).
  useEffect(() => {
    if (!priceId) return;
    let cancelled = false;
    fetch("/api/bff/public/courses")
      .then((r) => (r.ok ? r.json() : null))
      .then((body: { items: PricedCourse[] } | null) => {
        if (cancelled || !body) return;
        setCourse(body.items.find((c) => c.price?.price_id === priceId) ?? null);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [priceId]);

  async function createOrder(): Promise<OrderResponse | null> {
    if (!priceId) {
      setError("No programme selected — start from the catalogue.");
      return null;
    }
    const quantity = method === "po" ? Math.max(1, Number(seats) || 1) : 1;
    const orderResp = await authedFetch("/api/bff/orders", {
      method: "POST",
      // Idempotency-Key (03 §1.6): a network retry of this exact click
      // must not create a second order. One key per attempt — generated
      // fresh here, not stored across retries, since a genuine second
      // click (not a retry) is a new, distinct purchase attempt.
      headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({
        currency: "ZAR",
        customer_type: customerType,
        lines: [{ price_id: priceId, quantity }],
      }),
    });
    if (!orderResp.ok) {
      const body = await orderResp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not create the order.");
      return null;
    }
    const createdOrder: OrderResponse = await orderResp.json();
    setOrder(createdOrder);
    return createdOrder;
  }

  async function payByCard() {
    setBusy("card");
    setError(null);
    const createdOrder = await createOrder();
    if (!createdOrder) {
      setBusy(null);
      return;
    }
    // No Idempotency-Key here — 03 §1.6 never names this endpoint
    // (core/idempotency.py's SCOPED_ROUTES docstring), because a
    // retried click is just a second hosted-checkout redirect the buyer
    // abandons, not a duplicate charge: Payfast itself, via the ITN
    // webhook, is the sole source of truth for whether money moved.
    const cardResp = await authedFetch(`/api/bff/orders/${createdOrder.id}/checkout/card`, {
      method: "POST",
    });
    if (!cardResp.ok) {
      setBusy(null);
      if (cardResp.status === 503) {
        setError("Card payment isn't switched on for this deployment yet — please use EFT.");
      } else {
        const body = await cardResp.json().catch(() => null);
        setError(body?.error?.message ?? "Could not start card checkout.");
      }
      return;
    }
    setCardCheckout(await cardResp.json());
    setStep("redirecting");
    // Payfast's hosted checkout only accepts a real form POST, not a
    // fetch/redirect — submit once the hidden form below has rendered.
    requestAnimationFrame(() => cardFormRef.current?.submit());
  }

  async function payByEft() {
    setBusy("eft");
    setError(null);
    const createdOrder = await createOrder();
    if (!createdOrder) {
      setBusy(null);
      return;
    }
    const eftResp = await authedFetch(`/api/bff/orders/${createdOrder.id}/checkout/eft`, {
      method: "POST",
    });
    setBusy(null);
    if (!eftResp.ok) {
      setError("Could not start EFT checkout.");
      return;
    }
    setEft(await eftResp.json());
    setStep("eft");
  }

  async function requestProForma() {
    if (!poNumber.trim() || !poFile) {
      setError("A purchase order number and the signed document are both required.");
      return;
    }
    setBusy("po");
    setError(null);
    const createdOrder = await createOrder();
    if (!createdOrder) {
      setBusy(null);
      return;
    }
    const formData = new FormData();
    formData.append("po_number", poNumber.trim());
    formData.append("file", poFile);
    const resp = await authedFetch(`/api/bff/orders/${createdOrder.id}/checkout/po`, {
      method: "POST",
      body: formData,
    });
    setBusy(null);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not request a pro-forma invoice.");
      return;
    }
    setStep("po_submitted");
  }

  async function submitProof() {
    if (!order || !file) return;
    setBusy("eft");
    setError(null);
    const formData = new FormData();
    formData.append("file", file);
    const resp = await authedFetch(`/api/bff/orders/${order.id}/payment-proof`, {
      method: "POST",
      body: formData,
    });
    setBusy(null);
    if (!resp.ok) {
      setError("Could not upload the proof of payment.");
      return;
    }
    setStep("submitted");
  }

  /* ---------- terminal states ---------- */

  if (step === "redirecting" && cardCheckout) {
    return (
      <main className="pad-lg" style={{ textAlign: "center" }}>
        <h1 className="serif" style={{ fontSize: "1.5rem" }}>
          Taking you to secure checkout&hellip;
        </h1>
        <p style={{ fontSize: ".875rem", color: "var(--muted)", marginTop: ".4rem" }}>
          You&rsquo;ll pay on Payfast&rsquo;s own site — this platform never sees your card details.
        </p>
        {/* Hosted-checkout redirect: Payfast requires a real browser form
            POST with these exact fields, not a fetch or 3xx redirect. */}
        <form ref={cardFormRef} method="POST" action={cardCheckout.action_url} hidden>
          {Object.entries(cardCheckout.fields).map(([key, value]) => (
            <input key={key} type="hidden" name={key} value={value} />
          ))}
        </form>
      </main>
    );
  }

  if (step === "submitted" || step === "po_submitted") {
    const isPo = step === "po_submitted";
    return (
      <main className="pad-lg">
        <div style={{ maxWidth: "38rem" }}>
          <h1 className="serif" style={{ fontSize: "1.5rem" }}>
            {isPo ? "Pro-forma invoice requested" : "Submitted for approval"}
          </h1>
          <div className="callout" style={{ marginTop: "1rem" }}>
            <b>{isPo ? "Finance will issue the pro-forma invoice" : "Finance will confirm the payment"}</b>
            {isPo
              ? "The tax invoice follows once the order is approved. Seats stay locked until then."
              : "Access opens once finance confirms the payment — typically within one business day, and not when the proof is uploaded."}
          </div>
          <p style={{ marginTop: "1rem" }}>
            <Link className="btn btn--ghost" href="/learn">
              Go to my learning
            </Link>
          </p>
        </div>
      </main>
    );
  }

  /* ---------- summary ---------- */

  const unit = course?.price ? Number(course.price.unit_amount) : null;
  const qty = method === "po" ? Math.max(1, Number(seats) || 1) : 1;
  const gross = unit !== null ? unit * qty : null;
  const inclusive = course?.price?.includes_vat ?? true;
  const exVat = gross === null ? null : inclusive ? gross / (1 + VAT_RATE) : gross;
  const vat = gross === null || exVat === null ? null : inclusive ? gross - exVat : gross * VAT_RATE;
  const total = gross === null ? null : inclusive ? gross : gross + (vat ?? 0);

  const summary = (
    <div style={{ display: "grid", gap: "1rem" }}>
      <div className="summary">
        <div className="summary-row">
          <span>
            {course?.title ?? "Selected programme"}
            {qty > 1 ? ` × ${qty}` : ""}
          </span>
          <span className="v">{exVat === null ? "—" : formatMoney(exVat)}</span>
        </div>
        <div className="summary-row">
          <span>VAT at 15%</span>
          <span className="v">{vat === null ? "—" : formatMoney(vat)}</span>
        </div>
        <div className="summary-row summary-row--total">
          <span>Total</span>
          <span className="v">{total === null ? "—" : formatMoney(total)}</span>
        </div>
      </div>

      {course ? (
        <div className="aside-card">
          <p className="eyebrow">Included</p>
          <ul className="buybox-list">
            <li>
              <b>✓</b>
              <span>
                {course.module_count} modules, {course.lesson_count} lessons
                {formatDuration(course.estimated_minutes)
                  ? ` · ${formatDuration(course.estimated_minutes)}`
                  : ""}
              </span>
            </li>
            {course.includes_workshop ? (
              <li>
                <b>✓</b>
                <span>One live workshop seat</span>
              </li>
            ) : null}
            {course.has_certificate ? (
              <li>
                <b>✓</b>
                <span>Verifiable certificate and shareable badge</span>
              </li>
            ) : null}
          </ul>
        </div>
      ) : null}

      <p style={{ fontSize: ".6875rem", color: "var(--faint)" }}>
        Guest progress from your sample lesson carries across to this enrolment.
      </p>
    </div>
  );

  /* ---------- details ---------- */

  const errorBlock = error ? (
    <p className="callout callout--stop" role="alert">
      {error}
    </p>
  ) : null;

  return (
    <main className="pad-lg">
      <div className="checkout">
        <div style={{ display: "grid", gap: "1.35rem" }}>
          <div>
            <h1 className="serif" style={{ fontSize: "1.65rem" }}>
              How would you like to pay?
            </h1>
            <p style={{ fontSize: ".8125rem", color: "var(--muted)", marginTop: ".3rem" }}>
              All three paths produce a sequentially numbered tax invoice.
            </p>
          </div>

          <div>
            <div className="tabs" role="tablist" aria-label="Payment method">
              {(
                [
                  ["card", "Card"],
                  ["eft", "EFT"],
                  ["po", "Purchase order"],
                ] as [Method, string][]
              ).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  role="tab"
                  className="tab"
                  aria-selected={method === value}
                  onClick={() => {
                    setMethod(value);
                    setError(null);
                  }}
                >
                  {label}
                </button>
              ))}
            </div>

            {method === "card" ? (
              <div className="panel" role="tabpanel" aria-label="Card">
                <div className="callout">
                  <b>You will be redirected to Payfast</b>
                  Card details are entered on the gateway, never on this site. Access opens the
                  moment the payment webhook confirms.
                </div>
                <div className="fields">
                  <label className="field">
                    <b>You are purchasing as</b>
                    <select
                      className="input"
                      value={customerType}
                      onChange={(e) => setCustomerType(e.target.value)}
                    >
                      <option value="individual">An individual</option>
                      <option value="registered_business">A registered business</option>
                      <option value="international">International (not yet supported)</option>
                    </select>
                  </label>
                </div>
                {errorBlock}
                <button
                  type="button"
                  className="btn btn--primary btn--lg btn--block"
                  disabled={busy !== null}
                  onClick={payByCard}
                >
                  {busy === "card"
                    ? "Starting checkout…"
                    : `Pay ${total === null ? "" : formatMoney(total)} with Payfast`}
                </button>
              </div>
            ) : null}

            {method === "eft" ? (
              <div className="panel" role="tabpanel" aria-label="EFT">
                <div className="callout callout--warn">
                  <b>Access opens after finance confirms the payment</b>
                  Not when the proof is uploaded. Typically within one business day.
                </div>

                {eft ? (
                  <>
                    <div className="bank">
                      <div>
                        <span className="k">Bank</span>
                        <span className="v">{eft.bank_name}</span>
                      </div>
                      <div>
                        <span className="k">Account name</span>
                        <span className="v">{eft.account_name}</span>
                      </div>
                      <div>
                        <span className="k">Account number</span>
                        <span className="v">{eft.account_number}</span>
                      </div>
                      <div>
                        <span className="k">Branch code</span>
                        <span className="v">{eft.branch_code}</span>
                      </div>
                      <div>
                        <span className="k">Amount</span>
                        <span className="v">
                          {eft.currency} {eft.amount}
                        </span>
                      </div>
                      <div>
                        <span className="k">Your reference</span>
                        <span className="v hi">{eft.payment_reference}</span>
                      </div>
                    </div>
                    <p style={{ fontSize: ".75rem", color: "var(--muted)" }}>
                      Use that reference exactly — it is how the payment is matched to your
                      enrolment.
                    </p>
                    <label className="dropzone" style={{ display: "block", cursor: "pointer" }}>
                      {file ? (
                        <b style={{ color: "var(--brand-ink)" }}>{file.name}</b>
                      ) : (
                        <>
                          Drop your proof of payment here, or{" "}
                          <b style={{ color: "var(--brand-ink)" }}>browse</b>
                          <br />
                          <span style={{ fontSize: ".6875rem" }}>
                            PDF or image, up to 10&nbsp;MB. Scanned before anyone can open it.
                          </span>
                        </>
                      )}
                      <input
                        type="file"
                        accept="application/pdf,image/*"
                        hidden
                        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                      />
                    </label>
                    {errorBlock}
                    <button
                      type="button"
                      className="btn btn--primary btn--block"
                      disabled={!file || busy !== null}
                      onClick={submitProof}
                    >
                      Submit for approval
                    </button>
                  </>
                ) : (
                  <>
                    {errorBlock}
                    <button
                      type="button"
                      className="btn btn--primary btn--lg btn--block"
                      disabled={busy !== null}
                      onClick={payByEft}
                    >
                      {busy === "eft" ? "Starting checkout…" : "Show me the bank details"}
                    </button>
                  </>
                )}
              </div>
            ) : null}

            {method === "po" ? (
              <div className="panel" role="tabpanel" aria-label="Purchase order">
                <div className="callout callout--warn">
                  <b>A pro-forma invoice is issued immediately</b>
                  The tax invoice follows once finance approves the order. Seats stay locked until
                  then.
                </div>
                <div className="fields">
                  <div className="two">
                    <label className="field">
                      <b>Purchase order number</b>
                      <input
                        className="input"
                        value={poNumber}
                        onChange={(e) => setPoNumber(e.target.value)}
                        placeholder="MER-2026-0418"
                      />
                    </label>
                    <label className="field">
                      <b>Seats</b>
                      <input
                        className="input"
                        type="number"
                        min={1}
                        value={seats}
                        onChange={(e) => setSeats(e.target.value)}
                      />
                    </label>
                  </div>
                </div>
                {/* The prototype also shows an accounts-payable email. It is not
                    collected here: POST /orders/{id}/checkout/po accepts only
                    po_number and the document, so the field would be discarded
                    silently. Add ap_email to that endpoint before asking for it. */}
                <label className="dropzone" style={{ display: "block", cursor: "pointer" }}>
                  {poFile ? (
                    <b style={{ color: "var(--brand-ink)" }}>{poFile.name}</b>
                  ) : (
                    <>
                      Attach the signed purchase order ·{" "}
                      <b style={{ color: "var(--brand-ink)" }}>browse</b>
                    </>
                  )}
                  <input
                    type="file"
                    accept="application/pdf,image/*"
                    hidden
                    onChange={(e) => setPoFile(e.target.files?.[0] ?? null)}
                  />
                </label>
                {errorBlock}
                <button
                  type="button"
                  className="btn btn--primary btn--block"
                  disabled={busy !== null}
                  onClick={requestProForma}
                >
                  {busy === "po" ? "Requesting…" : "Request pro-forma invoice"}
                </button>
              </div>
            ) : null}
          </div>
        </div>

        {summary}
      </div>
    </main>
  );
}
