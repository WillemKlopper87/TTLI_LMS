"use client";

/**
 * Step 6 — Pricing & access. The step where the permission split actually
 * bites: a `content_author` holds `course:edit` but neither
 * `course:publish` nor `product:manage`, so those cards render as an
 * explicit hand-off rather than as buttons that would 403. The UI only
 * mirrors server truth; every one of these calls is re-checked server-side.
 *
 * The order below is the order the API enforces: publish → tenant-assign →
 * product → price → activate. A course is invisible and unsellable until
 * all of it is done.
 */

import { useEffect, useState } from "react";

import {
  type ProductItem,
  type SellableCourse,
  type TenantAssignmentRow,
} from "../types";
import { getJson, readError, sendJson } from "../wizard-api";
import { type StepProps, WizardShell } from "../wizard-shell";

const MANAGER_VISIBILITY = [
  { value: "aggregate_only", label: "Aggregate only — participation, never scores" },
  { value: "individual_enabled", label: "Individual reporting enabled" },
  { value: "disabled", label: "No manager reporting" },
];

function HandOff({ permission }: { permission: string }) {
  return (
    <div className="callout callout--warn mt-2">
      <b>Hand off to an admin — you don&apos;t hold {permission}.</b>
      <p style={{ fontSize: "0.8125rem" }}>
        Everything you have authored is saved. An administrator can finish this step from the same
        screen.
      </p>
    </div>
  );
}

