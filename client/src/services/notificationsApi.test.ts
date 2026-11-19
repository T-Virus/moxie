import { describe, expect, it } from 'vitest'
import { buildNotificationQuery, notificationMeta, notificationTone } from './notificationsApi'

describe('站内信查询参数', () => {
  it('默认 limit=50，不带 unread_only', () => {
    const params = new URLSearchParams(buildNotificationQuery())
    expect(params.get('limit')).toBe('50')
    expect(params.has('unread_only')).toBe(false)
  })

  it('只看未读时按后端字段名 unread_only=true 传递', () => {
    const params = new URLSearchParams(buildNotificationQuery({ limit: 20, unreadOnly: true }))
    expect(params.get('limit')).toBe('20')
    expect(params.get('unread_only')).toBe('true')
  })
})

describe('站内信展示映射', () => {
  it('已知分类有中文名与跳转目标', () => {
    expect(notificationMeta('subscription_expired')).toEqual({
      label: '订阅状态',
      to: '/plans',
    })
    expect(notificationMeta('payment_failed').to).toBe('/account?tab=orders')
  })

  it('未知分类回落到系统通知', () => {
    expect(notificationMeta('unknown_category')).toEqual({ label: '系统通知', to: '/' })
  })

  it('等级映射到对应徽标样式', () => {
    expect(notificationTone('error')).toBe('badge--danger')
    expect(notificationTone('warning')).toBe('badge--warn')
    expect(notificationTone('success')).toBe('badge--success')
    expect(notificationTone('info')).toBe('badge--brand')
  })
})
