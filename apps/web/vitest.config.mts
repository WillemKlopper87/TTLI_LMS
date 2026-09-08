/**
 * Component and unit tests for the web app (REMEDIATION_LEDGER.md M7 —
 * "component testing effectively absent").
 *
 * Deliberately separate from Playwright rather than folded into it. The
 * e2e suite in ./e2e drives a real browser against a real API and is the
 * right tool for a journey; it is the wrong tool for asserting that
 * `authedFetch` refreshes exactly once on a stale 401, because provoking
 * that from the outside means racing a token clock. Those are the bugs
 * H-15/H-16/H-17 actually were, and they live in shared transport code
 * that every screen imports — so they get tested directly, at the seam.
 *
 * The two runners cannot collide: Playwright owns `./e2e` (its `testDir`)
 * and matches `*.spec.ts`; vitest is excluded from that directory and
 * matches `*.test.ts` only.
 */
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    // Mirrors tsconfig.json's `"@/*": ["./*"]`. Without it every module
    // under test fails to resolve its own imports and the suite is
    // green-by-vacuity.
    alias: { "@": fileURLToPath(new URL(".", import.meta.url)) },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["{app,components,lib}/**/*.test.{ts,tsx}"],
    exclude: ["e2e/**", "node_modules/**", ".next/**", "test-results/**"],
    // A suite that silently matches nothing is worse than no suite: it
    // reports success. Fail instead if the include glob ever stops
    // finding files.
    passWithNoTests: false,
    restoreMocks: true,
  },
});
