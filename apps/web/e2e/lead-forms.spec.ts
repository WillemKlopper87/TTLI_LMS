import { expect, test } from "@playwright/test";

/**
 * Contact and guest-access forms, end to end through a real browser
 * (checklist item 18, "test forms"): the privacy-consent gate refuses
 * submission, then a real submission reaches the API and the page shows
 * its own success state. Both POST to real, unauthenticated endpoints
 * (leads, guest-access), so — unlike public.spec.ts's API-less
 * render/axe checks — this needs a live API: same skip-gracefully,
 * fail-hard-under-REQUIRE_API_E2E convention every authenticated spec
 * already uses (see organisations.spec.ts).
 *
 * No seeded fixture accounts needed — these are public lead-capture
 * forms, not learner/staff logins — so this runs lighter than the other
 * authenticated specs and doesn't need its own account pair.
 */
test.beforeEach(async ({ request }) => {
  const probe = await request
    .get("/api/bff/public/workshops", { failOnStatusCode: false })
    .catch(() => null);
  if ((!probe || !probe.ok()) && process.env.REQUIRE_API_E2E === "1") {
    throw new Error("form e2e requires a healthy API, but its readiness probe failed");
  }
  test.skip(
    !probe || !probe.ok(),
    "no API on :8010 — start it (scripts/dev-up.sh + uvicorn src.main:app)",
  );
});

test("the contact form refuses submission without consent, then succeeds with it", async ({
  page,
}) => {
  await page.goto("/contact");
  await page.getByLabel("First name").fill("Test");
  await page.getByLabel("Last name").fill("Visitor");
  await page.getByLabel("Email").fill(`e2e-contact-${Date.now()}@example.com`);
  await page.getByLabel("Message").fill("This is an end-to-end test message.");

  await page.getByRole("button", { name: "Send message" }).click();
  // Not getByText: both the consent label and the error share "accept
  // the privacy policy" text. Not bare getByRole("alert") either: Next's
  // own route-announcer div carries the same role — the text filter
  // narrows to the form's own error paragraph either way.
  await expect(
    page.getByRole("alert").filter({ hasText: /accept the privacy policy/i }),
  ).toBeVisible();

  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByRole("heading", { name: "Thank you" })).toBeVisible();
});

test("guest access refuses submission without consent, then succeeds with it", async ({
  page,
}) => {
  await page.goto("/guest-access");
  await page.getByLabel("First name").fill("Test");
  await page.getByLabel("Last name").fill("Visitor");
  await page.getByLabel("Work email").fill(`e2e-guest-${Date.now()}@example.com`);

  await page.getByRole("button", { name: "Send my sign-in link" }).click();
  // Not getByText: both the consent label and the error share "accept
  // the privacy policy" text. Not bare getByRole("alert") either: Next's
  // own route-announcer div carries the same role — the text filter
  // narrows to the form's own error paragraph either way.
  await expect(
    page.getByRole("alert").filter({ hasText: /accept the privacy policy/i }),
  ).toBeVisible();

  await page.locator("#privacy-consent").check();
  await page.getByRole("button", { name: "Send my sign-in link" }).click();
  await expect(page.getByRole("heading", { name: "Check your email" })).toBeVisible();
});
