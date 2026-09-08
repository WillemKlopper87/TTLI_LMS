/**
 * Per-suite setup. `@testing-library/jest-dom/vitest` registers the DOM
 * matchers (toBeInTheDocument, toBeDisabled, ...) against vitest's expect;
 * without it those assertions throw rather than fail, which reads like a
 * broken test instead of a broken component.
 */
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// React Testing Library does not unmount between tests on its own outside
// of its own globals setup. Left out, a component's effects keep running
// into the next test and failures land in whichever test happens to be
// unlucky rather than the one that caused them.
afterEach(() => {
  cleanup();
});
