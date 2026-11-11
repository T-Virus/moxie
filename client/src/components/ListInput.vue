<template>
  <div class="list-field">
    <div class="list-field__rows">
      <div v-for="(item, index) in modelValue" :key="index" class="list-field__row">
        <span class="list-field__no">{{ String(index + 1).padStart(2, '0') }}</span>
        <input
          :value="item"
          class="list-field__input"
          type="text"
          :placeholder="placeholder"
          @input="update(index, ($event.target as HTMLInputElement).value)"
        />
        <button
          type="button"
          class="list-field__remove"
          title="删除该条目"
          aria-label="删除该条目"
          @click="remove(index)"
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path d="M3 6h18" />
            <path d="M8 6V4h8v2" />
            <path d="M6 6l1 15h10l1-15" />
          </svg>
        </button>
      </div>
    </div>
    <button type="button" class="list-field__add" @click="add">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
        <path d="M12 5v14M5 12h14" stroke-linecap="round" />
      </svg>
      {{ addLabel }}
    </button>
    <p v-if="hint" class="list-field__hint">{{ hint }}</p>
  </div>
</template>

<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    modelValue: string[]
    placeholder?: string
    addLabel?: string
    hint?: string
  }>(),
  {
    placeholder: '输入内容',
    addLabel: '添加一条',
    hint: '',
  },
)

const emit = defineEmits<{ (event: 'update:modelValue', value: string[]): void }>()

function update(index: number, value: string): void {
  const next = props.modelValue.slice()
  next[index] = value
  emit('update:modelValue', next)
}

function add(): void {
  emit('update:modelValue', [...props.modelValue, ''])
}

function remove(index: number): void {
  const next = props.modelValue.slice()
  next.splice(index, 1)
  emit('update:modelValue', next)
}
</script>

<style scoped>
.list-field {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-md);
  background: var(--color-surface);
}

.list-field__rows {
  max-height: 420px;
  overflow-y: auto;
  scrollbar-width: thin;
}

.list-field__rows::-webkit-scrollbar {
  width: 6px;
}

.list-field__rows::-webkit-scrollbar-thumb {
  background: #d7dde5;
  border-radius: 8px;
}

.list-field__row {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 46px;
  padding: 0 8px 0 14px;
  border-bottom: 1px solid var(--color-line);
  transition: background var(--dur-fast) var(--ease);
}

.list-field__row:hover,
.list-field__row:focus-within {
  background: var(--color-bg-softer);
}

.list-field__no {
  flex: none;
  width: 22px;
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--color-text-3);
}

.list-field__input {
  flex: 1;
  min-width: 0;
  height: 44px;
  border: none;
  background: transparent;
  color: var(--color-text);
  font-size: 14px;
}

.list-field__input:focus {
  outline: none;
}

.list-field__input::placeholder {
  color: var(--color-text-3);
}

.list-field__remove {
  flex: none;
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  color: var(--color-text-3);
  opacity: 0;
  transition: opacity var(--dur-fast) var(--ease), background var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease);
}

.list-field__row:hover .list-field__remove,
.list-field__row:focus-within .list-field__remove {
  opacity: 1;
}

.list-field__remove:hover {
  background: var(--color-danger-soft);
  color: var(--color-danger);
}

.list-field__remove svg {
  width: 14px;
  height: 14px;
}

.list-field__add {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  height: 42px;
  padding: 0 14px;
  color: var(--color-brand);
  font-size: 14px;
  text-align: left;
}

.list-field__add:hover {
  background: rgba(13, 148, 136, 0.06);
}

.list-field__add svg {
  width: 14px;
  height: 14px;
}

.list-field__hint {
  margin: 0;
  padding: 0 14px 10px;
  font-size: 13px;
  color: var(--color-text-3);
}
</style>
