/* global self, caches, fetch, URL, Response */

const CACHE_NAME = "trader-safe-shell-v1";
const SAFE_SHELL = ["/offline", "/manifest.webmanifest", "/icons/app-icon.svg"];
const SAFE_STATIC_PREFIXES = ["/_next/static/", "/icons/"];
const SENSITIVE_PREFIXES = [
  "/api/",
  "/files/",
  "/downloads/",
  "/requests",
  "/results",
  "/publications",
  "/notifications",
  "/profile",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(SAFE_SHELL)));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("message", (event) => {
  if (event.data?.type === "SKIP_WAITING") void self.skipWaiting();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (isSensitiveRequest(request, url)) {
    event.respondWith(fetch(request, { cache: "no-store" }));
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request, { cache: "no-store" }).catch(async () => {
        const fallback = await caches.match("/offline");
        return fallback ?? Response.error();
      }),
    );
    return;
  }

  if (isSafeStaticAsset(url.pathname)) {
    event.respondWith(
      caches.match(request).then(async (cached) => {
        if (cached) return cached;
        const response = await fetch(request);
        if (response.ok && response.type === "basic") {
          const cache = await caches.open(CACHE_NAME);
          await cache.put(request, response.clone());
        }
        return response;
      }),
    );
  }
});

function isSensitiveRequest(request, url) {
  return (
    request.headers.has("Authorization") ||
    request.headers.has("X-CSRF-Token") ||
    url.searchParams.has("_rsc") ||
    SENSITIVE_PREFIXES.some((prefix) => {
      const exactPath = prefix.endsWith("/") ? prefix.slice(0, -1) : prefix;
      return url.pathname === exactPath || url.pathname.startsWith(prefix);
    })
  );
}

function isSafeStaticAsset(pathname) {
  return (
    SAFE_SHELL.includes(pathname) ||
    SAFE_STATIC_PREFIXES.some((prefix) => pathname.startsWith(prefix))
  );
}
