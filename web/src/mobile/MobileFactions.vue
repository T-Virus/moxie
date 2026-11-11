<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import Icon from '../components/Icon.vue'
import Modal from '../components/Modal.vue'
import BatchRename from '../components/BatchRename.vue'
import MobilePicker from './MobilePicker.vue'
import { api } from '../api'
import { state, store } from '../store'
import { useBookDoc } from '../composables/useBookDoc'
import { confirmBox, toast } from '../ui'
import { FACTION_CATEGORIES, FACTION_RELATIONS, factionCategoryMeta, factionRelationMeta, pct, tagStyle } from '../cardMeta'
import { STANCES, stanceMeta } from '../factionMeta'
import { normUnit } from '../utils'
import type { SbSchema } from '../types'

const { raw, factions, saving, load, save, batchRename } = useBookDoc()
const schema = ref<SbSchema | null>(null)
const kw = ref('')
const catFilter = ref('')
const visible = ref(36)
const dirty = ref(false)
const detail = ref<number | null>(null)
/* 新增卡先本地挂着，填好名称点「完成」才写盘（无名卡会被服务端过滤掉） */
const newIdx = ref(-1)
const nameInput = ref<HTMLInputElement | null>(null)
const renameOpen = ref(false)
const renameRef = ref<any>(null)

onMounted(async () => {
  store.loadBooks().catch(() => {})
  load()
  try { schema.value = await api.getSchema() } catch { /* 忽略 */ }
})
watch(() => store.curBook(), () => {
  dirty.value = false; detail.value = null; newIdx.value = -1
  kw.value = ''; catFilter.value = ''
})
onBeforeRouteLeave(async () => {
  if (dirty.value) {
    const ok = await save(true)
    if (!ok) return false
    dirty.value = false
  }
  return true
})

const FALLBACK = ['name', 'category', 'stance', 'relTo', 'relType', 'relStrength',
  'relPublic', 'relations', 'desc']
const fieldKeys = computed(() => (schema.value?.faction_fields || FALLBACK.map(k => [k, k] as [string, string])).map(([k]) => k))

const filters = computed(() => {
  const all = [{ label: '', name: '全部', n: factions.value.length }]
  const items = FACTION_CATEGORIES.map(m => ({
    label: m.label, name: m.label,
    n: factions.value.filter(f => String(f.category || '') === m.label).length,
  })).filter(x => x.n > 0)
  return [...all, ...items]
})

const rows = computed(() => {
  const k = kw.value.trim().toLowerCase()
  return factions.value.map((c, i) => ({ c, i }))
    .filter(r => !catFilter.value || String(r.c.category || '') === catFilter.value)
    .filter(r => !k || String(r.c.name || '').toLowerCase().includes(k))
})
const shown = computed(() => rows.value.slice(0, visible.value))
const hasMore = computed(() => rows.value.length > visible.value)
watch([kw, catFilter], () => { visible.value = 36 })

const cur = computed(() => (detail.value !== null ? factions.value[detail.value] : null))
const factionNames = computed(() => factions.value.map(f => String(f.name || '')).filter(Boolean)
  .filter(n => n !== String(cur.value?.name || '')))

const catOf = (v: any) => factionCategoryMeta(v)
const stanceOf = (v: any) => stanceMeta(v)
const relOf = (v: any) => factionRelationMeta(v)
const cardColor = (c: Record<string, string>) =>
  catOf(c.category)?.color || stanceOf(c.stance)?.color || '#7c8a84'
const cardTint = (c: Record<string, string>) =>
  catOf(c.category)?.bg || stanceOf(c.stance)?.bg || '#f2f4f0'

