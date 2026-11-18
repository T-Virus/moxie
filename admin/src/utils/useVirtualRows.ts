import { computed, ref, type ComputedRef, type Ref } from 'vue'
import { computeVirtualRange, type VirtualRange } from './virtualList'

export interface VirtualRows<T> {
  /** 容器当前滚动位置（px），测试可直接赋值推进。 */
  scrollTop: Ref<number>
  range: ComputedRef<VirtualRange>
  /** 当前应渲染的行切片（保留原始对象，不做转换）。 */
  visibleRows: ComputedRef<T[]>
  onScroll: (event: { target: EventTarget | null }) => void
  resetScroll: () => void
}

/**
 * 表格长列表虚拟滚动：定高行 + 上下 spacer 占位，只渲染视口附近的行。
 * 与 TaskBoard 的日志虚拟化同源（computeVirtualRange），抽成 composable 供多页复用。
 */
export function useVirtualRows<T>(
  rows: Ref<T[]>,
  rowHeight: number,
  viewportHeight: number,
  overscan = 6,
): VirtualRows<T> {
  const scrollTop = ref(0)
  const range = computed(() =>
    computeVirtualRange(rows.value.length, rowHeight, scrollTop.value, viewportHeight, overscan),
  )
  const visibleRows = computed(() => rows.value.slice(range.value.start, range.value.end))
  const onScroll = (event: { target: EventTarget | null }): void => {
    const el = event.target as HTMLElement | null
    scrollTop.value = el ? el.scrollTop : 0
  }
  const resetScroll = (): void => {
    scrollTop.value = 0
  }
  return { scrollTop, range, visibleRows, onScroll, resetScroll }
}
