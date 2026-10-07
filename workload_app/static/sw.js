/* Selecao+ on the home screen.
 *
 * A phone only offers to keep a web page as an app when the page has a worker
 * like this one. It caches nothing but the page shown when there is no
 * connection: every screen, script and figure still comes straight from the
 * server, so an update is in use the next time the app opens.
 */
'use strict';

const CACHE = 'selecao-offline-1';
const OFFLINE = 'offline.html';

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.add(OFFLINE)));
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (event) => {
  // Only opening a page is answered here, and only when the network cannot.
  if (event.request.mode !== 'navigate') return;
  event.respondWith(fetch(event.request).catch(() => caches.match(OFFLINE)));
});
