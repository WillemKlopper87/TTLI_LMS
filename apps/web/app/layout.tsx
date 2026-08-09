import type { ReactNode } from "react";

import { getTheme } from "@/lib/server-api";

import "./globals.css";

export default async function RootLayout({ children }: { children: ReactNode }) {
  const theme = await getTheme();
  const style = {
    "--brand-primary": theme?.primary_color ?? "#8e151c",
    "--brand-secondary": theme?.secondary_color ?? "#bc222a",
  } as React.CSSProperties;

  return (
    <html lang="en">
      <head>
        <title>{theme?.tenant_name ?? "TTLI"}</title>
      </head>
      <body style={style} className="min-h-screen antialiased">
        {children}
      </body>
    </html>
  );
}
