<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import Icon from './Icon.vue'

const props = withDefaults(defineProps<{
  modelValue: string[]
  options: string[]
  placeholder?: string
  emptyText?: string
  mobile?: boolean
  tone?: 'user' | 'flag' | 'item'
}>(), {
  placeholder: '点击选择',
  emptyText: '暂无可选项',
  mobile: false,
  tone: 'user',
})
const emit = defineEmits<{ (e: 'update:modelValue', v: string[]): void }>()

const root = ref<HTMLElement | null>(null)
const searchEl = ref<HTMLInputElement | null>(null)
const open = ref(false)
const query = ref('')

const ALLOWED_ICON = { user: 'user', flag: 'flag', item: 'shield' } as const
const toneIcon = computed(() => ALLOWED_ICON[props.tone] || 'user')
const toneLabel = computed(() => props.tone === 'flag' ? '势力' : props.tone === 'item' ? '道具功法' : '角色')
const selected = computed(() => props.modelValue || [])
const allOptions = computed(() => {
  const set = new Set(props.options)
  /* 旧数据里手工写过的名字也保留，避免打开编辑器后凭空消失 */
  for (const n of selected.value) set.add(n)
  return Array.from(set)
})
const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return allOptions.value
  return allOptions.value.filter(n => String(n).toLowerCase().includes(q))
})

function toggleOpen() {
  open.value = !open.value
  if (open.value) {
    query.value = ''
    nextTick(() => searchEl.value?.focus())
  }
}
function close() { open.value = false }
function toggle(n: string) {
  const cur = selected.value.slice()
  const i = cur.indexOf(n)
  if (i >= 0) cur.splice(i, 1)
  else cur.push(n)
  emit('update:modelValue', cur)
}
function remove(n: string) {
  emit('update:modelValue', selected.value.filter(x => x !== n))
}
function clear() {
  emit('update:modelValue', [])
}
function onDocDown(e: MouseEvent) {
  if (!open.value || !root.value) return
  if (!root.value.contains(e.target as Node)) close()
}
function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && open.value) { e.stopPropagation(); close() }
}
onMounted(() => {
  document.addEventListener('mousedown', onDocDown)
  document.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  document.removeEventListener('mousedown', onDocDown)
  document.removeEventListener('keydown', onKey)
})
watch(() => props.options, () => {
  if (!open.value) query.value = ''
})
</script>

