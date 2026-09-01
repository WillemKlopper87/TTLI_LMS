import { expect, test } from "@playwright/test";

/**
 * Crawls the public pages' own header/footer/body links and checks that
 * every same-origin one resolves without a 4xx/5xx. Runs in the same
 * API-less "web" CI job as public.spec.ts, so it only ever sees links
 * that render with no seeded data — same reasoning as public.spec.ts's
 * own PUBLIC_PAGES list.
 *
 * External links (mailto:, tel:, other domains — LinkedIn, the book
 * retailer, Spotify) are collected but never fetched: a CI run has no
 * business making live network calls to third-party sites, and a
 * flaky or rate-limited external host would fail this gate for a
 * reason that isn't ours to fix.
 */
const ENTRY_PAGES = [
  "/",
  "/catalogue",
  "/executive-programmes",
  "/workshops",
  "/resources",
  "/podcasts",
  "/about",
  "/contact",
  "/login",
  "/paths",
  "/privacy",
  "/terms",
  "/guest-access",
  "/cultivate-with-intent",
  "/lead-with-intent",
  "/for-organisations",
  "/faq",
];

test("no broken same-origin links across the public pages", async ({ page, request, baseURL }) => {
  test.skip(!baseURL, "no baseURL configured");
  // Sixteen page loads plus every link on them, one HTTP check each —
  // comfortably past the default 30s on a cold dev server.
  test.setTimeout(120_000);

  const sameOrigin = new Set<string>();
  for (const path of ENTRY_PAGES) {
    await page.goto(path);
    const hrefs = await page
      .locator("a[href]")
      .evaluateAll((anchors) =>
        anchors
          .map((a) => (a as HTMLAnchorElement).getAttribute("href"))
          .filter((href): href is string => !!href),
      );
    for (const href of hrefs) {
      if (href.startsWith("#") || href.startsWith("mailto:") || href.startsWith("tel:")) continue;
      if (/^https?:\/\//.test(href) && !href.startsWith(baseURL!)) continue;
      sameOrigin.add(href.split("#")[0]);
    }
  }

  const broken: string[] = [];
  for (const href of sameOrigin) {
    const response = await request.get(href);
    if (response.status() >= 400) broken.push(`${href} -> ${response.status()}`);
  }

  expect(broken, "broken same-origin links").toEqual([]);
});
