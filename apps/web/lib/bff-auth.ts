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
  const payload = text ? JSON.parse(text) : null;

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
