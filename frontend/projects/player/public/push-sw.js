/*
 * Web Push service worker (realtime-and-notifications, 6.2).
 *
 * Receives pushes sent by the backend (organize/push.py) and shows a
 * notification; tapping it deep-links into the app (tower detail for
 * steal/conquer, map for bonus). Payloads are the JSON built by
 * `_build_payload`: { event, title, body, url, session, ... }.
 */

self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { body: event.data ? event.data.text() : '' };
  }
  const title = data.title || 'Cercetador';
  event.waitUntil(
    self.registration.showNotification(title, {
      body: data.body || '',
      tag: data.event ? `cercetador-${data.event}` : 'cercetador',
      data: { url: data.url || '/' },
    }),
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(
    clients
      .matchAll({ type: 'window', includeUncontrolled: true })
      .then((windowClients) => {
        for (const client of windowClients) {
          if ('focus' in client) {
            if ('navigate' in client) {
              client.navigate(url);
            }
            return client.focus();
          }
        }
        return clients.openWindow(url);
      }),
  );
});
