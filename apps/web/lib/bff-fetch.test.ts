/**
 * The contract both transports share for a request that never arrives.
 *
 * `unreachable()` is the whole of H-17's fix: a rejected fetch used to sail
 * past the `setBusy(false)` on the line before it, leaving a form
 * permanently disabled with nothing on screen. Every caller branches on
 * `resp.ok`, so the failure has to arrive *as a response*. These assert the
 * three properties callers actually depend on — it resolves rather than
 * rejects, it carries a status the `!resp.ok` branch catches, and its body
 * parses as the API's own error envelope so `readError` finds a message.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { bffFetch, unreachable } from "@/lib/bff-fetch";

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("unreachable", () => {
  it("is a 503 carrying the API's error envelope", async () => {
    const resp = unreachable();

    expect(resp.ok).toBe(false);
    expect(resp.status).toBe(503);
    expect(resp.headers.get("Content-Type")).toBe("application/json");
    await expect(resp.json()).resolves.toEqual({
      error: {
        code: "SERVICE_UNAVAILABLE",
        message: "The server could not be reached. Check your connection and try again.",
      },
    });
  });

  it("returns a fresh response each call", async () => {
    // A shared instance would have its body stream consumed by the first
    // caller, and every later failure would throw on .json() instead of
    // rendering a message.
    const first = unreachable();
    const second = unreachable();

    expect(first).not.toBe(second);
    await first.json();
    expect(first.bodyUsed).toBe(true);
    await expect(second.json()).resolves.toMatchObject({
      error: { code: "SERVICE_UNAVAILABLE" },
    });
  });
});

describe("bffFetch", () => {
  it("passes a successful response straight through", async () => {
    const ok = new Response("{}", { status: 200 });
    vi.mocked(globalThis.fetch).mockResolvedValue(ok);

    await expect(bffFetch("/api/bff/auth/login")).resolves.toBe(ok);
  });

  it("forwards path and init to fetch unchanged", async () => {
    // Unlike authedFetch this transport adds nothing; if it ever started
    // rewriting init, login and password-reset bodies would change shape.
    vi.mocked(globalThis.fetch).mockResolvedValue(new Response("{}", { status: 200 }));
    const init: RequestInit = { method: "POST", body: '{"email":"a@b.c"}' };

    await bffFetch("/api/bff/auth/login", init);

    expect(globalThis.fetch).toHaveBeenCalledWith("/api/bff/auth/login", init);
  });

  it("resolves a transport failure to the 503 envelope rather than rejecting", async () => {
    vi.mocked(globalThis.fetch).mockRejectedValue(new TypeError("Failed to fetch"));

    const resp = await bffFetch("/api/bff/auth/login");

    expect(resp.status).toBe(503);
    await expect(resp.json()).resolves.toMatchObject({
      error: { code: "SERVICE_UNAVAILABLE" },
    });
  });

  it("does not swallow a non-ok response into the unreachable envelope", async () => {
    // A 400 from the API carries its own actionable message; replacing it
    // with "could not be reached" would be a regression in the opposite
    // direction from H-17.
    const badRequest = new Response(
      JSON.stringify({ error: { code: "VALIDATION_ERROR", message: "Email is required" } }),
      { status: 400 },
    );
    vi.mocked(globalThis.fetch).mockResolvedValue(badRequest);

    const resp = await bffFetch("/api/bff/auth/login");

    expect(resp.status).toBe(400);
    await expect(resp.json()).resolves.toMatchObject({
      error: { code: "VALIDATION_ERROR" },
    });
  });
});
