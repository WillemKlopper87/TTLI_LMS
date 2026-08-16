"use client";

/**
 * Shared session state, replacing the old module-level access token in
 * lib/session.ts. The access token still lives only in memory — it's the
 * refresh token that now persists (as an HttpOnly cookie the BFF manages),
 * which is what lets a page reload restore the session silently instead of
 * bouncing to /login, and lets a scheduled timer rotate the access token
 * before it actually expires.
 */
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";

import { setAccessToken as setLegacyAccessToken } from "@/lib/session";

type Status = "loading" | "authenticated" | "anonymous";

interface TokenPayload {
  access_token: string;
  expires_in: number;
}

interface SessionValue {
  accessToken: string | null;
  status: Status;
  setSession: (token: TokenPayload) => void;
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
 * including the winner's brand-new token. Three real triggers reach it:
 * React StrictMode's development double-mount, several tabs restoring at
 * once, and two tabs' scheduled timers firing together.
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

  function applyToken(token: TokenPayload) {
    if (timerRef.current) clearTimeout(timerRef.current);
    setAccessTokenState(token.access_token);
    setLegacyAccessToken(token.access_token);
    setStatus("authenticated");
    const delayMs = Math.max(token.expires_in * REFRESH_AT_FRACTION, MIN_REFRESH_DELAY_SECONDS) * 1000;
    timerRef.current = setTimeout(() => {
      void runRefresh();
    }, delayMs);
  }

  function clearToken() {
    if (timerRef.current) clearTimeout(timerRef.current);
    setAccessTokenState(null);
    setLegacyAccessToken(null);
    setStatus("anonymous");
  }

  async function runRefresh() {
    const { ok, payload } = await serialisedRefresh();
    if (cancelledRef.current) return;
    if (!ok || !payload) {
      clearToken();
      return;
    }
    applyToken(payload);
  }

  useEffect(() => {
    cancelledRef.current = false;
    void runRefresh();
    return () => {
      cancelledRef.current = true;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
    // Boot-time restore only — applyToken/runRefresh close over refs and
    // useState setters, both stable across renders, so this is safe to run
    // once rather than on every redefinition.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function logout() {
    if (timerRef.current) clearTimeout(timerRef.current);
    try {
      await fetch("/api/bff/auth/logout", { method: "POST", cache: "no-store" });
    } finally {
      clearToken();
    }
  }

  return (
    <SessionContext.Provider value={{ accessToken, status, setSession: applyToken, logout }}>
      {children}
    </SessionContext.Provider>
  );
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
