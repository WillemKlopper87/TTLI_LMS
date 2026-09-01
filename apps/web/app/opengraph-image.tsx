import { ImageResponse } from "next/og";

import { getTheme } from "@/lib/server-api";

/**
 * Default social-share card for every route that doesn't define its own
 * (Next's file convention: any segment can override this by adding its
 * own opengraph-image.tsx). Generated rather than a static asset in
 * public/brand — no 1200x630 marketing asset exists yet, and a
 * generated card can carry the signed-in tenant's own name/color the
 * same way layout.tsx's CSS vars and manifest.ts's icons already do.
 */
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";
export const alt = "Courses, certificates and workshops";

export default async function OpengraphImage() {
  const theme = await getTheme();
  const name = theme?.tenant_name ?? "TTLI";
  const primary = theme?.primary_color ?? "#8e151c";

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          background: primary,
          color: "#f4f4f2",
          fontFamily: "sans-serif",
        }}
      >
        <div style={{ fontSize: 72, fontWeight: 600, letterSpacing: "-0.02em" }}>{name}</div>
        <div style={{ fontSize: 30, marginTop: 28, opacity: 0.85 }}>
          Courses, certificates and workshops
        </div>
      </div>
    ),
    { ...size },
  );
}
