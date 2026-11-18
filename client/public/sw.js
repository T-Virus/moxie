/* 墨写 PWA Service Worker：只做静态资源的离线兜底，绝不碰业务数据。
 *
 * 安全边界：
 *  - 只缓存 GET 且同源的「导航请求」与「带内容类型签名的静态资源」；
 *  - /v1/ 下的所有 API（含加密 payload、登录态、额度）一律直通网络，不缓存；
 *  - 带查询串的 API、非 GET 请求、跨域请求一律直通；
 *  - 导航用 network-first（网络恢复即拿最新版），失败才回退 index.html；
 *  - 静态资产用 cache-first（Vite 产物带 hash，内容变则 URL 变）。
 * 这样离线时能打开已有页面壳，但绝不会把过期/他人的业务数据离线留存。
 */
const CACHE = 'moxie-shell-v1'
const SHELL = ['/', '/index.html', '/manifest.webmanifest', '/icon.svg', '/icon-maskable.svg']

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()))
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  )
})

function isApi(url) {
  return url.pathname === '/v1' || url.pathname.startsWith('/v1/')
}

function isStaticAsset(url) {
  // Vite 构建产物统一落在 /assets/，文件名带内容 hash，可安全长期缓存
  return url.pathname.startsWith('/assets/') || /\.(?:svg|ico|woff2?|css|js)$/.test(url.pathname)
}

self.addEventListener('fetch', (event) => {
  const req = event.request
  if (req.method !== 'GET') return
  const url = new URL(req.url)
  if (url.origin !== self.location.origin) return
  if (isApi(url) || url.search) return  // 业务 API 与带参数请求不缓存

  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req)
        .then((resp) => {
          if (resp && resp.ok) {
            const copy = resp.clone()
            caches.open(CACHE).then((cache) => cache.put('/index.html', copy))
          }
          return resp
        })
        .catch(() => caches.match('/index.html')),
    )
    return
  }

  if (isStaticAsset(url)) {
    event.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((resp) => {
        if (resp && resp.ok) {
          const copy = resp.clone()
          caches.open(CACHE).then((cache) => cache.put(req, copy))
        }
        return resp
      })),
    )
  }
})

/* ---- Web Push：通知展示与点击跳转 ----------------------------------------
 * 推送正文来自不可信服务端，一律按字符串截断；跳转目标限定同源相对路径，
 * 防止恶意 payload 把用户带到钓鱼站。
 */
function safeNotificationUrl(raw) {
  if (typeof raw !== 'string' || !raw) return '/'
  try {
    const u = new URL(raw, self.location.origin)
    if (u.origin !== self.location.origin) return '/'
    return u.pathname + u.search + u.hash
  } catch (e) {
    return '/'
  }
}

self.addEventListener('push', (event) => {
  let payload = {}
  if (event.data) {
    try {
      payload = event.data.json()
    } catch (e) {
      payload = { body: event.data.text() }
    }
  }
  if (!payload || typeof payload !== 'object') payload = {}
  const title = String(payload.title || '墨写').slice(0, 120)
  event.waitUntil(self.registration.showNotification(title, {
    body: String(payload.body || '').slice(0, 500),
    icon: '/icon.svg',
    badge: '/icon.svg',
    tag: String(payload.tag || 'moxie').slice(0, 100),
    data: { url: safeNotificationUrl(payload.url) },
  }))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const target = safeNotificationUrl(event.notification.data && event.notification.data.url)
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      const targetPath = new URL(target, self.location.origin).pathname
      for (const client of clients) {
        if (new URL(client.url).pathname === targetPath) return client.focus()
      }
      return self.clients.openWindow(target)
    }),
  )
})
