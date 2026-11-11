import { expect, test, type Page } from '@playwright/test'

const BOOK = 'e2e-smoke-book'

/** 收集控制台 error 与未捕获异常，测试末尾断言为空。 */
function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(`${msg.text()} @ ${msg.location().url}`)
  })
  page.on('pageerror', (error) => errors.push(`pageerror: ${error.message}`))
  return errors
}

async function openRoute(page: Page, route: string): Promise<string[]> {
  const errors = collectConsoleErrors(page)
  await page.goto(`/#${route}`)
  await expect(page.locator('body')).toBeVisible()
  return errors
}

test.describe('桌面端核心页面（本地模式）', () => {
  test('overview 加载作品详情与目录', async ({ page }) => {
    const errors = await openRoute(page, '/overview')
    await expect(page.locator('.overview-card')).toBeVisible()
    await expect(page.locator('.card-title', { hasText: '目录' })).toBeVisible()
    await expect(page.getByText('山门试炼', { exact: false }).first()).toBeVisible()
    expect(errors).toEqual([])
  })

  test('chapters 加载章节概括页', async ({ page }) => {
    const errors = await openRoute(page, '/chapters')
    await expect(page.getByRole('heading', { name: '章节概括' })).toBeVisible()
    await expect(page.getByText('山门试炼', { exact: false }).first()).toBeVisible()
    expect(errors).toEqual([])
  })

  test('characters 加载角色卡页面与角色数据', async ({ page }) => {
    const errors = await openRoute(page, '/characters')
    await expect(page.getByRole('heading', { name: '角色卡' })).toBeVisible()
    await expect(page.getByText('共 1 张', { exact: false })).toBeVisible()
    await expect(page.getByPlaceholder('未命名人物')).toHaveValue('林舟')
    expect(errors).toEqual([])
  })

  test('factions 加载势力表页面与势力数据', async ({ page }) => {
    const errors = await openRoute(page, '/factions')
    await expect(page.getByRole('heading', { name: '势力表' })).toBeVisible()
    await expect(page.getByText('共 1 个', { exact: false })).toBeVisible()
    await expect(page.getByPlaceholder('未命名势力')).toHaveValue('青云宗')
    expect(errors).toEqual([])
  })

  test('cloud 未登录时展示本地模式提示，不依赖真实云端', async ({ page }) => {
    const errors = await openRoute(page, '/cloud')
    await expect(page.getByRole('heading', { name: '云端账户' })).toBeVisible()
    await expect(page.getByText('当前为本地模式', { exact: false })).toBeVisible()
    await expect(page.getByText('本地拆解、改编、全书设定、章节数据等功能完全不受影响', { exact: false })).toBeVisible()
    expect(errors).toEqual([])
  })

  test('临时数据目录隔离：作品列表只包含 E2E 测试书', async ({ page, request }) => {
    await page.goto('/#/overview')
    await expect(page.locator('.overview-card')).toBeVisible()
    const response = await request.get('/api/books')
    expect(response.ok()).toBeTruthy()
    const payload = await response.json()
    const names = (payload.books || []).map((b: { name: string }) => b.name)
    expect(names).toContain(BOOK)
    expect(names.every((name: string) => name === BOOK)).toBeTruthy()
  })
})
