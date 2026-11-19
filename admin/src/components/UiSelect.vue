<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

export interface UiSelectOption {
  value: string | number | boolean | null
  label: string
  disabled?: boolean
}

type SelectValue = string | number | boolean | null

const props = withDefaults(defineProps<{
  modelValue: SelectValue
  options: UiSelectOption[]
  placeholder?: string
  label?: string
  hint?: string
  size?: 'sm' | 'md'
  variant?: 'field' | 'toolbar' | 'plain'
  disabled?: boolean
  width?: string
}>(), {
  placeholder: '',
  label: '',
  hint: '',
  size: 'md',
  variant: 'field',
  disabled: false,
  width: '',
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: SelectValue): void
  (e: 'change', value: SelectValue): void
}>()

const hasField = computed(() => Boolean(props.label || props.hint))
const triggerStyle = computed(() => (props.width ? { width: props.width } : undefined))

function optionValue(value: SelectValue): string {
  if (value === null || value === undefined) return ''
  return String(value)
}

const currentValue = computed(() => optionValue(props.modelValue))

const items = computed<UiSelectOption[]>(() => {
  const list: UiSelectOption[] = []
  if (props.placeholder) list.push({ value: '', label: props.placeholder })
  return list.concat(props.options)
})

const selected = computed(() => items.value.find(item => optionValue(item.value) === currentValue.value))
const displayText = computed(() => (selected.value ? selected.value.label : props.placeholder))

const open = ref(false)
const activeIndex = ref(-1)
const root = ref<HTMLElement | null>(null)
const trigger = ref<HTMLElement | null>(null)
const menu = ref<HTMLElement | null>(null)
const menuStyle = ref<Record<string, string>>({})

function isSelected(item: UiSelectOption): boolean {
  return optionValue(item.value) === currentValue.value
}

function placeMenu() {
  const el = trigger.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  const width = Math.max(rect.width, 132)
  const estimated = Math.min(items.value.length, 8) * 33 + 10
  const left = Math.max(8, Math.min(rect.left, window.innerWidth - width - 8))
  const below = rect.bottom + 4
  const top = below + estimated > window.innerHeight ? Math.max(8, rect.top - estimated - 4) : below
  menuStyle.value = {
    position: 'fixed',
    left: `${left}px`,
    top: `${top}px`,
    width: `${width}px`,
    maxHeight: `${Math.min(estimated, window.innerHeight - 16)}px`,
  }
}

/**
 * 只滚动菜单自身，不用 scrollIntoView：
 * 后者会在菜单无需滚动时把整个页面滚一下，触发 window 的 scroll 监听，
 * 导致下拉刚打开就立刻被关掉（表现为「要点两次才弹出来」）。
 */
function scrollActiveIntoView() {
  const el = menu.value
  const item = el?.children[activeIndex.value] as HTMLElement | undefined
  if (!el || !item) return
  const top = item.offsetTop
  const bottom = top + item.offsetHeight
  if (top < el.scrollTop) el.scrollTop = top
  else if (bottom > el.scrollTop + el.clientHeight) el.scrollTop = bottom - el.clientHeight
}

async function openMenu() {
  if (props.disabled || open.value) return
  open.value = true
  const index = items.value.findIndex(item => isSelected(item))
  activeIndex.value = index >= 0 ? index : 0
  await nextTick()
  placeMenu()
  scrollActiveIntoView()
}

function close(focus = false) {
  if (!open.value) return
  open.value = false
  activeIndex.value = -1
  if (focus) trigger.value?.focus()
}

function toggle() {
  if (open.value) close()
  else void openMenu()
}

function pick(item: UiSelectOption) {
  if (item.disabled) return
  close(true)
  if (optionValue(item.value) === currentValue.value) return
  emit('update:modelValue', item.value)
  emit('change', item.value)
}

function moveActive(step: number) {
  const count = items.value.length
  if (!count) return
  let index = activeIndex.value
  for (let i = 0; i < count; i++) {
    index = index < 0 ? (step > 0 ? 0 : count - 1) : (index + step + count) % count
    if (!items.value[index]?.disabled) {
      activeIndex.value = index
      break
    }
  }
  scrollActiveIntoView()
}

