import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Security headers (04 §3) on every response, plus a per-request CSP
 * nonce. Next.js auto-detects a `nonce-` source in the CSP header and
 * applies it to its own inline hydration/RSC-streaming scripts — see
 * https://nextjs.org/docs/app/guides/content-security-policy — so
 * `script-src` stays strict (no `unsafe-inline`, no `unsafe-eval`)
 * without any extra plumbing beyond this file.
 *
 * `style-src` keeps `unsafe-inline`: this app uses React's inline
 * `style` prop pervasively (see app/checkout, app/page.tsx, etc.), and
 * Next's nonce mechanism doesn't cover style attributes the way it
 * covers its own script tags. Inline style injection is a real but
 * lower-severity vector than script injection, and every inline style
 * in this app is a literal, never user-supplied data — revisit if that
 * changes.
 */
function generateNonce(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary);
}

export function proxy(request: NextRequest) {
  const nonce = generateNonce();
  const isProd = process.env.NODE_ENV === "production";

  const csp = [
    `default-src 'self'`,
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'`,
    `style-src 'self' 'unsafe-inline'`,
    `img-src 'self' data:`,
    `font-src 'self'`,
    `connect-src 'self'`,
    `frame-ancestors 'none'`,
    `base-uri 'self'`,
    `form-action 'self'`,
    ...(isProd ? ["upgrade-insecure-requests"] : []),
  ].join("; ");

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", csp);
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("X-Frame-Options", "DENY");
  response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  response.headers.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  // HSTS only has any effect over HTTPS — sending it in local dev over
  // http is harmless (browsers ignore it), but it's gated anyway so a
  // stray dev header never gets mistaken for a production guarantee.
  if (isProd) {
    response.headers.set(
      "Strict-Transport-Security",
      "max-age=63072000; includeSubDomains; preload"
    );
  }
  return response;
}

export const config = {
  matcher: [
    // Skip static assets — headers matter for pages and API responses,
    // not cached binary files that never execute anything.
    "/((?!_next/static|_next/image|favicon.ico|icon.png).*)",
  ],
};
