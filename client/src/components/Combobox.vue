<template>
  <div ref="rootEl" class="cb" :class="{ 'is-disabled': disabled, 'is-open': open }">
    <!-- 触发区：单选显示当前文本；多选显示 chips + 输入 -->
    <div
      ref="triggerEl"
      class="cb__control"
      :class="{ 'is-focus': open, 'is-empty': !values.length }"
      role="combobox"
      :aria-expanded="open"
      :aria-disabled="disabled"
      :aria-haspopup="'listbox'"
      tabindex="0"
      @click="toggleOpen"
      @keydown="onTriggerKey"
    >
      <template v-if="multiple">
        <span v-for="item in selectedItems" :key="item.value" class="cb__chip">
          <span class="cb__chip-label">{{ item.label }}</span>
          <button
            type="button"
            class="cb__chip-x"
            tabindex="-1"
            aria-label="移除"
            @click.stop="removeValue(item.value)"
          >
            <svg viewBox="0 0 10 10" width="9" height="9" aria-hidden="true">
              <path d="M1.5 1.5 L8.5 8.5 M8.5 1.5 L1.5 8.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
            </svg>
          </button>
        </span>
      </template>
      <!-- 单选未展开时用文本展示已选值；展开后 input 才用于搜索输入 -->
      <span
        v-if="!multiple && !open && values.length"
        class="cb__single-label"
      >{{ selectedItems[0]?.label }}</span>
      <input
        v-else
        ref="inputEl"
        v-model="query"
        class="cb__input"
        :class="{ 'cb__input--single': !multiple }"
        :placeholder="multiple && values.length ? '' : placeholder"
        :disabled="disabled"
        autocomplete="off"
        spellcheck="false"
        @click.stop="onInputClick"
        @keydown.stop="onInputKey"
      />
      <button
        v-if="clearable && !multiple && values.length"
        type="button"
        class="cb__clear"
        tabindex="-1"
        aria-label="清除"
        @click.stop="clear"
      >
        <svg viewBox="0 0 10 10" width="9" height="9" aria-hidden="true">
          <path d="M1.5 1.5 L8.5 8.5 M8.5 1.5 L1.5 8.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
        </svg>
      </button>
      <span class="cb__caret" aria-hidden="true">▾</span>
    </div>

    <Teleport to="body">
      <div
        v-if="open"
        class="cb__panel"
        :style="panelStyle"
        @mousedown.prevent
        @keydown="onPanelKey"
      >
        <div ref="listEl" class="cb__list" @scroll="onScroll">
          <div v-if="useVirtual" :style="{ height: totalHeight + 'px', position: 'relative' }">
            <div :style="{ transform: `translateY(${offsetY}px)`, position: 'absolute', left: 0, right: 0 }">
              <button
                v-for="opt in rendered"
                :key="opt.value"
                type="button"
                class="cb__opt"
                :class="{ 'is-active': isSelected(opt.value), 'is-highlight': highlight === opt._i }"
                @click="pick(opt)"
              >
                <span class="cb__opt-label">{{ opt.label }}</span>
                <span v-if="isSelected(opt.value)" class="cb__check">✓</span>
              </button>
            </div>
          </div>

          <template v-else>
            <button
              v-for="opt in visibleList"
              :key="opt.value"
              type="button"
              class="cb__opt"
              :class="{ 'is-active': isSelected(opt.value), 'is-highlight': highlight === opt._i }"
              @click="pick(opt)"
            >
              <span class="cb__opt-label">{{ opt.label }}</span>
              <span v-if="isSelected(opt.value)" class="cb__check">✓</span>
            </button>
          </template>

          <button
            v-if="showCreate"
            type="button"
            class="cb__opt cb__opt--create"
            :class="{ 'is-highlight': highlight === visibleList.length - 1 }"
            @click="createFromQuery"
          >
            <span class="cb__opt-label">{{ createLabel }}</span>
          </button>

          <div v-if="!visibleList.length && !showCreate" class="cb__empty">{{ emptyResolved }}</div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
  type CSSProperties,
} from 'vue'
import { createPreset } from '@/services/presets'

type RawOpt = string | { value: string; label?: string }
interface Opt {
  value: string
  label: string
  _i?: number
}

