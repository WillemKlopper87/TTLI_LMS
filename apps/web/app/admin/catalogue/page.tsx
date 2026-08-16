"use client";

import { Fragment, useEffect, useState } from "react";

import { getAccessToken } from "@/lib/session";

import { useAdmin } from "../admin-context";

interface PriceRow {
  id: string;
  currency: string;
  unit_amount: string;
  tax_behaviour: string;
}

interface ProductItem {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  kind: string;
  is_active: boolean;
  course_id: string | null;
  course_title: string | null;
  subscription_plan_id: string | null;
  prices: PriceRow[];
}

interface SellableCourse {
  id: string;
  title: string;
  state: string;
  already_sold_as: string | null;
}

/**
 * Product authoring (frontend backlog item 5) — the screen that makes an
 * authored course purchasable. `product:manage`-gated server-side;
 * mirrored here only to hide forms a caller can't use, the same
 * convention every other admin authoring screen follows.
 *
 * Products owned by a subscription plan are listed read-only: the plan
 * owns its product/price triple as one unit (services/subscriptions.py),
 * so editing it here would desynchronise the two. Those rows link the
 * reader to the subscriptions screen instead.
 */
export default function CatalogueScreen() {
  const { me } = useAdmin();
  const canManage = me.permissions.includes("product:manage");

  const [products, setProducts] = useState<ProductItem[] | null>(null);
  const [courses, setCourses] = useState<SellableCourse[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [courseId, setCourseId] = useState("");
  const [createBusy, setCreateBusy] = useState(false);

  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [priceAmount, setPriceAmount] = useState("");
  const [priceCurrency, setPriceCurrency] = useState("ZAR");
  const [priceTax, setPriceTax] = useState("exclusive");

  async function authedFetch(path: string, init: RequestInit = {}) {
    const token = getAccessToken();
    return fetch(path, { ...init, headers: { ...init.headers, Authorization: `Bearer ${token}` } });
  }

  async function load() {
    const [p, c] = await Promise.all([
      authedFetch("/api/bff/catalogue/products"),
      authedFetch("/api/bff/catalogue/sellable-courses"),
    ]);
    if (p.ok) setProducts((await p.json()).items);
    else setError("Products could not be loaded.");
    if (c.ok) setCourses((await c.json()).items);
  }

  useEffect(() => {
    if (!canManage) return;
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canManage]);

  /** Surfaces the API's own refusal text rather than a generic message —
   * every failure this screen can hit (duplicate slug, unassigned course,
   * publishing with no price, deleting a sold price) has a specific,
   * actionable reason the server already wrote. */
  async function readError(resp: Response, fallback: string) {
    try {
      const body = await resp.json();
      return body?.error?.message ?? fallback;
    } catch {
      return fallback;
    }
  }

  async function createProduct(event: React.FormEvent) {
    event.preventDefault();
    setCreateBusy(true);
    setError(null);
    setNotice(null);
    const resp = await authedFetch("/api/bff/catalogue/products", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        slug,
        name,
        description: description || null,
        course_id: courseId || null,
      }),
    });
    setCreateBusy(false);
    if (!resp.ok) {
      setError(await readError(resp, "The product could not be created."));
      return;
    }
    setSlug("");
    setName("");
    setDescription("");
    setCourseId("");
    setNotice("Product created as a draft. Add a price, then make it available to buy.");
    load();
  }

  async function addPrice(productId: string) {
    setError(null);
    setNotice(null);
    const resp = await authedFetch(`/api/bff/catalogue/products/${productId}/prices`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        currency: priceCurrency,
        unit_amount: priceAmount,
        tax_behaviour: priceTax,
      }),
    });
    if (!resp.ok) {
      setError(await readError(resp, "The price could not be added."));
      return;
    }
    setPriceAmount("");
    load();
  }

  async function deletePrice(priceId: string) {
    setError(null);
    setNotice(null);
    const resp = await authedFetch(`/api/bff/catalogue/prices/${priceId}`, { method: "DELETE" });
    if (!resp.ok) {
      setError(await readError(resp, "The price could not be removed."));
      return;
    }
    load();
  }

  async function setActive(productId: string, isActive: boolean) {
    setError(null);
    setNotice(null);
    const resp = await authedFetch(`/api/bff/catalogue/products/${productId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_active: isActive }),
    });
    if (!resp.ok) {
      setError(await readError(resp, "The product could not be updated."));
      return;
    }
    load();
  }

  async function attachCourse(productId: string, newCourseId: string) {
    setError(null);
    setNotice(null);
    const resp = await authedFetch(`/api/bff/catalogue/products/${productId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ course_id: newCourseId }),
    });
    if (!resp.ok) {
      setError(await readError(resp, "The course could not be attached."));
      return;
    }
    load();
  }

  if (!canManage) {
    return (
      <div>
        <h1 className="serif" style={{ fontSize: "1.5rem" }}>
          Catalogue
        </h1>
        <p className="mt-2" style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
          You do not have permission to manage products.
        </p>
      </div>
    );
  }

  return (
    <div>
      <h1 className="serif" style={{ fontSize: "1.5rem" }}>
        Catalogue
      </h1>
      <p className="mt-1" style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
        Turn an authored course into something a learner can buy.
      </p>

      {error ? (
        <p role="alert" className="mt-4" style={{ fontSize: "0.8125rem", color: "var(--stop)" }}>
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="mt-4" style={{ fontSize: "0.8125rem", color: "var(--done)" }}>
          {notice}
        </p>
      ) : null}

      <section className="card mt-6" style={{ padding: "1.25rem" }}>
        <h2 className="serif" style={{ fontSize: "1.1rem" }}>
          New product
        </h2>
        <form onSubmit={createProduct} className="mt-3 space-y-3">
          <input
            className="input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Product name"
            aria-label="Product name"
            required
          />
          <input
            className="input"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            placeholder="url-slug"
            aria-label="Slug"
            pattern="[a-z0-9-]+"
            title="Lowercase letters, numbers and hyphens only"
            required
          />
          <textarea
            className="input"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Description shown in the catalogue (optional)"
            aria-label="Description"
            rows={2}
          />
          <select
            className="input"
            value={courseId}
            onChange={(e) => setCourseId(e.target.value)}
            aria-label="Course to sell"
          >
            <option value="">No course — a sellable wrapper only</option>
            {(courses ?? []).map((c) => (
              <option key={c.id} value={c.id}>
                {c.title}
                {c.state !== "published" ? ` (${c.state})` : ""}
                {c.already_sold_as ? ` — already sold as "${c.already_sold_as}"` : ""}
              </option>
            ))}
          </select>
          <button type="submit" disabled={createBusy} className="btn btn--primary">
            Create draft product
          </button>
        </form>
      </section>

      <section className="mt-8">
        <h2 className="serif" style={{ fontSize: "1.1rem" }}>
          Products
        </h2>
        {products === null ? (
          <p className="mt-2" style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
            Loading…
          </p>
        ) : products.length === 0 ? (
          <p className="mt-2" style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
            No products yet.
          </p>
        ) : (
          <table className="mt-3 w-full" style={{ fontSize: "0.875rem" }}>
            <thead>
              <tr style={{ textAlign: "left", color: "var(--muted)" }}>
                <th className="py-2">Name</th>
                <th className="py-2">Course</th>
                <th className="py-2">Prices</th>
                <th className="py-2">Status</th>
                <th className="py-2" />
              </tr>
            </thead>
            <tbody>
              {products.map((p) => {
                const ownedByPlan = p.subscription_plan_id !== null;
                return (
                  <Fragment key={p.id}>
                    <tr style={{ borderTop: "1px solid var(--rule)" }}>
                      <td className="py-2">
                        {p.name}
                        <div style={{ fontSize: "0.75rem", color: "var(--muted)" }}>{p.slug}</div>
                      </td>
                      <td className="py-2">
                        {p.course_title ?? (
                          <span style={{ color: "var(--muted)" }}>—</span>
                        )}
                      </td>
                      <td className="py-2">
                        {p.prices.length === 0 ? (
                          <span style={{ color: "var(--muted)" }}>none</span>
                        ) : (
                          p.prices
                            .map((pr) => `${pr.currency} ${pr.unit_amount}`)
                            .join(", ")
                        )}
                      </td>
                      <td className="py-2">
                        <span className={p.is_active ? "tag tag--brand" : "tag"}>
                          {ownedByPlan ? "subscription" : p.is_active ? "on sale" : "draft"}
                        </span>
                      </td>
                      <td className="py-2" style={{ textAlign: "right" }}>
                        {ownedByPlan ? (
                          <span style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                            Managed on Subscriptions
                          </span>
                        ) : (
                          <button
                            type="button"
                            className="btn btn--ghost"
                            onClick={() => setExpandedId(expandedId === p.id ? null : p.id)}
                          >
                            {expandedId === p.id ? "Close" : "Manage"}
                          </button>
                        )}
                      </td>
                    </tr>
                    {expandedId === p.id && !ownedByPlan ? (
                      <tr>
                        <td colSpan={5} style={{ background: "var(--surface-2)" }}>
                          <div className="p-4 space-y-4">
                            <div>
                              <h3 style={{ fontSize: "0.8125rem", fontWeight: 600 }}>Prices</h3>
                              {p.prices.length === 0 ? (
                                <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
                                  A product needs at least one price before it can go on sale.
                                </p>
                              ) : (
                                <ul className="mt-1 space-y-1">
                                  {p.prices.map((pr) => (
                                    <li key={pr.id} style={{ fontSize: "0.8125rem" }}>
                                      {pr.currency} {pr.unit_amount} ({pr.tax_behaviour} of tax){" "}
                                      <button
                                        type="button"
                                        className="btn btn--ghost"
                                        onClick={() => deletePrice(pr.id)}
                                      >
                                        Remove
                                      </button>
                                    </li>
                                  ))}
                                </ul>
                              )}
                              <div className="mt-2 flex gap-2">
                                <input
                                  className="input"
                                  style={{ maxWidth: "7rem" }}
                                  value={priceCurrency}
                                  onChange={(e) => setPriceCurrency(e.target.value.toUpperCase())}
                                  aria-label="Currency"
                                  maxLength={3}
                                />
                                <input
                                  className="input"
                                  style={{ maxWidth: "9rem" }}
                                  value={priceAmount}
                                  onChange={(e) => setPriceAmount(e.target.value)}
                                  placeholder="1500.00"
                                  aria-label="Amount"
                                  inputMode="decimal"
                                />
                                <select
                                  className="input"
                                  style={{ maxWidth: "10rem" }}
                                  value={priceTax}
                                  onChange={(e) => setPriceTax(e.target.value)}
                                  aria-label="Tax behaviour"
                                >
                                  <option value="exclusive">Tax exclusive</option>
                                  <option value="inclusive">Tax inclusive</option>
                                </select>
                                <button
                                  type="button"
                                  className="btn btn--primary"
                                  onClick={() => addPrice(p.id)}
                                  disabled={!priceAmount}
                                >
                                  Add price
                                </button>
                              </div>
                            </div>

                            <div>
                              <h3 style={{ fontSize: "0.8125rem", fontWeight: 600 }}>Course</h3>
                              <select
                                className="input mt-1"
                                style={{ maxWidth: "26rem" }}
                                value={p.course_id ?? ""}
                                onChange={(e) => attachCourse(p.id, e.target.value)}
                                aria-label="Course sold by this product"
                              >
                                <option value="">No course attached</option>
                                {(courses ?? []).map((c) => (
                                  <option key={c.id} value={c.id}>
                                    {c.title}
                                    {c.state !== "published" ? ` (${c.state})` : ""}
                                  </option>
                                ))}
                              </select>
                              <p
                                className="mt-1"
                                style={{ fontSize: "0.75rem", color: "var(--muted)" }}
                              >
                                Buying this product enrols the learner in the attached course.
                              </p>
                            </div>

                            <div>
                              {p.is_active ? (
                                <button
                                  type="button"
                                  className="btn btn--ghost"
                                  onClick={() => setActive(p.id, false)}
                                >
                                  Take off sale
                                </button>
                              ) : (
                                <button
                                  type="button"
                                  className="btn btn--primary"
                                  onClick={() => setActive(p.id, true)}
                                >
                                  Make available to buy
                                </button>
                              )}
                            </div>
                          </div>
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
