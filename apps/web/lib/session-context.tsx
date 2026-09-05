"use client";

/**
 * Shared session state, replacing the old module-level access token in
 * lib/session.ts. The access token still lives only in memory — it's the
 * refresh token that now persists (as an HttpOnly cookie the BFF manages),
 * which is what lets a page reload restore the session silently instead of
 * bouncing to /login, and lets a scheduled timer rotate the access token
 * before it actually expires.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";

import {
  setAccessToken as setLegacyAccessToken,
  setSessionRefresher,
} from "@/lib/session";

type Status = "loading" | "authenticated" | "anonymous";

interface TokenPayload {
  access_token: string;
  expires_in: number;
}

interface SessionValue {
  accessToken: string | null;
  status: Status;
  setSession: (token: TokenPayload) => void;
  refreshSession: () => Promise<string | null>;
  logout: () => Promise<void>;
}

const SessionContext = createContext<SessionValue | null>(null);

// Refresh at 80% of the token's lifetime, not right at expiry — a request
// mid-flight when the token actually dies would otherwise fail for no
// user-visible reason. Floored at 5s so a short dev-config TTL can't spin.
const REFRESH_AT_FRACTION = 0.8;
const MIN_REFRESH_DELAY_SECONDS = 5;

/**
 * A refresh that fails because the session is over is a different event
 * from one that fails because the network blinked, and this used to treat
 * them identically: any non-2xx — a 503, a proxy hiccup, a half-deployed
 * API — dropped the provider to "anonymous" and bounced the user to /login
 * mid-session. Worse, a `fetch` rejection (offline, DNS, nothing
 * listening) was not caught at all: it propagated out of the boot-time
 * restore as an unhandled rejection, leaving `status` on "loading"
 * forever, which the admin shell renders as a blank page (fable5.1 review
 * H-17).
 *
 * So the three outcomes are named. Only `expired` ends a session.
 */
type RefreshOutcome = "ok" | "expired" | "unavailable";

interface RefreshResult {
  outcome: RefreshOutcome;
  payload: TokenPayload | null;
}

// How long to wait before retrying a refresh that failed transiently, in
// order. Bounded rather than endless: after roughly twelve seconds of a
// dead network a boot-time restore that has still produced no token
// settles to "anonymous", so the page can say something instead of
// rendering nothing at all.
const TRANSIENT_RETRY_DELAYS_MS = [1_000, 3_000, 8_000];

async function postRefresh(): Promise<RefreshResult> {
  let resp: Response;
  try {
    resp = await fetch("/api/bff/auth/refresh", { method: "POST", cache: "no-store" });
  } catch {
    // fetch rejects only for a transport failure. Nothing is known about
    // the session here, so nothing about it should change.
    return { outcome: "unavailable", payload: null };
  }
  // 401 is what the BFF answers for a missing or spent refresh cookie, 403
  // the API refusing the family outright (reuse detected, or the user
  // suspended). Both are authoritative answers about the session itself.
  if (resp.status === 401 || resp.status === 403) return { outcome: "expired", payload: null };
  if (!resp.ok) return { outcome: "unavailable", payload: null };
  try {
    return { outcome: "ok", payload: (await resp.json()) as TokenPayload };
  } catch {
    // A 200 whose body is not the token payload is a broken deployment,
    // not a signed-out user.
    return { outcome: "unavailable", payload: null };
  }
}

// Holds the in-flight refresh for the Web-Locks-less fallback path below.
let inFlightRefresh: Promise<RefreshResult> | null = null;

/**
 * Never let two refreshes race on the same cookie.
 *
 * A refresh *rotates* the refresh token: the presented one is consumed and a
 * successor issued. So a second caller presenting the same cookie looks to
 * the API exactly like a replayed token — and services/tokens.py::rotate
 * treats replay as theft, by design: it revokes the whole family and writes
 * a TOKEN_REUSE_DETECTED audit event. The user is signed out of every
 * device and the security log gains a false theft alert.
 *
 * That is not theoretical. Two concurrent POSTs to /api/bff/auth/refresh
 * were confirmed live to return 200 + 401 and leave the session dead —
 * including the winner's brand-new token. Four real triggers reach it:
 * React StrictMode's development double-mount, several tabs restoring at
 * once, two tabs' scheduled timers firing together, and — since
 * lib/authed-fetch.ts — several panels on one page each retrying a 401 in
 * the same tick.
 *
 * The fix belongs here, at the source of the concurrency — not in the API,
 * whose reuse detection is correct and load-bearing. Web Locks serialises
 * across every tab on this origin, so the second caller waits and then
 * presents the *rotated* cookie: a legitimate sequential rotation, not a
 * replay. Where Web Locks is unavailable (it needs a secure context;
 * localhost and HTTPS both qualify, so this is a belt-and-braces path) the
 * shared promise still collapses the same-tab case, which is the one a
 * single document can cause on its own.
 */
