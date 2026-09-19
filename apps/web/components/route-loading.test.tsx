/**
 * F18 (BACKLOG.md): no route in the app had a loading.tsx, so a storefront
 * navigation showed the previous page (or nothing) until the API answered.
 * These pin the shared fallback's accessibility contract, and — because a
 * loading state is exactly the kind of thing that quietly goes missing on
 * the next route someone adds — that every anonymous storefront route has
 * one.
 */
import { existsSync } from "node:fs";
import { join } from "node:path";

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RouteLoading } from "@/components/route-loading";

describe("RouteLoading", () => {
  it("announces itself politely to assistive tech with the given label", () => {
    render(<RouteLoading label="Loading the catalogue" />);

    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("Loading the catalogue");
    expect(status).toHaveAttribute("aria-live", "polite");
  });

  it("falls back to a generic label", () => {
    render(<RouteLoading />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading");
  });
});

// Anonymous storefront routes: the pages that fetch public API data
// server-side (lib/server-api.ts) and so can spend real time waiting.
const STOREFRONT_ROUTES = [
  "catalogue",
  "courses/[courseId]",
  "paths",
  "paths/[pathId]",
  "podcasts",
  "podcasts/[slug]",
  "workshops",
  "resources",
  "resources/articles/[slug]",
  "executive-programmes",
];

describe("storefront loading states", () => {
  it.each(STOREFRONT_ROUTES)("app/%s has a loading.tsx", (route) => {
    expect(existsSync(join(process.cwd(), "app", route, "loading.tsx"))).toBe(true);
  });
});
