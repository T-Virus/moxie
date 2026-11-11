import type { AdminAccount, AdminSession, Role } from './types'

const STORAGE_KEY = 'moxie_admin_session'

let memory: AdminSession | null = null

function readStorage(): AdminSession | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const value = JSON.parse(raw) as AdminSession
    if (!value?.access_token || !value?.refresh_token || !value?.account) return null
    if (typeof value.expires_at !== 'number') return null
    return value
  } catch {
    return null
  }
}

export function loadSession(): AdminSession | null {
  if (memory) return memory
  memory = readStorage()
  return memory
}

export function saveSession(session: AdminSession): void {
  memory = session
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session))
  } catch {
    // 隐私模式下 sessionStorage 不可用，仅保留内存态
  }
}

export function clearSession(): void {
  memory = null
  try {
    sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    // ignore
  }
}

export function getAccessToken(): string {
  return loadSession()?.access_token || ''
}

export function getRefreshToken(): string {
  return loadSession()?.refresh_token || ''
}

export function getAccount(): AdminAccount | null {
  return loadSession()?.account || null
}

export function getRole(): Role | null {
  const role = getAccount()?.role
  return role === 'admin' || role === 'support' ? role : null
}

export function isExpired(now = Date.now()): boolean {
  const session = loadSession()
  return !session || session.expires_at <= now
}
