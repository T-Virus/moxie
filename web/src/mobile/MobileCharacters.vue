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
import { ALIGNMENTS, ALIGN_AXES, FACTION_CATEGORIES, RACES, RELATIONS, ROLES, alignmentMeta, factionCategoryMeta, pct, roleMeta, tagStyle } from '../cardMeta'
import { STANCES, stanceMeta } from '../factionMeta'
import { genderTag, normUnit } from '../utils'
import type { SbSchema } from '../types'

const { raw, cards, factions, saving, load, save, batchRename } = useBookDoc()
const schema = ref<SbSchema | null>(null)
const kw = ref('')
const roleFilter = ref('')
const visible = ref(36)
const dirty = ref(false)
const detail = ref<number | null>(null)
/* 新增卡的本地下标：新增时先不写盘，等用户填好名称、点「完成」再保存。
   直接带着空名称保存会被服务端当作无名卡过滤掉，回显时卡片凭空消失。 */
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
  kw.value = ''; roleFilter.value = ''
})
onBeforeRouteLeave(async () => {
  /* 保存失败（比如本书正有任务在跑）时留在原页，避免编辑内容静默丢失 */
  if (dirty.value) {
    const ok = await save(true)
    if (!ok) return false
    dirty.value = false
  }
  return true
})

/* 角色卡字段：拿不到 schema 时用内置字段兜底，保证编辑不空 */
const FALLBACK = ['name', 'gender', 'race', 'role', 'alignment', 'stance', 'factionCategory', 'factionName',
  'subFaction', 'loyalty', 'joinChapter', 'leaveChapter', 'relationTo', 'relationType',
  'relationDirection', 'relationStrength', 'isPublic', 'chapter', 'relations',
  'identity', 'personality', 'speech', 'catchwords', 'weakness', 'goal']
const fieldKeys = computed(() => (schema.value?.card_fields || FALLBACK.map(k => [k, k] as [string, string])).map(([k]) => k))
const labels = computed<Record<string, string>>(() =>
  Object.fromEntries(schema.value?.card_fields || FALLBACK.map(k => [k, k])))

const filters = computed(() => {
  const all = [{ label: '', name: '全部', n: cards.value.length }]
  const items = ROLES.map(m => ({
    label: m.label, name: m.label,
    n: cards.value.filter(c => String(c.role || '') === m.label).length,
  })).filter(x => x.n > 0)
  return [...all, ...items]
})

const rows = computed(() => {
  const k = kw.value.trim().toLowerCase()
  return cards.value.map((c, i) => ({ c, i }))
    .filter(r => !roleFilter.value || String(r.c.role || '') === roleFilter.value)
    .filter(r => !k || String(r.c.name || '').toLowerCase().includes(k))
})
const shown = computed(() => rows.value.slice(0, visible.value))
const hasMore = computed(() => rows.value.length > visible.value)
watch([kw, roleFilter], () => { visible.value = 36 })

const cur = computed(() => (detail.value !== null ? cards.value[detail.value] : null))
const cardNames = computed(() => cards.value.map(c => String(c.name || '')).filter(Boolean))
const factionNames = computed(() => factions.value.map(f => String(f.name || '')).filter(Boolean))
const alignRows = computed(() => ALIGN_AXES.rows.map((_, ri) => ALIGNMENTS.filter(m => m.row === ri)))
const categories = FACTION_CATEGORIES
const relationTypes = RELATIONS.map(r => r.label)

const roleOf = (v: any) => roleMeta(v)
const alignOf = (v: any) => alignmentMeta(v)
const stanceOf = (v: any) => stanceMeta(v)
const catOf = (v: any) => factionCategoryMeta(v)
const avatarColor = (c: Record<string, string>) => {
  const g = String(c.gender || '')
  return g.includes('女') ? '#d96b93' : g.includes('男') ? '#4d7ee8' : '#7c8a84'
}
const descOf = (c: Record<string, string>) =>
  String(c.identity || c.personality || c.goal || '').trim()

