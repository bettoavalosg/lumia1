// Web Push: el servidor manda { title, body, tag } y aquí se muestra. Se importa desde el service worker generado.
self.addEventListener('push', event => {
  let datos = {}
  try {
    datos = event.data ? event.data.json() : {}
  } catch {
    datos = { title: 'Mariela · 29', body: event.data ? event.data.text() : '' }
  }
  const titulo = datos.title || 'Mariela · 29'
  event.waitUntil(
    self.registration.showNotification(titulo, {
      body: datos.body || '',
      tag: datos.tag || 'mariela',
      renotify: true,
      icon: '/pwa-192.png',
      badge: '/favicon-32.png',
      vibrate: [80, 40, 80],
      data: { url: datos.url || '/' },
    }),
  )
})

self.addEventListener('notificationclick', event => {
  event.notification.close()
  const destino = (event.notification.data && event.notification.data.url) || '/'
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(ventanas => {
      for (const ventana of ventanas) {
        if ('focus' in ventana) return ventana.focus()
      }
      return self.clients.openWindow(destino)
    }),
  )
})
