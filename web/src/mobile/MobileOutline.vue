<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import Icon from '../components/Icon.vue'
import MobilePicker from './MobilePicker.vue'
import SearchMultiSelect from '../components/SearchMultiSelect.vue'
import { api } from '../api'
import { state, store } from '../store'
import { AUDIENCE_PRESETS, GENRE_PRESETS, PERSON_PRESETS, TONE_PRESETS, VOICE_PRESETS } from '../storyPresets'
import { useBookDoc } from '../composables/useBookDoc'
import type { SbSchema } from '../types'

const { raw, fields, saving, load, save, cards, items } = useBookDoc()
const schema = ref<SbSchema | null>(null)
const dirty = ref(false)

onMounted(async () => {
  store.loadBooks().catch(() => {})
  load()
  try { schema.value = await api.getSchema() } catch { /* 忽略 */ }
})
watch(() => store.curBook(), () => { dirty.value = false })
onBeforeRouteLeave(async () => {
  if (dirty.value) { const ok = await save(true); if (ok) dirty.value = false }
  return true
})

const groups = [
  { key: 'basic', name: '基础信息', icon: 'file', keys: ['synopsis', 'genre', 'person', 'audience', 'style'] },
  { key: 'world', name: '世界观', icon: 'dashboard', keys: ['world', 'power', 'places', 'items', 'terms', 'timeline', 'map'] },
  { key: 'plot', name: '故事主线', icon: 'arrowR', keys: ['mainline', 'conflict', 'suspense', 'subplots'] },
  { key: 'people', name: '人物与伏笔', icon: 'eye', keys: ['protagonist', 'supporting', 'antagonist', 'foreshadow', 'taboos'] },
]
const oneLine = new Set(['genre', 'person', 'audience', 'style', 'places', 'items', 'conflict', 'suspense'])
/* 题材 / 文风 / 人称 / 读者定位：与桌面「作品大纲」同一套预设，选中即用「、」追加，
   既保留自由填写，也不用记词表 */
const PRESET_MAP: Record<string, string[]> = {
  genre: [...GENRE_PRESETS, ...TONE_PRESETS],
  style: VOICE_PRESETS,
  person: PERSON_PRESETS,
  audience: AUDIENCE_PRESETS,
}
function appendPreset(k: string, v: string) {
  if (!v) return
  const cur = String(fields.value[k] || '').trim()
  if (cur.includes(v)) return
  fields.value[k] = cur ? cur + '、' + v : v
  dirty.value = true
}
/* 人物 / 道具：从角色卡 / 道具功法里多选，选中项即实体名称，与卡片保持同一份数据。
   改名由服务端同步替换文本；删卡后名称不再出现在选项里，选中态自动消失。 */
