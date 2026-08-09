"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { getAccessToken } from "@/lib/session";

interface Me {
  user_id: string;
  tenant_slug: string;
  email: string;
  permissions: string[];
}

// The Phase 1 "empty admin shell": navigation that exists but leads nowhere
// yet, and proof of who is signed in. Each section fills in with its phase.
const SECTIONS = ["Courses", "Learners", "Orders", "Reports", "Settings"];

export default function AdminShell() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) {
      router.replace("/");
      return;
    }
    fetch("/api/bff/auth/me", { headers: { Authorization: `Bearer ${token}` } })
      .then(async (resp) => {
        if (!resp.ok) throw new Error("unauthenticated");
        setMe(await resp.json());
      })
      .catch(() => router.replace("/"));
  }, [router]);

  if (!me) return null;

  return (
    <div className="flex min-h-screen">
      <aside
        className="w-56 shrink-0 p-4 text-white"
        style={{ backgroundColor: "var(--brand-primary)" }}
      >
        <div className="mb-8 text-lg font-semibold">{me.tenant_slug}</div>
        <nav className="space-y-1">
          {SECTIONS.map((section) => (
            <div
              key={section}
              className="cursor-not-allowed rounded-md px-3 py-2 text-sm opacity-70"
              title="Arrives with its phase"
            >
              {section}
            </div>
          ))}
        </nav>
      </aside>
      <main className="flex-1 p-8">
        <h1 className="text-xl font-semibold">Welcome</h1>
        <p className="mt-2 text-sm text-gray-600">
          Signed in as <span className="font-mono">{me.email}</span>
        </p>
        <p className="mt-1 text-sm text-gray-600">
          Permissions: {me.permissions.length > 0 ? me.permissions.join(", ") : "none"}
        </p>
      </main>
    </div>
  );
}
