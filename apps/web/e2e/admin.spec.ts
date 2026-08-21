import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

/**
 * The admin operations home and course reports (enterprise-gaps-plan
 * Pass A). This is the screen an enterprise buyer is shown first, so it
 * gets browser coverage rather than the HTTP-status-only verification
 * every earlier admin pass settled for.
 *
 * Needs a live API on :8010 and an account holding `analytics:view`.
 * Skipped, loudly, when either is missing — the public specs still run.
 */
import { ADMIN_STATE } from "./admin.setup";

test.use({ storageState: ADMIN_STATE });

test("the operations home shows real KPIs, not a welcome stub", async ({ page }) => {
  await page.goto("/admin");

  await expect(page.getByRole("heading", { name: "Operations", level: 1 })).toBeVisible();

  // The KPI tiles are the point of the screen. Each <dt> label must have a
  // value beside it — a tile that renders its label and no number is the
  // failure mode a screenshot check would wave through.
  const tiles = page.locator(".stat");
  await expect(tiles.first()).toBeVisible();
  expect(await tiles.count()).toBeGreaterThanOrEqual(8);
  for (const value of await page.locator(".stat dd").allTextContents()) {
    expect(value.trim()).not.toBe("");
  }

  // The previously-inert nav placeholder now goes somewhere real.
  await page.getByRole("link", { name: "Course reports" }).click();
  await page.waitForURL(/\/admin\/reports\/courses/);
  await expect(page.getByRole("heading", { name: "Course reports" })).toBeVisible();
});

test("a course report opens from the list", async ({ page }) => {
  await page.goto("/admin/reports/courses");

  const firstCourse = page.locator("table tbody tr td a").first();
  await expect(firstCourse).toBeVisible();
  await firstCourse.click();

  await page.waitForURL(/\/admin\/reports\/courses\/[0-9a-f-]{36}/);
  // The funnel is the headline; "Where learners stop" is the table that
  // makes drop-off visible at all.
  await expect(page.getByText("Enrolled", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Where learners stop" })).toBeVisible();
});

test("the admin home has no WCAG A/AA violations", async ({ page }) => {
  await page.goto("/admin");
  await expect(page.locator(".stat").first()).toBeVisible();

  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const summary = results.violations.map(
    (v) => `${v.id}: ${v.help} -> ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`,
  );
  expect(summary, "axe violations on /admin").toEqual([]);
});
