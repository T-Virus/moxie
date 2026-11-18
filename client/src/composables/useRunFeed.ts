import { onBeforeUnmount, ref } from 'vue'
import { streamRunFeed } from '@/services/agentApi'

interface RunFeedOptions {
  /** 是否还有活跃任务；无活跃任务时自动断开事件流。 */
  active: () => boolean
  /** 收到 refresh 或降级轮询时要执行的列表刷新。 */
  refresh: () => void
  /** SSE 不可用时的兜底轮询间隔，默认 4000ms。 */
  pollIntervalMs?: number
}

/**
 * 账号级运行变更流：SSE 优先，404/405/501 等不支持场景自动降级轮询。
 * 降级后不再空转重连 SSE，调用方重新 active 时才会再次尝试。
 */
export function useRunFeed(options: RunFeedOptions) {
  const usingFallback = ref(false)
  let controller: AbortController | null = null
  let timer: number | null = null

  function stopFallback(): void {
    if (timer !== null) {
      window.clearInterval(timer)
      timer = null
    }
  }

  function startFallback(): void {
    if (timer !== null || !options.active()) return
    usingFallback.value = true
    timer = window.setInterval(() => {
      if (!options.active()) return
      options.refresh()
    }, options.pollIntervalMs ?? 4000)
  }

  async function connect(signal: AbortSignal): Promise<void> {
    while (!signal.aborted && options.active()) {
      try {
        await streamRunFeed((event) => {
          if (event.type === 'refresh') options.refresh()
        }, signal)
      } catch {
        // 流不可用（含 404/405/501）或网络中断：统一降级轮询，避免空转重连。
        if (signal.aborted) return
        startFallback()
        return
      }
      if (signal.aborted || !options.active() || usingFallback.value) return
      await new Promise((resolve) => window.setTimeout(resolve, 300))
    }
  }

  function start(): void {
    if (controller) return
    if (!options.active()) return
    usingFallback.value = false
    controller = new AbortController()
    void connect(controller.signal)
  }

  function stop(): void {
    controller?.abort()
    controller = null
    stopFallback()
    usingFallback.value = false
  }

  function sync(active: boolean): void {
    if (active) start()
    else stop()
  }

  onBeforeUnmount(stop)
  return { sync, stop, usingFallback }
}
