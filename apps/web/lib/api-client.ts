/**
 * A typed client for browser components, built on the generated OpenAPI
 * contract instead of hand-rolled `fetch` + hand-written interfaces.
 *
 * `packages/api-client`'s generated types describe the real API — routes,
 * request bodies, response shapes — regenerated and drift-checked in CI on
 * every schema change (`.github/workflows/ci.yml`'s "api-client drift"
 * step). Almost nothing in this app actually consumed them: one server-side
 * helper imports `createApiClient` for a single call, and every client
 * component instead hand-rolls its own `fetch` + interface per page. That
 * meant the drift gate proved the *generated artifact* matched the
 * backend, never that a given *page* did — a field rename could stay
 * green in CI and still break a screen at runtime.
 *
 * This file is the client-side half of closing that gap: one typed client,
 * wired to the same `authedFetch` transport (token attach + refresh-and-
 * replay-once on a stale 401) every other authenticated call already uses,
 * routed through the BFF the way browser calls always have to be. Nothing
 * about `authedFetch`'s own behaviour changes — this only gives it a typed
 * front door.
 *
 * `openapi-fetch` builds requests against `baseUrl + schemaPath`, and the
 * generated schema's paths are the real API's own (`/api/v1/...`) — but a
 * browser must call the BFF (`/api/bff/...`), which itself prepends
 * `/api/v1` before forwarding (`app/api/bff/[...path]/route.ts`). The
 * custom `fetch` below is exactly that one rewrite, otherwise a pass-
 * through to `authedFetch`.
 */
import createClient from "openapi-fetch";
import type { paths } from "@ttli/api-client";

import { authedFetch } from "@/lib/authed-fetch";

async function bffFetch(request: Request): Promise<Response> {
  const url = new URL(request.url);
  const bffPath = url.pathname.replace(/^\/api\/v1/, "/api/bff") + url.search;
  const init: RequestInit = { method: request.method, headers: request.headers };
  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = await request.arrayBuffer();
  }
  return authedFetch(bffPath, init);
}

/** Singleton, matching `authedFetch` itself: no per-call setup, safe to
 * import from any client component or module. `baseUrl` is empty on
 * purpose — every generated schema path already starts with `/api/v1`
 * (openapi-typescript keeps the real API's own paths verbatim), so a
 * non-empty `baseUrl` here would double it. A relative path still
 * resolves to a same-origin absolute URL when `Request` constructs it,
 * which is all `bffFetch` needs to read `.pathname` and rewrite it. */
export const api = createClient<paths>({ baseUrl: "", fetch: bffFetch });

/** The one error-envelope shape every non-2xx response uses
 * (`apps/api/src/core/errors.py::error_envelope`). `openapi-fetch` doesn't
 * type this precisely per-endpoint (this codebase's error responses aren't
 * declared in each route's OpenAPI `responses=`), so callers get `unknown`
 * back — this is the one place that shape is asserted, instead of every
 * page re-deriving its own `body?.error?.message ?? "fallback"` guess. */
interface ApiErrorEnvelope {
  error: { code: string; message: string; details: Record<string, unknown>; request_id: string };
}

function isApiErrorEnvelope(value: unknown): value is ApiErrorEnvelope {
  return (
    typeof value === "object" &&
    value !== null &&
    "error" in value &&
    typeof (value as { error: unknown }).error === "object" &&
    (value as { error: unknown }).error !== null &&
    "message" in (value as { error: { message?: unknown } }).error
  );
}

/** `openapi-fetch` splits every response into `{ data, error, response }` —
 * `error` is present exactly when `!response.ok`. Pass whichever of the two
 * `error` came back as (some paths, this schema included, don't have a
 * typed error case, so it can be `undefined` even on failure); the fallback
 * covers that and anything that isn't the envelope shape at all (a network
 * failure never reaches this — it throws — but a non-JSON 502 from
 * somewhere in front of the API could still land here). */
export function apiErrorMessage(error: unknown, fallback = "Something went wrong."): string {
  return isApiErrorEnvelope(error) ? error.error.message : fallback;
}
