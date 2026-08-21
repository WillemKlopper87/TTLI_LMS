/**
 * The refresh-token cookie the BFF's auth routes set and read.
 *
 * The token itself never reaches browser JS — only these routes
 * (app/api/bff/auth/*) see it, which is why the cookie is scoped to that
 * path rather than the whole site.
 */

export const REFRESH_COOKIE = "rt";

// Mirrors apps/api/src/core/config.py settings.refresh_token_days. Not
// fetched from the API at request time — no config endpoint exposes it, and
// duplicating one integer is cheaper than building one for this.
const REFRESH_TOKEN_DAYS = 30;

export function refreshCookieOptions(): {
  httpOnly: true;
  secure: boolean;
  sameSite: "lax";
  path: string;
  maxAge: number;
} {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/api/bff/auth",
    maxAge: REFRESH_TOKEN_DAYS * 86400,
  };
}

/**
 * The single-sign-on browser binding (`apps/api/src/services/oidc.py`).
 *
 * The API mints this when a login starts and refuses the callback
 * without it, which is what stops an attacker completing their own
 * half-finished login inside somebody else's browser. It is HttpOnly
 * for the same reason the refresh token is: page JavaScript has no
 * business holding it, and an XSS that could read it could complete the
 * attack the binding exists to prevent.
 *
 * SameSite is Lax, not Strict. The identity provider returns the user
 * by a top-level cross-site navigation; Lax is the conventional and
 * sufficient setting for an OAuth state cookie, and Strict buys nothing
 * here because the cookie is only ever read by a same-origin fetch.
 *
 * Short-lived by design: it is worthless once the flow finishes, and
 * ten minutes matches STATE_TTL_SECONDS on the API side.
 */
export const SSO_BINDING_COOKIE = "sso_b";

export function ssoBindingCookieOptions(): {
  httpOnly: true;
  secure: boolean;
  sameSite: "lax";
  path: string;
  maxAge: number;
} {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/api/bff/auth",
    maxAge: 600,
  };
}
