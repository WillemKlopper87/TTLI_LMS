/**
 * One unauthenticated call to the BFF, and the contract both transports
 * share for a request that never arrives.
 *
 * `fetch` rejects when the request does not reach the server at all —
 * offline, DNS, a dead API, a cancelled connection. None of the public
 * forms in this app was written to catch that: each branches on
 * `resp.ok`, and the rejection sailed straight past the `setBusy(false)`
 * on the line before it, leaving the form permanently disabled with
 * nothing on screen to say why. That is what fable5.1 review H-17 saw as
 * "most busy patterns have no try/finally"; a `finally` alone would have
 * re-enabled the button and still shown the user nothing.
 *
 * So a transport failure resolves to a 503 carrying the API's own error
 * envelope — which is what "it never reached the server" honestly is —
 * and it goes down the failure branch every caller already has.
 * lib/authed-fetch.ts does the same with the same helper, so the two
 * transports cannot drift.
 */

export function unreachable(): Response {
  return new Response(
    JSON.stringify({
      error: {
        code: "SERVICE_UNAVAILABLE",
        message: "The server could not be reached. Check your connection and try again.",
      },
    }),
    { status: 503, headers: { "Content-Type": "application/json" } },
  );
}

/** For BFF routes that take no bearer: login, magic links, password
 * resets, lead capture. Anything authenticated wants
 * lib/authed-fetch.ts, which adds the token and the 401 replay. */
export function bffFetch(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(path, init).catch(unreachable);
}
