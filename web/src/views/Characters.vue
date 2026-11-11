<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import Icon from '../components/Icon.vue'
import BackLink from '../components/BackLink.vue'
import EmptyBox from '../components/EmptyBox.vue'
import BatchRename from '../components/BatchRename.vue'
import SelectBox from '../components/SelectBox.vue'
import { api } from '../api'
import { store, state } from '../store'
import { confirmBox, toast } from '../ui'
import { useBookDoc } from '../composables/useBookDoc'
import {
  ALIGNMENTS, ALIGN_AXES, FACTION_CATEGORIES, RACES, RELATIONS, RELATION_DIRECTIONS, ROLES,
  alignmentMeta, factionCategoryMeta, normDirection, normPublic, pct, relationMeta, roleMeta, tagStyle,
} from '../cardMeta'
import type { AlignMeta } from '../cardMeta'
import { STANCES, stanceMeta } from '../factionMeta'
import { genderTag, normUnit } from '../utils'
import type { SbSchema } from '../types'

const { raw, cards, factions, saving, load, save, batchRename } = useBookDoc()
const schema = ref<SbSchema | null>(null)
/* 批量改名：一次改多个名字，服务端同步章节角色、关系对象、道具持有者等引用 */
const renameOpen = ref(false)
const renameRef = ref<any>(null)

onMounted(async () => {
  store.loadBooks().catch(() => {})
  load()
  try { schema.value = await api.getSchema() } catch { /* 忽略 */ }
})

const scrollEl = ref<HTMLElement | null>(null)

/* 左侧名词注释：tab 分组，避免长列表一滚到底 */
const legendTabs = [
  { k: 'align', label: '人设倾向' },
  { k: 'role', label: '剧情功能' },
  { k: 'rel', label: '关系类型' },
  { k: 'stance', label: '对主角态度' },
  { k: 'faction', label: '势力大类' },
]
const legendTab = ref('align')
/* 名词解释 Splitter：可拖宽 / 可收起 / 宽度记忆（与正文目录同一套交互） */
const LEGEND_KEY = 'legend.layout'
const savedLegend = (() => { try { return JSON.parse(localStorage.getItem(LEGEND_KEY) || '{}') as Record<string, unknown> } catch { return {} } })()
/* 最小 380：保证 5 个 tab 文字不被挤压；最大 520，拖到 300 以下直接收起 */
const LEGEND_MIN = 380, LEGEND_MAX = 520, LEGEND_FOLD = 300
const legendW = ref(Math.min(LEGEND_MAX, Math.max(LEGEND_MIN, Number(savedLegend.w) || LEGEND_MIN)))
/* 手机 / 平板竖屏：名词解释默认收起，工具条提供展开入口 */
const narrowScreen = typeof window !== 'undefined' && window.matchMedia('(max-width: 900px)').matches
const legendOff = ref(narrowScreen ? true : !!savedLegend.off)
function saveLegend() {
  try { localStorage.setItem(LEGEND_KEY, JSON.stringify({ w: legendW.value, off: legendOff.value })) } catch { /* 忽略 */ }
}
let legendDrag = false, legendX0 = 0, legendW0 = 0
function startLegendDrag(e: PointerEvent) {
  if (legendOff.value) return
  e.preventDefault()
  legendDrag = true; legendX0 = e.clientX; legendW0 = legendW.value
  document.body.classList.add('ws-resizing')
  window.addEventListener('pointermove', onLegendMove)
  window.addEventListener('pointerup', endLegendDrag, { once: true })
  window.addEventListener('pointercancel', endLegendDrag, { once: true })
}
function onLegendMove(e: PointerEvent) {
  if (!legendDrag) return
  const w = legendW0 + (e.clientX - legendX0)
  if (w < LEGEND_FOLD) { endLegendDrag(); legendOff.value = true; saveLegend(); return }
  legendW.value = Math.min(LEGEND_MAX, Math.max(LEGEND_MIN, w))
}
function endLegendDrag() {
  if (!legendDrag) return
  legendDrag = false
  document.body.classList.remove('ws-resizing')
  window.removeEventListener('pointermove', onLegendMove)
  window.removeEventListener('pointercancel', endLegendDrag)
  saveLegend()
}
function toggleLegend() { legendOff.value = !legendOff.value; saveLegend() }

/* ---- 搜索 + 分页：先按名称过滤，再每页只渲染 PAGE_SIZE 张，编辑仍针对全量数组 ---- */
const PAGE_SIZE = 8
const kw = ref('')
const page = ref(1)
/* 过滤结果保留原始下标：搜索态下编辑 / 删除都落在真实元素上，不会串卡 */
const rows = computed(() => {
  const k = kw.value.trim().toLowerCase()
  return cards.value.map((c, i) => ({ c, i }))
    .filter(r => !k || String(r.c.name || '').toLowerCase().includes(k))
})
const pageCount = computed(() => Math.max(1, Math.ceil(rows.value.length / PAGE_SIZE)))
const pageStart = computed(() => (Math.min(page.value, pageCount.value) - 1) * PAGE_SIZE)
const pageRows = computed(() => rows.value.slice(pageStart.value, pageStart.value + PAGE_SIZE))

