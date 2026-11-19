export type Role = 'admin' | 'support'

export interface AdminAccount {
  id: number
  email?: string | null
  phone?: string | null
  status: string
  role: Role | string
  created_at?: string | null
}

export interface AdminSession {
  access_token: string
  refresh_token: string
  expires_at: number
  account: AdminAccount
}

export interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  refresh_expires_in: number
  account: AdminAccount
}

export interface ListResult<T> {
  items: T[]
  total: number | null
  page: number | null
  pageSize: number | null
}

export interface UserRow {
  id: number
  email?: string | null
  phone?: string | null
  status: string
  role: string
  created_at?: string | null
  subscription?: SubscriptionRow | null
  devices_count?: number | null
  tasks_count?: number | null
  usage?: UsageMetric[] | null
  last_seen_at?: string | null
}

export interface UserDetail {
  account?: AdminAccount & { updated_at?: string | null }
  user?: AdminAccount
  devices?: DeviceRow[]
  subscription?: SubscriptionRow | null
  recent_tasks?: TaskRow[]
  tasks?: TaskRow[]
  usage?: UsageMetric[]
  entitlements?: UsageMetric[]
  [key: string]: unknown
}

export interface DeviceRow {
  id: number
  platform: string
  name?: string | null
  status: string
  last_seen_at?: string | null
  created_at?: string | null
}

export interface UsageMetric {
  metric: string
  unit?: string
  limit?: number
  used?: number
  reserved?: number
  remaining?: number
  quantity?: number
}

export interface SubscriptionRow {
  id: number
  account_id?: number | null
  account?: { id?: number; email?: string | null; phone?: string | null } | null
  status: string
  plan?: { code?: string; name?: string } | string | null
  plan_code?: string | null
  plan_name?: string | null
  seats?: number
  cancel_at_period_end?: boolean
  current_start_at?: string | null
  current_end_at?: string | null
  days_left?: number | null
  provider?: string | null
  version?: number
  note?: string | null
  [key: string]: unknown
}

export interface OrderRow {
  id: number
  account_id?: number | null
  account?: { id?: number; email?: string | null; phone?: string | null } | null
  subscription_id?: number | null
  amount_cents: number
  currency?: string
  status: string
  provider: string
  provider_txn_id?: string | null
  external_order_no?: string | null
  kind?: string
  cycle?: string
  refunded_cents?: number
  failure_reason?: string | null
  paid_at?: string | null
  created_at?: string | null
  meta?: Record<string, unknown> | null
  [key: string]: unknown
}

export interface RefundRow {
  id: number
  order_id: number
  account_id?: number | null
  amount_cents: number
  currency?: string
  status: string
  provider: string
  provider_refund_id?: string | null
  reason?: string | null
  note?: string | null
  requested_at?: string | null
  succeeded_at?: string | null
  [key: string]: unknown
}

export interface InvoiceRow {
  id: number
  order_id: number
  account_id?: number | null
  title: string
  tax_no?: string | null
  email?: string | null
  amount_cents: number
  status: string
  note?: string | null
  admin_id?: number | null
  created_at?: string | null
  issued_at?: string | null
  [key: string]: unknown
}

export interface ReconcileItem {
  type?: string
  external_order_no?: string | null
  order_id?: number | null
  amount_cents?: number | null
  local_amount_cents?: number | null
  channel_amount_cents?: number | null
  count?: number | null
  [key: string]: unknown
}

export interface ReconcileReport {
  id?: number
  provider: string
  biz_date: string
  status?: string
  summary?: Record<string, unknown>
  items?: ReconcileItem[]
  channel_source?: string | null
}

export interface TaskRow {
  id: string
  account_id?: number | null
  type?: string
  /** 任务来源：task=拆解/改编任务，agent_run=用户在创作页触发的写作运行 */
  source?: 'task' | 'agent_run'
  title?: string | null
  status: string
  progress?: number
  book?: string | null
  book_id?: number | null
  error_code?: string | null
  error_message?: string | null
  attempts?: number
  /** 失败重试的退避到点时间（ISO 字符串），无待重试时为 null */
  next_retry_at?: string | null
  /** 写作运行的模式（hot/reference/custom），拆解任务为空 */
  mode?: string | null
  created_at?: string | null
  started_at?: string | null
  finished_at?: string | null
  /** 最近一次心跳/阶段更新时间，用于判断是否卡死 */
  last_activity_at?: string | null
  stalled?: boolean
  cost_actual_cents?: number | null
  [key: string]: unknown
}

