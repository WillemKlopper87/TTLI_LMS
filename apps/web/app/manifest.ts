import type { MetadataRoute } from "next";

import { getTheme } from "@/lib/server-api";

/**
 * Phase 4.5 PWA (01 §5.9/§6.6): installable, theme-color and name reflect
 * the signed-in tenant's own theme, not a hardcoded TTLI default — the
 * same `getTheme()` server call `app/layout.tsx` already uses to set the
 * brand CSS variables, so a white-label tenant installs with its own
 * identity rather than TTLI's.
 */
export default async function manifest(): Promise<MetadataRoute.Manifest> {
  const theme = await getTheme();
  const name = theme?.tenant_name ?? "TTLI";
  // The API has no dedicated short-name field, and a home-screen label
  // needs one — the manifest spec's own guidance is ~12 characters.
  // Initials for a name that won't fit, the name itself when it will.
  const shortName =
    name.length > 15 ? name.split(" ").map((word) => word[0]).join("").toUpperCase() : name;

  return {
    name: `${name} Learning Platform`,
    short_name: shortName,
    description: `${name}'s learning platform — courses, certificates and workshops.`,
    start_url: "/learn",
    scope: "/",
    display: "standalone",
    background_color: "#f4f4f2",
    theme_color: theme?.primary_color ?? "#8e151c",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