/* 页码越界自动回退：删光末页卡片 / 切换作品导致总量变小时，不再出现「3 / 2 页」这种错位 */
watch(pageCount, n => { if (page.value > n) page.value = n })
/* 搜索词变化回到第一页并回顶 */
watch(kw, () => {
  page.value = 1
  nextTick(() => { if (scrollEl.value) scrollEl.value.scrollTop = 0 })
})
/* 切换作品清空搜索、回到第一页并回到顶部 */
watch(() => store.curBook(), () => {
  kw.value = ''
  page.value = 1
  if (scrollEl.value) scrollEl.value.scrollTop = 0
})

function goPage(p: number) {
  const n = Math.min(Math.max(1, Math.round(p) || 1), pageCount.value)
  if (n === page.value) return
  page.value = n
  /* 翻页后回到列表顶部，否则会停在上页的滚动位置 */
  nextTick(() => { if (scrollEl.value) scrollEl.value.scrollTop = 0 })
}

async function delCard(i: number) {
  if (!await confirmBox('删除这张角色卡？', { danger: true, ok: '删除' })) return
  cards.value.splice(i, 1)
}

function addCard() {
  if (!schema.value) return
  cards.value.push(Object.fromEntries(schema.value.card_fields.map(([k]) => [k, ''])))
  kw.value = ''            /* 清空搜索，保证新卡可见 */
  /* 页码在 nextTick 里设：kw 的 watcher 会先把页码拉回第 1 页，这里再覆盖到末页；
     末页渲染完再聚焦，否则焦点会落在被替换掉的旧节点上 */
  nextTick(() => {
    page.value = pageCount.value
    nextTick(() => {
      if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
      const inputs = scrollEl.value?.querySelectorAll<HTMLInputElement>('.entity-card .name-in')
      inputs?.[inputs.length - 1]?.focus()
    })
  })
}

/* 批量改名应用：整包保存，服务端同步所有引用后本页重新载入 */
async function applyRename(mapping: Record<string, string>) {
  const ok = await batchRename('characters', mapping)
  if (ok) {
    renameOpen.value = false
    toast('已改名，章节与关系中的引用已同步', 'ok')
  } else {
    renameRef.value?.resetBusy()
  }
}

/* ---- 人设分析：九宫格 / 剧情功能 / 势力归属 / 对主角态度 ---- */
const factionOptions = computed(() => (factions.value || []).map(f => String(f.name || '')).filter(Boolean))
const cardNames = computed(() => cards.value.map(c => String(c.name || '')).filter(Boolean))
/* 九宫格按行取：善良行 / 中立行 / 邪恶行 */
const alignByRow = computed(() => ALIGN_AXES.rows.map((_, ri) => ALIGNMENTS.filter(m => m.row === ri)))

const alignNote = (v: string) => alignmentMeta(v)?.note || ''
const roleNote = (v: string) => roleMeta(v)?.note || ''
const stanceNote = (v: string) => stanceMeta(v)?.note || ''
const relNote = (v: string) => relationMeta(v)?.note || ''
const catNote = (v: string) => factionCategoryMeta(v)?.example || ''

function normChapter(v: any) {
  const s = String(v ?? '').trim()
  if (!s) return ''
  const m = s.match(/\d+/)
  return m ? m[0] : s
}

/* 九宫格按钮：未选中用浅底色，选中用实色 + 白字 */
function cellStyle(m: AlignMeta, on: boolean) {
  return on
    ? { background: m.color, color: '#fff', borderColor: m.color }
    : { background: m.bg, color: m.color, borderColor: 'transparent' }
}
function pickAlign(c: Record<string, string>, label: string) {
  c.alignment = c.alignment === label ? '' : label      /* 再点一次取消，便于清空 */
}

/* 左彩条＝人设倾向色；性别由头像徽章色表达，卡片统一白底更干净 */
function cardStyle(c: Record<string, string>) {
  const a = alignmentMeta(c.alignment)
  return { borderLeftColor: a ? a.color : '#dee2e6' } as Record<string, string>
}

/* 旧数据 / AI 自由表述落回规范值；缺失字段补空串，避免下拉绑定 undefined */
const FIELDS = ['role', 'alignment', 'stance', 'factionCategory', 'factionName', 'subFaction',
  'loyalty', 'joinChapter', 'leaveChapter', 'relationTo', 'relationType', 'relationDirection',
  'relationStrength', 'isPublic', 'chapter', 'relations', 'faction']
