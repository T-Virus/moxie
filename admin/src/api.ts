import { getAccessToken } from './session'
import { noteRequestId, reportApiError } from './errorReporter'
import {
  configurePayloadCrypto,
  decryptJson,
  decryptSse,
  encryptJson,
  getPayloadSession,
  payloadHeaders,
  resetPayloadCrypto,
  type PayloadSession,
} from './payloadCrypto'
import type {
  AdminPlanRow,
  PlanUpdatePayload,
  AccountDeletionListResponse, AccountDeletionRequestView, AdminDeadLettersResponse, AdminFeedEvent, AdminPerformance, AdminTaskReplayBatchResponse, AdminTaskReplayResult, AlertRow, AuditRow, BackupConfig, BackupConfigInput, BackupRestoreResult, BackupRow, FourLedgerReconcileReport, ListResult, LoginResponse, ModelUsageSummary, NotificationDetail, NotificationRow, OrderRow,
  NotificationBatchResult, PlanRow, PushReceiptHistory, ReconcileReport, RefundRow, RunEvent, SkillsCatalog,
  SubscriptionRow, TaskDashboard, TaskDetail, TaskRow, TelemetryCanary, TelemetryConfig,
  UserDetail, UserRow,
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
  'password', 'refresh_token', 'token', 'signature', 'api_key', 'secret',
  // 正文/提示词/通知正文等长文本保留原始空白；短文本与标识统一 trim。
  'content', 'body', 'prompt',
])

export function trimPayload(value: unknown, key = ''): unknown {
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
  /** 请求超时毫秒数；0 表示关闭（大文件上传用）。默认 60s。 */
  timeoutMs?: number
  /** 内部使用：密钥轮换后只重试一次 */
  cryptoRetried?: boolean
}

/** 默认请求超时，避免网络挂起时 fetch 永远 pending。 */
const DEFAULT_TIMEOUT_MS = 60_000

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
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS
  const signal = timeoutMs > 0 ? AbortSignal.timeout(timeoutMs) : undefined
  try {
    const response = await fetch(url, {
      method,
      headers,
      body,
      credentials: 'omit',
      signal,
    })
    noteRequestId(response.headers.get('x-request-id'))
    return { response, session, method, pathQuery }
  } catch (error) {
    if (error instanceof DOMException && error.name === 'TimeoutError') {
      const err = new ApiError(0, 'timeout', '请求超时，请稍后重试', path)
      reportApiError(err, pathQuery)
      throw err
    }
    const err = new ApiError(0, 'network_error', `无法连接服务端（${apiBaseLabel()}）`, path)
    reportApiError(err, pathQuery)
    throw err
  }
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
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
    reportApiError(error, raw.pathQuery, error.requestId)
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

export async function getAdminPerformance(): Promise<AdminPerformance> {
  return request<AdminPerformance>('/v1/admin/performance')
}

