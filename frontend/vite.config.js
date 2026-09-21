import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import basicSsl from '@vitejs/plugin-basic-ssl'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  // The backend address is configuration, not source. It used to be a
  // hardcoded LAN IP here, so moving the API meant editing this file -- and
  // the symptom was a frontend that looked like a dead backend rather than a
  // misconfigured one.
  const target = env.VITE_BACKEND_TARGET || 'http://127.0.0.1:8000'

  const appName = env.VITE_APP_NAME || 'ESSCAN'
  const shortName = env.VITE_APP_SHORT_NAME || appName
  const themeColor = env.VITE_APP_THEME_COLOR || '#462776'

  return {
    plugins: [
      react(),
      tailwindcss(),
      basicSsl(),
      VitePWA({
        // Ship a new bundle and browsers pick it up on the next visit instead
        // of serving last week's frontend against this week's API. 'prompt'
        // rather than 'autoUpdate' so the app is never swapped out from under
        // someone mid-scan; PWAUpdatePrompt.jsx surfaces the waiting version.
        registerType: 'prompt',
        includeAssets: ['favicon.svg', 'apple-touch-icon.png'],

        manifest: {
          name: appName,
          short_name: shortName,
          description: appName + ' automated assessment',
          theme_color: themeColor,
          background_color: '#ffffff',
          display: 'standalone',
          orientation: 'portrait',
          start_url: '/',
          scope: '/',
          icons: [
            { src: 'pwa-192x192.png', sizes: '192x192', type: 'image/png' },
            { src: 'pwa-512x512.png', sizes: '512x512', type: 'image/png' },
            {
              // Android crops icons to the launcher's shape. A maskable icon
              // keeps the logo inside the safe zone so the corners are not
              // shaved off.
              src: 'pwa-maskable-512x512.png',
              sizes: '512x512',
              type: 'image/png',
              purpose: 'maskable',
            },
          ],
        },

        workbox: {
          globPatterns: ['**/*.{js,css,html,svg,png,woff2}'],

          // Scanned pages are large and the bundle is not small; the default
          // 2MB precache ceiling silently drops files past it.
          maximumFileSizeToCacheInBytes: 5 * 1024 * 1024,

          // NOTHING under /api may be cached or served from the shell.
          //
          // A professor watches a submission move from Processing to Graded by
          // polling. Serving even one stale response makes grading look stuck,
          // and the bug presents as a backend fault. The denylist keeps the
          // SPA fallback off API routes; the NetworkOnly rule keeps Workbox
          // from caching them.
          navigateFallback: 'index.html',
          navigateFallbackDenylist: [/^\/api/],
          runtimeCaching: [
            {
              urlPattern: ({ url }) => url.pathname.startsWith('/api'),
              handler: 'NetworkOnly',
            },
          ],

          cleanupOutdatedCaches: true,
        },

        devOptions: {
          // Lets the service worker be tested with `npm run dev` instead of
          // only after a build. Registration still requires a TRUSTED
          // certificate: @vitejs/plugin-basic-ssl issues a self-signed one,
          // and browsers refuse to register a service worker on an origin
          // with a certificate error. localhost is exempt.
          enabled: true,
          type: 'module',
        },
      }),
    ],

    server: {
      host: '0.0.0.0',
      https: true,
      proxy: {
        '/api': {
          target,
          changeOrigin: true,
          secure: false,
        },
      },
    },
  }
})
