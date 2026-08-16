/**
 * Read-only mirror of the access token held by lib/session-context.tsx.
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
