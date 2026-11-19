/** 站内信：列表、未读数与已读标记。服务端模板见 server/services/notifications.py。 */
import { apiFetch } from './http'

export interface NotificationItem {
  id: number
  category: string
  title: string
  body: string
  level: string
  status: string
  meta: Record<string, unknown> | null
  created_at: string | null
  read_at: string | null
}

export interface NotificationListResult {
  items: NotificationItem[]
  unread_count: number
}

export interface NotificationQuery {
  limit?: number
  unreadOnly?: boolean
}

/** 纯函数：拼查询串，便于单测锁定参数名（后端用 unread_only）。 */
export function buildNotificationQuery(query: NotificationQuery = {}): string {
  const params = new URLSearchParams()
  params.set('limit', String(query.limit ?? 50))
  if (query.unreadOnly) params.set('unread_only', 'true')
  return params.toString()
}

export async function fetchNotifications(query: NotificationQuery = {}): Promise<NotificationListResult> {
  return apiFetch<NotificationListResult>(`/notifications?${buildNotificationQuery(query)}`)
}

export async function markNotificationRead(
  id: number,
): Promise<{ notification: NotificationItem }> {
  return apiFetch<{ notification: NotificationItem }>(
    `/notifications/${encodeURIComponent(String(id))}/read`,
    { method: 'POST' },
  )
}

export async function markAllNotificationsRead(): Promise<{ ok: boolean; marked: number }> {
  return apiFetch<{ ok: boolean; marked: number }>('/notifications/read-all', { method: 'POST' })
}

/** 分类 → 中文名 + 点击跳转；未知分类回落为「系统通知」。 */
const CATEGORY_META: Record<string, { label: string; to: string }> = {
  subscription_renewal_reminder: { label: '订阅提醒', to: '/plans' },
  subscription_expired: { label: '订阅状态', to: '/plans' },
  credit_pack_expiring: { label: '额度包', to: '/plans' },
  payment_succeeded: { label: '支付', to: '/account?tab=orders' },
  payment_failed: { label: '支付', to: '/account?tab=orders' },
  quota_insufficient: { label: '额度', to: '/plans' },
  usage_anomaly: { label: '用量提醒', to: '/runs' },
  admin_message: { label: '平台通知', to: '/' },
}

export function notificationMeta(category: string): { label: string; to: string } {
  return CATEGORY_META[category] || { label: '系统通知', to: '/' }
}

/** 等级 → 徽标样式；unknown 用中性色，避免出现无样式裸文本。 */
export function notificationTone(level: string): string {
  if (level === 'error') return 'badge--danger'
  if (level === 'warning' || level === 'warn') return 'badge--warn'
  if (level === 'success') return 'badge--success'
  return 'badge--brand'
}
