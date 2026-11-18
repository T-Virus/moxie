import { describe, expect, it } from 'vitest'
import { toPayload } from './pushApi'

function fakeSubscription(json: Record<string, unknown>): PushSubscription {
  return { toJSON: () => json } as unknown as PushSubscription
}

describe('Web Push 订阅上报', () => {
  it('只提取 endpoint 与加密密钥三元组', () => {
    const payload = toPayload(
      fakeSubscription({
        endpoint: 'https://push.example.com/sub/1',
        expirationTime: null,
        keys: { p256dh: 'p256-key', auth: 'auth-key' },
      }),
      'Chrome',
    )
    expect(payload).toEqual({
      endpoint: 'https://push.example.com/sub/1',
      keys: { p256dh: 'p256-key', auth: 'auth-key' },
      device_label: 'Chrome',
    })
  })

  it('缺失 keys 时用空串兜底，不抛异常', () => {
    const payload = toPayload(fakeSubscription({ endpoint: 'https://push.example.com/sub/2' }))
    expect(payload.keys).toEqual({ p256dh: '', auth: '' })
    expect(payload.device_label).toBeNull()
  })
})
