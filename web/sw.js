// Keeps the app working offline: fresh files when the Pi answers within 2 s, the cached copy otherwise.
const CACHE = 'ember-2';
const SCRIPTS = ['app.js', 'core.js', 'text.js', 'sound.js', 'write.js', 'ask.js', 'list.js', 'note.js', 'read.js'];

self.oninstall = e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(['./', 'style.css', ...SCRIPTS, 'manifest.json', 'fonts/courier-prime.woff2', 'fonts/courier-prime-bold.woff2'])));
  self.skipWaiting();
};

self.onactivate = e => e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));  // an older app's files go

self.onfetch = e => {
  const path = new URL(e.request.url).pathname;
  if (e.request.method !== 'GET' || /^\/(api|files\/thumbs|files\/speech)\//.test(path)) return;  // thumbnails and notes read aloud come and go
  e.respondWith(caches.open(CACHE).then(cache => {
    const fresh = fetch(e.request).then(r => (r.ok && cache.put(e.request, r.clone()), r));
    const slow = new Promise((_, fail) => setTimeout(fail, 2000));
    return Promise.race([fresh, slow]).catch(() => cache.match(e.request, { ignoreSearch: true }).then(hit => hit || fresh));
  }));
};
