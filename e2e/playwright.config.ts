import { defineConfig, devices } from '@playwright/test'
import os from 'node:os'
import path from 'node:path'

const PORT = Number(process.env.E2E_PORT || 8797)
const BASE_URL = `http://127.0.0.1:${PORT}`
// 本地无 Chromium 时可用系统浏览器：E2E_CHANNEL=msedge；CI 默认安装 Chromium。
const CHANNEL = process.env.E2E_CHANNEL as 'msedge' | 'chrome' | undefined

// 每次运行使用独立的临时根目录：MOBIT_ROOT 会让 src/paths.py 把 data/input/output/config
// 全部指向该目录，真实 data/ 不会被写入。目录由 scripts/start-server.mjs 创建、退出时清理。
// 这里只计算路径、不创建目录：Playwright 会多次加载配置（主进程 + worker），
// 提前 mkdir 会留下无内容的空目录。
const E2E_ROOT = path.join(
  os.tmpdir(),
  `moxie-e2e-${process.pid}-${Date.now().toString(36)}`,
)
process.env.E2E_ROOT = E2E_ROOT

export default defineConfig({
  testDir: './tests',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [
    ['list'],
    ['html', { outputFolder: 'artifacts/report', open: 'never' }],
  ],
  outputDir: 'test-results',
  globalTeardown: './scripts/global-teardown.mjs',
  use: {
    baseURL: BASE_URL,
    locale: 'zh-CN',
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'desktop-chromium',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
        ...(CHANNEL ? { channel: CHANNEL } : {}),
      },
    },
  ],
  webServer: {
    command: 'node scripts/start-server.mjs',
    url: `${BASE_URL}/`,
    cwd: path.resolve(import.meta.dirname),
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      ...process.env,
      E2E_ROOT,
      E2E_PORT: String(PORT),
      MOBIT_PORT: String(PORT),
      MOBIT_HOST: '127.0.0.1',
    },
  },
})