function onKeydown(event: KeyboardEvent) {
  if (props.disabled) return
  if (event.key === 'Escape') {
    if (open.value) {
      event.preventDefault()
      close(true)
    }
    return
  }
  if (!open.value) {
    if (['Enter', ' ', 'ArrowDown', 'ArrowUp'].includes(event.key)) {
      event.preventDefault()
      void openMenu()
    }
    return
  }
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    moveActive(1)
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    moveActive(-1)
  } else if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    const item = items.value[activeIndex.value]
    if (item) pick(item)
  } else if (event.key === 'Tab') {
    close()
  }
}

function onDocClick(event: MouseEvent) {
  const target = event.target as Node
  if (root.value?.contains(target) || menu.value?.contains(target)) return
  close()
}

/** 页面滚动时收起菜单；菜单自身的滚动（选项过多）不该关闭它 */
function onViewportChange(event: Event) {
  if (!open.value) return
  const target = event.target
  if (target instanceof Node && (menu.value?.contains(target) || root.value?.contains(target))) return
  close()
}

onMounted(() => {
  document.addEventListener('click', onDocClick)
  window.addEventListener('scroll', onViewportChange, true)
  window.addEventListener('resize', onViewportChange)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick)
  window.removeEventListener('scroll', onViewportChange, true)
  window.removeEventListener('resize', onViewportChange)
})
</script>

<template>
  <span ref="root" class="ui-select-wrap" :class="{ 'has-field': hasField }">
    <span v-if="label" class="ui-select-label">{{ label }}</span>
    <div
      ref="trigger"
      class="ui-select"
      :class="[`ui-select--${size}`, `ui-select--${variant}`, { 'is-open': open, 'is-disabled': disabled }]"
      :style="triggerStyle"
      role="combobox"
      :tabindex="disabled ? -1 : 0"
      :aria-expanded="open"
      aria-haspopup="listbox"
      @click.stop="toggle"
      @keydown="onKeydown"
    >
      <span class="ui-select__text">{{ displayText }}</span>
    </div>
    <span v-if="hint" class="ui-select-hint">{{ hint }}</span>
    <Teleport to="body">
      <div v-if="open" ref="menu" class="ui-select__menu" :style="menuStyle" role="listbox">
        <button
          v-for="(item, index) in items"
          :key="optionValue(item.value)"
          type="button"
          class="ui-select__item"
          :class="{ 'is-active': index === activeIndex, 'is-selected': isSelected(item) }"
          role="option"
          :aria-selected="isSelected(item)"
          :disabled="item.disabled"
          @click.stop="pick(item)"
          @mouseenter="activeIndex = index"
        >{{ item.label }}</button>
      </div>
    </Teleport>
  </span>
</template>

<style scoped>
.ui-select-wrap {
  position: relative;
  display: inline-flex;
  flex-direction: column;
  min-width: 0;
}
.ui-select-wrap.has-field { gap: 6px; }
.ui-select {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  cursor: pointer;
  user-select: none;
}
.ui-select.is-disabled { background: #f6f8fa; color: var(--text-3); cursor: not-allowed; }
.ui-select.is-open { border-color: var(--primary); box-shadow: 0 0 0 3px rgba(15, 155, 142, .12); }
/* 选中文字左对齐，并与输入框保持相同的左内边距；右侧留出箭头位置 */
.ui-select-wrap .ui-select {
  padding-left: 10px !important;
  padding-right: 28px !important;
  text-align: left !important;
}
.ui-select__text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: left; }
.ui-select__menu {
  z-index: 2000;
  padding: 4px;
  display: flex;
  flex-direction: column;
  gap: 1px;
  overflow-y: auto;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 9px;
  box-shadow: var(--shadow-lg);
  animation: pop .12s ease;
}
.ui-select__item {
  width: 100%;
  height: 32px;
  flex: none;
  padding: 0 12px;
  border: none;
  border-radius: 6px;
  background: none;
  color: var(--text-2);
  font-size: 12px;
  text-align: left;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ui-select__item:hover,
.ui-select__item.is-active { background: #f3f7f6; color: var(--text); }
.ui-select__item.is-selected { color: var(--primary); font-weight: 600; background: var(--primary-bg); }
.ui-select__item:disabled { opacity: .45; cursor: not-allowed; }
</style>
