/**
 * Access-token holder. 04 §1.2: the access token lives in SPA memory — a
 * module variable, never storage — so a page refresh simply asks you to log
 * in again. The HttpOnly-cookie-via-BFF refresh flow arrives with the funnel
 * phase; this is the Phase 1 shell.
 */

let accessToken: string | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}
