/* 安卓端 / 手机宽度判定：App.vue 的外壳切换与路由组件选择共用同一套规则 */
export function isMobileView(): boolean {
  if (typeof window === 'undefined') return false
  const force = new URLSearchParams(window.location.search).get('mobile')
  if (force === '1') return true
  if (force === '0') return false
  const viaWidth = !!window.matchMedia?.('(max-width: 760px)').matches
  return !!(window as any).Native || viaWidth
}
