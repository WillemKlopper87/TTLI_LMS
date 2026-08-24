"use client";

/**
 * Shared site header — the prototype's `.site-head` shell, rendered on every
 * non-admin route (the admin shell in app/admin/layout.tsx has its own
 * sidebar and sign-out, so a second bar up top would be redundant there).
 *
 *   signed out   brand · public nav · [Sign in] [Try a free lesson]
 *   guest        brand · public nav · [Guest tag] [avatar] [Sign out]
 *   learner      brand · learner nav (My learning …) · [avatar] [Sign out]
 *   staff        learner nav + an "Admin" item pointing at the admin shell
 *
 * Tenant identity comes from the root layout (which already fetches
 * GET /tenant/theme server-side): TTLI renders its own mark and strapline,
 * a white-label tenant renders its own logo/name with "Powered by TTLI".
 */
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useSession } from "@/lib/session-context";

export interface SiteHeaderProps {
  tenantName: string | null;
  logoUrl: string | null;
}

interface NavItem {
  label: string;
  href: string;
}

// The public/marketing journey. Each item is its own page: pointing
// "Executive Programmes" at a catalogue filter and "Live Workshops" at a
// (non-existent) catalogue anchor made three nav items render the same
// list, and put the corporate pitch behind a login.
const PUBLIC_NAV: NavItem[] = [
  { label: "Courses", href: "/catalogue" },
  { label: "Executive Programmes", href: "/executive-programmes" },
  { label: "Live Workshops", href: "/workshops" },
  { label: "Resources", href: "/resources" },
  { label: "For Organisations", href: "/for-organisations" },
  { label: "About", href: "/about" },
];

// The signed-in learner journey (prototype screens 7, 10). There is no
// standalone achievements page yet — that still anchors into the
// learner dashboard. Workshops got its own page in P7 phase 2
// (/learn/sessions) once cancel/reschedule needed somewhere to live —
// the dashboard's own "Coming up" rowlist stayed read-only on purpose.
const LEARNER_NAV: NavItem[] = [
  { label: "My learning", href: "/learn" },
  { label: "Catalogue", href: "/catalogue" },
  { label: "Learning paths", href: "/paths" },
  { label: "Workshops", href: "/learn/sessions" },
  { label: "Achievements", href: "/learn#completed" },
];

// Mirrors lib/post-login-redirect.ts — any of these means the account has
// a staff surface, so the header offers a way into the admin shell.
const STAFF_PERMISSIONS = [
  "analytics:view",
  "payment:approve",
  "workshop:manage",
  "workshop:facilitate",
  "deal:manage",
  "campaign:manage",
];

interface Me {
  email: string;
  permissions: string[];
}

/** "thandi.nkosi@…" → "TN"; "admin@…" → "AD". Nothing else about the
 * person is available client-side (auth/me carries no display name). */
export function initialsFromEmail(email: string): string {
  const local = email.split("@")[0] ?? "";
  const parts = local.split(/[._\-+]+/).filter(Boolean);
  const letters =
    parts.length >= 2 ? `${parts[0][0]}${parts[1][0]}` : local.slice(0, 2);
  return letters.toUpperCase() || "?";
}

/** GET /auth/me does not expose `is_guest`; the guest role's permission set
 * (`["course:view"]` alone, from the role seed) is the only client-visible
 * signal. A learner additionally holds `lesson:complete`. */
function isGuestPermissionSet(permissions: string[]): boolean {
  return permissions.length === 1 && permissions[0] === "course:view";
}

function isFirstPartyTenant(tenantName: string | null): boolean {
  if (!tenantName) return true;
  return /\bTTLI\b|Themba\s+Thandeka/i.test(tenantName);
}

function splitHref(href: string): { path: string; query: string } {
  const [beforeHash] = href.split("#");
  const [path, query = ""] = beforeHash.split("?");
  return { path, query };
}

/**
 * Which nav item is "current". Several items can share a pathname
 * (Courses and Executive Programmes are both /catalogue): the one whose
 * query string is present in the URL wins; otherwise the plain one does.
 * Reads window.location.search directly rather than useSearchParams so
 * this global header never forces the whole route tree to bail out of
 * static rendering.
 */
