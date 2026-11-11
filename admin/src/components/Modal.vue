<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import Icon from './Icon.vue'

withDefaults(defineProps<{
  title: string
  subtitle?: string
  size?: 'normal' | 'wide' | 'narrow'
}>(), { size: 'normal', subtitle: '' })

const emit = defineEmits<{ (e: 'close'): void }>()

function onKey(event: KeyboardEvent) {
  if (event.key === 'Escape') emit('close')
}

let previousOverflow = ''
onMounted(() => {
  previousOverflow = document.body.style.overflow
  document.body.style.overflow = 'hidden'
  window.addEventListener('keydown', onKey)
})
onUnmounted(() => {
  document.body.style.overflow = previousOverflow
  window.removeEventListener('keydown', onKey)
})
</script>

<template>
  <Teleport to="body">
    <div class="modal-overlay" @mousedown.self="$emit('close')">
      <div class="modal" :class="size">
        <div class="modal-head">
          <div>
            <h3>{{ title }}</h3>
            <p v-if="subtitle">{{ subtitle }}</p>
          </div>
          <button class="close" type="button" title="关闭" @click="$emit('close')">
            <Icon name="close" :size="18" />
          </button>
        </div>
        <div class="modal-body"><slot /></div>
        <div v-if="$slots.footer" class="modal-foot"><slot name="footer" /></div>
      </div>
    </div>
  </Teleport>
</template>
