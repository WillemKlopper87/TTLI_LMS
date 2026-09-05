"use client";

import Link from "next/link";
import { useState } from "react";

import { LoginForm } from "./login-form";
import { SsoButton } from "./sso-button";

/**
 * Individual / Organisation sign-in (design doc §5 item 20).
 *
 * Both paths end at the same credential check — TTLI has one identity
 * per person, and a corporate learner is still a person. What differs is
 * *which tenant* authenticates them: a white-label organisation has its
 * own subdomain, its own branding and its own catalogue
 * (`core/tenancy.py` resolves the tenant from the hostname), so an
 * organisation user signing in at the shared host would be
 * authenticating against the wrong tenant entirely.
 *
 * So the Organisation tab does the one thing it can honestly do here:
 * take the workspace name and send the visitor to their own subdomain's
 * login, where their own tenant is the one authenticating them — and,
 * if that tenant has configured an identity provider, where the SSO
 * button appears.
 *
 * That button (SsoButton, on the Individual panel) renders only when
 * `GET /auth/sso/available` says this tenant has an IdP, so the shared
 * host shows nothing and a configured workspace leads with it. The copy
 * here used to say SSO was not implemented at all; the flow was in fact
 * built end to end except for the browser half, which is what fable5.1
 * review H-15 was about.
 */
export function AccountTypeSignIn({ baseHost }: { baseHost: string }) {
  const [tab, setTab] = useState<"individual" | "organisation">("individual");
  const [workspace, setWorkspace] = useState("");

  const slug = workspace.trim().toLowerCase().replace(/[^a-z0-9-]/g, "");
  const target = slug ? `${window.location.protocol}//${slug}.${baseHost}/login` : null;

  return (
    <>
      <div className="tabs" role="tablist" aria-label="Account type">
        <button
          type="button"
          role="tab"
          className="tab"
          aria-selected={tab === "individual"}
          onClick={() => setTab("individual")}
        >
          Individual
        </button>
        <button
          type="button"
          role="tab"
          className="tab"
          aria-selected={tab === "organisation"}
          onClick={() => setTab("organisation")}
        >
          Organisation
        </button>
      </div>

      {tab === "individual" ? (
        <div className="panel" role="tabpanel" aria-label="Individual sign-in">
          {/* Renders nothing unless this tenant has an IdP configured. */}
          <SsoButton />
          <LoginForm />
          <p
            style={{
              display: "flex",
              justifyContent: "center",
              gap: ".75rem",
              fontSize: ".8125rem",
              color: "var(--muted)",
            }}
          >
            <Link href="/auth/password-reset">Forgot password?</Link>
            <span aria-hidden="true">·</span>
            <Link href="/auth/magic-link">Sign in with a link</Link>
          </p>
          <p style={{ fontSize: ".75rem", color: "var(--muted)", textAlign: "center" }}>
            No account yet? <Link href="/guest-access">Try a free lesson</Link>.
          </p>
        </div>
      ) : (
        <div className="panel" role="tabpanel" aria-label="Organisation sign-in">
          <p style={{ fontSize: ".8125rem", color: "var(--muted)" }}>
            Your organisation has its own workspace, with its own branding and its own
            programme catalogue. Enter its name to continue there.
          </p>
          <label className="field">
            <b>Workspace name</b>
            <input
              className="input"
              value={workspace}
              onChange={(e) => setWorkspace(e.target.value)}
              placeholder="meridian"
              autoComplete="organization"
              aria-describedby="workspace-hint"
            />
            <span id="workspace-hint">
              {slug ? `You will sign in at ${slug}.${baseHost}` : `For example, meridian.${baseHost}`}
            </span>
          </label>
          <a
            className={target ? "btn btn--primary btn--block" : "btn btn--locked btn--block"}
            href={target ?? undefined}
            aria-disabled={target ? undefined : true}
            onClick={(e) => {
              if (!target) e.preventDefault();
            }}
          >
            Continue to your workspace
          </a>
          <div className="callout">
            <b>Don&rsquo;t know your workspace name?</b>
            Your administrator set it up — it is the address your team uses to sign in, and where
            single sign-on appears if your organisation uses it. If your organisation
            hasn&rsquo;t been set up yet,{" "}
            <Link href="/for-organisations">read how corporate accounts work</Link>.
          </div>
        </div>
      )}
    </>
  );
}