const props = withDefaults(
  defineProps<{
    /** 单选为 string；多选为 string[] */
    modelValue?: string | string[]
    multiple?: boolean
    /** 候选项：纯字符串或 {value,label}；留空则完全自由输入 */
    options?: RawOpt[]
    /** 允许输入不存在的值（自定义输入） */
    allowCreate?: boolean
    placeholder?: string
    disabled?: boolean
    emptyText?: string
    /** 选项超过此数启用虚拟滚动 */
    virtualThreshold?: number
    /** 自定义输入的提示文案，{0} 会被输入文本替换 */
    createText?: string
    /** 单选时显示清除按钮，允许把值重置为空 */
    clearable?: boolean
    /** 预设类型名：传入后，用户自定义输入会自动持久化为本人私有预设 */
    presetType?: string
  }>(),
  {
    modelValue: '',
    multiple: false,
    options: () => [],
    allowCreate: true,
    placeholder: '请选择',
    disabled: false,
    emptyText: '无匹配项',
    virtualThreshold: 50,
    createText: '使用「{0}」',
    clearable: false,
  },
)

const emit = defineEmits<{ (e: 'update:modelValue', value: string | string[]): void }>()

const rootEl = ref<HTMLElement | null>(null)
const triggerEl = ref<HTMLElement | null>(null)
const inputEl = ref<HTMLInputElement | null>(null)
const listEl = ref<HTMLElement | null>(null)

const open = ref(false)
const query = ref('')
const highlight = ref(0)
const scrollTop = ref(0)

const normOptions = computed<Opt[]>(() =>
  props.options.map((o) =>
    typeof o === 'string' ? { value: o, label: o } : { value: o.value, label: o.label ?? o.value },
  ),
)

const values = computed<string[]>(() => {
  if (props.multiple) {
    return Array.isArray(props.modelValue) ? props.modelValue.map(String) : []
  }
  return props.modelValue ? [String(props.modelValue)] : []
})

const selectedItems = computed<Opt[]>(() =>
  values.value.map((v) => normOptions.value.find((o) => o.value === v) || { value: v, label: v }),
)

const filtered = computed<Opt[]>(() => {
  const q = query.value.trim().toLowerCase()
  return normOptions.value.filter(
    (o) => !q || o.label.toLowerCase().includes(q) || o.value.toLowerCase().includes(q),
  )
})

const showCreate = computed(
  () =>
    props.allowCreate &&
    query.value.trim().length > 0 &&
    !normOptions.value.some((o) => o.value.toLowerCase() === query.value.trim().toLowerCase()),
)

const createLabel = computed(() => props.createText.replace('{0}', query.value.trim()))

/** 无候选且允许自定义时，给出可操作的引导文案而不是「无匹配项」 */
const emptyResolved = computed(() =>
  !normOptions.value.length && props.allowCreate ? '输入内容后回车即可创建' : props.emptyText,
)

const visibleList = computed<Opt[]>(() => {
  const list: Opt[] = filtered.value.map((o, i) => ({ ...o, _i: i }))
  if (showCreate.value) {
    list.push({ value: '__create__', label: createLabel.value, _i: list.length })
  }
  return list
})

/* 虚拟滚动：仅当候选项明显偏多时启用，避免大列表卡顿 */
const useVirtual = computed(() => normOptions.value.length > props.virtualThreshold)
const ITEM_H = 34
const PANEL_H = 264
const BUFFER = 6
const totalHeight = computed(() => visibleList.value.length * ITEM_H)
const startIndex = computed(() =>
  Math.max(0, Math.floor(scrollTop.value / ITEM_H) - BUFFER),
)
const endIndex = computed(() =>
  Math.min(visibleList.value.length, Math.ceil((scrollTop.value + PANEL_H) / ITEM_H) + BUFFER),
)
const offsetY = computed(() => startIndex.value * ITEM_H)
const rendered = computed(() => visibleList.value.slice(startIndex.value, endIndex.value))

const panelStyle = ref<CSSProperties>({})

function positionPanel(): void {
  const el = triggerEl.value
  if (!el) return
  const r = el.getBoundingClientRect()
  const spaceBelow = window.innerHeight - r.bottom
  const style: CSSProperties = {
    position: 'fixed',
    left: `${r.left}px`,
    width: `${Math.max(r.width, 220)}px`,
  }
  // 面板高度随内容自适应：空间够就贴在输入框下方；否则用 bottom 定位，
  // 让面板底边贴住输入框顶部、向上自然生长，避免固定高度算出「飘在半空」的偏移。
  if (spaceBelow >= 140 || spaceBelow >= r.top) {
    style.top = `${r.bottom + 6}px`
  } else {
    style.bottom = `${window.innerHeight - r.top + 6}px`
  }
  panelStyle.value = style
}

