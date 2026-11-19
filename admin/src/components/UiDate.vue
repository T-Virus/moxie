<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import UiSelect from './UiSelect.vue'

type Mode = 'date' | 'datetime'

const props = withDefaults(defineProps<{
  modelValue: string
  mode?: Mode
  placeholder?: string
  disabled?: boolean
  clearable?: boolean
}>(), {
  mode: 'date',
  placeholder: '',
  disabled: false,
  clearable: true,
})

const emit = defineEmits<{ (e: 'update:modelValue', value: string): void }>()

const WEEK = ['一', '二', '三', '四', '五', '六', '日']
const HOURS = Array.from({ length: 24 }, (_, i) => pad(i))
const MINUTES = Array.from({ length: 60 }, (_, i) => pad(i))

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

function parse(value: string): Date | null {
  if (!value) return null
  const matched = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/.exec(value)
  if (!matched) return null
  const date = new Date(
    Number(matched[1]),
    Number(matched[2]) - 1,
    Number(matched[3]),
    Number(matched[4] || 0),
    Number(matched[5] || 0),
  )
  return Number.isNaN(date.getTime()) ? null : date
}

function format(date: Date): string {
  const day = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
  return props.mode === 'datetime' ? `${day}T${pad(date.getHours())}:${pad(date.getMinutes())}` : day
}

function sameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
}

const selected = computed(() => parse(props.modelValue))
const displayText = computed(() => {
  if (!props.modelValue) return ''
  return props.modelValue.replace('T', ' ')
})
const emptyText = computed(() => props.placeholder || (props.mode === 'datetime' ? '选择日期时间' : '选择日期'))

const open = ref(false)
const cursor = ref(new Date())
const root = ref<HTMLElement | null>(null)
const trigger = ref<HTMLElement | null>(null)
const panel = ref<HTMLElement | null>(null)
const panelStyle = ref<Record<string, string>>({})

const monthLabel = computed(() => `${cursor.value.getFullYear()} 年 ${cursor.value.getMonth() + 1} 月`)

/** 周一为一周第一天，固定渲染 6 行，避免面板高度随月份跳动 */
const cells = computed(() => {
  const year = cursor.value.getFullYear()
  const month = cursor.value.getMonth()
  const firstWeekday = (new Date(year, month, 1).getDay() + 6) % 7
  const daysInMonth = new Date(year, month + 1, 0).getDate()
  const daysInPrev = new Date(year, month, 0).getDate()
  const list: { key: string; day: number; date: Date; muted: boolean }[] = []
  for (let i = firstWeekday - 1; i >= 0; i -= 1) {
    list.push({ key: `prev-${i}`, day: daysInPrev - i, date: new Date(year, month - 1, daysInPrev - i), muted: true })
  }
  for (let day = 1; day <= daysInMonth; day += 1) {
    list.push({ key: `cur-${day}`, day, date: new Date(year, month, day), muted: false })
  }
  for (let day = 1; list.length < 42; day += 1) {
    list.push({ key: `next-${day}`, day, date: new Date(year, month + 1, day), muted: true })
  }
  return list
})

const hourValue = computed(() => (selected.value ? pad(selected.value.getHours()) : '00'))
const minuteValue = computed(() => (selected.value ? pad(selected.value.getMinutes()) : '00'))

function placePanel(): void {
  const el = trigger.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  const width = 272
  const height = props.mode === 'datetime' ? 366 : 318
  const left = Math.max(8, Math.min(rect.left, window.innerWidth - width - 8))
  const below = rect.bottom + 6
  const top = below + height > window.innerHeight ? Math.max(8, rect.top - height - 6) : below
  panelStyle.value = { position: 'fixed', left: `${left}px`, top: `${top}px`, width: `${width}px` }
}

function openPanel(): void {
  if (props.disabled || open.value) return
  cursor.value = selected.value
    ? new Date(selected.value.getFullYear(), selected.value.getMonth(), 1)
    : new Date()
  open.value = true
  void nextTick(placePanel)
}

function close(): void {
  open.value = false
}

function toggle(): void {
  if (open.value) close()
  else openPanel()
}

