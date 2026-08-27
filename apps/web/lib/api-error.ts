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
    return body?.error?.message ?? fallback;
  } catch {
    return fallback;
  }
}
