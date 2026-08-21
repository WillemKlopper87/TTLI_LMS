// Flat config — Next 16 removed `next lint`, so ESLint runs directly
// (`npm run lint`, wired into scripts/gates.sh and CI's web job). The
// ruleset is next/core-web-vitals: the framework's own correctness and
// performance rules, not a style regime — formatting stays tsc+review,
// matching how the codebase was actually written. eslint-config-next 16
// exports flat configs natively; FlatCompat chokes on it (circular
// plugin references), hence the direct import.
import coreWebVitals from "eslint-config-next/core-web-vitals";

const config = [
  ...coreWebVitals,
  {
    ignores: [".next/**", "node_modules/**", "next-env.d.ts", "playwright-report/**", "test-results/**"],
  },
  {
    rules: {
      // 34 pre-existing sites (mostly "read window.* / fetch state in an
      // effect then setState") predate this gate; refactoring them is
      // tracked cleanup (NEXT_AGENT_BRIEF §4), not a lint chore to
      // mechanically silence. Warn keeps them visible without blocking
      // the gate; everything else in core-web-vitals stays an error.
      "react-hooks/set-state-in-effect": "warn",
    },
  },
];

export default config;
