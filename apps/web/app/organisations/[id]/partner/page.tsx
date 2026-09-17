"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { authedFetch } from "@/lib/authed-fetch";
import { readError } from "@/lib/api-error";
import { getAccessToken } from "@/lib/session";
import { useRequireAuth } from "@/lib/session-context";

interface Organisation {
  id: string;
  name: string;
}

interface PartnerProfile {
  id: string;
  organisation_id: string;
  display_name: string;
  bio: string | null;
  logo_object_key: string | null;
  professional_body: string | null;
  status: string;
  operator_agreement_accepted_at: string | null;
}

interface ActivationStatus {
  can_activate: boolean;
  missing_gates: string[];
}

export default function PartnerPortalPage() {
  const params = useParams<{ id: string }>();
  const { ready } = useRequireAuth();
  const orgId = params.id;

  const [org, setOrg] = useState<Organisation | null>(null);
  const [profile, setProfile] = useState<PartnerProfile | null>(null);
  const [activationStatus, setActivationStatus] = useState<ActivationStatus | null>(null);
  const [error, setError] = useState<"forbidden" | "unknown" | null>(null);

  const [displayName, setDisplayName] = useState("");
  const [bio, setBio] = useState("");
  const [logoObjectKey, setLogoObjectKey] = useState("");
  const [professionalBody, setProfessionalBody] = useState("");
  const [createProfileBusy, setCreateProfileBusy] = useState(false);
  const [createProfileError, setCreateProfileError] = useState<string | null>(null);

  const [activateBusy, setActivateBusy] = useState(false);
  const [activateError, setActivateError] = useState<string | null>(null);

  const [clientOrgName, setClientOrgName] = useState("");
  const [createClientBusy, setCreateClientBusy] = useState(false);
  const [createClientError, setCreateClientError] = useState<string | null>(null);
  const [clientCreated, setClientCreated] = useState(false);

  async function loadOrg() {
    const resp = await authedFetch(`/api/bff/organisations/${orgId}`);
    if (resp.status === 403) {
      setError("forbidden");
      return;
    }
    if (!resp.ok) {
      setError("unknown");
      return;
    }
    setOrg(await resp.json());
  }

  async function loadActivationStatus(profileId: string) {
    const resp = await authedFetch(`/api/bff/partner/profiles/${profileId}/activation-status`);
    if (resp.ok) {
      setActivationStatus(await resp.json());
    }
  }

  async function loadProfile() {
    const resp = await authedFetch(`/api/bff/partner/profiles/by-organisation/${orgId}`);
    if (!resp.ok) return;
    const body = await resp.json();
    if (body === null) return;
    setProfile(body);
    await loadActivationStatus(body.id);
  }

  useEffect(() => {
    if (!ready || !getAccessToken()) return;
    void (async () => {
      await loadOrg();
      await loadProfile();
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, orgId]);

  async function createPartnerProfile(event: React.FormEvent) {
    event.preventDefault();
    if (!displayName.trim()) return;
    setCreateProfileBusy(true);
    setCreateProfileError(null);
    const resp = await authedFetch("/api/bff/partner/profiles", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        organisation_id: orgId,
        display_name: displayName.trim(),
        bio: bio.trim() || null,
        logo_object_key: logoObjectKey.trim() || null,
        professional_body: professionalBody.trim() || null,
      }),
    });
    setCreateProfileBusy(false);
    if (!resp.ok) {
      setCreateProfileError(await readError(resp, "Partner profile could not be created."));
      return;
    }
    const newProfile = await resp.json();
    setProfile(newProfile);
    setDisplayName("");
    setBio("");
    setLogoObjectKey("");
    setProfessionalBody("");
    await loadActivationStatus(newProfile.id);
  }

  async function activateProfile() {
    if (!profile) return;
    setActivateBusy(true);
    setActivateError(null);
    const resp = await authedFetch(`/api/bff/partner/profiles/${profile.id}/activate`, {
      method: "POST",
    });
    setActivateBusy(false);
    if (!resp.ok) {
      setActivateError(await readError(resp, "Partner profile could not be activated."));
      return;
    }
    if (activationStatus) {
      setActivationStatus({ ...activationStatus, can_activate: false });
    }
    await loadActivationStatus(profile.id);
  }

  async function createClientOrganisation(event: React.FormEvent) {
    event.preventDefault();
    if (!clientOrgName.trim()) return;
    setCreateClientBusy(true);
    setCreateClientError(null);
    const resp = await authedFetch("/api/bff/partner/clients", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: clientOrgName.trim(),
      }),
    });
    setCreateClientBusy(false);
    if (!resp.ok) {
      setCreateClientError(await readError(resp, "Client organisation could not be created."));
      return;
    }
    setClientOrgName("");
    setClientCreated(true);
    setTimeout(() => setClientCreated(false), 3000);
  }

  if (error === "forbidden") {
    return (
      <main className="mx-auto max-w-3xl px-6 py-16">
        <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
          You are not a member of this organisation.
        </p>
      </main>
    );
  }

  if (error === "unknown" || org === null) {
    return (
      <main className="mx-auto max-w-3xl px-6 py-16">
        <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>
          {error === "unknown" ? "This organisation could not be loaded." : "Loading…"}
        </p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <p className="eyebrow">Organisation</p>
      <h1 className="serif mt-2" style={{ fontSize: "1.75rem" }}>
        {org.name}
      </h1>

      <section className="mt-10">
        <h2 className="serif" style={{ fontSize: "1.125rem" }}>
          Partner Profile
        </h2>

        {profile === null ? (
          <div className="card p-5 mt-4" style={{ maxWidth: "32rem" }}>
            <b style={{ fontSize: "0.875rem" }}>Create partner profile</b>
            <form onSubmit={(e) => void createPartnerProfile(e)} className="mt-3">
              <label className="field">
                <b>Display name</b>
                <input
                  className="input"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder="e.g. Your Organisation Name"
                  required
                  autoFocus
                />
              </label>
              <label className="field mt-3">
                <b>Bio</b>
                <textarea
                  className="input"
                  value={bio}
                  onChange={(e) => setBio(e.target.value)}
                  rows={3}
                  placeholder="Optional description of your organisation"
                />
              </label>
              <label className="field mt-3">
                <b>Logo object key</b>
                <input
                  className="input"
                  value={logoObjectKey}
                  onChange={(e) => setLogoObjectKey(e.target.value)}
                  placeholder="Optional S3 object key"
                />
              </label>
              <label className="field mt-3">
                <b>Professional body</b>
                <input
                  className="input"
                  value={professionalBody}
                  onChange={(e) => setProfessionalBody(e.target.value)}
                  placeholder="Optional, for health professionals"
                />
              </label>
              {createProfileError ? (
                <p
                  role="alert"
                  style={{ fontSize: "0.8125rem", color: "var(--stop)" }}
                  className="mt-2"
                >
                  {createProfileError}
                </p>
              ) : null}
              <button
                type="submit"
                className="btn btn--primary mt-3"
                disabled={createProfileBusy || !displayName.trim()}
              >
                {createProfileBusy ? "Creating…" : "Create profile"}
              </button>
            </form>
          </div>
        ) : (
          <div className="mt-4 flex flex-col gap-4">
            <div className="card p-4">
              <b style={{ fontSize: "0.875rem" }}>Profile details</b>
              <dl className="mt-3 flex flex-col gap-2">
                <div className="flex justify-between">
                  <dt style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>Display name</dt>
                  <dd className="mono" style={{ fontSize: "0.8125rem" }}>
                    {profile.display_name}
                  </dd>
                </div>
                {profile.bio ? (
                  <div className="flex justify-between">
                    <dt style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>Bio</dt>
                    <dd className="mono" style={{ fontSize: "0.8125rem" }}>
                      {profile.bio}
                    </dd>
                  </div>
                ) : null}
                {profile.professional_body ? (
                  <div className="flex justify-between">
                    <dt style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>Professional body</dt>
                    <dd className="mono" style={{ fontSize: "0.8125rem" }}>
                      {profile.professional_body}
                    </dd>
                  </div>
                ) : null}
                <div className="flex justify-between">
                  <dt style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>Status</dt>
                  <dd>
                    <span className="tag tag--live" style={{ fontSize: "0.8125rem" }}>
                      {profile.status}
                    </span>
                  </dd>
                </div>
              </dl>
            </div>

            {activationStatus !== null ? (
              <div className="card p-4">
                <b style={{ fontSize: "0.875rem" }}>Activation</b>
                <div className="mt-3">
                  {activationStatus.can_activate ? (
                    <>
                      <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }} className="mb-3">
                        All requirements met. Ready to activate.
                      </p>
                      <button
                        type="button"
                        className="btn btn--primary"
                        disabled={activateBusy}
                        onClick={() => void activateProfile()}
                      >
                        {activateBusy ? "Activating…" : "Activate"}
                      </button>
                    </>
                  ) : (
                    <>
                      <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }} className="mb-2">
                        Requirements not yet met:
                      </p>
                      <ul className="mt-2 flex flex-col gap-1">
                        {activationStatus.missing_gates.map((gate) => (
                          <li
                            key={gate}
                            style={{
                              fontSize: "0.8125rem",
                              color: "var(--muted)",
                              paddingLeft: "1rem",
                            }}
                          >
                            • {gate}
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                  {activateError ? (
                    <p
                      role="alert"
                      style={{ fontSize: "0.8125rem", color: "var(--stop)" }}
                      className="mt-2"
                    >
                      {activateError}
                    </p>
                  ) : null}
                </div>
              </div>
            ) : null}
          </div>
        )}
      </section>

      {profile !== null ? (
        <section className="mt-10">
          <h2 className="serif" style={{ fontSize: "1.125rem" }}>
            Create client organisation
          </h2>

          <div className="card p-5 mt-4" style={{ maxWidth: "32rem" }}>
            <form onSubmit={(e) => void createClientOrganisation(e)}>
              <label className="field">
                <b>Name</b>
                <input
                  className="input"
                  value={clientOrgName}
                  onChange={(e) => setClientOrgName(e.target.value)}
                  placeholder="e.g. Client Organisation Name"
                  required
                  autoFocus
                />
              </label>
              {createClientError ? (
                <p
                  role="alert"
                  style={{ fontSize: "0.8125rem", color: "var(--stop)" }}
                  className="mt-2"
                >
                  {createClientError}
                </p>
              ) : null}
              {clientCreated ? (
                <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }} className="mt-2">
                  Client organisation created successfully.
                </p>
              ) : null}
              <button
                type="submit"
                className="btn btn--primary mt-3"
                disabled={createClientBusy || !clientOrgName.trim()}
              >
                {createClientBusy ? "Creating…" : "Create organisation"}
              </button>
            </form>
          </div>
        </section>
      ) : null}
    </main>
  );
}
