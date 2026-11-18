/** Web Push 订阅辅助：只在浏览器 + SW + VAPID 公钥齐备时可用，失败一律静默降级。 */

export function pushSupported(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof navigator !== 'undefined' &&
    'serviceWorker' in navigator &&
    'PushManager' in window
  )
}

/** VAPID 公钥是 base64url，PushManager 需要 Uint8Array。 */
export function urlBase64ToUint8Array(value: string): Uint8Array {
  const padding = '='.repeat((4 - (value.length % 4)) % 4)
  const base64 = (value + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(base64)
  return Uint8Array.from(raw, (ch) => ch.charCodeAt(0))
}

/** 通知跳转目标只接受同源相对路径，避免恶意 payload 造成钓鱼跳转。 */
export function safeNotificationPath(input: unknown): string {
  if (typeof input !== 'string' || !input) return '/'
  try {
    const origin =
      typeof window !== 'undefined' ? window.location.origin : 'http://localhost'
    const url = new URL(input, origin)
    if (url.origin !== origin) return '/'
    return `${url.pathname}${url.search}${url.hash}`
  } catch {
    return '/'
  }
}

export async function currentPushSubscription(): Promise<PushSubscription | null> {
  if (!pushSupported()) return null
  try {
    const registration = await navigator.serviceWorker.ready
    return await registration.pushManager.getSubscription()
  } catch {
    return null
  }
}

export async function enablePush(vapidPublicKey: string): Promise<PushSubscription | null> {
  if (!pushSupported() || !vapidPublicKey) return null
  try {
    const registration = await navigator.serviceWorker.ready
    return await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(vapidPublicKey) as BufferSource,
    })
  } catch {
    // 用户拒绝授权 / 浏览器策略禁止时静默失败，不影响主流程
    return null
  }
}

export async function disablePush(): Promise<boolean> {
  const subscription = await currentPushSubscription()
  if (!subscription) return false
  try {
    return await subscription.unsubscribe()
  } catch {
    return false
  }
}
