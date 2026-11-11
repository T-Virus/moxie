<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import Icon from '../components/Icon.vue'
import BackLink from '../components/BackLink.vue'
import EmptyBox from '../components/EmptyBox.vue'
import SelectBox from '../components/SelectBox.vue'
import SearchMultiSelect from '../components/SearchMultiSelect.vue'
import { api } from '../api'
import { store, state } from '../store'
import { useBookDoc } from '../composables/useBookDoc'
import { AUDIENCE_PRESETS, GENRE_PRESETS, PERSON_PRESETS, TONE_PRESETS, VOICE_PRESETS } from '../storyPresets'
import type { SbSchema } from '../types'

const { raw, fields, saving, load, save, cards, items } = useBookDoc()
const schema = ref<SbSchema | null>(null)

onMounted(async () => {
  store.loadBooks().catch(() => {})
  load()
  try { schema.value = await api.getSchema() } catch { /* 忽略 */ }
})

/* 分组展示：短字段半宽成对，长字段整宽 */
const groups = [
  { name: '基础信息', keys: ['synopsis', 'genre', 'person', 'audience', 'style'] },
  { name: '世界观与设定', keys: ['world', 'power', 'places', 'items', 'terms', 'timeline', 'map'] },
  { name: '故事主线', keys: ['mainline', 'conflict', 'suspense', 'subplots'] },
  { name: '人物与伏笔', keys: ['protagonist', 'supporting', 'antagonist', 'foreshadow', 'taboos'] },
]
const halfKeys = new Set(['genre', 'person', 'audience', 'style', 'places', 'items',
  'conflict', 'suspense', 'protagonist', 'supporting', 'antagonist', 'foreshadow'])
const oneLine = new Set(['genre', 'person', 'audience', 'style', 'places', 'items', 'conflict', 'suspense'])

const labelOf = computed<Record<string, string>>(() =>
  Object.fromEntries(schema.value?.sb_fields || []))
const extraKeys = computed(() =>
  (schema.value?.sb_fields || []).map(([k]) => k).filter(k => !groups.some(g => g.keys.includes(k))))

/* 卡片式页签：分类提升为 tab，一次只看一组（同「设定图谱」页交互） */
type Tab = 'basic' | 'world' | 'plot' | 'people' | 'extra'
const tab = ref<Tab>('basic')
const TAB_DEF: { key: Tab; label: string; icon: string }[] = [
  { key: 'basic', label: '基础信息', icon: 'file' },
  { key: 'world', label: '世界观与设定', icon: 'dashboard' },
  { key: 'plot', label: '故事主线', icon: 'arrowR' },
  { key: 'people', label: '人物与伏笔', icon: 'eye' },
]
const tabsAll = computed(() => [
  ...TAB_DEF.map(t => ({ ...t, count: groups.find(g => g.name === t.label)?.keys.length || 0 })),
  ...(extraKeys.value.length
    ? [{ key: 'extra' as Tab, label: '其他要素', icon: 'settings', count: extraKeys.value.length }]
    : []),
])
const curGroup = computed(() => groups[TAB_DEF.findIndex(t => t.key === tab.value)])

/* 题材 / 文风 / 人称 / 读者定位：本来就是自由文本，但多数场景从固定词表里挑。
   给一个「预设追加」下拉，选中后以「、」拼到文本框里，既统一选择交互，也保留自由填写。 */
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
}
/* 人物 / 道具：改成「从角色卡 / 道具功法里多选」，选项即实体名称，天然和卡片一一对应。
   文本里识别出的名称作为已选项回显——改名由服务端同步替换文本；删卡后名称不在选项里，
   选中态随之消失，不会出现「卡片没了、大纲还挂着旧名」的不一致。 */
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
/** 字段文本里「恰好等于某个选项」的名称，才是已关联的实体 */
function linkSelected(k: string): string[] {
  const opts = new Set(linkOptions.value[k] || [])
  const out: string[] = []
  for (const t of splitTokens(fields.value[k])) {
    if (opts.has(t) && !out.includes(t)) out.push(t)
  }
  return out
}
/** 只删被分隔符包住的整名，描述性文字（「主角林辰，十九岁…」）原样保留 */
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
}
</script>

