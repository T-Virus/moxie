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
import { STANCES, stanceMeta, stanceTag } from '../factionMeta'
import { FACTION_CATEGORIES, FACTION_RELATIONS, factionCategoryMeta, factionRelationMeta, normPublic, pct } from '../cardMeta'
import { normUnit } from '../utils'
import type { SbSchema } from '../types'

const { raw, factions, saving, load, save, batchRename } = useBookDoc()
const schema = ref<SbSchema | null>(null)
/* 批量改名：一次改多个势力名，服务端同步章节势力引用、角色归属与势力关系 */
const renameOpen = ref(false)
const renameRef = ref<any>(null)

onMounted(async () => {
  store.loadBooks().catch(() => {})
  load()
  try { schema.value = await api.getSchema() } catch { /* 忽略 */ }
})

const scrollEl = ref<HTMLElement | null>(null)

/* 左侧名词注释：tab 分组 */
const legendTabs = [
  { k: 'cat', label: '势力大类' },
  { k: 'stance', label: '立场' },
  { k: 'rel', label: '势力关系' },
]
const legendTab = ref('cat')
/* 名词解释 Splitter：可拖宽 / 可收起 / 宽度记忆（与正文目录同一套交互） */
const LEGEND_KEY = 'legend.layout'
const savedLegend = (() => { try { return JSON.parse(localStorage.getItem(LEGEND_KEY) || '{}') as Record<string, unknown> } catch { return {} } })()
/* 最小 380：保证 tab 文字不被挤压；最大 520，拖到 300 以下直接收起 */
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

