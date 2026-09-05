/**
 * One authenticated fetch, replacing nineteen private copies.
 *
 * Every client page that talks to the BFF had grown its own four-line
 * `authedFetch`: read the in-memory access token, set an Authorization
 * header, call fetch. All nineteen were the same four lines, and none of
 * them handled the one case that actually matters — a token that has gone
 * stale between render and click.
 *
 * That gap was small but real. The access token is rotated on a timer at
 * 80% of its lifetime (lib/session-context.tsx), which covers an idle tab.
 * It does not cover a request already in flight when the token dies, a tab
 * that was suspended by the OS and woke with a dead token, or a clock that
 * jumped. In each of those the old copies simply surfaced a 401 to the
 * user as "could not be loaded", with a still-valid refresh cookie sitting
 * unused in the browser.
 *
 * So: on 401, refresh once and replay the request with the new token.
 *
 * A plain module function rather than a hook, deliberately. The wizard's
 * shared api module (app/admin/courses/wizard-api.ts) is imported by 16
 * files at 94 call sites and is not a component, so a hook could not serve
 * it without threading a callback through all of them. A module function
 * serves component and module callers alike, and — because its identity
 * never changes — it drops out of dependency arrays entirely instead of
 * re-triggering effects every time the token rotates.
 */
import { unreachable } from "@/lib/bff-fetch";
import { getAccessToken, refreshAccessToken } from "@/lib/session";

function withBearer(init: RequestInit, token: string): RequestInit {
  // `RequestInit.headers` may be a Headers instance or tuple array, neither
  // of which survives object spread correctly. Normalise through the web
  // platform class, preserving every caller-supplied header before setting
  // the one this transport owns.
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  return { ...init, headers };
}

export async function authedFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = getAccessToken();
  const resp = await fetch(path, withBearer(init, token ?? "")).catch(unreachable);
  if (resp.status !== 401) return resp;

  // Only retry a request that actually presented a token. A 401 on a
  // request sent with no token at all is not a stale token — it is an
  // anonymous caller, or a boot-time restore still in flight, and the
  // provider owns both of those paths already. Refreshing here would add a
  // pointless rotation on every anonymous page load.
  if (!token) return resp;

  const refreshed = await refreshAccessToken();
  // Genuinely signed out: the provider has already dropped to "anonymous",
  // so useRequireAuth redirects. Hand back the original 401 so a caller
  // that renders its own signed-out state still sees one.
  if (!refreshed) return resp;

  return fetch(path, withBearer(init, refreshed)).catch(unreachable);
}
