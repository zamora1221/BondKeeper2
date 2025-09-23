const CACHE = "bailsaas-v1";
const ASSETS = [
  "/", "/static/manifest.webmanifest",
  // add your core CSS/JS paths here
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (e) => {
  const { request } = e;
  if (request.method !== "GET") return;
  e.respondWith(
    caches.match(request).then((cached) =>
      cached || fetch(request).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(request, copy));
        return res;
      })
    )
  );
});

// Web Push → Notification
self.addEventListener("push", (e) => {
  let data = {};
  try { data = e.data.json(); } catch(_) {}
  const title = data.title || "BailSaaS";
  const body = data.body || "";
  const url = data.url || "/";
  e.waitUntil(
    self.registration.showNotification(title, {
      body, data: { url }, icon: "/static/icons/icon-192.png", badge: "/static/icons/icon-192.png"
    })
  );
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = e.notification.data?.url || "/";
  e.waitUntil(clients.matchAll({ type: "window" }).then(list => {
    for (const c of list) { if (c.url === url && "focus" in c) return c.focus(); }
    return clients.openWindow(url);
  }));
});