function openPanel(): void {
  if (props.disabled) return
  open.value = true
  query.value = ''
  scrollTop.value = 0
  highlight.value = 0
  positionPanel()
  window.addEventListener('scroll', positionPanel, true)
  window.addEventListener('resize', positionPanel)
  nextTick(() => {
    inputEl.value?.focus()
  })
}

function closePanel(): void {
  open.value = false
  window.removeEventListener('scroll', positionPanel, true)
  window.removeEventListener('resize', positionPanel)
}

function toggleOpen(): void {
  if (props.disabled) return
  if (open.value) closePanel()
  else openPanel()
}

function isSelected(value: string): boolean {
  return values.value.includes(value)
}

function emitValue(next: string[]): void {
  if (props.multiple) emit('update:modelValue', next)
  else emit('update:modelValue', next[0] ?? '')
}

function pick(opt: Opt): void {
  if (opt.value === '__create__') {
    createFromQuery()
    return
  }
  if (props.multiple) {
    const next = isSelected(opt.value)
      ? values.value.filter((v) => v !== opt.value)
      : [...values.value, opt.value]
    emitValue(next)
    query.value = ''
    highlight.value = 0
  } else {
    emitValue([opt.value])
    closePanel()
  }
}

function createFromQuery(): void {
  const text = query.value.trim()
  if (!text) return
  if (props.multiple) {
    const next = isSelected(text) ? values.value : [...values.value, text]
    emitValue(next)
    query.value = ''
    highlight.value = 0
  } else {
    emitValue([text])
  }
  // 用户自定义输入：持久化为本人私有预设（POST /v1/presets），下次打开即可复用。
  // 失败静默处理——本地已选中，不影响当前交互。
  if (props.presetType) {
    createPreset({ type: props.presetType, value: text }).catch(() => undefined)
  }
  if (!props.multiple) closePanel()
}

function removeValue(value: string): void {
  emitValue(values.value.filter((v) => v !== value))
}

function clear(): void {
  if (props.multiple) emitValue([])
  else emitValue([''])
}

// 搜索词变化时回到列表顶部并重置高亮（v-model 与程序赋值统一走这里）
watch(query, () => {
  highlight.value = 0
  scrollTop.value = 0
  if (listEl.value) listEl.value.scrollTop = 0
})

/**
 * 点击输入框：阻断冒泡，避免控件 click 把已打开的面板关掉
 * （mousedown 聚焦不会开面板，由这里统一负责打开，消除开/关竞态）
 */
function onInputClick(): void {
  if (!open.value) openPanel()
}

function onScroll(): void {
  if (listEl.value) scrollTop.value = listEl.value.scrollTop
}

function ensureHighlightVisible(): void {
  if (!useVirtual.value) return
  const top = highlight.value * ITEM_H
  const bottom = top + ITEM_H
  if (top < scrollTop.value) scrollTop.value = top
  else if (bottom > scrollTop.value + PANEL_H) scrollTop.value = bottom - PANEL_H
  if (listEl.value) listEl.value.scrollTop = scrollTop.value
}

function move(dir: number): void {
  const max = visibleList.value.length - 1
  if (max < 0) return
  highlight.value = Math.max(0, Math.min(max, highlight.value + dir))
  ensureHighlightVisible()
}

function onInputKey(e: KeyboardEvent): void {
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    if (!open.value) openPanel()
    else move(1)
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    move(-1)
  } else if (e.key === 'Enter') {
    e.preventDefault()
    const item = visibleList.value[highlight.value]
    if (item) pick(item)
    // 没有可选项时兜底：输入了内容就直接采纳为自定义值
    else if (props.allowCreate && query.value.trim()) createFromQuery()
  } else if (e.key === 'Escape') {
    e.preventDefault()
    closePanel()
  } else if (e.key === 'Backspace' && props.multiple && !query.value && values.value.length) {
    emitValue(values.value.slice(0, -1))
  }
}

function onTriggerKey(e: KeyboardEvent): void {
  if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(e.key)) {
    e.preventDefault()
    if (!open.value) openPanel()
    else move(e.key === 'ArrowUp' ? -1 : 1)
  } else if (e.key === 'Escape') {
    closePanel()
  }
}

