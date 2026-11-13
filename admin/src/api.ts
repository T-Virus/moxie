import { clearSession, getAccessToken } from './session'
import {
  configurePayloadCrypto,
  decryptJson,
  encryptJson,
  getPayloadSession,
  payloadHeaders,
  resetPayloadCrypto,
  type PayloadSession,
} from './payloadCrypto'
import type {
  AlertRow, AuditRow, InvoiceRow, ListResult, LoginResponse, NotificationRow, OrderRow,
  PlanRow, ReconcileReport, RefundRow, SubscriptionRow, TaskDashboard, TaskRow, UserDetail,
  UserRow,
} from './types'

export const API_BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/+$/, '')

export function apiUrl(path: string): string {
  return API_BASE ? `${API_BASE}${path}` : path
}

configurePayloadCrypto(apiUrl('/v1/crypto/public-key'))

export function apiBaseLabel(): string {
  return API_BASE || '同源（开发代理 /v1 → 127.0.0.1:8000）'
}

export class ApiError extends Error {
  status: number
  code: string
  path: string
  requestId?: string
  endpointMissing: boolean

  constructor(
    status: number,
    code: string,
    message: string,
    path: string,
    requestId?: string,
    endpointMissing = false,
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.path = path
    this.requestId = requestId
    this.endpointMissing = endpointMissing
  }
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return String(error || '未知错误')
}

export function isMissingEndpoint(error: unknown): boolean {
  return error instanceof ApiError && error.endpointMissing
}

/** 提交前统一去掉字符串首尾空白；口令/令牌/密钥/正文等敏感字段保留原样。 */
const NO_TRIM_KEYS = new Set([
  'password', 'refresh_token', 'token', 'signature', 'api_key', 'secret', 'content',
])

function trimPayload(value: unknown, key = ''): unknown {
  if (typeof value === 'string') return NO_TRIM_KEYS.has(key) ? value : value.trim()
  if (Array.isArray(value)) return value.map((item) => trimPayload(item, key))
  if (value && typeof value === 'object') {
    const result: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      result[k] = trimPayload(v, k)
    }
    return result
  }
  return value
}

function trimFormData(form: FormData): FormData {
  const result = new FormData()
  for (const [key, value] of form.entries()) {
    result.append(key, typeof value === 'string' && !NO_TRIM_KEYS.has(key) ? value.trim() : value)
  }
  return result
}

function buildQuery(query?: Record<string, unknown>): string {
  if (!query) return ''
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue
    params.set(key, String(value))
  }
  const text = params.toString()
  return text ? `?${text}` : ''
}

let refreshHandler: (() => Promise<boolean>) | null = null
let unauthorizedHandler: (() => void) | null = null

export function setRefreshHandler(handler: (() => Promise<boolean>) | null): void {
  refreshHandler = handler
}

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler
}

interface RequestOptions {
  method?: string
  body?: unknown
  auth?: boolean
  skipRefresh?: boolean
  headers?: Record<string, string>
  query?: Record<string, unknown>
  /** 内部使用：密钥轮换后只重试一次 */
  cryptoRetried?: boolean
}

interface RawResponse {
  response: Response
  session: PayloadSession | null
  method: string
  pathQuery: string
}

function pathWithQuery(url: string): string {
  try {
    const parsed = new URL(url, window.location.origin)
    return parsed.pathname + parsed.search
  } catch {
    return url
  }
}

function encryptionApplies(url: string, body?: BodyInit): boolean {
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
  return true
}

async function readResponseText(raw: RawResponse): Promise<string> {
  const encrypted = raw.response.headers.get('x-payload-encrypted') === '1'
  if (!encrypted) return raw.response.text()
  if (!raw.session) throw new ApiError(500, 'payload_session_missing', '缺少加密会话', raw.pathQuery)
  const nonce = raw.response.headers.get('x-payload-nonce') || ''
  try {
    return await decryptJson(
      raw.session,
      raw.method,
      raw.pathQuery,
      nonce,
      await raw.response.arrayBuffer(),
    )
  } catch {
    throw new ApiError(raw.response.status, 'payload_decrypt_failed', '服务端响应解密失败', raw.pathQuery)
  }
}

