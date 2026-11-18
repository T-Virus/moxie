import { ref } from 'vue'
import { streamRunEvents } from '@/services/agentApi'
import type { RunEvent, RunStatus } from '@/types'

/** 触发刷新/停止判断所需的最小上下文，由视图注入，便于独立测试。 */
export interface RunStreamOptions {
  /** 当前 run 状态；变化时由调用方负责重启或停止同步 */
  getStatus: () => RunStatus | undefined
  /** 拉取最新详情（通常是 loadRun(true)） */
  refresh: () => Promise<void>
  /** 轮询降级间隔，默认 1800ms */
  pollIntervalMs?: number
  /** 事件唤醒刷新的最小间隔（节流），默认 500ms */
  eventThrottleMs?: number
  /** 流正常结束后的重连延时，默认 300ms */
  reconnectDelayMs?: number
}

const TERMINAL: RunStatus[] = ['succeeded', 'failed', 'canceled']

function isBlocked(status: RunStatus | undefined): boolean {
  return !status || TERMINAL.includes(status) || status === 'paused'
}

/**
 * 任务详情的实时同步：优先 SSE 事件流，失败时自动降级为固定间隔轮询。
 *
 * SSE 端点只推送日志事件（seq/stage/...），不含状态与正文，因此：
 *  - 事件到达时按节流频率触发 refresh() 拉取详情；
 *  - 每次流正常结束（后端 60s 上限或任务终态）后再强制 refresh() 一次，
 *    兜底捕获「无日志事件的状态跃迁」；
 *  - 用最大 seq 作为下次连接的 since，服务端按 seq > since 天然去重；
 *  - 流抛错（端点不支持/网络中断/鉴权失效）时降级为轮询，避免界面停滞。
 */
export function useRunStream(options: RunStreamOptions) {
  const active = ref(false)
  const usingFallback = ref(false)
  let controller: AbortController | null = null
  let timer: ReturnType<typeof setInterval> | null = null
  let generation = 0
  let lastSeq = 0
  let lastFetchAt = 0

  function onEvent(event: RunEvent): void {
    if (typeof event.seq === 'number' && event.seq > lastSeq) lastSeq = event.seq
    const now = Date.now()
    if (now - lastFetchAt < (options.eventThrottleMs ?? 500)) return
    lastFetchAt = now
    void options.refresh()
  }

  function fallbackToPolling(): void {
    // 竞态保护：若已停止（卸载/切换任务/终态），不再启动轮询
    if (!active.value || timer !== null) return
    usingFallback.value = true
    timer = setInterval(() => {
      if (!active.value) return
      if (isBlocked(options.getStatus())) {
        stop()
        return
      }
      void options.refresh()
    }, options.pollIntervalMs ?? 1800)
  }

  async function streamLoop(runId: string, signal: AbortSignal, gen: number): Promise<void> {
    let since = 0
    while (!signal.aborted && gen === generation && active.value) {
      try {
        await streamRunEvents(runId, since, onEvent, signal)
      } catch {
        if (signal.aborted || gen !== generation || !active.value) return
        // SSE 不可用（404/405/501）或网络中断：降级轮询
        fallbackToPolling()
        return
      }
      if (signal.aborted || gen !== generation || !active.value) return
      // 流结束兜底刷新一次，捕获无日志事件的状态变化
      await options.refresh()
      if (isBlocked(options.getStatus())) {
        stop()
        return
      }
      since = lastSeq
      await new Promise((resolve) =>
        setTimeout(resolve, options.reconnectDelayMs ?? 300),
      )
    }
  }

  function start(runId: string): void {
    stop()
    active.value = true
    usingFallback.value = false
    lastSeq = 0
    lastFetchAt = 0
    const gen = ++generation
    const ctrl = new AbortController()
    controller = ctrl
    void streamLoop(runId, ctrl.signal, gen)
  }

  function stop(): void {
    active.value = false
    generation++
    if (controller) {
      controller.abort()
      controller = null
    }
    if (timer !== null) {
      clearInterval(timer)
      timer = null
    }
  }

  return { active, usingFallback, start, stop }
}