const LINK_MAP: Record<string, 'user' | 'item'> = {
  protagonist: 'user', supporting: 'user', antagonist: 'user', items: 'item',
}
const linkOptions = computed<Record<string, string[]>>(() => {
  const cardNames = cards.value.map(c => String(c.name || '').trim()).filter(Boolean)
  const itemNames = items.value.map(it => String(it.name || '').trim()).filter(Boolean)
  return { protagonist: cardNames, supporting: cardNames, antagonist: cardNames, items: itemNames }
})
const TOKEN_RE = /[、，,；;/｜|\n]+/
function splitTokens(v: unknown): string[] {
  return String(v ?? '').split(TOKEN_RE).map(s => s.trim()).filter(Boolean)
}
function linkSelected(k: string): string[] {
  const opts = new Set(linkOptions.value[k] || [])
  const out: string[] = []
  for (const t of splitTokens(fields.value[k])) {
    if (opts.has(t) && !out.includes(t)) out.push(t)
  }
  return out
}
function dropToken(text: string, name: string): string {
  const esc = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const SEP = '[\\s、，,；;/｜|]'
  let out = text
  out = out.replace(new RegExp('(^|\\n)[ \\t\\u3000]*' + esc + '[ \\t\\u3000]*(?=\\n|$)', 'g'), '$1')
  out = out.replace(new RegExp('(^|' + SEP + ')' + esc + '[ \\t]*[、，,；;/｜|][ \\t]*', 'g'), '$1')
  out = out.replace(new RegExp('[ \\t]*[、，,；;/｜|][ \\t]*' + esc + '(?=$|' + SEP + ')', 'g'), '')
  return out.replace(/\n{3,}/g, '\n\n').trim()
}
/** 追加名称：描述性长文本已以句号收尾时另起一行，避免出现「…家人。、童母」 */
function appendName(text: string, name: string): string {
  const t = text.replace(/\s+$/, '')
  if (!t) return name
  return /[。！？；;]$/.test(t) ? t + '\n' + name : t + '、' + name
}
function setLinks(k: string, next: string[]) {
  const cur = linkSelected(k)
  let text = String(fields.value[k] || '')
  for (const n of cur) if (!next.includes(n)) text = dropToken(text, n)
  for (const n of next) if (!cur.includes(n)) text = appendName(text, n)
  fields.value[k] = text
  dirty.value = true
}
const minH: Record<string, number> = { synopsis: 112, world: 96, power: 84, mainline: 96, subplots: 80,
  protagonist: 84, supporting: 84, antagonist: 84, terms: 76, timeline: 76, map: 76, foreshadow: 76, taboos: 76 }

const labelOf = computed<Record<string, string>>(() =>
  Object.fromEntries(schema.value?.sb_fields || []))
const extraKeys = computed(() =>
  (schema.value?.sb_fields || []).map(([k]) => k).filter(k => !groups.some(g => g.keys.includes(k))))
const tabs = computed(() => [
  ...groups.map(g => ({ ...g, filled: g.keys.filter(k => String(fields.value[k] || '').trim()).length })),
  ...(extraKeys.value.length
    ? [{ key: 'extra', name: '其他', icon: 'settings', keys: extraKeys.value,
        filled: extraKeys.value.filter(k => String(fields.value[k] || '').trim()).length }]
    : []),
])
const tab = ref('basic')
const curGroup = computed(() => tabs.value.find(t => t.key === tab.value) || tabs.value[0])
const totalKeys = computed(() => tabs.value.reduce((n, t) => n + t.keys.length, 0))
const filledKeys = computed(() => tabs.value.reduce((n, t) => n + t.filled, 0))
const pct = computed(() => Math.round((filledKeys.value / Math.max(1, totalKeys.value)) * 100))

async function doSave() {
  const ok = await save()
  if (ok) dirty.value = false
}
</script>

