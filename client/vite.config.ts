import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// 开发期把 /v1 代理到本机服务端（默认 http://127.0.0.1:8000），
// 这样不需要改服务端 CORS 白名单；生产构建用 VITE_API_BASE 指向真实域名。
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.VITE_API_PROXY || 'http://127.0.0.1:8000'
  return {
    plugins: [
      vue(),
      {
        // 社交分享卡需要绝对 URL；未配置 VITE_SITE_URL 时退化为相对路径，
        // 本地/内网部署无需改动，生产填正式域名即自动补全 OG/Twitter 图片与页面地址。
        name: 'moxie-og-absolute-url',
        transformIndexHtml(html: string) {
          const site = (env.VITE_SITE_URL || '').trim().replace(/\/+$/, '')
          return html.replaceAll('{{SITE_URL}}', site)
        },
      },
    ],
    resolve: {
      alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
    },
    server: {
      port: 5190,
      strictPort: true,
      proxy: {
        '/v1': { target, changeOrigin: true },
      },
    },
    preview: { port: 5190 },
    build: {
      outDir: 'dist',
      emptyOutDir: true,
      sourcemap: false,
    },
  }
})
