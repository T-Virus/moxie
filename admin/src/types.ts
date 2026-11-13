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
  attempts?: number
  created_at?: string | null
  started_at?: string | null
  finished_at?: string | null
  cost_actual_cents?: number | null
  [key: string]: unknown
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

export interface NotificationRow {
  id: number
  channel?: string | null
  recipient?: string | null
  subject?: string | null
  template?: string | null
  status: string
  attempts?: number
  last_error?: string | null
  created_at?: string | null
  sent_at?: string | null
  [key: string]: unknown
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