function onPanelKey(e: KeyboardEvent): void {
  onInputKey(e)
}

function onDocClick(e: MouseEvent): void {
  if (!open.value) return
  const t = e.target as Node
  if (rootEl.value && !rootEl.value.contains(t) && !(t as HTMLElement).closest?.('.cb__panel')) {
    closePanel()
  }
}

onMounted(() => document.addEventListener('mousedown', onDocClick, true))
onBeforeUnmount(() => {
  document.removeEventListener('mousedown', onDocClick, true)
  window.removeEventListener('scroll', positionPanel, true)
  window.removeEventListener('resize', positionPanel)
})

watch(open, (v) => {
  if (!v) query.value = ''
})
</script>

<style scoped>
.cb {
  position: relative;
  width: 100%;
  font-family: inherit;
}

.cb__control {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  min-height: 36px;
  padding: 4px 44px 4px 10px;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-md, 8px);
  background: #fff;
  cursor: text;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.cb__control:hover {
  border-color: var(--color-line-strong, #c7ced6);
}

.cb__control.is-focus {
  border-color: var(--color-brand, #0d9488);
  box-shadow: 0 0 0 3px rgba(13, 148, 136, 0.12);
}

.cb.is-disabled .cb__control {
  background: var(--color-bg-softer, #f5f7fa);
  cursor: not-allowed;
  opacity: 0.7;
}

.cb__chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 100%;
  height: 24px;
  padding: 0 4px 0 9px;
  border-radius: 999px;
  background: var(--color-bg-soft, #eef1f5);
  color: var(--color-text, #2b313a);
  font-size: 13px;
  line-height: 1;
  white-space: nowrap;
}

/* 长标签截断省略，防止 chip 撑破输入框 */
.cb__chip-label {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cb__chip-x {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 16px;
  height: 16px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: var(--color-text-3, #8a94a3);
  line-height: 0;
  appearance: none;
  -webkit-appearance: none;
  cursor: pointer;
}

.cb__chip-x:hover {
  background: rgba(0, 0, 0, 0.08);
  color: var(--color-danger, #e03131);
}

.cb__input {
  flex: 1 1 60px;
  min-width: 60px;
  height: 26px;
  border: none;
  outline: none;
  background: transparent;
  font: inherit;
  font-size: 14px;
  color: var(--color-text, #2b313a);
}

.cb__input--single {
  flex: 1;
}

.cb__input::placeholder {
  color: var(--color-text-3, #8a94a3);
}

.cb__caret {
  position: absolute;
  right: 10px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 10px;
  color: var(--color-text-3, #8a94a3);
  pointer-events: none;
}

.cb__clear {
  position: absolute;
  right: 30px;
  top: 50%;
  transform: translateY(-50%);
  display: flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: var(--color-bg-soft, #eef1f5);
  color: var(--color-text-3, #8a94a3);
  line-height: 0;
  appearance: none;
  -webkit-appearance: none;
  cursor: pointer;
  z-index: 1;
}

.cb__clear:hover {
  background: rgba(0, 0, 0, 0.1);
  color: var(--color-danger, #e03131);
}

.cb__panel {
  z-index: 2000;
  background: #fff;
  border: 1px solid var(--color-line, #e2e6ec);
  border-radius: var(--radius-md, 8px);
  box-shadow: 0 12px 32px -12px rgba(15, 23, 42, 0.35);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.cb__single-label {
  flex: 1;
  min-width: 0;
  font-size: 14px;
  color: var(--color-text, #2b313a);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cb__list {
  max-height: 264px;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 4px;
  scrollbar-width: thin;
}

.cb__opt {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  height: 34px;
  padding: 0 10px;
  border: none;
  border-radius: var(--radius-sm, 6px);
  background: transparent;
  font: inherit;
  font-size: 14px;
  color: var(--color-text, #2b313a);
  text-align: left;
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cb__opt:hover,
.cb__opt.is-highlight {
  background: var(--color-bg-soft, #eef1f5);
}

.cb__opt.is-active {
  color: var(--color-brand, #0d9488);
  font-weight: 600;
}

.cb__opt--create {
  color: var(--color-brand, #0d9488);
}

.cb__check {
  flex: none;
  font-size: 13px;
}

.cb__empty {
  padding: 16px 12px;
  text-align: center;
  font-size: 13px;
  color: var(--color-text-3, #8a94a3);
}
</style>
