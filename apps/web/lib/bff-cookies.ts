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
