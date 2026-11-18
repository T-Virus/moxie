import { readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'
import { describe, expect, it } from 'vitest'

const swPath = fileURLToPath(new URL('../../public/sw.js', import.meta.url))
const manifestPath = fileURLToPath(new URL('../../public/manifest.webmanifest', import.meta.url))
const indexPath = fileURLToPath(new URL('../../index.html', import.meta.url))

describe('PWA Service Worker 安全边界', () => {
  const sw = readFileSync(swPath, 'utf8')

  it('只处理 GET 请求', () => {
    expect(sw).toContain("req.method !== 'GET'")
  })

  it('排除 /v1/ 业务 API 与带查询串的请求（加密 payload / 登录态不缓存）', () => {
    expect(sw).toContain("url.pathname.startsWith('/v1/')")
    expect(sw).toContain('url.search')
  })

  it('导航用 network-first，失败才回退缓存壳', () => {
    expect(sw).toContain("req.mode === 'navigate'")
    expect(sw.indexOf('fetch(req)')).toBeLessThan(sw.indexOf('caches.match'))
  })

  it('离线壳只包含静态资源，不含业务路由', () => {
    expect(sw).toContain("/index.html")
    expect(sw).not.toMatch(/SHELL[^\]]*\/runs/)
  })
})

describe('PWA manifest 与 SEO', () => {
  it('manifest 声明 standalone 与图标', () => {
    const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'))
    expect(manifest.display).toBe('standalone')
    expect(manifest.start_url).toBe('/')
    expect(Array.isArray(manifest.icons)).toBe(true)
    expect(manifest.icons.length).toBeGreaterThan(0)
  })

  it('index.html 含 description / OG / manifest 引用', () => {
    const html = readFileSync(indexPath, 'utf8')
    expect(html).toContain('name="description"')
    expect(html).toContain('property="og:title"')
    expect(html).toContain('rel="manifest"')
  })
})

describe('Web Push 接收端', () => {
  const sw = readFileSync(swPath, 'utf8')

  it('处理 push 事件并展示截断后的通知', () => {
    expect(sw).toContain("addEventListener('push'")
    expect(sw).toContain('showNotification')
    expect(sw).toContain('slice(0, 500)')
  })

  it('通知点击只跳同源，跨域 payload 回退首页', () => {
    expect(sw).toContain("addEventListener('notificationclick'")
    expect(sw).toContain('u.origin !== self.location.origin')
    expect(sw).toContain("return '/'")
  })

  it('OG 图片与页面地址使用构建期站点域名占位符', () => {
    const html = readFileSync(indexPath, 'utf8')
    expect(html).toContain('property="og:url" content="{{SITE_URL}}/"')
    expect(html).toContain('property="og:image" content="{{SITE_URL}}/icon.svg"')
    expect(html).toContain('name="twitter:image"')
  })
})
