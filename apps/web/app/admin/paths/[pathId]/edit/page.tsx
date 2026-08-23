"use client";

/**
 * `/admin/paths/{id}/edit` — a single-page editor, not a clone of the
 * course wizard's seven-step shell: a path has no lessons, content or
 * assessments to author, only membership, order, a certificate and a
 * publish/assign step. Three sections instead — Basics, Courses,
 * Certification & publish.
 *
 * The course-reorder list reuses the wizard's Curriculum drag idiom
 * (`../../courses/curriculum-outline.tsx`'s `DragRef`/optimistic-local-
 * state/rollback-on-refusal pattern) at a single flat level — closer to
 * `reorderModules` alone than the two-level module/lesson version, since
 * a path's course list has no nesting.
 */

import { type DragEvent, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";

import { useAdmin } from "../../../admin-context";
import type { CertificateTemplate, CourseItem, ProductItem } from "../../../courses/types";
import { authedFetch, getJson, readError, sendJson } from "../../../courses/wizard-api";

interface LearningPathItem {
  id: string;
  slug: string;
  title: string;
  description: string | null;
  state: string;
  certificate_template_id: string | null;
}

interface PathCourseRow {
  course_id: string;
  title: string;
  slug: string;
  state: string;
  level: string | null;
  position: number;
}

interface ReadinessCheckRow {
  code: string;
  level: string;
  ok: boolean;
  message: string;
}

interface PathReadiness {
  publishable: boolean;
  course_count: number;
  checks: ReadinessCheckRow[];
}

export default function EditLearningPathPage() {
  const params = useParams<{ pathId: string }>();
  const pathId = params.pathId;
  const { me } = useAdmin();
  const canEdit = me.permissions.includes("course:edit");
  const canPublish = me.permissions.includes("course:publish");

  const [path, setPath] = useState<LearningPathItem | null>(null);
  const [members, setMembers] = useState<PathCourseRow[] | null>(null);
  const [readiness, setReadiness] = useState<PathReadiness | null>(null);
  const [allCourses, setAllCourses] = useState<CourseItem[] | null>(null);
  const [certificates, setCertificates] = useState<CertificateTemplate[] | null>(null);
  const [product, setProduct] = useState<ProductItem | null>(null);

  const [addCourseId, setAddCourseId] = useState("");
  const [priceAmount, setPriceAmount] = useState("");
  const [priceCurrency, setPriceCurrency] = useState("ZAR");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const dragRef = useRef<string | null>(null);
  const canManageProducts = me.permissions.includes("product:manage");

  async function loadAll() {
    const [pathResp, membersResp, readinessResp] = await Promise.all([
      getJson<LearningPathItem>(`/api/bff/learning-paths/${pathId}`),
      getJson<{ items: PathCourseRow[] }>(`/api/bff/learning-paths/${pathId}/courses`),
      getJson<PathReadiness>(`/api/bff/learning-paths/${pathId}/readiness`),
    ]);
    setPath(pathResp);
    setMembers(membersResp?.items ?? []);
    setReadiness(readinessResp);
    if (canManageProducts) {
      const products = await getJson<{ items: ProductItem[] }>("/api/bff/catalogue/products");
      setProduct((products?.items ?? []).find((p) => p.learning_path_id === pathId) ?? null);
    }
  }

  useEffect(() => {
    void loadAll();
    void getJson<{ items: CourseItem[] }>("/api/bff/courses").then((r) =>
      setAllCourses(r?.items ?? []),
    );
    void getJson<{ items: CertificateTemplate[] }>("/api/bff/certificate-templates").then((r) =>
      setCertificates(r?.items ?? []),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathId]);

  async function saveBasics(title: string, description: string) {
    setError(null);
    const resp = await sendJson(`/api/bff/learning-paths/${pathId}`, "PATCH", {
      title: title.trim() || undefined,
      description,
    });
    if (!resp.ok) {
      setError(await readError(resp, "The path could not be saved."));
      return;
    }
    setNotice("Saved.");
    await loadAll();
  }

  async function addCourse() {
    if (!addCourseId) return;
    setBusy(true);
    setError(null);
    const resp = await sendJson(`/api/bff/learning-paths/${pathId}/courses`, "POST", {
      course_id: addCourseId,
    });
    setBusy(false);
    if (!resp.ok) {
      setError(await readError(resp, "That course could not be added."));
      return;
    }
    setAddCourseId("");
    await loadAll();
  }

  async function removeCourse(courseId: string) {
    setBusy(true);
    setError(null);
    const resp = await authedFetch(`/api/bff/learning-paths/${pathId}/courses/${courseId}`, {
      method: "DELETE",
    });
    setBusy(false);
    if (!resp.ok) {
      setError(await readError(resp, "That course could not be removed."));
      return;
    }
    await loadAll();
  }

  async function createProduct() {
    if (!path) return;
    setBusy(true);
    setError(null);
    const resp = await sendJson("/api/bff/catalogue/products", "POST", {
      slug: path.slug,
      name: path.title,
      description: path.description,
      learning_path_id: pathId,
    });
    setBusy(false);
    if (!resp.ok) {
      setError(await readError(resp, "The product could not be created."));
      return;
    }
    setNotice("Product created — add a price to make it purchasable.");
    await loadAll();
  }

  async function addPrice() {
    if (!product || !priceAmount) return;
    setBusy(true);
    setError(null);
    const resp = await sendJson(`/api/bff/catalogue/products/${product.id}/prices`, "POST", {
      currency: priceCurrency,
      unit_amount: priceAmount,
    });
    setBusy(false);
    if (!resp.ok) {
      setError(await readError(resp, "The price could not be added."));
      return;
    }
    setPriceAmount("");
    await loadAll();
  }

  async function setProductActive(isActive: boolean) {
    if (!product) return;
    setBusy(true);
    setError(null);
    const resp = await sendJson(`/api/bff/catalogue/products/${product.id}`, "PATCH", {
      is_active: isActive,
    });
    setBusy(false);
    if (!resp.ok) {
      setError(await readError(resp, "The product could not be updated."));
      return;
    }
    setNotice(isActive ? "Now on sale." : "Taken off sale.");
    await loadAll();
  }

  function allowDrop(event: DragEvent) {
    if (!dragRef.current) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }

  async function reorder(targetCourseId: string) {
    const draggedId = dragRef.current;
    dragRef.current = null;
    if (!draggedId || draggedId === targetCourseId || members === null) return;
    const previous = members;
    const from = previous.findIndex((m) => m.course_id === draggedId);
    const to = previous.findIndex((m) => m.course_id === targetCourseId);
    if (from < 0 || to < 0) return;
    const next = [...previous];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    setMembers(next);
    setError(null);
    setBusy(true);
    const resp = await sendJson(`/api/bff/learning-paths/${pathId}/courses/reorder`, "POST", {
      ordered_course_ids: next.map((m) => m.course_id),
    });
    setBusy(false);
    if (!resp.ok) {
      setMembers(previous);
      setError(await readError(resp, "The courses could not be reordered."));
      return;
    }
    await loadAll();
  }

  async function attachCertificate(templateId: string) {
    setError(null);
    const resp = await sendJson(`/api/bff/learning-paths/${pathId}`, "PATCH", {
      certificate_template_id: templateId,
    });
    if (!resp.ok) {
      setError(await readError(resp, "The certificate template could not be attached."));
      return;
    }
    await loadAll();
  }

  async function togglePublish() {
    if (!path) return;
    const action = path.state === "published" ? "unpublish" : "publish";
    setBusy(true);
    setError(null);
    const resp = await sendJson(`/api/bff/learning-paths/${pathId}/${action}`, "POST", {});
    setBusy(false);
    if (!resp.ok) {
      setError(await readError(resp, `The path could not be ${action}ed.`));
      return;
    }
    setNotice(action === "publish" ? "Published." : "Unpublished — back to draft.");
    await loadAll();
  }

  async function assignToTenant() {
    setBusy(true);
    setError(null);
    const resp = await sendJson(`/api/bff/learning-paths/${pathId}/tenant-assignments`, "POST", {
      is_bespoke: false,
    });
    setBusy(false);
    if (!resp.ok) {
      setError(await readError(resp, "The path could not be assigned to your tenant."));
      return;
    }
    setNotice("Assigned to your tenant.");
  }

  if (path === null) {
    return (
      <div className="dash">
        <p style={{ color: "var(--faint)" }}>Loading…</p>
      </div>
    );
  }

  const availableCourses = (allCourses ?? []).filter(
    (c) => !(members ?? []).some((m) => m.course_id === c.id),
  );

  return (
    <div className="dash">
      <div className="dash-top">
        <div>
          <p className="eyebrow">Path setup</p>
          <h1>{path.title}</h1>
        </div>
        <a className="btn btn--ghost" href="/admin/paths">
          All paths
        </a>
      </div>

      {error ? (
        <div className="callout callout--warn" role="alert">
          <p style={{ fontSize: "0.8125rem" }}>{error}</p>
        </div>
      ) : null}
      {notice ? (
        <div className="callout callout--done">
          <p style={{ fontSize: "0.8125rem" }}>{notice}</p>
        </div>
      ) : null}

      <div className="card p-4 mt-4">
        <b>Basics</b>
        <label className="field mt-2">
          <span>Title</span>
          <input
            className="input"
            defaultValue={path.title}
            disabled={!canEdit}
            onBlur={(e) => void saveBasics(e.target.value, path.description ?? "")}
          />
        </label>
        <label className="field mt-2">
          <span>Description</span>
          <textarea
            className="input"
            defaultValue={path.description ?? ""}
            disabled={!canEdit}
            rows={2}
            onBlur={(e) => void saveBasics(path.title, e.target.value)}
          />
        </label>
      </div>

      <div className="card p-4 mt-4">
        <b>Courses</b>
        <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
          Drag to reorder — this is the order a learner completes them in.
        </p>
        <ul className="mt-2 flex flex-col gap-1">
          {(members ?? []).map((m, index) => (
            <li
              key={m.course_id}
              onDragOver={allowDrop}
              onDrop={(e) => {
                e.preventDefault();
                void reorder(m.course_id);
              }}
              className="flex items-center gap-2"
              style={{
                border: "1px solid var(--rule)",
                padding: "0.5rem 0.75rem",
                background: "var(--surface)",
              }}
            >
              {canEdit ? (
                <span
                  draggable
                  onDragStart={(e) => {
                    dragRef.current = m.course_id;
                    e.dataTransfer.effectAllowed = "move";
                    e.dataTransfer.setData("text/plain", m.course_id);
                  }}
                  title="Drag to reorder"
                  aria-label="Drag to reorder"
                  style={{ cursor: "grab", color: "var(--faint)", fontFamily: "var(--mono)" }}
                >
                  ⋮⋮
                </span>
              ) : null}
              <span style={{ fontFamily: "var(--mono)", color: "var(--faint)" }}>{index + 1}</span>
              <span className="flex-1">{m.title}</span>
              <span
                className={`tag ${m.state === "published" ? "tag--done" : "tag--mute"}`}
              >
                {m.state}
              </span>
              {canEdit ? (
                <button
                  type="button"
                  className="btn btn--quiet"
                  disabled={busy}
                  onClick={() => void removeCourse(m.course_id)}
                >
                  Remove
                </button>
              ) : null}
            </li>
          ))}
          {members !== null && members.length === 0 ? (
            <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>No courses added yet.</p>
          ) : null}
        </ul>

        {canEdit ? (
          <div className="mt-3 flex items-end gap-2">
            <label className="field">
              <span>Add a course</span>
              <select
                className="input"
                value={addCourseId}
                onChange={(e) => setAddCourseId(e.target.value)}
              >
                <option value="">Select a course…</option>
                {availableCourses.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.title} ({c.state})
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="btn btn--primary"
              disabled={!addCourseId || busy}
              onClick={() => void addCourse()}
            >
              Add
            </button>
          </div>
        ) : null}
      </div>

      <div className="card p-4 mt-4">
        <b>Certification</b>
        <label className="field mt-2">
          <span>Certificate template</span>
          <select
            className="input"
            value={path.certificate_template_id ?? ""}
            disabled={!canEdit}
            onChange={(e) => void attachCertificate(e.target.value)}
          >
            <option value="">No certificate</option>
            {(certificates ?? []).map((t) => (
              <option key={t.id} value={t.id}>
                {t.title}
              </option>
            ))}
          </select>
        </label>
      </div>

      {canManageProducts ? (
        <div className="card p-4 mt-4">
          <b>Sell this path</b>
          {product === null ? (
            <>
              <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
                No product yet — a path needs one to be purchasable.
              </p>
              <button
                type="button"
                className="btn btn--primary mt-2"
                disabled={busy}
                onClick={() => void createProduct()}
              >
                Create product
              </button>
            </>
          ) : (
            <>
              <p className="mt-1 flex items-center gap-2" style={{ fontSize: "0.8125rem" }}>
                <span>{product.name}</span>
                <span className={`tag ${product.is_active ? "tag--done" : "tag--mute"}`}>
                  {product.is_active ? "on sale" : "inactive"}
                </span>
              </p>
              <ul className="mt-2 flex flex-col gap-1">
                {product.prices.map((p) => (
                  <li key={p.id} style={{ fontSize: "0.8125rem" }}>
                    {p.currency} {p.unit_amount}
                  </li>
                ))}
                {product.prices.length === 0 ? (
                  <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>No price yet.</p>
                ) : null}
              </ul>
              <div className="mt-2 flex items-end gap-2">
                <label className="field">
                  <span>Currency</span>
                  <input
                    className="input"
                    style={{ width: "5rem" }}
                    value={priceCurrency}
                    onChange={(e) => setPriceCurrency(e.target.value.toUpperCase())}
                    maxLength={3}
                  />
                </label>
                <label className="field">
                  <span>Amount</span>
                  <input
                    className="input"
                    value={priceAmount}
                    onChange={(e) => setPriceAmount(e.target.value)}
                    placeholder="e.g. 3000.00"
                  />
                </label>
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
                className="btn btn--ghost mt-2"
                disabled={busy || product.prices.length === 0}
                onClick={() => void setProductActive(!product.is_active)}
              >
                {product.is_active ? "Take off sale" : "Put on sale"}
              </button>
            </>
          )}
        </div>
      ) : null}

      {readiness ? (
        <div className="reqs mt-4">
          <div className="reqs-head">
            <h4>Readiness</h4>
            <span className={`tag ${readiness.publishable ? "tag--done" : "tag--stop"}`}>
              {readiness.publishable ? "Publishable" : "Not yet publishable"}
            </span>
          </div>
          {readiness.checks.map((check) => (
            <div key={check.code} className={`req${check.ok ? " met" : ""}`}>
              <span className="mk">{check.ok ? "✓" : check.level === "blocker" ? "!" : "○"}</span>
              <span className="lbl">{check.message}</span>
              <span className="val">{check.code}</span>
            </div>
          ))}
        </div>
      ) : null}

      <div className="mt-4 flex flex-wrap items-center gap-3">
        {canPublish ? (
          <button
            type="button"
            className={path.state === "published" ? "btn btn--ghost" : "btn btn--primary btn--lg"}
            disabled={busy || (path.state !== "published" && !(readiness?.publishable ?? false))}
            onClick={() => void togglePublish()}
          >
            {path.state === "published" ? "Unpublish" : "Publish this path"}
          </button>
        ) : null}
        {canPublish && path.state === "published" ? (
          <button
            type="button"
            className="btn btn--ghost"
            disabled={busy}
            onClick={() => void assignToTenant()}
          >
            Assign to my tenant
          </button>
        ) : null}
      </div>
    </div>
  );
}
