/** 顶栏未读角标：全局单例状态 + 轮询，成功/失败都不打断主流程。 */
import { ref } from 'vue'
import { hasSession } from '@/services/http'
import { fetchNotifications } from '@/services/notificationsApi'

export const unreadCount = ref(0)

let timer: ReturnType<typeof setInterval> | null = null

export function setUnreadCount(value: number): void {
  unreadCount.value = Math.max(0, Math.trunc(value))
}

export async function refreshUnreadCount(): Promise<void> {
  if (!hasSession()) {
    unreadCount.value = 0
    return
  }
  try {
    // limit=1 只为拿 unread_count，避免把整页消息拉回来
    const data = await fetchNotifications({ limit: 1 })
    setUnreadCount(data.unread_count)
  } catch {
    // 角标是增强信息：网络抖动时保持上一次数值，不弹错误
  }
}

export function startUnreadPolling(intervalMs = 60_000): void {
  stopUnreadPolling()
  if (!hasSession()) return
  void refreshUnreadCount()
  timer = setInterval(() => {
    if (document.visibilityState === 'visible') void refreshUnreadCount()
  }, intervalMs)
}

export function stopUnreadPolling(): void {
  if (timer !== null) {
    clearInterval(timer)
    timer = null
  }
}
