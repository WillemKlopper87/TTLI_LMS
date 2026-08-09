"use client";

import { useAdmin } from "./admin-context";

export default function AdminOverview() {
  const { me } = useAdmin();

  return (
    <>
      <h1 className="serif" style={{ fontSize: "1.5rem" }}>
        Welcome
      </h1>
      <p className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
        Signed in as <span className="mono">{me.email}</span>
      </p>
      <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
        Permissions: {me.permissions.length > 0 ? me.permissions.join(", ") : "none"}
      </p>
    </>
  );
}
