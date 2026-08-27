import { defineConfig, devices } from "@playwright/test";

/**
 * Browser-level smoke + accessibility gate.
 *
 * Every "browser-verified" claim in docs/HANDOFF.md until now was a human
 * (or an agent driving CDP by hand) looking at a page once. These tests
 * are the automated floor under that: the pages a customer sees first
 * must render, the learner path must be reachable behind a real login,
 * and axe-core must find no WCAG A/AA violations on the public surface —
 * the regression gate the one-time contrast audit never had (Phase 4.5's
 * last open item).
 *
 * Runs against a PRODUCTION build on :3011, not `next dev` on :3010.
 * That is deliberate: under parallel requests the dev server's on-demand
 * webpack compilation intermittently 500s a route that renders perfectly
 * (`__webpack_modules__[moduleId] is not a function`) — a dev-mode
 * artefact that would make this gate flaky and, worse, train everyone to
 * ignore it. The production build is also what actually ships. Port 3011
 * keeps it clear of a dev server someone left running on 3010.
 *
 * The API is NOT started here. It must be up on :8010 with the demo
 * tenant seeded (`scripts/dev-up.sh` + the uvicorn command) for the
 * authenticated spec; that spec skips itself, loudly, when it isn't, so
 * the public + axe checks still run on a bare checkout.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: process.env.WEB_URL ?? "http://localhost:3011",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: process.env.WEB_URL
    ? undefined
    : {
        command: "npm run build && npm run start:e2e",
        // Readiness must not render a server component that calls the API:
        // the CI web job intentionally starts no API. robots.txt is static,
        // while the authenticated specs perform their own API probe and skip.
        url: "http://localhost:3011/robots.txt",
        reuseExistingServer: !process.env.CI,
        timeout: 300_000,
      },
});
