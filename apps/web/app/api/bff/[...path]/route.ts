/**
 * The BFF proxy: the only path from the browser to the API.
 *
 * It sets X-Tenant-Host from the request's own Host header — and by doing so
 * DROPS any inbound X-Tenant-Host a client tried to smuggle in, which is the
 * web tier's half of the tenancy contract (04 §2.4 / HANDOFF weakness 5).
 * It also keeps the API off the browser's origin, so no CORS surface exists.
 */
import { type NextRequest, NextResponse } from "next/server";

const API_URL = process.env.API_URL ?? "http://localhost:8010";

const RESPONSE_HEADER_ALLOWLIST = [
  "content-disposition",
  "cache-control",
  "etag",
  "last-modified",
  "retry-after",
];

async function forward(request: NextRequest, path: string[]): Promise<NextResponse> {
  const url = `${API_URL}/api/v1/${path.join("/")}${request.nextUrl.search}`;

  const headers: Record<string, string> = {
    "X-Tenant-Host": request.headers.get("host") ?? "localhost",
  };
  // Same overwrite-not-append stance as X-Tenant-Host: the value is what
  // Next's own server observed (it populates x-forwarded-for from the
  // socket), never something the browser chose. The API only honours it
  // when TRUST_X_FORWARDED_FOR says this proxy is the sole path in —
  // see apps/api/src/core/net.py. Without this, every per-IP rate limit
  // saw one shared address for the entire site.
  const clientAddr = request.headers.get("x-forwarded-for");
  if (clientAddr) headers["X-Forwarded-For"] = clientAddr;
  const auth = request.headers.get("authorization");
  if (auth) headers["Authorization"] = auth;
  const contentType = request.headers.get("content-type");
  if (contentType) headers["Content-Type"] = contentType;
  const fingerprint = request.headers.get("x-device-fingerprint");
  if (fingerprint) headers["X-Device-Fingerprint"] = fingerprint;
  // core/idempotency.py's middleware requires this on a handful of
  // commerce endpoints (03 §1.6) — dropped here like every other header
  // not on this explicit allowlist, so it never reached the API at all
  // until this line existed. Caught live: every curl test against the
  // API directly passed, but the same request through this proxy 400'd
  // with IDEMPOTENCY_KEY_REQUIRED — pytest's ASGI transport and manual
  // API-only curl checks both bypass this proxy, so neither could have
  // caught it; only a request through the real browser path could.
  const idempotencyKey = request.headers.get("idempotency-key");
  if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;

  // arrayBuffer, not text: a text() round-trip re-decodes/re-encodes as
  // UTF-8, which corrupts binary bodies — multipart file uploads
  // (payment-proof) in particular. JSON bodies pass through arrayBuffer
  // just as correctly, so there's no reason to special-case content-type.
  const body =
    request.method === "GET" || request.method === "HEAD" ? undefined : await request.arrayBuffer();

  const upstream = await fetch(url, { method: request.method, headers, body, cache: "no-store" });

  const responseBody = await upstream.arrayBuffer();
  const responseHeaders: Record<string, string> = {
    "Content-Type": upstream.headers.get("content-type") ?? "application/json",
  };
  // Safe response metadata only — never a hop-by-hop, cookie, or other
  // header that would let the API set state in the browser's own origin
  // (that's the refresh cookie's job, scoped to /api/bff/auth, not this
  // proxy). Downloads (invoices, credentials, CSV exports) need
  // Content-Disposition for their filename; the others are cheap,
  // standard wins (correct caching/conditional-request behaviour,
  // honouring a 429/503's Retry-After) that silently vanished for every
  // endpoint until now, not just the ones with their own download helper.
  for (const name of RESPONSE_HEADER_ALLOWLIST) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders[name] = value;
  }
  return new NextResponse(responseBody.byteLength > 0 ? responseBody : null, {
    status: upstream.status,
    headers: responseHeaders,
  });
}

type Context = { params: Promise<{ path: string[] }> };

export async function GET(request: NextRequest, context: Context) {
  return forward(request, (await context.params).path);
}

export async function POST(request: NextRequest, context: Context) {
  return forward(request, (await context.params).path);
}

export async function PATCH(request: NextRequest, context: Context) {
  return forward(request, (await context.params).path);
}

// DELETE joined the allowlist with the course wizard (`DELETE /modules/{id}`,
// `/lessons/{id}`, `/lessons/{id}/activity`, `/catalogue/prices/{id}`) —
// Next answers 405 for any method a route file doesn't export, so without
// this the browser never reached the API at all.
export async function DELETE(request: NextRequest, context: Context) {
  return forward(request, (await context.params).path);
}
