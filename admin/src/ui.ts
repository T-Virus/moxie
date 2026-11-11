const STATUS_LABELS: Record<string, string> = {
  active: '启用',
  banned: '已封禁',
  disabled: '已停用',
  inactive: '未启用',
  pending: '待处理',
  paid: '已支付',
  unpaid: '未支付',
  trialing: '试用中',
  past_due: '已逾期',
  paused: '已暂停',
  canceled: '已取消',
  cancelled: '已取消',
  expired: '已过期',
  refunded: '已退款',
  partially_refunded: '部分退款',
  succeeded: '成功',
  success: '成功',
  failed: '失败',
  running: '运行中',
  queued: '排队中',
  done: '完成',
  completed: '完成',
  requested: '待开票',
  issued: '已开具',
  voided: '已作废',
  rejected: '已作废',
  sent: '已发送',
  delivered: '已送达',
  retry_pending: '待重试',
  skipped: '已跳过',
  retrying: '重试中',
  received: '已接收',
  processing: '处理中',
  approving: '审批中',
  approved: '已通过',
  warning: '警告',
  critical: '严重',
  info: '提示',
}

const STATUS_CLASSES: Record<string, string> = {
  active: 'ok', paid: 'ok', succeeded: 'ok', success: 'ok', done: 'ok', completed: 'ok',
  issued: 'ok', sent: 'ok', delivered: 'ok', approved: 'ok',
  pending: 'warn', trialing: 'warn', past_due: 'warn', requested: 'warn', queued: 'warn',
  retry_pending: 'warn', processing: 'warn', approving: 'warn', warning: 'warn', unpaid: 'warn',
  banned: 'danger', failed: 'danger', voided: 'danger', rejected: 'danger', expired: 'danger', canceled: 'danger',
  cancelled: 'danger', disabled: 'danger', critical: 'danger',
  running: 'info', received: 'info',
  refunded: 'purple', partially_refunded: 'purple',
  paused: 'muted', inactive: 'muted',
}

export function statusLabel(value?: string | null): string {
  if (!value) return '—'
  return STATUS_LABELS[value] || value
}

export function statusClass(value?: string | null): string {
  if (!value) return 'muted'
  return STATUS_CLASSES[value] || 'muted'
}

export function formatTime(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date)
}

export function formatDate(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(date)
}

export function formatMoney(cents?: number | null, currency = 'CNY'): string {
  if (cents === null || cents === undefined || Number.isNaN(cents)) return '—'
  const value = cents / 100
  try {
    return new Intl.NumberFormat('zh-CN', { style: 'currency', currency }).format(value)
  } catch {
    return `¥${value.toFixed(2)}`
  }
}

export function formatNumber(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return new Intl.NumberFormat('zh-CN').format(value)
}

export function accountLabel(row: any): string {
  if (!row) return '—'
  const account = row.account || row
  return account?.email || account?.phone || (account?.id ? `#${account.id}` : '—')
}

export function accountIdOf(row: any): number | null {
  if (!row) return null
  const id = row.account_id ?? row.account?.id ?? row.id
  return typeof id === 'number' ? id : null
}

export function planLabel(row: any): string {
  if (!row) return '—'
  if (row.plan && typeof row.plan === 'object') return row.plan.name || row.plan.code || '—'
  if (typeof row.plan === 'string') return row.plan
  return row.plan_name || row.plan_code || '—'
}

export function prettyJson(value: unknown): string {
  if (value === null || value === undefined) return '—'
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

export function compactJson(value: unknown): string {
  if (value === null || value === undefined) return '—'
  try {
    const text = JSON.stringify(value)
    return text.length > 96 ? `${text.slice(0, 96)}…` : text
  } catch {
    return String(value)
  }
}

export function todayInputValue(offsetDays = 0): string {
  const date = new Date()
  date.setDate(date.getDate() + offsetDays)
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export function toDateInput(value?: string | null): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value.slice(0, 10)
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}
