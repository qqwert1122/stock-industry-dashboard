const CACHE_NAME = "stock-dashboard-__BUILD_TS__";
const STATIC_ASSETS = [
  "./",
  "./manifest.webmanifest",
  "./assets/pwa-icon-192.png",
  "./assets/pwa-icon-512.png"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(STATIC_ASSETS))
      .catch(() => undefined)
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

function notifyOfflineFallback(request) {
  self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
    clients.forEach((client) => client.postMessage({ type: "offline-fallback", url: request.url }));
  });
}

async function networkFirst(request) {
  const cache = await caches.open(CACHE_NAME);
  try {
    const response = await fetch(request);
    if (response && response.ok) {
      cache.put(request, response.clone()).catch(() => undefined);
    }
    return response;
  } catch (_error) {
    const cached = await cache.match(request);
    if (cached) {
      notifyOfflineFallback(request);
      return cached;
    }
    if (request.mode === "navigate") {
      const shell = await cache.match("./");
      if (shell) {
        notifyOfflineFallback(request);
        return shell;
      }
    }
    throw _error;
  }
}

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response && response.ok) {
    const cache = await caches.open(CACHE_NAME);
    cache.put(request, response.clone()).catch(() => undefined);
  }
  return response;
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  const isNavigation = request.mode === "navigate" || request.destination === "document";
  const isDataJson = /\/data\/.*\.json$/.test(url.pathname);
  if (isNavigation || isDataJson) {
    event.respondWith(networkFirst(request));
    return;
  }
  const isStaticAsset = url.pathname.endsWith("/manifest.webmanifest") || /\/assets\/pwa-icon-\d+\.png$/.test(url.pathname);
  if (isStaticAsset) {
    event.respondWith(cacheFirst(request));
  }
});
