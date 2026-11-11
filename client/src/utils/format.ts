import type { RunMode, RunStatus, StageState } from '@/types'

export const MODE_LABEL: Record<RunMode, string> = {
  hot: '热门写作',
  reference: '参考写作',
  custom: '大神写作',
}

export const STATUS_LABEL: Record<RunStatus, string> = {
  queued: '排队中',
  running: '生成中',
  paused: '已停止',
  succeeded: '已完成',
  failed: '失败',
  canceled: '已取消',
}

/** paused 只表示用户主动停止，任务执行过程中不会等待确认 */
export function statusLabel(status: RunStatus): string {
  return STATUS_LABEL[status]
}

export const STATUS_TONE: Record<RunStatus, string> = {
  queued: '',
  running: 'badge--brand',
  paused: 'badge--warn',
  succeeded: 'badge--success',
  failed: 'badge--danger',
  canceled: '',
}

export const STAGE_LABEL: Record<StageState, string> = {
  pending: '待开始',
  running: '进行中',
  succeeded: '已完成',
  failed: '失败',
  skipped: '已跳过',
}

export function formatBytes(size: number): string {
  if (!size) return '0 KB'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatClock(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '--:--:--'
  return date.toLocaleTimeString('zh-CN', { hour12: false })
}

export function relativeTime(iso: string): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const diff = Date.now() - then
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`
  return `${Math.floor(diff / 86400000)} 天前`
}

export function clampProgress(value: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.max(0, Math.min(100, Math.round(value)))
}