watch(cards, list => {
  for (const c of list || []) {
    for (const k of FIELDS) if (c[k] === undefined || c[k] === null) c[k] = ''
    const a = alignmentMeta(c.alignment)
    const rl = roleMeta(c.role)
    const st = stanceMeta(c.stance)
    const cat = factionCategoryMeta(c.factionCategory)
    const rt = relationMeta(c.relationType)
    if (a) c.alignment = a.label
    if (rl) c.role = rl.label
    if (st) c.stance = st.label
    if (cat) c.factionCategory = cat.label
    if (rt) c.relationType = rt.label
    /* 旧版只有一个「势力归属」：迁到势力名称，大类按名称推断 */
    if (!c.factionName && c.faction) c.factionName = c.faction
    if (!c.factionCategory && c.factionName) {
      const guess = factionCategoryMeta(c.factionName)
      if (guess) c.factionCategory = guess.label
    }
    /* 方向只认「单向/双向」；强度、忠诚度、章节号统一成规范写法。
       认不出的方向 / 公开性原样保留（下拉以「旧值」项显示），不静默清空。 */
    c.relationDirection = normDirection(c.relationDirection)
    c.relationStrength = normUnit(c.relationStrength)
    c.loyalty = normUnit(c.loyalty)
    c.chapter = normChapter(c.chapter)
    c.joinChapter = normChapter(c.joinChapter)
    c.leaveChapter = normChapter(c.leaveChapter)
    c.isPublic = normPublic(c.isPublic)
  }
}, { immediate: true })

/* 头像徽章色：按性别（与头像区分一致） */
function avatarColor(c: { gender?: string }) {
  const g = String(c.gender || '')
  return g.includes('女') ? '#e6618f' : g.includes('男') ? '#4c84ff' : '#9aa4b2'
}

/* 性别作为表单内下拉选项 */
const genderOptions = ref(['男', '女', '其他'])

/* 下拉选项：候选项 + 「不在候选里的旧值」（显示旧值标注，保存的仍是原值） */
function withLegacy(options: string[], cur: string, legacyLabel = '（旧值）') {
  const out: { label: string; value: string }[] = []
  if (cur && !options.includes(cur)) out.push({ label: cur + legacyLabel, value: cur })
  for (const o of options) out.push({ label: o, value: o })
  return out
}
/* 文本字段仍然按字段表渲染，排除已单独处理的项 */
const TEXT_FIELDS = ['identity', 'personality', 'speech', 'catchwords', 'weakness', 'goal']
const textFieldList = computed<[string, string][]>(() => {
  const labels = Object.fromEntries(schema.value?.card_fields || [])
  return TEXT_FIELDS.filter(k => labels[k]).map(k => [k, labels[k]])
})
const textSpan: Record<string, string> = {
  identity: 'full', personality: 'full', speech: '', catchwords: '', weakness: 'full', goal: 'full',
}
const heightOf: Record<string, number> = {
  identity: 64, personality: 56, speech: 56, catchwords: 38, weakness: 56, goal: 56,
}
</script>

