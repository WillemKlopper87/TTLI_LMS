import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

/**
 * The authenticated path, through the real browser: type credentials into
 * the real form, get redirected, land on the learner shell with a session
 * that survives a reload.
 *
 * Needs a live API on :8010 with the demo tenant seeded — skipped, loudly,
 * when there isn't one, so `npm run test:e2e` on a bare checkout still runs
 * the public + axe specs instead of failing for the wrong reason.
 */
const EMAIL = process.env.E2E_EMAIL ?? "smoke-agent@example.com";
const PASSWORD = process.env.E2E_PASSWORD ?? "SmokeTest123!agent";

test.beforeEach(async ({ request }) => {
  const probe = await request
    .post("/api/bff/auth/login", {
      data: { email: EMAIL, password: PASSWORD },
      failOnStatusCode: false,
    })
    .catch(() => null);
  test.skip(
    !probe || !probe.ok(),
    `no API session available for ${EMAIL} — start the API (scripts/dev-up.sh + uvicorn) ` +
      "and seed the demo tenant, or set E2E_EMAIL/E2E_PASSWORD",
  );
});

test("a learner can sign in and reach their dashboard", async ({ page }) => {
  await page.goto("/login");

  await page.getByLabel(/email/i).fill(EMAIL);
  await page.getByLabel(/password/i).fill(PASSWORD);
  await page.getByRole("button", { name: /sign in|log ?in/i }).click();

  // The access token lives in memory only (lib/session.ts), so "signed
  // in" is asserted from what the user can see, not from storage.
  await page.waitForURL(/\/learn/, { timeout: 30_000 });
  await expect(page.locator("header").first()).toBeVisible();

  // A reload must survive on the HttpOnly refresh cookie alone — the
  // silent-refresh path (lib/session-context.tsx) is the thing most
  // likely to break without anyone noticing.
  await page.reload();
  await expect(page).toHaveURL(/\/learn/);
});

test("the learner dashboard, including its Learning paths section, has no WCAG A/AA violations", async ({
  page,
}) => {
  // Covers whichever state the seeded account is actually in — the
  // dashboard's "Learning paths" section (P5 Phase 4) renders nothing
  // when the account holds none, so this isn't contingent on a specific
  // path being purchased the way the pytest integration suite's own
  // fixtures are (F4, docs/research/p5-review-findings.md).
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(EMAIL);
  await page.getByLabel(/password/i).fill(PASSWORD);
  await page.getByRole("button", { name: /sign in|log ?in/i }).click();
  await page.waitForURL(/\/learn/, { timeout: 30_000 });

  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const summary = results.violations.map(
    (v) => `${v.id}: ${v.help} -> ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`,
  );
  expect(summary, "axe violations on /learn").toEqual([]);
});
