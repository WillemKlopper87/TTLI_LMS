"use client";

import { useCallback, useEffect, useState } from "react";

import { authedFetch } from "@/lib/authed-fetch";

import { useAdmin } from "../admin-context";

/**
 * Staff administration (backlog P3): who is in this tenant, and what
 * they may do.
 *
 * Until this screen existed there was no way to onboard a colleague
 * without a developer — `role_assignments` was written by migration
 * `0002` and by test fixtures, and by nothing else.
 *
 * The permission split shows up directly in what this page offers:
 * `user:invite` sees the list and the invite form, `user:suspend` gets
 * the suspend control, and only `tenant:manage` gets the role controls,
 * because changing what someone may do is the one action that can
 * change the caller's own authority. The server enforces all three
 * regardless — plus a rule the UI cannot express, that you may never
 * grant a role carrying permissions you do not hold yourself.
 */

interface TenantUser {
  id: string;
  email: string;
  full_name: string | null;
  status: string;
  is_guest: boolean;
  roles: string[];
  created_at: string;
}

interface Role {
  code: string;
  name: string;
  permissions: string[];
}

export default function People() {
  const { me } = useAdmin();
  const canInvite = me.permissions.includes("user:invite");
  const canSuspend = me.permissions.includes("user:suspend");
  const canManageRoles = me.permissions.includes("tenant:manage");

  const [users, setUsers] = useState<TenantUser[] | null>(null);
  const [roles, setRoles] = useState<Role[]>([]);
  const [includeLearners, setIncludeLearners] = useState(false);
  const [query, setQuery] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteName, setInviteName] = useState("");
  const [inviteRole, setInviteRole] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const authed = useCallback(
    (path: string, init?: RequestInit) =>
      authedFetch(`/api/bff${path}`, {
        ...init,
        headers: {
          ...(init?.headers ?? {}),
          ...(init?.body ? { "Content-Type": "application/json" } : {}),
        },
      }),
    [],
  );

  const load = useCallback(async () => {
    try {
      const [u, r] = await Promise.all([
        authed(`/tenant/users?include_learners=${includeLearners}`),
        authed("/tenant/roles"),
      ]);
      if (!u.ok || !r.ok) {
        setError("The people list could not be loaded.");
        return;
      }
      setUsers(((await u.json()) as { items: TenantUser[] }).items);
      setRoles(((await r.json()) as { roles: Role[] }).roles);
      setError(null);
    } catch {
      setError("The people list could not be loaded.");
    }
  }, [authed, includeLearners]);

  useEffect(() => {
    if (canInvite) void (async () => {
      await load();
    })();
  }, [canInvite, load]);

  const needle = query.trim().toLowerCase();
  const visibleUsers = needle
    ? (users ?? []).filter(
        (user) =>
          user.email.toLowerCase().includes(needle) ||
          (user.full_name ?? "").toLowerCase().includes(needle),
      )
    : (users ?? []);

  async function act(path: string, init: RequestInit, success: string) {
    setBusy(true);
    setNotice(null);
    const resp = await authed(path, init).catch(() => null);
    setBusy(false);
    if (!resp || !resp.ok) {
      // The server's refusal is the useful message — "you cannot grant a
      // role carrying permissions you do not hold" says more than
      // "something went wrong".
      const body = resp ? await resp.json().catch(() => null) : null;
      setError(body?.error?.message ?? "That change was refused.");
      return;
    }
    setError(null);
    setNotice(success);
    await load();
  }

  if (!canInvite) {
    return (
      <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
        Your role does not hold <span className="mono">user:invite</span>.
      </p>
    );
  }

  return (
    <>
      <div className="dash-top">
        <div>
          <h1>People</h1>
          <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
            Staff and their roles. {canManageRoles ? null : "Role changes need tenant:manage."}
          </p>
        </div>
        <label className="field" style={{ alignSelf: "end" }}>
          <input
            type="checkbox"
            checked={includeLearners}
            onChange={(e) => setIncludeLearners(e.target.checked)}
          />{" "}
          Include learners
        </label>
      </div>

      {error ? (
        <div className="callout callout--warn mt-3" role="status">
          {error}
        </div>
      ) : null}
      {notice ? (
        <div className="callout mt-3" role="status">
          {notice}
        </div>
      ) : null}

      <section className="mt-4">
        <h2 className="serif" style={{ fontSize: "1.05rem" }}>
          Invite a colleague
        </h2>
        <p className="mt-1" style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
          They receive a sign-in link and choose their own password — an administrator never
          handles someone else&rsquo;s credentials.
        </p>
        <form
          className="mt-2"
          style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", alignItems: "end" }}
          onSubmit={(e) => {
            e.preventDefault();
            void act(
              "/tenant/users",
              {
                method: "POST",
                body: JSON.stringify({
                  email: inviteEmail,
                  full_name: inviteName || null,
                  roles: inviteRole ? [inviteRole] : [],
                }),
              },
              `Invitation sent to ${inviteEmail}.`,
            ).then(() => {
              setInviteEmail("");
              setInviteName("");
              setInviteRole("");
            });
          }}
        >
          <label className="field">
            Email
            <input
              type="email"
              required
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
            />
          </label>
          <label className="field">
            Name (optional)
            <input value={inviteName} onChange={(e) => setInviteName(e.target.value)} />
          </label>
          {canManageRoles ? (
            <label className="field">
              Role (optional)
              <select value={inviteRole} onChange={(e) => setInviteRole(e.target.value)}>
                <option value="">No role yet</option>
                {roles.map((role) => (
                  <option key={role.code} value={role.code}>
                    {role.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <button type="submit" className="btn btn--primary" disabled={busy}>
            Send invitation
          </button>
        </form>
      </section>

      <section className="mt-4">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 className="serif" style={{ fontSize: "1.05rem" }}>
            {includeLearners ? "Everyone" : "Staff"}
            {query.trim() ? (
              <span style={{ fontSize: "0.8125rem", color: "var(--muted)", fontWeight: 400 }}>
                {" "}
                · {visibleUsers.length} of {(users ?? []).length}
              </span>
            ) : null}
          </h2>
          {/* Ticking "include learners" turns a short staff list into
              every account in the tenant, which is unbounded — scanning
              it by eye was the only way to find anyone. Filters the rows
              already loaded; no new request. */}
          <input
            className="input"
            type="search"
            style={{ maxWidth: "16rem" }}
            placeholder="Filter by name or email"
            aria-label="Filter people by name or email"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="table-wrap mt-2">
          <table>
            <thead>
              <tr>
                <th scope="col">Person</th>
                <th scope="col">Roles</th>
                <th scope="col">Status</th>
                {canManageRoles || canSuspend ? <th scope="col">Actions</th> : null}
              </tr>
            </thead>
            <tbody>
              {visibleUsers.length === 0 && (users ?? []).length > 0 ? (
                <tr>
                  <td colSpan={canManageRoles || canSuspend ? 4 : 3} style={{ color: "var(--muted)" }}>
                    Nobody here matches “{query.trim()}”.
                  </td>
                </tr>
              ) : null}
              {visibleUsers.map((user) => (
                <tr key={user.id}>
                  <td>
                    {user.full_name ? <div>{user.full_name}</div> : null}
                    <span className="m mono" style={{ fontSize: "0.6875rem" }}>
                      {user.email}
                    </span>
                  </td>
                  <td>
                    {user.roles.length === 0 ? (
                      <span className="m">—</span>
                    ) : (
                      user.roles.map((role) => (
                        <span key={role} className="tag" style={{ marginRight: 4 }}>
                          {role}
                          {canManageRoles && user.id !== me.user_id ? (
                            <button
                              type="button"
                              aria-label={`Remove ${role}`}
                              className="btn btn--quiet"
                              style={{ marginLeft: 4, padding: "0 4px" }}
                              disabled={busy}
                              onClick={() =>
                                void act(
                                  `/tenant/users/${user.id}/roles/${role}`,
                                  { method: "DELETE" },
                                  `Removed ${role}.`,
                                )
                              }
                            >
                              ×
                            </button>
                          ) : null}
                        </span>
                      ))
                    )}
                  </td>
                  <td>
                    <span className="tag">{user.is_guest ? "guest" : user.status}</span>
                  </td>
                  {canManageRoles || canSuspend ? (
                    <td>
                      <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
                        {canManageRoles && user.id !== me.user_id ? (
                          <select
                            aria-label={`Add a role for ${user.email}`}
                            defaultValue=""
                            disabled={busy}
                            onChange={(e) => {
                              const role = e.target.value;
                              e.target.value = "";
                              if (role)
                                void act(
                                  `/tenant/users/${user.id}/roles`,
                                  { method: "POST", body: JSON.stringify({ role_code: role }) },
                                  `Granted ${role}.`,
                                );
                            }}
                          >
                            <option value="">Add role…</option>
                            {roles
                              .filter((role) => !user.roles.includes(role.code))
                              .map((role) => (
                                <option key={role.code} value={role.code}>
                                  {role.name}
                                </option>
                              ))}
                          </select>
                        ) : null}
                        {canSuspend && user.id !== me.user_id ? (
                          <button
                            type="button"
                            className="btn btn--quiet"
                            disabled={busy}
                            onClick={() => {
                              // Suspending is immediate and not local to
                              // this screen: services/tenant_users.py's
                              // set_status revokes every refresh-token
                              // family and denies the account's existing
                              // access tokens, so the person is signed out
                              // of every device mid-session. One
                              // mis-click on a row in a list of
                              // near-identical email addresses did that
                              // silently. Reinstating is not destructive
                              // and stays a single click.
                              if (
                                user.status !== "suspended" &&
                                !window.confirm(
                                  `Suspend ${user.email}? They are signed out everywhere ` +
                                    `immediately and cannot sign in again until reinstated.`,
                                )
                              ) {
                                return;
                              }
                              void act(
                                `/tenant/users/${user.id}/status`,
                                {
                                  method: "POST",
                                  body: JSON.stringify({
                                    status: user.status === "suspended" ? "active" : "suspended",
                                  }),
                                },
                                user.status === "suspended" ? "Reinstated." : "Suspended.",
                              );
                            }}
                          >
                            {user.status === "suspended" ? "Reinstate" : "Suspend"}
                          </button>
                        ) : null}
                      </div>
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {users !== null && users.length === 0 ? (
          <p className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
            No one matches. Invite a colleague above.
          </p>
        ) : null}
      </section>
    </>
  );
}