function touch() { dirty.value = true }
function open(i: number) { newIdx.value = -1; detail.value = i }
/* 关闭抽屉即保存；新增但没填名称的卡本地丢弃 */
async function close() {
  if (detail.value === null) return
  if (newIdx.value === detail.value) {
    if (!String(cur.value?.name || '').trim()) {
      factions.value.splice(detail.value, 1)
      newIdx.value = -1
      detail.value = null
      dirty.value = false
      return
    }
    newIdx.value = -1
  }
  if (dirty.value) {
    const ok = await save(true)
    if (!ok) return
    dirty.value = false
  }
  detail.value = null
}
function addFaction() {
  const item: Record<string, string> = {}
  for (const k of fieldKeys.value) item[k] = ''
  factions.value.push(item)
  newIdx.value = factions.value.length - 1
  dirty.value = true
  catFilter.value = ''
  kw.value = ''
  visible.value = 36
  detail.value = factions.value.length - 1
  nextTick(() => nameInput.value?.focus())
}
async function delFaction() {
  if (detail.value === null) return
  if (newIdx.value === detail.value) {
    factions.value.splice(detail.value, 1)
    newIdx.value = -1
    detail.value = null
    dirty.value = false
    toast('已取消新增', 'ok')
    return
  }
  if (!await confirmBox('删除这张势力卡？章节与角色卡里的关联引用也会同步移除。', { danger: true, ok: '删除' })) return
  factions.value.splice(detail.value, 1)
  detail.value = null
  const ok = await save(true)
  dirty.value = false
  if (!ok) { load(); return }
  toast('已删除，关联引用已同步', 'ok')
}
async function applyRename(mapping: Record<string, string>) {
  const ok = await batchRename('factions', mapping)
  if (ok) {
    renameOpen.value = false
    toast('已改名，章节与关系中的引用已同步', 'ok')
  } else {
    renameRef.value?.resetBusy()
  }
}
</script>

