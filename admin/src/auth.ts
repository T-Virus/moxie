import { api, setRefreshHandler, setUnauthorizedHandler } from './api'
import { clearSession, getAccessToken, getRefreshToken, loadSession, saveSession } from './session'
import type { AdminSession } from './types'

let refreshPromise: Promise<boolean> | null = null
let timer: number | null = null
let sessionLost: (() => void) | null = null
let loginNotice = ''

export function setSessionLostHandler(handler: () => void): void {
  sessionLost = handler
}

export function consumeLoginNotice(): string {
  const text = loginNotice
  loginNotice = ''
  return text
}

export function notifyLoginNotice(text: string): void {
  loginNotice = text
}

function scheduleRefresh(): void {
  if (timer !== null) window.clearTimeout(timer)
  const session = loadSession()
  if (!session) return
  const delay = Math.max(session.expires_at - Date.now() - 60_000, 0)
  timer = window.setTimeout(() => {
    void refreshAccessToken()
  }, delay)
}

export async function login(identity: string, password: string): Promise<AdminSession> {
  const response = await api.login(identity, password)
  if (response.account?.role !== 'admin' && response.account?.role !== 'support') {
    throw new Error('该账号没有管理后台权限（仅允许 admin / support 角色）')
  }
  const session: AdminSession = {
    access_token: response.access_token,
    refresh_token: response.refresh_token,
    expires_at: Date.now() + response.expires_in * 1000,
    account: response.account,
  }
  saveSession(session)
  scheduleRefresh()
  return session
}

export async function refreshAccessToken(): Promise<boolean> {
  if (refreshPromise) return refreshPromise
  const refreshToken = getRefreshToken()
  if (!refreshToken) {
    handleSessionLost('登录状态已失效，请重新登录')
    return false
  }
  refreshPromise = (async () => {
    try {
      const response = await api.refresh(refreshToken)
      const session: AdminSession = {
        access_token: response.access_token,
        refresh_token: response.refresh_token,
        expires_at: Date.now() + response.expires_in * 1000,
        account: response.account,
      }
      saveSession(session)
      scheduleRefresh()
      return true
    } catch {
      handleSessionLost('登录已过期，请重新登录')
      return false
    } finally {
      refreshPromise = null
    }
  })()
  return refreshPromise
}

export async function ensureSession(): Promise<boolean> {
  const session = loadSession()
  if (!session) return false
  if (session.expires_at - Date.now() < 30_000) {
    return refreshAccessToken()
  }
  return true
}

export async function logout(): Promise<void> {
  if (timer !== null) {
    window.clearTimeout(timer)
    timer = null
  }
  if (getAccessToken()) {
    try {
      await api.logout()
    } catch {
      // 本地退出始终成功；服务端会话不可达时忽略
    }
  }
  clearSession()
}

function handleSessionLost(message: string): void {
  if (timer !== null) {
    window.clearTimeout(timer)
    timer = null
  }
  clearSession()
  notifyLoginNotice(message)
  sessionLost?.()
}

setRefreshHandler(refreshAccessToken)
setUnauthorizedHandler(() => handleSessionLost('登录状态已失效，请重新登录'))
