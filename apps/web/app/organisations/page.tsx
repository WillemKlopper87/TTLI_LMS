"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { authedFetch } from "@/lib/authed-fetch";
import { getAccessToken } from "@/lib/session";
import { useRequireAuth } from "@/lib/session-context";

interface OrganisationSummary {
  id: string;
  name: string;
}

/**
 * Organisation creation is self-service (02 §4.5, REQ-TEN-02) — any
 * authenticated user can start one and becomes its first admin. There is
 * no separate signup flow yet, so this is reached the same way /checkout
 * is: an already-authenticated learner deciding to buy seats for a team.
 */
export default function OrganisationsPage() {
  const router = useRouter();
  const { ready } = useRequireAuth();
  const [orgs, setOrgs] = useState<OrganisationSummary[] | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    const resp = await authedFetch("/api/bff/organisations");
    if (resp.ok) setOrgs(await resp.json());
  }

  useEffect(() => {
    if (!ready || !getAccessToken()) return;
    void (async () => {
      await load();
    })();
  }, [ready]);

  async function createOrganisation() {
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    const resp = await authedFetch("/api/bff/organisations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name.trim() }),
    });
    setBusy(false);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not create the organisation.");
      return;
    }
    const created: OrganisationSummary = await resp.json();
    router.push(`/organisations/${created.id}`);
  }

  if (orgs === null) {
    return (
      <main className="mx-auto max-w-2xl px-6 py-16">
        <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>Loading…</p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-2xl px-6 py-16">
      <p className="eyebrow">For teams</p>
      <h1 className="serif mt-2" style={{ fontSize: "1.75rem" }}>
        Your organisations
      </h1>
      <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
        Buy seats for a course once, then invite your team into them.
      </p>

      {orgs.length === 0 ? (
        <p className="mt-8" style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>
          You aren&rsquo;t part of an organisation yet.
        </p>
      ) : (
        <div className="mt-8 flex flex-col gap-2">
          {orgs.map((org) => (
            <Link key={org.id} href={`/organisations/${org.id}`} className="card p-4">
              <b style={{ fontSize: "0.9375rem" }}>{org.name}</b>
            </Link>
          ))}
        </div>
      )}

      <div className="card mt-8 p-5">
        <b style={{ fontSize: "0.875rem" }}>Start a new organisation</b>
        <label className="field mt-3">
          <b>Name</b>
          <input
            className="input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Acme Manufacturing"
          />
        </label>
        {error ? (
          <p role="alert" className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--stop)" }}>
            {error}
          </p>
        ) : null}
        <button
          type="button"
          className="btn btn--primary mt-3"
          disabled={busy || !name.trim()}
          onClick={createOrganisation}
        >
          Create organisation
        </button>
      </div>
    </main>
  );
}
