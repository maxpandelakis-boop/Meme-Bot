// Service worker of the Trencher web app: keeps the app's own files so it opens without network and installs as an app.
// Network first (an update shows up on the next start), cache only as fallback. Data APIs (prices, chain, Reddit) are never cached.
const CACHE = "trencher-v15";
const SHELL = ["copy.html", "copy.css", "copy.js", "copy-engine.js", "scout.js", "sim.js", "lib/lightweight-charts.standalone.production.js",
               "app-manifest.json", "icons/app-192.png", "icons/app-512.png", "icons/app-180.png"];
// one by one, a file that fails (e.g. an icon the host redirects elsewhere) must not stop the install
self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => Promise.all(SHELL.map(f => c.add(f).catch(() => {})))).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin) return;     // APIs: straight to the network
  e.respondWith(fetch(e.request, { cache: "no-cache" }).then(r => {      // always ask the server: no stale file from the browser's own cache
    if (r.ok) { const c = r.clone(); caches.open(CACHE).then(x => x.put(e.request, c)); }
    return r;
  }).catch(() => caches.match(e.request, { ignoreSearch: true })));
});
