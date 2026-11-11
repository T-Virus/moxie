import type { PaymentProviderOption, Plan, QuotaSummary, Subscription } from '@/types'
import { ApiError, apiFetch } from './http'

export async function fetchPlans(): Promise<Plan[]> {
  const data = await apiFetch<{ plans: Plan[] }>('/plans')
  return data.plans || []
}

/** 服务端在没有订阅时返回 404 no_subscription，这里归一化为 null。 */
export async function fetchCurrentSubscription(): Promise<Subscription | null> {
  try {
    return await apiFetch<Subscription>('/subscriptions/current')
  } catch (err) {
    if (err instanceof ApiError && (err.status === 404 || err.code === 'no_subscription')) {
      return null
    }
    throw err
  }
}

export async function fetchEntitlements(): Promise<QuotaSummary> {
  return apiFetch<QuotaSummary>('/entitlements')
}

export interface SubscribeResult {
  subscription: Subscription
  payment?: { provider: string; amount_cents: number; currency: string }
}

/** 当前环境真正可下单的支付渠道（服务端已过滤未配置/生产禁用的渠道） */
export async function fetchPaymentProviders(): Promise<PaymentProviderOption[]> {
  const data = await apiFetch<{ items: PaymentProviderOption[] }>('/payments/providers')
  return data.items || []
}

/** 登录后下单：provider 必须显式传入，由服务端校验渠道可用性 */
export async function subscribePlan(
  planCode: string,
  cycle: 'month' | 'year' = 'month',
  provider = '',
): Promise<SubscribeResult> {
  return apiFetch<SubscribeResult>('/subscriptions', {
    method: 'POST',
    body: JSON.stringify({ plan_code: planCode, cycle, provider }),
  })
}

export function formatMoney(cents: number, currency = 'CNY'): string {
  const symbol = currency === 'CNY' ? '¥' : ''
  const value = cents / 100
  // 最多两位小数并去掉尾零：990 → 9.9，9900/12 → 8.25，100 → 100
  const text = value.toFixed(2).replace(/\.?0+$/, '')
  return `${symbol}${text}`
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })
}
