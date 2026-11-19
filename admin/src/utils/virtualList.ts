/** 定高列表虚拟滚动的可见区间计算：与 UI 解耦，node 环境可单测。
 *
 * 采用「上下占位 + 中间渲染可见行」的方案：不引入第三方虚拟滚动依赖，
 * 对 DOM 只保留视口附近的行，避免上千章目录把整棵 DOM 树撑爆。
 */
export interface VirtualRange {
  /** 可见起始行（含），已计入 overscan */
  start: number
  /** 可见结束行（不含） */
  end: number
  /** 上方占位高度（px） */
  paddingTop: number
  /** 下方占位高度（px） */
  paddingBottom: number
}

const EMPTY: VirtualRange = { start: 0, end: 0, paddingTop: 0, paddingBottom: 0 }

/**
 * @param count 总行数
 * @param rowHeight 单行高度（px，所有行等高）
 * @param scrollTop 容器滚动位置
 * @param viewportHeight 容器可视高度
 * @param overscan 视口上下各多渲染几行，减少快速滚动时的白屏
 */
export function computeVirtualRange(
  count: number,
  rowHeight: number,
  scrollTop: number,
  viewportHeight: number,
  overscan = 6,
): VirtualRange {
  if (count <= 0 || rowHeight <= 0) return EMPTY
  const vh = Math.max(0, viewportHeight)
  const visible = Math.ceil(vh / rowHeight) + overscan * 2
  // 上限钳制：scrollTop 异常过大（如内容收缩后）也要渲染尾部若干行，不能返回空区间
  const start = Math.min(
    Math.max(0, Math.floor(Math.max(0, scrollTop) / rowHeight) - overscan),
    Math.max(0, count - 1),
  )
  const end = Math.min(count, start + visible)
  return {
    start,
    end,
    paddingTop: start * rowHeight,
    paddingBottom: Math.max(0, (count - end) * rowHeight),
  }
}
