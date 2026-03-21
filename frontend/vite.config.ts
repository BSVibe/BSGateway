import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  base: '/dashboard/',
  server: {
    allowedHosts: process.env.VITE_ALLOWED_HOSTS
      ? process.env.VITE_ALLOWED_HOSTS.split(',').map((h) => h.trim())
      : true,
    proxy: {
      '/api': 'http://localhost:8000',
    },
    headers: {
      'X-Content-Type-Options': 'nosniff',
      'X-Frame-Options': 'DENY',
      'Referrer-Policy': 'strict-origin-when-cross-origin',
    },
  },
  build: {
    // Code splitting strategy for better caching
    rollupOptions: {
      output: {
        manualChunks: (id: string) => {
          // Vendor libraries - stable and cacheable
          if (id.includes('node_modules/react')) return 'react_vendor'
          if (id.includes('node_modules/react-dom')) return 'react_vendor'
          if (id.includes('node_modules/react-router-dom')) return 'react_vendor'
          // UI libraries
          if (id.includes('node_modules/@headlessui/react')) return 'ui_vendor'
          if (id.includes('node_modules/@heroicons/react')) return 'ui_vendor'
          // (additional vendor splits can be added here)
        },
      },
    },
    // Inline small assets (<4KB) to reduce requests
    assetsInlineLimit: 4096,
    // Target modern browsers for better compression
    target: 'es2020',
    // CSS code splitting
    cssCodeSplit: true,
    // Source maps in production for debugging
    sourcemap: false,
    // Output chunk size warning threshold
    chunkSizeWarningLimit: 500,
  },
})
