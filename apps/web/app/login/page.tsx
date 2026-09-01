import Image from "next/image";

import { getTheme } from "@/lib/server-api";

import { AccountTypeSignIn } from "./account-type";

/** The base host organisation workspaces hang off. Configurable because
 * it differs per deployment (localhost in dev, ttli.co.za in production);
 * `core/tenancy.py` resolves the tenant from whatever hostname arrives. */
const BASE_HOST = process.env.NEXT_PUBLIC_TENANT_BASE_HOST ?? "localhost:3010";

export const metadata = {
  title: "Sign in",
  alternates: { canonical: "/login" },
};

export default async function LoginPage() {
  const theme = await getTheme();
  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="card w-full" style={{ padding: "2rem", maxWidth: "26rem" }}>
        {theme?.logo_url ? (
          <div className="mb-6 flex justify-center">
            <Image
              src={theme.logo_url}
              alt={theme.tenant_name}
              width={220}
              height={116}
              preload
            />
          </div>
        ) : (
          <div
            className="mb-6 rounded-lg px-4 py-3 text-center text-lg font-semibold"
            style={{ background: "var(--brand)", color: "var(--on-brand)" }}
          >
            {theme?.tenant_name ?? "TTLI"}
          </div>
        )}

        <AccountTypeSignIn baseHost={BASE_HOST} />

        {theme?.support_email ? (
          <p className="mt-6 text-center" style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
            Need help? {theme.support_email}
          </p>
        ) : null}
      </div>
    </main>
  );
}
