import { type NextRequest, NextResponse } from "next/server";

import { clearRefreshCookie, forwardAndIssueCookie } from "@/lib/bff-auth";
import { REFRESH_COOKIE } from "@/lib/bff-cookies";

/**
 * The browser calls this with no body — the refresh token lives only in the
 * HttpOnly cookie this route itself reads, never in anything client JS holds.
 */
export async function POST(request: NextRequest) {
  const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value;
  if (!refreshToken) {
    return NextResponse.json({ detail: "No session to refresh." }, { status: 401 });
  }

  const response = await forwardAndIssueCookie(
    request,
    "/api/v1/auth/refresh",
    JSON.stringify({ refresh_token: refreshToken }),
  );
  if (response.status === 401) {
    clearRefreshCookie(response);
  }
  return response;
}
