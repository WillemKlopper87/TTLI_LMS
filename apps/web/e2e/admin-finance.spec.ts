import { expect, test } from "@playwright/test";

import { authorAndSubmitPendingEftPayment } from "./fixtures/author-content";

/**
 * The finance approval queue (REQ-PAY-03), end to end through a real
 * browser: a real EFT payment with proof already uploaded sits in
 * `/admin/payments`, finance approves it, and the queue — and the
 * buyer's own enrolment — reflect the real effect of that click, not
 * just a UI state flip.
 *
 * The purchase that puts the payment in the queue is fixture setup
 * (`fixtures/author-content.ts::authorAndSubmitPendingEftPayment`), done
 * through the real API exactly like every other fixture in this suite —
 * what this spec actually drives through the browser is the approval
 * itself, which is the point of "admin finance" coverage.
 *
 * Deliberately does not assert against the analytics/reports dashboards'
 * aggregate figures: those sum every order on a shared, long-lived dev
 * database (the same reason `public.spec.ts`'s course-report test warns
 * about stale rows elsewhere in this suite), so a single fixture order
 * is not reliably distinguishable in an aggregate number without the
 * same kind of cleanup query that test needed. The buyer's own new
 * enrolment is the correctness check instead — a real, isolated effect
 * of the approval, not an aggregate.
 */
const CONTENT_EMAIL = process.env.E2E_CONTENT_EMAIL ?? "content-fixture@example.com";
const CONTENT_PASSWORD = process.env.E2E_CONTENT_PASSWORD ?? "SmokeTest123!content";
const FINANCE_EMAIL = process.env.E2E_FINANCE_EMAIL ?? "finance-e2e@example.com";
const FINANCE_PASSWORD = process.env.E2E_FINANCE_PASSWORD ?? "SmokeTest123!finance";
const BUYER_EMAIL = process.env.E2E_FINANCE_BUYER_EMAIL ?? "finance-buyer-e2e@example.com";
const BUYER_PASSWORD = process.env.E2E_FINANCE_BUYER_PASSWORD ?? "SmokeTest123!financebuyer";

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
      "content-fixture@/finance-e2e@/finance-buyer-e2e@ (scripts/seed_e2e_accounts.py)",
  );
});

test("finance approves a pending EFT payment and the buyer is really enrolled", async ({
  page,
  request,
}) => {
  test.setTimeout(60_000);

  const pending = await authorAndSubmitPendingEftPayment(request, {
    contentEmail: CONTENT_EMAIL,
    contentPassword: CONTENT_PASSWORD,
    buyerEmail: BUYER_EMAIL,
    buyerPassword: BUYER_PASSWORD,
  });

  await page.goto("/login");
  await page.getByLabel(/email/i).fill(FINANCE_EMAIL);
  await page.getByLabel(/password/i).fill(FINANCE_PASSWORD);
  await page.getByRole("button", { name: /sign in|log ?in/i }).click();
  await page.waitForURL(/\/(admin|learn)/, { timeout: 30_000 });

  await page.goto("/admin/payments");
  await expect(page.getByRole("heading", { name: "Payments", level: 1 })).toBeVisible();

  // Addressed by payment id, not by buyer email. The queue is a shared
  // dev database and this account has bought before — every earlier run
  // that died between creating the payment and approving it leaves its row
  // behind, so matching on the email resolved to two cards and failed
  // strict mode. One failed run used to poison every run after it.
  const row = page.locator(".card", {
    has: page.getByLabel(`Reason for rejecting payment ${pending.paymentId}`),
  });
  await expect(row).toBeVisible();
  await expect(row.getByText(pending.buyerEmail)).toBeVisible();
  await expect(row.getByText("Proof uploaded")).toBeVisible();

  await row.getByRole("button", { name: "Approve" }).click();
  await expect(row).toHaveCount(0, { timeout: 10_000 });

  // The real effect: the buyer now holds a genuine enrolment, not just a
  // queue row that disappeared.
  const buyerLogin = await request.post("/api/bff/auth/login", {
    data: { email: BUYER_EMAIL, password: BUYER_PASSWORD },
  });
  expect(buyerLogin.ok(), await buyerLogin.text()).toBe(true);
  const buyerToken = await buyerLogin.json();
  const enrolmentsResp = await request.get("/api/bff/enrolments", {
    headers: { Authorization: `Bearer ${buyerToken.access_token}` },
  });
  expect(enrolmentsResp.ok(), await enrolmentsResp.text()).toBe(true);
  const enrolments = await enrolmentsResp.json();
  expect(
    enrolments.some((e: { course_title: string }) => e.course_title === pending.courseTitle),
  ).toBe(true);
});
