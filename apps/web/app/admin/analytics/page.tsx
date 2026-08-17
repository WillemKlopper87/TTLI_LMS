"use client";

import { useCallback, useEffect, useState } from "react";

import { getAccessToken } from "@/lib/session";

import { useAdmin } from "../admin-context";

/**
 * Payment & revenue analytics (docs/research/payment-analytics-
 * dashboard.md). Read-only: two server-computed reports over a shared
 * timeframe, plus their CSV exports. `analytics:view`-gated server-side,
 * mirrored here only to hide a screen a caller can't use — the same
 * convention every other admin screen follows.
 *
 * Money is never summed across currencies (the API returns one figure
 * per currency for exactly that reason), so every money cell renders one
 * line per currency present rather than a blended total.
 */

interface Money {
  currency: string;
  amount: string;
}

interface Period {
  preset: string | null;
  from: string;
  to: string;
}

interface RevenueSummary {
  period: Period;
  paid_vs_waiting: {
    paid: number;
    awaiting_payment: number;
    did_not_convert: number;
    total_users: number;
  };
  payment_methods: { provider: string; payment_count: number; amount: Money[] }[];
  actual_revenue: Money[];
  payments_received: Money[];
  refunds_issued: Money[];
  predicted_revenue: {
    pipeline: Money[];
    pipeline_order_count: number;
    subscription_renewals: Money[];
    subscription_renewal_count: number;
    total: Money[];
  };
}

interface Registrations {
  period: Period;
  total_registered: number;
  by_package: { package_label: string; user_count: number }[];
  by_organisation: {
    organisation_id: string | null;
    organisation_name: string;
    user_count: number;
  }[];
}

const PRESETS: { value: string; label: string }[] = [
  { value: "last_24h", label: "Last 24 hours" },
  { value: "last_7d", label: "Last 7 days" },
  { value: "last_30d", label: "Last 30 days" },
  { value: "last_3m", label: "Last 3 months" },
  { value: "last_6m", label: "Last 6 months" },
  { value: "last_1y", label: "Last year" },
];

const PROVIDER_LABELS: Record<string, string> = {
  card: "Card",
  eft: "EFT",
  po: "Purchase order",
};

function formatMoney(money: Money[]): string {
  if (money.length === 0) return "—";
  return money
    .map((m) => {
      const amount = Number(m.amount);
      const symbol = m.currency === "ZAR" ? "R" : `${m.currency} `;
      return `${symbol}${amount.toLocaleString("en-ZA", {
        minimumFractionDigits: amount % 1 === 0 ? 0 : 2,
        maximumFractionDigits: 2,
      })}`;
    })
    .join(" · ");
}

