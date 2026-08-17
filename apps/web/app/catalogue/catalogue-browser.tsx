"use client";

/**
 * The prototype's screen 4 body: `.cat` = `.facets` beside the result
 * header, `.course-grid` and the team `.callout`.
 *
 * Filtering happens here rather than on the API because `GET
 * /public/courses` returns the whole published catalogue in one call and
 * has no filter parameters — so the facet counts are exact, and toggling
 * a facet costs no round trip.
 *
 * Two rules the dev data forces:
 *   - a course with `topic`/`level`/`format` null is *unspecified*, not
 *     excluded: it still appears whenever that facet has no selection.
 *   - selections are OR within a facet, AND across facets, and each
 *     option's count is computed against the *other* facets' selections
 *     so the number always says what picking it would give you.
 */
import Link from "next/link";
import { useMemo, useState } from "react";

import { CourseCard } from "@/app/catalogue/course-card";
import { formatFormat, formatLevel } from "@/lib/format";
import type { PublicCourse } from "@/lib/server-api";

type FacetKey = "topic" | "format" | "includes" | "level";

interface FacetOption {
  value: string;
  label: string;
  matches: (course: PublicCourse) => boolean;
}

type Selection = Record<FacetKey, string[]>;

const EMPTY_SELECTION: Selection = { topic: [], format: [], includes: [], level: [] };

const FORMAT_VALUES = ["self_paced", "blended", "live_cohort"];
const LEVEL_VALUES = ["introductory", "intermediate", "executive"];

const INCLUDES_OPTIONS: FacetOption[] = [
  { value: "certificate", label: "Certificate", matches: (c) => c.has_certificate },
  { value: "workshop", label: "Live workshop", matches: (c) => c.includes_workshop },
  { value: "cpd", label: "CPD points", matches: (c) => Boolean(c.cpd_points) },
];

// 1 300+ rows exist in the development database. The grid renders a page
// at a time so a filter that matches everything does not ship a thousand
// cards into the document; the count in the header is always the true
// total, not the number drawn.
const PAGE_SIZE = 24;

type SortKey = "relevant" | "newest" | "price";

export interface CatalogueBrowserProps {
  courses: PublicCourse[];
  initialTopic: string | null;
  initialLevel: string | null;
}

