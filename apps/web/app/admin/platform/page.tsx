"use client";

import { useCallback, useEffect, useState } from "react";

import { authedFetch } from "@/lib/authed-fetch";

import { useAdmin } from "../admin-context";

interface FeatureFlag {
  key: string;
  label: string;
  description: string;
  enabled: boolean;
}

interface ServiceStatus {
  name: string;
  ok: boolean;
  detail: string | null;
}

interface SystemHealth {
  api_version: string;
  environment: string;
  services: ServiceStatus[];
}

/**
 * Super-admin-only platform operations (`settings:manage` — seeded
 * since the baseline permission set, held only by super_admin; the
 * business-facing `admin` role never gets it). Deliberately separate
 * from /admin/settings (`tenant:manage`, branding/manager-visibility):
 * this page is deploy/maintenance/system-health concerns a tenant's own
 * administrator shouldn't be able to touch, or even know exist — the
 * sidebar itself hides this link from anyone without the permission
 * (app/admin/layout.tsx), this page's own check is the second,
 * server-enforced layer.
 */
export default function PlatformScreen() {
  const { me } = useAdmin();
  const canManage = me.permissions.includes("settings:manage");
  const [flags, setFlags] = useState<FeatureFlag[] | null>(null);
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!canManage) return;
    setError(null);
    const [flagsResp, healthResp] = await Promise.all([
      authedFetch("/api/bff/platform/feature-flags"),
      authedFetch("/api/bff/platform/system-health"),
    ]);
    if (!flagsResp.ok || !healthResp.ok) {
      setError("Could not load platform status. Try again shortly.");
      return;
    }
    setFlags((await flagsResp.json()).flags);
    setHealth(await healthResp.json());
  }, [canManage]);

  useEffect(() => {
    void load();
  }, [load]);

  async function toggle(flag: FeatureFlag) {
    setBusyKey(flag.key);
    setError(null);
    const resp = await authedFetch(`/api/bff/platform/feature-flags/${flag.key}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: !flag.enabled }),
    });
    setBusyKey(null);
    if (!resp.ok) {
      setError(`Could not update "${flag.label}". Try again shortly.`);
      return;
    }
    setFlags((await resp.json()).flags);
  }

  if (!canManage) {
    return (
      <div className="callout callout--warn">
        <b>You do not hold settings:manage</b>
        Platform operations — feature flags and system health — are limited to super
        administrators.
      </div>
    );
  }

  return (
    <div className="dash">
      <div className="dash-top">
        <div>
          <p className="eyebrow">Platform</p>
          <h1 className="serif">Platform operations</h1>
          <p style={{ fontSize: ".8125rem", color: "var(--muted)", marginTop: ".2rem" }}>
            Deploy, maintenance and feature-availability controls — not tenant configuration
            (that&rsquo;s Settings).
          </p>
        </div>
      </div>

      {error ? (
        <p className="callout callout--warn" role="alert">
          {error}
        </p>
      ) : null}

      {health ? (
        <div>
          <h2 className="serif" style={{ fontSize: "1.125rem", marginBottom: ".7rem" }}>
            System health
          </h2>
          <dl className="stats">
            <div className="stat">
              <dt>API version</dt>
              <dd className="mono" style={{ fontSize: "1rem" }}>
                {health.api_version}
              </dd>
            </div>
            <div className="stat">
              <dt>Web version</dt>
              <dd className="mono" style={{ fontSize: "1rem" }}>
                {process.env.NEXT_PUBLIC_APP_VERSION ?? "unknown"}
              </dd>
            </div>
            <div className="stat">
              <dt>Environment</dt>
              <dd style={{ fontSize: "1rem" }}>{health.environment}</dd>
            </div>
          </dl>
          <div className="rowlist" style={{ marginTop: ".7rem" }}>
            {health.services.map((svc) => (
              <div className="rowitem" key={svc.name}>
                <span
                  className={`tag ${svc.ok ? "tag--done" : "tag--stop"}`}
                  style={{ textTransform: "capitalize" }}
                >
                  {svc.ok ? "OK" : "Down"}
                </span>
                <span className="t" style={{ textTransform: "capitalize" }}>
                  {svc.name}
                </span>
                {svc.detail ? <span className="m mono">{svc.detail}</span> : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {flags ? (
        <div style={{ marginTop: "2rem" }}>
          <h2 className="serif" style={{ fontSize: "1.125rem", marginBottom: ".35rem" }}>
            Feature flags
          </h2>
          <p style={{ fontSize: ".8125rem", color: "var(--muted)", marginBottom: ".7rem" }}>
            Kill switches, not a staged rollout — turning one off refuses new attempts at that
            feature immediately, with no deploy and no maintenance window. Existing state (an
            active subscription, a confirmed booking) is never affected.
          </p>
          <div className="tablewrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Feature</th>
                  <th scope="col">Status</th>
                  <th scope="col"></th>
                </tr>
              </thead>
              <tbody>
                {flags.map((flag) => (
                  <tr key={flag.key}>
                    <td>
                      <b>{flag.label}</b>
                      <p style={{ fontSize: ".75rem", color: "var(--muted)", marginTop: ".15rem" }}>
                        {flag.description}
                      </p>
                    </td>
                    <td>
                      <span className={`tag ${flag.enabled ? "tag--done" : "tag--stop"}`}>
                        {flag.enabled ? "Enabled" : "Disabled"}
                      </span>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn--ghost"
                        disabled={busyKey === flag.key}
                        onClick={() => toggle(flag)}
                      >
                        {busyKey === flag.key ? "Saving…" : flag.enabled ? "Disable" : "Enable"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </div>
  );
}
