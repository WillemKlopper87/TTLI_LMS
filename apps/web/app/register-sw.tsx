"use client";

import { useEffect } from "react";

/**
 * Registers the app-shell service worker (public/sw.js) on mount.
 * A no-op, not an error, when the browser doesn't support service
 * workers (or in dev with hot-reload disagreeing with a stale worker) —
 * the app works identically either way; this only adds the offline shell.
 */
export function RegisterServiceWorker() {
  useEffect(() => {
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => undefined);
    }
  }, []);
  return null;
}
