import { type NextRequest, NextResponse } from "next/server";

import { API_URL, authHeaders } from "@/lib/bff-auth";
import { SSO_BINDING_COOKIE, ssoBindingCookieOptions } from "@/lib/bff-cookies";

/**
 * Begins a single-sign-on login and hands the browser the URL to follow.
 *
 * The API returns two things: the authorization URL, and a `binding`
 * secret. The binding is stripped here and parked in an HttpOnly cookie
 * — the same split the login route makes with `refresh_token`. Page
 * JavaScript never sees it, and the callback route below is the only
 * thing that reads it back.
 *
 * Note what is *not* forwarded: a redirect URI. The API derives that
 * from the tenant it resolved, and deliberately ignores anything a
 * caller says about it.
 */
export async function POST(request: NextRequest) {
  const next = new URL(request.url).searchParams.get("next");
  const query = next ? `?next=${encodeURIComponent(next)}` : "";

  const upstream = await fetch(`${API_URL}/api/v1/auth/sso/start${query}`, {
    method: "POST",
    headers: authHeaders(request),
    cache: "no-store",
  });

  const text = await upstream.text();
  if (!upstream.ok) {
    return new NextResponse(text, {
      status: upstream.status,
      headers: {
        "Content-Type":
          upstream.headers.get("content-type") ?? "application/json",
      },
    });
  }

  const { binding, ...rest } = JSON.parse(text) as {
    binding?: string;
    authorization_url?: string;
  };
  const response = NextResponse.json(rest, { status: upstream.status });
  if (typeof binding === "string") {
    response.cookies.set(
      SSO_BINDING_COOKIE,
      binding,
      ssoBindingCookieOptions(),
    );
  }
  return response;
}