<template>
  <div class="m-page m-page-fixed">
    <div class="m-head">
      <div>
        <h1>作品大纲</h1>
        <p>全书要素与故事主线，AI 扩写与审查的核心依据</p>
      </div>
      <div class="m-head-act">
        <button class="m-btn sm" :disabled="saving" @click="doSave">
          <Icon name="check" :size="14" /> {{ saving ? '保存中' : '保存' }}
        </button>
      </div>
    </div>

    <div v-if="!state.books.length" class="m-empty" style="padding-top:70px">
      <span class="m-empty-ico"><Icon name="list" :size="28" /></span>
      <b>还没有作品</b>
      <p>先新建作品并完成拆解，再回来编辑全书大纲。</p>
    </div>

    <div v-else-if="!raw" class="m-empty" style="padding-top:70px">
      <span class="m-empty-ico"><Icon name="refresh" :size="28" /></span>
      <b>正在载入大纲</b>
      <p>从本地作品数据里读取设定…</p>
    </div>

    <template v-else>
      <!-- 固定区：完成度 + 分组页签（不随表单滚动） -->
      <div class="m-ol-top">
        <div class="m-card m-ol-progress">
          <div class="m-ol-ring" :style="{ '--p': pct + '%' }">
            <span>{{ pct }}<i>%</i></span>
          </div>
          <div class="m-ol-progress-txt">
            <b>设定完成度</b>
            <small>已填写 {{ filledKeys }} / {{ totalKeys }} 项，补充得越完整，正文越稳定</small>
          </div>
          <span v-if="dirty" class="m-tag gold">未保存</span>
          <span v-else class="m-tag green">已同步</span>
        </div>

        <div class="m-chips" style="margin-top:12px">
          <button v-for="t in tabs" :key="t.key" class="m-chip" :class="{ on: tab === t.key }"
                  @click="tab = t.key">
            {{ t.name }}<span class="m-chip-n">{{ t.filled }}</span>
          </button>
        </div>
      </div>

      <!-- 滚动区：只滚表单，顶部模块始终可见；保存按钮只在右上，不再放底部 -->
      <div class="m-page-scroll">
        <div class="m-card">
          <div class="m-card-head">
            <b>{{ curGroup?.name }}</b>
            <span class="m-sub">{{ curGroup?.keys.length }} 项要素</span>
            <span class="m-spacer"></span>
            <span class="m-sub">{{ curGroup?.filled }} 项已填写</span>
          </div>

          <div class="m-form">
            <div v-for="k in curGroup?.keys" :key="k" class="m-field">
              <label>
                <span>{{ labelOf[k] || k }}</span>
                <em v-if="String(fields[k] || '').trim()">已填写 {{ String(fields[k]).length }} 字</em>
              </label>
              <SearchMultiSelect v-if="LINK_MAP[k]" mobile
                                 :model-value="linkSelected(k)"
                                 :options="linkOptions[k] || []"
                                 :tone="LINK_MAP[k]"
                                 :placeholder="LINK_MAP[k] === 'item' ? '从道具功法里选择关联' : '从角色卡里选择关联'"
                                 @update:model-value="v => setLinks(k, v)" />
              <input v-if="oneLine.has(k)" class="m-input" v-model="fields[k]"
                     :placeholder="'填写' + (labelOf[k] || k)" @input="dirty = true" />
              <textarea v-else class="m-textarea" v-model="fields[k]"
                        :style="{ minHeight: (minH[k] || 76) + 'px' }"
                        :placeholder="'填写' + (labelOf[k] || k) + '…'" @input="dirty = true"></textarea>
              <MobilePicker v-if="PRESET_MAP[k]" chip :model-value="''" :options="PRESET_MAP[k]"
                            :allow-empty="false" :title="'选择' + (labelOf[k] || k) + '预设'"
                            placeholder="+ 预设" @update:model-value="v => appendPreset(k, v)" />
            </div>
          </div>
        </div>

        <p class="m-hint" style="padding:12px 6px 0">
          提示：大纲会随作品保存到本地，切换作品或退出应用前会自动保留修改。
        </p>
      </div>
    </template>
  </div>
</template>

<style scoped>
.m-ol-progress { display: flex; align-items: center; gap: 13px; }
.m-ol-ring {
  width: 54px; height: 54px; flex: none; border-radius: 50%;
  background: conic-gradient(var(--m-primary) var(--p), #edf0ea 0);
  display: grid; place-items: center; position: relative;
}
.m-ol-ring::after { content: ''; position: absolute; inset: 5px; border-radius: 50%; background: #fff; }
.m-ol-ring span { position: relative; z-index: 1; font-size: 14px; font-weight: 750; color: var(--m-primary); }
.m-ol-ring span i { font-style: normal; font-size: 9px; font-weight: 600; }
.m-ol-progress-txt { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.m-ol-progress-txt b { font-size: 14px; font-weight: 650; }
.m-ol-progress-txt small { font-size: 11px; line-height: 1.55; color: var(--m-text3); }
.m-save-enter-active, .m-save-leave-active { transition: opacity .18s, transform .18s; }
.m-save-enter-from, .m-save-leave-to { opacity: 0; transform: translateY(8px); }
</style>
