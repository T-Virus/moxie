<template>
  <div class="segmented" role="tablist" aria-label="写作模式">
    <button
      v-for="tab in tabs"
      :key="tab.id"
      class="segmented__item"
      :class="{ 'is-active': tab.id === modelValue }"
      type="button"
      role="tab"
      :aria-selected="tab.id === modelValue"
      :data-mode="tab.id"
      @click="select(tab.id)"
      @keydown="onKeydown($event, tab.id)"
    >
      {{ tab.label }}
    </button>
  </div>
</template>

<script setup lang="ts">
export interface SegmentedTab {
  id: string
  label: string
}

const props = defineProps<{
  tabs: SegmentedTab[]
  modelValue: string
}>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: string): void
}>()

function select(id: string): void {
  emit('update:modelValue', id)
}

function onKeydown(event: KeyboardEvent, id: string): void {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
  event.preventDefault()
  const index = props.tabs.findIndex((tab) => tab.id === id)
  const delta = event.key === 'ArrowRight' ? 1 : -1
  const next = props.tabs[(index + delta + props.tabs.length) % props.tabs.length]
  if (next) {
    emit('update:modelValue', next.id)
    const target = (event.currentTarget as HTMLElement).parentElement?.querySelector<HTMLElement>(
      `[data-mode="${next.id}"]`,
    )
    target?.focus()
  }
}
</script>

<style scoped>
.segmented {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 4px;
  border-radius: var(--radius-pill);
  background: #f1f2f4;
  border: 1px solid #eceef1;
}

.segmented__item {
  padding: 9px 22px;
  border-radius: var(--radius-pill);
  color: #6b7280;
  font-size: var(--text-sm);
  font-weight: 500;
  white-space: nowrap;
  transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease),
    box-shadow var(--dur-fast) var(--ease);
}

.segmented__item:hover {
  color: var(--color-text);
}

.segmented__item.is-active {
  background: #fff;
  color: var(--color-text);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(15, 23, 32, 0.08), 0 4px 12px -6px rgba(15, 23, 32, 0.18);
}

@media (max-width: 560px) {
  .segmented__item {
    padding: 9px 14px;
    font-size: var(--text-xs);
  }
}
</style>
