import { defineConfig, loadEnv, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'

const MESA = '#07050a'

// CSP solo en producción: en desarrollo, el preámbulo de React Refresh es un script en línea.
// Supabase se agrega a connect-src en la Fase 2.
const CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "font-src 'self'",
  "img-src 'self' data: blob:",
  "connect-src 'self'",
  "manifest-src 'self'",
  "worker-src 'self'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join('; ')

function html(sitio: string): Plugin {
  return {
    name: 'mariela:html',
    transformIndexHtml: {
      order: 'pre',
      handler: (texto, ctx) =>
        texto
          .replaceAll('%SITIO%', sitio)
          .replace('<!--CSP-->', ctx.server ? '' : `<meta http-equiv="Content-Security-Policy" content="${CSP}">`),
    },
  }
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // og:image necesita URL absoluta: en Vercel sale del dominio de producción; en local, de VITE_SITE_URL.
  const sitio = (env.VITE_SITE_URL || (env.VERCEL_PROJECT_PRODUCTION_URL ? `https://${env.VERCEL_PROJECT_PRODUCTION_URL}` : '')).replace(/\/$/, '')

  return {
    plugins: [
      html(sitio),
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
          globIgnores: ['**/node_modules/**/*', 'pwa-*.png'],
          navigateFallback: '/index.html',
          cleanupOutdatedCaches: true,
          // Desde la primera visita el service worker controla la página: sin red, ya funciona.
          clientsClaim: true,
        },
      }),
    ],
  }
})
