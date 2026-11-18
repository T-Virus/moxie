import { describe, expect, it } from 'vitest'
import { ref } from 'vue'
import { useVirtualRows } from './useVirtualRows'

const ROW_H = 40
const VIEW_H = 400

describe('useVirtualRows', () => {
  it('只渲染视口附近的行，spacer 高度守恒', () => {
    const rows = ref(Array.from({ length: 1000 }, (_, i) => ({ id: i })))
    const v = useVirtualRows(rows, ROW_H, VIEW_H, 3)

    v.scrollTop.value = 4000 // 第 100 行处
    expect(v.visibleRows.value[0].id).toBe(97) // 100 - overscan 3
    expect(v.range.value.paddingTop).toBe(97 * ROW_H)
    // 上方占位 + 可见行 + 下方占位 == 总高度
    expect(
      v.range.value.paddingTop + v.visibleRows.value.length * ROW_H + v.range.value.paddingBottom,
    ).toBe(1000 * ROW_H)
  })

  it('滚动到底部时钳制最后一行且下方占位为 0', () => {
    const rows = ref(Array.from({ length: 50 }, (_, i) => ({ id: i })))
    const v = useVirtualRows(rows, ROW_H, VIEW_H, 2)
    v.scrollTop.value = 5000 // 远超底部
    expect(v.range.value.end).toBe(50)
    expect(v.range.value.paddingBottom).toBe(0)
    expect(v.visibleRows.value[v.visibleRows.value.length - 1].id).toBe(49)
  })

  it('换页后 resetScroll 回到顶部', () => {
    const rows = ref(Array.from({ length: 200 }, (_, i) => ({ id: i })))
    const v = useVirtualRows(rows, ROW_H, VIEW_H)
    v.scrollTop.value = 2000
    expect(v.visibleRows.value[0].id).toBeGreaterThan(0)
    v.resetScroll()
    expect(v.visibleRows.value[0].id).toBe(0)
  })

  it('scroll 事件从事件目标读取 scrollTop', () => {
    const rows = ref(Array.from({ length: 200 }, (_, i) => ({ id: i })))
    const v = useVirtualRows(rows, ROW_H, VIEW_H)
    v.onScroll({ target: { scrollTop: 800 } as HTMLElement })
    expect(v.scrollTop.value).toBe(800)
  })
})
