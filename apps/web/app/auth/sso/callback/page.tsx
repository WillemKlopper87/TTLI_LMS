"use client";

/**
 * Where the identity provider sends the browser back to.
 *
 * `routers/sso.py::callback_url` builds `https://{tenant host}/auth/sso/
 * callback` and registers it with the IdP as the one redirect URI a
 * tenant's flow will ever use — and until now nothing was serving it.
 * The API endpoints, the two BFF routes and the HttpOnly binding cookie
 * were all built and tested; a tenant that configured an IdP sent its
 * staff to a 404 (fable5.1 review H-15).
 *
 * This page is the missing half. It takes the `code` and `state` the IdP
 * put in the query, hands them to the BFF — which adds the binding
 * cookie only it can read — and turns the result into a session.
 *
 * Three things it deliberately does not do:
 *
 * - It does not read `next` from its own query string. The deep link is
 *   parked server-side when the flow begins and comes back out of the
 *   callback, so a link crafted by someone else cannot steer where a
 *   successful login lands. `services/oidc.py::safe_next_path` reduces it
 *   to a path on this site; the check below is the second half of the
 *   same belt-and-braces, in the tier that does the navigating.
 * - It does not retry. Every part of the flow is single-use: the state
 *   record is deleted on the way past, win or lose, and the binding
 *   cookie is cleared by the BFF. A retry button would only ever produce
 *   the same refusal, so the offer is to start again from /login.
 * - It does not show the IdP's `error_description` as-is. That string is
 *   attacker-influenceable in the general case; the error *code* is
 *   enough to tell "you cancelled" from "your IdP refused", and that is
 *   what the copy below is built from.
 */
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";

import { bffFetch } from "@/lib/bff-fetch";
import { useSession } from "@/lib/session-context";

function isSameSitePath(value: string): boolean {
  return value.startsWith("/") && !value.startsWith("//") && !value.includes("\\");
}

/** What the query string alone already rules out, before anything is
 * sent anywhere. Derived during render rather than set from the effect:
 * it depends on nothing but the URL. */
function refusalFromQuery(params: URLSearchParams): string | null {
  const error = params.get("error");
  if (error) {
    return error === "access_denied"
      ? "That sign-in was cancelled, or your organisation did not allow it."
      : "Your identity provider refused the sign-in.";
  }
  if (!params.get("code") || !params.get("state")) {
    return "That sign-in link is incomplete. Start again from the sign-in page.";
  }
  return null;
}

function SsoCallback() {
  const router = useRouter();
  const params = useSearchParams();
  const { setSession } = useSession();
  const [exchangeFailure, setExchangeFailure] = useState<string | null>(null);
  // React StrictMode double-mounts in development, and this exchange is
  // single-use on both sides — a second POST would spend a state record
  // that is already gone and report a failure over a login that worked.
  const startedRef = useRef(false);

  const refusal = refusalFromQuery(params);
  const failure = refusal ?? exchangeFailure;

  useEffect(() => {
    if (refusal || startedRef.current) return;
    startedRef.current = true;

    void (async () => {
      const resp = await bffFetch("/api/bff/auth/sso/callback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: params.get("code"), state: params.get("state") }),
      });
      if (!resp.ok) {
        const body = (await resp.json().catch(() => null)) as {
          error?: { message?: string };
          detail?: string;
        } | null;
        // The API's own refusals here are written for the person reading
        // them ("that sign-in attempt does not belong to this
        // organisation"), so they are shown rather than flattened.
        setExchangeFailure(
          body?.error?.message ?? body?.detail ?? "That sign-in could not be completed.",
        );
        return;
      }
      const body = (await resp.json()) as {
        access_token: string;
        expires_in: number;
        next_path?: string;
      };
      setSession(body);
      router.replace(
        body.next_path && isSameSitePath(body.next_path) ? body.next_path : "/learn",
      );
    })();
  }, [params, refusal, router, setSession]);

  if (!failure) {
    return (
      <main className="flex min-h-screen items-center justify-center p-6">
        <p role="status" style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
          Signing you in…
        </p>
      </main>
    );
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="card w-full max-w-sm text-center" style={{ padding: "2rem" }}>
        <h1 className="serif" style={{ fontSize: "1.25rem" }}>
          Single sign-on didn&rsquo;t complete
        </h1>
        <p className="mt-3" style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
          {failure}
        </p>
        <Link href="/login" className="btn btn--primary btn--block mt-4">
          Back to sign in
        </Link>
      </div>
    </main>
  );
}

export default function SsoCallbackPage() {
  // useSearchParams needs a suspense boundary above it, or the whole
  // route opts out of static rendering with a build-time warning.
  return (
    <Suspense
      fallback={
        <main className="flex min-h-screen items-center justify-center p-6">
          <p style={{ fontSize: "0.875rem", color: "var(--muted)" }}>Signing you in…</p>
        </main>
      }
    >
      <SsoCallback />
    </Suspense>
  );
}
