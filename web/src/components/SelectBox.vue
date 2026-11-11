<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import Icon from './Icon.vue'

/**
 * 统一的下拉选择（替换原生 select / 旧 Combo）：
 * 触发器沿用输入框外观，下拉面板带搜索、当前项打勾、支持「空值」与「旧值」项。
 * options 可混用字符串与 { label, value }——旧值这种「显示文案 ≠ 存储值」的场景用后者。
 * allowCustom：面板里的输入框可直接敲自定义值（回车或点按钮采用），用于题材 / 文风这类可自由填写的字段。
 */
type Opt = { label: string; value: string }
const props = withDefaults(defineProps<{
  modelValue: string | number
  options: (string | Opt)[]
  placeholder?: string
  allowEmpty?: boolean
  emptyLabel?: string
  disabled?: boolean
  /* 选项超过这个数量才显示搜索框 */
  searchFrom?: number
  /* 卡片内紧凑尺寸 */
  compact?: boolean
  /* 允许直接输入自定义值 */
  allowCustom?: boolean
}>(), {
  placeholder: '请选择',
  allowEmpty: false,
  emptyLabel: '— 未填 —',
  disabled: false,
  searchFrom: 10,
  compact: false,
  allowCustom: false,
})

const emit = defineEmits<{ (e: 'update:modelValue', v: string): void }>()

const open = ref(false)
const up = ref(false)      // 靠近窗口底部时向上弹，避免面板被容器裁掉
const kw = ref('')
const root = ref<HTMLElement | null>(null)
const searchEl = ref<HTMLInputElement | null>(null)

const opts = computed<Opt[]>(() => (props.options || []).map(o =>
  typeof o === 'string' ? { label: o, value: o } : o))
const cur = computed(() => String(props.modelValue ?? ''))
const curLabel = computed(() => opts.value.find(o => o.value === cur.value)?.label || cur.value)
const list = computed(() => {
  const q = kw.value.trim().toLowerCase()
  return q ? opts.value.filter(o => o.label.toLowerCase().includes(q)) : opts.value
})
const needSearch = computed(() => props.allowCustom || opts.value.length > props.searchFrom)
const customText = computed(() => kw.value.trim())

function toggle() {
  if (props.disabled) return
  open.value = !open.value
  if (open.value) {
    kw.value = ''
    const r = root.value?.getBoundingClientRect()
    up.value = !!r && r.bottom + 300 > window.innerHeight && r.top > 310
    nextTick(() => { if (needSearch.value) searchEl.value?.focus() })
  }
}
function pick(v: string) {
  emit('update:modelValue', v)
  open.value = false
}
/* 自定义值：面板输入框里回车 / 点「使用」直接采用 */
function useCustom() {
  if (!customText.value) return
  pick(customText.value)
}
function onDocDown(e: MouseEvent) {
  if (open.value && root.value && !root.value.contains(e.target as Node)) open.value = false
}
function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && open.value) { e.stopPropagation(); open.value = false }
}
onMounted(() => {
  document.addEventListener('mousedown', onDocDown)
  document.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  document.removeEventListener('mousedown', onDocDown)
  document.removeEventListener('keydown', onKey)
})
</script>

