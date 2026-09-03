"use client";

import Hls from "hls.js";
import { useEffect, useRef, useState } from "react";

import { authedFetch } from "@/lib/authed-fetch";

interface Watermark {
  text: string;
  opacity: number;
}

interface PlaybackResponse {
  playlist_url: string;
  captions_url: string | null;
  expires_at: string;
  watermark: Watermark;
  delivery_mode: "hls" | "progressive";
}

/**
 * Real signed HLS playback (03 §6.7) with heartbeat-validated progress
 * (REQ-BYPASS-02/03/04). The watermark is a player overlay rendered here,
 * client-side — never a burned-in re-encode (06 §3.5).
 */
export function VideoPlayer({
  lessonId,
  blockId,
  videoAssetId,
}: {
  lessonId: string;
  blockId: string;
  videoAssetId: string;
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const sessionIdRef = useRef<string>(crypto.randomUUID());
  const [watermark, setWatermark] = useState<Watermark | null>(null);
  const [captionsUrl, setCaptionsUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let hls: Hls | null = null;
    let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
    let cancelled = false;

    async function setup() {
      const resp = await authedFetch(`/api/bff/media/${videoAssetId}/playback`);
      if (!resp.ok) {
        if (!cancelled) setError("This video is not available right now.");
        return;
      }
      const playback: PlaybackResponse = await resp.json();
      if (cancelled) return;
      setWatermark(playback.watermark);
      setCaptionsUrl(playback.captions_url ? `/api/bff/${playback.captions_url}` : null);

      const src = `/api/bff/${playback.playlist_url}`;
      const video = videoRef.current;
      if (!video) return;

      if (playback.delivery_mode === "progressive") {
        // 0040's as-is bypass: no manifest, no adaptive rungs — just the
        // original file, served whole by GET /media/{id}/original.
        video.src = src;
      } else if (Hls.isSupported()) {
        hls = new Hls();
        hls.loadSource(src);
        hls.attachMedia(video);
      } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
        // Safari plays HLS natively — no hls.js needed.
        video.src = src;
      } else {
        setError("This browser cannot play HLS video.");
        return;
      }

      heartbeatTimer = setInterval(() => {
        if (video.paused || video.seeking) return;
        authedFetch(`/api/bff/lessons/${lessonId}/heartbeat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            block_id: blockId,
            position_seconds: video.currentTime,
            playback_rate: video.playbackRate || 1.0,
            session_id: sessionIdRef.current,
          }),
        }).catch(() => undefined);
      }, 5000);
    }

    setup();

    return () => {
      cancelled = true;
      if (heartbeatTimer) clearInterval(heartbeatTimer);
      if (hls) hls.destroy();
    };
  }, [lessonId, blockId, videoAssetId]);

  if (error) {
    return <p role="alert" style={{ fontSize: "0.8125rem", color: "var(--stop)" }}>{error}</p>;
  }

  return (
    <div className="relative mt-3">
      <video
        ref={videoRef}
        controls
        aria-label="Lesson video"
        className="w-full"
        style={{ borderRadius: "4px" }}
      >
        {captionsUrl ? (
          <track kind="captions" src={captionsUrl} srcLang="en" label="English" default />
        ) : null}
      </video>
      {watermark ? (
        <div
          className="pointer-events-none absolute bottom-2 right-2"
          style={{
            fontSize: "0.6875rem",
            color: "white",
            opacity: watermark.opacity,
            textShadow: "0 1px 2px rgba(0,0,0,0.8)",
          }}
        >
          {watermark.text}
        </div>
      ) : null}
    </div>
  );
}