export function CatalogueBrowser({ courses, initialTopic, initialLevel }: CatalogueBrowserProps) {
  const topics = useMemo(() => {
    const seen = new Set<string>();
    for (const course of courses) if (course.topic) seen.add(course.topic);
    return [...seen].sort((a, b) => a.localeCompare(b));
  }, [courses]);

  const facets = useMemo<Array<{ key: FacetKey; title: string; options: FacetOption[] }>>(
    () => [
      {
        key: "topic",
        title: "Topic",
        options: topics.map((topic) => ({
          value: topic,
          label: topic,
          matches: (course: PublicCourse) => course.topic === topic,
        })),
      },
      {
        key: "format",
        title: "Format",
        options: FORMAT_VALUES.map((value) => ({
          value,
          label: formatFormat(value) ?? value,
          matches: (course: PublicCourse) => course.format === value,
        })),
      },
      { key: "includes", title: "Includes", options: INCLUDES_OPTIONS },
      {
        key: "level",
        title: "Level",
        options: LEVEL_VALUES.map((value) => ({
          value,
          label: formatLevel(value) ?? value,
          matches: (course: PublicCourse) => course.level === value,
        })),
      },
    ],
    [topics],
  );

  const [selected, setSelected] = useState<Selection>(() => ({
    ...EMPTY_SELECTION,
    topic: initialTopic && topics.includes(initialTopic) ? [initialTopic] : [],
    level: initialLevel && LEVEL_VALUES.includes(initialLevel) ? [initialLevel] : [],
  }));
  const [sort, setSort] = useState<SortKey>("relevant");
  const [visible, setVisible] = useState(PAGE_SIZE);

  function toggle(key: FacetKey, value: string) {
    setVisible(PAGE_SIZE);
    setSelected((current) => {
      const values = current[key];
      return {
        ...current,
        [key]: values.includes(value) ? values.filter((v) => v !== value) : [...values, value],
      };
    });
  }

  /** Courses matching every facet except `skip` — the base both for the
   * result list (skip nothing) and for each facet's own counts. */
  function matching(selection: Selection, skip?: FacetKey): PublicCourse[] {
    return courses.filter((course) =>
      facets.every(({ key, options }) => {
        if (key === skip) return true;
        const chosen = selection[key];
        if (chosen.length === 0) return true;
        return options.some((option) => chosen.includes(option.value) && option.matches(course));
      }),
    );
  }

  const results = useMemo(() => {
    const matched = matching(selected);
    const sorted = [...matched];
    if (sort === "newest") {
      // Course ids are UUIDv7 — lexicographic order is creation order.
      sorted.sort((a, b) => b.id.localeCompare(a.id));
    } else if (sort === "price") {
      sorted.sort((a, b) => {
        const left = a.price ? Number(a.price.unit_amount) : Number.POSITIVE_INFINITY;
        const right = b.price ? Number(b.price.unit_amount) : Number.POSITIVE_INFINITY;
        return left - right;
      });
    }
    return sorted;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courses, facets, selected, sort]);

  const counts = useMemo(() => {
    const table: Record<string, number> = {};
    for (const { key, options } of facets) {
      const base = matching(selected, key);
      for (const option of options) {
        table[`${key}:${option.value}`] = base.filter((course) => option.matches(course)).length;
      }
    }
    return table;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courses, facets, selected]);

  const activeTopic = selected.topic.length === 1 ? selected.topic[0] : null;
  const activeLevel = selected.level.length === 1 ? formatLevel(selected.level[0]) : null;
  const heading = [activeTopic, activeLevel].filter(Boolean).join(" · ") || "All programmes";
  const total = results.length;
  const anySelected = facets.some(({ key }) => selected[key].length > 0);

  return (
    <div className="cat">
      <div className="facets">
        {facets.map(({ key, title, options }) => (
          <div className="facet" key={key}>
            <h4 id={`facet-${key}`}>{title}</h4>
            <ul aria-labelledby={`facet-${key}`}>
              {options.map((option) => {
                const on = selected[key].includes(option.value);
                return (
                  <li key={option.value} className={on ? "on" : undefined}>
                    <button type="button" aria-pressed={on} onClick={() => toggle(key, option.value)}>
                      <i aria-hidden="true" />
                      {option.label}
                      <span>{counts[`${key}:${option.value}`] ?? 0}</span>
                    </button>
                  </li>
                );
              })}
              {options.length === 0 ? (
                <li>
                  <span style={{ color: "var(--faint)" }}>No topics yet</span>
                </li>
              ) : null}
            </ul>
          </div>
        ))}
      </div>

      <div>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "baseline",
            gap: "1rem",
            flexWrap: "wrap",
            marginBottom: "1.1rem",
          }}
        >
          <div>
            <h1 className="serif" style={{ fontSize: "1.5rem" }}>
              {heading}
            </h1>
            <p style={{ fontSize: "0.8125rem", color: "var(--muted)", marginTop: "0.2rem" }}>
              {total === 1 ? "1 programme matches your filters" : `${total} programmes match your filters`}
            </p>
          </div>
          <label style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <span style={{ fontSize: "0.75rem", color: "var(--muted)" }}>Sort</span>
            <select
              style={{ width: "auto" }}
              value={sort}
              onChange={(event) => setSort(event.target.value as SortKey)}
            >
              <option value="relevant">Most relevant</option>
              <option value="newest">Newest</option>
              <option value="price">Price, low to high</option>
            </select>
          </label>
        </div>

        {total === 0 ? (
          <p style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
            Nothing matches that combination.{" "}
            {anySelected ? (
              <button
                type="button"
                className="btn btn--quiet"
                onClick={() => {
                  setSelected(EMPTY_SELECTION);
                  setVisible(PAGE_SIZE);
                }}
              >
                Clear the filters
              </button>
            ) : null}
          </p>
        ) : (
          <>
            <div className="course-grid">
              {results.slice(0, visible).map((course) => (
                <CourseCard key={course.id} course={course} />
              ))}
            </div>
            {visible < total ? (
              <div style={{ marginTop: "1.25rem" }}>
                <button
                  type="button"
                  className="btn btn--ghost"
                  onClick={() => setVisible((count) => count + PAGE_SIZE)}
                >
                  Show more programmes
                </button>
              </div>
            ) : null}
          </>
        )}

        <div className="callout" style={{ marginTop: "1.5rem" }}>
          <b>Buying for a team?</b>
          Seat bundles from five learners include a manager dashboard, invoice or EFT payment and
          purchase-order support.{" "}
          <Link href="/organisations" style={{ color: "var(--brand-ink)" }}>
            Talk to us about an organisation account
          </Link>
          .
        </div>
      </div>
    </div>
  );
}
