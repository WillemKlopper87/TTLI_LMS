import { getTheme } from "@/lib/server-api";

import { LoginForm } from "./login-form";

export default async function LoginPage() {
  const theme = await getTheme();
  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="w-full max-w-sm rounded-xl border border-gray-200 bg-white p-8 shadow-sm">
        <div
          className="mb-6 rounded-lg px-4 py-3 text-center text-lg font-semibold text-white"
          style={{ backgroundColor: "var(--brand-primary)" }}
        >
          {theme?.tenant_name ?? "TTLI"}
        </div>
        <LoginForm />
        {theme?.support_email ? (
          <p className="mt-6 text-center text-xs text-gray-500">
            Need help? {theme.support_email}
          </p>
        ) : null}
      </div>
    </main>
  );
}
