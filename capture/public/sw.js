// cam3D Capture service worker: the app opens and captures without network.
// Photos live in IndexedDB; this only caches the application shell.
const CACHE = "cam3d-capture-v1";
const SHELL = ["/", "/scan/", "/settings/", "/t/", "/manifest.webmanifest", "/icon.svg"];

self.addEventListener("install", (e) => {
  e.waitUntil((async () => {
    const c = await caches.open(CACHE);
    await c.addAll(SHELL);
    // also cache the scripts/styles each page needs, so a reload works offline
    const assets = new Set();
    for (const page of SHELL.filter((u) => u.endsWith("/"))) {
      const res = await c.match(page);
      const html = res ? await res.text() : "";
      for (const m of html.matchAll(/\/_next\/static\/[^"'\s)]+/g)) assets.add(m[0]);
    }
    await Promise.all([...assets].map((a) => c.add(a).catch(() => undefined)));
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
  if (url.pathname.startsWith("/_next/static/")) {
    // immutable build assets: cache first
    e.respondWith(caches.match(req).then((hit) => hit || fetch(req).then((res) => {
      const copy = res.clone();
      caches.open(CACHE).then((c) => c.put(req, copy));
      return res;
    })));
    return;
  }
  // pages and other assets: network first, cache fallback (works offline)
  e.respondWith(fetch(req).then((res) => {
    if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); }
    return res;
  }).catch(() => caches.match(req, { ignoreSearch: true }).then((hit) => hit || caches.match("/", { ignoreSearch: true }))));
});
