"use client";

import { useId, useState } from "react";

/**
 * Net revenue over time — the one thing the analytics dashboard could
 * not show, because every other figure it serves is a single aggregate
 * for the whole period.
 *
 * **Hand-rolled SVG rather than a chart library, deliberately.**
 * `docs/research/payment-analytics-dashboard.md` §7 chose recharts, and
 * the reasoning it gave was six distinct charts (three of them pies).
 * That premise did not survive contact with the page: the proportions
 * it wanted as pies are already drawn as `.bar` share rows with direct
 * labels and percentages, which is the better form for part-to-whole
 * anyway — a three-slice pie is harder to read than three bars, and a
 * two-slice pie is not a chart. What was genuinely missing was *trend*,
 * and that is one chart. One chart does not justify a charting
 * dependency in a frontend that has deliberately avoided component
 * libraries; six would have.
 *
 * Mark specs are fixed rather than taste: 2px line with round caps,
 * 8px end markers carrying a 2px surface ring so they stay legible
 * where they cross, a ~10% area wash under a single series, hairline
 * solid gridlines one step off the surface, and labels only on the
 * endpoint and the peak — never a number on every point.
 *
 * Currencies are never blended (the API returns one figure per currency
 * for exactly that reason), so each currency is its own line. The two
 * series colours are validated tokens, not picked by eye — see
 * `--series-1`/`--series-2` in globals.css.
 */

interface Money {
  currency: string;
  amount: string;
}

export interface RevenuePoint {
  bucket: string;
  label: string;
  amounts: Money[];
}

interface Props {
  points: RevenuePoint[];
  currencies: string[];
  granularity: string;
}

// A fixed viewBox scaled by CSS: the chart fills its column at any width
// without a resize observer, and the geometry below can stay in one
// coordinate space.
const W = 720;
const H = 240;
const PAD = { top: 16, right: 16, bottom: 28, left: 56 };
const PLOT_W = W - PAD.left - PAD.right;
const PLOT_H = H - PAD.top - PAD.bottom;

const SERIES_VARS = ["var(--series-1)", "var(--series-2)"];

function niceCeiling(value: number): number {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  return Math.ceil(value / magnitude) * magnitude;
}

function compact(value: number): string {
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (Math.abs(value) >= 1_000) return `${Math.round(value / 1_000)}k`;
  return String(Math.round(value));
}

