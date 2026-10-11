import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(), // Tailwind v4 — no postcss.config needed
  ],
  server: {
    port: 5173,
    proxy: {
      '/analyze': 'http://127.0.0.1:8000',
      '/api': 'http://127.0.0.1:8000',
      '/news': 'http://127.0.0.1:8000',
      '/market': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
      '/seed-graph': 'http://127.0.0.1:8000',
      '/knowledge-graph': 'http://127.0.0.1:8000',
      '/validate': 'http://127.0.0.1:8000',
    },
  },
})
