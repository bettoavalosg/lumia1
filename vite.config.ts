import { defineConfig, loadEnv, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'

const MESA = '#07050a'

// CSP solo en producción: en desarrollo, el preámbulo de React Refresh es un script en línea.
// 'wasm-unsafe-eval' es para el modo demo (Postgres en WebAssembly); no permite eval de JavaScript.
function csp(supabase: string): string {
  const conexiones = ["'self'"]
  if (supabase) {
    const url = new URL(supabase)
    conexiones.push(url.origin, `${url.protocol === 'http:' ? 'ws' : 'wss'}://${url.host}`)
  }
  return [
    "default-src 'self'",
    "script-src 'self' 'wasm-unsafe-eval'",
    "style-src 'self' 'unsafe-inline'",
    "font-src 'self'",
    "img-src 'self' data: blob:",
    `connect-src ${conexiones.join(' ')}`,
    "manifest-src 'self'",
    "worker-src 'self' blob:",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
  ].join('; ')
}

function html(sitio: string, politica: string): Plugin {
  return {
    name: 'mariela:html',
    transformIndexHtml: {
      order: 'pre',
      handler: (texto, ctx) =>
        texto
          .replaceAll('%SITIO%', sitio)
          .replace('<!--CSP-->', ctx.server ? '' : `<meta http-equiv="Content-Security-Policy" content="${politica}">`),
    },
  }
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // og:image necesita URL absoluta: en Vercel sale del dominio de producción; en local, de VITE_SITE_URL.
  const sitio = (env.VITE_SITE_URL || (env.VERCEL_PROJECT_PRODUCTION_URL ? `https://${env.VERCEL_PROJECT_PRODUCTION_URL}` : '')).replace(/\/$/, '')

  return {
    // PGlite trae su propio WebAssembly: Vite no debe reempaquetarlo al vuelo.
    optimizeDeps: { exclude: ['@electric-sql/pglite'] },
    build: {
      chunkSizeWarningLimit: 700,
      rolldownOptions: {
        // Todo lo del demo (Postgres en el navegador) en un chunk aparte y con nombre: solo se descarga si se usa.
        output: { codeSplitting: { groups: [{ name: 'pglite', test: /node_modules[\\/]@electric-sql[\\/]/ }] } },
      },
    },
    plugins: [
      html(sitio, csp(env.VITE_SUPABASE_URL ?? '')),
      react(),
      tailwindcss(),
      VitePWA({
        registerType: 'autoUpdate',
        injectRegister: 'script-defer',
        // Los íconos del manifest solo se usan al instalar: no van al precache (ver globIgnores).
        includeManifestIcons: false,
        manifest: {
          id: '/',
          name: 'Mariela cumple 29',
          short_name: 'Mariela 29',
          description: '…y esta noche alguien no va a salir viva. XOXO',
          lang: 'es-MX',
          start_url: '/',
          scope: '/',
          display: 'standalone',
          orientation: 'portrait',
          background_color: MESA,
          theme_color: MESA,
          icons: [
            { src: '/pwa-192.png', sizes: '192x192', type: 'image/png' },
            { src: '/pwa-512.png', sizes: '512x512', type: 'image/png' },
            { src: '/pwa-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
          ],
        },
        workbox: {
          // Sin og.jpg: la vista previa es para WhatsApp, no para el celular de cada invitado.
          globPatterns: ['**/*.{js,css,html,woff2,png}'],
          // El demo (Postgres en el navegador, ~17 MB) no viaja al celular de cada invitado; si se usa, se guarda al usarlo.
          globIgnores: ['**/node_modules/**/*', 'pwa-*.png', 'assets/pglite-*', 'assets/demo-*', 'assets/Simulador-*', 'assets/pgcrypto-*', 'assets/initdb-*'],
          runtimeCaching: [
            {
              urlPattern: ({ url }: { url: URL }) => /\/assets\/(pglite|demo|Simulador|pgcrypto|initdb)-[^/]+\.(js|wasm|data|gz)$/.test(url.pathname),
              handler: 'CacheFirst',
              options: { cacheName: 'demo', expiration: { maxEntries: 12 } },
            },
          ],
          // La lógica de notificaciones push (evento `push` y clic) vive aparte, en public/push-sw.js.
          importScripts: ['push-sw.js'],
          navigateFallback: '/index.html',
          cleanupOutdatedCaches: true,
          // Desde la primera visita el service worker controla la página: sin red, ya funciona.
          clientsClaim: true,
        },
      }),
    ],
  }
})
