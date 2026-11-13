import { ref, onMounted } from 'vue'
import { fetchPresets, type PresetOption } from '@/services/presets'

/**
 * 在挂载时从 GET /v1/presets 拉取指定类型的预设，覆盖本地硬编码兜底常量。
 * 接口成功后严格以服务端为准（哪怕该类型返回空组）：避免管理端删除/清空预设后，
 * 前端又用本地常量把它补回来，造成维护列表与页面选项不一致。
 * 只有接口失败/未就绪时才回退 fallback，保证离线或弱网下仍可交互。
 */
export function usePresets(types: string[]) {
  const groups = ref<Record<string, PresetOption[]>>({})
  const loaded = ref(false)

  onMounted(async () => {
    try {
      const data = await fetchPresets(types)
      groups.value = data.groups || {}
      loaded.value = true
    } catch {
      /* 接口失败：保留本地兜底 */
    }
  })

  function presetValues(type: string, fallback: string[]): string[] {
    const opts = groups.value[type]
    if (loaded.value) return (opts || []).map((o) => o.value)
    return opts && opts.length ? opts.map((o) => o.value) : fallback
  }

  return { groups, loaded, presetValues }
}