<template>
  <div class="m-page m-page-fixed">
    <div class="m-head">
      <div>
        <h1>势力表</h1>
        <p>{{ factions.length }} 个势力 · 门派、组织、阵营与相互关系</p>
      </div>
      <div class="m-head-act">
        <button class="m-btn sm ghost" :disabled="!raw || !factions.length" @click="renameOpen = true">
          <Icon name="edit" :size="14" /> 改名
        </button>
        <button class="m-btn sm" :disabled="!raw" @click="addFaction">
          <Icon name="plus" :size="14" /> 新增
        </button>
      </div>
    </div>

    <div v-if="!state.books.length" class="m-empty" style="padding-top:70px">
      <span class="m-empty-ico"><Icon name="flag" :size="28" /></span>
      <b>还没有作品</b>
      <p>先新建作品并完成拆解，势力表会自动提取到这里。</p>
    </div>

    <div v-else-if="!raw" class="m-empty" style="padding-top:70px">
      <span class="m-empty-ico"><Icon name="refresh" :size="28" /></span>
      <b>正在载入势力表</b>
      <p>从本地作品数据里读取势力设定…</p>
    </div>

    <template v-else>
      <!-- 固定区：搜索 + 阵营筛选，列表单独滚动 -->
      <div class="m-head-fixed">
        <div class="m-searchbar">
          <Icon name="search" :size="16" />
          <input v-model="kw" placeholder="搜索势力名称" />
          <button v-if="kw" class="m-clear" @click="kw = ''"><Icon name="close" :size="13" /></button>
        </div>

        <div class="m-chips">
          <button v-for="f in filters" :key="f.name" class="m-chip" :class="{ on: catFilter === f.label }"
                  @click="catFilter = f.label">
            {{ f.name }}<span class="m-chip-n">{{ f.n }}</span>
          </button>
        </div>
      </div>

      <div class="m-page-scroll">
      <div v-if="factions.length" class="m-rows" style="margin-top:9px">
        <button v-for="r in shown" :key="r.i" class="m-row-card" @click="open(r.i)">
          <span class="m-row-accent" :style="{ background: cardColor(r.c) }"></span>
          <span class="m-avatar" :style="{ background: cardTint(r.c), color: cardColor(r.c) }">
            <Icon name="flag" :size="20" />
          </span>
          <span class="m-row-main">
            <span class="m-row-title"><b>{{ r.c.name || '未命名势力' }}</b></span>
            <span class="m-row-tags">
              <span v-if="r.c.category" class="m-tag" :style="tagStyle(catOf(r.c.category))">{{ r.c.category }}</span>
              <span v-if="r.c.stance" class="m-tag" :style="tagStyle(stanceOf(r.c.stance))">{{ r.c.stance }}</span>
              <span v-if="r.c.relType" class="m-tag gray">{{ r.c.relType }}</span>
            </span>
            <span v-if="r.c.desc" class="m-row-desc">{{ r.c.desc }}</span>
          </span>
          <Icon name="right" :size="14" class="m-row-arrow" style="margin-top:4px" />
        </button>

        <button v-if="hasMore" class="m-load-more" @click="visible += 40">
          还有 {{ rows.length - visible }} 个，加载更多
        </button>
      </div>

      <div v-else class="m-empty">
        <span class="m-empty-ico"><Icon name="flag" :size="28" /></span>
        <b>{{ factions.length ? '没有匹配的势力' : '暂无势力卡' }}</b>
        <p>{{ factions.length ? '换个关键词或清除筛选试试。' : '拆解时会自动提取势力，也可以点右上角「新增」手动添加。' }}</p>
      </div>
      </div>

      <Modal :open="detail !== null" :title="cur?.name ? '势力 · ' + cur.name : '势力卡'" @update:open="v => { if (!v) close() }">
        <div v-if="cur" class="m-modal-form" @input="touch" @change="touch">
          <div class="m-modal-hero">
            <span class="m-avatar" :style="{ background: cardTint(cur), color: cardColor(cur) }">
              <Icon name="flag" :size="21" />
            </span>
            <div class="m-modal-name">
              <input ref="nameInput" class="m-input" v-model="cur.name" placeholder="未命名势力" />
            </div>
          </div>

          <div class="m-sec-title" style="margin-top:2px">基本信息</div>
          <div class="m-field">
            <label>势力大类<em>{{ catOf(cur.category)?.example || '属于哪一类组织' }}</em></label>
            <div class="m-pick">
              <button v-for="m in FACTION_CATEGORIES" :key="m.key" :class="{ on: cur.category === m.label }"
                      :style="cur.category === m.label ? tagStyle(m) : undefined"
                      @click="cur.category = cur.category === m.label ? '' : m.label; touch()">{{ m.label }}</button>
            </div>
          </div>

          <div class="m-field">
            <label>立场<em>{{ stanceOf(cur.stance)?.note || '对主角的态度' }}</em></label>
            <div class="m-pick">
              <button v-for="m in STANCES" :key="m.key" :class="{ on: cur.stance === m.label }"
                      :style="cur.stance === m.label ? tagStyle(m) : undefined"
                      @click="cur.stance = cur.stance === m.label ? '' : m.label; touch()">{{ m.label }}</button>
            </div>
          </div>

          <div class="m-sec-title">势力关系<span class="m-hint" style="margin-left:6px;font-weight:400">与谁、什么关系</span></div>
          <div class="m-form-2">
            <div class="m-field">
              <label>关联势力</label>
              <MobilePicker v-model="cur.relTo" title="选择关联势力"
                            :options="factionNames" placeholder="— 未填 —"
                            @update:model-value="touch" />
            </div>
            <div class="m-field">
              <label>势力关系<em>{{ relOf(cur.relType)?.note || '' }}</em></label>
              <MobilePicker v-model="cur.relType" title="选择势力关系"
                            :options="FACTION_RELATIONS.map(m => m.label)" placeholder="— 未填 —"
                            @update:model-value="touch" />
            </div>
            <div class="m-field">
              <label>关系强度<em>{{ pct(cur.relStrength) || '0 ~ 1' }}</em></label>
              <input class="m-input" v-model="cur.relStrength" placeholder="0.9"
                     @blur="cur.relStrength = normUnit(cur.relStrength)" />
            </div>
            <div class="m-field">
              <label>关系公开</label>
              <div class="m-seg">
                <button v-for="v in ['是', '否']" :key="v" :class="{ on: cur.relPublic === v }"
                        @click="cur.relPublic = cur.relPublic === v ? '' : v; touch()">{{ v }}</button>
              </div>
            </div>
          </div>
          <div class="m-field">
            <label>其他势力关系<em>一行一条：势力｜关系｜强度</em></label>
            <textarea class="m-textarea" v-model="cur.relations" style="min-height:82px"
                      placeholder="如：青云宗｜敌对｜0.9"></textarea>
          </div>

          <div class="m-sec-title">其他</div>
          <div class="m-field">
            <label>简介</label>
            <textarea class="m-textarea" v-model="cur.desc" style="min-height:104px"
                      placeholder="势力的来历、构成、目标与当前处境…"></textarea>
          </div>
        </div>

        <template #footer>
          <div class="m-modal-foot">
            <button class="m-btn del" title="删除势力" @click="delFaction"><Icon name="trash" :size="16" /></button>
            <button class="m-btn" :disabled="saving" @click="close">
              <Icon name="check" :size="15" /> {{ saving ? '保存中…' : '完成' }}
            </button>
          </div>
        </template>
      </Modal>
    </template>
  </div>

  <BatchRename ref="renameRef" :open="renameOpen" kind="factions" title="批量修改势力名"
               desc-key="desc" :entities="factions" mobile
               @update:open="v => renameOpen = v" @apply="applyRename" />
</template>
