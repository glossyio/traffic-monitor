import vue from '@vitejs/plugin-vue'
import vuetify from 'vite-plugin-vuetify'
import { defineConfig } from 'vitest/config'

// `npm run dev` and `npm run preview` send API calls to a tm-control backend on this machine, usually one in fake
// mode (see README.md). changeOrigin: false keeps the browser's Host header, which the backend's cross-site check
// compares with Origin, as nginx does on a device. (Vite's 'path': 'url' shorthand would change it.)
const target = { target: 'http://127.0.0.1:8090', changeOrigin: false }
const backend = { '/api': target, '/logout': target }

export default defineConfig({
  plugins: [
    vue(),
    // Imports only the Vuetify components the pages use, with the SASS settings in src/styles/settings.scss
    vuetify({ autoImport: true, styles: { configFile: 'src/styles/settings.scss' } }),
  ],
  server: { proxy: backend },
  preview: { proxy: backend },
  test: {
    environment: 'jsdom',
    setupFiles: ['tests/setup.ts'],
    server: { deps: { inline: ['vuetify'] } },
  },
})
