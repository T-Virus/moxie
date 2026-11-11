<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import Icon from '../components/Icon.vue'
import BackLink from '../components/BackLink.vue'
import EmptyBox from '../components/EmptyBox.vue'
import BatchRename from '../components/BatchRename.vue'
import SelectBox from '../components/SelectBox.vue'
import { api } from '../api'
import { store, state } from '../store'
import { useBookDoc } from '../composables/useBookDoc'
import { confirmBox, toast } from '../ui'
import type { SbSchema } from '../types'

/* 道具 / 功法：与角色卡、势力表同级的世界观实体，拆解 / 改编时自动提取 */
const { raw, cards, factions, items, saving, load, save, batchRename } = useBookDoc()
const schema = ref<SbSchema | null>(null)
const renameOpen = ref(false)
const renameRef = ref<any>(null)
const scrollEl = ref<HTMLElement | null>(null)

onMounted(async () => {
  store.loadBooks().catch(() => {})
  load()
  try { schema.value = await api.getSchema() } catch { /* 忽略 */ }
})

const FALLBACK_FIELDS: [string, string][] = [
  ['name', '名称'], ['kind', '类别'], ['grade', '品阶'], ['owner', '持有者'],
  ['faction', '所属势力'], ['chapter', '首次出现'], ['effect', '效果用途'],
  ['origin', '来历'], ['desc', '简介'],
]
const fieldKeys = computed(() => (schema.value?.item_fields || FALLBACK_FIELDS).map(([k]) => k))
const fields = computed<[string, string][]>(() => schema.value?.item_fields || FALLBACK_FIELDS)
const labelOf = (k: string) => fields.value.find(([x]) => x === k)?.[1] || k
const kindOptions = computed(() => (schema.value?.item_kinds || []).map(([, lb]) => lb))

/* 下拉选项：候选项 + 不在候选里的旧值（显示标注，保存原值） */
function withLegacy(options: string[], cur: string, legacyLabel = '（旧值）') {
  const out: { label: string; value: string }[] = []
  if (cur && !options.includes(cur)) out.push({ label: cur + legacyLabel, value: cur })
  for (const o of options) out.push({ label: o, value: o })
  return out
}

/* ---- 搜索 + 分页 ---- */
const PAGE_SIZE = 8
const kw = ref('')
const kindFilter = ref('')
const page = ref(1)
const rows = computed(() => {
  const k = kw.value.trim().toLowerCase()
  return items.value.map((c, i) => ({ c, i }))
    .filter(r => !kindFilter.value || String(r.c.kind || '') === kindFilter.value)
    .filter(r => !k || ['name', 'effect', 'origin', 'desc', 'owner', 'faction']
      .some(f => String(r.c[f] || '').toLowerCase().includes(k)))
})
const pageCount = computed(() => Math.max(1, Math.ceil(rows.value.length / PAGE_SIZE)))
const pageStart = computed(() => (Math.min(page.value, pageCount.value) - 1) * PAGE_SIZE)
const pageRows = computed(() => rows.value.slice(pageStart.value, pageStart.value + PAGE_SIZE))

watch(pageCount, n => { if (page.value > n) page.value = n })
watch([kw, kindFilter], () => {
  page.value = 1
  nextTick(() => { if (scrollEl.value) scrollEl.value.scrollTop = 0 })
})
watch(() => store.curBook(), () => {
  kw.value = ''
  kindFilter.value = ''
  page.value = 1
  if (scrollEl.value) scrollEl.value.scrollTop = 0
})

function goPage(p: number) {
  const n = Math.min(Math.max(1, Math.round(p) || 1), pageCount.value)
  if (n === page.value) return
  page.value = n
  nextTick(() => { if (scrollEl.value) scrollEl.value.scrollTop = 0 })
}

const charNames = computed(() => cards.value.map(c => String(c.name || '')).filter(Boolean))
const factionNames = computed(() => factions.value.map(f => String(f.name || '')).filter(Boolean))

/* 名称在头部单独渲染，其余字段按「基本 / 归属 / 说明」分组 */
const GROUPS = computed<[string, string[]][]>(() => {
  const g = schema.value?.item_groups
  if (g?.length) return g
  return [['基本', ['kind', 'grade']], ['归属', ['owner', 'faction', 'chapter']],
          ['说明', ['effect', 'origin', 'desc']]]
})
const cardGroups = computed(() => {
  const out: [string, string[]][] = []
  for (const [title, keys] of GROUPS.value) {
    const ks = keys.filter(k => k !== 'name' && fieldKeys.value.includes(k))
    if (ks.length) out.push([title, ks])
  }
  return out
})

