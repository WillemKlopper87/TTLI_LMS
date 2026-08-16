"use client";

/**
 * Web Push opt-in (01 §5.9) — payment approved/rejected, certificate/
 * badge issued, workshop reminders. Mounted globally next to SiteHeader
 * (app/layout.tsx), the same "renders nothing in the cases that don't
 * apply" pattern that component already established: signed out, push
 * unsupported by the browser, not configured for this deployment (no
 * VAPID key — GET /push/vapid-public-key's configured:false), already
 * subscribed, or dismissed once this session, all render null.
 */
import { useEffect, useState } from "react";

import { getAccessToken } from "@/lib/session";
import { useSession } from "@/lib/session-context";

const DISMISSED_KEY = "ttli-push-prompt-dismissed";

function urlBase64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const raw = atob((base64 + padding).replace(/-/g, "+").replace(/_/g, "/"));
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  return bytes;
}

export function NotificationOptIn() {
  const { accessToken, status } = useSession();
  const [visible, setVisible] = useState(false);
  const [vapidPublicKey, setVapidPublicKey] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (status !== "authenticated" || !accessToken) return;
    if (sessionStorage.getItem(DISMISSED_KEY)) return;
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) return;
    if (Notification.permission === "denied") return;

    let cancelled = false;
    (async () => {
      const keyResp = await fetch("/api/bff/push/vapid-public-key").catch(() => null);
      if (!keyResp?.ok) return;
      const key = await keyResp.json();
      if (!key.configured || cancelled) return;

      const registration = await navigator.serviceWorker.ready;
      const existing = await registration.pushManager.getSubscription();
      if (existing || cancelled) return;

      setVapidPublicKey(key.public_key);
      setVisible(true);
    })();
    return () => {
      cancelled = true;
    };
  }, [status, accessToken]);

  async function enable() {
    if (!vapidPublicKey || !accessToken) return;
    setBusy(true);
    setError(null);
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        setError("Notifications are blocked — you can turn them on later in your browser settings.");
        setBusy(false);
        return;
      }
      const registration = await navigator.serviceWorker.ready;
      const subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(vapidPublicKey),
      });
      const token = getAccessToken();
      await fetch("/api/bff/push-subscriptions", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify(subscription.toJSON()),
      });
      setVisible(false);
    } catch {
      setError("Could not enable notifications. Try again shortly.");
    }
    setBusy(false);
  }

  function dismiss() {
    sessionStorage.setItem(DISMISSED_KEY, "1");
    setVisible(false);
  }

  if (!visible) return null;

  return (
    <div
      className="mx-auto mt-3 flex max-w-2xl items-center justify-between gap-3 rounded-md p-3"
      style={{ background: "var(--surface-2)", fontSize: "0.8125rem" }}
      role="status"
    >
      <span>
        Get notified when a payment is approved, a certificate is issued, or a workshop is coming up.
      </span>
      <div className="flex shrink-0 gap-2">
        <button type="button" className="btn btn--ghost" onClick={dismiss}>
          Not now
        </button>
        <button type="button" className="btn btn--primary" disabled={busy} onClick={enable}>
          {busy ? "Enabling…" : "Enable"}
        </button>
      </div>
      {error ? (
        <p role="alert" style={{ color: "var(--stop)" }}>
          {error}
        </p>
      ) : null}
    </div>
  );
}
