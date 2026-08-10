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

async function forward(request: NextRequest, path: string[]): Promise<NextResponse> {
  const url = `${API_URL}/api/v1/${path.join("/")}${request.nextUrl.search}`;

  const headers: Record<string, string> = {
    "X-Tenant-Host": request.headers.get("host") ?? "localhost",
  };
  const auth = request.headers.get("authorization");
  if (auth) headers["Authorization"] = auth;
  const contentType = request.headers.get("content-type");
  if (contentType) headers["Content-Type"] = contentType;
  const fingerprint = request.headers.get("x-device-fingerprint");
  if (fingerprint) headers["X-Device-Fingerprint"] = fingerprint;

  // arrayBuffer, not text: a text() round-trip re-decodes/re-encodes as
  // UTF-8, which corrupts binary bodies — multipart file uploads
  // (payment-proof) in particular. JSON bodies pass through arrayBuffer
  // just as correctly, so there's no reason to special-case content-type.
  const body =
    request.method === "GET" || request.method === "HEAD" ? undefined : await request.arrayBuffer();

  const upstream = await fetch(url, { method: request.method, headers, body, cache: "no-store" });

  const responseBody = await upstream.arrayBuffer();
  return new NextResponse(responseBody.byteLength > 0 ? responseBody : null, {
    status: upstream.status,
    headers: {
      "Content-Type": upstream.headers.get("content-type") ?? "application/json",
    },
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
