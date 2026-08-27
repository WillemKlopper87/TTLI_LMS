import { expect, test } from "@playwright/test";

/**
 * The 401-refresh-and-replay path in `lib/authed-fetch.ts`.
 *
 * Before the nineteen private `authedFetch` copies were consolidated, a
 * token that went stale between render and request surfaced to the user as
 * "could not be loaded" — with a perfectly valid refresh cookie sitting
 * unused in the browser. The scheduled rotation at 80% of the token's
 * lifetime covers an idle tab; it does not cover a request already in
 * flight when the token dies, a tab the OS suspended and woke with a dead
 * token, or a clock that jumped.
 *
 * Reproducing any of those for real would mean waiting out a token
 * lifetime or moving the system clock, so the staleness is injected
 * instead: the first GET of the product list is answered 401, exactly as
 * the API would answer an expired bearer, and everything after it is left
 * alone. What is asserted is the *recovery*, which is all real code —
 * `/admin/catalogue` renders its table rather than hanging on "Loading…",
 * and the replayed request carries a different bearer from the one that
 * was rejected, proof it went through a genuine rotation rather than
 * re-presenting the dead token.
 *
 * Signs in for itself rather than sharing storageState, for the reason
 * admin.spec.ts documents at length: refresh tokens rotate and the API
 * runs reuse detection on them.
 *
 * **Its own account, not admin.spec.ts's.** Login is rate-limited to 5/min
 * per account and the fixed window admits exactly the fifth hit;
 * admin.spec.ts already spends four of those on `ops-admin@`. A fifth login
 * there would sit exactly on the ceiling, and CI's one retry would tip it
 * into a 429 that the login form reports as "those credentials are not
 * valid" — indistinguishable, on screen, from a broken page. This account
 * holds `admin` (which carries the `product:manage` this screen needs)
 * rather than `super_admin`; scripts/seed_e2e_accounts.py creates all three.
 */
const EMAIL = process.env.E2E_REFRESH_EMAIL ?? "refresh-admin@example.com";
const PASSWORD = process.env.E2E_REFRESH_PASSWORD ?? "SmokeTest123!refresh";

test.beforeEach(async ({ request }) => {
  const probe = await request
    .get("/api/bff/public/workshops", { failOnStatusCode: false })
    .catch(() => null);
  test.skip(
    !probe || !probe.ok(),
    "no API on :8010 — start it (scripts/dev-up.sh + uvicorn) and seed an " +
      "account holding product:manage (scripts/seed_e2e_accounts.py)",
  );
});

test("a stale access token is refreshed and the request replayed", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(EMAIL);
  await page.getByLabel(/password/i).fill(PASSWORD);
  await page.getByRole("button", { name: /sign in|log ?in/i }).click();
  await page.waitForURL(/\/(admin|learn)/, { timeout: 30_000 });

  // Every attempt at the products GET, with the token it presented and how
  // it ended. More than one initial attempt is expected: `npm run dev` runs
  // React in StrictMode, which mounts the page twice, and both mounts fire
  // before any refresh completes. Only the first is rejected, so the second
  // sails through on a token that was never really dead — the mock is what
  // pretended otherwise. Counting requests would therefore be asserting a
  // dev-mode artefact; what is asserted instead is the invariant that holds
  // either way.
  const attempts: { bearer: string; status: number }[] = [];
  let alreadyRejected = false;

  await page.route("**/api/bff/catalogue/products", async (route) => {
    const request = route.request();
    if (request.method() !== "GET") {
      await route.continue();
      return;
    }
    const bearer = request.headers()["authorization"] ?? "";
    if (!alreadyRejected) {
      alreadyRejected = true;
      // The API's own envelope for an expired bearer (03 §1.3), so the
      // client cannot tell this from the real thing.
      attempts.push({ bearer, status: 401 });
      await route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({
          error: { code: "UNAUTHENTICATED", message: "Access token has expired." },
        }),
      });
      return;
    }
    const response = await route.fetch();
    attempts.push({ bearer, status: response.status() });
    await route.fulfill({ response });
  });

  await page.goto("/admin/catalogue");

  // The screen recovered. Without the replay `products` stays null, so the
  // section renders "Loading..." indefinitely and the failure copy appears;
  // the table only exists once a GET actually came back with rows. The
  // positive outcome is what is waited for - asserting only the absence of
  // the error would pass on a page that rendered nothing at all.
  await expect(page.getByRole("heading", { name: "Products" })).toBeVisible();
  await expect(page.getByRole("table")).toBeVisible();
  await expect(page.getByText("Products could not be loaded.")).toHaveCount(0);

  // The rejected attempt, and then a replay that presented a *different*
  // bearer and succeeded. Same-token retries and give-ups both fail here:
  // the old nineteen copies never retried at all, and a retry that re-sent
  // the dead token would leave every bearer equal to the rejected one.
  const rejected = attempts[0];
  expect(rejected.status).toBe(401);
  expect(rejected.bearer).toMatch(/^Bearer \S+/);
  await expect
    .poll(() => attempts.some((a) => a.bearer !== rejected.bearer && a.status === 200), {
      timeout: 10_000,
    })
    .toBe(true);
});
