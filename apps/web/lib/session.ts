/**
 * Read-only mirror of the session held by lib/session-context.tsx.
 *
 * The context (SessionProvider) is the source of truth — it drives the
 * scheduled-refresh timer and the boot-time silent restore from the
 * HttpOnly refresh cookie, and calls setAccessToken() below on every change.
 * This module exists only so the many components that just need the token
 * for an Authorization header (not a reactive re-render, not the redirect
 * guard — see useRequireAuth in session-context.tsx) don't have to be
 * rewired into the context individually. Still a module variable, never
 * storage — 04 §1.2.
 */

let accessToken: string | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

type Refresher = () => Promise<string | null>;

let refresher: Refresher | null = null;

/**
 * The provider registers its own refresh here for the same reason it
 * mirrors the token: so a non-component caller can reach it.
 *
 * lib/authed-fetch.ts is the caller — it needs to rotate a stale token and
 * replay the request, and it has to be a plain function (the course
 * wizard's shared api module is not a component). Routing through this
 * registration keeps the *real* refresh in one place: the provider's, which
 * serialises on Web Locks, applies the new token to React state and the
 * mirror together, and drops the session to "anonymous" when the refresh
 * cookie is finally spent. A second implementation here would reintroduce
 * exactly the token-rotation race session-context.tsx documents at length.
 */
export function setSessionRefresher(fn: Refresher | null): void {
  refresher = fn;
}

/** The new access token, or null if the session could not be renewed —
 * including the case where no provider is mounted at all. */
export function refreshAccessToken(): Promise<string | null> {
  return refresher ? refresher() : Promise.resolve(null);
}
