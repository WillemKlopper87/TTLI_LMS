import { type NextRequest, NextResponse } from "next/server";

import { forwardAndIssueCookie } from "@/lib/bff-auth";
import { SSO_BINDING_COOKIE, ssoBindingCookieOptions } from "@/lib/bff-cookies";

/**
 * Finishes a single-sign-on login: the code and state come from the
 * page's query string, the browser binding comes from the HttpOnly
 * cookie the start route set.
 *
 * A missing cookie is refused here rather than forwarded. The API would
 * refuse it too, but sending a request that cannot succeed spends the
 * caller's rate-limit budget and burns the one-use state record on the
 * way past.
 */
export async function POST(request: NextRequest) {
  const binding = request.cookies.get(SSO_BINDING_COOKIE)?.value;
  if (!binding) {
    return NextResponse.json(
      { detail: "That sign-in attempt did not start in this browser." },
      { status: 401 },
    );
  }

  const body = (await request.json()) as { code?: string; state?: string };
  const upstream = await forwardAndIssueCookie(
    request,
    "/api/v1/auth/sso/callback",
    JSON.stringify({ code: body.code, state: body.state }),
    { "X-Sso-Binding": binding },
  );

  // One use, win or lose. The API burns its half of the pair on every
  // outcome; leaving a live cookie behind would be the only surviving
  // piece of a finished flow.
  upstream.cookies.set(SSO_BINDING_COOKIE, "", {
    ...ssoBindingCookieOptions(),
    maxAge: 0,
  });
  return upstream;
}
