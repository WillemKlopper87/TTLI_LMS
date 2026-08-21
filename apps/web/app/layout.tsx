import { cookies } from "next/headers";
import { Archivo, IBM_Plex_Mono, Newsreader } from "next/font/google";
import type { ReactNode } from "react";

import { getTheme } from "@/lib/server-api";
import { SessionProvider } from "@/lib/session-context";
import { SKIN_COOKIE, parseSkin, skinSwitcherEnabled } from "@/lib/skin";
import { NotificationOptIn } from "@/components/notification-opt-in";
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
      <head>
        <title>{theme?.tenant_name ?? "TTLI"}</title>
        <meta name="theme-color" content={themeColor} />
        {/* iOS Safari doesn't read the web app manifest for "Add to Home
            Screen" — these are its own, separate PWA affordances. */}
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta
          name="apple-mobile-web-app-title"
          content={theme?.tenant_name ?? "TTLI"}
        />
        <link rel="apple-touch-icon" href="/icon-192.png" />
      </head>
      <body style={style} className="min-h-screen antialiased">
        <RegisterServiceWorker />
        <SessionProvider>
          <SiteHeader
            tenantName={theme?.tenant_name ?? null}
            logoUrl={theme?.logo_url ?? null}
          />
          <NotificationOptIn />
          {children}
          {skinSwitcherEnabled() ? <SkinSwitcher initial={skin} /> : null}
        </SessionProvider>
      </body>
    </html>
  );
}
