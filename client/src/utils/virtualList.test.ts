import { describe, expect, it } from 'vitest'
import { computeVirtualRange, isIndexVisible } from './virtualList'

describe('computeVirtualRange', () => {
  it('空列表返回全 0', () => {
    expect(computeVirtualRange(0, 30, 0, 300)).toEqual({ start: 0, end: 0, paddingTop: 0, paddingBottom: 0 })
    expect(computeVirtualRange(100, 0, 0, 300).end).toBe(0)
  })

  it('顶部：从 0 开始，含 overscan', () => {
    const r = computeVirtualRange(1000, 30, 0, 300, 3)
    expect(r.start).toBe(0)
    expect(r.end).toBe(16) // ceil(300/30)=10 + 上下 overscan 各 3
    expect(r.paddingTop).toBe(0)
    expect(r.paddingBottom).toBe((1000 - 16) * 30)
  })

  it('滚动到中部：起止与占位正确、总高度守恒', () => {
    const r = computeVirtualRange(1000, 30, 3000, 300, 3)
    expect(r.start).toBe(97) // 3000/30 - 3
    expect(r.end).toBe(113) // 视口 10 行 + 上下各 3 行 overscan
    expect(r.paddingTop).toBe(97 * 30)
    expect(r.paddingBottom).toBe((1000 - 113) * 30)
    // 占位 + 可见行高度 = 总高度
    expect(r.paddingTop + (r.end - r.start) * 30 + r.paddingBottom).toBe(1000 * 30)
  })

  it('底部：end 不超过总数，paddingBottom 归零', () => {
    const r = computeVirtualRange(100, 30, 100000, 300, 3)
    expect(r.end).toBe(100)
    expect(r.paddingBottom).toBe(0)
    expect(r.start).toBeLessThan(100)
  })

  it('列表不足以填满视口时全部渲染', () => {
    const r = computeVirtualRange(5, 30, 0, 300, 3)
    expect(r.start).toBe(0)
    expect(r.end).toBe(5)
    expect(r.paddingBottom).toBe(0)
  })
})

describe('isIndexVisible', () => {
  it('判断目标行是否在可见区间', () => {
    const range = computeVirtualRange(100, 30, 300, 300, 2)
    expect(isIndexVisible(range.start, range)).toBe(true)
    expect(isIndexVisible(range.start - 1, range)).toBe(false)
    expect(isIndexVisible(range.end, range)).toBe(false)
  })
})
