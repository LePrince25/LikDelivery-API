const CACHE_NAME = "livraison-express-v5";
const PRECACHE = [
  "/",
  "/css/style.css",
  "/js/app.js",
  "/manifest.json",
  "/images/icon-192.svg",
  "/images/icon-512.svg"
];

self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", event => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);

  // Never cache API or uploaded product images (always network)
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/uploads/")) {
    event.respondWith(
      fetch(req).catch(() => new Response("", { status: 503, statusText: "Offline" }))
    );
    return;
  }

  const isAppAsset =
    url.pathname === "/" ||
    url.pathname.endsWith(".js") ||
    url.pathname.endsWith(".css") ||
    url.pathname.endsWith(".html");

  if (isAppAsset) {
    event.respondWith(
      fetch(req)
        .then(res => {
          const copy = res.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(req, copy));
          return res;
        })
        .catch(() => caches.match(req).then(r => r || caches.match("/")))
    );
    return;
  }

  event.respondWith(
    fetch(req)
      .then(res => res)
      .catch(() => caches.match(req).then(r => r || caches.match("/")))
  );
});
