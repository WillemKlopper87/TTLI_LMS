import type { useRouter } from "next/navigation";

// Any of these means "this account has a staff surface to land on" — the
// permissions already gating the working admin screens (Leads, Payments).
// Everyone else is a learner/buyer: send them to their own courses, not an
// admin shell with nothing they can do in it.
const STAFF_PERMISSIONS = [
  "analytics:view",
  "payment:approve",
  "workshop:manage",
  "workshop:facilitate",
  "deal:manage",
  "campaign:manage",
];

export async function postLoginRedirect(router: ReturnType<typeof useRouter>, token: string) {
  const resp = await fetch("/api/bff/auth/me", { headers: { Authorization: `Bearer ${token}` } });
  if (resp.ok) {
    const me = await resp.json();
    const isStaff = (me.permissions ?? []).some((p: string) => STAFF_PERMISSIONS.includes(p));
    router.push(isStaff ? "/admin" : "/learn");
    return;
  }
  router.push("/learn");
}
