"use client";

/**
 * `/admin/assessments` — assessment templates and instances management.
 * Two tabs: Templates (GET /assessment-platform/templates) and Instances
 * (GET /assessment-platform/instances). Requires assessment:author for
 * templates, assessment:run for instances.
 */

import { useEffect, useState } from "react";

import { useAdmin } from "../admin-context";
import { authedFetch, readError } from "../courses/wizard-api";

interface TemplateItem {
  id: string;
  slug: string;
  title: string;
  kind: string;
  response_mode: string;
  status: string;
  version: number;
}

interface InstanceItem {
  id: string;
  template_id: string;
  organisation_id: string;
  title: string;
  status: string;
  evaluation_role: string;
}

export default function AssessmentsScreen() {
  const { me } = useAdmin();
  const canCreateTemplate = me.permissions.includes("assessment:author");
  const canCreateInstance = me.permissions.includes("assessment:run");
  const canViewTemplates =
    me.permissions.includes("assessment:author") || me.permissions.includes("assessment:analyse");
  const canViewInstances = me.permissions.includes("assessment:run");

  const [tab, setTab] = useState<"templates" | "instances">("templates");

  const [templates, setTemplates] = useState<TemplateItem[] | null>(null);
  const [templatesError, setTemplatesError] = useState<string | null>(null);

  const [instances, setInstances] = useState<InstanceItem[] | null>(null);
  const [instancesError, setInstancesError] = useState<string | null>(null);

  async function loadTemplates() {
    const resp = await authedFetch("/api/bff/assessment-platform/templates");
    if (!resp.ok) {
      setTemplatesError(await readError(resp, "Templates could not be loaded."));
      setTemplates([]);
      return;
    }
    setTemplates((await resp.json()).items);
    setTemplatesError(null);
  }

  async function loadInstances() {
    const resp = await authedFetch("/api/bff/assessment-platform/instances");
    if (!resp.ok) {
      setInstancesError(await readError(resp, "Instances could not be loaded."));
      setInstances([]);
      return;
    }
    setInstances((await resp.json()).items);
    setInstancesError(null);
  }

  useEffect(() => {
    void (async () => {
      if (canViewTemplates) {
        await loadTemplates();
      }
      if (canViewInstances) {
        await loadInstances();
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const templateCount = templates?.length ?? 0;
  const instanceCount = instances?.length ?? 0;

  return (
    <div className="dash">
      <div className="dash-top">
        <div>
          <p className="eyebrow">Assess</p>
          <h1>Assessments</h1>
        </div>
        {canCreateTemplate ? (
          <a className="btn btn--primary" href="/admin/assessments/new-template">
            New template
          </a>
        ) : null}
      </div>

      {templatesError ? (
        <div className="callout callout--warn" role="alert">
          <p style={{ fontSize: "0.8125rem" }}>{templatesError}</p>
        </div>
      ) : null}

      {instancesError ? (
        <div className="callout callout--warn" role="alert">
          <p style={{ fontSize: "0.8125rem" }}>{instancesError}</p>
        </div>
      ) : null}

      {canViewTemplates && (
        <>
          <dl className="stats">
            <div className="stat">
              <dt>Templates</dt>
              <dd>{templates?.length ?? "—"}</dd>
            </div>
            <div className="stat">
              <dt>Instances</dt>
              <dd>{instances?.length ?? "—"}</dd>
            </div>
          </dl>

          <div style={{ marginBottom: "1.5rem", borderBottom: "1px solid var(--border)" }}>
            <div style={{ display: "flex", gap: "1rem" }}>
              <button
                type="button"
                onClick={() => setTab("templates")}
                style={{
                  padding: "0.75rem 1rem",
                  borderBottom: tab === "templates" ? "2px solid var(--brand)" : "none",
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  fontWeight: tab === "templates" ? 600 : 400,
                  color: tab === "templates" ? "var(--text)" : "var(--muted)",
                }}
              >
                Templates
              </button>
              <button
                type="button"
                onClick={() => setTab("instances")}
                style={{
                  padding: "0.75rem 1rem",
                  borderBottom: tab === "instances" ? "2px solid var(--brand)" : "none",
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  fontWeight: tab === "instances" ? 600 : 400,
                  color: tab === "instances" ? "var(--text)" : "var(--muted)",
                }}
              >
                Instances
              </button>
            </div>
          </div>

          {tab === "templates" && (
            <div className="tablewrap">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Template</th>
                    <th scope="col">Kind</th>
                    <th scope="col">Mode</th>
                    <th scope="col">Status</th>
                    <th scope="col" />
                  </tr>
                </thead>
                <tbody>
                  {templates === null ? (
                    <tr>
                      <td colSpan={5} style={{ color: "var(--faint)" }}>
                        Loading…
                      </td>
                    </tr>
                  ) : null}
                  {templates !== null && templates.length === 0 ? (
                    <tr>
                      <td colSpan={5} style={{ color: "var(--muted)" }}>
                        No templates yet.
                        {canCreateTemplate && ' "New template" to create one.'}
                      </td>
                    </tr>
                  ) : null}
                  {(templates ?? []).map((template) => (
                    <tr key={template.id}>
                      <td>
                        <b>{template.title}</b>
                        <div style={{ fontSize: "0.6875rem", color: "var(--faint)" }}>
                          {template.slug}
                        </div>
                      </td>
                      <td>{template.kind}</td>
                      <td>{template.response_mode}</td>
                      <td>
                        <span className={`tag tag--${template.status === "draft" ? "mute" : "success"}`}>
                          {template.status}
                        </span>
                      </td>
                      <td />
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {tab === "instances" && canViewInstances && (
            <div className="tablewrap">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Instance</th>
                    <th scope="col">Role</th>
                    <th scope="col">Status</th>
                    <th scope="col" />
                  </tr>
                </thead>
                <tbody>
                  {instances === null ? (
                    <tr>
                      <td colSpan={4} style={{ color: "var(--faint)" }}>
                        Loading…
                      </td>
                    </tr>
                  ) : null}
                  {instances !== null && instances.length === 0 ? (
                    <tr>
                      <td colSpan={4} style={{ color: "var(--muted)" }}>
                        No instances yet.
                        {canCreateInstance && ' "New instance" to create one.'}
                      </td>
                    </tr>
                  ) : null}
                  {(instances ?? []).map((instance) => (
                    <tr key={instance.id}>
                      <td>
                        <b>{instance.title}</b>
                      </td>
                      <td>{instance.evaluation_role}</td>
                      <td>
                        <span className={`tag tag--${instance.status === "draft" ? "mute" : "success"}`}>
                          {instance.status}
                        </span>
                      </td>
                      <td />
                    </tr>
                  ))}
                </tbody>
              </table>

              {canCreateInstance && (
                <div style={{ marginTop: "1.5rem", paddingTop: "1.5rem", borderTop: "1px solid var(--border)" }}>
                  <a className="btn btn--primary" href="/admin/assessments/new-instance">
                    New instance
                  </a>
                </div>
              )}
            </div>
          )}
        </>
      )}

      {!canViewTemplates && !canViewInstances && (
        <div style={{ color: "var(--muted)", padding: "2rem" }}>
          You do not have permission to manage assessments.
        </div>
      )}
    </div>
  );
}
