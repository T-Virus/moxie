import { API_BASE } from './config'
import {
  configurePayloadCrypto,
  decryptJson,
  encryptJson,
  getPayloadSession,
  payloadHeaders,
  resetPayloadCrypto,
  type PayloadSession,
} from './payloadCrypto'
import type { AuthResponse } from '@/types'

configurePayloadCrypto(`${API_BASE}/crypto/public-key`)

const ACCESS_KEY = 'mx_access_token'
const REFRESH_KEY = 'mx_refresh_token'
const ACCOUNT_KEY = 'mx_account'

export class ApiError extends Error {
  status: number
  code: string
  requestId: string

  constructor(status: number, code: string, message: string, requestId = '') {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.requestId = requestId
  }
}

const FRIENDLY_BY_STATUS: Record<number, string> = {
  400: '提交内容不合法，请检查后重试',
  401: '登录状态已失效，请重新登录',
  403: '当前账号没有该操作权限',
  404: '接口不存在或资源已失效',
  409: '资源状态冲突，请刷新后重试',
  413: '文件超过大小限制',
  415: '文件格式不支持',
  422: '提交内容校验未通过',
  429: '操作过于频繁，请稍后再试',
}

export function friendlyMessage(status: number): string {
  if (status >= 500) return '服务端开小差了，请稍后重试'
  return FRIENDLY_BY_STATUS[status] || '请求失败，请稍后重试'
}

export function isNetworkError(err: unknown): boolean {
  return err instanceof TypeError
}

export function getAccessToken(): string {
  return localStorage.getItem(ACCESS_KEY) || ''
}

export function getRefreshToken(): string {
  return localStorage.getItem(REFRESH_KEY) || ''
}

export function hasSession(): boolean {
  return !!getAccessToken()
}

export function saveSession(auth: AuthResponse): void {
  localStorage.setItem(ACCESS_KEY, auth.access_token)
  localStorage.setItem(REFRESH_KEY, auth.refresh_token)
  localStorage.setItem(ACCOUNT_KEY, JSON.stringify(auth.account))
}

export function clearSession(): void {
  localStorage.removeItem(ACCESS_KEY)
  localStorage.removeItem(REFRESH_KEY)
  localStorage.removeItem(ACCOUNT_KEY)
}

export function readAccount() {
  const raw = localStorage.getItem(ACCOUNT_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as AuthResponse['account']
  } catch {
    return null
  }
}

/** 并发 401 时只触发一次刷新，其余请求等待同一个 Promise。 */
let refreshPromise: Promise<boolean> | null = null

async function refreshToken(): Promise<boolean> {
  const token = getRefreshToken()
  if (!token) return false
  try {
    const data = await apiFetch<AuthResponse>('/auth/refresh', {
      method: 'POST',
      body: JSON.stringify({ refresh_token: token }),
      anonymous: true,
      noRetry: true,
    })
    saveSession(data)
    return true
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) clearSession()
    return false
  }
}

export function ensureRefresh(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = refreshToken().finally(() => {
      refreshPromise = null
    })
  }
  return refreshPromise
}

interface ErrorBody {
  error?: { code?: string; message?: string; request_id?: string }
  detail?: unknown
}

export function extractError(status: number, body: unknown): ApiError {
  const data = (body || {}) as ErrorBody
  const code = data.error?.code || `http_${status}`
  const message = data.error?.message || friendlyMessage(status)
  const requestId = data.error?.request_id || ''
  return new ApiError(status, code, message, requestId)
}

export async function parseBody(resp: Response): Promise<unknown> {
  return parseJsonText(await resp.text())
}

function parseJsonText(text: string): unknown {
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return { error: { code: 'invalid_response', message: '服务端返回了非 JSON 内容' } }
  }
}

function pathWithQuery(url: string): string {
  try {
    const parsed = new URL(url, window.location.origin)
    return parsed.pathname + parsed.search
  } catch {
    return url
  }
}

