<script setup lang="ts">
export interface UiSegmentedOption {
  value: string | number
  label: string
  count?: number | string | null
}

type SegmentValue = string | number

withDefaults(defineProps<{
  modelValue: SegmentValue
  options: UiSegmentedOption[]
  size?: 'sm' | 'md'
  variant?: 'tabs' | 'chip'
}>(), {
  size: 'sm',
  variant: 'tabs',
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: SegmentValue): void
  (e: 'change', value: SegmentValue): void
}>()

function select(value: SegmentValue) {
  emit('update:modelValue', value)
  emit('change', value)
}
</script>

<template>
  <div class="ui-segmented" :class="[`ui-segmented--${size}`, `ui-segmented--${variant}`]" role="tablist">
    <button
      v-for="item in options"
      :key="String(item.value)"
      type="button"
      role="tab"
      :aria-selected="modelValue === item.value"
      :class="{ active: modelValue === item.value }"
      @click="select(item.value)"
    >
      <span>{{ item.label }}</span>
      <span v-if="item.count !== undefined && item.count !== null" class="count">{{ item.count }}</span>
    </button>
  </div>
</template>
