"use client";

import { Fragment, useEffect, useState } from "react";

import { getAccessToken } from "@/lib/session";

import { useAdmin } from "../admin-context";

interface PlanItem {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  price_id: string;
  billing_interval_days: number;
  is_active: boolean;
}

interface CourseItem {
  id: string;
  title: string;
}

interface PlanCourseRow {
  course_id: string;
  course_title: string;
}

/**
 * Subscription plan authoring (backlog: multi-tier subscriptions,
 * REQ-PAY-12). `subscription_plan:manage`-gated server-side, mirrored
 * here only to hide forms a caller can't use — same convention as every
 * other admin authoring screen. Renewals are funded through the existing
 * EFT/PO checkout flow, not automatic card charging
 * (services/subscriptions.py's own docstring); this screen only builds
 * the plan/bundle shape, not a billing dashboard.
 */
export default function SubscriptionsScreen() {
  const { me } = useAdmin();
  const canManage = me.permissions.includes("subscription_plan:manage");

  const [plans, setPlans] = useState<PlanItem[] | null>(null);
  const [courses, setCourses] = useState<CourseItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [unitAmount, setUnitAmount] = useState("");
  const [billingIntervalDays, setBillingIntervalDays] = useState("30");
  const [createBusy, setCreateBusy] = useState(false);

  const [expandedPlanId, setExpandedPlanId] = useState<string | null>(null);
  const [planCourses, setPlanCourses] = useState<PlanCourseRow[] | null>(null);
  const [addCourseId, setAddCourseId] = useState("");

  async function authedFetch(path: string, init: RequestInit = {}) {
    const token = getAccessToken();
    return fetch(path, { ...init, headers: { ...init.headers, Authorization: `Bearer ${token}` } });
  }

  async function loadPlans() {
    const resp = await authedFetch("/api/bff/subscription-plans");
    if (resp.ok) setPlans((await resp.json()).items);
  }

  async function loadCourses() {
    const resp = await authedFetch("/api/bff/courses");
    if (resp.ok) setCourses((await resp.json()).items);
  }

  useEffect(() => {
    if (!canManage) return;
    loadPlans();
    loadCourses();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canManage]);

  async function createPlan() {
    if (!slug.trim() || !name.trim() || !unitAmount.trim()) return;
    setCreateBusy(true);
    setError(null);
    const resp = await authedFetch("/api/bff/subscription-plans", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        slug: slug.trim(),
        name: name.trim(),
        description: description.trim() || null,
        currency: "ZAR",
        unit_amount: unitAmount,
        billing_interval_days: Number(billingIntervalDays) || 30,
      }),
    });
    setCreateBusy(false);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not create that plan.");
      return;
    }
    setSlug("");
    setName("");
    setDescription("");
    setUnitAmount("");
    setBillingIntervalDays("30");
    await loadPlans();
  }

  async function togglePlan(planId: string) {
    if (expandedPlanId === planId) {
      setExpandedPlanId(null);
      setPlanCourses(null);
      return;
    }
    setExpandedPlanId(planId);
    const resp = await authedFetch(`/api/bff/subscription-plans/${planId}/courses`);
    setPlanCourses(resp.ok ? (await resp.json()).items : []);
  }

  async function addCourseToPlan(planId: string) {
    if (!addCourseId) return;
    const resp = await authedFetch(`/api/bff/subscription-plans/${planId}/courses`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ course_id: addCourseId }),
    });
    if (resp.ok) {
      setAddCourseId("");
      const refreshed = await authedFetch(`/api/bff/subscription-plans/${planId}/courses`);
      if (refreshed.ok) setPlanCourses((await refreshed.json()).items);
    }
  }

  async function removeCourseFromPlan(planId: string, courseId: string) {
    const resp = await authedFetch(`/api/bff/subscription-plans/${planId}/courses/${courseId}`, {
      method: "DELETE",
    });
    if (resp.ok) {
      const refreshed = await authedFetch(`/api/bff/subscription-plans/${planId}/courses`);
      if (refreshed.ok) setPlanCourses((await refreshed.json()).items);
    }
  }

  if (!canManage) {
    return (
      <div>
        <h1 className="serif" style={{ fontSize: "1.5rem" }}>
          Subscriptions
        </h1>
        <p className="mt-2" style={{ color: "var(--muted)" }}>
          Your role doesn&apos;t hold <code>subscription_plan:manage</code>, so there&apos;s nothing
          to show here.
        </p>
      </div>
    );
  }

  return (
    <div>
      <h1 className="serif" style={{ fontSize: "1.5rem" }}>
        Subscriptions
      </h1>
      <p className="mt-1" style={{ color: "var(--muted)" }}>
        Multi-tier plans, each granting renewing access to a bundle of courses. Renewals are funded
        through the same EFT/PO checkout flow as one-time purchases.
      </p>
      {error ? (
        <p role="alert" className="mt-3" style={{ color: "var(--stop)" }}>
          {error}
        </p>
      ) : null}

      <div className="card mt-4 p-4">
        <b style={{ fontSize: "0.875rem" }}>Create a plan</b>
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <label className="field">
            <b>Slug</b>
            <input
              className="input"
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              placeholder="full-library"
            />
          </label>
          <label className="field">
            <b>Name</b>
            <input
              className="input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Full Library"
            />
          </label>
          <label className="field">
            <b>Price (ZAR/period)</b>
            <input
              className="input"
              type="number"
              min={0}
              value={unitAmount}
              onChange={(e) => setUnitAmount(e.target.value)}
              style={{ maxWidth: "8rem" }}
            />
          </label>
          <label className="field">
            <b>Billing interval (days)</b>
            <input
              className="input"
              type="number"
              min={1}
              value={billingIntervalDays}
              onChange={(e) => setBillingIntervalDays(e.target.value)}
              style={{ maxWidth: "8rem" }}
            />
          </label>
          <button
            type="button"
            className="btn btn--primary"
            disabled={createBusy || !slug.trim() || !name.trim() || !unitAmount.trim()}
            onClick={createPlan}
          >
            Create plan
          </button>
        </div>
        <label className="field mt-2">
          <b>Description (optional)</b>
          <input
            className="input"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </label>
      </div>

      <div className="table-wrap mt-4">
        <table className="data">
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Slug</th>
              <th scope="col">Interval</th>
              <th scope="col">Active</th>
              <th scope="col"></th>
            </tr>
          </thead>
          <tbody>
            {(plans ?? []).map((p) => (
              <Fragment key={p.id}>
                <tr>
                  <td>{p.name}</td>
                  <td className="mono" style={{ fontSize: "0.75rem" }}>
                    {p.slug}
                  </td>
                  <td className="mono">{p.billing_interval_days}d</td>
                  <td>
                    <span className={`tag ${p.is_active ? "tag--done" : "tag--mute"}`}>
                      {p.is_active ? "active" : "inactive"}
                    </span>
                  </td>
                  <td>
                    <button type="button" className="btn btn--ghost" onClick={() => togglePlan(p.id)}>
                      {expandedPlanId === p.id ? "Close" : "Manage bundle"}
                    </button>
                  </td>
                </tr>
                {expandedPlanId === p.id ? (
                  <tr>
                    <td colSpan={5}>
                      <div className="card p-3" style={{ background: "var(--bg)" }}>
                        <b style={{ fontSize: "0.8125rem" }}>Course bundle</b>
                        <div className="mt-2 flex flex-col gap-1">
                          {(planCourses ?? []).map((c) => (
                            <div
                              key={c.course_id}
                              className="flex items-center justify-between gap-2"
                              style={{ fontSize: "0.8125rem" }}
                            >
                              <span>{c.course_title}</span>
                              <button
                                type="button"
                                className="btn btn--ghost"
                                onClick={() => removeCourseFromPlan(p.id, c.course_id)}
                              >
                                Remove
                              </button>
                            </div>
                          ))}
                          {planCourses !== null && planCourses.length === 0 ? (
                            <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>
                              No courses bundled yet.
                            </p>
                          ) : null}
                        </div>
                        <div className="mt-2 flex items-end gap-2">
                          <label className="field">
                            <b>Add a course</b>
                            <select
                              className="input"
                              value={addCourseId}
                              onChange={(e) => setAddCourseId(e.target.value)}
                            >
                              <option value="">Select a course…</option>
                              {(courses ?? []).map((c) => (
                                <option key={c.id} value={c.id}>
                                  {c.title}
                                </option>
                              ))}
                            </select>
                          </label>
                          <button
                            type="button"
                            className="btn btn--primary"
                            disabled={!addCourseId}
                            onClick={() => addCourseToPlan(p.id)}
                          >
                            Add
                          </button>
                        </div>
                      </div>
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            ))}
            {plans !== null && plans.length === 0 ? (
              <tr>
                <td colSpan={5} style={{ color: "var(--faint)" }}>
                  No plans yet.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}
