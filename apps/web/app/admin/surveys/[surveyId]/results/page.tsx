"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { authedDownload } from "@/lib/authed-download";
import { authedFetch } from "@/lib/authed-fetch";

import { useAdmin } from "../../../admin-context";

interface ResultQuestion {
  question_id: string;
  question_type: string;
  prompt: string;
  options: { id: string; text: string }[];
  counts: Record<string, number> | null;
  response_count: number;
}

interface SurveyResults {
  survey_id: string;
  title: string;
  response_mode: "identified" | "anonymous";
  minimum_group_size: number;
  response_count: number;
  available: boolean;
  questions: ResultQuestion[];
  evaluation_role: "standalone" | "pre" | "post";
  pair_id: string | null;
}

interface SurveyDelta {
  pre_title: string;
  post_title: string;
  pre_response_count: number;
  post_response_count: number;
  pre_minimum_group_size: number;
  post_minimum_group_size: number;
  available: boolean;
  questions: {
    position: number;
    prompt: string;
    options: {
      text: string;
      pre_percent: number;
      post_percent: number;
      delta_percentage_points: number;
    }[];
  }[];
}

/**
 * P9/REQ-ASSESS-06: the aggregate view a survey's minimum_group_size
 * gates — this page shows exactly what `GET /surveys/{id}/results`
 * returns and nothing more. Below the threshold there is nothing to
 * reveal per question yet, not even a partial breakdown; the server
 * enforces that (services/survey.py::aggregate_results), this page just
 * renders whichever shape came back.
 */
export default function SurveyResultsScreen() {
  const { me } = useAdmin();
  const canView = me.permissions.includes("course:edit");
  const { surveyId } = useParams<{ surveyId: string }>();

  const [data, setData] = useState<SurveyResults | null>(null);
  const [delta, setDelta] = useState<SurveyDelta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    if (!canView) return;
    authedFetch(`/api/bff/surveys/${surveyId}/results`)
      .then(async (resp) => {
        if (!resp.ok) {
          setError("These results could not be loaded.");
          return;
        }
        const result: SurveyResults = await resp.json();
        setData(result);
        if (result.pair_id) {
          const deltaResp = await authedFetch(`/api/bff/surveys/${surveyId}/delta`);
          if (deltaResp.ok) setDelta(await deltaResp.json());
        }
      })
      .catch(() => setError("These results could not be loaded."));
  }, [canView, surveyId]);

  async function downloadCsv() {
    setDownloading(true);
    const ok = await authedDownload(
      `/api/bff/surveys/${surveyId}/results/export.csv`,
      `survey-${surveyId}-results.csv`,
    );
    setDownloading(false);
    if (!ok) setError("The CSV export could not be downloaded.");
  }

  if (!canView) {
    return (
      <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
        Your role does not hold <span className="mono">course:edit</span>.
      </p>
    );
  }

  if (error) {
    return (
      <div className="callout callout--warn" role="status">
        {error}
      </div>
    );
  }

  if (data === null) {
    return <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>Loading…</p>;
  }

  const progressPercent = Math.min(
    100,
    Math.round((data.response_count / Math.max(1, data.minimum_group_size)) * 100),
  );

  return (
    <>
      <div className="dash-top">
        <div>
          <p className="mb-1">
            <Link href="/admin/surveys" style={{ fontSize: "0.8125rem" }}>
              ← All surveys
            </Link>
          </p>
          <h1>{data.title}</h1>
          <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
            {data.response_mode === "anonymous" ? "Anonymous" : "Identified"} responses ·{" "}
            {data.response_count} received
          </p>
        </div>
        {data.available ? (
          <button type="button" className="btn btn--quiet" disabled={downloading} onClick={downloadCsv}>
            {downloading ? "Preparing…" : "Download CSV"}
          </button>
        ) : null}
      </div>

      {!data.available ? (
        <div className="callout mt-4">
          <b>Not enough responses yet</b>
          <p style={{ marginTop: "0.35rem" }}>
            {data.response_count} of {data.minimum_group_size} minimum responses received.
            Results stay hidden until enough people have answered — a small enough group can make
            an aggregate answer as identifying as a named one.
          </p>
          <span className="bar mt-2" style={{ display: "block" }}>
            <i style={{ width: `${progressPercent}%` }} />
          </span>
        </div>
      ) : (
        <div className="mt-4 flex flex-col gap-5">
          {data.questions.map((q) => (
            <div key={q.question_id} className="card p-4">
              <b style={{ fontSize: "0.9375rem" }}>{q.prompt}</b>

              {q.counts === null ? (
                <p className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
                  Free text · {q.response_count} response{q.response_count === 1 ? "" : "s"}{" "}
                  received. Reading individual answers isn&rsquo;t available yet — only how many
                  people answered.
                </p>
              ) : (
                <div className="mt-3 flex flex-col gap-2">
                  {q.options.map((option) => {
                    const count = q.counts?.[option.id] ?? 0;
                    const pct = q.response_count > 0 ? Math.round((count / q.response_count) * 100) : 0;
                    return (
                      <div key={option.id}>
                        <div
                          className="flex items-center justify-between"
                          style={{ fontSize: "0.8125rem" }}
                        >
                          <span>{option.text}</span>
                          <span className="mono" style={{ color: "var(--muted)" }}>
                            {count} · {pct}%
                          </span>
                        </div>
                        <span className="bar mt-1" style={{ display: "block" }}>
                          <i style={{ width: `${pct}%` }} />
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {delta ? (
        <section className="mt-8">
          <h2>Pre/post change</h2>
          {!delta.available ? (
            <div className="callout mt-3">
              Both stages must reach their privacy threshold before change is shown. Pre: {delta.pre_response_count}/
              {delta.pre_minimum_group_size}; post: {delta.post_response_count}/
              {delta.post_minimum_group_size}.
            </div>
          ) : (
            <div className="mt-3 flex flex-col gap-4">
              {delta.questions.map((question) => (
                <div key={question.position} className="card p-4">
                  <b>{question.prompt}</b>
                  <div className="mt-2 flex flex-col gap-2">
                    {question.options.map((option) => (
                      <div key={option.text} className="flex items-center justify-between gap-3">
                        <span>{option.text}</span>
                        <span className="mono" style={{ color: "var(--muted)" }}>
                          {option.pre_percent.toFixed(1)}% → {option.post_percent.toFixed(1)}% ({option.delta_percentage_points >= 0 ? "+" : ""}
                          {option.delta_percentage_points.toFixed(1)} pp)
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      ) : null}
    </>
  );
}
