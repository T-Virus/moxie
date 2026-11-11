<template>
  <Teleport to="body">
    <Transition name="dialog">
      <div v-if="open" class="dialog__mask" @click.self="close">
        <div class="dialog" :class="`dialog--${size}`" role="dialog" aria-modal="true" :aria-label="title">
          <header class="dialog__head">
            <h2 class="dialog__title">{{ title }}</h2>
            <button ref="closeBtn" type="button" class="dialog__close" aria-label="关闭弹窗" @click="close">
              <svg viewBox="0 0 14 14" aria-hidden="true">
                <path d="M3 3l8 8M11 3l-8 8" fill="none" stroke="currentColor" stroke-width="1.4" />
              </svg>
            </button>
          </header>
          <div class="dialog__body">
            <slot />
          </div>
          <footer v-if="$slots.footer" class="dialog__footer">
            <slot name="footer" />
          </footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { lockPageScroll, unlockPageScroll } from '@/utils/scrollLock'

const props = withDefaults(
  defineProps<{
    open: boolean
    title: string
    /** 弹窗宽度：sm 确认框 / md 普通表单 / lg 多字段编辑 */
    size?: 'sm' | 'md' | 'lg'
  }>(),
  { size: 'md' },
)

const emit = defineEmits<{
  (event: 'close'): void
}>()

const closeBtn = ref<HTMLButtonElement | null>(null)
let pageLocked = false

/** 弹窗打开时锁定背景页面，关闭时恢复；只允许弹窗内容区自身滚动 */
function syncPageLock(open: boolean): void {
  if (open && !pageLocked) {
    pageLocked = true
    lockPageScroll()
  } else if (!open && pageLocked) {
    pageLocked = false
    unlockPageScroll()
  }
}

function close(): void {
  emit('close')
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && props.open) close()
}

watch(
  () => props.open,
  async (open) => {
    syncPageLock(open)
    if (!open) return
    await nextTick()
    closeBtn.value?.focus()
  },
  { immediate: true },
)

window.addEventListener('keydown', onKeydown)
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  syncPageLock(false)
})
</script>

<style scoped>
.dialog__mask {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-5);
  overflow: hidden;
  overscroll-behavior: contain;
  background: rgba(9, 16, 24, 0.45);
  backdrop-filter: blur(3px);
}

.dialog {
  width: 100%;
  max-width: 520px;
  max-height: calc(100dvh - 48px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--color-surface);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  border: 1px solid var(--color-line);
}

.dialog--sm {
  max-width: 420px;
}

.dialog--lg {
  max-width: 820px;
}

.dialog__head {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-5) var(--space-6) var(--space-3);
}

.dialog__title {
  font-size: var(--text-md);
  font-weight: 700;
}

.dialog__close {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  color: var(--color-text-3);
}

.dialog__close:hover {
  background: var(--color-bg-soft);
  color: var(--color-text);
}

.dialog__close svg {
  width: 12px;
  height: 12px;
}

.dialog__body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 0 var(--space-6) var(--space-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.dialog__footer {
  flex: none;
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  padding: var(--space-4) var(--space-6);
  border-top: 1px solid var(--color-line);
  background: var(--color-bg-softer);
  border-radius: 0 0 var(--radius-lg) var(--radius-lg);
}

.dialog-enter-active,
.dialog-leave-active {
  transition: opacity var(--dur) var(--ease);
}

.dialog-enter-active .dialog,
.dialog-leave-active .dialog {
  transition: transform var(--dur) var(--ease);
}

.dialog-enter-from,
.dialog-leave-to {
  opacity: 0;
}

.dialog-enter-from .dialog,
.dialog-leave-to .dialog {
  transform: translateY(10px) scale(0.98);
}
</style>
