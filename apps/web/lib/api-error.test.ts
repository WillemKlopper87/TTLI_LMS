/**
 * `readError` is what turns a refusal into the sentence a user reads, on
 * every admin screen and the whole course wizard. Its failure mode is
 * quiet: get it wrong and every error collapses to the generic fallback,
 * so the specific, actionable reason the API wrote server-side is thrown
 * away and nobody notices because *something* still renders.
 */
import { describe, expect, it } from "vitest";

import { readError } from "@/lib/api-error";

function envelope(body: unknown, status = 400): Response {
  return new Response(JSON.stringify(body), { status });
}

describe("readError", () => {
  it("returns the API's own message when the envelope carries one", async () => {
    const resp = envelope({
      error: { code: "VALIDATION_ERROR", message: "Start date must be before end date" },
    });

    await expect(readError(resp, "Could not save")).resolves.toBe(
      "Start date must be before end date",
    );
  });

  it("falls back when the body is not JSON at all", async () => {
    // A proxy error page or an HTML 502 — .json() throws, and the caller
    // still needs a sentence.
    const resp = new Response("<html>502 Bad Gateway</html>", { status: 502 });

    await expect(readError(resp, "Could not save")).resolves.toBe("Could not save");
  });

  it("falls back on an empty body", async () => {
    const resp = new Response("", { status: 500 });

    await expect(readError(resp, "Could not save")).resolves.toBe("Could not save");
  });

  it("falls back when the JSON is not the error envelope", async () => {
    await expect(readError(envelope({ detail: "nope" }), "Could not save")).resolves.toBe(
      "Could not save",
    );
    await expect(readError(envelope({ error: {} }), "Could not save")).resolves.toBe(
      "Could not save",
    );
    await expect(readError(envelope(null), "Could not save")).resolves.toBe("Could not save");
  });

  it("falls back rather than rendering a non-string message", async () => {
    // Found by writing this test: `?? fallback` only guards null/undefined,
    // so an object- or array-valued message was returned as-is, making the
    // declared `Promise<string>` a lie and putting a literal
    // "[object Object]" in front of the user. Each of these must reach the
    // fallback instead.
    for (const message of [null, undefined, { nested: "x" }, ["a", "b"], 42, ""]) {
      const resp = envelope({ error: { message } });
      const out = await readError(resp, "Could not save");

      expect(typeof out).toBe("string");
      expect(out).toBe("Could not save");
    }
  });

  it("keeps a message that is a real sentence, including a falsy-looking one", async () => {
    // Guard against over-correcting the above into a truthiness check that
    // would swallow a legitimate short message.
    await expect(readError(envelope({ error: { message: "0" } }), "fallback")).resolves.toBe("0");
  });

  it("reads the unreachable envelope that both transports synthesise", async () => {
    // The seam between lib/bff-fetch.ts and this module: a transport
    // failure must produce a real sentence, not the caller's generic
    // fallback, or H-17's fix stops being visible to the user.
    const { unreachable } = await import("@/lib/bff-fetch");

    await expect(readError(unreachable(), "Could not save")).resolves.toBe(
      "The server could not be reached. Check your connection and try again.",
    );
  });
});