const KIND_COLOR: Record<string, string> = {
  剧情道具: '#4d7ee8', 武学功法: '#0ca678', 战技: '#e8590c', 兵器: '#868e96',
  丹药: '#d6336c', 法宝: '#7048e8', 线索: '#f08c00', 其他: '#adb5bd',
}
const kindColor = (v: string) => KIND_COLOR[v] || '#adb5bd'

function addItem() {
  if (!schema.value) return
  const obj: Record<string, string> = {}
  for (const k of fieldKeys.value) obj[k] = ''
  items.value.push(obj)
  kw.value = ''
  kindFilter.value = ''
  nextTick(() => {
    page.value = pageCount.value
    nextTick(() => {
      if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
      const inputs = scrollEl.value?.querySelectorAll<HTMLInputElement>('.entity-card .name-in')
      inputs?.[inputs.length - 1]?.focus()
    })
  })
}

async function delItem(i: number) {
  if (!await confirmBox('删除这张道具 / 功法卡？章节里对它的引用也会一并移除。', { danger: true, ok: '删除' })) return
  items.value.splice(i, 1)
  /* 删除后立即整包保存：服务端会把章节 items 与相关引用同步清掉 */
  const ok = await save(true)
  if (ok) toast('已删除，章节引用已同步', 'ok')
}

async function applyRename(mapping: Record<string, string>) {
  const ok = await batchRename('items', mapping)
  if (ok) {
    renameOpen.value = false
    toast('已改名，章节与关联数据已同步', 'ok')
  } else {
    renameRef.value?.resetBusy()
  }
}
</script>

