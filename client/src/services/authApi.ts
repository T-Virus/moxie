import type { Account, AuthResponse } from '@/types'
import { apiFetch, clearSession, saveSession } from './http'

/** 与服务端 config.legal_terms_version 保持一致；升级后旧客户端会被 422 拦截并提示重新同意 */
export const LEGAL_VERSION = '2026-11-01'

export interface ConsentEntry {
  version: string
  accepted: boolean
}

export async function login(email: string, password: string): Promise<AuthResponse> {
  const data = await apiFetch<AuthResponse>('/auth/login', {
    method: 'POST',
    anonymous: true,
    body: JSON.stringify({ email, password }),
  })
  saveSession(data)
  return data
}

export async function register(
  email: string,
  password: string,
  consents: Record<string, ConsentEntry>,
): Promise<AuthResponse> {
  const data = await apiFetch<AuthResponse>('/auth/register', {
    method: 'POST',
    anonymous: true,
    body: JSON.stringify({ email, password, consents }),
  })
  saveSession(data)
  return data
}

export async function fetchMe(): Promise<Account> {
  return apiFetch<Account>('/auth/me')
}

export async function logout(): Promise<void> {
  try {
    await apiFetch('/auth/logout', { method: 'POST' })
  } catch {
    // 登出失败不影响本地会话清理
  } finally {
    clearSession()
  }
}

/** 401 时给出就近提示，避免用户只看到「请求失败」 */
export function authErrorMessage(status: number, code: string, message: string): string {
  if (status === 401) {
    if (code === 'invalid_credentials') return '账号或密码错误，请检查后重试'
    return '登录状态已失效，请重新登录'
  }
  if (status === 403) return '该账号已被停用，请联系客服'
  if (status === 409 || code === 'account_exists') return '该邮箱已注册，可直接登录'
  if (status === 429) return '操作过于频繁，请稍后再试'
  if (status === 422) return message || '提交内容不合法，请检查邮箱与密码'
  if (status === 0) return '无法连接服务端，请检查网络后重试'
  return message || '请求失败，请稍后重试'
}
