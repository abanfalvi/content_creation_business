import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In development the API runs separately (`uv run podcast-server`); /api is proxied to it.
// In production FastAPI serves the built files from dist/ itself.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})
