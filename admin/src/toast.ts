import { reactive } from 'vue'

export interface ToastItem {
  id: number
  message: string
  kind: 'info' | 'error' | 'warn'
}

export const toasts = reactive<ToastItem[]>([])

let seq = 0

export function pushToast(message: string, kind: ToastItem['kind'] = 'info', timeout = 3600): void {
  const id = ++seq
  toasts.push({ id, message, kind })
  window.setTimeout(() => dismissToast(id), timeout)
}

export function dismissToast(id: number): void {
  const index = toasts.findIndex(item => item.id === id)
  if (index >= 0) toasts.splice(index, 1)
}