export default function RevenueChart({ points, currencies, granularity }: Props) {
  const titleId = useId();
  const [hover, setHover] = useState<number | null>(null);

  if (points.length === 0 || currencies.length === 0) {
    return (
      <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
        No payments were recorded in this period, so there is no revenue line to draw.
      </p>
    );
  }

  const series = currencies.slice(0, SERIES_VARS.length).map((currency, index) => ({
    currency,
    colour: SERIES_VARS[index],
    values: points.map((p) => Number(p.amounts.find((a) => a.currency === currency)?.amount ?? 0)),
  }));

  const peak = Math.max(0, ...series.flatMap((s) => s.values));
  const top = niceCeiling(peak);
  // A single point has no line to draw between anything; centring it
  // beats dividing by zero.
  const x = (i: number) =>
    PAD.left + (points.length === 1 ? PLOT_W / 2 : (i / (points.length - 1)) * PLOT_W);
  const y = (v: number) => PAD.top + PLOT_H - (top === 0 ? 0 : (v / top) * PLOT_H);

  const ticks = [0, 0.5, 1].map((f) => f * top);
  // Enough labels to orient, never one per bucket.
  const labelEvery = Math.max(1, Math.ceil(points.length / 6));

  return (
    <figure style={{ margin: 0 }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        role="img"
        aria-labelledby={titleId}
        style={{ display: "block", overflow: "visible" }}
        onMouseLeave={() => setHover(null)}
      >
        <title id={titleId}>
          Net revenue per {granularity}
          {series.map((s) => `, ${s.currency}`).join("")}
        </title>

        {ticks.map((tick) => (
          <g key={tick}>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={y(tick)}
              y2={y(tick)}
              stroke="var(--chart-grid)"
              strokeWidth={1}
            />
            <text
              x={PAD.left - 8}
              y={y(tick) + 4}
              textAnchor="end"
              fontSize={10}
              fill="var(--muted)"
              style={{ fontVariantNumeric: "tabular-nums" }}
            >
              {compact(tick)}
            </text>
          </g>
        ))}

        {points.map((p, i) =>
          i % labelEvery === 0 || i === points.length - 1 ? (
            <text
              key={p.bucket}
              x={x(i)}
              y={H - 8}
              textAnchor={i === points.length - 1 ? "end" : "middle"}
              fontSize={10}
              fill="var(--muted)"
            >
              {p.label}
            </text>
          ) : null,
        )}

        {series.map((s, si) => {
          const line = s.values.map((v, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(v)}`).join(" ");
          const peakIndex = s.values.indexOf(Math.max(...s.values));
          const lastIndex = s.values.length - 1;
          return (
            <g key={s.currency}>
              {/* A wash only under a lone series: two overlapping fills
                  muddy each other and stop reading as either. */}
              {series.length === 1 ? (
                <path
                  d={`${line} L${x(lastIndex)},${y(0)} L${x(0)},${y(0)} Z`}
                  fill={s.colour}
                  opacity={0.1}
                />
              ) : null}
              <path
                d={line}
                fill="none"
                stroke={s.colour}
                strokeWidth={2}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
              {[peakIndex, lastIndex]
                .filter((i, idx, all) => all.indexOf(i) === idx)
                .map((i) => (
                  <circle
                    key={`${s.currency}-${i}`}
                    cx={x(i)}
                    cy={y(s.values[i])}
                    r={4}
                    fill={s.colour}
                    stroke="var(--surface)"
                    strokeWidth={2}
                  />
                ))}
              <text
                x={x(lastIndex)}
                y={y(s.values[lastIndex]) - 10}
                textAnchor="end"
                fontSize={10}
                fill="var(--ink-2)"
                style={{ fontVariantNumeric: "tabular-nums" }}
              >
                {s.currency} {compact(s.values[lastIndex])}
              </text>
              {si === 0 && peakIndex !== lastIndex ? (
                <text
                  x={x(peakIndex)}
                  y={y(s.values[peakIndex]) - 10}
                  textAnchor="middle"
                  fontSize={10}
                  fill="var(--ink-2)"
                  style={{ fontVariantNumeric: "tabular-nums" }}
                >
                  {compact(s.values[peakIndex])}
                </text>
              ) : null}
            </g>
          );
        })}

        {hover !== null ? (
          <line
            x1={x(hover)}
            x2={x(hover)}
            y1={PAD.top}
            y2={PAD.top + PLOT_H}
            stroke="var(--rule-2)"
            strokeWidth={1}
          />
        ) : null}

        {/* Hit targets wider than the marks — a 4px dot is far too small
            to aim at, so each bucket owns a full-height band. */}
        {points.map((p, i) => (
          <rect
            key={`hit-${p.bucket}`}
            x={x(i) - PLOT_W / Math.max(points.length, 1) / 2}
            y={PAD.top}
            width={PLOT_W / Math.max(points.length, 1)}
            height={PLOT_H}
            fill="transparent"
            onMouseEnter={() => setHover(i)}
          />
        ))}
      </svg>

      <figcaption
        aria-live="polite"
        className="mt-1"
        style={{ fontSize: "0.75rem", color: "var(--muted)" }}
      >
        {hover === null ? (
          <>
            Net revenue per {granularity} — payments received less refunds, from the ledger.
            {series.length > 1 ? " One line per currency; never summed across them." : null}
          </>
        ) : (
          <>
            <strong>{points[hover].label}</strong>
            {series.map((s) => (
              <span key={s.currency} style={{ marginLeft: "0.75rem" }}>
                <span
                  aria-hidden="true"
                  style={{
                    display: "inline-block",
                    width: 8,
                    height: 8,
                    borderRadius: 999,
                    background: s.colour,
                    marginRight: 4,
                  }}
                />
                {s.currency} {s.values[hover].toLocaleString("en-ZA")}
              </span>
            ))}
          </>
        )}
      </figcaption>

      {series.length > 1 ? (
        <ul
          className="mt-1"
          style={{
            display: "flex",
            gap: "1rem",
            listStyle: "none",
            padding: 0,
            fontSize: "0.75rem",
            color: "var(--ink-2)",
          }}
        >
          {series.map((s) => (
            <li key={s.currency}>
              <span
                aria-hidden="true"
                style={{
                  display: "inline-block",
                  width: 10,
                  height: 2,
                  background: s.colour,
                  marginRight: 6,
                  verticalAlign: "middle",
                }}
              />
              {s.currency}
            </li>
          ))}
        </ul>
      ) : null}

      {/* The same numbers, readable without seeing the line at all. */}
      <details className="mt-2">
        <summary style={{ fontSize: "0.75rem", color: "var(--muted)", cursor: "pointer" }}>
          Show these figures as a table
        </summary>
        <div className="table-wrap mt-1">
          <table>
            <thead>
              <tr>
                <th scope="col">Period</th>
                {series.map((s) => (
                  <th key={s.currency} scope="col">
                    {s.currency}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {points.map((p, i) => (
                <tr key={p.bucket}>
                  <td>{p.label}</td>
                  {series.map((s) => (
                    <td key={s.currency} style={{ fontVariantNumeric: "tabular-nums" }}>
                      {s.values[i].toLocaleString("en-ZA")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
