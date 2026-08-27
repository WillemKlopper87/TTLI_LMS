import { expect, test } from "@playwright/test";

import { authorSellableCourse } from "./fixtures/author-content";

/**
 * Organisation seat purchasing and management, end to end through a real
 * browser (02 §4.5, REQ-TEN-02): create an organisation, buy seats
 * against it via the PO path — the only path organisations use today —
 * have finance approve the purchase order, then invite an employee into
 * one of the purchased seats and watch the seat pool account for it.
 *
 * The PO is approved via the API (`request` context, as finance-e2e@ who
 * holds `payment:approve`), not a second browser session — finance's own
 * approval *click* is already covered by admin-finance.spec.ts; what
 * this spec exercises is the organisation side of the same fulfilment:
 * the seat pool appearing once the order is fulfilled, and an invited
 * employee actually drawing from it.
 */
const CONTENT_EMAIL = process.env.E2E_CONTENT_EMAIL ?? "content-fixture@example.com";
const CONTENT_PASSWORD = process.env.E2E_CONTENT_PASSWORD ?? "SmokeTest123!content";
const ORG_EMAIL = process.env.E2E_ORG_EMAIL ?? "org-e2e@example.com";
const ORG_PASSWORD = process.env.E2E_ORG_PASSWORD ?? "SmokeTest123!orge2e";
// finance-e2e@, not content-fixture@ — see checkout.spec.ts's identical
// note: stacking a second use onto the shared authoring account is how a
// full local run of every new spec at once produced real 429s.
const FINANCE_EMAIL = process.env.E2E_FINANCE_EMAIL ?? "finance-e2e@example.com";
const FINANCE_PASSWORD = process.env.E2E_FINANCE_PASSWORD ?? "SmokeTest123!finance";

test.beforeEach(async ({ request }) => {
  const probe = await request
    .get("/api/bff/public/workshops", { failOnStatusCode: false })
    .catch(() => null);
  if ((!probe || !probe.ok()) && process.env.REQUIRE_API_E2E === "1") {
    throw new Error("authenticated E2E requires a healthy API, but its readiness probe failed");
  }
  test.skip(
    !probe || !probe.ok(),
    "no API on :8010 — start it (scripts/dev-up.sh + uvicorn) and seed " +
      "content-fixture@/org-e2e@ (scripts/seed_e2e_accounts.py)",
  );
});

test("an org admin buys a seat via PO and assigns it to an employee", async ({
  page,
  request,
}) => {
  test.setTimeout(60_000);

  const course = await authorSellableCourse(request, {
    contentEmail: CONTENT_EMAIL,
    contentPassword: CONTENT_PASSWORD,
  });
  const suffix = Math.random().toString(36).slice(2, 8);
  const employeeEmail = `e2e-employee-${suffix}@example.com`;

  await page.goto("/login");
  await page.getByLabel(/email/i).fill(ORG_EMAIL);
  await page.getByLabel(/password/i).fill(ORG_PASSWORD);
  await page.getByRole("button", { name: /sign in|log ?in/i }).click();
  await page.waitForURL(/\/(admin|learn)/, { timeout: 30_000 });

  await page.goto("/organisations");
  await page.getByLabel(/^name$/i).fill(`E2E Org ${suffix}`);
  await page.getByRole("button", { name: "Create organisation" }).click();
  await page.waitForURL(/\/organisations\/[0-9a-f-]{36}$/, { timeout: 15_000 });

  await page.getByRole("link", { name: "Buy seats" }).click();
  await page.waitForURL(/\/buy-seats$/);
  await page.locator("select").selectOption(course.priceId);
  await page.getByRole("button", { name: "Continue to PO details" }).click();

  await expect(page.getByRole("heading", { name: "Purchase order details" })).toBeVisible();
  await page.getByLabel("PO number").fill(`PO-E2E-${suffix}`);
  await page
    .getByLabel("Purchase order document")
    .setInputFiles({ name: "po.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-fake") });

  const poResponse = page.waitForResponse((r) => /\/checkout\/po$/.test(new URL(r.url()).pathname));
  await page.getByRole("button", { name: "Submit for approval" }).click();
  const po = await (await poResponse).json();
  await expect(page.getByRole("heading", { name: "Submitted for approval" })).toBeVisible();

  // Finance approves — the same real action admin-finance.spec.ts drives
  // through the browser, done here via the API since this spec's point
  // is the organisation side of the fulfilment, not the approval click.
  const financeLogin = await request.post("/api/bff/auth/login", {
    data: { email: FINANCE_EMAIL, password: FINANCE_PASSWORD },
  });
  expect(financeLogin.ok(), await financeLogin.text()).toBe(true);
  const financeToken = await financeLogin.json();
  const approved = await request.post(`/api/bff/payments/${po.payment_id}/approve`, {
    headers: {
      Authorization: `Bearer ${financeToken.access_token}`,
      "Idempotency-Key": `e2e-org-approve-${suffix}`,
    },
  });
  expect(approved.ok(), await approved.text()).toBe(true);

  // A plain <a> (not a Next <Link>) — a real hard navigation, which
  // already re-mounts SessionProvider and refetches this page's data.
  // A second, explicit page.reload() right after was tried here first
  // and reproduced session-context.tsx's own documented double-refresh
  // race (two overlapping boot-time refreshes, the second navigation's
  // teardown discarding the first's in-flight cookie rotation before it
  // applied) — the exact failure mode that file's `serialisedRefresh`
  // docstring describes, just triggered by two navigations in the same
  // tab rather than two tabs/timers. One hard navigation is correct and
  // sufficient; a redundant second one is what broke it.
  await page.getByRole("link", { name: "Back to the organisation" }).click();
  await page.waitForURL(/\/organisations\/[0-9a-f-]{36}$/);

  const seatRow = page.locator("tr", { has: page.getByText(course.title) });
  await expect(seatRow).toBeVisible({ timeout: 10_000 });
  await expect(seatRow.locator("td.mono").first()).toHaveText("1"); // purchased

  await page.getByPlaceholder("course UUID").first().fill(course.courseId);
  await page.getByPlaceholder("one per line, or comma-separated").fill(employeeEmail);
  await page.getByRole("button", { name: "Assign seats" }).click();

  const resultRow = page.locator("li", { has: page.getByText(employeeEmail) });
  await expect(resultRow).toBeVisible({ timeout: 10_000 });
  await expect(resultRow).toContainText("ok");

  await expect(seatRow.locator("td.mono").nth(1)).toHaveText("1"); // assigned
});