function shiftMonth(step: number): void {
  cursor.value = new Date(cursor.value.getFullYear(), cursor.value.getMonth() + step, 1)
}

function shiftYear(step: number): void {
  cursor.value = new Date(cursor.value.getFullYear() + step, cursor.value.getMonth(), 1)
}

function pick(date: Date): void {
  const next = new Date(date)
  if (props.mode === 'datetime') {
    const base = selected.value
    next.setHours(base ? base.getHours() : 0, base ? base.getMinutes() : 0, 0, 0)
  }
  emit('update:modelValue', format(next))
  if (props.mode === 'date') close()
}

function updateTime(hour: string, minute: string): void {
  const base = selected.value
    ?? new Date(cursor.value.getFullYear(), cursor.value.getMonth(), cursor.value.getDate())
  const next = new Date(base)
  next.setHours(Number(hour), Number(minute), 0, 0)
  emit('update:modelValue', format(next))
}

function clear(): void {
  emit('update:modelValue', '')
  close()
}

function pickToday(): void {
  const now = new Date()
  if (props.mode === 'datetime') {
    emit('update:modelValue', format(now))
  } else {
    emit('update:modelValue', format(new Date(now.getFullYear(), now.getMonth(), now.getDate())))
    close()
  }
}

function onKeydown(event: KeyboardEvent): void {
  if (props.disabled) return
  if (event.key === 'Escape' && open.value) {
    event.preventDefault()
    close()
    return
  }
  if (!open.value && ['Enter', ' ', 'ArrowDown'].includes(event.key)) {
    event.preventDefault()
    openPanel()
  }
}

function onDocClick(event: MouseEvent): void {
  const target = event.target as Node
  if (root.value?.contains(target) || panel.value?.contains(target)) return
  close()
}

function onViewportChange(event: Event): void {
  // 时/分下拉是另一层 Teleport 菜单，滚动它不应把日期面板关掉
  const target = event.target
  if (target instanceof Element && target.closest('.ui-select__menu')) return
  if (open.value) close()
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
  <span ref="root" class="ui-date-wrap">
    <div
      ref="trigger"
      class="ui-date"
      :class="{ 'is-open': open, 'is-disabled': disabled }"
      role="button"
      :tabindex="disabled ? -1 : 0"
      :aria-expanded="open"
      @click.stop="toggle"
      @keydown="onKeydown"
    >
      <svg class="ui-date__icon" width="14" height="14" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" stroke-width="2" stroke-linecap="round">
        <rect x="3" y="5" width="18" height="16" rx="2" />
        <path d="M8 3v4M16 3v4M3 10h18" />
      </svg>
      <span class="ui-date__text" :class="{ 'is-empty': !displayText }">{{ displayText || emptyText }}</span>
    </div>
    <Teleport to="body">
      <div v-if="open" ref="panel" class="ui-date__panel" :style="panelStyle" role="dialog">
        <div class="ui-date__head">
          <button type="button" class="ui-date__nav" title="上一年" @click.stop="shiftYear(-1)">«</button>
          <button type="button" class="ui-date__nav" title="上个月" @click.stop="shiftMonth(-1)">‹</button>
          <span class="ui-date__month">{{ monthLabel }}</span>
          <button type="button" class="ui-date__nav" title="下个月" @click.stop="shiftMonth(1)">›</button>
          <button type="button" class="ui-date__nav" title="下一年" @click.stop="shiftYear(1)">»</button>
        </div>
        <div class="ui-date__week">
          <span v-for="w in WEEK" :key="w">{{ w }}</span>
        </div>
        <div class="ui-date__grid">
          <button
            v-for="cell in cells"
            :key="cell.key"
            type="button"
            class="ui-date__day"
            :class="{
              'is-muted': cell.muted,
              'is-selected': selected && sameDay(cell.date, selected),
              'is-today': sameDay(cell.date, new Date()),
            }"
            @click.stop="pick(cell.date)"
          >{{ cell.day }}</button>
        </div>
        <div v-if="mode === 'datetime'" class="ui-date__time">
          <span class="ui-date__time-label">时间</span>
          <UiSelect
            size="sm"
            variant="plain"
            :model-value="hourValue"
            :options="HOURS.map(h => ({ value: h, label: h }))"
            @change="updateTime(String($event), minuteValue)"
          />
          <span class="ui-date__colon">:</span>
          <UiSelect
            size="sm"
            variant="plain"
            :model-value="minuteValue"
            :options="MINUTES.map(m => ({ value: m, label: m }))"
            @change="updateTime(hourValue, String($event))"
          />
        </div>
        <div class="ui-date__foot">
          <button v-if="clearable" type="button" class="ui-date__link" @click.stop="clear">清除</button>
          <button type="button" class="ui-date__link" @click.stop="pickToday">今天</button>
          <span class="ui-date__spacer"></span>
          <button v-if="mode === 'datetime'" type="button" class="ui-date__done" @click.stop="close">完成</button>
        </div>
      </div>
    </Teleport>
  </span>
