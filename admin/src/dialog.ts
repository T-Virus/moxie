import { reactive } from 'vue'

/**
 * 全局确认弹窗状态（命令式调用）。
 * 用法：const ok = await confirm({ title, message, danger?: true, confirmText?: '删除' })
 */
export interface ConfirmOptions {
  title: string
  message: string
  confirmText?: string
  cancelText?: string
  danger?: boolean
}

export const confirmState = reactive<{
  open: boolean
  options: ConfirmOptions
}>({
  open: false,
  options: { title: '', message: '' },
})

let resolver: ((value: boolean) => void) | null = null

export function confirm(options: ConfirmOptions): Promise<boolean> {
  // 若已有确认框未关闭，先以“取消”结算，避免多个 resolver 悬挂
  if (resolver) resolver(false)
  confirmState.options = {
    confirmText: '确认',
    cancelText: '取消',
    danger: false,
    ...options,
  }
  confirmState.open = true
  return new Promise<boolean>((resolve) => {
    resolver = resolve
  })
}

export function resolveConfirm(value: boolean): void {
  confirmState.open = false
  const current = resolver
  resolver = null
  if (current) current(value)
}
