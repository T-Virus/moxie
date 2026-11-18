import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from './api'
import { getLastRequestId, noteRequestId, reportApiError } from './errorReporter'

const fetchMock = vi.fn()

beforeEach(() => {
  fetchMock.mockReset()
  fetchMock.mockResolvedValue({ ok: true } as Response)
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => vi.unstubAllGlobals())

describe('admin reportApiError', () => {
  it('4xx 不上报，5xx 上报并标记来源 admin', () => {
    reportApiError(new ApiError(403, 'forbidden', '无权限', '/v1/admin', 'req-1'), '/v1/admin/users')
    expect(fetchMock).not.toHaveBeenCalled()
    reportApiError(new ApiError(500, 'internal_error', '错误', '/v1/admin', 'req-2'), '/v1/admin/users', 'req-2')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/v1/telemetry/client-error')
    const body = JSON.parse(init.body as string)
    expect(body.source).toBe('admin')
    expect(body.request_id).toBe('req-2')
  })

  it('noteRequestId 记录链路 id', () => {
    noteRequestId('req-admin')
    expect(getLastRequestId()).toBe('req-admin')
  })
})