</template>

<style scoped>
.ui-date-wrap { display: block; min-width: 0; }
.ui-date {
  display: flex; align-items: center; gap: 8px;
  width: 100%; height: var(--ctl-h, 36px); padding: 0 10px;
  border: 1px solid var(--border-strong); border-radius: 8px; background: #fff;
  color: var(--text); font-size: var(--ctl-font, 12.5px);
  cursor: pointer; user-select: none;
  transition: border-color .12s, box-shadow .12s;
}
.ui-date:hover { border-color: var(--primary); }
.ui-date.is-open { border-color: var(--primary); box-shadow: 0 0 0 3px rgba(15, 155, 142, .12); }
.ui-date.is-disabled { background: #f6f8fa; color: var(--text-3); cursor: not-allowed; }
.ui-date__icon { flex: none; color: var(--text-3); }
.ui-date__text { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ui-date__text.is-empty { color: var(--text-3); }

.ui-date__panel {
  z-index: 2000; padding: 10px;
  background: #fff; border: 1px solid var(--border); border-radius: 11px;
  box-shadow: var(--shadow-lg); font-size: 12px;
  animation: pop .12s ease;
}
.ui-date__head { display: flex; align-items: center; gap: 2px; margin-bottom: 6px; }
.ui-date__month { flex: 1; text-align: center; font-weight: 600; font-size: 12.5px; color: var(--text); }
.ui-date__nav {
  width: 22px; height: 22px; display: inline-flex; align-items: center; justify-content: center;
  border: none; border-radius: 6px; background: none; color: var(--text-3); font-size: 13px; cursor: pointer;
}
.ui-date__nav:hover { background: #f1f6f5; color: var(--text); }
.ui-date__week,
.ui-date__grid { display: grid; grid-template-columns: repeat(7, 1fr); }
.ui-date__week span { text-align: center; font-size: 11px; color: var(--text-3); padding: 4px 0; }
.ui-date__grid { row-gap: 2px; }
.ui-date__day {
  height: 28px; border: none; border-radius: 6px; background: none;
  color: var(--text); font-size: 12px; font-variant-numeric: tabular-nums; cursor: pointer;
}
.ui-date__day:hover { background: #f1f6f5; }
.ui-date__day.is-muted { color: var(--text-3); opacity: .6; }
.ui-date__day.is-today { box-shadow: inset 0 0 0 1px var(--border-strong); }
.ui-date__day.is-selected { background: var(--primary); color: #fff; font-weight: 600; }

.ui-date__time { display: flex; align-items: center; gap: 6px; margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--border); }
.ui-date__time-label { font-size: 11.5px; color: var(--text-3); }
.ui-date__time :deep(.ui-select) { width: 62px; }
.ui-date__colon { color: var(--text-3); }

.ui-date__foot { display: flex; align-items: center; gap: 10px; margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--border); }
.ui-date__spacer { flex: 1; }
.ui-date__link { border: none; background: none; padding: 2px 4px; color: var(--primary); font-size: 12px; cursor: pointer; }
.ui-date__link:hover { text-decoration: underline; }
.ui-date__done {
  border: none; border-radius: 6px; padding: 4px 12px;
  background: var(--primary); color: #fff; font-size: 12px; cursor: pointer;
}
</style>