<template>
  <div v-if="!state.books.length" class="card"><EmptyBox title="还没有作品" desc="先「新建作品」并完成拆解" /></div>
  <div v-else-if="!raw" class="card"><EmptyBox title="请选择作品" desc="在左侧作品集合中选择一本书" /></div>
  <template v-else>
    <div class="page-head"><div><h1>角色卡</h1>
      <p>人物身份、性格、目标与关系——扩写时保证人物言行一致的关键设定。</p></div>
    </div>
    <div class="page-split" :style="{ '--split-w': legendOff ? '28px' : '14px' }">
      <!-- 左：名词注释，独立卡片，标题固定、内容在卡片内滚动 -->
      <aside class="card legend-card" v-show="!legendOff" :style="{ width: legendW + 'px' }">
        <div class="cl-head"><span>名词解释</span><span class="cl-head-note">人物标签的判定标准</span>
          <button class="cl-close" @click="toggleLegend">收起</button></div>
        <div class="cl-tabs">
          <button v-for="t in legendTabs" :key="t.k" :class="{ on: legendTab === t.k }"
                  @click="legendTab = t.k">{{ t.label }}</button>
        </div>
        <div class="cl-scroll">
          <div v-show="legendTab === 'align'" class="cl-group">
            <h4>人设倾向 <span>性格坐标，不是关系</span></h4>
            <div class="ag-legend">
              <span></span>
              <span v-for="c in ALIGN_AXES.cols" :key="'lc' + c" class="ag-axis">{{ c }}</span>
              <template v-for="(group, ri) in alignByRow" :key="'lr' + ri">
                <span class="ag-axis">{{ ALIGN_AXES.rows[ri] }}</span>
                <span v-for="m in group" :key="m.key" class="ag-lcell"
                      :style="{ background: m.bg, color: m.color }" :title="m.note">{{ m.label }}</span>
              </template>
            </div>
          </div>
          <div v-show="legendTab === 'role'" class="cl-group">
            <h4>剧情功能 <span>在故事里起什么作用</span></h4>
            <div v-for="m in ROLES" :key="m.key" class="cl-item">
              <i :style="{ background: m.color }"></i><b>{{ m.label }}</b><span>{{ m.note }}</span>
            </div>
          </div>
          <div v-show="legendTab === 'rel'" class="cl-group">
            <h4>关系类型 <span>两人之间是什么关系</span></h4>
            <div v-for="m in RELATIONS" :key="m.key" class="cl-item rel">
              <i :style="{ background: m.color }"></i><b>{{ m.label }}</b>
              <span>{{ m.note }}<em>{{ m.example }}</em></span>
            </div>
            <p class="cl-sub">方向：暗恋 / 监视 / 利用 / 救命 是单向，其余多为双向。</p>
          </div>
          <div v-show="legendTab === 'stance'" class="cl-group">
            <h4>对主角态度 <span>与势力用的是同一套词</span></h4>
            <div v-for="m in STANCES" :key="m.key" class="cl-item">
              <i :style="{ background: m.color }"></i><b>{{ m.label }}</b><span>{{ m.note }}</span>
            </div>
          </div>
          <div v-show="legendTab === 'faction'" class="cl-group">
            <h4>势力大类 <span>与势力表用的是同一套词</span></h4>
            <div v-for="m in FACTION_CATEGORIES" :key="m.key" class="cl-item">
              <i :style="{ background: m.color }"></i><b>{{ m.label }}</b><span>{{ m.example }}</span>
            </div>
          </div>
          <p class="cl-tip">「守序善良的朝廷命官」完全可以「敌对」主角——人设倾向说的是他怎么做事，对主角态度说的是他站哪边，关系类型说的是他和谁有什么牵扯。</p>
        </div>
      </aside>

      <!-- Splitter：整条可拖拽调宽；拖到最窄自动收起，双击 / 中间按钮也能收起 -->
      <div class="legend-split" :class="{ off: legendOff }"
           :title="legendOff ? '展开名词解释' : '左右拖动调宽 · 双击收起'"
           @pointerdown="startLegendDrag" @dblclick="toggleLegend">
        <button class="split-btn" :title="legendOff ? '展开名词解释' : '收起名词解释'"
                @pointerdown.stop @click.stop="toggleLegend">
          <Icon :name="legendOff ? 'right' : 'left'" :size="12" />
        </button>
        <span v-if="legendOff" class="split-txt">名词解释</span>
      </div>

      <!-- 右：卡片列表，独立卡片 -->
      <div class="card page-card">
      <div class="toolbar">
        <BackLink class="m-back" />
        <button class="btn ghost legend-toggle" @click="toggleLegend">名词解释</button>
        <span class="hint">
          {{ kw ? `匹配 ${rows.length} / 共 ${cards.length} 张` : `共 ${cards.length} 张` }}</span>
        <div class="tb-right">
          <div class="tb-search">
            <input class="input" v-model="kw" placeholder="搜索角色名称" />
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
            <button class="btn ghost" :disabled="!cards.length" @click="renameOpen = true">
              <Icon name="edit" :size="14" /> 批量改名</button>
            <button class="btn ghost" @click="addCard"><Icon name="plus" :size="14" /> 加人物</button>
            <button class="btn m-save-hide" :disabled="saving" @click="save()"><Icon name="check" :size="15" /> 保存</button>
          </div>
        </div>
      </div>

      <div class="form-scroll" ref="scrollEl">
          <div v-if="rows.length" class="entity-cards">
            <div v-for="r in pageRows" :key="r.i" class="entity-card char-card" :style="cardStyle(r.c)">
              <!-- 头部：姓名 + 剧情功能 / 人设倾向 / 对主角态度三个彩色标签 -->
              <div class="ec-head">
                <span class="ec-avatar" :style="{ background: avatarColor(r.c) }">{{ (r.c.name || '?').slice(0, 1) }}</span>
                <input class="name-in" v-model="r.c.name" placeholder="未命名人物" />
                <span v-if="r.c.role" class="tag" :style="tagStyle(roleMeta(r.c.role))"
                      :title="'剧情功能：' + (roleNote(r.c.role) || '未识别')">{{ r.c.role }}</span>
                <span v-if="r.c.alignment" class="tag" :style="tagStyle(alignmentMeta(r.c.alignment))"
                      :title="'人设倾向：' + (alignNote(r.c.alignment) || '未识别')">{{ r.c.alignment }}</span>
                <span v-if="r.c.stance" class="tag" :style="tagStyle(stanceMeta(r.c.stance))"
                      :title="'对主角态度：' + (stanceNote(r.c.stance) || '未识别')">{{ r.c.stance }}</span>
                <span v-if="r.c.race" class="tag race-tag" :title="'种族：' + r.c.race">{{ r.c.race }}</span>
              </div>
              <button class="rm" title="删除该人物" @click="delCard(r.i)">
                <Icon name="trash" :size="13" /></button>

              <div class="ef">
                <div class="sec-label full">人设分析</div>

                <!-- 剧情功能 -->
                <div>
                  <div class="field" style="margin-bottom:0">
                    <label>剧情功能<em v-if="roleNote(r.c.role)" class="lf-note">{{ roleNote(r.c.role) }}</em></label>
                    <SelectBox compact allow-empty :model-value="r.c.role"
                               :options="withLegacy(ROLES.map(m => m.label), r.c.role)"
                               @update:model-value="v => r.c.role = v" />
                  </div>
                </div>
                <!-- 势力归属：大类（规范 10 类）+ 具体势力名（联动势力表）+ 分支 + 忠诚 / 章节 -->
                <div class="sec-label full">势力归属
                  <em class="lf-note">大类决定组织性质，势力名对上势力表，分支写他在这势力里的具体位置</em></div>
                <div>
                  <div class="field" style="margin-bottom:0">
                    <label>势力大类<em class="lf-note">{{ catNote(r.c.factionCategory) }}</em></label>
                    <SelectBox compact allow-empty :model-value="r.c.factionCategory"
                               :options="withLegacy(FACTION_CATEGORIES.map(m => m.label), r.c.factionCategory)"
                               @update:model-value="v => r.c.factionCategory = v" />
                  </div>
                </div>
                <div>
                  <div class="field" style="margin-bottom:0">
                    <label>势力名称<em class="lf-note">{{ factionOptions.length ? '取自势力表，新势力请先去势力表添加' : '尚无势力，请先去势力表添加' }}</em></label>
                    <SelectBox compact allow-empty :model-value="r.c.factionName"
                               :options="withLegacy(factionOptions, r.c.factionName, '（不在势力表中）')"
                               @update:model-value="v => r.c.factionName = v" />
                  </div>
                </div>
                <div>
                  <div class="field" style="margin-bottom:0">
                    <label>下属分支</label>
                    <input class="input" v-model="r.c.subFaction" placeholder="如先锋营、暗卫队" />
                  </div>
                </div>
                <div>
                  <div class="field" style="margin-bottom:0">
                    <label>忠诚度<em class="lf-note">{{ pct(r.c.loyalty) || '0~1' }}</em></label>
                    <input class="input" v-model="r.c.loyalty" placeholder="0.9 忠心不二"
                           @blur="r.c.loyalty = normUnit(r.c.loyalty)" />
                  </div>
                </div>
                <div>
                  <div class="field" style="margin-bottom:0">
                    <label>加入章节</label>
                    <input class="input" v-model="r.c.joinChapter" placeholder="如 45"
                           @blur="r.c.joinChapter = normChapter(r.c.joinChapter)" />
                  </div>
                </div>
                <div>
                  <div class="field" style="margin-bottom:0">
                    <label>脱离章节<em class="lf-note">仍在势力内就留空</em></label>
                    <input class="input" v-model="r.c.leaveChapter" placeholder="如 210"
                           @blur="r.c.leaveChapter = normChapter(r.c.leaveChapter)" />
                  </div>
                </div>

                <!-- 人设倾向：3×3 九宫格，点格子直接选，再点一次取消 -->
                <div class="full">
                  <div class="field" style="margin-bottom:0">
                    <label>人设倾向<em class="lf-note">{{ alignNote(r.c.alignment) || (r.c.alignment ? r.c.alignment + '（旧值，点格子覆盖）' : '守序/中立/混乱 × 善良/中立/邪恶') }}</em></label>
                    <div class="align-grid">
                      <span></span>
                      <span v-for="c in ALIGN_AXES.cols" :key="'c' + c" class="ag-axis">{{ c }}</span>
                      <template v-for="(group, ri) in alignByRow" :key="'r' + ri">
                        <span class="ag-axis">{{ ALIGN_AXES.rows[ri] }}</span>
                        <button v-for="m in group" :key="m.key" type="button" class="ag-cell"
                                :class="{ on: r.c.alignment === m.label }"
                                :style="cellStyle(m, r.c.alignment === m.label)"
                                :title="m.label + '：' + m.note"
                                @click="pickAlign(r.c, m.label)">{{ m.label }}</button>
                      </template>
                    </div>
                  </div>
                </div>

                <!-- 对主角态度 -->
                <div>
                  <div class="field" style="margin-bottom:0">
                    <label>对主角态度<em v-if="stanceNote(r.c.stance)" class="lf-note">{{ stanceNote(r.c.stance) }}</em></label>
                    <SelectBox compact allow-empty :model-value="r.c.stance"
                               :options="withLegacy(STANCES.map(m => m.label), r.c.stance)"
                               @update:model-value="v => r.c.stance = v" />
                  </div>
                </div>
                <div>
                  <div class="field" style="margin-bottom:0">
                    <label>性别</label>
                    <SelectBox compact allow-empty empty-label="未设置" :model-value="r.c.gender"
                               :options="withLegacy(genderOptions, r.c.gender)"
                               @update:model-value="v => r.c.gender = v" />
                  </div>
                </div>
                <div>
                  <div class="field" style="margin-bottom:0">
                    <label>种族<em class="lf-note">可直接输入自定义种族</em></label>
                    <SelectBox compact allow-empty allow-custom empty-label="未设置" :model-value="r.c.race"
                               :options="withLegacy(RACES, r.c.race, '')"
                               @update:model-value="v => r.c.race = v" />
                  </div>
                </div>

                <div class="sec-label full">关键关系
                  <em class="lf-note">关系类型描述两人之间是什么关系；立场、人设倾向都不是关系</em></div>
                <div>
                  <div class="field" style="margin-bottom:0">
                    <label>关系对象<em class="lf-note">取自角色池</em></label>
                    <SelectBox compact allow-empty :model-value="r.c.relationTo"
                               :options="withLegacy(cardNames, r.c.relationTo, '（不在角色池）')"
                               @update:model-value="v => r.c.relationTo = v" />
                  </div>
                </div>
                <div>
                  <div class="field" style="margin-bottom:0">
                    <label>关系类型<em v-if="relNote(r.c.relationType)" class="lf-note">{{ relNote(r.c.relationType) }}</em></label>
                    <SelectBox compact allow-empty :model-value="r.c.relationType"
                               :options="withLegacy(RELATIONS.map(m => m.label), r.c.relationType)"
                               @update:model-value="v => r.c.relationType = v" />
                  </div>
                </div>
                <div>
                  <div class="field" style="margin-bottom:0">
                    <label>关系方向</label>
                    <SelectBox compact allow-empty :model-value="r.c.relationDirection"
                               :options="withLegacy(RELATION_DIRECTIONS.map(m => m.label), r.c.relationDirection)"
                               @update:model-value="v => r.c.relationDirection = v" />
                  </div>
                </div>
                <div>
                  <div class="field" style="margin-bottom:0">
                    <label>关系强度<em class="lf-note">{{ pct(r.c.relationStrength) || '0~1' }}</em></label>
                    <input class="input" v-model="r.c.relationStrength" placeholder="0.95 生死之交"
                           @blur="r.c.relationStrength = normUnit(r.c.relationStrength)" />
                  </div>
                </div>
                <div>
                  <div class="field" style="margin-bottom:0">
                    <label>是否公开</label>
                    <SelectBox compact allow-empty :model-value="r.c.isPublic"
                               :options="withLegacy(['是', '否'], r.c.isPublic)"
                               @update:model-value="v => r.c.isPublic = v" />
                  </div>
                </div>
                <div>
                  <div class="field" style="margin-bottom:0">
                    <label>关系确立章节</label>
                    <input class="input" v-model="r.c.chapter" placeholder="如 120"
                           @blur="r.c.chapter = normChapter(r.c.chapter)" />
                  </div>
                </div>
                <div class="full">
                  <div class="field" style="margin-bottom:0">
                    <label>其他关系<em class="lf-note">一行一条：对象｜类型｜强度</em></label>
                    <textarea class="textarea" v-model="r.c.relations" style="min-height:54px"
                              placeholder="袁绍｜旧友｜0.6&#10;荀彧｜秘密合作｜0.4"></textarea>
                  </div>
                </div>

                <div class="sec-label full">基础资料</div>
                <div v-for="[k, lb] in textFieldList" :key="k" :class="textSpan[k] || ''">
                  <div class="field" style="margin-bottom:0"><label>{{ lb }}</label>
                    <textarea class="textarea" v-model="r.c[k]"
                              :style="{ minHeight: (heightOf[k] || 48) + 'px' }"></textarea></div>
                </div>
              </div>
            </div>
          </div>
          <EmptyBox v-else-if="!cards.length" title="暂无人物卡" desc="拆解时会自动提取，也可以点击「加人物」手动添加" />
          <EmptyBox v-else title="没有匹配的人物" desc="换个关键词试试，或点击「清除」查看全部" />
        </div>
        <!-- 手机：保存常驻底部 -->
        <div class="m-save-bar">
          <button class="btn lg" :disabled="saving" @click="save()">
            <Icon name="check" :size="16" /> 保存角色卡</button>
        </div>
      </div>
    </div>
  </template>

  <BatchRename ref="renameRef" :open="renameOpen" kind="characters" title="批量修改角色名"
               desc-key="identity" :entities="cards" @update:open="v => renameOpen = v"
               @apply="applyRename" />
