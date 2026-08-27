"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { authedFetch } from "@/lib/authed-fetch";

import { useAdmin } from "../admin-context";

interface SurveyListItem {
  id: string;
  title: string;
  response_mode: "identified" | "anonymous";
  minimum_group_size: number;
  question_count: number;
  evaluation_role: "standalone" | "pre" | "post";
  pair_id: string | null;
}

const MODE_LABEL: Record<string, string> = {
  identified: "Identified",
  anonymous: "Anonymous",
};

/**
 * P9/REQ-ASSESS-06: the read side of the anonymous-survey story. Survey
 * authoring already existed (course wizard's lesson-activity panel
 * creates/attaches surveys); nothing before this page ever read a
 * response back — this list is where "view results" starts.
 */
export default function SurveysScreen() {
  const { me } = useAdmin();
  const canView = me.permissions.includes("course:edit");

  const [surveys, setSurveys] = useState<SurveyListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!canView) return;
    authedFetch("/api/bff/surveys")
      .then(async (resp) => {
        if (!resp.ok) {
          setError("Surveys could not be loaded.");
          return;
        }
        setSurveys((await resp.json()).items);
      })
      .catch(() => setError("Surveys could not be loaded."));
  }, [canView]);

  if (!canView) {
    return (
      <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
        Your role does not hold <span className="mono">course:edit</span>.
      </p>
    );
  }

  return (
    <>
      <div className="dash-top">
        <div>
          <h1>Surveys</h1>
          <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
            Every survey authored across every course. Results stay hidden until enough people
            have responded.
          </p>
        </div>
      </div>

      {error ? (
        <div className="callout callout--warn mt-3" role="status">
          {error}
        </div>
      ) : null}

      {surveys === null && !error ? (
        <p className="mt-3" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
          Loading…
        </p>
      ) : null}

      {surveys !== null ? (
        surveys.length === 0 ? (
          <p className="mt-3" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
            No surveys have been authored yet.
          </p>
        ) : (
          <div className="table-wrap mt-3">
            <table>
              <thead>
                <tr>
                  <th scope="col">Survey</th>
                  <th scope="col">Mode</th>
                  <th scope="col">Stage</th>
                  <th scope="col">Questions</th>
                  <th scope="col">Minimum group size</th>
                  <th scope="col"></th>
                </tr>
              </thead>
              <tbody>
                {surveys.map((s) => (
                  <tr key={s.id}>
                    <td>{s.title}</td>
                    <td>
                      <span className="tag">{MODE_LABEL[s.response_mode] ?? s.response_mode}</span>
                    </td>
                    <td>
                      <span className="tag">
                        {s.evaluation_role === "standalone"
                          ? "Standalone"
                          : s.evaluation_role === "pre"
                            ? "Pre-course"
                            : "Post-course"}
                      </span>
                    </td>
                    <td style={{ fontVariantNumeric: "tabular-nums" }}>{s.question_count}</td>
                    <td style={{ fontVariantNumeric: "tabular-nums" }}>{s.minimum_group_size}</td>
                    <td>
                      <Link href={`/admin/surveys/${s.id}/results`}>View results →</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      ) : null}
    </>
  );
}
