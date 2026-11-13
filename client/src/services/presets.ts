import { apiFetch } from './http'

export interface PresetOption {
  value: string
  label: string
  audience: string[]
  custom: boolean
}

export interface PresetsResponse {
  groups: Record<string, PresetOption[]>
  types: string[]
}

/** 从服务端统一预设接口拉取选项（按 type 分组）。失败时由调用方回退到本地常量。 */
export function fetchPresets(types: string[]): Promise<PresetsResponse> {
  const q = types.length ? `?types=${encodeURIComponent(types.join(','))}` : ''
  return apiFetch<PresetsResponse>(`/presets${q}`)
}

export interface PresetCreatePayload {
  type: string
  value: string
  label?: string
  audience?: string
}

export interface PresetCreateResult {
  id: number
  type: string
  value: string
  label: string
  custom: boolean
}

/** 把用户的自定义输入持久化为本人私有预设，下次打开同一下拉即可复用。 */
export async function createPreset(
  payload: PresetCreatePayload,
): Promise<PresetCreateResult> {
  return apiFetch<PresetCreateResult>('/presets', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

/** 删除当前用户自己的自定义预设。 */
export async function deletePreset(id: number): Promise<{ deleted: boolean; id: number }> {
  return apiFetch<{ deleted: boolean; id: number }>(`/presets/${id}`, { method: 'DELETE' })
}
