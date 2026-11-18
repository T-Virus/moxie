/** 后台错误上报：裸 fetch，不走 api.ts 的加密 / 401 刷新 / 重试，避免递归。 */

const API_BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/+$/, '')

export interface ReportPayload {
  level: 'error' | 'warn'
  code: string
  message: string
  source: string
  url: string
  request_id?: string
  user_agent?: string
  ts?: string
}

let lastRequestId = ''

export function noteRequestId(id: string | null | undefined): void {
  if (id) lastRequestId = id.slice(0, 64)
}

export function getLastRequestId(): string {
  return lastRequestId
}

const seen = new Map<string, number>()
const DEDUP_WINDOW_MS = 30_000

function shouldSend(key: string, now: number): boolean {
  const prev = seen.get(key)
  if (prev !== undefined && now - prev < DEDUP_WINDOW_MS) return false
  seen.set(key, now)
  if (seen.size > 200) {
    for (const [k, t] of seen) if (now - t > DEDUP_WINDOW_MS) seen.delete(k)
  }
  return true
}

export function sendReport(payload: ReportPayload): void {
  try {
    const now = Date.now()
    const key = `${payload.source}:${payload.code}:${payload.message.slice(0, 120)}`
    if (!shouldSend(key, now)) return
    const body = JSON.stringify({
      level: payload.level,
      code: payload.code.slice(0, 80),
      message: payload.message.slice(0, 1000),
      source: payload.source.slice(0, 16),
      url: payload.url.slice(0, 500),
      request_id: (payload.request_id || lastRequestId).slice(0, 64),
      user_agent: (payload.user_agent || (typeof navigator !== 'undefined' ? navigator.userAgent : '')).slice(0, 300),
      ts: payload.ts || new Date().toISOString(),
    })
    void fetch(`${API_BASE}/v1/telemetry/client-error`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      keepalive: true,
      credentials: 'omit',
    }).catch(() => {})
  } catch {
    /* 尽力而为 */
  }
}

/** API 错误：仅网络 / 超时 / 5xx 上报，4xx 属用户侧问题。 */
export function reportApiError(err: unknown, url: string, requestId = ''): void {
  const status = (err as { status?: number } | null)?.status ?? 0
  if (status >= 400 && status < 500) return
  const code = String((err as { code?: string } | null)?.code || 'client_error')
  const message = err instanceof Error ? err.message : String(err || 'unknown')
  sendReport({ level: 'error', code, message, source: 'admin', url, request_id: requestId || lastRequestId })
}

let installed = false

export function installErrorReporter(): void {
  if (installed || typeof window === 'undefined') return
  installed = true
  window.addEventListener('error', (event) => {
    sendReport({
      level: 'error',
      code: 'js_error',
      message: `${event.message} @ ${event.filename || ''}:${event.lineno || 0}`,
      source: 'admin',
      url: typeof location !== 'undefined' ? location.href : '',
    })
  })
  window.addEventListener('unhandledrejection', (event) => {
    const reason = (event as PromiseRejectionEvent).reason
    const message = reason instanceof Error ? reason.message : String(reason || 'unhandled rejection')
    sendReport({
      level: 'error',
      code: 'unhandled_rejection',
      message,
      source: 'admin',
      url: typeof location !== 'undefined' ? location.href : '',
    })
  })
}
