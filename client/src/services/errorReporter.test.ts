import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from './http'
import { getLastRequestId, noteRequestId, reportApiError, sendReport } from './errorReporter'

const fetchMock = vi.fn()

beforeEach(() => {
  fetchMock.mockReset()
  fetchMock.mockResolvedValue({ ok: true } as Response)
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('reportApiError', () => {
  it('4xx 用户侧错误不上报', () => {
    reportApiError(new ApiError(422, 'validation_failed', '校验失败', 'req-1'), '/v1/runs')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('5xx 上报并携带服务端 requestId', () => {
    reportApiError(new ApiError(500, 'internal_error', '服务内部错误', 'req-500'), '/v1/runs')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/telemetry/client-error')
    const body = JSON.parse(init.body as string)
    expect(body.code).toBe('internal_error')
    expect(body.request_id).toBe('req-500')
    expect(body.source).toBe('client')
  })

  it('网络错误（status 0）也上报', () => {
    reportApiError(new ApiError(0, 'network_error', '无法连接服务端'), '/v1/runs')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('上报失败不会抛出（fetch reject 被吞掉）', async () => {
    fetchMock.mockRejectedValueOnce(new Error('offline'))
    expect(() => sendReport({ level: 'error', code: 'x', message: 'y', source: 'client', url: '/' })).not.toThrow()
  })
})

describe('节流', () => {
  it('相同错误在窗口内只上报一次', () => {
    const payload = { level: 'error' as const, code: 'dup', message: 'same', source: 'client', url: '/' }
    sendReport(payload)
    sendReport(payload)
    sendReport(payload)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})

describe('requestId 关联', () => {
  it('noteRequestId 记录最近一次服务端 id 供 JS 异常关联', () => {
    noteRequestId('req-from-header')
    expect(getLastRequestId()).toBe('req-from-header')
    sendReport({ level: 'error', code: 'js_error', message: 'boom', source: 'client', url: '/' })
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    const body = JSON.parse(init.body as string)
    expect(body.request_id).toBe('req-from-header')
  })
})