/** 与服务端 keep in sync：文件、回调、公开密钥等接口不做应用层加密 */
function payloadEncryptionApplies(url: string, body?: BodyInit | null): boolean {
  if (typeof FormData !== 'undefined' && body instanceof FormData) return false
  const path = pathWithQuery(url)
  if (!path.startsWith('/v1')) return false
  if (path === '/v1/crypto/public-key' || path === '/v1/uploads') return false
  if (path.startsWith('/v1/downloads')) return false
  if (path.startsWith('/v1/license')) return false
  if (path.startsWith('/v1/webhooks')) return false
  if (path.startsWith('/v1/gateway')) return false
  if (path.startsWith('/v1/payments/invoices/callback')) return false
  if (path.startsWith('/v1/payments/stripe')) return false
  if (path.startsWith('/v1/admin/payments/reconcile/export')) return false
  if (/^\/v1\/agent-runs\/[^/]+\/cover(?:\/upload)?$/.test(path)) return false
  if (/^\/v1\/agent-runs\/[^/]+\/artifacts\//.test(path)) return false
  return true
}

async function readPayloadText(
  resp: Response,
  session: PayloadSession | null,
  method: string,
  pathQuery: string,
): Promise<string> {
  if (resp.headers.get('x-payload-encrypted') !== '1') return resp.text()
  if (!session) throw new ApiError(500, 'payload_session_missing', '缺少加密会话')
  const nonce = resp.headers.get('x-payload-nonce') || ''
  try {
    return await decryptJson(session, method, pathQuery, nonce, await resp.arrayBuffer())
  } catch {
    throw new ApiError(resp.status, 'payload_decrypt_failed', '服务端响应解密失败')
  }
}

export interface RequestOptions {
  method?: string
  body?: BodyInit | null
  headers?: Record<string, string>
  signal?: AbortSignal
  /** 跳过 Authorization（登录/注册） */
  anonymous?: boolean
  /** 只发一次，不做 401 刷新重试（刷新接口自身） */
  noRetry?: boolean
}

export async function apiFetch<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`
  const method = (opts.method || 'GET').toUpperCase()
  const headers = new Headers(opts.headers)
  const token = getAccessToken()
  if (!opts.anonymous && token) headers.set('Authorization', `Bearer ${token}`)
  if (opts.body && !(opts.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  let body: BodyInit | null | undefined = opts.body
  let session: PayloadSession | null = null
  const pathQuery = pathWithQuery(url)
  if (payloadEncryptionApplies(url, body)) {
    session = await getPayloadSession()
    Object.entries(payloadHeaders(session)).forEach(([name, value]) => headers.set(name, value))
    if (typeof body === 'string') {
      const encrypted = await encryptJson(session, method, pathQuery, body)
      body = encrypted.body
      headers.set('Content-Type', 'application/octet-stream')
      headers.set('X-Payload-Nonce', encrypted.nonce)
      headers.set('X-Payload-Encrypted', '1')
    }
  }

  let resp: Response
  try {
    resp = await fetch(url, {
      method,
      body,
      headers,
      signal: opts.signal,
    })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw new ApiError(0, 'network_error', '无法连接服务端，请检查网络与后端地址')
  }

  if (resp.status === 401 && !opts.anonymous && !opts.noRetry) {
    const refreshed = await ensureRefresh()
    if (refreshed) return apiFetch<T>(path, { ...opts, noRetry: true })
  }

  let text: string
  try {
    text = await readPayloadText(resp, session, method, pathQuery)
  } catch (err) {
    if (err instanceof ApiError && err.status !== 401) throw err
    throw err
  }
  const parsed = parseJsonText(text)
  if (!resp.ok) {
    const error = extractError(resp.status, parsed)
    // 服务端重启/换密钥后客户端会话失效：清空并重试一次
    if (error.code === 'payload_key_mismatch' && !opts.noRetry) {
      resetPayloadCrypto()
      return apiFetch<T>(path, { ...opts, noRetry: true })
    }
    throw error
  }
  return parsed as T
}

/**
 * 下载产物：必须带 Authorization，不能用裸链接。
 * 服务端对 markdown 产物返回 `{name,size,url}` 预签名元数据（json 产物直接返回内容），
 * 这里识别元数据后二次拉取签名链接，避免把元数据 JSON 当成 md 文件保存。
 */
export async function apiDownload(path: string, fallbackName: string): Promise<File> {
  const resp = await fetch(`${API_BASE}${path}`, {
    headers: getAccessToken() ? { Authorization: `Bearer ${getAccessToken()}` } : {},
  }).catch(() => {
    throw new ApiError(0, 'network_error', '无法连接服务端，请检查网络与后端地址')
  })
  if (!resp.ok) throw extractError(resp.status, await parseBody(resp))

  const contentType = resp.headers.get('content-type') || ''
  if (contentType.includes('application/json')) {
    const text = await resp.text()
    let parsed: unknown = null
    try {
      parsed = JSON.parse(text)
    } catch {
      // 非 JSON 内容按纯文本保存
    }
    const meta = parsed as { url?: unknown; name?: unknown } | null
    if (meta && typeof meta.url === 'string' && meta.url) {
      const signedUrl = meta.url.startsWith('http')
        ? meta.url
        : `${window.location.origin}${meta.url.startsWith('/') ? '' : '/'}${meta.url}`
      const download = await fetch(signedUrl).catch(() => {
        throw new ApiError(0, 'network_error', '产物下载链接不可访问，请检查存储配置')
      })
      if (!download.ok) throw extractError(download.status, await parseBody(download))
      const blob = await download.blob()
      const name = typeof meta.name === 'string' && meta.name ? meta.name : fallbackName
      return new File([blob], name, { type: blob.type || 'application/octet-stream' })
    }
    return new File([text], fallbackName, { type: contentType })
  }

  const blob = await resp.blob()
  return new File([blob], fallbackName, { type: blob.type || 'application/octet-stream' })
}
