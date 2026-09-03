"use client";

/**
 * Step 3 — Content. Outline on the left, the selected lesson on the right:
 * document body (PATCH on blur) plus the existing `LessonActivityPanel`,
 * reused unchanged — 964 lines of proven attach/upload/caption logic,
 * including the FormData content-type and `video_asset_id` query-param
 * subtleties that were hard-won.
 *
 * The transcode strip polls `GET /courses/{id}/outline` every 5s while any
 * lesson's `video_state` is still `uploaded`/`transcoding`, so the author
 * keeps working while ffmpeg runs instead of watching one upload.
 */

import { useEffect, useMemo, useState } from "react";

import { LessonPicker } from "../curriculum-outline";
import { LessonActivityPanel } from "../lesson-activity-panel";
import {
  ACCESS_LEVELS,
  IN_FLIGHT_VIDEO_STATES,
  type LessonItem,
  primaryActivityType,
  primaryOutlineBlock,
} from "../types";
import { authedFetch, readError, sendJson } from "../wizard-api";
import { type StepProps, WizardShell } from "../wizard-shell";

/** A lesson's document text lives on its own "text" block (0041), not
 * the lesson itself. */
function textBlockBody(lesson: LessonItem): string {
  return lesson.blocks.find((b) => b.block_type === "text")?.body ?? "";
}

