import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// 开发/预览时把管理端请求代理到本机服务端，避免浏览器跨域。
// 生产环境若与管理端不同域，请把 VITE_API_BASE 指向服务端，并由服务端配置 CORS。
const target = process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000'
const proxy = {
  '/v1': { target, changeOrigin: true },
  '/healthz': { target, changeOrigin: true },
  '/readyz': { target, changeOrigin: true },
  '/metrics': { target, changeOrigin: true },
}

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5180,
    strictPort: true,
    proxy,
  },
  preview: {
    port: 5180,
    strictPort: true,
    proxy,
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
  },
})
