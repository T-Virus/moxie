import { defineConfig, devices } from '@playwright/test'

// 固定使用冷门端口，避开开发机上 Docker/WSL 常占用的 8000。
const SERVER_PORT = process.env.MOXIE_E2E_SERVER_PORT || '18000'
const SERVER = `http://127.0.0.1:${SERVER_PORT}`
const CLIENT = 'http://127.0.0.1:5190'
const ADMIN = 'http://127.0.0.1:5180'
// 让 client/admin 的 Vite 代理指向 E2E 专属后端端口。
const proxyEnv = {
  VITE_API_PROXY: SERVER,
  VITE_API_PROXY_TARGET: SERVER,
}

export default defineConfig({
  testDir: './e2e-online',
  outputDir: './test-results',
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [
    ['list'],
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
  ],
  use: {
    baseURL: CLIENT,
    locale: 'zh-CN',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [{ name: 'online-chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: 'node e2e-online/start-server.mjs',
      url: `${SERVER}/healthz`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: { MOXIE_E2E_SERVER_PORT: SERVER_PORT },
    },
    {
      command: 'npm run dev -- --host 127.0.0.1',
      url: CLIENT,
      reuseExistingServer: true,
      timeout: 120_000,
      env: proxyEnv,
    },
    {
      command: 'npm --prefix ../admin run dev -- --host 127.0.0.1',
      url: ADMIN,
      reuseExistingServer: true,
      timeout: 120_000,
      env: proxyEnv,
    },
  ],
})
