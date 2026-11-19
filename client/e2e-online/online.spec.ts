import { expect, test, type Page } from '@playwright/test'
import { spawnSync } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const SERVER = `http://127.0.0.1:${process.env.MOXIE_E2E_SERVER_PORT || '18000'}`
const ADMIN = 'http://127.0.0.1:5180'
const here = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(here, '../..')

type ApiOpts = { method?: string; body?: unknown; anonymous?: boolean }

async function callApi<T>(page: Page, pathname: string, opts: ApiOpts = {}): Promise<T> {
  const normalized: ApiOpts = {
    ...opts,
    body:
      opts.body !== undefined && typeof opts.body !== 'string'
        ? JSON.stringify(opts.body)
        : opts.body,
  }
  return page.evaluate(
    async ({ pathname, opts }) => {
      const mod = (await import('/src/services/http.ts')) as {
        apiFetch<T>(path: string, opts?: Record<string, unknown>): Promise<T>
      }
      return mod.apiFetch<T>(pathname, opts)
    },
    { pathname, opts: normalized },
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

  const me = await callApi<{ id: number; email: string }>(page, '/auth/me')
  expect(me.id).toBeGreaterThan(0)

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

  // 顶栏用户下拉菜单：点击邮箱展开【账户设置】【退出】
  await page.locator('.user-menu__trigger').click()
  await expect(page.getByRole('menuitem', { name: '账户设置' })).toBeVisible()
  await expect(page.getByRole('menuitem', { name: '退出' })).toBeVisible()

  // 账户设置页：6 个功能 tab 可见（订阅与额度 / 自有模型从订阅页迁入）
  await page.goto('/account')
  await expect(page.getByRole('heading', { name: '账户设置' })).toBeVisible()
  for (const tabName of ['订阅与额度', '自有模型', '账号安全', '订单与退款', '数据与导出', '注销账号']) {
    await expect(page.getByRole('tab', { name: tabName })).toBeVisible()
  }

  // 订阅与额度 tab：已下单后展示当前订阅与本月额度
  await expect(page.getByText('本月额度')).toBeVisible()
  await expect(page.getByText('创作版')).toBeVisible()

  // 自有模型 tab：BYOK 配置区可见（API Key / 模型名 / 接口地址）
  await page.getByRole('tab', { name: '自有模型' }).click()
  await expect(page.locator('#byok-key')).toBeVisible()
  await expect(page.locator('#byok-model')).toBeVisible()
  await expect(page.locator('#byok-base-url')).toBeVisible()

  // 数据与导出 tab：真实点击导出（走前端 UI 而非直接调 API）
  await page.getByRole('tab', { name: '数据与导出' }).click()
  await expect(page.getByRole('button', { name: '导出我的数据' })).toBeVisible()
  const downloadPromise = page.waitForEvent('download', { timeout: 15_000 })
  await page.getByRole('button', { name: '导出我的数据' }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toMatch(/^moxie-data-\d{4}-\d{2}-\d{2}\.json$/)
  await expect(page.getByText('数据已导出，请检查浏览器下载。')).toBeVisible()

  // 订单与退款 tab：真实走 UI 查询可退金额并提交退款申请
  await page.getByRole('tab', { name: '订单与退款' }).click()
  await expect(page.getByRole('button', { name: '申请退款' }).first()).toBeVisible()
  await page.getByRole('button', { name: '申请退款' }).first().click()
  await expect(page.locator('#refund-reason')).toBeVisible({ timeout: 10_000 })
  await expect(page.getByText(/可退金额/)).toBeVisible()
  await page.locator('#refund-reason').fill('E2E 测试退款申请')
  await page.getByRole('button', { name: '提交申请', exact: true }).click()
  await expect(page.getByText('退款记录')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText('待审核').first()).toBeVisible()

  await callApi(page, '/auth/register', {
    method: 'POST',
    anonymous: true,
    body: { email: adminEmail, password },
  })
  bootstrapAdmin(adminEmail)

  // 账户设置页：真实提交注销申请（密码 + 确认串）
  await page.goto('/account?tab=danger')
  await expect(page.locator('#delete-password')).toBeVisible()
  await page.locator('#delete-password').fill(password)
  await page.locator('#delete-confirm').fill('DELETE_MY_ACCOUNT')
  await page.getByRole('button', { name: '提交注销申请' }).click()
  await expect(page.getByText('注销申请已提交')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText('状态：待清除')).toBeVisible()
  // 提交后前端会话已撤销：顶栏回到未登录态
  await expect(page.getByRole('link', { name: '登录', exact: true })).toBeVisible({ timeout: 10_000 })

  await page.goto(`${ADMIN}/#/login`)
  await page.locator('#identity').fill(adminEmail)
  await page.locator('#password').fill(password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page).toHaveURL(/#\/overview/, { timeout: 15_000 })

  await page.goto(`${ADMIN}/#/account-deletions`)
  await expect(
    page.locator('tbody tr td:nth-child(2)', { hasText: `#${me.id}` }).first(),
  ).toBeVisible({ timeout: 15_000 })
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: '立即清除' }).first().click()
  await expect(page.getByText('账号数据已清除')).toBeVisible({ timeout: 15_000 })
})
