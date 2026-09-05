"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { type ReactNode, useEffect, useState } from "react";

import { authedFetch } from "@/lib/authed-fetch";
import type { Theme } from "@/lib/server-api";
import { browserThemeAssetUrl } from "@/lib/theme-assets";
import { useRequireAuth, useSession } from "@/lib/session-context";

import { AdminContext, type Me } from "./admin-context";

// The Phase 1 "empty admin shell": navigation that exists but leads nowhere
// yet, and proof of who is signed in. Sections fill in with their phase —
// "Leads" (Phase 2), "Payments" (Phase 3, REQ-PAY-03's finance queue),
// "Settings" (Phase 5 sprint 2, REQ-TEN-03's manager-visibility toggles),
// "Courses"/"Templates" (Phase 4's authoring gap, closed after Phase 5),
// "Grading" (frontend-completeness backlog item 3), "Subscriptions"
// (multi-tier subscription plan authoring, REQ-PAY-12) and "Reports"
// (Pass A's course analytics) are the ones that do so far.
// `permission` (optional) hides a section from the sidebar entirely for
// anyone who doesn't hold it, rather than showing a link that 403s on
// click — the distinction the super_admin-only "Platform" section needs
// (deploy/maintenance/system-health concerns a business admin shouldn't
// even see exist, not just can't open).
const WORKING_SECTIONS: { label: string; href: string; permission?: string }[] = [
  { label: "Leads", href: "/admin/leads" },
  { label: "Deals", href: "/admin/deals" },
  { label: "Campaigns", href: "/admin/campaigns" },
  { label: "Payments", href: "/admin/payments", permission: "payment:approve" },
  { label: "Analytics", href: "/admin/analytics", permission: "analytics:view" },
  { label: "Reports", href: "/admin/reports/courses" },
  { label: "Audit log", href: "/admin/audit", permission: "audit:read" },
  { label: "People", href: "/admin/people" },
  { label: "Workshops", href: "/admin/workshops" },
  { label: "Courses", href: "/admin/courses" },
  { label: "Learning paths", href: "/admin/paths" },
  { label: "Catalogue", href: "/admin/catalogue" },
  { label: "Podcasts", href: "/admin/podcasts" },
  { label: "Articles", href: "/admin/articles" },
  { label: "Recommendations", href: "/admin/recommendations" },
  { label: "Grading", href: "/admin/grading", permission: "quiz:grade" },
  { label: "Surveys", href: "/admin/surveys" },
  { label: "Question bank", href: "/admin/question-bank" },
  { label: "Subscriptions", href: "/admin/subscriptions" },
  { label: "Templates", href: "/admin/templates" },
  { label: "Settings", href: "/admin/settings", permission: "settings:manage" },
  { label: "Platform", href: "/admin/platform", permission: "settings:manage" },
];

/* Everything guest/learner hold (migration 0002's ROLES). Holding only
   these means the caller is a learner, not staff — every staff role
   carries at least one permission outside this set, so a permission
   added later counts as staff automatically rather than silently
   admitting learners. */
const LEARNER_PERMISSIONS = new Set(["course:view", "lesson:complete"]);

function isStaff(permissions: string[]): boolean {
  return permissions.some((p) => !LEARNER_PERMISSIONS.has(p));
}
// Nothing is inert any more. "Reports" left this list when Pass A gave it
// a real destination, and "Learners" became "People" when Pass C built
// staff administration — the organisations half of that screen is still
// its own page under /organisations.
const INERT_SECTIONS: string[] = [];

