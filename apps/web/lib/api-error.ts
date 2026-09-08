/**
 * One reading of the API's error envelope (03 section 1.3), replacing five
 * byte-identical private copies that had accumulated across the admin
 * pages and the course wizard.
 *
 * Every refusal this app can provoke carries a specific, actionable reason
 * written server-side; the fallback is only for a response that is not the
 * envelope at all -- a proxy error page, or a network failure that never
 * produced JSON.
 */
export async function readError(resp: Response, fallback: string): Promise<string> {
  try {
    const body = await resp.json();
    const message = body?.error?.message;
    // `?? fallback` alone only guards null/undefined, so a non-string
    // message -- a validation payload that arrived as an object or array
    // rather than a sentence -- was returned as-is, making this function's
    // `Promise<string>` a lie and rendering "[object Object]" at the user.
    // Anything that isn't a usable sentence takes the fallback instead.
    return typeof message === "string" && message.trim() !== "" ? message : fallback;
  } catch {
    return fallback;
  }
}
