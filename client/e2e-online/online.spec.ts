import { expect, test, type Page } from '@playwright/test'
import { spawnSync } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const SERVER = 'http://127.0.0.1:8000'
const ADMIN = 'http://127.0.0.1:5180'
const here = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(here, '../..')

type ApiOpts = { method?: string; body?: unknown; anonymous?: boolean }

async function callApi<T>(page: Page, pathname: string, opts: ApiOpts = {}): Promise<T> {
  return page.evaluate(
    async ({ pathname, opts }) => {
      const mod = (await import('/src/services/http.ts')) as {
        apiFetch<T>(path: string, opts?: Record<string, unknown>): Promise<T>
      }
      return mod.apiFetch<T>(pathname, opts)
    },
    { pathname, opts },
  )
}

function bootstrapAdmin(email: string): void {
  const envPath = path.join(root, 'client', '.e2e-online-env.json')
  const env = JSON.parse(readFileSync(envPath, 'utf8')) as NodeJS.ProcessEnv
  const serverDir = path.join(root, 'server')
  const venvPython = path.join(serverDir, '.venv', 'Scripts', 'python.exe')
  const python = process.platform === 'win32' && existsSync(venvPython) ? venvPython : 'python'
  const result = spawnSync(python, ['scripts/bootstrap_admin.py', '--email', email], {
    cwd: serverDir,
    env: { ...process.env, ...env },
    encoding: 'utf8',
  })
  expect(result.status, result.stderr || result.stdout).toBe(0)
}

test('online main chain: register → subscribe → run → export → delete → admin purge', async ({ page }) => {
  const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`
  const userEmail = `e2e-user-${suffix}@example.test`
  const adminEmail = `e2e-admin-${suffix}@example.test`
  const password = 'E2ePass123!'
  const runTitle = `E2E 主链 ${suffix}`

  await page.goto('/login?tab=register')
  await page.locator('#auth-email').fill(userEmail)
  await page.locator('#auth-password').fill(password)
  await page.locator('.auth__check').check()
  await page.getByRole('button', { name: '注册', exact: true }).click()
  await expect
    .poll(() => page.evaluate(() => !!sessionStorage.getItem('mx_access_token')), { timeout: 15_000 })
    .toBe(true)

  const me = await callApi<{ account: { id: number } }>(page, '/auth/me')
  expect(me.account.id).toBeGreaterThan(0)

  await page.goto('/plans')
  await expect(page.getByText(/套餐|方案/).first()).toBeVisible()

  const subscription = await callApi<{
    payment: { params: { webhook_path: string; signature: string; body: unknown } }
  }>(page, '/subscriptions', {
    method: 'POST',
    body: { plan_code: 'creator', cycle: 'month', provider: 'mock' },
  })
  const callback = await page.request.post(
    new URL(subscription.payment.params.webhook_path, SERVER).toString(),
    {
      data: subscription.payment.params.body,
      headers: { 'x-mock-signature': subscription.payment.params.signature },
    },
  )
  expect(callback.ok()).toBeTruthy()
  expect((await callback.json()).order_status).toBe('paid')

  const run = await callApi<{ run_id: string; status: string }>(page, '/agent-runs', {
    method: 'POST',
    body: {
      mode: 'hot',
      title: runTitle,
      audience: 'male',
      length: 'short',
      genre: { id: 'xuanhuan', name: '玄幻' },
    },
  })
  expect(run.run_id).toBeTruthy()
  expect(run.status).toBeTruthy()

  await page.goto('/runs')
  await expect(page.getByText(runTitle)).toBeVisible()

  const exportData = await callApi<{ generated_at?: string; account?: unknown }>(page, '/me/export')
  expect(exportData).toBeTruthy()
  expect(exportData.account).toBeTruthy()

  await callApi(page, '/auth/register', {
    method: 'POST',
    anonymous: true,
    body: { email: adminEmail, password },
  })
  bootstrapAdmin(adminEmail)

  const deletion = await callApi<{ id: number; status: string }>(page, '/me/delete', {
    method: 'POST',
    body: { password, confirmation: 'DELETE_MY_ACCOUNT' },
  })
  expect(deletion.id).toBeGreaterThan(0)
  expect(deletion.status).toBe('pending')

  await page.goto(`${ADMIN}/#/login`)
  await page.locator('#identity').fill(adminEmail)
  await page.locator('#password').fill(password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page).toHaveURL(/#\/overview/, { timeout: 15_000 })

  const adminToken = await page.evaluate(() => {
    const raw = sessionStorage.getItem('moxie_admin_session') || '{}'
    return (JSON.parse(raw) as { access_token?: string }).access_token || ''
  })
  expect(adminToken).toBeTruthy()

  const listResp = await page.request.get(`${ADMIN}/v1/admin/account-deletions?status=pending`, {
    headers: { Authorization: `Bearer ${adminToken}` },
  })
  expect(listResp.ok()).toBeTruthy()
  const list = (await listResp.json()) as {
    items: Array<{ id: number; account_id: number; status: string }>
  }
  const found = list.items.find((item) => item.account_id === me.account.id)
  expect(found, `deletion request for account ${me.account.id} not found`).toBeTruthy()

  const purgeResp = await page.request.post(
    `${ADMIN}/v1/admin/account-deletions/${found!.id}/purge`,
    { headers: { Authorization: `Bearer ${adminToken}` } },
  )
  expect(purgeResp.ok()).toBeTruthy()
  expect((await purgeResp.json()).deleted).toBe(true)
})
