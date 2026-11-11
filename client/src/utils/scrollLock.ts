/** 弹窗打开时锁定背景滚动：引用计数支持多个弹窗叠加，最后一个关闭时恢复。 */

let lockCount = 0
let savedBodyOverflow = ''
let savedScrollerOverflow = ''

function pageScroller(): HTMLElement | null {
  return document.querySelector<HTMLElement>('.shell__content')
}

export function lockPageScroll(): void {
  if (lockCount === 0) {
    savedBodyOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const scroller = pageScroller()
    if (scroller) {
      savedScrollerOverflow = scroller.style.overflow
      scroller.style.overflow = 'hidden'
    }
  }
  lockCount += 1
}

export function unlockPageScroll(): void {
  if (lockCount === 0) return
  lockCount -= 1
  if (lockCount > 0) return
  document.body.style.overflow = savedBodyOverflow
  const scroller = pageScroller()
  if (scroller) scroller.style.overflow = savedScrollerOverflow
}
