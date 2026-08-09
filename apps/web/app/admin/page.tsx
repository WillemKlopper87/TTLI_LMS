"use client";

import { useAdmin } from "./admin-context";

export default function AdminOverview() {
  const { me } = useAdmin();

  return (
    <>
      <h1 className="text-xl font-semibold">Welcome</h1>
      <p className="mt-2 text-sm text-gray-600">
        Signed in as <span className="font-mono">{me.email}</span>
      </p>
      <p className="mt-1 text-sm text-gray-600">
        Permissions: {me.permissions.length > 0 ? me.permissions.join(", ") : "none"}
      </p>
    </>
  );
}