function formatDay(iso: string): string {
  return new Date(iso).toLocaleDateString("en-ZA", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

/** A share bar — the prototype's `.bar`, one row per slice. */
function ShareRow({
  label,
  value,
  total,
  tone,
}: {
  label: string;
  value: number;
  total: number;
  tone?: "done";
}) {
  const pct = total > 0 ? Math.round((value / total) * 100) : 0;
  return (
    <div className="rowitem">
      <span className="t">{label}</span>
      <span
        className={tone === "done" ? "bar minibar bar--done" : "bar minibar"}
        style={{ flex: "1 1 160px" }}
      >
        <i style={{ width: `${pct}%` }} />
      </span>
      <span className="m mono">
        {value.toLocaleString("en-ZA")} · {pct}%
      </span>
    </div>
  );
}

export default function AnalyticsScreen() {
  const { me } = useAdmin();
  const canView = me.permissions.includes("analytics:view");

  const [preset, setPreset] = useState("last_30d");
  const [revenue, setRevenue] = useState<RevenueSummary | null>(null);
  const [registrations, setRegistrations] = useState<Registrations | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!canView) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    const token = getAccessToken();
    const headers = { Authorization: `Bearer ${token}` };
    try {
      const [r1, r2] = await Promise.all([
        fetch(`/api/bff/analytics/revenue-summary?preset=${preset}`, { headers }),
        fetch(`/api/bff/analytics/registrations?preset=${preset}`, { headers }),
      ]);
      if (!r1.ok || !r2.ok) {
        setError("Could not load the report. Try again shortly.");
        setLoading(false);
        return;
      }
      setRevenue(await r1.json());
      setRegistrations(await r2.json());
    } catch {
      setError("Could not load the report. Try again shortly.");
    }
    setLoading(false);
  }, [canView, preset]);

  useEffect(() => {
    void load();
  }, [load]);

  function exportUrl(report: "revenue-summary" | "registrations"): string {
    return `/api/bff/analytics/${report}/export.csv?preset=${preset}`;
  }

  async function download(report: "revenue-summary" | "registrations") {
    // The BFF needs the bearer, so the file is fetched rather than linked.
    const resp = await fetch(exportUrl(report), {
      headers: { Authorization: `Bearer ${getAccessToken()}` },
    });
    if (!resp.ok) {
      setError("The export could not be generated.");
      return;
    }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${report}-${preset}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  if (!canView) {
    return (
      <div className="callout callout--warn">
        <b>You do not hold analytics:view</b>
        Revenue and registration reporting is limited to administrators and finance.
      </div>
    );
  }

  const pvw = revenue?.paid_vs_waiting;
  const totalPayments = revenue?.payment_methods.reduce((n, p) => n + p.payment_count, 0) ?? 0;

  return (
    <div className="dash">
      <div className="dash-top">
        <div>
          <p className="eyebrow">Finance</p>
          <h1 className="serif">Payment &amp; revenue analytics</h1>
          {revenue ? (
            <p style={{ fontSize: ".8125rem", color: "var(--muted)", marginTop: ".2rem" }}>
              {formatDay(revenue.period.from)} — {formatDay(revenue.period.to)}
            </p>
          ) : null}
        </div>
        <div style={{ display: "flex", gap: ".5rem", alignItems: "center", flexWrap: "wrap" }}>
          <label className="field" style={{ margin: 0 }}>
            <span className="eyebrow">Timeframe</span>
            <select
              className="input"
              value={preset}
              onChange={(e) => setPreset(e.target.value)}
              style={{ width: "auto" }}
            >
              {PRESETS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {error ? (
        <p className="callout callout--warn" role="alert">
          {error}
        </p>
      ) : null}
      {loading ? <p style={{ color: "var(--muted)" }}>Loading the report…</p> : null}

      {revenue ? (
        <>
          <dl className="stats">
            <div className="stat">
              <dt>Actual revenue</dt>
              <dd>{formatMoney(revenue.actual_revenue)}</dd>
            </div>
            <div className="stat">
              <dt>Payments received</dt>
              <dd>{formatMoney(revenue.payments_received)}</dd>
            </div>
            <div className="stat">
              <dt>Refunds issued</dt>
              <dd>{formatMoney(revenue.refunds_issued)}</dd>
            </div>
            <div className="stat">
              <dt>Predicted (pipeline)</dt>
              <dd>{formatMoney(revenue.predicted_revenue.total)}</dd>
            </div>
          </dl>

          <div className="callout">
            <b>Figures are never blended across currencies</b>
            Each total lists one amount per currency. &ldquo;Actual revenue&rdquo; is invoiced and
            fulfilled; &ldquo;predicted&rdquo; is {revenue.predicted_revenue.pipeline_order_count}{" "}
            order(s) still awaiting payment plus{" "}
            {revenue.predicted_revenue.subscription_renewal_count} scheduled renewal(s) — not a
            forecast model.
          </div>

          <div>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "baseline",
                gap: "1rem",
                marginBottom: ".7rem",
              }}
            >
              <h2 className="serif" style={{ fontSize: "1.125rem" }}>
                Buyers in this period
              </h2>
              <button type="button" className="btn btn--quiet" onClick={() => download("revenue-summary")}>
                Export CSV
              </button>
            </div>
            <div className="rowlist">
              {pvw ? (
                <>
                  <ShareRow label="Paid" value={pvw.paid} total={pvw.total_users} tone="done" />
                  <ShareRow
                    label="Awaiting payment"
                    value={pvw.awaiting_payment}
                    total={pvw.total_users}
                  />
                  <ShareRow
                    label="Did not convert"
                    value={pvw.did_not_convert}
                    total={pvw.total_users}
                  />
                </>
              ) : null}
            </div>
          </div>

          <div>
            <h2 className="serif" style={{ fontSize: "1.125rem", marginBottom: ".7rem" }}>
              How they paid
            </h2>
            <div className="tablewrap">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Method</th>
                    <th scope="col">Payments</th>
                    <th scope="col">Share</th>
                    <th scope="col">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {revenue.payment_methods.map((row) => {
                    const pct =
                      totalPayments > 0 ? Math.round((row.payment_count / totalPayments) * 100) : 0;
                    return (
                      <tr key={row.provider}>
                        <td>{PROVIDER_LABELS[row.provider] ?? row.provider}</td>
                        <td className="mono">{row.payment_count.toLocaleString("en-ZA")}</td>
                        <td>
                          <span className="bar minibar" style={{ display: "inline-block", width: 90 }}>
                            <i style={{ width: `${pct}%` }} />
                          </span>{" "}
                          <span className="mono" style={{ fontSize: ".6875rem" }}>
                            {pct}%
                          </span>
                        </td>
                        <td className="mono">{formatMoney(row.amount)}</td>
                      </tr>
                    );
                  })}
                  {revenue.payment_methods.length === 0 ? (
                    <tr>
                      <td colSpan={4} style={{ color: "var(--muted)" }}>
                        No payments in this period.
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </div>
        </>
      ) : null}

      {registrations ? (
        <div>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "baseline",
              gap: "1rem",
              marginBottom: ".7rem",
            }}
          >
            <h2 className="serif" style={{ fontSize: "1.125rem" }}>
              Registrations · {registrations.total_registered.toLocaleString("en-ZA")}
            </h2>
            <button type="button" className="btn btn--quiet" onClick={() => download("registrations")}>
              Export CSV
            </button>
          </div>

          <div className="tablewrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Package</th>
                  <th scope="col">Users</th>
                  <th scope="col">Share</th>
                </tr>
              </thead>
              <tbody>
                {registrations.by_package.map((row) => {
                  const pct =
                    registrations.total_registered > 0
                      ? Math.round((row.user_count / registrations.total_registered) * 100)
                      : 0;
                  return (
                    <tr key={row.package_label}>
                      <td>{row.package_label}</td>
                      <td className="mono">{row.user_count.toLocaleString("en-ZA")}</td>
                      <td>
                        <span className="bar minibar" style={{ display: "inline-block", width: 90 }}>
                          <i style={{ width: `${pct}%` }} />
                        </span>{" "}
                        <span className="mono" style={{ fontSize: ".6875rem" }}>
                          {pct}%
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {registrations.by_organisation.length > 0 ? (
            <div style={{ marginTop: "1.25rem" }}>
              <h3 className="serif" style={{ fontSize: "1rem", marginBottom: ".5rem" }}>
                By organisation
              </h3>
              <div className="rowlist">
                {registrations.by_organisation.map((row) => (
                  <div className="rowitem" key={row.organisation_id ?? row.organisation_name}>
                    <span className="t">{row.organisation_name}</span>
                    <span className="m mono">{row.user_count.toLocaleString("en-ZA")} users</span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
