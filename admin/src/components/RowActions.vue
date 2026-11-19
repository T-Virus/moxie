<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

export interface RowAction {
  label: string
  tone?: 'default' | 'danger' | 'primary'
  disabled?: boolean
  run: () => void
}

const props = defineProps<{ actions: RowAction[]; label?: string }>()
const open = ref(false)
const trigger = ref<HTMLElement | null>(null)
const menuStyle = ref<Record<string, string>>({})

function placeMenu() {
  const el = trigger.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  const width = 132
  const estimatedHeight = Math.min(props.actions.length, 8) * 32 + 8
  const left = Math.max(8, Math.min(rect.left + rect.width / 2 - width / 2, window.innerWidth - width - 8))
  const below = rect.bottom + 4
  const top = below + estimatedHeight > window.innerHeight ? Math.max(8, rect.top - estimatedHeight - 4) : below
  menuStyle.value = {
    position: 'fixed',
    left: `${left}px`,
    top: `${top}px`,
    width: `${width}px`,
  }
}

async function toggle() {
  open.value = !open.value
  if (open.value) {
    await nextTick()
    placeMenu()
  }
}
function close() { open.value = false }
function onDocClick(event: MouseEvent) {
  const target = event.target as Node
  if (trigger.value && trigger.value.contains(target)) return
  close()
}
function onScroll() { if (open.value) close() }
onMounted(() => {
  document.addEventListener('click', onDocClick)
  window.addEventListener('scroll', onScroll, true)
  window.addEventListener('resize', onScroll)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick)
  window.removeEventListener('scroll', onScroll, true)
  window.removeEventListener('resize', onScroll)
})

function invoke(action: RowAction) {
  if (action.disabled) return
  close()
  action.run()
}
</script>

<template>
  <span class="row-actions-wrap">
    <button ref="trigger" class="row-actions" type="button" :aria-expanded="open" @click.stop="toggle">
      <span>{{ label || '更多' }}</span>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M6 9l6 6 6-6" />
      </svg>
    </button>
    <Teleport to="body">
      <div v-if="open" class="row-actions__menu" :style="menuStyle" @click.stop>
        <button
          v-for="(action, index) in actions"
          :key="index"
          type="button"
          class="row-actions__item"
          :class="`is-${action.tone || 'default'}`"
          :disabled="action.disabled"
          @click="invoke(action)"
        >{{ action.label }}</button>
      </div>
    </Teleport>
  </span>
</template>

<style scoped>
.row-actions-wrap { display: inline-flex; }
.row-actions {
  display: inline-flex; align-items: center; justify-content: center; gap: 3px;
  height: 28px; padding: 0 6px; border: none; border-radius: 6px;
  background: transparent; color: var(--primary); font-size: 12px; white-space: nowrap;
  transition: background .12s, color .12s;
}
.row-actions:hover { background: var(--primary-bg); color: var(--primary-hover); }
.row-actions svg { width: 12px; height: 12px; opacity: .8; }
</style>

<style>
.row-actions__menu {
  z-index: 2000; padding: 4px; display: flex; flex-direction: column; gap: 1px;
  background: #fff; border: 1px solid var(--border); border-radius: 9px; box-shadow: var(--shadow-lg);
  animation: pop .12s ease;
}
.row-actions__item {
  width: 100%; height: 32px; padding: 0 12px; border: none; border-radius: 6px; background: none;
  color: var(--text-2); font-size: 12px; text-align: left; white-space: nowrap;
}
.row-actions__item:hover { background: #f3f7f6; color: var(--text); }
.row-actions__item.is-danger { color: var(--red); }
.row-actions__item.is-danger:hover { background: var(--red-bg); }
.row-actions__item.is-primary { color: var(--primary); font-weight: 600; }
.row-actions__item.is-primary:hover { background: var(--primary-soft); }
.row-actions__item:disabled { opacity: .45; cursor: not-allowed; }
</style>