function currentIndex(items: NavItem[], pathname: string | null, search: string): number {
  if (!pathname) return -1;
  const matches = items
    .map((item, index) => ({ index, ...splitHref(item.href) }))
    .filter(({ path }) => path === pathname || (path !== "/" && pathname.startsWith(`${path}/`)));
  if (matches.length === 0) return -1;
  const withQuery = matches.find(({ query }) => query && search.includes(query));
  if (withQuery) return withQuery.index;
  return (matches.find(({ query }) => !query) ?? matches[0]).index;
}

export function SiteHeader({ tenantName, logoUrl }: SiteHeaderProps) {
  const { accessToken, status, logout } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const [me, setMe] = useState<Me | null>(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    if (status !== "authenticated" || !accessToken) {
      setMe(null);
      return;
    }
    let cancelled = false;
    fetch("/api/bff/auth/me", { headers: { Authorization: `Bearer ${accessToken}` } })
      .then((resp) => (resp.ok ? resp.json() : null))
      .then((data) => {
        if (cancelled || !data) return;
        setMe({ email: data.email ?? "", permissions: data.permissions ?? [] });
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [status, accessToken]);

  // Query string for the "current item" check; re-read on every navigation.
  useEffect(() => {
    setSearch(typeof window === "undefined" ? "" : window.location.search);
  }, [pathname]);

  // The admin shell (app/admin/layout.tsx) has its own sidebar with its own
  // sign-out entry — a second one up top would be redundant there.
  if (pathname?.startsWith("/admin")) return null;

  async function handleLogout() {
    await logout();
    router.push("/login");
  }

  const signedIn = status === "authenticated";
  const permissions = me?.permissions ?? [];
  const isStaff = permissions.some((p) => STAFF_PERMISSIONS.includes(p));
  const isGuest = signedIn && me !== null && !isStaff && isGuestPermissionSet(permissions);

  // Guests are still on the public journey (catalogue → course → buy); a
  // learner or staff member gets the learner journey, staff also get Admin.
  const items: NavItem[] = !signedIn || isGuest
    ? PUBLIC_NAV
    : isStaff
      ? [...LEARNER_NAV, { label: "Admin", href: "/admin" }]
      : LEARNER_NAV;
  const onIndex = currentIndex(items, pathname, search);

  const firstParty = isFirstPartyTenant(tenantName);
  const brandLabel = firstParty ? "TTLI" : (tenantName ?? "TTLI");
  const strapline = firstParty ? "Organisational Behaviour Consultancy" : "Powered by TTLI";

  return (
    <header className="site-head">
      <Link href="/" className="brand-mark" aria-label={`${brandLabel} home`}>
        {firstParty ? (
          <img className="brand-glyph" src="/brand/ttli-mark.png" alt="" width={26} height={26} />
        ) : logoUrl ? (
          <img className="brand-glyph" src={logoUrl} alt="" width={26} height={26} />
        ) : (
          <span className="tenant-logo" aria-hidden="true">
            {brandLabel.charAt(0).toUpperCase()}
          </span>
        )}
        <span className="brand-name">
          {brandLabel}
          <small>{strapline}</small>
        </span>
      </Link>

      <nav className="site-nav" aria-label="Main">
        {status === "loading"
          ? null
          : items.map((item, index) => {
              const on = index === onIndex;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={on ? "on" : undefined}
                  aria-current={on ? "page" : undefined}
                >
                  {item.label}
                </Link>
              );
            })}
      </nav>

      <div className="head-actions">
        {status === "loading" ? null : !signedIn ? (
          <>
            <Link href="/login" className="btn btn--quiet">
              Sign in
            </Link>
            <Link href="/guest-access" className="btn btn--primary">
              Try a free lesson
            </Link>
          </>
        ) : (
          <>
            {isGuest ? <span className="tag tag--live">Guest</span> : null}
            {me?.email ? (
              <span className="avatar" title={me.email} aria-label={`Signed in as ${me.email}`}>
                {initialsFromEmail(me.email)}
              </span>
            ) : null}
            <button type="button" onClick={handleLogout} className="btn btn--quiet">
              Sign out
            </button>
          </>
        )}
      </div>
    </header>
  );
}
