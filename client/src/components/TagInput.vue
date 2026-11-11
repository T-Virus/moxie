<template>
  <div class="tag-field">
    <div class="tag-field__box" :class="{ 'is-focus': focused }">
      <span v-for="(tag, index) in modelValue" :key="`${tag}-${index}`" class="tag-field__tag">
        {{ tag }}
        <button
          type="button"
          class="tag-field__remove"
          :aria-label="`移除 ${tag}`"
          @click="remove(index)"
        >
          ×
        </button>
      </span>
      <input
        v-model="draft"
        class="tag-field__input"
        type="text"
        :placeholder="modelValue.length ? '继续输入' : placeholder"
        @focus="focused = true"
        @blur="onBlur"
        @keydown.enter.prevent="commit"
        @keydown.backspace="onBackspace"
      />
    </div>
    <div v-if="presets.length" class="tag-field__presets">
      <button
        v-for="preset in unselected"
        :key="preset"
        type="button"
        class="tag-field__preset"
        @click="add(preset)"
      >
        + {{ preset }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

const props = withDefaults(
  defineProps<{
    modelValue: string[]
    presets?: string[]
    placeholder?: string
  }>(),
  {
    presets: () => [],
    placeholder: '输入后回车添加',
  },
)

const emit = defineEmits<{ (event: 'update:modelValue', value: string[]): void }>()

const draft = ref('')
const focused = ref(false)

const unselected = computed(() => props.presets.filter((item) => !props.modelValue.includes(item)))

function add(value: string): void {
  const text = value.trim()
  if (!text || props.modelValue.includes(text)) return
  emit('update:modelValue', [...props.modelValue, text])
}

function commit(): void {
  const parts = draft.value
    .split(/[、,，;；\n]/)
    .map((item) => item.trim())
    .filter(Boolean)
  if (!parts.length) return
  const next = [...props.modelValue]
  for (const part of parts) {
    if (!next.includes(part)) next.push(part)
  }
  emit('update:modelValue', next)
  draft.value = ''
}

function remove(index: number): void {
  const next = props.modelValue.slice()
  next.splice(index, 1)
  emit('update:modelValue', next)
}

function onBackspace(): void {
  if (draft.value || !props.modelValue.length) return
  remove(props.modelValue.length - 1)
}

function onBlur(): void {
  focused.value = false
  commit()
}
</script>

<style scoped>
.tag-field {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.tag-field__box {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  min-height: 40px;
  padding: 5px 8px;
  border: 1px solid var(--color-line-strong);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  transition: border-color var(--dur-fast) var(--ease), box-shadow var(--dur-fast) var(--ease);
}

.tag-field__box.is-focus {
  border-color: var(--color-brand);
  box-shadow: 0 0 0 3px rgba(13, 148, 136, 0.12);
}

.tag-field__tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 26px;
  padding: 0 8px;
  border-radius: var(--radius-pill);
  background: rgba(13, 148, 136, 0.1);
  color: var(--color-brand);
  font-size: 14px;
}

.tag-field__remove {
  display: grid;
  place-items: center;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  color: var(--color-brand);
  font-size: 15px;
  line-height: 1;
}

.tag-field__remove:hover {
  background: rgba(13, 148, 136, 0.18);
}

.tag-field__input {
  flex: 1;
  min-width: 120px;
  height: 28px;
  border: none;
  background: transparent;
  font-size: 14px;
}

.tag-field__input:focus {
  outline: none;
}

.tag-field__input::placeholder {
  color: var(--color-text-3);
}

.tag-field__presets {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tag-field__preset {
  height: 26px;
  padding: 0 9px;
  border: 1px dashed var(--color-line-strong);
  border-radius: var(--radius-pill);
  color: var(--color-text-3);
  font-size: 13px;
}

.tag-field__preset:hover {
  border-color: var(--color-brand);
  color: var(--color-brand);
}
</style>