function authHeaders(): Record<string, string> {
  const token = getAccessToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function parseError(response: Response, path: string, rawText: string): Promise<ApiError> {
  let payload: any = null
  if (rawText) {
    try {
      payload = JSON.parse(rawText)
    } catch {
      payload = null
    }
  }
  const err = payload?.error
  const message = err?.message || payload?.detail || payload?.message || response.statusText || '请求失败'
  const code = err?.code || (response.status === 404 ? 'not_found' : 'http_error')
  const missingByRoute =
    response.status === 405 ||
    (response.status === 404 &&
      (message === 'Not Found' ||
        payload?.detail === 'Not Found' ||
        (!payload && !rawText.trim())))
  return new ApiError(
    response.status,
    code,
    message,
    path,
    err?.request_id,
    missingByRoute,
  )
}

async function rawRequest(path: string, options: RequestOptions = {}): Promise<RawResponse> {
  const method = (options.method || 'GET').toUpperCase()
  const url = apiUrl(path) + buildQuery(options.query)
  const pathQuery = pathWithQuery(url)
  const headers: Record<string, string> = { Accept: 'application/json', ...(options.headers || {}) }
  if (options.auth !== false) Object.assign(headers, authHeaders())
  let body: BodyInit | undefined
  if (options.body !== undefined && method !== 'GET') {
    if (options.body instanceof FormData) {
      body = trimFormData(options.body)
    } else {
      headers['Content-Type'] = 'application/json'
      body = JSON.stringify(trimPayload(options.body))
    }
  }

  let session: PayloadSession | null = null
  if (encryptionApplies(url, body)) {
    session = await getPayloadSession()
    Object.assign(headers, payloadHeaders(session))
    if (typeof body === 'string') {
      const encrypted = await encryptJson(session, method, pathQuery, body)
      body = encrypted.body
      headers['Content-Type'] = 'application/octet-stream'
      headers['X-Payload-Nonce'] = encrypted.nonce
      headers['X-Payload-Encrypted'] = '1'
    }
  }
  try {
    const response = await fetch(url, {
      method,
      headers,
      body,
      credentials: 'omit',
    })
    return { response, session, method, pathQuery }
  } catch (error) {
    throw new ApiError(0, 'network_error', `无法连接服务端（${apiBaseLabel()}）`, path)
  }
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const raw = await rawRequest(path, options)
  const rawText = await readResponseText(raw)
  const response = raw.response
  if (response.status === 401 && options.auth !== false && !options.skipRefresh && refreshHandler) {
    const refreshed = await refreshHandler()
    if (refreshed) {
      return request<T>(path, { ...options, skipRefresh: true })
    }
    unauthorizedHandler?.()
  }
  if (!response.ok) {
    const error = await parseError(response, path, rawText)
    if (error.code === 'payload_key_mismatch' && !options.cryptoRetried) {
      resetPayloadCrypto()
      return request<T>(path, { ...options, cryptoRetried: true })
    }
    throw error
  }
  if (!rawText) return {} as T
  try {
    return JSON.parse(rawText) as T
  } catch {
    throw new ApiError(response.status, 'invalid_response', '服务端返回了非 JSON 内容', path)
  }
}

export function normalizeList<T>(payload: any, keys: string[] = []): ListResult<T> {
  const root = payload && typeof payload === 'object' && !Array.isArray(payload) ? payload : {}
  const container = root.data && typeof root.data === 'object' ? root.data : root
  let items: T[] = []
  if (Array.isArray(payload)) {
    items = payload as T[]
  } else if (Array.isArray(container.items)) {
    items = container.items as T[]
  } else {
    for (const key of keys) {
      if (Array.isArray(container[key])) {
        items = container[key] as T[]
        break
      }
    }
    if (!items.length) {
      for (const value of Object.values(container)) {
        if (Array.isArray(value)) {
          items = value as T[]
          break
        }
      }
    }
  }
  const numberOrNull = (value: unknown): number | null =>
    typeof value === 'number' && Number.isFinite(value) ? value : null
  return {
    items,
    total: numberOrNull(container.total ?? container.count),
    page: numberOrNull(container.page),
    pageSize: numberOrNull(container.page_size ?? container.pageSize),
  }
}

export interface ProbeOutcome {
  state: 'ready' | 'missing' | 'forbidden' | 'error'
  httpStatus?: number
  code?: string
  message?: string
}

export async function probeEndpoint(
  path: string,
  options: RequestOptions = {},
): Promise<ProbeOutcome> {
  try {
    const raw = await rawRequest(path, { ...options, method: options.method || 'GET' })
    const response = raw.response
    const text = await readResponseText(raw)
    if (response.ok) return { state: 'ready', httpStatus: response.status }
    if (response.status === 422 || response.status === 409) {
      return { state: 'ready', httpStatus: response.status, message: '路由已注册（参数校验生效）' }
    }
    const error = await parseError(response, path, text)
    if (error.endpointMissing) {
      return { state: 'missing', httpStatus: response.status, code: error.code, message: error.message }
    }
    if (response.status === 404) {
      return { state: 'ready', httpStatus: response.status, code: error.code, message: '路由已注册（资源不存在）' }
    }
    if (response.status === 401 || response.status === 403) {
      return { state: 'forbidden', httpStatus: response.status, code: error.code, message: error.message }
    }
    return { state: 'error', httpStatus: response.status, code: error.code, message: error.message }
  } catch (error) {
    if (error instanceof ApiError) {
      return { state: error.status === 401 || error.status === 403 ? 'forbidden' : 'error', httpStatus: error.status, code: error.code, message: error.message }
    }
    return { state: 'error', message: String(error) }
  }
}

export async function getHealth(): Promise<{ ok: boolean; body: any }> {
  try {
    const response = await fetch(apiUrl('/healthz'), { credentials: 'omit' })
    return { ok: response.ok, body: await response.json().catch(() => ({})) }
  } catch {
    return { ok: false, body: {} }
  }
}

export async function getReady(): Promise<{ httpStatus: number; body: any }> {
  try {
    const response = await fetch(apiUrl('/readyz'), { credentials: 'omit' })
    return { httpStatus: response.status, body: await response.json().catch(() => ({})) }
  } catch {
    return { httpStatus: 0, body: {} }
  }
}

export async function downloadBlob(path: string, fallbackName: string): Promise<void> {
  const raw = await rawRequest(path)
  const response = raw.response
  if (response.status === 401 && refreshHandler && (await refreshHandler())) {
    return downloadBlob(path, fallbackName)
  }
  if (!response.ok) {
    const text = await readResponseText(raw)
    throw await parseError(response, path, text)
  }
  const disposition = response.headers.get('content-disposition') || ''
  const match = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/i.exec(disposition)
  const name = match?.[1]?.replace(/['"]/g, '') || fallbackName
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = name
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export const api = {
  login(identity: string, password: string) {
    const body = identity.includes('@')
      ? { email: identity.trim().toLowerCase(), password }
      : { phone: identity.trim(), password }
    return request<LoginResponse>('/v1/auth/login', {
      method: 'POST', body, auth: false, skipRefresh: true,
    })
  },
  refresh(refreshToken: string) {
    return request<LoginResponse>('/v1/auth/refresh', {
      method: 'POST', body: { refresh_token: refreshToken }, auth: false, skipRefresh: true,
    })
  },
  logout() {
    return request<{ ok: boolean }>('/v1/auth/logout', { method: 'POST', body: {}, skipRefresh: true })
  },

  users(query: Record<string, unknown>) {
    return request<any>('/v1/admin/users', { query })
  },
  userDetail(id: number) {
    return request<UserDetail>(`/v1/admin/users/${id}`)
  },
  banUser(id: number, reason: string) {
    return request<any>(`/v1/admin/users/${id}/ban`, { method: 'POST', body: { reason } })
  },
  unbanUser(id: number, reason: string) {
    return request<any>(`/v1/admin/users/${id}/unban`, { method: 'POST', body: { reason } })
  },
  deleteUser(id: number) {
    return request<any>(`/v1/admin/users/${id}`, { method: 'DELETE' })
  },
  presets(query: Record<string, unknown>) {
    return request<any>('/v1/admin/presets', { query })
  },
  createPreset(payload: Record<string, unknown>) {
    return request<any>('/v1/admin/presets', { method: 'POST', body: payload })
  },
  updatePreset(id: number, payload: Record<string, unknown>) {
    return request<any>(`/v1/admin/presets/${id}`, { method: 'PUT', body: payload })
  },
  deletePreset(id: number) {
    return request<any>(`/v1/admin/presets/${id}`, { method: 'DELETE' })
  },
  syncPresetSeeds() {
    return request<any>('/v1/admin/presets/sync-seeds', { method: 'POST', body: {} })
  },
  modelConfigs() {
    return request<any>('/v1/admin/model-configs')
  },
  putModelConfig(stepKey: string, payload: Record<string, unknown>) {
    return request<any>(`/v1/admin/model-configs/${stepKey}`, { method: 'PUT', body: payload })
  },
  deleteModelConfig(stepKey: string) {
    return request<any>(`/v1/admin/model-configs/${stepKey}`, { method: 'DELETE' })
  },
  testModelConfig(stepKey: string, payload: Record<string, unknown>) {
    return request<any>(`/v1/admin/model-configs/${stepKey}/test`, { method: 'POST', body: payload })
  },
  offlinePackages() {
    return request<any>('/v1/admin/offline-packages')
  },
  offlinePackageLimits() {
    return request<{ max_bytes: number; suffix: Record<string, string> }>(
      '/v1/admin/offline-packages/limits',
    )
  },
  uploadOfflinePackage(formData: FormData) {
    return request<any>('/v1/admin/offline-packages', { method: 'POST', body: formData })
  },
  deleteOfflinePackage(id: number) {
    return request<any>(`/v1/admin/offline-packages/${id}`, { method: 'DELETE' })
  },

  subscriptions(query: Record<string, unknown>) {
    return request<any>('/v1/admin/subscriptions', { query })
  },
  adjustSubscription(id: number, body: Record<string, unknown>) {
    return request<any>(`/v1/admin/subscriptions/${id}`, { method: 'PATCH', body })
  },
  quotaAdjust(accountId: number, body: Record<string, unknown>) {
    return request<any>(`/v1/admin/accounts/${accountId}/quota-adjustments`, { method: 'POST', body })
  },
  quotaAdjustments(accountId: number) {
    return request<any>(`/v1/admin/accounts/${accountId}/quota-adjustments`)
  },

  orders(query: Record<string, unknown>) {
    return request<any>('/v1/admin/orders', { query })
  },
  orderDetail(id: number) {
    return request<{ order: OrderRow; refunds?: RefundRow[] }>(`/v1/admin/orders/${id}`)
  },
  refunds(query: Record<string, unknown> = {}) {
    return request<any>('/v1/admin/refunds', { query })
  },
  approveRefund(id: number, note: string) {
    return request<any>(`/v1/admin/refunds/${id}/approve`, { method: 'POST', body: { note } })
  },
  rejectRefund(id: number, note: string) {
    return request<any>(`/v1/admin/refunds/${id}/reject`, { method: 'POST', body: { note } })
  },
  directRefund(orderId: number, body: { amount_cents?: number; reason: string }) {
    return request<any>(`/v1/admin/orders/${orderId}/refund`, { method: 'POST', body })
  },

  invoices(query: Record<string, unknown>) {
    return request<any>('/v1/admin/invoices', { query })
  },
  updateInvoice(id: number, status: 'issued' | 'voided', note: string) {
    return request<any>(`/v1/admin/invoices/${id}`, { method: 'POST', body: { status, note } })
  },

  reconcile(provider: string, bizDate: string) {
    return request<ReconcileReport>('/v1/admin/payments/reconcile', {
      query: { provider, biz_date: bizDate },
    })
  },
  runReconcile(provider: string, bizDate: string) {
    return request<ReconcileReport>('/v1/admin/payments/reconcile', {
      method: 'POST', body: { provider, biz_date: bizDate },
    })
  },
  exportReconcile(provider: string, bizDate: string) {
    return downloadBlob(
      `/v1/admin/payments/reconcile/export${buildQuery({ provider, biz_date: bizDate })}`,
      `reconcile-${provider}-${bizDate}.csv`,
    )
  },

  taskDashboard() {
    return request<TaskDashboard>('/v1/admin/tasks/dashboard')
  },
  taskRetry(id: string) {
    return request<any>(`/v1/admin/tasks/${encodeURIComponent(id)}/retry`, { method: 'POST', body: {} })
  },

  alerts(query: Record<string, unknown>) {
    return request<any>('/v1/admin/alerts', { query })
  },
  notifications(query: Record<string, unknown>) {
    return request<any>('/v1/admin/notifications', { query })
  },
  retryNotification(id: number) {
    return request<any>(`/v1/admin/notifications/${id}/retry`, { method: 'POST', body: {} })
  },

  auditLogs(query: Record<string, unknown>) {
    return request<any>('/v1/admin/audit-logs', { query })
  },
  plans() {
    return request<{ plans: PlanRow[] }>('/v1/plans', { auth: false })
  },
  renewalReminders() {
    return request<any>('/v1/admin/renewal-reminders')
  },
}

export type { SubscriptionRow, TaskRow }
