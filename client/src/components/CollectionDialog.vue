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

          <TagInput
            v-if="field.type === 'tags'"
            v-model="form[field.key]"
            :presets="field.presets || []"
            :placeholder="field.placeholder || '输入后回车添加'"
          />
          <textarea
            v-else-if="field.type === 'textarea'"
            v-model="form[field.key]"
            class="input"
            :rows="field.rows || 3"
            :maxlength="field.maxlength || undefined"
            :placeholder="field.placeholder || ''"
          />
          <template v-else-if="field.type === 'select'">
            <select
              v-if="field.options?.length"
              v-model="form[field.key]"
              class="input"
            >
              <option value="">— 不指定 —</option>
              <option
                v-for="opt in field.options"
                :key="opt.value"
                :value="opt.value"
              >
                {{ opt.label }}
              </option>
            </select>
            <template v-else>
              <input
                v-model="form[field.key]"
                class="input"
                :placeholder="field.placeholder || ''"
              />
              <div v-if="field.presets?.length" class="collect-form__presets">
                <button
                  v-for="preset in field.presets"
                  :key="preset"
                  type="button"
                  class="collect-form__pill"
                  :class="{ 'is-active': form[field.key] === preset }"
                  @click="form[field.key] = form[field.key] === preset ? '' : preset"
                >
                  {{ preset }}
                </button>
              </div>
            </template>
          </template>
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
import TagInput from '@/components/TagInput.vue'
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
        form[field.key] = Array.isArray(raw) ? raw.map((item) => String(item)) : []
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
        .map((item) => String(item).trim())
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
  gap: 14px;
}

.collect-form__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 14px;
}

.collect-form__field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.collect-form__field--full {
  grid-column: 1 / -1;
}

.collect-form__label {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-2);
}

.collect-form__label i {
  margin-left: 2px;
  font-style: normal;
  color: var(--color-danger);
}

.collect-form__presets {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.collect-form__pill {
  height: 26px;
  padding: 0 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid transparent;
  border-radius: var(--radius-pill);
  background: var(--color-bg-soft);
  color: var(--color-text-2);
  font-size: 13px;
  font-family: inherit;
  white-space: nowrap;
}

.collect-form__pill:hover {
  color: var(--color-brand);
}

.collect-form__pill.is-active {
  border-color: var(--color-brand);
  background: rgba(13, 148, 136, 0.1);
  color: var(--color-brand);
  font-weight: 600;
}

.collect-form__hint {
  font-size: 12px;
  color: var(--color-text-3);
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
