import type { ReactNode } from "react";

import { getTheme } from "@/lib/server-api";

import { RegisterServiceWorker } from "./register-sw";

import "./globals.css";

export default async function RootLayout({ children }: { children: ReactNode }) {
  const theme = await getTheme();
  const themeColor = theme?.primary_color ?? "#8e151c";
  const style = {
    "--brand-primary": themeColor,
    "--brand-secondary": theme?.secondary_color ?? "#bc222a",
  } as React.CSSProperties;

  return (
    <html lang="en">
      <head>
        <title>{theme?.tenant_name ?? "TTLI"}</title>
        <meta name="theme-color" content={themeColor} />
        {/* iOS Safari doesn't read the web app manifest for "Add to Home
            Screen" — these are its own, separate PWA affordances. */}
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-title" content={theme?.tenant_name ?? "TTLI"} />
        <link rel="apple-touch-icon" href="/icon-192.png" />
      </head>
      <body style={style} className="min-h-screen antialiased">
        <RegisterServiceWorker />
        {children}
      </body>
    </html>
  );
}