async function serialisedRefresh(): Promise<RefreshResult> {
  try {
    if (typeof navigator !== "undefined" && navigator.locks) {
      return await navigator.locks.request("ttli-auth-refresh", () => postRefresh());
    }
    if (!inFlightRefresh) {
      inFlightRefresh = postRefresh().finally(() => {
        inFlightRefresh = null;
      });
    }
    return await inFlightRefresh;
  } catch {
    // postRefresh no longer throws, so this is the lock itself failing — an
    // aborted or released request. Transient by nature, and the one
    // remaining way this function could have rejected into its callers.
    return { outcome: "unavailable", payload: null };
  }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [accessToken, setAccessTokenState] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>("loading");
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cancelledRef = useRef(false);
  // applyToken schedules the next rotation, which calls back into
  // refreshSession, which applies the token it gets — a cycle useCallback
  // cannot express directly. The ref breaks it without either callback
  // depending on the other, which is what keeps both stable for the whole
  // life of the provider (see the identity note on the value memo below).
  const refreshRef = useRef<() => Promise<string | null>>(async () => null);
  // How many transient failures the current run of retries has seen, and
  // whether a token is held at all. Refs, not state, because refreshSession
  // reads both and must stay referentially stable for the provider's whole
  // life — the boot effect below depends on exactly that.
  const transientAttemptsRef = useRef(0);
  const hasTokenRef = useRef(false);

  // One pending callback at a time, whether it is the scheduled rotation or
  // a retry after a transient failure, so the two can never both be armed
  // and refresh twice.
  const scheduleRefresh = useCallback((delayMs: number) => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      // refreshSession resolves rather than rejects for every failure it
      // knows about; a timer callback is the one place a stray rejection
      // would have nowhere to go but an unhandled-rejection log.
      void refreshRef.current().catch(() => undefined);
    }, delayMs);
  }, []);

  const applyToken = useCallback(
    (token: TokenPayload) => {
      setAccessTokenState(token.access_token);
      setLegacyAccessToken(token.access_token);
      hasTokenRef.current = true;
      setStatus("authenticated");
      const delayMs =
        Math.max(token.expires_in * REFRESH_AT_FRACTION, MIN_REFRESH_DELAY_SECONDS) * 1000;
      scheduleRefresh(delayMs);
    },
    [scheduleRefresh],
  );

  const clearToken = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    setAccessTokenState(null);
    setLegacyAccessToken(null);
    hasTokenRef.current = false;
    setStatus("anonymous");
  }, []);

  /**
   * Rotate now, and report the access token that resulted — or null if the
   * session is genuinely over, in which case the provider has already
   * dropped to "anonymous" and useRequireAuth's guard fires as usual.
   *
   * Returning the token, rather than only setting state, is what lets the
   * caller retry the request that provoked the refresh in the same tick:
   * `accessToken` from context is still the stale value until React has
   * re-rendered, so a 401 retry reading it from context would present the
   * dead token a second time. lib/authed-fetch.ts is the caller that needs
   * this; the boot-time and timer paths ignore the return value.
   */
  const refreshSession = useCallback(async (): Promise<string | null> => {
    const { outcome, payload } = await serialisedRefresh();
    if (cancelledRef.current) return null;

    if (outcome === "ok" && payload) {
      transientAttemptsRef.current = 0;
      applyToken(payload);
      return payload.access_token;
    }

    if (outcome === "expired") {
      transientAttemptsRef.current = 0;
      clearToken();
      return null;
    }

    // Transient: the session may well still be alive, so nothing is
    // cleared. Something must still schedule the next attempt, though —
    // without this, one blink left no rotation pending and the token simply
    // expired in silence.
    const delayMs = TRANSIENT_RETRY_DELAYS_MS[transientAttemptsRef.current];
    if (delayMs !== undefined) {
      transientAttemptsRef.current += 1;
      scheduleRefresh(delayMs);
      return null;
    }

    // Out of retries. Holding a live token, leave the session alone:
    // lib/authed-fetch.ts refreshes again on the next 401, which is a
    // better trigger than a timer against a network that is not answering.
    // Holding none, this was the boot-time restore, and "loading" would
    // otherwise be permanent — which the admin shell renders as an empty
    // page rather than a redirect.
    transientAttemptsRef.current = 0;
    if (!hasTokenRef.current) clearToken();
    return null;
  }, [applyToken, clearToken, scheduleRefresh]);

  useEffect(() => {
    refreshRef.current = refreshSession;
    // Publish the same refresh to the non-context mirror, so
    // lib/authed-fetch.ts can rotate a stale token without a second
    // implementation racing this one. Cleared on unmount so a torn-down
    // provider cannot be called back into.
    setSessionRefresher(refreshSession);
    return () => setSessionRefresher(null);
  }, [refreshSession]);

  useEffect(() => {
    cancelledRef.current = false;
    // The await sits inside the wrapper rather than being a bare call
    // because the lint rule reads a bare one as a synchronous setState in
    // an effect body (it is not — refreshSession's first statement is an
    // await); the catch is belt and braces now that refreshSession resolves
    // for every failure it knows about.
    void (async () => {
      await refreshSession().catch(() => undefined);
    })();
    return () => {
      cancelledRef.current = true;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
    // Boot-time restore only, and honestly declared rather than suppressed:
    // refreshSession is stable for the provider's whole lifetime, because
    // applyToken and clearToken close over refs and useState setters — both
    // stable across renders — so this effect never actually re-runs.
  }, [refreshSession]);

  const logout = useCallback(async () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    try {
      await fetch("/api/bff/auth/logout", { method: "POST", cache: "no-store" });
    } finally {
      clearToken();
    }
  }, [clearToken]);

  // Only accessToken and status ever actually change; all three callbacks
  // are stable. Memoising anyway ties the context value's own identity to
  // the data, so a consumer is not woken by an unrelated re-render of this
  // provider's parent.
  const value = useMemo<SessionValue>(
    () => ({ accessToken, status, setSession: applyToken, refreshSession, logout }),
    [accessToken, status, applyToken, refreshSession, logout],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used within a SessionProvider");
  return ctx;
}

/** Redirects to /login once the boot-time silent refresh has genuinely
 * failed — never before, so a mid-session reload never bounces a still-valid
 * session. */
export function useRequireAuth(): { accessToken: string | null; ready: boolean } {
  const { accessToken, status } = useSession();
  const router = useRouter();

  useEffect(() => {
    if (status === "anonymous") router.replace("/login");
  }, [status, router]);

  return { accessToken, ready: status !== "loading" };
}
