"use client";

/**
 * Minimal shared header for learner-facing pages (/learn, /account,
 * /organisations) — the only affordance those pages had for signing out
 * until now was closing the tab. Renders nothing while signed out, so it's
 * invisible on /login, /catalogue, and marketing pages.
 */
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useSession } from "@/lib/session-context";

export function SiteHeader() {
  const { accessToken, status, logout } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const [email, setEmail] = useState<string | null>(null);

  useEffect(() => {
    if (status !== "authenticated" || !accessToken) {
      setEmail(null);
      return;
    }
    let cancelled = false;
    fetch("/api/bff/auth/me", { headers: { Authorization: `Bearer ${accessToken}` } })
      .then((resp) => (resp.ok ? resp.json() : null))
      .then((me) => {
        if (!cancelled) setEmail(me?.email ?? null);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [status, accessToken]);

  // The admin shell (app/admin/layout.tsx) has its own sidebar with its own
  // sign-out entry — a second one up top would be redundant there.
  if (status !== "authenticated" || pathname?.startsWith("/admin")) return null;

  async function handleLogout() {
    await logout();
    router.push("/login");
  }

  return (
    <header
      className="flex items-center justify-between px-4 py-3"
      style={{ borderBottom: "1px solid var(--rule)" }}
    >
      {email ? <span style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>{email}</span> : <span />}
      <button type="button" onClick={handleLogout} className="btn btn--ghost">
        Sign out
      </button>
    </header>
  );
}
