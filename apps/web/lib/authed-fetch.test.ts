/**
 * `authedFetch` is the transport every authenticated screen imports, and
 * its whole reason for existing is one branch: a token that went stale
 * between render and click gets refreshed once and the request replayed.
 * That branch is close to untestable from the outside — provoking it in
 * Playwright means racing an 80%-of-lifetime rotation timer — so it is
 * asserted here, at the seam, where the token state is a mock.
 *
 * The cases below are the four outcomes the module's own docstring
 * promises, plus the two things that silently break a transport: dropped
 * caller headers, and a rejected fetch escaping past the caller's
 * error branch.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { authedFetch } from "@/lib/authed-fetch";
import { getAccessToken, refreshAccessToken } from "@/lib/session";

vi.mock("@/lib/session", () => ({
  getAccessToken: vi.fn(),
  refreshAccessToken: vi.fn(),
}));

const mockedGetAccessToken = vi.mocked(getAccessToken);
const mockedRefreshAccessToken = vi.mocked(refreshAccessToken);

/** The Authorization header of the nth fetch call, so assertions read as
 * "it replayed with the *new* token" rather than as index arithmetic. */
function bearerOfCall(n: number): string | null {
  const [, init] = vi.mocked(globalThis.fetch).mock.calls[n] as [string, RequestInit];
  return new Headers(init.headers).get("Authorization");
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("authedFetch", () => {
  it("attaches the current access token and returns a success untouched", async () => {
    mockedGetAccessToken.mockReturnValue("token-1");
    const ok = new Response("{}", { status: 200 });
    vi.mocked(globalThis.fetch).mockResolvedValue(ok);

    const resp = await authedFetch("/api/bff/courses");

    expect(resp).toBe(ok);
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    expect(bearerOfCall(0)).toBe("Bearer token-1");
    expect(mockedRefreshAccessToken).not.toHaveBeenCalled();
  });

  it("refreshes once and replays the request with the new token on a 401", async () => {
    mockedGetAccessToken.mockReturnValue("stale-token");
    mockedRefreshAccessToken.mockResolvedValue("fresh-token");
    const replayed = new Response("{}", { status: 200 });
    vi.mocked(globalThis.fetch)
      .mockResolvedValueOnce(new Response("", { status: 401 }))
      .mockResolvedValueOnce(replayed);

    const resp = await authedFetch("/api/bff/courses");

    expect(resp).toBe(replayed);
    expect(mockedRefreshAccessToken).toHaveBeenCalledTimes(1);
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
    expect(bearerOfCall(0)).toBe("Bearer stale-token");
    expect(bearerOfCall(1)).toBe("Bearer fresh-token");
  });

  it("does not refresh a 401 for a request that carried no token", async () => {
    // An anonymous caller, or a boot-time restore still in flight. The
    // session provider owns both; refreshing here would add a pointless
    // rotation to every anonymous page load.
    mockedGetAccessToken.mockReturnValue(null);
    const unauthorized = new Response("", { status: 401 });
    vi.mocked(globalThis.fetch).mockResolvedValue(unauthorized);

    const resp = await authedFetch("/api/bff/courses");

    expect(resp).toBe(unauthorized);
    expect(mockedRefreshAccessToken).not.toHaveBeenCalled();
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  });

  it("hands back the original 401 when the refresh fails", async () => {
    // Genuinely signed out. The caller's own signed-out branch must still
    // see a 401 rather than a synthesised success or a thrown error.
    mockedGetAccessToken.mockReturnValue("stale-token");
    mockedRefreshAccessToken.mockResolvedValue(null);
    const unauthorized = new Response("", { status: 401 });
    vi.mocked(globalThis.fetch).mockResolvedValue(unauthorized);

    const resp = await authedFetch("/api/bff/courses");

    expect(resp).toBe(unauthorized);
    expect(mockedRefreshAccessToken).toHaveBeenCalledTimes(1);
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  });

  it("refreshes at most once — a 401 on the replay is returned, not retried", async () => {
    mockedGetAccessToken.mockReturnValue("stale-token");
    mockedRefreshAccessToken.mockResolvedValue("fresh-token");
    vi.mocked(globalThis.fetch).mockResolvedValue(new Response("", { status: 401 }));

    const resp = await authedFetch("/api/bff/courses");

    expect(resp.status).toBe(401);
    expect(mockedRefreshAccessToken).toHaveBeenCalledTimes(1);
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
  });

  it("preserves caller headers whichever shape they arrive in", async () => {
    // RequestInit.headers may be a Headers instance, a tuple array or a
    // plain object, and none of the first two survives object spread. A
    // regression here silently drops Content-Type and the API starts
    // refusing writes.
    mockedGetAccessToken.mockReturnValue("token-1");
    vi.mocked(globalThis.fetch).mockResolvedValue(new Response("{}", { status: 200 }));

    const shapes: RequestInit["headers"][] = [
      new Headers({ "Content-Type": "application/json" }),
      [["Content-Type", "application/json"]],
      { "Content-Type": "application/json" },
    ];

    for (const [i, headers] of shapes.entries()) {
      await authedFetch("/api/bff/courses", { method: "POST", body: "{}", headers });
      const [, init] = vi.mocked(globalThis.fetch).mock.calls[i] as [string, RequestInit];
      const sent = new Headers(init.headers);
      expect(sent.get("Content-Type")).toBe("application/json");
      expect(sent.get("Authorization")).toBe("Bearer token-1");
      expect(init.method).toBe("POST");
    }
  });

  it("resolves a transport failure to a 503 envelope instead of rejecting", async () => {
    // H-17: a rejected fetch sails past the caller's `setBusy(false)` and
    // leaves the form permanently disabled with nothing on screen.
    mockedGetAccessToken.mockReturnValue("token-1");
    vi.mocked(globalThis.fetch).mockRejectedValue(new TypeError("Failed to fetch"));

    const resp = await authedFetch("/api/bff/courses");

    expect(resp.status).toBe(503);
    await expect(resp.json()).resolves.toMatchObject({
      error: { code: "SERVICE_UNAVAILABLE" },
    });
  });

  it("resolves a transport failure on the replay too", async () => {
    // The second fetch has its own .catch(unreachable); losing it would
    // turn a flaky network during a refresh into an unhandled rejection.
    mockedGetAccessToken.mockReturnValue("stale-token");
    mockedRefreshAccessToken.mockResolvedValue("fresh-token");
    vi.mocked(globalThis.fetch)
      .mockResolvedValueOnce(new Response("", { status: 401 }))
      .mockRejectedValueOnce(new TypeError("Failed to fetch"));

    const resp = await authedFetch("/api/bff/courses");

    expect(resp.status).toBe(503);
  });
});
