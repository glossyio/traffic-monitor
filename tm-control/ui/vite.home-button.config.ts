import { defineConfig, type Plugin } from 'vite'

// The home button's script, built after the control app into the same dist/: one file that nginx serves at
// /home-button.js and adds to each app's page. It runs on someone else's page, so it stays small and plain: no Vue,
// and the build fails if it grows past the limit.
const LIMIT = 10240

const sizeLimit: Plugin = {
  name: 'home-button-size-limit',
  generateBundle(_options, bundle) {
    for (const file of Object.values(bundle)) {
      // Bytes, which is what nginx sends, and not characters
      const size = file.type === 'chunk' ? Buffer.byteLength(file.code, 'utf8') : 0
      if (size > LIMIT) throw new Error(`home-button.js is ${size} bytes; the limit is ${LIMIT}`)
    }
  },
}

export default defineConfig({
  plugins: [sizeLimit],
  build: {
    outDir: 'dist',
    emptyOutDir: false,
    lib: {
      entry: 'src/home-button/entry.ts',
      formats: ['iife'],
      name: 'tmHomeButton',
      fileName: () => 'home-button.js',
    },
  },
})
