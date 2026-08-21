"use client";

import { useCallback, useEffect, useState } from "react";

import { getAccessToken } from "@/lib/session";

/**
 * Tenant branding and custom domains (backlog P3, gaps #44 and #45).
 *
 * White-label theming has worked since migration `0006` — two demo
 * tenants prove it at runtime — and until now a colour, a logo or a
 * hostname could only be changed by writing another migration. The
 * capability was built and left without a door; this is the door.
 *
 * Two things this panel deliberately does not do:
 *
 * - It does not preview a colour the server would reject. Contrast is
 *   measured server-side against the text that actually sits on a brand
 *   colour, and the refusal carries the measured ratio, so the message
 *   is shown as-is rather than replaced with "invalid".
 * - It offers no "verify" button for a domain. Proving a hostname means
 *   resolving its TXT record, which is Phase 7 work; a button that
 *   marked a domain verified on the admin's say-so would make
 *   "verified" mean "someone clicked".
 */

interface Branding {
  logo_url: string | null;
  primary_color: string | null;
  secondary_color: string | null;
  login_background_url: string | null;
  support_email: string | null;
  email_footer_text: string | null;
}

interface Domain {
  id: string;
  hostname: string;
  is_primary: boolean;
  verified_at: string | null;
  tls_status: string;
  dns_txt_record: string;
}

