import { defineConfig, devices } from '@playwright/test'

const SERVER = 'http://127.0.0.1:8000'
const CLIENT = 'http://127.0.0.1:5190'
const ADMIN = 'http://127.0.0.1:5180'

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
    },
    {
      command: 'npm run dev',
      url: CLIENT,
      reuseExistingServer: true,
      timeout: 120_000,
    },
    {
      command: 'npm --prefix ../admin run dev',
      url: ADMIN,
      reuseExistingServer: true,
      timeout: 120_000,
    },
  ],
})
