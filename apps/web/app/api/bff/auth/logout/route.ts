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
  if (refreshToken) {
    try {
      await fetch(`${API_URL}/api/v1/auth/logout`, {
        method: "POST",
        headers: authHeaders(request),
        body: JSON.stringify({ refresh_token: refreshToken }),
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
