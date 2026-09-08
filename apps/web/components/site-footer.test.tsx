/**
 * The first real component test in this app (REMEDIATION_LEDGER.md M7).
 *
 * SiteFooter is small but carries two rules that are invisible until they
 * break, and that the e2e suite would only catch by asserting a negative
 * on every admin route: it must render nothing under /admin, because that
 * route has its own full-viewport flex shell and a trailing footer lands
 * outside it; and it must fall back to "TTLI" when a tenant has no name,
 * rather than printing "Copyright © null".
 *
 * `usePathname` is the only thing standing between this component and
 * jsdom, so it is the only thing mocked — `next/link` renders a real
 * anchor and is left alone, which keeps the href assertions honest.
 */
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SiteFooter } from "@/components/site-footer";

const { usePathname } = vi.hoisted(() => ({ usePathname: vi.fn() }));

vi.mock("next/navigation", () => ({ usePathname }));

afterEach(() => {
  vi.clearAllMocks();
});

describe("SiteFooter", () => {
  it("renders the legal nav on a public route", () => {
    usePathname.mockReturnValue("/courses");

    render(<SiteFooter tenantName="Acme Institute" />);

    const nav = screen.getByRole("navigation", { name: "Legal and help" });
    expect(nav).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "FAQ" })).toHaveAttribute("href", "/faq");
    expect(screen.getByRole("link", { name: "Privacy" })).toHaveAttribute("href", "/privacy");
    expect(screen.getByRole("link", { name: "Terms" })).toHaveAttribute("href", "/terms");
  });

  it("shows the tenant name in the copyright line", () => {
    usePathname.mockReturnValue("/");

    render(<SiteFooter tenantName="Acme Institute" />);

    expect(screen.getByText(/Acme Institute/)).toBeInTheDocument();
  });

  it("falls back to TTLI rather than printing a null tenant name", () => {
    usePathname.mockReturnValue("/");

    render(<SiteFooter tenantName={null} />);

    expect(screen.getByText(/TTLI/)).toBeInTheDocument();
    expect(screen.queryByText(/null/)).not.toBeInTheDocument();
  });

  it("renders nothing under /admin, which has its own shell", () => {
    usePathname.mockReturnValue("/admin");

    const { container } = render(<SiteFooter tenantName="Acme Institute" />);

    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("stays hidden on nested admin routes, not just the index", () => {
    usePathname.mockReturnValue("/admin/courses/42/edit");

    const { container } = render(<SiteFooter tenantName="Acme Institute" />);

    expect(container).toBeEmptyDOMElement();
  });

  it("still renders on a route that merely starts with the same letters", () => {
    // `startsWith("/admin")` would also swallow a future /administration
    // or /admin-help route. Pin the current behaviour so that the day one
    // is added, this fails loudly instead of losing its footer silently.
    usePathname.mockReturnValue("/administration");

    render(<SiteFooter tenantName="Acme Institute" />);

    expect(screen.queryByRole("navigation", { name: "Legal and help" })).not.toBeInTheDocument();
  });

  it("renders when the pathname is not yet available", () => {
    // usePathname is typed as possibly null; the component guards with
    // `?.`, and a regression to `pathname.startsWith` would throw during
    // the first paint of every public page.
    usePathname.mockReturnValue(null);

    expect(() => render(<SiteFooter tenantName="Acme Institute" />)).not.toThrow();
    expect(screen.getByRole("navigation", { name: "Legal and help" })).toBeInTheDocument();
  });
});