export function StepContent({ ctx, stepStates, onStep, savedAt, error, notice }: StepProps) {
  const outline = ctx.outline;
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);

  const rows = useMemo(
    () => (outline?.modules ?? []).flatMap((m) => m.lessons),
    [outline],
  );
  const selected = rows.find((r) => r.lesson.id === selectedId) ?? null;
  // "The" activity block for the selected lesson, i.e. whichever one
  // primaryActivityType names — null on a document-only (or empty)
  // lesson.
  const activityBlockRow = selected ? primaryOutlineBlock(selected) : null;

  // Select the first lesson once the outline arrives, and keep the body
  // textarea in step with whichever lesson is open.
  useEffect(() => {
    void (async () => {
      if (rows.length === 0) return;
      if (selectedId === null || !rows.some((r) => r.lesson.id === selectedId)) {
        setSelectedId(rows[0].lesson.id);
        setBody(textBlockBody(rows[0].lesson));
      }
    })();
  }, [rows, selectedId]);

  const transcoding = rows.filter((r) => {
    const state = primaryOutlineBlock(r)?.media_state ?? null;
    return state !== null && IN_FLIGHT_VIDEO_STATES.has(state);
  });

  useEffect(() => {
    if (transcoding.length === 0) return;
    const id = setInterval(() => {
      void ctx.reloadOutline();
    }, 5000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [transcoding.length]);

  function select(lesson: LessonItem) {
    setSelectedId(lesson.id);
    setBody(textBlockBody(lesson));
  }

  async function saveBody() {
    if (!selected || !ctx.canEdit) return;
    const textBlock = selected.lesson.blocks.find((b) => b.block_type === "text") ?? null;
    if ((textBlock?.body ?? "") === body) return;
    let resp: Response;
    if (textBlock) {
      resp = await sendJson(`/api/bff/lessons/${selected.lesson.id}/blocks/${textBlock.id}`, "PATCH", {
        body: body || null,
      });
    } else if (body.trim().length > 0) {
      // No text block exists yet on this lesson — create one, then write
      // the body onto it (LessonBlockCreateRequest has no body field).
      const created = await sendJson(`/api/bff/lessons/${selected.lesson.id}/blocks`, "POST", {
        block_type: "text",
      });
      if (!created.ok) {
        ctx.setError(await readError(created, "The lesson body could not be saved."));
        return;
      }
      const blockId = (await created.json()).id as string;
      resp = await sendJson(`/api/bff/lessons/${selected.lesson.id}/blocks/${blockId}`, "PATCH", {
        body,
      });
    } else {
      return; // nothing to save: no block, and nothing typed
    }
    if (!resp.ok) {
      ctx.setError(await readError(resp, "The lesson body could not be saved."));
      return;
    }
    ctx.setError(null);
    ctx.markSaved();
    await ctx.reloadOutline();
    await ctx.reloadReadiness();
  }

  async function setAccessLevel(level: string) {
    if (!selected) return;
    const resp = await sendJson(`/api/bff/lessons/${selected.lesson.id}`, "PATCH", {
      access_level: level,
    });
    if (!resp.ok) {
      ctx.setError(await readError(resp, "The access level could not be changed."));
      return;
    }
    ctx.setError(null);
    ctx.markSaved();
    await ctx.reloadOutline();
  }

  async function detachActivity() {
    if (!selected) return;
    const activityBlock = selected.lesson.blocks.find((b) => b.block_type !== "text") ?? null;
    if (!activityBlock) return;
    if (
      !window.confirm(
        `Detach the ${activityBlock.block_type} from "${selected.lesson.title}"? The activity itself is kept — the lesson reverts to a document.`,
      )
    ) {
      return;
    }
    setBusy(true);
    // 0041: "detach" is deleting the one non-text block the lesson
    // carries — there is no lesson-level activity to detach any more.
    const resp = await authedFetch(`/api/bff/lessons/${selected.lesson.id}/blocks/${activityBlock.id}`, {
      method: "DELETE",
    });
    setBusy(false);
    if (!resp.ok) {
      ctx.setError(await readError(resp, "The activity could not be detached."));
      return;
    }
    ctx.setError(null);
    ctx.markSaved();
    await ctx.reloadOutline();
    await ctx.reloadReadiness();
  }

  return (
    <WizardShell
      step={3}
      stepStates={stepStates}
      onStep={onStep}
      savedAt={savedAt}
      error={error}
      notice={notice}
      title="Content"
      intro="Pick a lesson, then write its document body or attach a video, quiz, survey or assignment."
      onBack={() => onStep(2)}
      onContinue={() => onStep(4)}
    >
      {transcoding.length > 0 ? (
        <div className="callout callout--warn">
          <b>
            {transcoding.length} video{transcoding.length === 1 ? "" : "s"} still transcoding
          </b>
          <p style={{ fontSize: "0.8125rem" }}>
            Keep authoring — this strip refreshes every five seconds. A lesson whose video is not
            yet <span className="mono">ready</span> is a publish blocker.
          </p>
        </div>
      ) : null}

      {outline === null ? (
        <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>Loading…</p>
      ) : (
        <div className="mt-4 flex flex-col gap-6 xl:flex-row">
          <div className="xl:w-[22rem] xl:shrink-0">
            <LessonPicker
              outline={outline}
              selectedLessonId={selectedId}
              onSelect={(row) => select(row.lesson)}
            />
          </div>

          <div className="flex-1" style={{ minWidth: 0 }}>
            {selected === null ? (
              <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>
                Select a lesson to author it.
              </p>
            ) : (
              <>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="eyebrow">Lesson</p>
                    <h3 className="serif" style={{ fontSize: "1.05rem" }}>
                      {selected.lesson.title}
                    </h3>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="tag tag--mute">{primaryActivityType(selected.lesson)}</span>
                    {activityBlockRow?.media_state ? (
                      <span className="tag tag--live">{activityBlockRow.media_state}</span>
                    ) : null}
                    <a
                      className="btn btn--ghost"
                      href={`/preview/${selected.lesson.id}`}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      View as learner ↗
                    </a>
                  </div>
                </div>

                <div className="two mt-4">
                  <label>
                    <b>Access level</b>
                    <select
                      className="input"
                      value={selected.lesson.access_level}
                      disabled={!ctx.canEdit}
                      onChange={(e) => void setAccessLevel(e.target.value)}
                    >
                      {ACCESS_LEVELS.map((level) => (
                        <option key={level} value={level}>
                          {level}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <b>Estimated duration</b>
                    <span style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
                      {selected.estimated_minutes}m
                      {activityBlockRow?.duration_seconds != null
                        ? ` · video ${activityBlockRow.duration_seconds}s`
                        : ""}
                      {activityBlockRow?.media_state === "ready" && !activityBlockRow.video_has_captions
                        ? " · no captions"
                        : ""}
                      {activityBlockRow?.question_count != null
                        ? ` · ${activityBlockRow.question_count} questions`
                        : ""}
                    </span>
                  </label>
                </div>

                <label className="field mt-4">
                  <b>Document body</b>
                  <textarea
                    className="input"
                    rows={8}
                    value={body}
                    disabled={!ctx.canEdit}
                    placeholder="Plain-text lesson content. Saved when you click away."
                    onChange={(e) => setBody(e.target.value)}
                    onBlur={() => void saveBody()}
                  />
                </label>

                {primaryActivityType(selected.lesson) !== "document" && ctx.canEdit ? (
                  <button
                    type="button"
                    className="btn btn--ghost mt-3"
                    disabled={busy}
                    onClick={() => void detachActivity()}
                  >
                    Detach activity (revert to document)
                  </button>
                ) : null}

                <LessonActivityPanel
                  key={selected.lesson.id}
                  lesson={selected.lesson}
                  canEdit={ctx.canEdit}
                  onChanged={() => {
                    ctx.markSaved();
                    void ctx.reloadOutline();
                    void ctx.reloadReadiness();
                  }}
                />
              </>
            )}
          </div>
        </div>
      )}
    </WizardShell>
  );
}