export default function BrandingPanel() {
  const [branding, setBranding] = useState<Branding | null>(null);
  const [domains, setDomains] = useState<Domain[]>([]);
  const [verificationAvailable, setVerificationAvailable] = useState(false);
  const [hostname, setHostname] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const authed = useCallback(
    (path: string, init?: RequestInit) =>
      fetch(`/api/bff${path}`, {
        ...init,
        headers: {
          ...(init?.headers ?? {}),
          Authorization: `Bearer ${getAccessToken() ?? ""}`,
          ...(init?.body && !(init.body instanceof FormData)
            ? { "Content-Type": "application/json" }
            : {}),
        },
      }),
    [],
  );

  const load = useCallback(async () => {
    const [b, d] = await Promise.all([authed("/tenant/branding"), authed("/tenant/domains")]);
    if (!b.ok || !d.ok) {
      setError("Branding could not be loaded.");
      return;
    }
    setBranding((await b.json()) as Branding);
    const body = (await d.json()) as { items: Domain[]; verification_available: boolean };
    setDomains(body.items);
    setVerificationAvailable(body.verification_available);
    setError(null);
  }, [authed]);

  useEffect(() => {
    void load();
  }, [load]);

  async function submit(path: string, init: RequestInit, success: string) {
    setBusy(true);
    setNotice(null);
    const resp = await authed(path, init).catch(() => null);
    setBusy(false);
    if (!resp || !resp.ok) {
      const body = resp ? await resp.json().catch(() => null) : null;
      // The server's message names the measured contrast ratio; keep it.
      setError(body?.error?.message ?? "That change was refused.");
      return;
    }
    setError(null);
    setNotice(success);
    await load();
  }

  if (branding === null) return null;

  return (
    <>
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

      <section className="card mt-6 p-5">
        <b style={{ fontSize: "0.9375rem" }}>Branding</b>
        <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
          Colours are checked for readability against the text that sits on them — WCAG AA needs
          4.5:1, and a colour below that is refused with its measured ratio rather than rendered
          illegibly.
        </p>
        <form
          className="mt-4"
          style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", alignItems: "end" }}
          onSubmit={(e) => {
            e.preventDefault();
            const form = new FormData(e.currentTarget);
            void submit(
              "/tenant/branding",
              {
                method: "PATCH",
                body: JSON.stringify({
                  primary_color: String(form.get("primary_color") || ""),
                  secondary_color: String(form.get("secondary_color") || ""),
                  support_email: String(form.get("support_email") || "") || null,
                  email_footer_text: String(form.get("email_footer_text") || "") || null,
                }),
              },
              "Branding updated.",
            );
          }}
        >
          <label className="field">
            Primary colour
            <input
              name="primary_color"
              defaultValue={branding.primary_color ?? "#8e151c"}
              pattern="#[0-9a-fA-F]{6}"
            />
          </label>
          <label className="field">
            Secondary colour
            <input
              name="secondary_color"
              defaultValue={branding.secondary_color ?? "#bc222a"}
              pattern="#[0-9a-fA-F]{6}"
            />
          </label>
          <label className="field">
            Support email
            <input name="support_email" type="email" defaultValue={branding.support_email ?? ""} />
          </label>
          <label className="field">
            Email footer
            <input name="email_footer_text" defaultValue={branding.email_footer_text ?? ""} />
          </label>
          <button type="submit" className="btn btn--primary" disabled={busy}>
            Save branding
          </button>
        </form>

        <div className="mt-4">
          <label className="field">
            Logo (PNG, JPEG, SVG or WebP, under 2 MB — virus-scanned on upload)
            <input
              type="file"
              accept="image/png,image/jpeg,image/svg+xml,image/webp"
              disabled={busy}
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (!file) return;
                const payload = new FormData();
                payload.append("file", file);
                void submit(
                  "/tenant/branding/logo",
                  { method: "POST", body: payload },
                  "Logo uploaded.",
                );
              }}
            />
          </label>
          {branding.logo_url ? (
            <p className="mono" style={{ fontSize: "0.6875rem", color: "var(--muted)" }}>
              Current: {branding.logo_url}
            </p>
          ) : null}
        </div>
      </section>

      <section className="card mt-6 p-5">
        <b style={{ fontSize: "0.9375rem" }}>Custom domains</b>
        <p className="mt-1" style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
          A hostname is how a request finds this tenant, so each one is unique across the
          platform. Publish the DNS TXT record below to prove ownership.
        </p>
        {!verificationAvailable ? (
          <div className="callout mt-2" style={{ fontSize: "0.75rem" }}>
            Automatic verification and TLS issuance are not built yet, so a new hostname stays
            <span className="mono"> pending</span> until an operator completes it. Nothing here
            marks a domain verified on request — that would make &ldquo;verified&rdquo; meaningless.
          </div>
        ) : null}

        <form
          className="mt-4"
          style={{ display: "flex", gap: "0.75rem", alignItems: "end" }}
          onSubmit={(e) => {
            e.preventDefault();
            void submit(
              "/tenant/domains",
              { method: "POST", body: JSON.stringify({ hostname }) },
              `${hostname} added.`,
            ).then(() => setHostname(""));
          }}
        >
          <label className="field" style={{ flex: "1 1 260px" }}>
            Hostname
            <input
              required
              placeholder="learning.example.com"
              value={hostname}
              onChange={(e) => setHostname(e.target.value)}
            />
          </label>
          <button type="submit" className="btn btn--ghost" disabled={busy}>
            Add hostname
          </button>
        </form>

        <div className="table-wrap mt-4">
          <table>
            <thead>
              <tr>
                <th scope="col">Hostname</th>
                <th scope="col">State</th>
                <th scope="col">DNS TXT record</th>
                <th scope="col">Remove</th>
              </tr>
            </thead>
            <tbody>
              {domains.map((domain) => (
                <tr key={domain.id}>
                  <td>
                    {domain.hostname}
                    {domain.is_primary ? <span className="tag ml-1">primary</span> : null}
                  </td>
                  <td>
                    <span className="tag">
                      {domain.verified_at ? "verified" : `TLS ${domain.tls_status}`}
                    </span>
                  </td>
                  <td className="mono" style={{ fontSize: "0.6875rem" }}>
                    {domain.dns_txt_record}
                  </td>
                  <td>
                    {domain.is_primary ? (
                      <span className="m">—</span>
                    ) : (
                      <button
                        type="button"
                        className="btn btn--quiet"
                        disabled={busy}
                        onClick={() =>
                          void submit(
                            `/tenant/domains/${domain.id}`,
                            { method: "DELETE" },
                            `${domain.hostname} removed.`,
                          )
                        }
                      >
                        Remove
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
