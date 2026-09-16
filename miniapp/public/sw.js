// 🌊 W4 — Minimal PWA Offline Cache (same-origin, /app/ scope)
// Cache-first for static assets, network-first for /api
const CACHE = 'humsyar-v4-20260909';
const PRECACHE = ['/', '/app/'];
self.addEventListener('install', (e) => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(PRECACHE).catch(()=>{})));
});
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim()));
});
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  // Only handle same-origin GET
  if (e.request.method !== 'GET' || url.origin !== self.location.origin) return;
  // API: network-first with 3s timeout fallback to cache
  if (url.pathname.startsWith('/api/')) {
    e.respondWith(fetch(e.request).then(r=>{
      // cache successful GETs for offline reading (optional)
      if (r.ok) { const c = r.clone(); caches.open(CACHE).then(cache=>cache.put(e.request, c)); }
      return r;
    }).catch(()=>caches.match(e.request)));
    return;
  }
  // Static: cache-first
  e.respondWith(caches.match(e.request).then(cached=>{
    if (cached) return cached;
    return fetch(e.request).then(r=>{
      if (r.ok && (url.pathname.startsWith('/app/') || url.pathname.match(/\.(js|css|png|jpg|jpeg|svg|woff2)$/))) {
        const c = r.clone(); caches.open(CACHE).then(cache=>cache.put(e.request, c));
      }
      return r;
    }).catch(()=>cached);
  }));
});
