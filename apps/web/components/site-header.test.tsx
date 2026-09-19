/**
 * F17b (BACKLOG.md): the public header used to keep every nav item
 * visible on a phone by dropping them onto their own horizontally-
 * scrolling row — nothing collapsed, so nothing here needed a toggle.
 * A real collapse needs its own behaviour proven: the toggle button's
 * accessible state, and that it actually opens/closes the nav rather
 * than a class that only looks right in the CSS.
 *
 * The visual "is it actually collapsed under 760px and axe-clean there"
 * half of this fix is covered by e2e/public.spec.ts's mobile-viewport
 * check instead — jsdom does not evaluate media queries, so a
 * component test here can only prove the ARIA/JS half.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SiteHeader } from "@/components/site-header";

const { usePathname, useRouter } = vi.hoisted(() => ({
  usePathname: vi.fn(),
  useRouter: vi.fn(),
}));
const { useSession } = vi.hoisted(() => ({ useSession: vi.fn() }));

vi.mock("next/navigation", () => ({ usePathname, useRouter }));
vi.mock("@/lib/session-context", () => ({ useSession }));

afterEach(() => {
  vi.clearAllMocks();
});

function renderSignedOut(pathname: string) {
  usePathname.mockReturnValue(pathname);
  useRouter.mockReturnValue({ push: vi.fn() });
  useSession.mockReturnValue({
    accessToken: null,
    status: "anonymous",
    logout: vi.fn(),
  });
  return render(<SiteHeader tenantName="Acme Institute" logoUrl={null} />);
}

describe("SiteHeader mobile nav toggle", () => {
  it("starts closed", () => {
    renderSignedOut("/catalogue");

    const toggle = screen.getByRole("button", { name: "Open menu" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveAttribute("aria-controls", "site-nav");
    expect(screen.getByRole("navigation", { name: "Main" })).not.toHaveClass("site-nav--open");
  });

  it("opens on click and exposes that state to assistive tech", async () => {
    renderSignedOut("/catalogue");
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Open menu" }));

    expect(screen.getByRole("button", { name: "Close menu" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByRole("navigation", { name: "Main" })).toHaveClass("site-nav--open");
  });

  it("closes again on a second click", async () => {
    renderSignedOut("/catalogue");
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Open menu" }));
    await user.click(screen.getByRole("button", { name: "Close menu" }));

    expect(screen.getByRole("button", { name: "Open menu" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.getByRole("navigation", { name: "Main" })).not.toHaveClass("site-nav--open");
  });

  it("closes when navigation completes, so the just-tapped link's page isn't left covered", async () => {
    usePathname.mockReturnValue("/catalogue");
    useRouter.mockReturnValue({ push: vi.fn() });
    useSession.mockReturnValue({ accessToken: null, status: "anonymous", logout: vi.fn() });
    const { rerender } = render(<SiteHeader tenantName="Acme Institute" logoUrl={null} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Open menu" }));
    expect(screen.getByRole("navigation", { name: "Main" })).toHaveClass("site-nav--open");

    usePathname.mockReturnValue("/executive-programmes");
    rerender(<SiteHeader tenantName="Acme Institute" logoUrl={null} />);

    expect(screen.getByRole("navigation", { name: "Main" })).not.toHaveClass("site-nav--open");
    expect(screen.getByRole("button", { name: "Open menu" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });
});