export async function downloadBlob(path: string, fallbackName: string): Promise<void> {
  const raw = await rawRequest(path)
  const response = raw.response
  if (response.status === 401 && refreshHandler && (await refreshHandler())) {
    return downloadBlob(path, fallbackName)
  }
  if (!response.ok) {
    const text = await readResponseText(raw)
    const error = await parseError(response, path, text)
    reportApiError(error, raw.pathQuery, error.requestId)
    throw error
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
    // source=admin：服务端硬隔离，普通用户账号即使密码正确也无法登录管理后台。
    const body = identity.includes('@')
      ? { email: identity.trim().toLowerCase(), password, source: 'admin' }
      : { phone: identity.trim(), password, source: 'admin' }
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
  forgotPassword(email: string) {
    return request<{ status: string; email: string; message: string; reset_url?: string }>(
      '/v1/auth/forgot-password',
      // 管理端发起：重置链接须指向 /admin 的 hash 路由，不串到用户端。
      { method: 'POST', body: { email, channel: 'admin' }, auth: false, skipRefresh: true },
    )
  },
  resetPassword(token: string, newPassword: string) {
    return request<{ ok: boolean; message: string; revoked_sessions?: number }>(
      '/v1/auth/reset-password',
      {
        method: 'POST',
        body: { token, new_password: newPassword },
        auth: false,
        skipRefresh: true,
      },
    )
  },
  changePassword(oldPassword: string, newPassword: string) {
    return request<{ ok: boolean; message: string; revoked_sessions?: number }>(
      '/v1/auth/change-password',
      { method: 'POST', body: { old_password: oldPassword, new_password: newPassword } },
    )
  },

  users(query: Record<string, unknown>) {
    return request<{ items: UserRow[]; total: number; page: number; page_size: number }>('/v1/admin/users', { query })
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
  resetUserPassword(id: number) {
    return request<{ ok: boolean; email: string; sent: boolean; message: string; reset_url?: string }>(
      `/v1/admin/users/${id}/reset-password`,
      { method: 'POST', body: {} },
    )
  },
  deleteUser(id: number) {
    return request<any>(`/v1/admin/users/${id}`, { method: 'DELETE' })
  },
  accountDeletions(status = '', page = 1, pageSize = 50) {
    return request<AccountDeletionListResponse>('/v1/admin/account-deletions', {
      query: { status: status || undefined, page, page_size: pageSize },
    })
  },
  cancelAccountDeletion(id: number) {
    return request<AccountDeletionRequestView>(`/v1/admin/account-deletions/${id}/cancel`, {
      method: 'POST',
    })
  },
  purgeAccountDeletion(id: number) {
    return request<{ deleted: boolean }>(`/v1/admin/account-deletions/${id}/purge`, {
      method: 'POST',
    })
  },
  skills() {
    return request<SkillsCatalog>('/v1/admin/skills')
  },
  telemetryConfig() {
    return request<TelemetryConfig>('/v1/admin/telemetry-config')
  },
  putTelemetryConfig(payload: {
    sample_rate: number; dedupe_window_seconds: number; dedupe_max_entries: number
    canary_percent?: number; canary?: TelemetryCanary
  }) {
    return request<TelemetryConfig>('/v1/admin/telemetry-config', { method: 'PUT', body: payload })
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
    // 安装包可达数百 MB，关闭默认超时
    return request<any>('/v1/admin/offline-packages', { method: 'POST', body: formData, timeoutMs: 0 })
  },
  deleteOfflinePackage(id: number) {
    return request<any>(`/v1/admin/offline-packages/${id}`, { method: 'DELETE' })
  },

  subscriptions(query: Record<string, unknown>) {
    return request<{ items: SubscriptionRow[]; total: number; page: number; page_size: number }>('/v1/admin/subscriptions', { query })
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
    return request<{ items: OrderRow[]; total: number; page: number; page_size: number }>('/v1/admin/orders', { query })
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
  /** 仅用于历史数据修正：直接改 DB 状态，不触发渠道开票/作废。 */
  updateInvoice(id: number, status: 'issued' | 'voided', note: string) {
    return request<any>(`/v1/admin/invoices/${id}`, { method: 'POST', body: { status, note } })
  },
  /** 走渠道端点申请开票（requested/failed → issuing → issued/failed）。 */
  issueInvoice(id: number, note: string) {
    return request<any>(`/v1/admin/invoices/${id}/issue`, {
      method: 'POST',
      body: { note: note || undefined },
    })
  },
  /** 走渠道端点作废发票，reason 写入审计日志。 */
  voidInvoice(id: number, reason: string) {
    return request<any>(`/v1/admin/invoices/${id}/void`, {
      method: 'POST',
      body: { reason },
    })
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
  fourLedgerReconcile(query: Record<string, unknown> = {}) {
    return request<FourLedgerReconcileReport>(
      '/v1/admin/payments/four-ledger-reconcile',
      { query },
    )
  },

  taskDashboard() {
    return request<TaskDashboard>('/v1/admin/tasks/dashboard')
  },
  deadLetters(query: Record<string, unknown> = {}) {
    return request<AdminDeadLettersResponse>('/v1/admin/tasks/dead-letters', { query })
  },
  replayDeadLetter(id: string, reason: string) {
    return request<AdminTaskReplayResult>(`/v1/admin/tasks/${id}/replay`, {
      method: 'POST',
      body: { reason },
    })
  },
  replayDeadLettersBatch(taskIds: string[], reason: string) {
    return request<AdminTaskReplayBatchResponse>('/v1/admin/tasks/dead-letters/replay-batch', {
      method: 'POST',
      body: { task_ids: taskIds, reason },
    })
  },
  /** 全部任务记录：status/source/account_id/q + 分页，覆盖排队/运行/暂停/完成/失败/取消。 */
  taskList(query: Record<string, unknown> = {}) {
    return request<{ items: TaskRow[]; total: number; page: number; page_size: number }>('/v1/admin/tasks', { query })
  },
  taskRetry(id: string) {
    return request<any>(`/v1/admin/tasks/${encodeURIComponent(id)}/retry`, { method: 'POST', body: {} })
  },
  /** 运营管控：cancel/pause/resume 为协作式，force_cancel 直接落终态并释放预占。 */
  taskControl(
    id: string,
    action: 'cancel' | 'pause' | 'resume' | 'force_cancel' | 'requeue',
    source?: string,
    reason?: string,
  ) {
    return request<any>(`/v1/admin/tasks/${encodeURIComponent(id)}/control`, {
      method: 'POST',
      body: { action, ...(source ? { source } : {}), ...(reason ? { reason } : {}) },
    })
  },
  taskDetail(id: string, source?: string, since = 0) {
    return request<TaskDetail>(`/v1/admin/tasks/${encodeURIComponent(id)}`, {
      query: { ...(source ? { source } : {}), ...(since > 0 ? { since } : {}) },
    })
  },

  alerts(query: Record<string, unknown>) {
    return request<{
      items: AlertRow[]; total: number; page: number; page_size: number
      window_hours: number; failed_notifications: number; webhook_failures: number
    }>('/v1/admin/alerts', { query })
  },
  notifications(query: Record<string, unknown>) {
    return request<{ items: NotificationRow[]; total: number; page: number; page_size: number }>('/v1/admin/notifications', { query })
  },
  notificationDetail(id: number) {
    return request<{ delivery: NotificationDetail }>(`/v1/admin/notifications/${id}`)
  },
  notificationReceipts(id: number) {
    return request<{ delivery: PushReceiptHistory }>(`/v1/admin/notifications/${id}/receipts`)
  },
  notificationReceiptsCsv(id: number) {
    return downloadBlob(`/v1/admin/notifications/${id}/receipts/export`, `receipts-${id}.csv`)
  },
  sendNotificationBatch(payload: { account_ids: number[]; title: string; body: string; channels?: string[] }) {
    return request<NotificationBatchResult>('/v1/admin/notifications/batch', { method: 'POST', body: payload })
  },
  retryNotification(id: number) {
    return request<any>(`/v1/admin/notifications/${id}/retry`, { method: 'POST', body: {} })
  },

  backupConfig() {
    return request<BackupConfig>('/v1/admin/backup-config')
  },
  updateBackupConfig(body: BackupConfigInput) {
    return request<BackupConfig>('/v1/admin/backup-config', { method: 'PUT', body })
  },
  backups() {
    return request<{ items: BackupRow[] }>('/v1/admin/backups')
  },
  createBackup() {
    return request<{ item: BackupRow }>('/v1/admin/backups', { method: 'POST', body: {} })
  },
  downloadBackup(id: string) {
    return downloadBlob(`/v1/admin/backups/${encodeURIComponent(id)}/download`, `${id}.zip`)
  },
  restoreBackup(id: string, apply = false, confirm = '') {
    return request<BackupRestoreResult>(`/v1/admin/backups/${encodeURIComponent(id)}/restore`, {
      method: 'POST',
      body: { apply, confirm },
    })
  },
  deleteBackup(id: string) {
    return request<{ id: string; deleted: boolean }>(`/v1/admin/backups/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    })
  },

  modelUsage(query: Record<string, unknown>) {
    return request<ModelUsageSummary>('/v1/admin/usage/models', { query })
  },

  auditLogs(query: Record<string, unknown>) {
    return request<{ items: AuditRow[]; total: number; page: number; page_size: number }>(
      '/v1/admin/audit-logs', { query },
    )
  },
  plans() {
    return request<{ plans: PlanRow[] }>('/v1/plans', { auth: false })
  },
  adminPlans() {
    return request<{ plans: AdminPlanRow[] }>('/v1/admin/plans')
  },
  updatePlan(code: string, body: PlanUpdatePayload) {
    return request<AdminPlanRow>(`/v1/admin/plans/${encodeURIComponent(code)}`, {
      method: 'PATCH',
      body,
    })
  },
  renewalReminders() {
    return request<any>('/v1/admin/renewal-reminders')
  },
}

interface AdminSseMessage {
  event: string
  data: string
}

/** 管理端 SSE 统一解析：带 Authorization 与载荷加密，错误响应走同一解密链路。 */
async function streamSse(
  path: string,
  onMessage: (message: AdminSseMessage) => void,
  signal: AbortSignal,
): Promise<void> {
  const url = apiUrl(path)
  const pathQuery = pathWithQuery(url)
  const session = await getPayloadSession()
  const resp = await fetch(url, {
    headers: {
      Accept: 'text/event-stream',
      ...authHeaders(),
      ...payloadHeaders(session),
    },
    signal,
  }).catch((error) => {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError(0, 'network_error', `无法连接服务端（${apiBaseLabel()}）`, path)
  })
  noteRequestId(resp.headers.get('x-request-id'))
  if (!resp.ok || !resp.body) {
    const text = await readResponseText({
      response: resp,
      session,
      method: 'GET',
      pathQuery,
    })
    throw await parseError(resp, path, text)
  }

  const encrypted = resp.headers.get('x-payload-sse') === '1'
  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const blocks = buffer.split(/\r?\n\r?\n/)
    buffer = blocks.pop() || ''
    for (const block of blocks) {
      const lines = block.split(/\r?\n/)
      const dataLines = lines
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trim())
        .join('')
      if (!dataLines) continue
      const eventLine = lines.find((line) => line.startsWith('event:'))
      try {
        const raw = encrypted ? await decryptSse(session, pathQuery, dataLines) : dataLines
        onMessage({ event: eventLine?.slice(6).trim() || 'message', data: raw })
      } catch {
        // 忽略控制/心跳帧解析失败，保持流不中断
      }
    }
  }
}

/** 订阅单条任务/写作运行的增量事件与状态变化。 */
export async function streamTaskEvents(
  taskId: string,
  source: string | undefined,
  since: number,
  onEvent: (event: RunEvent) => void,
  onStatus: (status: string) => void,
  signal: AbortSignal,
): Promise<void> {
  const query = new URLSearchParams({ since: String(since) })
  if (source) query.set('source', source)
  await streamSse(
    `/v1/admin/tasks/${encodeURIComponent(taskId)}/events?${query.toString()}`,
    (message) => {
      try {
        if (message.event === 'status') {
          const payload = JSON.parse(message.data) as { status?: string }
          if (typeof payload.status === 'string') onStatus(payload.status)
          return
        }
        if (message.event !== 'message') return
        const event = JSON.parse(message.data) as RunEvent
        if (typeof event.seq === 'number') onEvent(event)
      } catch {
        // 忽略非 JSON 控制帧
      }
    },
    signal,
  )
}

/** 运营看板聚合变更流：收到 refresh 后重查列表与概览。 */
export async function streamTasksFeed(
  onEvent: (event: AdminFeedEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  await streamSse(
    '/v1/admin/tasks/stream',
    (message) => {
      if (!['ready', 'refresh', 'closed'].includes(message.event)) return
      try {
        const event = JSON.parse(message.data) as AdminFeedEvent
        if (typeof event.active === 'number') onEvent(event)
      } catch {
        // 忽略非 JSON 控制帧
      }
    },
    signal,
  )
}

export type { SubscriptionRow, TaskRow }