export default function AdminLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { accessToken, ready } = useRequireAuth();
  const { logout } = useSession();
  const [me, setMe] = useState<Me | null>(null);
  const [theme, setTheme] = useState<Theme | null>(null);
  // Mobile-only: the sidebar is off-canvas below `md` (facilitators marking
  // attendance on a phone — backlog P14, `app/admin/layout.tsx` used to be a
  // fixed w-56 sidebar with no narrow-viewport handling at all).
  const [navOpen, setNavOpen] = useState(false);

  useEffect(() => {
    if (!ready || !accessToken) return;
    authedFetch("/api/bff/auth/me")
      .then(async (resp) => {
        if (!resp.ok) throw new Error("unauthenticated");
        // Authorisation, not just authentication: this layout only ever
        // checked that someone was signed in, so a learner opening
        // /admin got the whole operations shell -- every section name in
        // the sidebar, all of them navigable, each page then 403ing from
        // the API. Nothing leaked, but it is not their screen.
        const body: Me = await resp.json();
        if (!isStaff(body.permissions)) {
          router.replace("/learn");
          return;
        }
        setMe(body);
      })
      .catch(() => router.replace("/login"));
    fetch("/api/bff/tenant/theme")
      .then(async (resp) => {
        if (!resp.ok) return;
        // The admin shell reads the theme itself rather than through
        // lib/server-api.ts (it is a client component), so it has to do
        // the same logo resolution that helper does.
        const body: Theme = await resp.json();
        setTheme({ ...body, logo_url: browserThemeAssetUrl(body.logo_url) });
      })
      .catch(() => undefined);
  }, [ready, accessToken, router]);

  // Close the slide-in nav on navigation rather than leaving it open over
  // the page the link just went to.
  useEffect(() => {
    void (async () => {
      setNavOpen(false);
    })();
  }, [pathname]);

  async function handleLogout() {
    await logout();
    router.replace("/login");
  }

  if (!me) return null;

  return (
    <div className="flex min-h-screen">
      {/* Mobile top bar: hidden at md and above, where the sidebar is
          always visible and needs no toggle. */}
      <div
        className="fixed inset-x-0 top-0 z-30 flex items-center justify-between p-3 md:hidden"
        style={{
          background: `linear-gradient(165deg, var(--brand) 0%, var(--brand-deep) 100%)`,
          color: "var(--on-brand)",
        }}
      >
        <Link href="/admin" style={{ color: "var(--on-brand)" }}>
          {theme?.logo_url ? (
            <Image
              src={theme.logo_url}
              alt={theme.tenant_name}
              width={120}
              height={63}
              unoptimized
            />
          ) : (
            <span className="serif" style={{ fontSize: "1.0625rem", fontWeight: 600 }}>
              {theme?.tenant_name ?? me.tenant_slug}
            </span>
          )}
        </Link>
        <button
          type="button"
          onClick={() => setNavOpen((open) => !open)}
          aria-expanded={navOpen}
          aria-controls="admin-nav"
          aria-label={navOpen ? "Close menu" : "Open menu"}
          className="rounded-md p-2"
          style={{ border: "1px solid rgba(255,255,255,0.4)" }}
        >
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
            {navOpen ? (
              <path
                d="M4 4l12 12M16 4L4 16"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
              />
            ) : (
              <path
                d="M3 5h14M3 10h14M3 15h14"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
              />
            )}
          </svg>
        </button>
      </div>

      {/* Backdrop, mobile only, closes the nav on tap-outside. */}
      {navOpen ? (
        <div
          className="fixed inset-0 z-30 md:hidden"
          style={{ background: "rgba(0,0,0,0.4)" }}
          onClick={() => setNavOpen(false)}
          aria-hidden="true"
        />
      ) : null}

      <aside
        id="admin-nav"
        // md:sticky + md:top-0 + md:h-screen (not md:relative): a relatively
        // positioned sidebar scrolls away with the page's own content, so
        // scrolling down a long admin page hides it, and the next
        // navigation's scroll-to-top reset makes it look like the sidebar
        // "jumped" back — it never left, the page just came back to where
        // the sidebar always was. Sticky-to-viewport keeps it in place
        // regardless of how far <main> is scrolled; its own overflow-y-auto
        // (needed on mobile for the off-canvas panel) now also does real
        // work here if the nav list itself is ever taller than the screen.
        className={`fixed inset-y-0 left-0 z-40 w-64 -translate-x-full overflow-y-auto p-4 transition-transform duration-200 md:sticky md:top-0 md:h-screen md:w-56 md:shrink-0 md:translate-x-0 ${
          navOpen ? "translate-x-0" : ""
        }`}
        style={{
          background: `linear-gradient(165deg, var(--brand) 0%, var(--brand-deep) 100%)`,
          color: "var(--on-brand)",
        }}
      >
        {/* Same explicit-colour reason as the nav links below: a tenant
            with no logo falls back to its name as text inside this <a>,
            which would otherwise inherit --brand-ink on the brand
            gradient and disappear (the `acme` demo tenant has no logo).
            Hidden at narrow widths — the mobile top bar above already
            shows it, and this sidebar is off-canvas there anyway. */}
        <Link href="/admin" className="mb-8 hidden md:block" style={{ color: "var(--on-brand)" }}>
          {theme?.logo_url ? (
            <Image
              src={theme.logo_url}
              alt={theme.tenant_name}
              width={160}
              height={84}
              className="max-w-full"
              unoptimized
            />
          ) : (
            <span className="serif" style={{ fontSize: "1.0625rem", fontWeight: 600 }}>
              {theme?.tenant_name ?? me.tenant_slug}
            </span>
          )}
        </Link>
        <nav className="mt-16 space-y-1 md:mt-0">
          {WORKING_SECTIONS.filter(
            (section) => !section.permission || me.permissions.includes(section.permission),
          ).map((section) => (
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
              // completely invisible. The neighbouring inert-section
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
      {/* pt-20 clears the fixed mobile top bar (its own height plus
          margin); md:pt-8 restores the even padding once the sidebar is
          no longer fixed/overlaying. */}
      <main className="min-w-0 flex-1 p-6 pt-20 md:p-8">
        <AdminContext.Provider value={{ me, theme }}>{children}</AdminContext.Provider>
      </main>
    </div>
  );
}
