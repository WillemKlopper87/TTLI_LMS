import { expect, test as setup } from "@playwright/test";

/**
 * Sign in once, save the session, let every admin spec reuse it.
 *
 * Not an optimisation — a correctness fix. The API rate-limits login to
 * 5 attempts per minute per account (routers/auth.py), so three specs
 * each signing in for themselves trip the limit and fail with a timeout
 * that looks like a broken redirect. One sign-in per run stays well
 * under it, and the real-form login path is still covered by
 * learner.spec.ts.
 *
 * The refresh cookie is what survives in storage state; the access token
 * lives in memory only (lib/session.ts), so the restored session
 * silently refreshes on first load exactly as a returning user's would.
 */
import { ADMIN_STATE } from "./auth-state";

const EMAIL = process.env.E2E_ADMIN_EMAIL ?? "ops-admin@example.com";
const PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "SmokeTest123!admin";



setup("authenticate as an admin", async ({ page, request }) => {
  const probe = await request
    .post("/api/bff/auth/login", {
      data: { email: EMAIL, password: PASSWORD },
      failOnStatusCode: false,
    })
    .catch(() => null);
  setup.skip(
    !probe || !probe.ok(),
    `no admin session for ${EMAIL} — start the API and seed an account with ` +
      "analytics:view, or set E2E_ADMIN_EMAIL/E2E_ADMIN_PASSWORD",
  );

  await page.goto("/login");
  await page.getByLabel(/email/i).fill(EMAIL);
  await page.getByLabel(/password/i).fill(PASSWORD);
  await page.getByRole("button", { name: /sign in|log ?in/i }).click();
  await page.waitForURL(/\/(admin|learn)/, { timeout: 30_000 });
  // The admin shell is a sidebar, not a <header> — assert the sidebar
  // navigation instead. Reaching a post-login URL with the shell
  // rendered is what makes the saved state worth saving.
  await expect(page.getByRole("navigation").first()).toBeVisible();

  await page.context().storageState({ path: ADMIN_STATE });
});
