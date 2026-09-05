import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

/**
 * The browser half of single sign-on (fable5.1 review H-15).
 *
 * The API endpoints, the two BFF routes and the HttpOnly binding cookie
 * were all built and unit-tested, and `routers/sso.py::callback_url`
 * registers `https://{tenant host}/auth/sso/callback` with the identity
 * provider — but no page served that path, and no button ever started a
 * flow. A tenant that configured an IdP sent its staff to a 404.
 *
 * A genuine round-trip needs a real IdP, which `tests/test_sso.py`
 * already exercises against a fake one at the HTTP boundary. What only a
 * browser can show is the part that lives here: that the callback route
 * exists, that it turns each outcome into something a person can read
 * or act on, and that it never navigates off this site on the say-so of
 * a response body.
 */

test("the callback page exists and reports a refusal from the identity provider", async ({
  page,
}) => {
  await page.goto("/auth/sso/callback?error=access_denied&state=abc");

  await expect(page.getByRole("heading", { name: /single sign-on didn.t complete/i })).toBeVisible();
  await expect(page.getByText(/cancelled/i)).toBeVisible();
  await expect(page.getByRole("link", { name: /back to sign in/i })).toBeVisible();

  // The same WCAG A/AA line every other unauthenticated page holds — this
  // one is reached by anybody whose SSO attempt goes wrong, which is
  // exactly when a page needs to be readable.
  const scan = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(scan.violations).toEqual([]);
});

test("a callback with no code says so rather than posting an empty exchange", async ({ page }) => {
  let posted = 0;
  await page.route("**/api/bff/auth/sso/callback", (route) => {
    posted += 1;
    return route.fulfill({ status: 400, contentType: "application/json", body: "{}" });
  });

  await page.goto("/auth/sso/callback?state=abc");

  await expect(page.getByText(/sign-in link is incomplete/i)).toBeVisible();
  expect(posted).toBe(0);
});

test("a completed callback lands on the deep link the flow parked", async ({ page }) => {
  await page.route("**/api/bff/auth/sso/callback", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "not-a-real-token",
        refresh_token: "not-a-real-token",
        token_type: "Bearer",
        expires_in: 900,
        next_path: "/catalogue",
      }),
    }),
  );

  await page.goto("/auth/sso/callback?code=abc&state=def");

  await page.waitForURL(/\/catalogue/, { timeout: 15_000 });
});

test("a next_path pointing off this site is refused by the page as well", async ({
  page,
  baseURL,
}) => {
  // The API sanitises this when it parks it (services/oidc.py), so the
  // only way to produce one is to answer for the API — which is exactly
  // what makes it worth pinning here: the page navigates to this value,
  // so the page checks it too.
  await page.route("**/api/bff/auth/sso/callback", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "not-a-real-token",
        refresh_token: "not-a-real-token",
        token_type: "Bearer",
        expires_in: 900,
        next_path: "https://evil.example/take-over",
      }),
    }),
  );

  await page.goto("/auth/sso/callback?code=abc&state=def");
  await page.waitForURL((url) => !url.pathname.startsWith("/auth/sso"), { timeout: 15_000 });

  const landed = new URL(page.url());
  expect(landed.host).toBe(new URL(baseURL ?? "http://localhost:3011").host);
  expect(landed.pathname).toBe("/learn");
});

test("the sign-in page offers SSO only when the tenant has an identity provider", async ({
  page,
}) => {
  // The demo tenant has none configured, so nothing should be offered —
  // a button that 404s on the way to a provider that does not exist is
  // worse than no button.
  await page.goto("/login");
  await expect(page.getByRole("button", { name: /continue with/i })).toHaveCount(0);

  await page.route("**/api/bff/auth/sso/available", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ available: true, display_name: "Meridian ID" }),
    }),
  );
  // Same-origin stand-in for the provider's authorization URL, so the
  // test asserts the navigation without leaving the site.
  await page.route("**/api/bff/auth/sso/start*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ authorization_url: "/faq" }),
    }),
  );

  await page.goto("/login");
  const button = page.getByRole("button", { name: "Continue with Meridian ID" });
  await expect(button).toBeVisible();

  await button.click();
  await page.waitForURL(/\/faq/, { timeout: 15_000 });
});
