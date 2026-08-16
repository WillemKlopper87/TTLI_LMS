// Phase 4.5 PWA (01 §5.9): an offline *shell*, not offline data — this
// platform's content is per-tenant and server-rendered from a live API,
// so caching course/lesson data here would mean building sync and
// conflict resolution this project has no infrastructure for yet. What a
// service worker can honestly provide today: the app frame still loads
// (with a real offline notice) instead of the browser's default
// connection-error page when a learner opens the app with no network.

const CACHE_NAME = "ttli-shell-v1";
const SHELL_ASSETS = ["/offline.html", "/icon-192.png", "/icon-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

// Network-first for navigations (real content is always preferred over a
// stale cache — this is a live app, not a static site); falls back to the
// cached offline shell only when the network request itself fails.
// Everything else (API calls, the BFF proxy) is left untouched — this
// service worker has no opinion on data freshness, only on keeping the
// app frame reachable.
self.addEventListener("fetch", (event) => {
  if (event.request.mode !== "navigate") return;
  event.respondWith(
    fetch(event.request).catch(
      () => caches.match("/offline.html") || new Response("Offline", { status: 503 })
    )
  );
});

// Web Push (01 §5.9). The payload is whatever services/push.py::
// send_push_sync's `data=json.dumps({title, body, url})` sent — a plain
// JSON object, not a Notification-shaped payload, so this parses it
// itself rather than assuming event.data.json() is display-ready.
self.addEventListener("push", (event) => {
  let payload = { title: "TTLI", body: "" };
  try {
    payload = event.data ? event.data.json() : payload;
  } catch {
    // Not JSON — fall back to the plain-text body rather than dropping
    // the notification entirely.
    payload = { title: "TTLI", body: event.data ? event.data.text() : "" };
  }
  event.waitUntil(
    self.registration.showNotification(payload.title || "TTLI", {
      body: payload.body || "",
      icon: "/icon-192.png",
      badge: "/icon-192.png",
      data: { url: payload.url || "/" },
    })
  );
});

// Clicking the notification focuses an already-open tab on that URL if
// one exists, rather than always opening a new one.
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data && event.notification.data.url;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if (client.url.includes(url) && "focus" in client) return client.focus();
      }
      if (self.clients.openWindow) return self.clients.openWindow(url || "/");
    })
  );
});
