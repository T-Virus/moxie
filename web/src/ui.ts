import { reactive } from 'vue'
import { api } from './api'

export interface ToastItem { id: number; msg: string; type: string }
export const ui = reactive({
  settingsOpen: false,
  /* 移动端侧边栏抽屉开关（≤1024px 生效，桌面端恒为静态侧栏） */
  menuOpen: false,
  toasts: [] as ToastItem[],
})

let _id = 0
export function toast(msg: string, type = '') {
  const t: ToastItem = { id: ++_id, msg, type }
  ui.toasts.push(t)
  setTimeout(() => {
    const i = ui.toasts.findIndex(x => x.id === t.id)
    if (i >= 0) ui.toasts.splice(i, 1)
  }, 2600)
}

export function openSettings() { ui.menuOpen = false; ui.settingsOpen = true }

/** 复制文本：优先 Clipboard API；WebView 失焦或权限受限时退回 execCommand。 */
export async function copyText(text: string): Promise<boolean> {
  if (!text) return false
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch { /* 继续走兜底 */ }
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', '')
    ta.style.position = 'fixed'
    ta.style.top = '0'
    ta.style.left = '0'
    ta.style.opacity = '0'
    ta.style.pointerEvents = 'none'
    document.body.appendChild(ta)
    ta.focus()
    ta.select()
    ta.setSelectionRange(0, text.length)
    const ok = document.execCommand('copy')
    ta.remove()
    return ok
  } catch {
    return false
  }
}

// ---- 全局确认框 ----
export const confirmState = reactive({ open: false, msg: '', ok: '确定', danger: false })
let _confirmRes: ((v: boolean) => void) | null = null
export function confirmBox(msg: string, opts: { ok?: string; danger?: boolean } = {}): Promise<boolean> {
  confirmState.msg = msg
  confirmState.ok = opts.ok || '确定'
  confirmState.danger = !!opts.danger
  confirmState.open = true
  return new Promise(res => { _confirmRes = res })
}
export function resolveConfirm(v: boolean) {
  confirmState.open = false
  _confirmRes && _confirmRes(v)
}

// ---- 口令输入框（导出包加密 / 解密） ----
export const passwordState = reactive({
  open: false, title: '', msg: '', placeholder: '至少 6 位', value: '',
})
let _pwdRes: ((v: string | null) => void) | null = null
export function passwordBox(title: string, msg: string, placeholder = '至少 6 位'): Promise<string | null> {
  passwordState.title = title
  passwordState.msg = msg
  passwordState.placeholder = placeholder
  passwordState.value = ''
  passwordState.open = true
  return new Promise(res => { _pwdRes = res })
}
export function resolvePassword(v: string | null) {
  passwordState.open = false
  const fn = _pwdRes
  _pwdRes = null
  fn && fn(v)
}

// ---- 文件预览 ----
// truncated/size 由后端给出：超大报告只回前一段内容，避免整段文本塞进 DOM 卡死页面
export const previewState = reactive({
  open: false, name: '', path: '', content: '', html: false, loading: false,
  truncated: false, size: 0,
})
export async function openFilePreview(path: string, name: string) {
  previewState.open = true
  previewState.name = name
  previewState.path = path
  previewState.loading = true
  previewState.html = /\.html?$/i.test(name)
  previewState.truncated = false
  previewState.size = 0
  try {
    const r = await api.getOutput(path)
    previewState.content = r.content
    previewState.truncated = !!r.truncated
    previewState.size = r.size || 0
  } catch (e: any) {
    previewState.content = '[读取失败] ' + (e.message || e)
  } finally {
    previewState.loading = false
  }
}
