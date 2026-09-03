"use client";

/**
 * The prototype's `.curriculum` block on screen 5.
 *
 * Two behaviours it has to keep: free-preview lessons (`is_preview`,
 * i.e. access_level="public") link straight to /preview/{lessonId}, and
 * everything past the second module is folded into one summary `.mod`
 * until the visitor asks for it — the prototype's "3–5 Holding the team,
 * reviewing, embedding / Show remaining modules" row.
 */
import Link from "next/link";
import { useState } from "react";

import { countLabel, formatDuration, joinMeta } from "@/lib/format";
import type { PublicModule } from "@/lib/server-api";

// Prototype glyphs, by lesson activity. An unknown/absent activity type
// gets the neutral bullet rather than a wrong icon.
const ACTIVITY_ICONS: Record<string, string> = {
  video: "▶",
  quiz: "▣",
  assignment: "✎",
  document: "☰",
  survey: "◔",
};

const VISIBLE_MODULES = 2;

function moduleMeta(module: PublicModule): string {
  return joinMeta([
    countLabel(module.lesson_count ?? module.lessons.length, "lesson"),
    formatDuration(module.estimated_minutes),
  ]);
}

function ModuleBlock({ module, index }: { module: PublicModule; index: number }) {
  return (
    <div className="mod">
      <div className="mod-head">
        <span>
          {index}&nbsp;&nbsp;{module.title}
        </span>
        <span>{moduleMeta(module)}</span>
      </div>
      <ul>
        {module.lessons.map((lesson) => (
          <li key={lesson.id}>
            <span className="ic" aria-hidden="true">
              {ACTIVITY_ICONS[lesson.blocks[0]?.block_type ?? "document"] ?? "●"}
            </span>
            <span>{lesson.title}</span>
            {lesson.is_preview ? (
              <Link className="tag tag--brand" href={`/preview/${lesson.id}`}>
                Preview
              </Link>
            ) : null}
            <span className="dur">{formatDuration(lesson.estimated_minutes) ?? ""}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export interface CurriculumProps {
  modules: PublicModule[];
  includesWorkshop: boolean;
}

export function Curriculum({ modules, includesWorkshop }: CurriculumProps) {
  const [expanded, setExpanded] = useState(false);

  const ordered = [...modules].sort((a, b) => a.position - b.position);
  const head = ordered.slice(0, VISIBLE_MODULES);
  const rest = ordered.slice(VISIBLE_MODULES);
  const shown = expanded ? ordered : head;

  const restLessons = rest.reduce((sum, m) => sum + (m.lesson_count ?? m.lessons.length), 0);
  const restMinutes = rest.reduce((sum, m) => sum + (m.estimated_minutes ?? 0), 0);
  const restTitles = rest.map((m) => m.title).join(", ");

  return (
    <div className="curriculum">
      {shown.map((module, index) => (
        <ModuleBlock key={module.id} module={module} index={index + 1} />
      ))}

      {rest.length > 0 && !expanded ? (
        <div className="mod">
          <div className="mod-head">
            <span>
              {/* A single collapsed module is "3", not "3–3". */}
              {VISIBLE_MODULES + 1 === ordered.length
                ? `${ordered.length}`
                : `${VISIBLE_MODULES + 1}–${ordered.length}`}
              &nbsp;&nbsp;{restTitles}
            </span>
            <span>{joinMeta([countLabel(restLessons, "lesson"), formatDuration(restMinutes)])}</span>
          </div>
          <ul>
            <li>
              <button
                type="button"
                onClick={() => setExpanded(true)}
                aria-expanded={false}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "0.7rem",
                  width: "100%",
                  font: "inherit",
                  color: "inherit",
                  background: "none",
                  border: 0,
                  padding: 0,
                  cursor: "pointer",
                  textAlign: "left",
                }}
              >
                <span className="ic" aria-hidden="true">
                  {"▾"}
                </span>
                <span>Show remaining modules</span>
              </button>
            </li>
          </ul>
        </div>
      ) : null}

      {includesWorkshop ? (
        <div className="mod">
          <div className="mod-head">
            <span>
              {ordered.length + 1}&nbsp;&nbsp;Live workshop
            </span>
            <span>Facilitated</span>
          </div>
          <ul>
            <li>
              <span className="ic" aria-hidden="true">
                {"●"}
              </span>
              <span>Cohort session with your facilitator, scheduled after enrolment</span>
            </li>
          </ul>
        </div>
      ) : null}
    </div>
  );
}