export interface AccountDeletionRequestView {
  id: number
  account_id: number
  status: string
  reason: string | null
  requested_at: string | null
  purge_at: string | null
  cancelled_at: string | null
}

export interface AccountDeletionListResponse {
  items: AccountDeletionRequestView[]
  total: number
}

export interface FourLedgerAnomaly {
  order_id: number
  order_no: string
  account_id: number
  code: string
  severity: string
  detail: string
}

export interface FourLedgerGroup {
  order_id: number
  order_no: string
  external_order_no: string | null
  account_id: number
  kind: string
  provider: string
  amount_cents: number
  created_at: string | null
  paid_at: string | null
  payment: Record<string, unknown>
  quota: Record<string, unknown>
  invoice: Record<string, unknown>
  refund: Record<string, unknown>
  anomalies: string[]
}

export interface FourLedgerReconcileReport {
  total: number
  window: { start_at: string | null; end_at: string | null }
  summary: { orders: number; anomaly_total: number; by_code: Record<string, number> }
  groups: FourLedgerGroup[]
  anomalies: FourLedgerAnomaly[]
}

export interface TaskDashboard {
  queue_depth?: number
  running_count?: number
  failed_count?: number
  retryable_count?: number
  generated_at?: string
  running?: TaskRow[]
  failed?: TaskRow[]
  queued?: TaskRow[]
  running_tasks?: TaskRow[]
  failed_tasks?: TaskRow[]
  [key: string]: unknown
}

export interface AdminPerformanceRoute {
  path: string
  count: number
  p95_ms: number | null
  p99_ms: number | null
  error_rate: number
}

export interface AdminDeadLettersResponse {
  items: TaskRow[]
  total: number
}

export interface AdminTaskReplayResult {
  task_id: string
  ok: boolean
  source?: string | null
  code?: string | null
}

export interface AdminTaskReplayBatchResponse {
  items: AdminTaskReplayResult[]
  succeeded: number
  failed: number
}

export interface AdminPerformance {
  generated_at: string
  requests: number
  p95_ms: number | null
  p99_ms: number | null
  error_rate: number
  routes: AdminPerformanceRoute[]
}

export interface RunEvent {
  seq: number
  stage: string
  level: string
  message: string
  at?: string | null
}

/** 运营看板聚合变更流：只发 refresh 信号，前端收到后重查列表/概览。 */
export interface AdminFeedEvent {
  type: 'ready' | 'refresh' | 'closed'
  active: number
  at?: number
}

export interface BackupEmailStatus {
  enabled: boolean
  status: string
  reason?: string | null
  recipients?: string[]
  error?: string | null
}

export interface BackupRow {
  id: string
  created_at?: string | null
  trigger: string
  engine: string
  size_bytes: number
  checksum: string
  email: BackupEmailStatus
}

export interface BackupConfig {
  schedule_enabled: boolean
  interval_minutes: number
  email_enabled: boolean
  notify_emails: string
  retention_count: number
  source: string
  updated_at?: string | null
  updated_by?: number | null
}

export type BackupConfigInput = Pick<
  BackupConfig,
  'schedule_enabled' | 'interval_minutes' | 'email_enabled' | 'notify_emails' | 'retention_count'
>

export interface BackupRestoreResult {
  id: string
  mode: 'staged' | 'applied'
  engine: string
  path?: string | null
}

export interface ModelUsageRow {
  key: string
  label: string
  provider: string
  tokens: number
  cost_cents: number
  calls: number
  account_count: number
  model_count: number
}

export interface ModelUsageSummary {
  generated_at: string
  days: number
  group_by: 'model' | 'provider' | 'account' | 'day'
  total_tokens: number
  total_cost_cents: number
  total_calls: number
  scanned_rows: number
  truncated: boolean
  items: ModelUsageRow[]
}

export interface TaskDetail {
  source: 'task' | 'agent_run'
  detail: Record<string, unknown>
  events: RunEvent[]
  /** 本次返回的最后一条事件 seq，日志轮询时作为下次的 since */
  last_seq?: number
  /** 单次返回达到上限，说明还有更早/更多的日志未展示 */
  truncated?: boolean
  [key: string]: unknown
}

export interface TaskStage {
  id: string
  name?: string
  state: string
  started_at?: string | null
  finished_at?: string | null
  [key: string]: unknown
}

