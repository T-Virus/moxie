import { ref, watch } from 'vue'
import type { Ref } from 'vue'

/**
 * 表单字段持久化：切走页面 / 刷新后仍保留用户上次填写的内容。
 *
 * 用于「大纲拆解 / 全文改编 / 正文生成 / 审查 / 工作台生成选项」等任务表单，
 * 避免离开页面再回来时选项被重置成默认值。
 *
 * - 统一存 localStorage，键前缀 `mb_form::`，与全局设置（mb_settings）互不干扰
 * - 仅存简单数据（string / number / boolean / string[]），不用于大段正文
 */
export function usePersistedRef<T>(name: string, defaultValue: T): Ref<T> {
  const key = 'mb_form::' + name
  let init: T = defaultValue
  try {
    const raw = localStorage.getItem(key)
    if (raw != null) {
      const parsed = JSON.parse(raw)
      if (parsed !== null && parsed !== undefined) init = parsed as T
    }
  } catch { /* 读取失败 / 非 JSON：回退默认值 */ }

  const r = ref(init) as unknown as Ref<T>
  watch(r, (v) => {
    try { localStorage.setItem(key, JSON.stringify(v)) } catch { /* 配额异常忽略 */ }
  }, { deep: true })
  return r
}