<template>
  <div v-if="!state.books.length" class="card"><EmptyBox title="还没有作品" desc="先「新建作品」并完成拆解" /></div>
  <div v-else-if="!raw" class="card"><EmptyBox title="请选择作品" desc="在左侧作品集合中选择一本书" /></div>
  <template v-else>
    <div class="page-head"><div><h1>道具功法</h1>
      <p>剧情道具、武学功法、战技、丹药与法宝——与角色卡、势力表同级，拆解 / 改编时自动提取，改名与删除会同步章节引用。</p></div>
    </div>
    <div class="card page-card">
      <div class="toolbar">
        <BackLink class="m-back" />
        <span class="hint">
          {{ kw || kindFilter ? `匹配 ${rows.length} / 共 ${items.length} 件` : `共 ${items.length} 件` }}</span>
        <div class="tb-right">
          <div class="tb-search">
            <input class="input" v-model="kw" placeholder="搜索名称 / 效果 / 持有者" />
            <button v-if="kw" class="link-btn" @click="kw = ''">清除</button>
          </div>
          <div class="tb-pager">
            <button class="btn ghost icon-only" :disabled="page <= 1" title="上一页" @click="goPage(page - 1)">
              <Icon name="left" :size="14" /></button>
            <span class="hint">{{ page }} / {{ pageCount }}</span>
            <button class="btn ghost icon-only" :disabled="page >= pageCount" title="下一页" @click="goPage(page + 1)">
              <Icon name="right" :size="14" /></button>
          </div>
          <div class="tb-acts">
            <button class="btn ghost" :disabled="!items.length" @click="renameOpen = true">
              <Icon name="edit" :size="14" /> 批量改名</button>
            <button class="btn ghost" @click="addItem"><Icon name="plus" :size="14" /> 加道具</button>
            <button class="btn m-save-hide" :disabled="saving" @click="save()"><Icon name="check" :size="15" /> 保存</button>
          </div>
        </div>
      </div>

      <div class="kind-bar" v-if="kindOptions.length">
        <button class="kind-chip" :class="{ on: !kindFilter }" @click="kindFilter = ''">
          全部 {{ items.length }}</button>
        <button v-for="k in kindOptions" :key="k" class="kind-chip" :class="{ on: kindFilter === k }"
                @click="kindFilter = kindFilter === k ? '' : k">
          <i class="kind-dot" :style="{ background: kindColor(k) }"></i>{{ k }}
          {{ items.filter(x => String(x.kind || '') === k).length }}
        </button>
      </div>

      <div class="form-scroll" ref="scrollEl">
        <div v-if="rows.length" class="entity-cards">
          <div v-for="r in pageRows" :key="r.i" class="entity-card item-card"
               :style="{ borderLeftColor: kindColor(String(r.c.kind || '')) }">
            <div class="ec-head">
              <span class="ec-avatar" :style="{ background: kindColor(String(r.c.kind || '')) }">
                {{ (r.c.name || '?').slice(0, 1) }}</span>
              <input class="name-in" v-model="r.c.name" placeholder="未命名道具 / 功法" />
              <span v-if="r.c.kind" class="tag" :style="{ color: kindColor(r.c.kind), background: kindColor(r.c.kind) + '18' }">
                {{ r.c.kind }}</span>
              <span v-if="r.c.grade" class="tag gray">{{ r.c.grade }}</span>
            </div>
            <button class="rm" title="删除该条目" @click="delItem(r.i)">
              <Icon name="trash" :size="13" /></button>

            <div class="ef">
              <template v-for="[title, keys] in cardGroups" :key="title">
                <div class="sec-label full">{{ title }}</div>
                <div v-for="k in keys" :key="k">
                  <div class="field" style="margin-bottom:0">
                    <label>{{ labelOf(k) }}<em v-if="k === 'owner' && !charNames.length" class="lf-note">角色池为空</em>
                      <em v-else-if="k === 'faction' && !factionNames.length" class="lf-note">势力表为空</em></label>

                    <SelectBox v-if="k === 'kind'" compact allow-empty :model-value="r.c.kind"
                               :options="withLegacy(kindOptions, r.c.kind)"
                               @update:model-value="v => r.c.kind = v" />

                    <SelectBox v-else-if="k === 'owner'" compact allow-empty :model-value="r.c.owner"
                               :options="withLegacy(charNames, r.c.owner, '（不在角色池）')"
                               @update:model-value="v => r.c.owner = v" />

                    <SelectBox v-else-if="k === 'faction'" compact allow-empty :model-value="r.c.faction"
                               :options="withLegacy(factionNames, r.c.faction, '（不在势力表）')"
                               @update:model-value="v => r.c.faction = v" />

                    <textarea v-else-if="k === 'desc' || k === 'effect' || k === 'origin'" class="textarea"
                              style="min-height:58px" v-model="r.c[k]" :placeholder="labelOf(k)"></textarea>

                    <input v-else-if="k === 'chapter'" class="input" inputmode="numeric"
                           v-model="r.c.chapter" placeholder="如 12" />

                    <input v-else class="input" v-model="r.c[k]" :placeholder="labelOf(k)" />
                  </div>
                </div>
              </template>
            </div>
          </div>
        </div>
        <EmptyBox v-else-if="!items.length" title="暂无道具 / 功法"
                  desc="拆解 / 改编时会自动提取；也可以点击「加道具」手动添加" />
        <EmptyBox v-else title="没有匹配的条目" desc="换个关键词或类别试试，或点击「清除」查看全部" />
      </div>

      <div class="m-save-bar">
        <button class="btn lg" :disabled="saving" @click="save()">
          <Icon name="check" :size="16" /> 保存道具功法</button>
      </div>
    </div>
  </template>

  <BatchRename ref="renameRef" :open="renameOpen" kind="items" title="批量修改道具 / 功法名"
               desc-key="effect" :entities="items" @update:open="v => renameOpen = v"
               @apply="applyRename" />
</template>

<style scoped>
.kind-bar {
  display: flex; gap: 6px; flex-wrap: wrap; padding: 10px;
}
.kind-chip {
  display: inline-flex; align-items: center; gap: 5px; height: 28px; padding: 0 10px;
  border: 1px solid var(--border-strong); border-radius: 14px; background: #fff;
  color: var(--text-2); font-size: 12px; cursor: pointer; font-family: inherit;
}
.kind-chip.on { border-color: var(--primary); color: var(--primary); background: #eef4ff; }
.kind-dot { width: 7px; height: 7px; border-radius: 50%; }
.item-card { border-left: 4px solid #adb5bd; }
.item-card .ec-head { flex-wrap: wrap; }
.item-card .ec-head .name-in { flex: 1 1 140px; min-width: 110px; }
.item-card .lf-note { font-size: 11px; font-weight: 400; color: var(--text-3); margin-left: 6px; }
</style>
