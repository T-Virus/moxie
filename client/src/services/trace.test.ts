import { beforeEach, describe, expect, it } from 'vitest'
import { currentTraceId, resetTraceId, traceHeaders } from './trace'

class MemoryStorage {
  private data = new Map<string, string>()

  getItem(key: string): string | null {
    return this.data.get(key) ?? null
  }

  setItem(key: string, value: string): void {
    this.data.set(key, value)
  }

  removeItem(key: string): void {
    this.data.delete(key)
  }
}

describe('端到端链路 ID', () => {
  beforeEach(() => {
    Object.defineProperty(globalThis, 'sessionStorage', {
      value: new MemoryStorage(),
      configurable: true,
      writable: true,
    })
    resetTraceId()
  })

  it('同一会话稳定复用 32 位 trace-id', () => {
    const first = currentTraceId()
    expect(first).toMatch(/^[0-9a-f]{32}$/)
    expect(currentTraceId()).toBe(first)
  })

  it('请求头包含 trace-id 与每请求独立的 W3C traceparent', () => {
    const first = traceHeaders()
    const second = traceHeaders()
    expect(first['X-Trace-Id']).toBe(second['X-Trace-Id'])
    expect(first.Traceparent).toMatch(/^00-[0-9a-f]{32}-[0-9a-f]{16}-01$/)
    expect(first.Traceparent).not.toBe(second.Traceparent)
  })

  it('重置后生成新的 trace-id', () => {
    const first = currentTraceId()
    resetTraceId()
    expect(currentTraceId()).not.toBe(first)
  })
})
