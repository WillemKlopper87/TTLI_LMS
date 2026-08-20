import { type NextRequest, NextResponse } from "next/server";

import { authHeaders, API_URL, clearRefreshCookie } from "@/lib/bff-auth";
import { REFRESH_COOKIE } from "@/lib/bff-cookies";

/**
 * Always clears the cookie and returns 204, even if the upstream call fails
 * or there was no session to begin with — logout must never leave the
 * browser believing it's still signed in.
 */
export async function POST(request: NextRequest) {
  const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value;
  // The Authorization header must reach the API: its logout denylists
  // the access token's jti, and without the header the bearer stays
  // live for its full TTL. Caught by the live smoke on 2026-08-20 —
  // pytest exercises the API directly and could never see this proxy
  // dropping the header (the Idempotency-Key line above tells the same
  // story). Also call upstream when there is a bearer but no cookie:
  // revoking the access token is worth doing even with no refresh
  // family left to revoke.
  const auth = request.headers.get("authorization");
  if (refreshToken || auth) {
    const headers = authHeaders(request);
    if (auth) headers["Authorization"] = auth;
    try {
      await fetch(`${API_URL}/api/v1/auth/logout`, {
        method: "POST",
        headers,
        body: JSON.stringify({ refresh_token: refreshToken ?? "" }),
        cache: "no-store",
      });
    } catch {
      // Best-effort — the cookie clears below regardless.
    }
  }

  const response = new NextResponse(null, { status: 204 });
  clearRefreshCookie(response);
  return response;
}
