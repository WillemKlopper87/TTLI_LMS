import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

/**
 * The admin operations home, course reports and audit log
 * (enterprise-gaps-plan Passes A and B). These are the screens an
 * enterprise buyer is shown first, so they get browser coverage rather
 * than the HTTP-status-only verification earlier admin passes settled
 * for.
 *
 * **Each test signs in for itself, and that is deliberate.** Sharing one
 * saved `storageState` across specs looks like the obvious optimisation
 * and is actively wrong here: refresh tokens rotate and the API runs
 * reuse detection on them (`services/tokens.py`). Replaying one saved
 * cookie from several parallel contexts means the second and third
 * present an already-rotated token, the API correctly revokes the whole
 * family, and every one of those specs lands on `/login` — which reads
 * as "the page is broken" rather than "the fixture is". Cost half a pass
 * to diagnose on 2026-08-21.
 *
 * Three form logins per run stays inside the 5/min per-account limit;
 * the availability probe below deliberately uses a PUBLIC endpoint so it
 * does not spend one of them.
 */
const EMAIL = process.env.E2E_ADMIN_EMAIL ?? "ops-admin@example.com";
const PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "SmokeTest123!admin";

test.beforeEach(async ({ request }) => {
  const probe = await request
    .get("/api/bff/public/workshops", { failOnStatusCode: false })
    .catch(() => null);
  test.skip(
    !probe || !probe.ok(),
    "no API on :8010 — start it (scripts/dev-up.sh + uvicorn) and seed an " +
      "account holding analytics:view and audit:read",
  );
});

async function signIn(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(EMAIL);
  await page.getByLabel(/password/i).fill(PASSWORD);
  await page.getByRole("button", { name: /sign in|log ?in/i }).click();
  await page.waitForURL(/\/(admin|learn)/, { timeout: 30_000 });
}

test("the operations home shows real KPIs, not a welcome stub", async ({ page }) => {
  await signIn(page);
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
  await signIn(page);
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

test("the audit log lists events and has no WCAG A/AA violations", async ({ page }) => {
  await signIn(page);
  await page.goto("/admin/audit");

  await expect(page.getByRole("heading", { name: "Audit log", level: 1 })).toBeVisible();
  // Signing in a line ago wrote an auth.login.succeeded row, so the log
  // is never empty on this path.
  await expect(page.locator("table tbody tr").first()).toBeVisible();

  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const summary = results.violations.map(
    (v) => `${v.id}: ${v.help} -> ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`,
  );
  expect(summary, "axe violations on /admin/audit").toEqual([]);
});
