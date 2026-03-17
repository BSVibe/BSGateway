import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  base: '/dashboard/',
  server: {
    allowedHosts: (process.env.VITE_ALLOWED_HOSTS || 'bsserver')
      .split(',')
      .map((h) => h.trim()),
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
