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

interface RefreshResult {
  ok: boolean;
  payload: TokenPayload | null;
}

async function postRefresh(): Promise<RefreshResult> {
  const resp = await fetch("/api/bff/auth/refresh", { method: "POST", cache: "no-store" });
  if (!resp.ok) return { ok: false, payload: null };
  return { ok: true, payload: (await resp.json()) as TokenPayload };
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
  if (typeof navigator !== "undefined" && navigator.locks) {
    return navigator.locks.request("ttli-auth-refresh", () => postRefresh());
  }
  if (!inFlightRefresh) {
    inFlightRefresh = postRefresh().finally(() => {
      inFlightRefresh = null;
    });
  }
  return inFlightRefresh;
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

  const applyToken = useCallback((token: TokenPayload) => {
    if (timerRef.current) clearTimeout(timerRef.current);
    setAccessTokenState(token.access_token);
    setLegacyAccessToken(token.access_token);
    setStatus("authenticated");
    const delayMs =
      Math.max(token.expires_in * REFRESH_AT_FRACTION, MIN_REFRESH_DELAY_SECONDS) * 1000;
    timerRef.current = setTimeout(() => {
      void refreshRef.current();
    }, delayMs);
  }, []);

  const clearToken = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    setAccessTokenState(null);
    setLegacyAccessToken(null);
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
    const { ok, payload } = await serialisedRefresh();
    if (cancelledRef.current) return null;
    if (!ok || !payload) {
      clearToken();
      return null;
    }
    applyToken(payload);
    return payload.access_token;
  }, [applyToken, clearToken]);

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
    void refreshSession();
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