<template>
  <div v-if="!state.books.length" class="card"><EmptyBox title="还没有作品" desc="先「新建作品」并完成拆解" /></div>
  <div v-else-if="!raw" class="card"><EmptyBox title="请选择作品" desc="在左侧作品集合中选择一本书" /></div>
  <template v-else>
    <div class="page-head"><div><h1>作品大纲</h1>
      <p>全书要素：题材、视角、世界观、力量体系等——扩写与审查时注入 AI 的核心设定。</p></div>
    </div>
    <div class="card page-card">
      <div class="ol-topbar">
        <div class="ol-tabs">
          <button v-for="t in tabsAll" :key="t.key" :class="{ active: tab === t.key }" @click="tab = t.key">
            <Icon :name="t.icon" :size="13" /> {{ t.label }}
            <span class="tab-n">{{ t.count }}</span>
          </button>
        </div>
        <div class="ol-acts">
          <BackLink />
          <button class="btn" :disabled="saving" @click="save()"><Icon name="check" :size="15" /> 保存</button>
        </div>
      </div>
      <div class="form-scroll">
      <div class="form-grid" style="padding: 4px 6px 8px 2px">
        <template v-if="tab !== 'extra' && curGroup">
          <div v-for="k in curGroup.keys" :key="k" :class="halfKeys.has(k) ? '' : 'full'">
            <div class="field" style="margin-bottom:0">
              <label>{{ labelOf[k] || k }}</label>
              <div v-if="LINK_MAP[k]" class="ol-link">
                <SearchMultiSelect :model-value="linkSelected(k)"
                                   :options="linkOptions[k] || []"
                                   :tone="LINK_MAP[k]"
                                   :placeholder="LINK_MAP[k] === 'item' ? '从道具功法里选择关联' : '从角色卡里选择关联'"
                                   @update:model-value="v => setLinks(k, v)" />
              </div>
              <div v-if="PRESET_MAP[k]" class="ol-preset">
                <SelectBox compact :model-value="''" :options="PRESET_MAP[k]" allow-custom
                           placeholder="从预设里选一个追加，或在下方自由填写"
                           @update:model-value="v => appendPreset(k, v)" />
              </div>
              <textarea class="textarea" v-model="fields[k]"
                        :style="{ minHeight: oneLine.has(k) ? '38px' : '72px' }"></textarea>
            </div>
          </div>
        </template>
        <template v-else>
          <div v-for="k in extraKeys" :key="k" class="full">
            <div class="field" style="margin-bottom:0">
              <label>{{ labelOf[k] || k }}</label>
              <textarea class="textarea" v-model="fields[k]" style="min-height:56px"></textarea>
            </div>
          </div>
        </template>
      </div>
      </div>
      <!-- 手机：保存常驻底部，长表单不用滚回顶部 -->
      <div class="m-save-bar">
        <button class="btn lg" :disabled="saving" @click="save()">
          <Icon name="check" :size="16" /> 保存大纲</button>
      </div>
    </div>
  </template>
</template>

<style scoped>
.ol-preset { margin-bottom: 6px; }
.ol-link { margin-bottom: 6px; }
/* 卡片式页签顶栏（同设定图谱页）：左页签 + 右操作，底部分割线，内容区内部滚动 */
.ol-topbar { display: flex; align-items: center; gap: 12px; padding: 8px 14px 0;
  border-bottom: 1px solid var(--border); flex: none; flex-wrap: wrap; row-gap: 6px; }
.ol-tabs { display: flex; gap: 2px; flex: 1; min-width: 0; flex-wrap: wrap; }
.ol-tabs button { display: flex; align-items: center; gap: 6px; border: none; background: none;
  cursor: pointer; padding: 8px 12px; font-size: 13px; color: var(--text-2);
  border-radius: 8px 8px 0 0; transition: color .15s; }
.ol-tabs button:hover:not(.active) { color: var(--text); }
.ol-tabs button.active { color: var(--text); font-weight: 700; background: var(--bg); }
.tab-n { font-size: 10px; background: var(--border-strong); color: var(--text-2);
  border-radius: 999px; padding: 0 6px; line-height: 15px; }
.ol-acts { display: flex; align-items: center; gap: 10px; flex: none; padding-bottom: 8px; }

/* 手机：页签改成一条可横滑的胶囊条，保存固定在右侧；返回入口交给底部「概览」 */
@media (max-width: 760px) {
  .ol-topbar { flex-wrap: nowrap; align-items: center; gap: 8px; padding: 8px 12px;
    position: sticky; top: 0; z-index: 6;
    background: var(--card); }
  .ol-tabs { flex-wrap: nowrap; overflow-x: auto; gap: 6px; padding-bottom: 2px;
    scrollbar-width: none; -webkit-overflow-scrolling: touch; }
  .ol-tabs::-webkit-scrollbar { display: none; }
  .ol-tabs button { flex: none; border: 1px solid var(--border); background: var(--card);
    padding: 8px 12px; border-radius: 10px; white-space: nowrap; }
  .ol-tabs button.active { background: var(--primary-bg); border-color: transparent;
    color: var(--primary); font-weight: 600; }
  .ol-acts { padding-bottom: 0; display: none; }
  .form-scroll { padding: 8px 12px 92px; }
  .form-scroll .form-grid { padding: 4px 0 8px !important; }
}
</style>
