import { API_BASE } from './config'
import { currentTraceId } from './trace'

/** 前端错误上报：用裸 fetch，绝不走 apiFetch，避免上报自身被加密 / 401 刷新 / 再次上报。 */

export interface ReportPayload {
  level: 'error' | 'warn'
  code: string
  message: string
  source: string
  url: string
  request_id?: string
  trace_id?: string
  user_agent?: string
  ts?: string
}

let lastRequestId = ''

/** http.ts 每次拿到响应后回填，供无 requestId 的 JS 异常做链路关联。 */
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

/** 发送上报。永不抛错、永不阻塞：失败静默，避免影响用户主流程。 */
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
      trace_id: (payload.trace_id || currentTraceId()).slice(0, 64),
      user_agent: (payload.user_agent || (typeof navigator !== 'undefined' ? navigator.userAgent : '')).slice(0, 300),
      ts: payload.ts || new Date().toISOString(),
    })
    void fetch(`${API_BASE}/telemetry/client-error`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      keepalive: true,
      credentials: 'omit',
    }).catch(() => {})
  } catch {
    /* 上报是尽力而为，任何异常都吞掉 */
  }
}

/** 上报 API 错误：仅网络错误 / 超时 / 5xx；4xx 是用户侧问题，不制造日志噪音。 */
export function reportApiError(err: unknown, url: string): void {
  const status = (err as { status?: number } | null)?.status ?? 0
  if (status >= 400 && status < 500) return
  const code = String((err as { code?: string } | null)?.code || 'client_error')
  const message = err instanceof Error ? err.message : String(err || 'unknown')
  const requestId = String((err as { requestId?: string } | null)?.requestId || '')
  sendReport({ level: 'error', code, message, source: 'client', url, request_id: requestId })
}

let installed = false

/** 安装全局 JS 异常与未处理 Promise 拒绝捕获；重复调用无副作用。 */
export function installErrorReporter(): void {
  if (installed || typeof window === 'undefined') return
  installed = true
  window.addEventListener('error', (event) => {
    sendReport({
      level: 'error',
      code: 'js_error',
      message: `${event.message} @ ${event.filename || ''}:${event.lineno || 0}`,
      source: 'client',
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
      source: 'client',
      url: typeof location !== 'undefined' ? location.href : '',
    })
  })
}
