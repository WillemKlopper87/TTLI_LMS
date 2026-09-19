/**
 * F17c (BACKLOG.md): below 900px `.cat` is one column, so the whole filter
 * sidebar rendered above the results. The fix is a Filters toggle that
 * collapses the facets on narrow screens. jsdom does not evaluate media
 * queries, so this proves the JS/ARIA half (state, labelling, and that
 * the facets stay in the DOM for desktop CSS to show); the real
 * "results come first at 375px" layout is asserted in e2e/public.spec.ts.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { CatalogueBrowser } from "@/app/catalogue/catalogue-browser";
import type { PublicCourse } from "@/lib/server-api";

function course(over: Partial<PublicCourse>): PublicCourse {
  return {
    id: "c1",
    slug: "c1",
    title: "Course",
    topic: "Leadership",
    level: "executive",
    format: "self_paced",
    has_certificate: true,
    includes_workshop: false,
    cpd_points: null,
    price: null,
    ...over,
  } as PublicCourse;
}

const courses = [
  course({ id: "a", title: "Alpha", topic: "Leadership" }),
  course({ id: "b", title: "Beta", topic: "Strategy" }),
];

describe("CatalogueBrowser mobile filters", () => {
  it("starts with the filters collapsed behind a toggle", () => {
    render(<CatalogueBrowser courses={courses} initialTopic={null} initialLevel={null} />);

    const toggle = screen.getByRole("button", { name: /^Filters/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveAttribute("aria-controls", "catalogue-facets");
    expect(document.getElementById("catalogue-facets")).not.toHaveClass("facets--open");
  });

  it("opens and closes on click", async () => {
    render(<CatalogueBrowser courses={courses} initialTopic={null} initialLevel={null} />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /^Filters/ }));
    expect(screen.getByRole("button", { name: /^Filters/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(document.getElementById("catalogue-facets")).toHaveClass("facets--open");

    await user.click(screen.getByRole("button", { name: /^Filters/ }));
    expect(document.getElementById("catalogue-facets")).not.toHaveClass("facets--open");
  });

  it("says how many filters are active, so a collapsed panel is not silent", () => {
    render(<CatalogueBrowser courses={courses} initialTopic="Leadership" initialLevel={null} />);

    expect(screen.getByRole("button", { name: "Filters (1 active)" })).toBeInTheDocument();
  });

  it("keeps the facet controls in the DOM while collapsed for the desktop layout", () => {
    render(<CatalogueBrowser courses={courses} initialTopic={null} initialLevel={null} />);

    expect(screen.getByRole("button", { name: /Leadership/ })).toBeInTheDocument();
  });
});
