import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

/**
 * The public surface: it renders, and it has no WCAG A/AA violations.
 *
 * lib/server-api.ts's publicGet() resolves null rather than throwing when
 * the API is down, so these pages render their shell either way — which
 * is exactly why they can be asserted without a running API, and also why
 * the assertions target the page's own chrome rather than API-fed content.
 */
const PUBLIC_PAGES = [
  { path: "/", name: "home" },
  { path: "/catalogue", name: "catalogue" },
  { path: "/executive-programmes", name: "executive programmes" },
  { path: "/workshops", name: "workshops" },
  { path: "/resources", name: "resources" },
  { path: "/podcasts", name: "podcasts" },
  { path: "/about", name: "about" },
  { path: "/contact", name: "contact" },
  { path: "/login", name: "login" },
  // The public learning-path browse page (P5 Phase 4) — added on review
  // (F4, docs/research/p5-review-findings.md): the approved P5 plan's
  // own Phase 4 "Verify" step called for this and it was skipped. The
  // detail page (`/paths/[pathId]`) needs a real, tenant-assigned path
  // to render anything but its "not found" shell, so it isn't listed
  // here the same way `/catalogue/[courseId]` isn't — this table is for
  // pages that render meaningfully with no seeded data.
  { path: "/paths", name: "learning paths" },
];

for (const page_ of PUBLIC_PAGES) {
  test(`${page_.name} renders`, async ({ page }) => {
    const response = await page.goto(page_.path);
    expect(response?.status(), `${page_.path} should not error`).toBeLessThan(400);
    // Every page carries the shared site header — a blank 200 (the
    // failure mode a status-code-only check misses) fails here.
    await expect(page.locator("header").first()).toBeVisible();
    await expect(page).toHaveTitle(/./);
  });

  test(`${page_.name} has no WCAG A/AA violations`, async ({ page }) => {
    await page.goto(page_.path);
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    // Named in the failure so a regression says which rule broke where —
    // including the offending selectors, because "1 violation" without a
    // target is a scavenger hunt.
    const summary = results.violations.map(
      (v) =>
        `${v.id}: ${v.help} -> ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`,
    );
    expect(summary, `axe violations on ${page_.path}`).toEqual([]);
  });
}

test("the header exposes the primary navigation", async ({ page }) => {
  await page.goto("/");
  const nav = page.locator("header nav").first();
  await expect(nav).toBeVisible();
  await expect(nav.getByRole("link")).not.toHaveCount(0);
});

// A learning path detail page for an id that doesn't exist — the "not
// found" shell (app/paths/[pathId]/page.tsx) renders identically
// whether the API has no such path or is down entirely (F4, docs/
// research/p5-review-findings.md), so it needs no seeded data the way
// a real path's own page would.
test("a learning path detail page for an unknown id renders its not-found shell", async ({
  page,
}) => {
  const response = await page.goto("/paths/00000000-0000-0000-0000-000000000000");
  expect(response?.status()).toBeLessThan(400);
  await expect(page.getByText(/could not be found/i)).toBeVisible();
});

test("that not-found shell has no WCAG A/AA violations", async ({ page }) => {
  await page.goto("/paths/00000000-0000-0000-0000-000000000000");
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const summary = results.violations.map(
    (v) => `${v.id}: ${v.help} -> ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`,
  );
  expect(summary, "axe violations on the path not-found shell").toEqual([]);
});
