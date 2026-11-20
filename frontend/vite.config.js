import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Khi phát triển: chuyển tiếp /api tới API Gateway chạy cục bộ
export default defineConfig({
  plugins: [vue()],
  server: { port: 5173, proxy: { '/api': 'http://127.0.0.1:8100' } },
  build: { outDir: 'dist', sourcemap: false, chunkSizeWarningLimit: 900 },
})
