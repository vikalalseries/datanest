import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
  build: {
    rollupOptions: {
      output: {
        // Libraries change rarely: separate chunks stay cached in the browser across app updates.
        manualChunks(id) {
          if (id.includes('node_modules/firebase') || id.includes('node_modules/@firebase')) return 'firebase'
          if (/node_modules\/(react|react-dom|react-router|react-router-dom|scheduler)\//.test(id)) return 'react'
        },
      },
    },
  },
  test: { env: { VITE_AUTH_DISABLED: 'false' }, environment: 'jsdom', globals: true, setupFiles: './src/setupTests.js' },
})
