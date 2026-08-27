import { expect, test } from "@playwright/test";

import { authorSellableCourse } from "./fixtures/author-content";

/**
 * The EFT checkout path and the `/checkout/return` confirmation screen,
 * end to end through a real browser (REQ-PAY-03). The card path is
 * deliberately out of scope: it redirects to Payfast's own hosted
 * checkout, which needs live Payfast sandbox credentials nobody has
 * provisioned in this environment (docs' own "externally blocked" list).
 * EFT needs nothing external — the bank details are the platform's own,
 * and approval is a real finance action — so it carries the coverage of
 * `/checkout/return` too: this test navigates there directly with a real
 * order id (skipping only the Payfast redirect leg, not the confirmation
 * page itself) and approves the payment *while the page's own poll loop
 * is running*, watching it transition from "Confirming…" to "Payment
 * confirmed" without a reload — the actual behaviour the polling exists
 * for, not just a fulfilled order loaded once.
 *
 * `Settings.eft_bank_name`/`eft_account_name`/`eft_account_number`/
 * `eft_branch_code` (core/config.py) all default to the literal string
 * "Not yet configured" — real bank details are platform-wide config
 * nobody has provisioned in this environment, the same class of gap as
 * Payfast's live credentials — so this only asserts the bank-details
 * block renders, not real values. `payment_reference` is the one field
 * that's genuinely per-payment regardless, and is what it checks.
 */
const CONTENT_EMAIL = process.env.E2E_CONTENT_EMAIL ?? "content-fixture@example.com";
const CONTENT_PASSWORD = process.env.E2E_CONTENT_PASSWORD ?? "SmokeTest123!content";
const BUYER_EMAIL = process.env.E2E_BUYER_EMAIL ?? "checkout-buyer@example.com";
const BUYER_PASSWORD = process.env.E2E_BUYER_PASSWORD ?? "SmokeTest123!buyer";
// finance-e2e@, not content-fixture@, for the approval — content-fixture@
// is already shared across every spec's fixture-authoring step, and the
// 5/min-per-account (and 10/min-per-IP) login limits mean stacking a
// second, unrelated use onto it is how a full local run of every new
// spec at once produced real 429s. finance-e2e@ also holds
// payment:approve on its own account (the `finance` role), so this is
// the more honest identity for the action anyway.
const FINANCE_EMAIL = process.env.E2E_FINANCE_EMAIL ?? "finance-e2e@example.com";
const FINANCE_PASSWORD = process.env.E2E_FINANCE_PASSWORD ?? "SmokeTest123!finance";

test.beforeEach(async ({ request }) => {
  const probe = await request
    .get("/api/bff/public/workshops", { failOnStatusCode: false })
    .catch(() => null);
  test.skip(
    !probe || !probe.ok(),
    "no API on :8010 — start it (scripts/dev-up.sh + uvicorn) and seed " +
      "content-fixture@/checkout-buyer@ (scripts/seed_e2e_accounts.py)",
  );
});

test("a learner buys a course via EFT and watches the return page confirm it live", async ({
  page,
  request,
}) => {
  // The default 30s test timeout is too tight here: fixture setup alone
  // is a dozen-plus sequential API round trips, and the live-poll wait
  // for "Payment confirmed" below has its own 20s budget. 90s leaves
  // real headroom rather than making this test flaky under load.
  test.setTimeout(90_000);

  const course = await authorSellableCourse(request, {
    contentEmail: CONTENT_EMAIL,
    contentPassword: CONTENT_PASSWORD,
  });

  await page.goto("/login");
  await page.getByLabel(/email/i).fill(BUYER_EMAIL);
  await page.getByLabel(/password/i).fill(BUYER_PASSWORD);
  await page.getByRole("button", { name: /sign in|log ?in/i }).click();
  await page.waitForURL(/\/(admin|learn)/, { timeout: 30_000 });

  await page.goto(`/checkout?price=${course.priceId}`);
  await expect(page.getByRole("heading", { name: /how would you like to pay/i })).toBeVisible();
  await expect(page.getByText(course.title)).toBeVisible();

  await page.getByRole("tab", { name: "EFT" }).click();

  const orderResponse = page.waitForResponse(
    (r) => /\/api\/bff\/orders$/.test(new URL(r.url()).pathname) && r.request().method() === "POST",
  );
  const eftResponse = page.waitForResponse((r) =>
    /\/checkout\/eft$/.test(new URL(r.url()).pathname),
  );
  await page.getByRole("button", { name: "Show me the bank details" }).click();
  const order = await (await orderResponse).json();
  const eft = await (await eftResponse).json();

  // eft.bank_name/account_name/account_number/branch_code are all the
  // same "Not yet configured" placeholder in this environment — EFT bank
  // details are platform-wide config nobody has provisioned here, the
  // same class of gap as Payfast's live credentials. The reference is
  // the one field that's genuinely per-payment regardless.
  await expect(page.locator(".bank")).toBeVisible();
  await expect(page.getByText(eft.payment_reference)).toBeVisible();

  await page
    .locator('input[type="file"]')
    .setInputFiles({ name: "proof.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-fake") });
  await page.getByRole("button", { name: "Submit for approval" }).click();
  await expect(page.getByRole("heading", { name: "Submitted for approval" })).toBeVisible();

  // The confirmation screen, watched live: pending first, then finance
  // approves mid-poll, then fulfilled — without a page reload.
  await page.goto(`/checkout/return?order=${order.id}`);
  await expect(page.getByRole("heading", { name: "Confirming your payment…" })).toBeVisible();

  const financeLogin = await request.post("/api/bff/auth/login", {
    data: { email: FINANCE_EMAIL, password: FINANCE_PASSWORD },
  });
  expect(financeLogin.ok(), await financeLogin.text()).toBe(true);
  const financeToken = await financeLogin.json();
  const approved = await request.post(`/api/bff/payments/${eft.payment_id}/approve`, {
    headers: {
      Authorization: `Bearer ${financeToken.access_token}`,
      "Idempotency-Key": `e2e-approve-${order.id}`,
    },
  });
  expect(approved.ok(), await approved.text()).toBe(true);

  await expect(page.getByRole("heading", { name: "Payment confirmed" })).toBeVisible({
    timeout: 20_000,
  });
  await expect(page.getByText("your course is ready")).toBeVisible();
});
