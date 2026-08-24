"use client";

/**
 * R3 (docs/BACKLOG.md; resources-hub-design.md §4 decision 3) — "at
 * least a viewed event for symmetry" with podcasts' listen-stat set.
 *
 * The article page itself stays a server component (deliberately
 * crawlable, per its own docstring) — this is the one small client
 * leaf, mirroring `app/podcasts/[slug]/page.tsx`'s `logEvent` idiom:
 * fire-and-forget, no auth, no response body, mounted once per real
 * browser render rather than inferred from the server-side fetch that
 * also serves search-engine crawlers.
 */
import { useEffect, useRef } from "react";

export default function ArticleViewTracker({ slug }: { slug: string }) {
  // React StrictMode double-invokes effects in dev, which would double
  // the count on every dev-mode page load (overall-review I3) — a real
  // browser render never remounts like this, so a once-per-slug guard
  // fixes dev without changing production behaviour, where the effect
  // only ever runs once anyway.
  const fired = useRef<string | null>(null);

  useEffect(() => {
    if (fired.current === slug) return;
    fired.current = slug;
    fetch(`/api/bff/public/articles/${slug}/events`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ event_name: "article.viewed" }),
    }).catch(() => undefined);
  }, [slug]);

  return null;
}
