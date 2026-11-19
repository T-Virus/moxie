/**
 * 自有模型配置（BYOK）会话态：Key + 自选模型 + 网关地址。
 *
 * 只存 sessionStorage：关闭标签页即失效；不写 localStorage、不进 Vue store、
 * 不随任务参数落库。实际请求头只由 apiFetch 在 withByok 模式注入。
 * 兼容旧版只存裸 Key 的记录（mx_byok_key）。
 */

export interface ByokConfig {
  key: string
  /** 模型名，如 gpt-4o / deepseek-chat；留空用服务端默认 */
  model: string
  /** OpenAI 兼容网关地址，如 https://api.openai.com/v1；留空用服务端默认 */
  baseUrl: string
}

const BYOK_KEY = 'mx_byok_key'
const BYOK_CONFIG = 'mx_byok_config'

function readConfig(): ByokConfig {
  // 新版结构化存储
  const raw = sessionStorage.getItem(BYOK_CONFIG)
  if (raw) {
    try {
      const parsed = JSON.parse(raw) as Partial<ByokConfig>
      return {
        key: String(parsed.key || '').trim(),
        model: String(parsed.model || '').trim(),
        baseUrl: String(parsed.baseUrl || '').trim(),
      }
    } catch {
      // 损坏则忽略，回落到旧 key
    }
  }
  // 旧版裸 key
  return { key: sessionStorage.getItem(BYOK_KEY) || '', model: '', baseUrl: '' }
}

export function getByokConfig(): ByokConfig {
  return readConfig()
}

export function getByokKey(): string {
  return readConfig().key
}

export function hasByokKey(): boolean {
  return !!getByokKey()
}

export function setByokConfig(config: ByokConfig): void {
  const key = (config.key || '').trim()
  if (!key) {
    clearByokKey()
    return
  }
  const normalized: ByokConfig = {
    key,
    model: (config.model || '').trim(),
    baseUrl: (config.baseUrl || '').trim().replace(/\/+$/, ''),
  }
  sessionStorage.setItem(BYOK_CONFIG, JSON.stringify(normalized))
  sessionStorage.removeItem(BYOK_KEY)
}

/** 兼容旧调用：只设置 key */
export function setByokKey(value: string): void {
  setByokConfig({ key: value, model: '', baseUrl: '' })
}

export function clearByokKey(): void {
  sessionStorage.removeItem(BYOK_KEY)
  sessionStorage.removeItem(BYOK_CONFIG)
}

export function byokHeaders(): Record<string, string> {
  const cfg = readConfig()
  if (!cfg.key) return {}
  const headers: Record<string, string> = { 'X-BYOK-Key': cfg.key }
  if (cfg.model) headers['X-BYOK-Model'] = cfg.model
  if (cfg.baseUrl) headers['X-BYOK-Base-URL'] = cfg.baseUrl
  return headers
}