<template>
  <div ref="root" class="sms" :class="[mobile ? 'is-mobile' : 'is-pc', 'tone-' + tone]">
    <button type="button" class="sms-trigger" :class="{ open }" @click="toggleOpen">
      <span class="sms-body">
        <template v-if="selected.length">
          <span v-for="n in selected" :key="n" class="sms-chip">
            <Icon :name="toneIcon" :size="11" />
            <span class="sms-chip-txt">{{ n }}</span>
            <span class="sms-x" role="button" title="移除" @click.stop="remove(n)">×</span>
          </span>
        </template>
        <span v-else class="sms-placeholder">{{ placeholder }}</span>
      </span>
      <span class="sms-tail">
        <span v-if="selected.length" class="sms-count">{{ selected.length }}</span>
        <span class="sms-chev" :class="{ open }"><Icon name="down" :size="14" /></span>
      </span>
    </button>

    <div v-if="open" class="sms-panel">
      <div class="sms-search">
        <Icon name="search" :size="14" />
        <input ref="searchEl" v-model="query" :placeholder="'搜索' + toneLabel + '…'"
               @keydown.esc="close" />
        <button v-if="query" type="button" class="sms-clear-q" @click="query = ''">×</button>
      </div>
      <div class="sms-list">
        <button v-for="n in filtered" :key="n" type="button" class="sms-option"
                :class="{ on: selected.includes(n) }" @click="toggle(n)">
          <span class="sms-check">{{ selected.includes(n) ? '✓' : '' }}</span>
          <Icon :name="toneIcon" :size="13" />
          <span class="sms-name">{{ n }}</span>
        </button>
        <div v-if="!allOptions.length" class="sms-empty">{{ emptyText }}</div>
        <div v-else-if="!filtered.length" class="sms-empty">没有匹配的{{ toneLabel }}</div>
      </div>
      <div class="sms-foot">
        <span>已选 {{ selected.length }} 项</span>
        <button v-if="selected.length" type="button" class="sms-clear" @click="clear">清空</button>
        <button type="button" class="sms-done" @click="close">完成</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sms { position: relative; width: 100%; --sms-a: #3370ff; --sms-soft: #eef3ff; }
.sms.tone-flag { --sms-a: #b7791f; --sms-soft: #fdf6e7; }
.sms.tone-item { --sms-a: #0f8a7a; --sms-soft: #e6f6f2; }
.sms-trigger {
  display: flex; align-items: flex-start; gap: 8px; width: 100%;
  padding: 6px 9px; min-height: 38px;
  border: 1px solid var(--line, #e5e7eb); border-radius: 8px;
  background: var(--panel, #fff); color: var(--text, #1f2329);
  font-size: 13px; text-align: left; cursor: pointer;
}
.sms-trigger.open, .sms-trigger:focus { border-color: var(--sms-a); box-shadow: 0 0 0 2px var(--sms-soft); outline: none; }
.sms-body { flex: 1; min-width: 0; display: flex; flex-wrap: wrap; gap: 5px; align-items: center; }
.sms-placeholder { color: var(--text-3, #8f959e); line-height: 26px; }
.sms-chip {
  display: inline-flex; align-items: center; gap: 4px;
  max-width: 100%; padding: 2px 4px 2px 7px; border-radius: 6px;
  background: var(--sms-soft); color: var(--sms-a); font-size: 12px; line-height: 20px;
}
.sms-chip-txt { max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sms-x { padding: 0 3px; border-radius: 4px; opacity: .65; font-size: 13px; }
.sms-x:hover { background: rgba(0, 0, 0, .07); opacity: 1; }
.sms-tail { flex: none; display: flex; align-items: center; gap: 5px; color: var(--text-3, #8f959e); line-height: 26px; }
.sms-chev { display: inline-flex; transition: transform .18s; }
.sms-chev.open { transform: rotate(180deg); }
.sms-count {
  min-width: 18px; height: 18px; padding: 0 5px; border-radius: 9px;
  background: var(--sms-soft); color: var(--sms-a); font-size: 10.5px;
  display: inline-flex; align-items: center; justify-content: center;
}
.sms-panel {
  margin-top: 6px; border: 1px solid var(--line, #e5e7eb); border-radius: 10px;
  background: var(--panel, #fff); box-shadow: 0 12px 30px rgba(20, 30, 27, .1);
  overflow: hidden;
}
.sms-search {
  display: flex; align-items: center; gap: 7px;
  padding: 8px 10px; border-bottom: 1px solid var(--line, #edf0ec);
  color: var(--text-3, #8f959e);
}
.sms-search input {
  flex: 1; min-width: 0; border: 0; outline: none; background: none;
  color: var(--text, #1f2329); font-size: 13px;
}
.sms-clear-q { border: 0; background: none; color: var(--text-3, #8f959e); font-size: 16px; padding: 0 2px; cursor: pointer; }
.sms-list { max-height: 220px; overflow-y: auto; padding: 5px; }
.sms-option {
  display: flex; align-items: center; gap: 7px; width: 100%;
  padding: 7px 8px; border: 0; border-radius: 7px; background: none;
  color: var(--text, #1f2329); font-size: 12.5px; text-align: left; cursor: pointer;
}
.sms-option:hover { background: #f6f8f4; }
.sms-option.on { background: var(--sms-soft); color: var(--sms-a); }
.sms-check {
  width: 15px; height: 15px; flex: none; border: 1px solid var(--line, #d9ded8); border-radius: 4px;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 10px; line-height: 1; color: #fff;
}
.sms-option.on .sms-check { background: var(--sms-a); border-color: var(--sms-a); }
.sms-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sms-empty { padding: 18px 10px; text-align: center; font-size: 12px; color: var(--text-3, #8f959e); }
.sms-foot {
  display: flex; align-items: center; gap: 8px;
  padding: 7px 10px; border-top: 1px solid var(--line, #edf0ec);
  font-size: 11px; color: var(--text-3, #8f959e);
}
.sms-clear { margin-left: auto; border: 0; background: none; color: var(--text-3, #8f959e); font-size: 11.5px; cursor: pointer; }
.sms-done { border: 0; border-radius: 6px; background: var(--sms-a); color: #fff; padding: 5px 11px; font-size: 11.5px; cursor: pointer; }

/* 安卓端 */
.sms.is-mobile { --sms-a: var(--m-primary, #0f766e); --sms-soft: var(--m-primary-soft, #e7f4f0); }
.sms.is-mobile.tone-flag { --sms-a: #a36a1c; --sms-soft: var(--m-gold-soft, #fdf5e6); }
.sms.is-mobile.tone-item { --sms-a: #0f8a7a; --sms-soft: #e3f4ef; }
.sms.is-mobile .sms-trigger {
  min-height: 44px; padding: 7px 10px; border-color: var(--m-line, #e4e6e1);
  border-radius: 12px; background: #fff; color: var(--m-text, #1f2622); font-size: 13px;
}
.sms.is-mobile .sms-trigger.open { border-color: var(--sms-a); box-shadow: 0 0 0 3px var(--sms-soft); }
.sms.is-mobile .sms-chip { font-size: 12px; line-height: 21px; border-radius: 7px; }
.sms.is-mobile .sms-panel { margin-top: 7px; border-color: var(--m-line, #e4e6e1); border-radius: 14px; }
.sms.is-mobile .sms-search { padding: 10px 12px; }
.sms.is-mobile .sms-search input { font-size: 16px; }
.sms.is-mobile .sms-list { max-height: 250px; padding: 6px; }
.sms.is-mobile .sms-option { min-height: 42px; padding: 8px 10px; font-size: 13px; border-radius: 9px; }
.sms.is-mobile .sms-foot { padding: 8px 12px; font-size: 11px; }
.sms.is-mobile .sms-done { padding: 7px 14px; font-size: 12px; }
</style>
