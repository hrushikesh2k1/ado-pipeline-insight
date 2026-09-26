import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { '/api': 'http://127.0.0.1:8000' } },
  build: { outDir: 'dist', emptyOutDir: true },
  // @ts-expect-error Vitest configuration
  test: {
    exclude: ['**/node_modules/**', '**/dist/**', '**/playwright/**'],
  },
})
