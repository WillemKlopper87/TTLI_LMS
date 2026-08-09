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

  const body = request.method === "GET" || request.method === "HEAD"
    ? undefined
    : await request.text();

  const upstream = await fetch(url, { method: request.method, headers, body, cache: "no-store" });

  const responseBody = await upstream.text();
  return new NextResponse(responseBody.length > 0 ? responseBody : null, {
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
