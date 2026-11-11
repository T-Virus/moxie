import { reactive } from 'vue'

export const denial = reactive({
  path: '',
  required: '',
  message: '',
})

export function setDenial(path: string, required: string): void {
  denial.path = path
  denial.required = required
  denial.message = `当前角色无权访问 ${path}（需要 ${required} 权限）`
}
