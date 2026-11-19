import type { Account, AuthResponse } from '@/types'
import { apiFetch, clearSession, saveSession } from './http'

/** 与服务端 config.legal_terms_version 保持一致；升级后旧客户端会被 422 拦截并提示重新同意 */
export const LEGAL_VERSION = '2026-11-18'

export interface ConsentEntry {
  version: string
  accepted: boolean
}

export async function login(email: string, password: string): Promise<AuthResponse> {
  const data = await apiFetch<AuthResponse>('/auth/login', {
    method: 'POST',
    anonymous: true,
    // source=client：服务端硬隔离，管理账号即使密码正确也无法登录用户端。
    body: JSON.stringify({ email, password, source: 'client' }),
  })
  saveSession(data)
  return data
}

export interface PendingVerification {
  status: 'pending_verification'
  email: string
  message: string
  verify_url?: string
}

export type RegisterResult = AuthResponse | PendingVerification

export async function register(
  email: string,
  password: string,
  consents: Record<string, ConsentEntry>,
): Promise<RegisterResult> {
  const data = await apiFetch<RegisterResult>('/auth/register', {
    method: 'POST',
    anonymous: true,
    body: JSON.stringify({ email, password, consents }),
  })
  // 仅当服务端直接返回了 token（邮箱已验证/免验证）才落库会话；待验证时不登录
  if (data && 'access_token' in data && data.access_token) saveSession(data)
  return data
}

export async function verifyEmail(token: string): Promise<AuthResponse> {
  const data = await apiFetch<AuthResponse>('/auth/verify-email', {
    method: 'POST',
    anonymous: true,
    body: JSON.stringify({ token }),
  })
  saveSession(data)
  return data
}

export async function resendVerification(email: string): Promise<PendingVerification> {
  return apiFetch<PendingVerification>('/auth/resend-verification', {
    method: 'POST',
    anonymous: true,
    body: JSON.stringify({ email }),
  })
}

export interface ForgotPasswordResult {
  status: string
  email: string
  message: string
  /** 开发环境未配置 SMTP 时回传，便于本地完成重置 */
  reset_url?: string
}

/** 申请重置密码邮件：无论邮箱是否注册，后端返回同一文案 */
export async function forgotPassword(email: string): Promise<ForgotPasswordResult> {
  return apiFetch<ForgotPasswordResult>('/auth/forgot-password', {
    method: 'POST',
    anonymous: true,
    body: JSON.stringify({ email }),
  })
}

export interface PasswordActionResult {
  ok: boolean
  message: string
  revoked_sessions?: number
}

export async function resetPassword(token: string, newPassword: string): Promise<PasswordActionResult> {
  return apiFetch<PasswordActionResult>('/auth/reset-password', {
    method: 'POST',
    anonymous: true,
    body: JSON.stringify({ token, new_password: newPassword }),
  })
}

/** 登录态修改密码：成功后其它设备会被强制下线，当前设备保持登录 */
export async function changePassword(
  oldPassword: string,
  newPassword: string,
): Promise<PasswordActionResult> {
  return apiFetch<PasswordActionResult>('/auth/change-password', {
    method: 'POST',
    body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
  })
}

export async function fetchMe(): Promise<Account> {
  return apiFetch<Account>('/auth/me')
}

/** 账号注销申请：服务端返回宽限期与清除时间 */
export interface AccountDeletionRequestView {
  id: number
  account_id: number
  status: string
  reason: string | null
  requested_at: string
  purge_at: string
  cancelled_at: string | null
}

/** 导出本人全部个人数据（JSON），不含密码与令牌哈希 */
export function exportMyData(): Promise<Record<string, unknown>> {
  return apiFetch<Record<string, unknown>>('/me/export')
}

/** 提交账号注销申请：需密码与显式确认串；提交后会话立即撤销 */
export function requestAccountDeletion(password: string): Promise<AccountDeletionRequestView> {
  return apiFetch<AccountDeletionRequestView>('/me/delete', {
    method: 'POST',
    body: JSON.stringify({ password, confirmation: 'DELETE_MY_ACCOUNT' }),
  })
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
  // 先按后端语义码精确匹配：already_verified(409) / token_expired(410) 曾与
  // 400/409 的状态码分支错配，导致提示文案与后端语义不符。
  if (code === 'account_exists') return '该邮箱已注册，可直接登录'
  if (code === 'already_verified') return '该邮箱已验证，请直接登录'
  if (code === 'token_expired') return '链接已过期，请重新申请'
  if (code === 'token_used') return '重置链接已使用，请重新申请'
  if (code === 'invalid_token') return '链接无效或已使用，请重新申请'
  if (code === 'invalid_password') return '当前密码不正确'
  if (code === 'same_password') return '新密码不能与当前密码相同'
  if (code === 'too_frequent') return '操作过于频繁，请稍后再试'
  if (code === 'portal_forbidden') return message || '该账号请前往对应的入口登录'
  if (status === 401) {
    if (code === 'invalid_credentials') return '账号或密码错误，请检查后重试'
    return '登录状态已失效，请重新登录'
  }
  if (status === 403) {
    if (code === 'email_not_verified') return '账号邮箱尚未验证，请先查收验证邮件完成验证'
    return '该账号已被停用，请联系客服'
  }
  if (status === 409) return '该邮箱已注册，可直接登录'
  if (status === 400) return message || '请求参数不合法，请检查后重试'
  if (status === 410) return message || '验证链接已过期，请重新获取验证邮件'
  if (status === 429) return '操作过于频繁，请稍后再试'
  if (status === 422) return message || '提交内容不合法，请检查邮箱与密码'
  if (status === 0) return '无法连接服务端，请检查网络后重试'
  return message || '请求失败，请稍后重试'
}
