"use client";

import { useId, useState } from "react";

/**
 * Pageviews over time — the trend the site-traffic panel was missing.
 * Same hand-rolled SVG approach and mark specs as revenue-chart.tsx (one
 * chart is not a reason to add a charting dependency), just a single
 * unitless series, so no per-currency handling.
 *
 * Renders at every volume, including zero: the API zero-fills every
 * bucket in the window, and an all-zero series draws as a flat baseline
 * with "0" labels rather than collapsing to a "nothing here" sentence —
 * a new tenant's panel should look designed, not broken (the Stripe
 * empty-state rule).
 */

export interface TrafficPoint {
  bucket: string;
  label: string;
  views: number;
}

const W = 720;
const H = 160;
const PAD = { top: 16, right: 16, bottom: 26, left: 40 };
const PLOT_W = W - PAD.left - PAD.right;
const PLOT_H = H - PAD.top - PAD.bottom;

function niceCeiling(value: number): number {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  return Math.ceil(value / magnitude) * magnitude;
}

export default function TrafficChart({
  points,
  granularity,
}: {
  points: TrafficPoint[];
  granularity: string;
}) {
  const titleId = useId();
  const [hover, setHover] = useState<number | null>(null);

  if (points.length === 0) {
    return (
      <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
        No trend to draw for this window.
      </p>
    );
  }

  const values = points.map((p) => p.views);
  const peak = Math.max(0, ...values);
  const top = niceCeiling(peak);
  const x = (i: number) =>
    PAD.left + (points.length === 1 ? PLOT_W / 2 : (i / (points.length - 1)) * PLOT_W);
  const y = (v: number) => PAD.top + PLOT_H - (v / top) * PLOT_H;
  const line = values.map((v, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(v)}`).join(" ");
  const peakIndex = values.indexOf(peak);
  const lastIndex = values.length - 1;
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
        <title id={titleId}>Pageviews per {granularity}</title>

        {[0, top].map((tick) => (
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
              {tick}
            </text>
          </g>
        ))}

        {points.map((p, i) =>
          i % labelEvery === 0 || i === lastIndex ? (
            <text
              key={p.bucket}
              x={x(i)}
              y={H - 6}
              textAnchor={i === lastIndex ? "end" : "middle"}
              fontSize={10}
              fill="var(--muted)"
            >
              {p.label}
            </text>
          ) : null,
        )}

        <path
          d={`${line} L${x(lastIndex)},${y(0)} L${x(0)},${y(0)} Z`}
          fill="var(--series-1)"
          opacity={0.1}
        />
        <path
          d={line}
          fill="none"
          stroke="var(--series-1)"
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        {[peakIndex, lastIndex]
          .filter((i, idx, all) => all.indexOf(i) === idx)
          .map((i) => (
            <circle
              key={i}
              cx={x(i)}
              cy={y(values[i])}
              r={4}
              fill="var(--series-1)"
              stroke="var(--surface)"
              strokeWidth={2}
            />
          ))}
        {peak > 0 && peakIndex !== lastIndex ? (
          <text
            x={x(peakIndex)}
            y={y(peak) - 10}
            textAnchor="middle"
            fontSize={10}
            fill="var(--ink-2)"
            style={{ fontVariantNumeric: "tabular-nums" }}
          >
            {peak.toLocaleString("en-ZA")}
          </text>
        ) : null}

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
        {points.map((p, i) => (
          <rect
            key={`hit-${p.bucket}`}
            x={x(i) - PLOT_W / points.length / 2}
            y={PAD.top}
            width={PLOT_W / points.length}
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
          <>Pageviews per {granularity}, every bucket in the window shown — a zero is a quiet {granularity}, not a gap.</>
        ) : (
          <>
            <strong>{points[hover].label}</strong>
            <span style={{ marginLeft: "0.75rem" }}>
              {points[hover].views.toLocaleString("en-ZA")} pageview
              {points[hover].views === 1 ? "" : "s"}
            </span>
          </>
        )}
      </figcaption>
    </figure>
  );
}
