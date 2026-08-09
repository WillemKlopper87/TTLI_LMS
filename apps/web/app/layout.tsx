import type { ReactNode } from "react";

import { getTheme } from "@/lib/server-api";

import "./globals.css";

export default async function RootLayout({ children }: { children: ReactNode }) {
  const theme = await getTheme();
  const style = {
    "--brand-primary": theme?.primary_color ?? "#1b2a4a",
    "--brand-secondary": theme?.secondary_color ?? "#c9a227",
  } as React.CSSProperties;

  return (
    <html lang="en">
      <head>
        <title>{theme?.tenant_name ?? "TTLI"}</title>
      </head>
      <body style={style} className="min-h-screen bg-gray-50 text-gray-900 antialiased">
        {children}
      </body>
    </html>
  );
}
