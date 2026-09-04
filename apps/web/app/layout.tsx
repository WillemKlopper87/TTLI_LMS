import { cookies } from "next/headers";
import { Archivo, IBM_Plex_Mono, Newsreader } from "next/font/google";
import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import { getTheme } from "@/lib/server-api";
import { getSiteUrl } from "@/lib/site-url";
import { SessionProvider } from "@/lib/session-context";
import { SKIN_COOKIE, parseSkin, skinSwitcherEnabled } from "@/lib/skin";
import { NotificationOptIn } from "@/components/notification-opt-in";
import { PageViewTracker } from "@/components/page-view-tracker";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import { SkinSwitcher } from "@/components/skin-switcher";

import { RegisterServiceWorker } from "./register-sw";

import "./globals.css";

/* The Institute skin's three families (`docs/design/institute/README.md`).
   Declared unconditionally but referenced only from the
   `[data-skin="institute"]` block in globals.css: an @font-face that
   nothing matches is never fetched, so the classic skin pays for the
   declaration and not the download. next/font self-hosts them at build
   time, which is also what keeps `font-src 'self'` in proxy.ts intact —
   a Google Fonts <link> would have needed the CSP widened. */
const newsreader = Newsreader({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  display: "swap",
  variable: "--font-newsreader",
});

const archivo = Archivo({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  display: "swap",
  variable: "--font-archivo",
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  display: "swap",
  variable: "--font-plex-mono",
});

/**
 * Resolved per-request from the tenant's own theme (white-label: each
 * tenant gets its own title/description/OG card, not a hardcoded TTLI
 * default) — the same shape manifest.ts already uses for its name and
 * description, kept consistent here rather than inventing new copy.
 * `title.template` is what fixes every page's own `export const
 * metadata = { title: "..." }` rendering as a bare title with no site
 * name — previously this file's own hardcoded `<title>` in `<head>`
 * fought with those, producing two `<title>` elements per page.
 */
export async function generateMetadata(): Promise<Metadata> {
  const [theme, siteUrl] = await Promise.all([getTheme(), getSiteUrl()]);
  const name = theme?.tenant_name ?? "TTLI";
  const description = `${name}'s learning platform — courses, certificates and workshops.`;

  return {
    metadataBase: new URL(siteUrl),
    title: { default: name, template: `%s | ${name}` },
    description,
    // iOS Safari doesn't read the web app manifest for "Add to Home
    // Screen" — appleWebApp/icons.apple are its own, separate PWA
    // affordances, generated here instead of by hand in `<head>`.
    appleWebApp: { capable: true, title: name },
    icons: { apple: "/icon-192.png" },
    openGraph: { title: name, description, siteName: name, type: "website" },
    twitter: { card: "summary_large_image", title: name, description },
  };
}

export async function generateViewport(): Promise<Viewport> {
  const theme = await getTheme();
  return { themeColor: theme?.primary_color ?? "#8e151c" };
}

export default async function RootLayout({
  children,
}: {
  children: ReactNode;
}) {
  const theme = await getTheme();
  const themeColor = theme?.primary_color ?? "#8e151c";
  const style = {
    "--brand-primary": themeColor,
    "--brand-secondary": theme?.secondary_color ?? "#bc222a",
  } as React.CSSProperties;

  // Stamped server-side so the first paint is already the right look.
  // Reading this on the client would show a frame of the other skin on
  // every navigation.
  const skin = parseSkin((await cookies()).get(SKIN_COOKIE)?.value);
  const fontVars = `${newsreader.variable} ${archivo.variable} ${plexMono.variable}`;

  return (
    <html lang="en" data-skin={skin} className={fontVars}>
      <body style={style} className="min-h-screen antialiased">
        <RegisterServiceWorker />
        <PageViewTracker />
        <SessionProvider>
          <SiteHeader
            tenantName={theme?.tenant_name ?? null}
            logoUrl={theme?.logo_url ?? null}
          />
          <NotificationOptIn />
          <div className="page-body">{children}</div>
          <SiteFooter tenantName={theme?.tenant_name ?? null} />
          {skinSwitcherEnabled() ? <SkinSwitcher initial={skin} /> : null}
        </SessionProvider>
      </body>
    </html>
  );
}
