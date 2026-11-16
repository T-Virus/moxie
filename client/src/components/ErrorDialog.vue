<template>
  <AppDialog :open="open" :title="title" size="sm" @close="$emit('close')">
    <div class="error-dialog">
      <span class="error-dialog__icon" :class="`error-dialog__icon--${tone}`" aria-hidden="true">
        <svg v-if="tone === 'error' || tone === 'warn'" viewBox="0 0 24 24">
          <path d="M12 8.5v4.5M12 16.5v.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
          <circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="1.5" />
        </svg>
        <svg v-else-if="tone === 'success'" viewBox="0 0 24 24">
          <path d="m7.5 12.5 3 3 6-7" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
          <circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="1.5" />
        </svg>
        <svg v-else viewBox="0 0 24 24">
          <path d="M12 11v5M12 8v.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
          <circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="1.5" />
        </svg>
      </span>
      <div class="error-dialog__content">
        <p class="error-dialog__message" role="alert">{{ message }}</p>
        <p v-if="detail" class="error-dialog__detail">{{ detail }}</p>
      </div>
    </div>
    <template #footer>
      <button type="button" class="btn btn--brand" @click="$emit('close')">{{ confirmText }}</button>
    </template>
  </AppDialog>
</template>

<script setup lang="ts">
import AppDialog from '@/components/AppDialog.vue'

withDefaults(
  defineProps<{
    open: boolean
    message: string
    title?: string
    detail?: string
    tone?: 'error' | 'warn' | 'info' | 'success'
    confirmText?: string
  }>(),
  {
    title: '操作失败',
    detail: '',
    tone: 'error',
    confirmText: '知道了',
  },
)

defineEmits<{ (event: 'close'): void }>()
</script>

<style scoped>
.error-dialog {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-2) 0 var(--space-1);
}

.error-dialog__icon {
  flex: none;
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  margin-top: 1px;
  border-radius: 50%;
}

.error-dialog__icon svg {
  width: 18px;
  height: 18px;
}

.error-dialog__icon--error {
  color: var(--color-danger);
  background: var(--color-danger-soft);
}

.error-dialog__icon--warn {
  color: var(--color-warn);
  background: var(--color-warn-soft);
}

.error-dialog__icon--info {
  color: var(--color-brand);
  background: var(--color-bg-soft);
}

.error-dialog__icon--success {
  color: var(--color-success);
  background: var(--color-success-soft);
}

.error-dialog__content {
  min-width: 0;
}

.error-dialog__message {
  font-size: var(--text-base);
  font-weight: 600;
  line-height: 1.5;
  color: var(--color-text);
  word-break: break-word;
}

.error-dialog__detail {
  margin-top: var(--space-1);
  font-size: var(--text-xs);
  line-height: 1.6;
  color: var(--color-text-2);
  word-break: break-word;
}
</style>
