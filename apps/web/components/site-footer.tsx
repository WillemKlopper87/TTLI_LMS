"use client";

/**
 * Site-wide utility footer: Terms/Privacy/FAQ, reachable from every
 * page instead of only the homepage (the gap this replaces — those
 * links used to live inside app/page.tsx's own footer block).
 *
 * Hidden under /admin only: that route has its own full-viewport flex
 * shell (app/admin/layout.tsx, a fixed sidebar + main pane) — a
 * trailing footer would render outside/below it and break the intended
 * full-screen app feel. Every other route, including checkout, account
 * and learn, has no such shell and shows this normally; a bottom-of-
 * page Terms/Privacy line is standard there too.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";

export function SiteFooter({ tenantName }: { tenantName: string | null }) {
  const pathname = usePathname();
  if (pathname?.startsWith("/admin")) return null;

  const name = tenantName ?? "TTLI";

  return (
    <footer className="site-footer">
      <div className="site-footer-inner">
        <nav aria-label="Legal and help">
          <Link href="/faq">FAQ</Link>
          <Link href="/privacy">Privacy</Link>
          <Link href="/terms">Terms</Link>
        </nav>
        <p>Copyright &copy; {name} 2026</p>
      </div>
    </footer>
  );
}
