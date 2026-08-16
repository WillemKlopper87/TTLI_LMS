/**
 * Shared plumbing for the auth-aware BFF routes (app/api/bff/auth/*).
 *
 * Unlike the generic catch-all proxy, these routes read the response body —
 * a raw pass-through can't split refresh_token out of it — so they forward
 * JSON, not arbitrary bytes. Every auth request/response in this API is
 * JSON, so that's not a loss of generality the way it would be for the
 * catch-all (which also carries multipart payment-proof uploads).
 */
import { type NextRequest, NextResponse } from "next/server";

import { REFRESH_COOKIE, refreshCookieOptions } from "@/lib/bff-cookies";

export const API_URL = process.env.API_URL ?? "http://localhost:8010";

export function authHeaders(request: NextRequest): Record<string, string> {
  const headers: Record<string, string> = {
    "X-Tenant-Host": request.headers.get("host") ?? "localhost",
    "Content-Type": "application/json",
  };
  const fingerprint = request.headers.get("x-device-fingerprint");
  if (fingerprint) headers["X-Device-Fingerprint"] = fingerprint;
  return headers;
}

/**
 * POST `body` to `apiPath` and relay the response. When the upstream body
 * carries a refresh_token (a 200 TokenResponse — not the 202 MFA-challenge
 * shape, and not an error), it's set as the HttpOnly cookie and stripped
 * before the JSON reaches the browser.
 */
export async function forwardAndIssueCookie(
  request: NextRequest,
  apiPath: string,
  body: BodyInit,
): Promise<NextResponse> {
  const upstream = await fetch(`${API_URL}${apiPath}`, {
    method: "POST",
    headers: authHeaders(request),
    body,
    cache: "no-store",
  });

  const text = await upstream.text();

  // Not every upstream body is JSON, even though every *designed* auth
  // response is. An unhandled 500 from the API (or anything between it and
  // here) can return plain text — "Internal Server Error" — and parsing it
  // blindly throws inside this route, turning a clean, diagnosable upstream
  // status into an opaque Next.js 500 with a stack trace and no hint of the
  // real cause. Seen for real: a dead Redis made /auth/login 500 in plain
  // text, and the browser got a JSON.parse SyntaxError instead of the
  // upstream's own status. Pass such a body straight through with its
  // original status and content type; the catch-all proxy next door, which
  // never parses anything, has always behaved this way.
  let payload: Record<string, unknown> | null = null;
  if (text) {
    try {
      payload = JSON.parse(text) as Record<string, unknown>;
    } catch {
      return new NextResponse(text, {
        status: upstream.status,
        headers: {
          "Content-Type": upstream.headers.get("content-type") ?? "text/plain",
        },
      });
    }
  }

  if (payload && typeof payload.refresh_token === "string") {
    const { refresh_token, ...rest } = payload;
    const response = NextResponse.json(rest, { status: upstream.status });
    response.cookies.set(REFRESH_COOKIE, refresh_token, refreshCookieOptions());
    return response;
  }

  return NextResponse.json(payload, { status: upstream.status });
}

export function clearRefreshCookie(response: NextResponse): void {
  response.cookies.set(REFRESH_COOKIE, "", { ...refreshCookieOptions(), maxAge: 0 });
}
