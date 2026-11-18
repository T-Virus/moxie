/**
 * 自有模型 Key（BYOK）会话态。
 *
 * 只存 sessionStorage：关闭标签页即失效；不写 localStorage、不进 Vue store、
 * 不随任务参数落库。实际请求头只由 apiFetch 在 withByok 模式注入。
 */

const BYOK_KEY = 'mx_byok_key'

export function getByokKey(): string {
  return sessionStorage.getItem(BYOK_KEY) || ''
}

export function hasByokKey(): boolean {
  return !!getByokKey()
}

export function setByokKey(value: string): void {
  const key = (value || '').trim()
  if (key) sessionStorage.setItem(BYOK_KEY, key)
  else clearByokKey()
}

export function clearByokKey(): void {
  sessionStorage.removeItem(BYOK_KEY)
}

export function byokHeaders(): Record<string, string> {
  const key = getByokKey()
  return key ? { 'X-BYOK-Key': key } : {}
}
