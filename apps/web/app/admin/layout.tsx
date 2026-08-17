"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { type ReactNode, useEffect, useState } from "react";

import { useRequireAuth, useSession } from "@/lib/session-context";
import type { Theme } from "@/lib/server-api";

import { AdminContext, type Me } from "./admin-context";

// The Phase 1 "empty admin shell": navigation that exists but leads nowhere
// yet, and proof of who is signed in. Sections fill in with their phase —
// "Leads" (Phase 2), "Payments" (Phase 3, REQ-PAY-03's finance queue),
// "Settings" (Phase 5 sprint 2, REQ-TEN-03's manager-visibility toggles),
// "Courses"/"Templates" (Phase 4's authoring gap, closed after Phase 5),
// "Grading" (frontend-completeness backlog item 3), and "Subscriptions"
// (multi-tier subscription plan authoring, REQ-PAY-12) are the ones that
// do so far.
const WORKING_SECTIONS = [
  { label: "Leads", href: "/admin/leads" },
  { label: "Deals", href: "/admin/deals" },
  { label: "Campaigns", href: "/admin/campaigns" },
  { label: "Payments", href: "/admin/payments" },
  { label: "Analytics", href: "/admin/analytics" },
  { label: "Workshops", href: "/admin/workshops" },
  { label: "Courses", href: "/admin/courses" },
  { label: "Catalogue", href: "/admin/catalogue" },
  { label: "Podcasts", href: "/admin/podcasts" },
  { label: "Articles", href: "/admin/articles" },
  { label: "Recommendations", href: "/admin/recommendations" },
  { label: "Grading", href: "/admin/grading" },
  { label: "Subscriptions", href: "/admin/subscriptions" },
  { label: "Templates", href: "/admin/templates" },
  { label: "Settings", href: "/admin/settings" },
];
const INERT_SECTIONS = ["Learners", "Reports"];

export default function AdminLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { accessToken, ready } = useRequireAuth();
  const { logout } = useSession();
  const [me, setMe] = useState<Me | null>(null);
  const [theme, setTheme] = useState<Theme | null>(null);

  useEffect(() => {
    if (!ready || !accessToken) return;
    fetch("/api/bff/auth/me", { headers: { Authorization: `Bearer ${accessToken}` } })
      .then(async (resp) => {
        if (!resp.ok) throw new Error("unauthenticated");
        setMe(await resp.json());
      })
      .catch(() => router.replace("/login"));
    fetch("/api/bff/tenant/theme")
      .then(async (resp) => (resp.ok ? setTheme(await resp.json()) : null))
      .catch(() => undefined);
  }, [ready, accessToken, router]);

  async function handleLogout() {
    await logout();
    router.replace("/login");
  }

  if (!me) return null;

  return (
    <div className="flex min-h-screen">
      <aside
        className="w-56 shrink-0 p-4"
        style={{
          background: `linear-gradient(165deg, var(--brand) 0%, var(--brand-deep) 100%)`,
          color: "var(--on-brand)",
        }}
      >
        {/* Same explicit-colour reason as the nav links below: a tenant
            with no logo falls back to its name as text inside this <a>,
            which would otherwise inherit --brand-ink on the brand
            gradient and disappear (the `acme` demo tenant has no logo). */}
        <Link href="/admin" className="mb-8 block" style={{ color: "var(--on-brand)" }}>
          {theme?.logo_url ? (
            <Image
              src={theme.logo_url}
              alt={theme.tenant_name}
              width={160}
              height={84}
              className="max-w-full"
            />
          ) : (
            <span className="serif" style={{ fontSize: "1.0625rem", fontWeight: 600 }}>
              {theme?.tenant_name ?? me.tenant_slug}
            </span>
          )}
        </Link>
        <nav className="space-y-1">
          {WORKING_SECTIONS.map((section) => (
            <Link
              key={section.href}
              href={section.href}
              className="block rounded-md px-3 py-2 text-sm"
              // `color` must be set explicitly, not inherited from the
              // <aside>: globals.css has a site-wide `a { color:
              // var(--brand-ink) }`, and any direct declaration beats an
              // inherited value regardless of specificity. Without this the
              // links render in --brand-ink (#8e151c) on the --brand
              // (#8e151c) gradient — the exact same colour, 1:1 contrast,
              // completely invisible. The neighbouring Learners/Reports
              // <div>s and the Sign out <button> were always fine precisely
              // because no element rule targets them, which is what made
              // this look like "only the nav links vanished".
              style={
                pathname === section.href
                  ? {
                      background: "rgba(255,255,255,0.15)",
                      fontWeight: 600,
                      color: "var(--on-brand)",
                    }
                  : { opacity: 0.85, color: "var(--on-brand)" }
              }
            >
              {section.label}
            </Link>
          ))}
          {INERT_SECTIONS.map((section) => (
            <div
              key={section}
              className="cursor-not-allowed rounded-md px-3 py-2 text-sm"
              // 0.6 opacity white-on-brand read at 3.55:1 against
              // --brand-deep — below WCAG AA's 4.5:1 for normal text.
              // 0.85 clears 4.6:1 against both ends of the brand
              // gradient; cursor-not-allowed + aria-disabled + the title
              // tooltip carry the "not yet available" meaning instead of
              // relying on a low-contrast dim alone.
              style={{ opacity: 0.85, fontStyle: "italic" }}
              aria-disabled="true"
              title="Arrives with its phase"
            >
              {section}
            </div>
          ))}
        </nav>
        <button
          type="button"
          onClick={handleLogout}
          className="mt-8 block w-full rounded-md px-3 py-2 text-left text-sm"
          style={{ opacity: 0.85 }}
        >
          Sign out
        </button>
      </aside>
      <main className="flex-1 p-8">
        <AdminContext.Provider value={{ me, theme }}>{children}</AdminContext.Provider>
      </main>
    </div>
  );
}
