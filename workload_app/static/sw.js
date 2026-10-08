/* Selecao+ on the home screen.
 *
 * A phone only offers to keep a web page as an app when the page has a worker
 * like this one. It caches nothing but the page shown when there is no
 * connection: every screen, script and figure still comes straight from the
 * server, so an update is in use the next time the app opens.
 *
 * It also shows the notifications the server sends (workload_app/notify.py):
 * each arrives sealed for this phone, and a tap opens the app at the view it
 * is about.
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

self.addEventListener('push', (event) => {
  let message = {};
  try { message = event.data ? event.data.json() : {}; } catch (error) { message = {}; }
  // A phone drops a subscription whose pushes show nothing, so something is
  // always shown, even when the message could not be read.
  const title = message.title || 'Selecao+';
  event.waitUntil(self.registration.showNotification(title, {
    body: message.body || 'Something needs you. Open Selecao+ to see it.',
    tag: message.tag || 'selecao',
    icon: 'brand/selecao-icon-192.png',
    badge: 'brand/selecao-icon-192.png',
    data: { url: message.url || './' },
  }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = new URL((event.notification.data && event.notification.data.url) || './',
    self.registration.scope).href;
  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    .then((open) => {
      const app = open.find((client) => client.url.startsWith(self.registration.scope));
      if (app) {
        app.postMessage({ open: target });
        return app.focus();
      }
      return self.clients.openWindow(target);
    }));
});