/* ---- 搜索 + 分页：先按名称过滤，再每页只渲染 PAGE_SIZE 个，编辑仍针对全量数组 ---- */
const PAGE_SIZE = 8
const kw = ref('')
const page = ref(1)
/* 过滤结果保留原始下标：搜索态下编辑 / 删除都落在真实元素上，不会串卡 */
const rows = computed(() => {
  const k = kw.value.trim().toLowerCase()
  return factions.value.map((c, i) => ({ c, i }))
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

async function delFaction(i: number) {
  if (!await confirmBox('删除这张势力卡？', { danger: true, ok: '删除' })) return
  factions.value.splice(i, 1)
}

function addFaction() {
  if (!schema.value) return
  factions.value.push(Object.fromEntries(schema.value.faction_fields.map(([k]) => [k, ''])))
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
/* 批量改名应用：整包保存，服务端同步章节势力引用、角色归属与势力关系后本页重新载入 */
async function applyRename(mapping: Record<string, string>) {
  const ok = await batchRename('factions', mapping)
  if (ok) {
    renameOpen.value = false
    toast('已改名，章节与关系中的引用已同步', 'ok')
  } else {
    renameRef.value?.resetBusy()
  }
}
/* ---- 势力大类 / 立场 / 势力关系：取值与释义集中在 cardMeta.ts 与 factionMeta.ts ----
   标签类字段一律用下拉，不提供自由输入：写进数据的必须能对上词表，否则配色与 AI 判断都会失准 */
type Opt = { key: string; label: string; note?: string; example?: string; color: string; bg: string }
const PUBLIC_OPTS: Opt[] = [
  { key: 'y', label: '是', note: '关系公开', color: '#0ca678', bg: '#e6fcf5' },
  { key: 'n', label: '否', note: '只有当事人知道', color: '#868e96', bg: '#f1f3f5' },
]
/* 名称在头部单独渲染，其余字段按「基本 / 势力关系 / 其他」三组排布 */
const cardFieldList = computed<[string, string][]>(() => {
  const labels = Object.fromEntries(schema.value?.faction_fields || [])
  return ['category', 'stance', 'relTo', 'relType', 'relStrength', 'relPublic', 'relations', 'desc']
    .filter(k => labels[k]).map(k => [k, labels[k]])
})
const selects: Record<string, Opt[]> = {
  category: FACTION_CATEGORIES, stance: STANCES, relType: FACTION_RELATIONS, relPublic: PUBLIC_OPTS,
}
const cardSpan: Record<string, string> = {
  category: '', stance: '', relTo: '', relType: '', relStrength: '', relPublic: '', relations: 'full', desc: 'full',
}
const heightOf: Record<string, number> = { relations: 54, desc: 72 }
const catOf = (v: any) => factionCategoryMeta(v)
const stanceOf = (v: any) => stanceMeta(v)
const relOf = (v: any) => factionRelationMeta(v)
/* 头像徽章色：按势力大类（与左彩条同源） */
const avatarColor = (c: any) => catOf(c.category)?.color || '#9aa4b2'
/* 关联势力只能选势力表里已有的名字（可排除自己），避免写出对不上的势力名 */
const factionNames = computed(() => {
  const own = new Set(factions.value.map(f => String(f.name || '')))
  return [...own].filter(Boolean).sort((a, b) => a.localeCompare(b, 'zh'))
})
/* 下拉选项：候选项 + 不在候选里的旧值（显示标注，保存原值） */
function withLegacy(options: string[], cur: string, legacyLabel = '（旧值）') {
  const out: { label: string; value: string }[] = []
  if (cur && !options.includes(cur)) out.push({ label: cur + legacyLabel, value: cur })
  for (const o of options) out.push({ label: o, value: o })
  return out
}
/* 当前值的一行释义：大类给例子，立场 / 关系给判定含义 */
const noteOf = (k: string, v: any) => {
  if (k === 'category') return catOf(v)?.example || ''
  if (k === 'stance') return stanceOf(v)?.note || ''
  if (k === 'relType') return relOf(v)?.note || ''
  return ''
}
/* 卡片主色按势力大类；没有大类时退回立场色，再没有就用灰 */
const cardColor = (c: any) => catOf(c.category)?.color || stanceOf(c.stance)?.color || '#adb5bd'
const cardTint = (c: any) => catOf(c.category)?.bg || stanceOf(c.stance)?.bg || '#f6f7f9'
/* 卡片背景：极淡的阵营色 + 左侧色条（见 scoped 样式），不至于压过正文 */
const cardStyle = (c: any) => ({ background: '#fff', '--fc': cardColor(c), '--fcs': cardTint(c) } as any)

/* 旧数据迁移 + 规范值回归：
   已删除的 camp / kind / relation 只用来补 category，补完即丢弃，不再回写；
   「暗中支持主角」「世仇」这类自由表述落回规范值，保证下拉能选中、配色可辨 */
const FIELDS = ['category', 'stance', 'relTo', 'relType', 'relStrength', 'relPublic', 'relations', 'desc']
const LEGACY = ['camp', 'kind', 'relation']
watch(factions, list => {
  for (const f of list || []) {
    for (const k of FIELDS) if (f[k] === undefined || f[k] === null) f[k] = ''
    if (!f.category) {
      const guess = catOf(f.kind) || catOf(f.camp) || catOf(f.relation)
      if (guess) f.category = guess.label
    }
    const cat = catOf(f.category)
    const s = stanceOf(f.stance)
    const rt = relOf(f.relType)
    if (cat) f.category = cat.label
    if (s) f.stance = s.label
    if (rt) f.relType = rt.label
    f.relStrength = normUnit(f.relStrength)
    /* 认不出的公开性原样保留（下拉以「旧值」项显示），不静默清空 */
    f.relPublic = normPublic(f.relPublic)
    for (const k of LEGACY) delete f[k]
  }
}, { immediate: true })
</script>

<template>
  <div v-if="!state.books.length" class="card"><EmptyBox title="还没有作品" desc="先「新建作品」并完成拆解" /></div>
  <div v-else-if="!raw" class="card"><EmptyBox title="请选择作品" desc="在左侧作品集合中选择一本书" /></div>
  <template v-else>
    <div class="page-head"><div><h1>势力表</h1>
      <p>门派、组织、阵营及其相互关系——处理多方博弈剧情时的设定依据。</p></div>
    </div>
    <div class="page-split" :style="{ '--split-w': legendOff ? '28px' : '14px' }">
      <!-- 名词解释：默认收起成一条标题栏，点开才占高度 -->
      <aside class="card legend-card" v-show="!legendOff" :style="{ width: legendW + 'px' }">
        <div class="fl-head"><span>名词解释</span><span class="fl-head-note">势力标签的判定标准</span>
          <button class="fl-close" @click="toggleLegend">收起</button></div>
        <div class="fl-tabs">
          <button v-for="t in legendTabs" :key="t.k" :class="{ on: legendTab === t.k }"
                  @click="legendTab = t.k">{{ t.label }}</button>
        </div>
        <div class="fl-scroll">
          <div v-show="legendTab === 'cat'" class="fl-group">
            <h4>势力大类 <span>属于哪一类组织</span></h4>
            <div v-for="m in FACTION_CATEGORIES" :key="m.key" class="fl-item">
              <i :style="{ background: m.color }"></i>
              <b>{{ m.label }}</b>
              <span>{{ m.example }}</span>
            </div>
          </div>
          <div v-show="legendTab === 'stance'" class="fl-group">
            <h4>立场 <span>对主角的态度</span></h4>
            <div v-for="m in STANCES" :key="m.key" class="fl-item">
              <i :style="{ background: m.color }"></i>
              <b>{{ m.label }}</b>
              <span>{{ m.note }}</span>
            </div>
          </div>
          <div v-show="legendTab === 'rel'" class="fl-group">
            <h4>势力关系 <span>两个势力之间是什么关系</span></h4>
            <div v-for="m in FACTION_RELATIONS" :key="m.key" class="fl-item rel">
              <i :style="{ background: m.color }"></i>
              <b>{{ m.label }}</b>
              <span>{{ m.note }}<em>{{ m.example }}</em></span>
            </div>
          </div>
          <p class="fl-tip">大类与立场相互独立：「隐藏势力 + 潜伏」＝ 明面盟友、实为反派内应；「诸侯势力 + 敌对」＝ 正常的两军对垒。</p>
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
          {{ kw ? `匹配 ${rows.length} / 共 ${factions.length} 个` : `共 ${factions.length} 个` }}</span>
        <div class="tb-right">
          <div class="tb-search">
            <input class="input" v-model="kw" placeholder="搜索势力名称" />
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
            <button class="btn ghost" :disabled="!factions.length" @click="renameOpen = true">
              <Icon name="edit" :size="14" /> 批量改名</button>
            <button class="btn ghost" @click="addFaction"><Icon name="plus" :size="14" /> 加势力</button>
            <button class="btn m-save-hide" :disabled="saving" @click="save()"><Icon name="check" :size="15" /> 保存</button>
          </div>
        </div>
      </div>

      <div class="form-scroll" ref="scrollEl">
          <div v-if="rows.length" class="entity-cards">
            <div v-for="r in pageRows" :key="r.i" class="entity-card faction-card" :style="cardStyle(r.c)">
              <!-- 头部：名称 + 势力大类 / 立场两个彩色标签（两个维度，颜色不同便于分辨） -->
              <div class="ec-head">
                <span class="ec-avatar" :style="{ background: avatarColor(r.c) }">{{ (r.c.name || '?').slice(0, 1) }}</span>
                <input class="name-in" v-model="r.c.name" placeholder="未命名势力" />
                <span v-if="r.c.category" class="tag" :style="{ color: catOf(r.c.category)?.color, background: catOf(r.c.category)?.bg }"
                      :title="'势力大类：' + (catOf(r.c.category)?.example || '')">{{ r.c.category }}</span>
                <span v-if="r.c.stance" class="tag" :class="stanceTag(r.c.stance)" :title="'立场：' + (stanceOf(r.c.stance)?.note || '')">{{ r.c.stance }}</span>
              </div>
              <button class="rm" title="删除该势力" @click="delFaction(r.i)"><Icon name="trash" :size="13" /></button>
              <div class="ef">
                <template v-for="[k, lb] in cardFieldList" :key="k">
                  <div v-if="k === 'category'" class="sec-label full">基本信息</div>
                  <div v-if="k === 'relTo'" class="sec-label full">势力关系
                    <em class="lf-note">明面关系与暗地关系分开填：表面敌对、暗地合作填「暗中往来」且公开＝否</em></div>
                  <div v-if="k === 'desc'" class="sec-label full">其他</div>
                  <div :class="cardSpan[k] || ''">
                    <div class="field" style="margin-bottom:0">
                      <label>{{ lb }}
                        <em v-if="noteOf(k, r.c[k])" class="lf-note">{{ noteOf(k, r.c[k]) }}</em>
                        <em v-else-if="k === 'relStrength' && pct(r.c[k])" class="lf-note">{{ pct(r.c[k]) }}</em></label>
                      <!-- 标签类字段全部走下拉；认不出的旧值单独留一项，避免显示成空白 -->
                      <SelectBox v-if="selects[k]" compact allow-empty :model-value="r.c[k]"
                                 :options="withLegacy(selects[k].map(m => m.label), r.c[k])"
                                 @update:model-value="v => r.c[k] = v" />
                      <SelectBox v-else-if="k === 'relTo'" compact allow-empty :model-value="r.c.relTo"
                                 :options="withLegacy(factionNames, r.c.relTo)"
                                 @update:model-value="v => r.c.relTo = v" />
                      <input v-else-if="k === 'relStrength'" class="input" v-model="r.c.relStrength"
                             placeholder="0~1，0.9 生死同盟" @blur="r.c.relStrength = normUnit(r.c.relStrength)" />
                      <textarea v-else class="textarea" v-model="r.c[k]"
                                :style="{ minHeight: (heightOf[k] || 48) + 'px' }"></textarea>
                    </div>
                  </div>
                </template>
              </div>
            </div>
          </div>
          <EmptyBox v-else-if="!factions.length" title="暂无势力卡" desc="拆解时会自动提取，也可以点击「加势力」手动添加" />
          <EmptyBox v-else title="没有匹配的势力" desc="换个关键词试试，或点击「清除」查看全部" />
        </div>
        <!-- 手机：保存常驻底部 -->
        <div class="m-save-bar">
          <button class="btn lg" :disabled="saving" @click="save()">
            <Icon name="check" :size="16" /> 保存势力表</button>
        </div>

      </div>
    </div>
  </template>

  <BatchRename ref="renameRef" :open="renameOpen" kind="factions" title="批量修改势力名"
               desc-key="desc" :entities="factions" @update:open="v => renameOpen = v"
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
.fl-head {
  flex: none; display: flex; align-items: baseline; gap: 8px; width: 100%;
  padding: 10px 14px; font-size: 13px; font-weight: 600; color: var(--text);
}
.fl-head-note { font-size: 11px; font-weight: 400; color: var(--text-3); }
/* 卡片式分段 tab：浅底容器内等分一行，激活项白底卡片浮起；
   按钮按文字宽度撑开且禁止收缩，窄面板下也不会把字挤成一列 */
.fl-tabs {
  flex: none; display: flex; gap: 2px; margin: 0 10px 6px;
  padding: 3px; background: var(--bg); border-radius: 9px;
  overflow-x: auto; scrollbar-width: none;
}
.fl-tabs::-webkit-scrollbar { height: 0; }
.fl-tabs button {
  flex: 1 0 auto; min-width: max-content; border: none; background: transparent; font-family: inherit; cursor: pointer;
  font-size: 11.5px; color: var(--text-2); padding: 6px 6px; border-radius: 7px; line-height: 1.2;
  white-space: nowrap; transition: background .15s, color .15s, box-shadow .15s;
}
.fl-tabs button:hover { color: var(--text); }
.fl-tabs button.on { background: #fff; color: var(--primary); font-weight: 600; box-shadow: 0 1px 3px rgba(0, 0, 0, .14); }
.fl-scroll { flex: 1; min-height: 0; overflow-y: auto; padding: 12px 14px 14px; }
.fl-scroll::-webkit-scrollbar { width: 8px; }
.fl-scroll::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 4px; }
/* tab 模式下每组独占一屏，去掉组间分隔 */
.fl-group h4 {
  display: flex; align-items: baseline; gap: 6px;
  font-size: 12px; font-weight: 700; color: var(--text); margin: 0 0 9px;
  padding-left: 8px; border-left: 3px solid var(--primary); line-height: 1.3;
}
.fl-group h4 span { font-weight: 400; color: var(--text-3); font-size: 11px; }
/* 条目两行式：色点+名称一行，说明缩进换行，hover 浅底 */
.fl-item {
  display: flex; flex-wrap: wrap; align-items: flex-start; gap: 3px 6px;
  padding: 7px 8px; margin: 0 -8px; border-radius: 8px; line-height: 1.5;
  transition: background .12s;
}
.fl-item:hover { background: var(--bg); }
/* 圆点与名称行（line-height 1.5 × 12px = 18px）垂直居中：(18-7)/2 ≈ 5px */
.fl-item i { width: 7px; height: 7px; border-radius: 50%; flex: none; margin-top: 5px; }
.fl-item b { font-size: 12px; font-weight: 600; color: var(--text); flex: none; }
.fl-item span { flex: 1 1 100%; padding-left: 13px; font-size: 11px; line-height: 1.6; color: var(--text-3); }
/* 势力关系条目：释义与例子分两行，窄面板也能读清 */
.fl-item.rel { align-items: flex-start; }
.fl-item.rel em { display: block; font-style: normal; font-size: 10.5px; color: var(--text-3); opacity: .8; margin-top: 2px; }
.fl-tip {
  margin: 14px 0 0; padding: 9px 11px; background: var(--bg); border-radius: 8px;
  font-size: 11px; line-height: 1.6; color: var(--text-2);
}
/* 卡片左侧色条按阵营上色，标签沿用 base.css 的 cp-* / st-* 配色 */
.faction-card { border-left: 4px solid var(--fc); background:
  linear-gradient(90deg, var(--fcs) 0, #fff 54px) !important; }
.faction-card .ec-head { flex-wrap: wrap; }
.faction-card .ec-head .name-in { flex: 1 1 140px; min-width: 120px; }
.faction-card .lf-note { font-size: 11px; font-weight: 400; color: var(--text-3); margin-left: 6px; }
.faction-card .field > label { display: flex; align-items: baseline; gap: 4px; }

/* 列表区变宽后，卡片网格更自由：≥760px 就允许多列，不再卡死单列 */

/* 名词解释开关：桌面隐藏，窄屏出现 */
.legend-toggle { display: none; flex: none; }
.fl-close {
  display: none; margin-left: auto; flex: none; border: 1px solid var(--border-strong);
  background: var(--card); color: var(--text-2); font-size: 11.5px; font-weight: 400;
  border-radius: 6px; padding: 3px 9px; cursor: pointer;
}
.fl-close:active { color: var(--primary); border-color: var(--primary); }

/* 窄屏：splitter 隐藏，名词解释回到上方横向面板 */
@media (max-width: 900px) {
  .page-split { grid-template-columns: 1fr; }
  .page-split > .legend-card, .page-split > .legend-split, .page-split > .page-card { grid-column: auto; }
  .legend-split { display: none; }
  .legend-card { width: 100% !important; max-height: 240px; }
  .legend-toggle { display: inline-flex; }
  .fl-close { display: inline-flex; }
}
/* 名词解释 tab 内容多时内部滚动；极窄屏放宽限高让内容完整露出 */
@media (max-width: 760px) {
  /* 手机：卡片列表跟随整页滚动，不再套一层内部滚动区 */
  .page-split, .page-split .page-card { flex: none; min-height: 0; }
  .page-split .page-card .form-scroll { overflow: visible; padding-bottom: 0; }
  .legend-card { max-height: 46vh; }
}
</style>
