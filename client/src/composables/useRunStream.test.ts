import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { RunEvent, RunStatus } from '@/types'

const mocks = vi.hoisted(() => ({
  streamRunEvents: vi.fn(),
}))

vi.mock('@/services/agentApi', () => ({
  streamRunEvents: mocks.streamRunEvents,
}))

import { useRunStream } from './useRunStream'

function event(seq: number): RunEvent {
  return { seq, stage: 'run', level: 'info', message: `evt-${seq}`, at: '2026-11-17T00:00:00Z' }
}

beforeEach(() => {
  mocks.streamRunEvents.mockReset()
})

describe('useRunStream', () => {
  it('SSE 端点不可用时降级为轮询', async () => {
    mocks.streamRunEvents.mockRejectedValueOnce(new Error('501 not implemented'))
    const refresh = vi.fn().mockResolvedValue(undefined)
    const live = useRunStream({ getStatus: () => 'running', refresh, pollIntervalMs: 1000 })

    live.start('run-1')
    await vi.waitFor(() => expect(live.usingFallback.value).toBe(true))
    expect(live.active.value).toBe(true)
    live.stop()
    expect(live.active.value).toBe(false)
  })

  it('刷新后进入终态则停止同步', async () => {
    mocks.streamRunEvents.mockResolvedValue(undefined)
    let status: RunStatus = 'running'
    const refresh = vi.fn().mockImplementation(async () => {
      status = 'succeeded'
    })
    const live = useRunStream({ getStatus: () => status, refresh })

    live.start('run-2')
    await vi.waitFor(() => expect(live.active.value).toBe(false))
    expect(live.usingFallback.value).toBe(false)
  })

  it('paused 状态停止同步', async () => {
    mocks.streamRunEvents.mockResolvedValue(undefined)
    let status: RunStatus = 'running'
    const refresh = vi.fn().mockImplementation(async () => {
      status = 'paused'
    })
    const live = useRunStream({ getStatus: () => status, refresh })

    live.start('run-3')
    await vi.waitFor(() => expect(live.active.value).toBe(false))
  })

  it('用事件最大 seq 作为下次连接的 since（去重）', async () => {
    mocks.streamRunEvents.mockImplementation(
      async (_id: string, since: number, onEvent: (e: RunEvent) => void) => {
        if (since === 0) {
          onEvent(event(5))
          onEvent(event(9)) // 乱序 / 重复都应取最大值
        }
      },
    )
    const refresh = vi.fn().mockResolvedValue(undefined)
    const live = useRunStream({
      getStatus: () => 'running',
      refresh,
      reconnectDelayMs: 5,
      eventThrottleMs: 0,
    })

    live.start('run-4')
    await vi.waitFor(() => {
      expect(mocks.streamRunEvents.mock.calls.length).toBeGreaterThanOrEqual(2)
    })
    expect(mocks.streamRunEvents.mock.calls[1]?.[1]).toBe(9)
    live.stop()
  })

  it('stop() 中止进行中的流', async () => {
    let captured: AbortSignal | null = null
    mocks.streamRunEvents.mockImplementation(
      async (_id: string, _since: number, _onEvent: (e: RunEvent) => void, signal: AbortSignal) => {
        captured = signal
        await new Promise(() => {}) // 永不自然结束
      },
    )
    const live = useRunStream({ getStatus: () => 'running', refresh: vi.fn() })

    live.start('run-5')
    await vi.waitFor(() => expect(captured).not.toBeNull())
    live.stop()
    expect((captured as AbortSignal | null)?.aborted).toBe(true)
  })
})
