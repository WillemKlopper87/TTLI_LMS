/**
 * F17a (BACKLOG.md): the push opt-in used to have no route gating at
 * all — mounted globally in app/layout.tsx, it could interrupt someone
 * mid-checkout or mid-lesson with nothing more than "authenticated,
 * not yet subscribed, not dismissed this session" standing in the way.
 *
 * Every test here arranges every OTHER visibility condition to succeed
 * (authenticated, push supported, not denied, VAPID configured, no
 * existing subscription) so that route is the only variable left — a
 * test that only checked "is hidden on /checkout" without also proving
 * the same setup shows the prompt elsewhere would pass even if the
 * component always rendered null.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NotificationOptIn } from "@/components/notification-opt-in";

const { usePathname } = vi.hoisted(() => ({ usePathname: vi.fn() }));
const { useSession } = vi.hoisted(() => ({ useSession: vi.fn() }));

vi.mock("next/navigation", () => ({ usePathname }));
vi.mock("@/lib/session-context", () => ({ useSession }));

class FakePushManager {
  async getSubscription() {
    return null;
  }
}

// Lets every already-scheduled microtask (the mocked fetch's resolved
// promise, its `.then` chain) run before asserting — without this, an
// assertion right after `render` can race the effect's own first
// `await` and pass for the wrong reason.
async function flushMicrotasks() {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

function primeBrowserForVisibility() {
  useSession.mockReturnValue({ accessToken: "token", status: "authenticated" });
  vi.stubGlobal("Notification", { permission: "default", requestPermission: vi.fn() });
  vi.stubGlobal("PushManager", FakePushManager);
  vi.stubGlobal("navigator", {
    ...navigator,
    serviceWorker: { ready: Promise.resolve({ pushManager: new FakePushManager() }) },
  });
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ configured: true, public_key: "a-key" }),
    }),
  );
  sessionStorage.clear();
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("NotificationOptIn route gating", () => {
  it("shows on an ordinary authenticated route, proving the setup is otherwise visible", async () => {
    primeBrowserForVisibility();
    usePathname.mockReturnValue("/learn");

    render(<NotificationOptIn />);

    await waitFor(() => expect(screen.getByRole("status")).toBeInTheDocument());
  });

  // `waitFor` on a negative assertion ("not in the document") is not a
  // reliable RED/GREEN signal here: it succeeds the instant the check
  // first runs, which is before the component's async effect (fetch,
  // then serviceWorker.ready, then getSubscription) has had any chance
  // to resolve — so it would pass even with zero route-gating code,
  // simply because nothing renders synchronously either way. Instead,
  // these assert the effect never even calls `fetch` — proving the
  // route check short-circuits before any of the visibility-determining
  // async work runs, not just that the UI hasn't updated *yet*.
  it("never fetches push config on /checkout", async () => {
    primeBrowserForVisibility();
    usePathname.mockReturnValue("/checkout");

    render(<NotificationOptIn />);
    await flushMicrotasks();

    expect(fetch).not.toHaveBeenCalled();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("never fetches push config on nested checkout routes", async () => {
    primeBrowserForVisibility();
    usePathname.mockReturnValue("/checkout/return");

    render(<NotificationOptIn />);
    await flushMicrotasks();

    expect(fetch).not.toHaveBeenCalled();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("never fetches push config on the lesson player", async () => {
    primeBrowserForVisibility();
    usePathname.mockReturnValue("/learn/9f18a2b0-2b7a-4b8e-9b7e-9b6a9b6a9b6a");

    render(<NotificationOptIn />);
    await flushMicrotasks();

    expect(fetch).not.toHaveBeenCalled();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("still shows on the learner dashboard's own workshops list", async () => {
    // /learn/sessions is not the player — its dynamic segment happens to
    // be the literal string "sessions", not an enrolment id, so the
    // player-route check must not swallow it.
    primeBrowserForVisibility();
    usePathname.mockReturnValue("/learn/sessions");

    render(<NotificationOptIn />);

    await waitFor(() => expect(screen.getByRole("status")).toBeInTheDocument());
  });

  it("still shows on the lesson transcript, which is not the player itself", async () => {
    primeBrowserForVisibility();
    usePathname.mockReturnValue("/learn/9f18a2b0-2b7a-4b8e-9b7e-9b6a9b6a9b6a/transcript");

    render(<NotificationOptIn />);

    await waitFor(() => expect(screen.getByRole("status")).toBeInTheDocument());
  });
});