function touch() { dirty.value = true }
function open(i: number) { newIdx.value = -1; detail.value = i }
/* 关闭抽屉即保存；新增但没填名称的卡本地丢弃（服务端会过滤无名卡，写盘也存不住） */
async function close() {
  if (detail.value === null) return
  if (newIdx.value === detail.value) {
    if (!String(cur.value?.name || '').trim()) {
      cards.value.splice(detail.value, 1)
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

function addCard() {
  const item: Record<string, string> = {}
  for (const k of fieldKeys.value) item[k] = ''
  cards.value.push(item)
  newIdx.value = cards.value.length - 1
  dirty.value = true
  roleFilter.value = ''
  kw.value = ''
  visible.value = 36
  detail.value = cards.value.length - 1
  nextTick(() => nameInput.value?.focus())
}
async function delCard() {
  if (detail.value === null) return
  /* 尚未保存的新卡：本地移除即可，不用请求服务端 */
  if (newIdx.value === detail.value) {
    cards.value.splice(detail.value, 1)
    newIdx.value = -1
    detail.value = null
    dirty.value = false
    toast('已取消新增', 'ok')
    return
  }
  if (!await confirmBox('删除这张角色卡？章节里的出场记录也会同步移除。', { danger: true, ok: '删除' })) return
  cards.value.splice(detail.value, 1)
  detail.value = null
  const ok = await save(true)
  dirty.value = false
  if (!ok) { load(); return }
  toast('已删除，关联引用已同步', 'ok')
}
function pickAlign(label: string) {
  if (!cur.value) return
  cur.value.alignment = cur.value.alignment === label ? '' : label
  touch()
}
async function applyRename(mapping: Record<string, string>) {
  const ok = await batchRename('characters', mapping)
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
        <h1>角色卡</h1>
        <p>{{ cards.length }} 位人物 · 身份、性格、目标与关系</p>
      </div>
      <div class="m-head-act">
        <button class="m-btn sm ghost" :disabled="!raw || !cards.length" @click="renameOpen = true">
          <Icon name="edit" :size="14" /> 改名
        </button>
        <button class="m-btn sm" :disabled="!raw" @click="addCard">
          <Icon name="plus" :size="14" /> 新增
        </button>
      </div>
    </div>

    <div v-if="!state.books.length" class="m-empty" style="padding-top:70px">
      <span class="m-empty-ico"><Icon name="user" :size="28" /></span>
      <b>还没有作品</b>
      <p>先新建作品并完成拆解，角色卡会自动提取到这里。</p>
    </div>

    <div v-else-if="!raw" class="m-empty" style="padding-top:70px">
      <span class="m-empty-ico"><Icon name="refresh" :size="28" /></span>
      <b>正在载入角色卡</b>
      <p>从本地作品数据里读取人物设定…</p>
    </div>

    <template v-else>
      <!-- 固定区：搜索 + 角色筛选，列表单独滚动 -->
      <div class="m-head-fixed">
        <div class="m-searchbar">
          <Icon name="search" :size="16" />
          <input v-model="kw" placeholder="搜索角色名称" />
          <button v-if="kw" class="m-clear" @click="kw = ''"><Icon name="close" :size="13" /></button>
        </div>

        <div class="m-chips">
          <button v-for="f in filters" :key="f.name" class="m-chip" :class="{ on: roleFilter === f.label }"
                  @click="roleFilter = f.label">
            {{ f.name }}<span class="m-chip-n">{{ f.n }}</span>
          </button>
        </div>
      </div>

      <div class="m-page-scroll">
      <div v-if="cards.length" class="m-rows" style="margin-top:9px">
        <button v-for="r in shown" :key="r.i" class="m-row-card" @click="open(r.i)">
          <span class="m-avatar" :style="{ background: avatarColor(r.c) }">{{ (r.c.name || '?').slice(0, 1) }}</span>
          <span class="m-row-main">
            <span class="m-row-title">
              <b>{{ r.c.name || '未命名人物' }}</b>
              <span v-if="r.c.gender" class="m-tag" :class="genderTag(r.c.gender)">{{ r.c.gender }}</span>
            </span>
            <span class="m-row-tags">
              <span v-if="r.c.role" class="m-tag" :style="tagStyle(roleOf(r.c.role))">{{ r.c.role }}</span>
              <span v-if="r.c.alignment" class="m-tag" :style="tagStyle(alignOf(r.c.alignment))">{{ r.c.alignment }}</span>
              <span v-if="r.c.stance" class="m-tag" :style="tagStyle(stanceOf(r.c.stance))">{{ r.c.stance }}</span>
              <span v-if="r.c.factionName" class="m-tag gray"><Icon name="flag" :size="10" />{{ r.c.factionName }}</span>
            </span>
            <span v-if="descOf(r.c)" class="m-row-desc">{{ descOf(r.c) }}</span>
          </span>
          <Icon name="right" :size="14" class="m-row-arrow" style="margin-top:4px" />
        </button>

        <button v-if="hasMore" class="m-load-more" @click="visible += 40">
          还有 {{ rows.length - visible }} 位，加载更多
        </button>
      </div>

      <div v-else class="m-empty">
        <span class="m-empty-ico"><Icon name="user" :size="28" /></span>
        <b>{{ cards.length ? '没有匹配的角色' : '暂无角色卡' }}</b>
        <p>{{ cards.length ? '换个关键词或清除筛选试试。' : '拆解时会自动提取人物，也可以点右上角「新增」手动添加。' }}</p>
      </div>
      </div>

      <!-- 角色详情 -->
      <Modal :open="detail !== null" :title="cur?.name ? '角色卡 · ' + cur.name : '角色卡'" @update:open="v => { if (!v) close() }">
        <div v-if="cur" class="m-modal-form" @input="touch" @change="touch">
          <div class="m-modal-hero">
            <span class="m-avatar" :style="{ background: avatarColor(cur) }">{{ (cur.name || '?').slice(0, 1) }}</span>
            <div class="m-modal-name">
              <input ref="nameInput" class="m-input" v-model="cur.name" placeholder="未命名人物" />
            </div>
          </div>

          <div class="m-sec-title" style="margin-top:2px">人设分析</div>
          <div class="m-field">
            <label>剧情功能<em>{{ roleOf(cur.role)?.note || '在故事里起什么作用' }}</em></label>
            <div class="m-pick">
              <button v-for="m in ROLES" :key="m.key" :class="{ on: cur.role === m.label }"
                      :style="cur.role === m.label ? tagStyle(m) : undefined"
                      @click="cur.role = cur.role === m.label ? '' : m.label; touch()">{{ m.label }}</button>
            </div>
          </div>

          <div class="m-field">
            <label>人设倾向<em>{{ alignOf(cur.alignment)?.note || '守序 / 中立 / 混乱 × 善良 / 中立 / 邪恶' }}</em></label>
            <div class="m-align-grid">
              <span></span>
              <span v-for="c in ALIGN_AXES.cols" :key="'c' + c" class="m-ag-axis">{{ c }}</span>
              <template v-for="(group, ri) in alignRows" :key="'r' + ri">
                <span class="m-ag-axis">{{ ALIGN_AXES.rows[ri] }}</span>
                <button v-for="m in group" :key="m.key" class="m-ag-cell" :class="{ on: cur.alignment === m.label }"
                        :style="cur.alignment === m.label ? tagStyle(m) : { background: m.bg, color: m.color }"
                        @click="pickAlign(m.label)">{{ m.label }}</button>
              </template>
            </div>
          </div>

          <div class="m-field">
            <label>对主角态度<em>{{ stanceOf(cur.stance)?.note || '当前与主角的关系位置' }}</em></label>
            <div class="m-pick">
              <button v-for="m in STANCES" :key="m.key" :class="{ on: cur.stance === m.label }"
                      :style="cur.stance === m.label ? tagStyle(m) : undefined"
                      @click="cur.stance = cur.stance === m.label ? '' : m.label; touch()">{{ m.label }}</button>
            </div>
          </div>

          <div class="m-field">
            <label>性别</label>
            <div class="m-seg">
              <button v-for="g in ['男', '女', '其他']" :key="g" :class="{ on: cur.gender === g }"
                      @click="cur.gender = cur.gender === g ? '' : g; touch()">{{ g }}</button>
            </div>
          </div>

          <div class="m-field">
            <label>种族<em>可选预设，也可直接输入自定义种族</em></label>
            <MobilePicker v-model="cur.race" title="选择或输入种族"
                          :options="RACES" placeholder="— 未设置 —" allow-custom
                          @update:model-value="touch" />
          </div>

          <div class="m-sec-title">势力归属</div>
          <div class="m-form-2">
            <div class="m-field">
              <label>势力大类<em>{{ catOf(cur.factionCategory)?.example || '' }}</em></label>
              <MobilePicker v-model="cur.factionCategory" title="选择势力大类"
                            :options="categories.map(m => m.label)" placeholder="— 无 / 未填 —"
                            @update:model-value="touch" />
            </div>
            <div class="m-field">
              <label>势力名称</label>
              <MobilePicker v-model="cur.factionName" title="选择势力"
                            :options="factionNames" placeholder="— 无 / 未填 —"
                            @update:model-value="touch" />
            </div>
            <div class="m-field">
              <label>下属分支</label>
              <input class="m-input" v-model="cur.subFaction" placeholder="如先锋营、暗卫队" />
            </div>
            <div class="m-field">
              <label>忠诚度<em>{{ pct(cur.loyalty) || '0 ~ 1' }}</em></label>
              <input class="m-input" v-model="cur.loyalty" placeholder="0.9" @blur="cur.loyalty = normUnit(cur.loyalty)" />
            </div>
            <div class="m-field">
              <label>加入章节</label>
              <input class="m-input" v-model="cur.joinChapter" placeholder="如 45" />
            </div>
            <div class="m-field">
              <label>脱离章节<em>仍在势力内留空</em></label>
              <input class="m-input" v-model="cur.leaveChapter" placeholder="如 210" />
            </div>
          </div>

          <div class="m-sec-title">关键关系</div>
          <div class="m-form-2">
            <div class="m-field">
              <label>关系对象</label>
              <MobilePicker v-model="cur.relationTo" title="选择关系对象"
                            :options="cardNames" placeholder="— 未填 —"
                            @update:model-value="touch" />
            </div>
            <div class="m-field">
              <label>关系类型</label>
              <MobilePicker v-model="cur.relationType" title="选择关系类型"
                            :options="relationTypes" placeholder="— 未填 —"
                            @update:model-value="touch" />
            </div>
            <div class="m-field">
              <label>关系方向</label>
              <div class="m-seg">
                <button v-for="d in ['双向', '单向']" :key="d" :class="{ on: cur.relationDirection === d }"
                        @click="cur.relationDirection = cur.relationDirection === d ? '' : d; touch()">{{ d }}</button>
              </div>
            </div>
            <div class="m-field">
              <label>关系强度<em>0 ~ 1</em></label>
              <input class="m-input" v-model="cur.relationStrength" placeholder="0.8"
                     @blur="cur.relationStrength = normUnit(cur.relationStrength)" />
            </div>
            <div class="m-field">
              <label>是否公开</label>
              <div class="m-seg">
                <button v-for="v in ['是', '否']" :key="v" :class="{ on: cur.isPublic === v }"
                        @click="cur.isPublic = cur.isPublic === v ? '' : v; touch()">{{ v }}</button>
              </div>
            </div>
            <div class="m-field">
              <label>关系章节</label>
              <input class="m-input" v-model="cur.chapter" placeholder="如 12" />
            </div>
          </div>
          <div class="m-field">
            <label>其他关系<em>一行一条：对象｜类型｜强度</em></label>
            <textarea class="m-textarea" v-model="cur.relations" style="min-height:80px"
                      placeholder="如：李四｜师徒｜0.9"></textarea>
          </div>

          <div class="m-sec-title">基础资料</div>
          <div class="m-field">
            <label>身份背景</label>
            <textarea class="m-textarea" v-model="cur.identity" placeholder="出身、身份、经历…"></textarea>
          </div>
          <div class="m-field">
            <label>性格</label>
            <textarea class="m-textarea" v-model="cur.personality" style="min-height:72px" placeholder="性格特点…"></textarea>
          </div>
          <div class="m-form-2">
            <div class="m-field">
              <label>说话风格</label>
              <textarea class="m-textarea" v-model="cur.speech" style="min-height:70px" placeholder="口吻、用词…"></textarea>
            </div>
            <div class="m-field">
              <label>口头禅</label>
              <textarea class="m-textarea" v-model="cur.catchwords" style="min-height:70px" placeholder="常用语、名台词…"></textarea>
            </div>
          </div>
          <div class="m-field">
            <label>弱点</label>
            <textarea class="m-textarea" v-model="cur.weakness" style="min-height:68px" placeholder="软肋、破绽…"></textarea>
          </div>
          <div class="m-field">
            <label>动机目标</label>
            <textarea class="m-textarea" v-model="cur.goal" style="min-height:68px" placeholder="他想要什么、为什么…"></textarea>
          </div>
        </div>

        <template #footer>
          <div class="m-modal-foot">
            <button class="m-btn del" title="删除角色" @click="delCard"><Icon name="trash" :size="16" /></button>
            <button class="m-btn" :disabled="saving" @click="close">
              <Icon name="check" :size="15" /> {{ saving ? '保存中…' : '完成' }}
            </button>
          </div>
        </template>
      </Modal>
    </template>
  </div>

  <BatchRename ref="renameRef" :open="renameOpen" kind="characters" title="批量修改角色名"
               desc-key="identity" :entities="cards" mobile
               @update:open="v => renameOpen = v" @apply="applyRename" />
</template>
