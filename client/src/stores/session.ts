import { reactive } from 'vue'
import type { Account } from '@/types'
import { readAccount, clearSession, getAccessToken } from '@/services/http'
import { fetchMe } from '@/services/authApi'

export const session = reactive({
  account: readAccount() as Account | null,
  loading: false,
  ready: false,
})

export function setAccount(account: Account | null): void {
  session.account = account
}

export function resetSession(): void {
  session.account = null
  clearSession()
}

/** 刷新页面后校验 token：失效则清空本地会话，不弹升全局错误。 */
export async function refreshSession(): Promise<void> {
  if (!getAccessToken()) {
    session.account = null
    session.ready = true
    return
  }
  session.loading = true
  try {
    session.account = await fetchMe()
  } catch {
    resetSession()
    session.account = null
  } finally {
    session.loading = false
    session.ready = true
  }
}
