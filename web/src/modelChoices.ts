import { state, store } from './store'

/**
 * 页面「模型」下拉的候选（与设置页共用同一套档案）：
 * 当前工序绑定的档案模型 → 全部档案模型 → 服务商预设里的模型 → 全局默认。
 * 顺序即推荐优先级，去重后交给 SelectBox；用户仍可在面板里直接输入自定义模型名。
 */
export function modelChoices(stageKey: string, extra: string[] = []): string[] {
  const out: string[] = []
  const push = (m?: string | null) => {
    const v = String(m || '').trim()
    if (v && !out.includes(v)) out.push(v)
  }
  push(store.profileFor(stageKey)?.profile.model)
  for (const p of Object.values(state.studio?.profiles || {})) push(p.model)
  for (const pp of state.studio?.provider_presets || []) {
    for (const m of pp.models || []) push(m)
  }
  push(state.model)
  for (const m of extra) push(m)
  if (!out.length) push('deepseek-v4-flash')
  return out
}
