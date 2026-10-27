// Keeps the app working offline: fresh files when the Pi answers within 2 s, the cached copy otherwise.
const CACHE = 'ember-1';

self.oninstall = e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(['./', 'style.css', 'app.js', 'manifest.json', 'fonts/courier-prime.woff2', 'fonts/courier-prime-bold.woff2'])));
  self.skipWaiting();
};

self.onactivate = e => e.waitUntil(self.clients.claim());

self.onfetch = e => {
  if (e.request.method !== 'GET' || new URL(e.request.url).pathname.startsWith('/api/')) return;
  e.respondWith(caches.open(CACHE).then(cache => {
    const fresh = fetch(e.request).then(r => (r.ok && cache.put(e.request, r.clone()), r));
    const slow = new Promise((_, fail) => setTimeout(fail, 2000));
    return Promise.race([fresh, slow]).catch(() => cache.match(e.request, { ignoreSearch: true }).then(hit => hit || fresh));
  }));
};