export interface AlertRow {
  id?: number
  account_id?: number | null
  level?: string
  status?: string
  message?: string
  metric?: string | null
  quantity?: number | null
  threshold?: number | null
  created_at?: string | null
  acknowledged_at?: string | null
  [key: string]: unknown
}

export interface DeliveryMetaSummary {
  subscribers?: number | null
  delivered?: number | null
  expired_count?: number | null
  receipt_count?: number | null
  retry_after_seconds?: number | null
  reason?: string | null
}

export interface PushReceipt {
  sub_id: number
  status: string
  error?: string
  http_status?: number
  retry_after_seconds?: number
}

export interface NotificationRow {
  id: number
  account_id?: number | null
  channel?: string | null
  recipient?: string | null
  subject?: string | null
  template?: string | null
  status: string
  attempts?: number
  max_attempts?: number | null
  last_error?: string | null
  next_retry_at?: string | null
  provider_message_id?: string | null
  meta_summary?: DeliveryMetaSummary | null
  created_at?: string | null
  sent_at?: string | null
  [key: string]: unknown
}

/** 批量发送结果：逐账号独立投递，单条失败不影响整批。 */
export interface NotificationBatchResult {
  batch_id: string
  total: number
  sent: number
  skipped: number
  results: Array<{
    account_id: number
    notification_id: number | null
    status: string
    detail: string | null
  }>
}

/** 结构化回执历史：从 delivery.meta 拆出的稳定字段，便于对账。 */
export interface PushReceiptHistory {
  delivery_id: number
  channel: string
  status: string
  attempts: number
  subscribers: number
  delivered: number
  expired: number[]
  receipts: PushReceipt[]
  retry_after_seconds: number | null
  reason: string | null
  next_retry_at: string | null
}

/** 投递详情：meta 含逐订阅 receipts / expired / retry_after_seconds。 */
export interface NotificationDetail extends NotificationRow {
  meta: {
    subscribers?: number
    delivered?: number
    expired?: number[]
    receipts?: PushReceipt[]
    retry_after_seconds?: number | null
    reason?: string
    [key: string]: unknown
  }
}

export interface AuditRow {
  id: number
  actor_id?: number | null
  action: string
  target_type?: string | null
  target_id?: string | null
  ip?: string | null
  meta?: Record<string, unknown> | null
  created_at?: string | null
}

export interface PlanRow {
  code: string
  name: string
  price_month_cents?: number
  price_year_cents?: number
  currency?: string
  entitlements?: { key: string; limit: number; unit: string; reset_period?: string }[]
}

/** 后台套餐：比公开列表多 active/status，供套餐管理页展示与编辑。 */
export interface AdminPlanRow {
  code: string
  name: string
  price_month_cents: number
  price_year_cents: number
  currency: string
  features?: Record<string, unknown>
  active: boolean
  status: string
  entitlements: { key: string; limit: number; unit: string; reset_period?: string }[]
}

export interface PlanUpdatePayload {
  name?: string
  price_month_cents?: number
  price_year_cents?: number
  active?: boolean
  entitlements?: Record<string, number>
}

/** 可观测配置：前端错误上报的采样率、去重窗口与 zset 容量（后台可热改）。 */
export interface TelemetryCanary {
  sample_rate?: number | null
  dedupe_window_seconds?: number | null
  dedupe_max_entries?: number | null
}

export interface TelemetryConfig {
  sample_rate: number
  dedupe_window_seconds: number
  dedupe_max_entries: number
  canary_percent: number
  canary: TelemetryCanary
  source: 'environment' | 'database'
  updated_at: string | null
  updated_by: number | null
}

/** 统一技能目录（10 环节）：与后端 /v1/admin/skills 契约一致。 */
export type SkillCoverage = 'full' | 'partial' | 'cloud_gap'

export interface SkillEntry {
  stages: string[]
  cloud_skills: string[]
  api: string[]
}

export interface AdminSkillItem {
  id: string
  index: number
  name: string
  external: string | null
  trigger: string[]
  purpose: string
  coverage: SkillCoverage
  available: boolean
  entry: SkillEntry
  gap: string | null
  ssot: string
  writes: string[]
  next: string[]
  desktop_note: string
  cloud_note: string
  desktop_files: string[]
  cloud_files: string[]
  registered: boolean
  reference: string
}

export interface SkillsCatalog {
  items: AdminSkillItem[]
  degraded: string | null
  schema_version: string | null
  updated_at: string | null
}
