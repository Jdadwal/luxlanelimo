/* Luxlane Driver — service worker (offline app shell) */
const CACHE = 'luxlane-driver-v2';
const ASSETS = [
  '/driver.html',
  '/assets/css/style.css',
  '/assets/css/driver.css',
  '/assets/js/driver.js',
  '/manifest.webmanifest',
  '/assets/img/icon.svg',
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  if (e.request.method !== 'GET') return; // don't intercept POST/etc.
  const url = new URL(e.request.url);
  // Never cache API calls — always go to the network for live data.
  if (url.pathname.startsWith('/api/')) {
    e.respondWith(fetch(e.request).catch(() => new Response('{"error":"offline"}', { headers: { 'Content-Type': 'application/json' } })));
    return;
  }
  // App shell: network-first so code updates apply immediately when online;
  // fall back to the cache when offline.
  e.respondWith(
    fetch(e.request).then(resp => {
      if (resp && resp.ok) {
        const copy = resp.clone();
        caches.open(CACHE).then(c => c.put(e.request, copy));
      }
      return resp;
    }).catch(() => caches.match(e.request))
  );
});
