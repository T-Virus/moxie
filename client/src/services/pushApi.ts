/** Web Push 订阅上报：浏览器订阅建立后把 endpoint/密钥交给服务端保存，才能从服务端推送。 */
import { apiFetch } from './http'

export interface PushSubscriptionView {
  id: number
  endpoint: string
  device_label: string | null
  status: string
  created_at: string | null
}

/** subscription.toJSON() -> 服务端订阅入参；只取推送必需的三元组。 */
export function toPayload(subscription: PushSubscription, deviceLabel?: string) {
  const json = subscription.toJSON()
  const keys = json.keys || {}
  return {
    endpoint: json.endpoint || '',
    keys: { p256dh: keys.p256dh || '', auth: keys.auth || '' },
    device_label: deviceLabel || null,
  }
}

/** 订阅建立/刷新后上报；失败静默吞掉（推送是增强功能，不能影响主流程）。 */
export async function reportPushSubscription(
  subscription: PushSubscription,
  deviceLabel?: string,
): Promise<boolean> {
  try {
    await apiFetch<{ items: PushSubscriptionView[] }>('/notifications/push-subscriptions', {
      method: 'POST',
      body: JSON.stringify(toPayload(subscription, deviceLabel)),
    })
    return true
  } catch {
    return false
  }
}

/** 退订：先取消浏览器订阅，再通知服务端删除，避免给已失效 endpoint 推送。 */
export async function removePushSubscription(subscription: PushSubscription): Promise<boolean> {
  const endpoint = subscription.toJSON().endpoint || ''
  let unsubscribed = false
  try {
    unsubscribed = await subscription.unsubscribe()
  } catch {
    unsubscribed = false
  }
  if (!unsubscribed || !endpoint) return unsubscribed
  try {
    const query = encodeURIComponent(endpoint)
    await apiFetch<{ items: PushSubscriptionView[] }>(
      `/notifications/push-subscriptions?endpoint=${query}`,
      { method: 'DELETE' },
    )
  } catch {
    // 浏览器已退订，服务端删除失败不影响用户意图；下次订阅会覆盖该 endpoint
  }
  return true
}