export function StepPricing({ ctx, stepStates, onStep, savedAt, error, notice }: StepProps) {
  const course = ctx.course;
  const [assignments, setAssignments] = useState<TenantAssignmentRow[] | null>(null);
  const [products, setProducts] = useState<ProductItem[] | null>(null);
  const [sellable, setSellable] = useState<SellableCourse[] | null>(null);
  const [busy, setBusy] = useState(false);

  const [isBespoke, setIsBespoke] = useState(false);
  const [productSlug, setProductSlug] = useState("");
  const [productName, setProductName] = useState("");
  const [priceAmount, setPriceAmount] = useState("");
  const [priceCurrency, setPriceCurrency] = useState("ZAR");
  const [priceTax, setPriceTax] = useState("exclusive");

  async function loadAccess() {
    const rows = await getJson<{ items: TenantAssignmentRow[] }>("/api/bff/tenant-assignments");
    setAssignments(rows?.items ?? []);
    if (ctx.canManageProducts) {
      const [p, s] = await Promise.all([
        getJson<{ items: ProductItem[] }>("/api/bff/catalogue/products"),
        getJson<{ items: SellableCourse[] }>("/api/bff/catalogue/sellable-courses"),
      ]);
      setProducts(p?.items ?? []);
      setSellable(s?.items ?? []);
    }
  }

  useEffect(() => {
    void (async () => {
      await loadAccess();
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ctx.canManageProducts]);

  useEffect(() => {
    if (course && !productName) {
      setProductName(course.title);
      setProductSlug(course.slug);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [course]);

  const assignment = (assignments ?? []).find((a) => a.course_id === ctx.courseId) ?? null;
  const product = (products ?? []).find((p) => p.course_id === ctx.courseId) ?? null;
  const sellableRow = (sellable ?? []).find((c) => c.id === ctx.courseId) ?? null;

  async function togglePublish() {
    if (!course || !ctx.canPublish) return;
    const action = course.state === "published" ? "unpublish" : "publish";
    setBusy(true);
    ctx.setError(null);
    const resp = await sendJson(`/api/bff/courses/${ctx.courseId}/${action}`, "POST", {});
    setBusy(false);
    if (!resp.ok) {
      ctx.setError(await readError(resp, `The course could not be ${action}ed.`));
      return;
    }
    ctx.markSaved();
    await ctx.reloadCourse();
    await ctx.reloadReadiness();
  }

  async function assignToTenant() {
    if (!ctx.canPublish) return;
    setBusy(true);
    ctx.setError(null);
    const resp = await sendJson(`/api/bff/courses/${ctx.courseId}/tenant-assignments`, "POST", {
      is_bespoke: isBespoke,
    });
    setBusy(false);
    if (!resp.ok) {
      ctx.setError(await readError(resp, "The course could not be assigned to your tenant."));
      return;
    }
    ctx.markSaved();
    await loadAccess();
    await ctx.reloadReadiness();
  }

  async function setManagerVisibility(value: string) {
    setBusy(true);
    ctx.setError(null);
    const resp = await sendJson(`/api/bff/courses/${ctx.courseId}/manager-visibility`, "PATCH", {
      manager_visibility: value,
    });
    setBusy(false);
    if (!resp.ok) {
      ctx.setError(await readError(resp, "Manager visibility could not be changed."));
      return;
    }
    ctx.markSaved();
    await ctx.reloadCourse();
  }

  async function toggleFreePreview(lessonId: string, makePublic: boolean) {
    setBusy(true);
    ctx.setError(null);
    const resp = await sendJson(`/api/bff/lessons/${lessonId}`, "PATCH", {
      access_level: makePublic ? "public" : "paid",
    });
    setBusy(false);
    if (!resp.ok) {
      ctx.setError(await readError(resp, "That lesson's access level could not be changed."));
      return;
    }
    ctx.markSaved();
    await ctx.reloadOutline();
    await ctx.reloadReadiness();
  }

  async function createProduct() {
    setBusy(true);
    ctx.setError(null);
    const resp = await sendJson("/api/bff/catalogue/products", "POST", {
      slug: productSlug.trim(),
      name: productName.trim(),
      description: course?.summary ?? null,
      course_id: ctx.courseId,
    });
    setBusy(false);
    if (!resp.ok) {
      ctx.setError(await readError(resp, "The product could not be created."));
      return;
    }
    ctx.markSaved();
    await loadAccess();
  }

  async function addPrice() {
    if (!product) return;
    setBusy(true);
    ctx.setError(null);
    const resp = await sendJson(`/api/bff/catalogue/products/${product.id}/prices`, "POST", {
      currency: priceCurrency,
      unit_amount: priceAmount,
      tax_behaviour: priceTax,
    });
    setBusy(false);
    if (!resp.ok) {
      ctx.setError(await readError(resp, "The price could not be added."));
      return;
    }
    setPriceAmount("");
    ctx.markSaved();
    await loadAccess();
  }

  async function setActive(isActive: boolean) {
    if (!product) return;
    setBusy(true);
    ctx.setError(null);
    const resp = await sendJson(`/api/bff/catalogue/products/${product.id}`, "PATCH", {
      is_active: isActive,
    });
    setBusy(false);
    if (!resp.ok) {
      ctx.setError(await readError(resp, "The product could not be updated."));
      return;
    }
    ctx.markSaved();
    await loadAccess();
    await ctx.reloadReadiness();
  }

  const lessons = (ctx.outline?.modules ?? []).flatMap((m) =>
    m.lessons.map((l) => ({ module: m.module, lesson: l.lesson })),
  );

  return (
    <WizardShell
      step={6}
      stepStates={stepStates}
      onStep={onStep}
      savedAt={savedAt}
      error={error}
      notice={notice}
      title="Pricing & access"
      intro="Who can see this course, who can buy it, and what a visitor can read before they do."
      onBack={() => onStep(5)}
      onContinue={() => onStep(7)}
    >
      {course === null ? (
        <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>Loading…</p>
      ) : (
        <div className="flex flex-col gap-6">
          <section className="card pad">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="eyebrow">Publish state</p>
                <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
                  A draft course is invisible everywhere. Publishing is refused unless the
                  structure passes — see step 7.
                </p>
              </div>
              <span className={`tag ${course.state === "published" ? "tag--done" : "tag--mute"}`}>
                {course.state}
              </span>
            </div>
            {ctx.canPublish ? (
              <button
                type="button"
                className="btn btn--primary mt-3"
                disabled={busy}
                onClick={() => void togglePublish()}
              >
                {course.state === "published" ? "Unpublish" : "Publish"}
              </button>
            ) : (
              <HandOff permission="course:publish" />
            )}
          </section>

          <section className="card pad">
            <p className="eyebrow">Tenant assignment</p>
            <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
              Only published courses can be assigned. Without an assignment the course is invisible
              to your tenant even once published.
            </p>
            <p className="mt-2" style={{ fontSize: "0.8125rem" }}>
              {assignments === null ? (
                <span style={{ color: "var(--faint)" }}>Checking…</span>
              ) : assignment ? (
                <span className="tag tag--done">
                  Assigned{assignment.is_bespoke ? " · bespoke" : ""}
                </span>
              ) : (
                <span className="tag tag--mute">Not assigned</span>
              )}
            </p>
            {ctx.canPublish ? (
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <label className="flex items-center gap-2" style={{ fontSize: "0.8125rem" }}>
                  <input
                    type="checkbox"
                    checked={isBespoke}
                    onChange={(e) => setIsBespoke(e.target.checked)}
                  />
                  Bespoke to my tenant
                </label>
                <button
                  type="button"
                  className="btn btn--ghost"
                  disabled={busy || course.state !== "published"}
                  onClick={() => void assignToTenant()}
                >
                  Assign to my tenant
                </button>
              </div>
            ) : (
              <HandOff permission="course:publish" />
            )}
          </section>

          <section className="card pad">
            <p className="eyebrow">Manager visibility</p>
            <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
              Privacy is a layout decision: managers see participation, never scores, unless
              individual reporting is deliberately enabled for this course.
            </p>
            <select
              className="input mt-3"
              style={{ maxWidth: "26rem" }}
              value={course.manager_visibility}
              disabled={!ctx.canEdit || busy}
              aria-label="Manager visibility"
              onChange={(e) => void setManagerVisibility(e.target.value)}
            >
              {MANAGER_VISIBILITY.map((v) => (
                <option key={v.value} value={v.value}>
                  {v.label}
                </option>
              ))}
            </select>
          </section>

          <section className="card pad">
            <p className="eyebrow">Free preview</p>
            <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
              A lesson marked <span className="mono">public</span> opens at
              <span className="mono"> /preview/&#123;id&#125;</span> without a purchase — the top of
              the guest → lead funnel.
            </p>
            <div className="tablewrap mt-3">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Lesson</th>
                    <th scope="col">Module</th>
                    <th scope="col">Access</th>
                    <th scope="col">Free preview</th>
                  </tr>
                </thead>
                <tbody>
                  {lessons.length === 0 ? (
                    <tr>
                      <td colSpan={4} style={{ color: "var(--muted)" }}>
                        No lessons yet.
                      </td>
                    </tr>
                  ) : null}
                  {lessons.map(({ module, lesson }) => (
                    <tr key={lesson.id}>
                      <td>{lesson.title}</td>
                      <td style={{ color: "var(--muted)" }}>{module.title}</td>
                      <td>
                        <span
                          className={`tag ${
                            lesson.access_level === "public" ? "tag--live" : "tag--mute"
                          }`}
                        >
                          {lesson.access_level}
                        </span>
                      </td>
                      <td>
                        <input
                          type="checkbox"
                          aria-label={`Free preview: ${lesson.title}`}
                          checked={lesson.access_level === "public"}
                          disabled={!ctx.canEdit || busy}
                          onChange={(e) => void toggleFreePreview(lesson.id, e.target.checked)}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="card pad">
            <p className="eyebrow">Pricing</p>
            {!ctx.canManageProducts ? (
              <HandOff permission="product:manage" />
            ) : sellableRow?.already_sold_as && !product ? (
              <div className="callout mt-2">
                <b>Already sold as &ldquo;{sellableRow.already_sold_as}&rdquo;</b>
                <p style={{ fontSize: "0.8125rem" }}>
                  Manage that product on the Catalogue screen rather than creating a second one.
                </p>
              </div>
            ) : product === null ? (
              <>
                <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
                  Create the product that sells this course. It starts as a draft; a price and an
                  activation follow.
                </p>
                <div className="two mt-3">
                  <label>
                    <b>Product name</b>
                    <input
                      className="input"
                      value={productName}
                      onChange={(e) => setProductName(e.target.value)}
                    />
                  </label>
                  <label>
                    <b>Slug</b>
                    <input
                      className="input"
                      value={productSlug}
                      pattern="[a-z0-9-]+"
                      title="Lowercase letters, numbers and hyphens only"
                      onChange={(e) => setProductSlug(e.target.value)}
                    />
                  </label>
                </div>
                <button
                  type="button"
                  className="btn btn--primary mt-3"
                  disabled={busy || !productName.trim() || !productSlug.trim()}
                  onClick={() => void createProduct()}
                >
                  Create draft product
                </button>
              </>
            ) : (
              <>
                <div className="mt-2 flex flex-wrap items-center gap-3">
                  <b style={{ fontSize: "0.875rem" }}>{product.name}</b>
                  <span className={`tag ${product.is_active ? "tag--done" : "tag--mute"}`}>
                    {product.is_active ? "on sale" : "draft"}
                  </span>
                </div>
                <ul className="mt-2" style={{ fontSize: "0.8125rem" }}>
                  {product.prices.length === 0 ? (
                    <li style={{ color: "var(--muted)" }}>
                      A product needs at least one price before it can go on sale.
                    </li>
                  ) : (
                    product.prices.map((pr) => (
                      <li key={pr.id}>
                        {pr.currency} {pr.unit_amount} ({pr.tax_behaviour} of tax)
                      </li>
                    ))
                  )}
                </ul>
                <div className="mt-3 flex flex-wrap items-end gap-2">
                  <input
                    className="input"
                    style={{ maxWidth: "6rem" }}
                    value={priceCurrency}
                    maxLength={3}
                    aria-label="Currency"
                    onChange={(e) => setPriceCurrency(e.target.value.toUpperCase())}
                  />
                  <input
                    className="input"
                    style={{ maxWidth: "9rem" }}
                    value={priceAmount}
                    inputMode="decimal"
                    placeholder="1500.00"
                    aria-label="Amount"
                    onChange={(e) => setPriceAmount(e.target.value)}
                  />
                  <select
                    className="input"
                    style={{ maxWidth: "10rem" }}
                    value={priceTax}
                    aria-label="Tax behaviour"
                    onChange={(e) => setPriceTax(e.target.value)}
                  >
                    <option value="exclusive">Tax exclusive</option>
                    <option value="inclusive">Tax inclusive</option>
                  </select>
                  <button
                    type="button"
                    className="btn btn--ghost"
                    disabled={busy || !priceAmount}
                    onClick={() => void addPrice()}
                  >
                    Add price
                  </button>
                </div>
                <button
                  type="button"
                  className={`btn mt-3 ${product.is_active ? "btn--ghost" : "btn--primary"}`}
                  disabled={busy}
                  onClick={() => void setActive(!product.is_active)}
                >
                  {product.is_active ? "Take off sale" : "Make available to buy"}
                </button>
              </>
            )}
          </section>
        </div>
      )}
    </WizardShell>
  );
}
