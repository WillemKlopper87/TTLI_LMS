"use client";

/**
 * Site-traffic pageviews on public marketing pages (checklist item 20
 * follow-up; 01_PRD.md §5.11's first-party-analytics decision — no
 * third-party tracker, so no cookie-consent banner is needed for this).
 * Mirrors resources/articles/[slug]/view-tracker.tsx's idiom: a small,
 * fire-and-forget client leaf, mounted once in the root layout so it
 * covers every route rather than needing a tracker added per page.
 *
 * Admin/account/auth/checkout/login/organisations/verify/unsubscribe/
 * learn never fire this — the same "what counts as the public site"
 * boundary robots.ts's NEVER_CRAWLED list already draws for crawlers.
 */
import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

const NON_MARKETING_PREFIXES = [
  "/admin",
  "/account",
  "/api",
  "/auth",
  "/checkout",
  "/login",
  "/organisations",
  "/verify",
  "/unsubscribe",
  "/learn",
];

function isMarketingPath(pathname: string): boolean {
  return !NON_MARKETING_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

export function PageViewTracker() {
  const pathname = usePathname();
  // Guards against both React StrictMode's dev-only double-invoke (same
  // pathname twice) and re-firing on a re-render that isn't a real
  // navigation — a real navigation is exactly when `pathname` changes.
  const fired = useRef<string | null>(null);

  useEffect(() => {
    if (!pathname || fired.current === pathname || !isMarketingPath(pathname)) return;
    fired.current = pathname;
    fetch("/api/bff/public/events/pageview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: pathname, referrer: document.referrer || undefined }),
    }).catch(() => undefined);
  }, [pathname]);

  return null;
}
