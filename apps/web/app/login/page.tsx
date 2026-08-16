import Image from "next/image";
import Link from "next/link";

import { getTheme } from "@/lib/server-api";

import { LoginForm } from "./login-form";

export default async function LoginPage() {
  const theme = await getTheme();
  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="card w-full max-w-sm" style={{ padding: "2rem" }}>
        {theme?.logo_url ? (
          <div className="mb-6 flex justify-center">
            <Image
              src={theme.logo_url}
              alt={theme.tenant_name}
              width={220}
              height={116}
              priority
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
        <LoginForm />
        <p
          className="mt-4 flex justify-center gap-3"
          style={{ fontSize: "0.8125rem", color: "var(--muted)" }}
        >
          <Link href="/auth/password-reset">Forgot password?</Link>
          <span aria-hidden="true">·</span>
          <Link href="/auth/magic-link">Sign in with a link</Link>
        </p>
        {theme?.support_email ? (
          <p className="mt-6 text-center" style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
            Need help? {theme.support_email}
          </p>
        ) : null}
      </div>
    </main>
  );
}
