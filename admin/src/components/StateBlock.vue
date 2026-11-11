<script setup lang="ts">
import { computed } from 'vue'
import Icon from './Icon.vue'

const props = withDefaults(defineProps<{
  kind?: 'loading' | 'empty' | 'error' | 'notready'
  title?: string
  message?: string
  endpoint?: string
  retryLabel?: string
}>(), { kind: 'empty', retryLabel: '' })

defineEmits<{ (e: 'retry'): void }>()

const defaults = {
  loading: { title: '正在加载…', icon: '' },
  empty: { title: '暂无数据', icon: 'info' },
  error: { title: '加载失败', icon: 'warning' },
  notready: { title: '接口未就绪', icon: 'link' },
}
const meta = computed(() => defaults[props.kind])
const titleText = computed(() => props.title || meta.value.title)
</script>

<template>
  <div class="state" :class="kind">
    <div class="state-icon">
      <span v-if="kind === 'loading'" class="spinner"></span>
      <Icon v-else :name="meta.icon" :size="20" />
    </div>
    <div class="state-title">{{ titleText }}</div>
    <div v-if="message" class="state-msg">{{ message }}</div>
    <div v-if="endpoint" class="endpoint">{{ endpoint }}</div>
    <div v-if="retryLabel || $slots.default" class="state-actions">
      <button v-if="retryLabel" class="btn ghost sm" @click="$emit('retry')">{{ retryLabel }}</button>
      <slot />
    </div>
  </div>
</template>
