import { describe, expect, it, vi } from 'vitest'
import { ApiError, apiFetch, backoffDelay, friendlyMessage, trimPayload } from './http'

describe('friendlyMessage', () => {
  it('映射常见状态码为可读文案', () => {
    expect(friendlyMessage(401)).toContain('重新登录')
    expect(friendlyMessage(403)).toContain('权限')
    expect(friendlyMessage(429)).toContain('频繁')
  })

  it('5xx 与未知码有兜底文案', () => {
    expect(friendlyMessage(500)).toContain('服务端')
    expect(friendlyMessage(418)).toContain('失败')
  })
})

describe('trimPayload', () => {
  it('去掉普通短文本首尾空白', () => {
    expect(trimPayload({ title: '  我的书  ', tags: [' 男频 ', ' 爽文 '] })).toEqual({
      title: '我的书',
      tags: ['男频', '爽文'],
    })
  })

  it('保留口令、正文、提示词与通知正文的原始空白', () => {
    const payload = {
      password: '  secret  ',
      content: '\n第一段\n',
      body: '  通知正文  ',
      prompt: '  续写  ',
    }
    expect(trimPayload(payload)).toEqual(payload)
  })
})

describe('ApiError', () => {
  it('保留状态码、错误码与 requestId', () => {
    const err = new ApiError(422, 'validation_failed', '校验失败', 'req-1')
    expect(err.status).toBe(422)
    expect(err.code).toBe('validation_failed')
    expect(err.requestId).toBe('req-1')
    expect(err.name).toBe('ApiError')
  })
})

// combinedSignal 未导出，这里通过 AbortSignal.timeout 行为验证超时组合在 Node 可用，
// 真正的端到端超时在集成/E2E 覆盖；此处防止运行环境缺少该 API 导致线上直接报错。
describe('AbortSignal 组合能力', () => {
  it('Node 运行时支持 timeout 与 any', () => {
    expect(typeof AbortSignal.timeout).toBe('function')
    expect(typeof AbortSignal.any).toBe('function')
    const s = AbortSignal.any([AbortSignal.timeout(1000)])
    expect(s.aborted).toBe(false)
  })
})

describe('弱网退避', () => {
  it('按指数增长并加入不超过 25% 的抖动', () => {
    expect(backoffDelay(0, null, () => 0)).toBe(300)
    expect(backoffDelay(1, null, () => 0)).toBe(600)
    expect(backoffDelay(2, null, () => 1)).toBe(1500)
  })

  it('尊重 Retry-After 且不超过上限', () => {
    expect(backoffDelay(0, '2', () => 0)).toBe(2000)
    expect(backoffDelay(10, '99', () => 1)).toBe(5000)
  })

  it('GET 网络失败后自动重试一次', async () => {
    Object.defineProperty(globalThis, 'sessionStorage', {
      value: {
        getItem: () => null,
        setItem: () => undefined,
        removeItem: () => undefined,
      },
      configurable: true,
      writable: true,
    })
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError('network down'))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
      )
    vi.stubGlobal('fetch', fetchMock)

    const result = await apiFetch<{ ok: boolean }>('https://example.test/ping', { retry: 1 })
    expect(result).toEqual({ ok: true })
    expect(fetchMock).toHaveBeenCalledTimes(2)
    vi.unstubAllGlobals()
  })
})