</template>

<style scoped>
/* 左右 Splitter：左侧名词解释可拖宽 / 可收起（与正文目录同一套交互） */
.page-split { display: grid; grid-template-columns: auto var(--split-w, 14px) minmax(0, 1fr); gap: 0; align-items: stretch; flex: 1; min-height: 0; }
.legend-card {
  flex: none; display: flex; flex-direction: column;
  overflow: hidden; padding: 0; min-width: 0;
}
.page-split .page-card { min-width: 0; min-height: 0; margin-top: 0; margin-left: 0; }
/* 三块各占固定列：名词解释收起时 display:none 不生成格子，靠列定位避免右侧卡片被挤进 14px 轨道 */
.page-split > .legend-card { grid-column: 1; }
.page-split > .legend-split { grid-column: 2; }
.page-split > .page-card { grid-column: 3; }
/* Splitter：14px 命中区；中间竖条提示可拖，悬停 / 拖拽时变高变蓝（与正文目录一致） */
.legend-split { position: relative; z-index: 2; width: var(--split-w, 14px); flex: none; cursor: col-resize;
  display: flex; align-items: center; justify-content: center; touch-action: none;
  border-radius: 6px; transition: background .15s; }
.legend-split:hover, body.ws-resizing .legend-split { background: rgba(51, 112, 255, .07); }
/* 分隔线：细缝常显，悬停 / 拖拽时变粗变蓝；中间圆钮提示可拖 */
.legend-split::before { content: ''; position: absolute; left: 50%; top: 0; bottom: 0; transform: translateX(-50%);
  width: 1px; background: #dfe3e9; transition: background .15s, width .15s; }
.legend-split:hover::before, body.ws-resizing .legend-split::before { background: var(--primary); width: 2px; }
/* 收起态：变成贴着卡片左缘的一条竖标签（白底 + 圆角 + 展开箭头），不再是孤零零一个圆点 */
.legend-split.off { align-self: center; flex-direction: column; gap: 8px; padding: 10px 0;
  background: var(--card); border: 1px solid var(--border); border-right: 0; border-radius: 9px 0 0 9px;
  box-shadow: var(--shadow); }
.legend-split.off::before { display: none; }
.legend-split.off:hover { background: var(--primary-bg); border-color: var(--primary); }
.split-txt { writing-mode: vertical-rl; font-size: 11px; letter-spacing: 1px; color: var(--text-3);
  user-select: none; pointer-events: none; }
.legend-split.off:hover .split-txt { color: var(--primary); }
.legend-split .split-btn { position: relative; z-index: 1; width: 18px; height: 18px; padding: 0; border-radius: 50%;
  border: 1px solid var(--border); background: var(--card); color: var(--text-3);
  display: flex; align-items: center; justify-content: center; cursor: pointer;
  box-shadow: 0 1px 2px rgba(0, 0, 0, .08); }
.legend-split .split-btn:hover { color: var(--primary); border-color: var(--primary); }
/* 收起态：抓手高亮成「可展开」，告诉用户左侧还能拉回来 */
.legend-split.off .split-btn { color: var(--primary); border-color: var(--primary);
  background: var(--primary-bg); box-shadow: 0 1px 4px rgba(51, 112, 255, .25); }
.cl-head {
  flex: none; display: flex; align-items: baseline; gap: 8px; width: 100%;
  padding: 10px 14px; font-size: 13px; font-weight: 600; color: var(--text);
}
.cl-head-note { font-size: 11px; font-weight: 400; color: var(--text-3); }
/* 卡片式分段 tab：浅底容器内等分一行，激活项白底卡片浮起；
   按钮按文字宽度撑开且禁止收缩，窄面板下也不会把字挤成一列 */
.cl-tabs {
  flex: none; display: flex; gap: 2px; margin: 0 10px 6px;
  padding: 3px; background: var(--bg); border-radius: 9px;
  overflow-x: auto; scrollbar-width: none;
}
.cl-tabs::-webkit-scrollbar { height: 0; }
.cl-tabs button {
  flex: 1 0 auto; min-width: max-content; border: none; background: transparent; font-family: inherit; cursor: pointer;
  font-size: 11.5px; color: var(--text-2); padding: 6px 6px; border-radius: 7px; line-height: 1.2;
  white-space: nowrap; transition: background .15s, color .15s, box-shadow .15s;
}
.cl-tabs button:hover { color: var(--text); }
.cl-tabs button.on { background: #fff; color: var(--primary); font-weight: 600; box-shadow: 0 1px 3px rgba(0, 0, 0, .14); }
.cl-scroll { flex: 1; min-height: 0; overflow-y: auto; padding: 12px 14px 14px; }
.cl-scroll::-webkit-scrollbar { width: 8px; }
.cl-scroll::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 4px; }
/* tab 模式下每组独占一屏，去掉组间分隔 */
.cl-group h4 {
  display: flex; align-items: baseline; gap: 6px;
  font-size: 12px; font-weight: 700; color: var(--text); margin: 0 0 9px;
  padding-left: 8px; border-left: 3px solid var(--primary); line-height: 1.3;
}
.cl-group h4 span { font-weight: 400; color: var(--text-3); font-size: 11px; }
/* 条目两行式：色点+名称一行，说明缩进换行，hover 浅底 */
.cl-item {
  display: flex; flex-wrap: wrap; align-items: flex-start; gap: 3px 6px;
  padding: 7px 8px; margin: 0 -8px; border-radius: 8px; line-height: 1.5;
  transition: background .12s;
}
.cl-item:hover { background: var(--bg); }
/* 圆点与名称行（line-height 1.5 × 12px = 18px）垂直居中：(18-7)/2 ≈ 5px */
.cl-item i { width: 7px; height: 7px; border-radius: 50%; flex: none; margin-top: 5px; }
.cl-item b { font-size: 12px; font-weight: 600; color: var(--text); flex: none; }
.cl-item span { flex: 1 1 100%; padding-left: 13px; font-size: 11px; line-height: 1.6; color: var(--text-3); }
/* 关系类型条目：释义与例子分两行，窄面板里也读得清 */
.cl-item.rel { align-items: flex-start; }
.cl-item.rel b { flex: none; }
.cl-item.rel em { display: block; font-style: normal; color: var(--text-3); opacity: .8; font-size: 10.5px; margin-top: 2px; }
.cl-sub {
  margin: 9px 0 0; padding: 7px 10px; background: var(--bg); border-radius: 7px;
  font-size: 10.5px; line-height: 1.6; color: var(--text-3);
}
.cl-tip {
  margin: 14px 0 0; padding: 9px 11px; background: var(--bg); border-radius: 8px;
  font-size: 11px; line-height: 1.6; color: var(--text-2);
}

/* 3×3 九宫格：行首/列首是轴名，其余是九个格子。列表区变宽后放宽 max 宽度 */
.align-grid, .ag-legend {
  display: grid; grid-template-columns: 30px repeat(3, 1fr); gap: 5px; align-items: center;
  max-width: 440px;
}
.ag-axis { font-size: 11px; color: var(--text-3); text-align: center; line-height: 1.2; font-weight: 500; }
.ag-cell {
  border: 1px solid transparent; border-radius: 7px; font-size: 11px; line-height: 1.2;
  padding: 6px 2px; cursor: pointer; font-family: inherit; transition: filter .15s;
}
.ag-cell:hover { filter: brightness(.96); }
.ag-lcell {
  border-radius: 7px; font-size: 11px; line-height: 1.2; padding: 7px 2px; text-align: center; font-weight: 600;
}
.char-card { border-left: 4px solid #dee2e6; }
.char-card .ec-head { flex-wrap: wrap; }
.char-card .ec-head .name-in { flex: 1 1 120px; min-width: 100px; }
.char-card .lf-note { font-size: 11px; font-weight: 400; color: var(--text-3); margin-left: 6px; }
.char-card .field > label { display: flex; align-items: baseline; gap: 4px; }
/* 种族标签用中性色：不和剧情功能 / 人设倾向 / 态度的语义色抢眼 */
.char-card .race-tag { background: #eef2f6; color: #495057; }

/* 列表区变宽后，卡片网格更自由：≥760px 就允许多列，不再卡死单列 */

/* 名词解释开关：桌面隐藏，窄屏出现 */
.legend-toggle { display: none; flex: none; }
.cl-close {
  display: none; margin-left: auto; flex: none; border: 1px solid var(--border-strong);
  background: var(--card); color: var(--text-2); font-size: 11.5px; font-weight: 400;
  border-radius: 6px; padding: 3px 9px; cursor: pointer;
}
.cl-close:active { color: var(--primary); border-color: var(--primary); }

/* 窄屏：splitter 隐藏，名词解释回到上方横向面板 */
@media (max-width: 900px) {
  .page-split { grid-template-columns: 1fr; }
  .page-split > .legend-card, .page-split > .legend-split, .page-split > .page-card { grid-column: auto; }
  .legend-split { display: none; }
  .legend-card { width: 100% !important; max-height: 240px; }
  .legend-toggle { display: inline-flex; }
  .cl-close { display: inline-flex; }
}
/* 手机：卡片列表跟随整页滚动，不再套一层内部滚动区 */
@media (max-width: 760px) {
  .page-split, .page-split .page-card { flex: none; min-height: 0; }
  .page-split .page-card .form-scroll { overflow: visible; padding-bottom: 0; }
  .legend-card { max-height: 46vh; }
}
</style>