<template>
  <div ref="root" class="sbox" :class="{ open, disabled, compact }">
    <button type="button" class="sbox-btn" :disabled="disabled" @click="toggle">
      <span class="sbox-txt" :class="{ ph: !curLabel }">{{ curLabel || placeholder }}</span>
      <Icon name="down" :size="12" class="sbox-caret" />
    </button>

    <div v-if="open" class="sbox-panel" :class="{ up }">
      <div v-if="needSearch" class="sbox-search">
        <Icon name="search" :size="13" />
        <input ref="searchEl" v-model="kw"
               :placeholder="allowCustom ? '筛选预设，或直接输入自定义值' : '输入关键词筛选'"
               @keydown.enter.prevent="allowCustom && useCustom()"
               @keydown.esc="open = false" />
        <button v-if="kw" type="button" class="sbox-clear" @click="kw = ''">×</button>
      </div>
      <div class="sbox-list">
        <button v-if="allowEmpty" type="button" class="sbox-opt" :class="{ on: !cur }" @click="pick('')">
          <span>{{ emptyLabel }}</span>
          <Icon v-if="!cur" name="check" :size="12" />
        </button>
        <button v-for="o in list" :key="o.value + '|' + o.label" type="button" class="sbox-opt"
                :class="{ on: cur === o.value }" @click="pick(o.value)">
          <span>{{ o.label }}</span>
          <Icon v-if="cur === o.value" name="check" :size="12" />
        </button>
        <div v-if="!list.length" class="sbox-empty">
          {{ allowCustom ? '没有匹配的预设，回车可直接使用输入值' : '没有匹配的选项' }}
        </div>
      </div>
      <div v-if="allowCustom && customText" class="sbox-custom">
        <button type="button" @click="useCustom">
          <Icon name="check" :size="12" /> 使用自定义值「{{ customText }}」
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sbox { position: relative; width: 100%; }
.sbox-btn {
  display: flex; align-items: center; gap: 6px; width: 100%;
  padding: 8px 12px; min-height: 36px;
  border: 1px solid var(--border-strong); border-radius: var(--radius-sm);
  background: var(--card); color: var(--text);
  font-family: inherit; font-size: 13px; text-align: left; cursor: pointer;
  transition: border-color .12s, box-shadow .12s;
}
.sbox-btn:focus-visible, .sbox.open .sbox-btn {
  outline: none; border-color: var(--primary); box-shadow: 0 0 0 2px var(--primary-bg);
}
.sbox-btn:disabled { cursor: not-allowed; opacity: .6; }
.sbox-txt { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sbox-txt.ph { color: var(--text-3); }
.sbox-caret { flex: none; color: var(--text-3); transition: transform .12s; }
.sbox.open .sbox-caret { transform: rotate(180deg); }
.sbox.compact .sbox-btn { padding: 6px 9px; min-height: 32px; font-size: 12.5px; }
.sbox-panel {
  position: absolute; z-index: 60; top: calc(100% + 4px); left: 0; right: 0;
  background: var(--card); border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm); box-shadow: var(--shadow-lg); overflow: hidden;
}
.sbox-panel.up { top: auto; bottom: calc(100% + 4px); }
.sbox-search {
  display: flex; align-items: center; gap: 6px;
  padding: 7px 9px; border-bottom: 1px solid var(--border); background: var(--bg);
  color: var(--text-3);
}
.sbox-search input {
  flex: 1; min-width: 0; border: 0; outline: none; background: none;
  color: var(--text); font-family: inherit; font-size: 12.5px;
}
.sbox-clear { border: 0; background: none; color: var(--text-3); font-size: 15px; padding: 0 2px; cursor: pointer; }
.sbox-list { max-height: 240px; overflow-y: auto; padding: 3px; }
.sbox-opt {
  display: flex; align-items: center; justify-content: space-between; gap: 8px; width: 100%;
  padding: 7px 9px; border: 0; border-radius: 6px; background: none;
  color: var(--text); font-family: inherit; font-size: 12.5px; text-align: left; cursor: pointer;
}
.sbox-opt:hover { background: var(--primary-bg); color: var(--primary); }
.sbox-opt.on { background: var(--primary-bg); color: var(--primary); font-weight: 600; }
.sbox-opt span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sbox-empty { padding: 12px 10px; font-size: 12px; color: var(--text-3); text-align: center; }
.sbox-custom { border-top: 1px solid var(--border); background: var(--bg); }
.sbox-custom button {
  display: flex; align-items: center; gap: 5px; width: 100%;
  padding: 8px 10px; border: 0; background: none; cursor: pointer;
  color: var(--primary); font-family: inherit; font-size: 12.5px; text-align: left;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.sbox-custom button:hover { background: var(--primary-bg); }
</style>
