"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { type ReactNode, useEffect, useState } from "react";

import { getAccessToken } from "@/lib/session";
import type { Theme } from "@/lib/server-api";

import { AdminContext, type Me } from "./admin-context";

// The Phase 1 "empty admin shell": navigation that exists but leads nowhere
// yet, and proof of who is signed in. Sections fill in with their phase —
// "Leads" (Phase 2) is the first one that does.
const INERT_SECTIONS = ["Courses", "Learners", "Orders", "Reports", "Settings"];

export default function AdminLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [me, setMe] = useState<Me | null>(null);
  const [theme, setTheme] = useState<Theme | null>(null);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) {
      router.replace("/");
      return;
    }
    fetch("/api/bff/auth/me", { headers: { Authorization: `Bearer ${token}` } })
      .then(async (resp) => {
        if (!resp.ok) throw new Error("unauthenticated");
        setMe(await resp.json());
      })
      .catch(() => router.replace("/"));
    fetch("/api/bff/tenant/theme")
      .then(async (resp) => (resp.ok ? setTheme(await resp.json()) : null))
      .catch(() => undefined);
  }, [router]);

  if (!me) return null;

  return (
    <div className="flex min-h-screen">
      <aside
        className="w-56 shrink-0 p-4 text-white"
        style={{ backgroundColor: "var(--brand-primary)" }}
      >
        <Link href="/admin" className="mb-8 block">
          {theme?.logo_url ? (
            <Image
              src={theme.logo_url}
              alt={theme.tenant_name}
              width={160}
              height={84}
              className="max-w-full"
            />
          ) : (
            <span className="text-lg font-semibold">{theme?.tenant_name ?? me.tenant_slug}</span>
          )}
        </Link>
        <nav className="space-y-1">
          <Link
            href="/admin/leads"
            className={`block rounded-md px-3 py-2 text-sm ${
              pathname === "/admin/leads" ? "bg-white/15 font-medium" : "hover:bg-white/10"
            }`}
          >
            Leads
          </Link>
          {INERT_SECTIONS.map((section) => (
            <div
              key={section}
              className="cursor-not-allowed rounded-md px-3 py-2 text-sm opacity-70"
              title="Arrives with its phase"
            >
              {section}
            </div>
          ))}
        </nav>
      </aside>
      <main className="flex-1 p-8">
        <AdminContext.Provider value={{ me, theme }}>{children}</AdminContext.Provider>
      </main>
    </div>
  );
}
