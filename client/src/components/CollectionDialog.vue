<template>
  <AppDialog :open="open" :title="title" size="lg" @close="close">
    <form class="collect-form" novalidate @submit.prevent>
      <div class="collect-form__grid">
        <div
          v-for="field in fields"
          :key="field.key"
          class="collect-form__field"
          :class="{
            'collect-form__field--full':
              field.full || field.type === 'textarea' || field.type === 'tags',
          }"
        >
          <span class="collect-form__label">
            {{ field.label }}
            <i v-if="field.required">*</i>
          </span>

          <!-- 多选：标签类字段（角色/势力/道具/章节的关联项）统一用可搜索、可自定义、支持虚拟滚动的下拉 -->
          <Combobox
            v-if="field.type === 'tags'"
            v-model="form[field.key]"
            :options="tagsOptions(field)"
            :multiple="true"
            :placeholder="field.placeholder || '搜索选择或输入，回车添加'"
            :allow-create="field.allowCreate ?? true"
            :preset-type="field.presetType"
          />
          <!-- 单选：标签类字段（大类/类型/立场/阵营/归属卷等）同样可搜索、可自定义、可清空 -->
          <Combobox
            v-else-if="field.type === 'select'"
            v-model="form[field.key]"
            :options="selectOptions(field)"
            :multiple="false"
            :clearable="true"
            :placeholder="field.placeholder || '请选择或输入'"
            :allow-create="field.allowCreate ?? true"
            :preset-type="field.presetType"
          />
          <textarea
            v-else-if="field.type === 'textarea'"
            v-model="form[field.key]"
            class="input collect-form__area"
            :rows="field.rows || 3"
            :maxlength="field.maxlength || undefined"
            :placeholder="field.placeholder || ''"
          />
          <input
            v-else-if="field.type === 'number'"
            v-model.number="form[field.key]"
            class="input"
            type="number"
            :min="field.min ?? 0"
            :placeholder="field.placeholder || ''"
          />
          <input
            v-else
            v-model="form[field.key]"
            class="input"
            :placeholder="field.placeholder || ''"
            :maxlength="field.maxlength || undefined"
          />

          <span v-if="field.hint" class="collect-form__hint">{{ field.hint }}</span>
          <span v-if="errors[field.key]" class="collect-form__error">{{ errors[field.key] }}</span>
        </div>
      </div>

      <div v-if="localError" class="alert" role="alert">{{ localError }}</div>
      <div v-if="error" class="alert" role="alert">{{ error }}</div>
    </form>

    <template #footer>
      <button type="button" class="btn" :disabled="saving" @click="close">取消</button>
      <button type="button" class="btn btn--brand" :disabled="saving" @click="submit">
        {{ saving ? '保存中…' : '保存' }}
      </button>
    </template>
  </AppDialog>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import AppDialog from '@/components/AppDialog.vue'
import Combobox from '@/components/Combobox.vue'
import type { CollectionField } from '@/types'

const props = withDefaults(
  defineProps<{
    open: boolean
    title: string
    fields: CollectionField[]
    value: Record<string, any>
    saving?: boolean
    error?: string
  }>(),
  { saving: false, error: '' },
)

const emit = defineEmits<{
  (event: 'close'): void
  (event: 'save', value: Record<string, any>): void
}>()

/** select 字段的备选项：优先 options（带真实值），否则用 presets 文本构造 */
function selectOptions(field: CollectionField): Array<string | { value: string; label: string }> {
  if (field.options?.length) return field.options
  return (field.presets || []).map((p) => ({ value: String(p), label: String(p) }))
}

/** tags 字段的备选项：presets 文本作为可选项，同时允许自由输入新值 */
function tagsOptions(field: CollectionField): Array<string | { value: string; label: string }> {
  return (field.presets || []).map((p) => ({ value: String(p), label: String(p) }))
}

const form = reactive<Record<string, any>>({})
const errors = reactive<Record<string, string>>({})
const localError = ref('')

watch(
  () => [props.open, props.value] as const,
  ([open]) => {
    if (!open) return
    for (const field of props.fields) {
      const raw = props.value?.[field.key]
      if (field.type === 'tags') {
        form[field.key] = Array.isArray(raw) ? raw.map((item: any) => String(item)) : []
      } else if (field.type === 'number') {
        form[field.key] = typeof raw === 'number' && Number.isFinite(raw) ? raw : ''
      } else {
        form[field.key] = raw === null || raw === undefined ? '' : String(raw)
      }
      errors[field.key] = ''
    }
    localError.value = ''
  },
  { immediate: true, deep: true },
)

watch(
  () => form,
  () => {
    if (localError.value) localError.value = ''
  },
  { deep: true },
)

function close(): void {
  if (props.saving) return
  emit('close')
}

function submit(): void {
  if (props.saving) return
  let valid = true
  for (const field of props.fields) {
    const value = form[field.key]
    const empty =
      field.type === 'tags'
        ? !Array.isArray(value) || value.length === 0
        : field.type === 'number'
          ? typeof value !== 'number' || !Number.isFinite(value)
          : !String(value ?? '').trim()
    errors[field.key] = ''
    if (field.required && empty) {
      errors[field.key] = `请填写${field.label}`
      valid = false
      continue
    }
    if (field.type === 'number' && typeof value === 'number' && value < (field.min ?? 0)) {
      errors[field.key] = `${field.label}不能小于 ${field.min ?? 0}`
      valid = false
    }
  }
  if (!valid) {
    localError.value = '请先完善必填信息'
    return
  }

  const payload: Record<string, any> = {}
  for (const field of props.fields) {
    const value = form[field.key]
    if (field.type === 'tags') {
      payload[field.key] = (Array.isArray(value) ? value : [])
        .map((item: any) => String(item).trim())
        .filter(Boolean)
    } else if (field.type === 'number') {
      payload[field.key] = typeof value === 'number' ? value : undefined
    } else {
      payload[field.key] = String(value ?? '').trim()
    }
  }
  emit('save', payload)
}
</script>

<style scoped>
.collect-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.collect-form__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 16px;
}

.collect-form__field {
  display: flex;
  flex-direction: column;
  gap: 7px;
  min-width: 0;
}

.collect-form__field--full {
  grid-column: 1 / -1;
}

.collect-form__label {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-2);
  letter-spacing: 0.01em;
}

.collect-form__label i {
  margin-left: 3px;
  font-style: normal;
  color: var(--color-danger);
}

/* 原生文本/数字输入与 Combobox 外观对齐：统一圆角、聚焦高亮 */
.collect-form .input {
  width: 100%;
  height: 36px;
  padding: 5px 8px;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-md, 8px);
  background: #fff;
  font: inherit;
  font-size: 14px;
  color: var(--color-text);
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.collect-form .input::placeholder {
  color: var(--color-text-3);
}

.collect-form .input:hover {
  border-color: var(--color-line-strong, #c7ced6);
}

.collect-form .input:focus {
  border-color: var(--color-brand, #0d9488);
  box-shadow: 0 0 0 3px rgba(13, 148, 136, 0.12);
}

.collect-form__area {
  height: auto;
  padding: 9px 11px;
  line-height: 1.6;
  resize: vertical;
  min-height: 64px;
}

.collect-form__hint {
  font-size: 12px;
  color: var(--color-text-3);
  line-height: 1.5;
}

.collect-form__error {
  font-size: 12px;
  color: var(--color-danger);
}

@media (max-width: 640px) {
  .collect-form__grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
