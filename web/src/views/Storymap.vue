<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import Icon from '../components/Icon.vue'
import BackLink from '../components/BackLink.vue'
import EmptyBox from '../components/EmptyBox.vue'
import VirtualList from '../components/VirtualList.vue'
import SelectBox from '../components/SelectBox.vue'
import WorldMap from '../components/WorldMap.vue'
import { api, pollJobById } from '../api'
import { adoptJob } from '../jobs'
import { store, state } from '../store'
import { toast } from '../ui'
import G6 from '@antv/g6'
import { factionCategoryMeta, factionRelationMeta, pct, relationMeta } from '../cardMeta'
import { stanceMeta } from '../factionMeta'

type Tab = 'people' | 'plot' | 'world' | 'map' | 'items' | 'issues'
const tab = ref<Tab>('people')

const loading = ref(false)
const data = ref<any>(null)
const plot = ref<any>(null)
const generating = ref(false)
const genLines = ref<string[]>([])
/* 日志条是否显示：跑完也留着（任务中心点「查看」时要能看到这个任务的历史日志） */
const logOpen = ref(false)
/* 本页自己的任务 id：多任务并发时只回显这一个任务的日志 */
const jid = ref('')
let timer: any = null
let since = 0

const TABS: { key: Tab; label: string; icon: string }[] = [
  { key: 'people', label: '人物关系', icon: 'eye' },
  { key: 'plot', label: '剧情脉络', icon: 'arrowR' },
  { key: 'world', label: '世界观设定', icon: 'dashboard' },
  { key: 'map', label: '世界地图', icon: 'map' },
  { key: 'items', label: '关键道具', icon: 'file' },
  { key: 'issues', label: '一致性信息', icon: 'shield' },
]

async function load() {
  const book = store.curBook()
  if (!book) return
  loading.value = true
  try {
    const r = await api.getStorymap(book)
    data.value = r.ok ? r.data : null
    try { plot.value = await api.getStorymapPlot(book) } catch { plot.value = null }
  } catch (e: any) {
    toast(e.message, 'err')
  } finally {
    loading.value = false
  }
}

async function generate() {
  const book = store.curBook()
  if (!book) { toast('请先选择作品', 'err'); return }
  /* 不因为「已有任务在跑」而拦下：同一本书重复生成由后端 409 兜底，
     换一本书可以直接再开一个任务，原来那个继续在后台跑（任务中心可见） */
  // 有 Key：AI 生成（关系 / 道具 / 一致性 / 剧情脉络）；无 Key：后端降级为程序统计
  const smc = store.callCreds('storymap')
  const hasAi = !!smc.api_key
  try {
    const r = await api.run(smc.api_key, 'storymap', { book })
    jid.value = r.id
  } catch (e: any) { toast(e.message, 'err'); return }
  toast(hasAi ? '正在用 AI 生成设定图谱与剧情脉络…'
    : '未配置 API Key，将由程序生成图谱（无 AI 关系与冲突）', 'ok')
  generating.value = true
  logOpen.value = true
  genLines.value = []
  since = 0
  if (timer) clearInterval(timer)
  timer = setInterval(poll, 900)
}

async function poll() {
  if (!jid.value) return
  try {
    const j: any = await pollJobById(jid.value, since)
    if (since > j.total) {          // 服务端日志被截断，重新对齐
      genLines.value = []
      since = 0
    }
    if (j.lines && j.lines.length) {
      genLines.value.push(...j.lines)
      since = j.total
      if (genLines.value.length > 300) genLines.value.splice(0, genLines.value.length - 300)
    }
    if (!j.running) {
      clearInterval(timer); timer = null
      generating.value = false
      if (j.code === 0) { toast('设定图谱已更新', 'ok'); load() }
      else toast('生成失败，请查看日志', 'err')
    }
  } catch { /* 下一轮再试 */ }
}

/* 回到本页时接管仍在后台跑的设定图谱生成：按「阶段 + 当前书」认领任务，
   不会把拆解 / 改编任务的日志当成图谱进度显示 */
async function syncTask() {
  if (generating.value) return
  const a = await adoptJob(['storymap'], store.curBook())
  if (!a || !a.running) return
  jid.value = a.id
  generating.value = true
  logOpen.value = true
  genLines.value = []
  since = 0
  if (timer) clearInterval(timer)
  timer = setInterval(poll, 900)
  toast('已接管进行中的设定图谱生成', 'ok')
}

const d = computed<any>(() => data.value || {})
const nodes = computed<any[]>(() => d.value.nodes || [])
const edges = computed<any[]>(() => d.value.edges || [])
const factionNodes = computed<any[]>(() => d.value.factionNodes || [])
const factionEdges = computed<any[]>(() => d.value.factionEdges || [])
/* 人物关系 / 势力关系：同一张 G6 画布，用图层切换；势力层节点=势力大类色、边=势力关系类型色 */
const graphLayer = ref<'person' | 'faction'>('person')
const sideNodes = computed(() => graphLayer.value === 'faction' ? factionNodes.value : visibleNodes.value)
const world = computed<any[]>(() => d.value.worldview || [])
const items = computed<any[]>(() => d.value.items || [])
const conflicts = computed<any[]>(() => d.value.conflicts || [])
const worldPoints = computed(() => world.value.reduce((n, g) => n + ((g.points || []).length), 0))
/* 世界地图：区域数作为页签角标（地图本身在 WorldMap 组件里按层级下钻） */
const mapRegions = computed<any[]>(() => d.value.map?.regions || [])
const foreshadows = computed<any[]>(() => d.value.foreshadows || [])
const timeEvents = computed<any[]>(() => d.value.timeEvents || [])
/* 情绪流：拆解阶段标好的情绪走向 / 峰值 / 钩子 / 爽点 / 铺垫，后端直接搬运，不重新让模型编 */
const emotionCurve = computed<any[]>(() => d.value.emotionCurve || [])
const hooks = computed<any[]>(() => d.value.hooks || [])
const payoffs = computed<any[]>(() => d.value.payoffs || [])
const setups = computed<any[]>(() => d.value.setups || [])
/* 钩子类型计数：一眼看出整本书是不是总用同一种钩子（同一种用多了读者会麻木） */
const hookStats = computed(() => {
  const m: Record<string, number> = {}
  for (const h of hooks.value) {
    const k = h.type || '未标类型'
    m[k] = (m[k] || 0) + 1
  }
  return Object.entries(m).sort((a, b) => b[1] - a[1])
})
/* 张力分段着色：1~3 蓝（铺垫）、4~6 青（摩擦）、7~9 橙（爆发）、10 红（命运级） */
function tensionTone(n: number) {
  const v = Number(n) || 0
  if (v >= 10) return 'hi'
  if (v >= 7) return 'hot'
  if (v >= 4) return 'mid'
  return 'low'
}
const itemLinks = computed<any[]>(() => d.value.itemLinks || [])
const chapters = computed<any[]>(() => d.value.chapters || [])
const volumes = computed<any[]>(() => d.value.volumes || [])
const chapterQuery = ref('')
const chapterVol = ref('')
const filteredChapters = computed(() => {
  let list = chapters.value
  const q = chapterQuery.value.trim()
  if (q) list = list.filter((c: any) => String(c.no).includes(q) || (c.title || '').includes(q))
  if (chapterVol.value) {
    const v = volumes.value.find((x: any) => x.title === chapterVol.value)
    if (v) list = list.filter((c: any) => c.no >= v.from && c.no <= v.to)
  }
  return list
})

/* 人物关系图：用 @antv/g6 力导向渲染，可拖拽 / 滚轮缩放 / 按关系类型着色 */
const selName = ref('')
const PALETTE = ['#4c6ef5', '#12b886', '#f59f00', '#e8590c', '#ae3ec9',
  '#1c7ed6', '#0ca678', '#d6336c', '#f76707', '#7048e8']
/* 连线颜色＝关系类型（18 类规范色，与角色卡下拉同一套），同场共现的自动边用中性灰 */
function relColor(label: string): string {
  if (!label || label.startsWith('共')) return '#a8b0bc'
  return relationMeta(label)?.color || '#8a93a0'
}
/* 边权：关系强度 0~1 映射到线宽（0.9 生死之交画得粗，0.2 点头之交画得细） */
function relWidth(e: any): number {
  const s = Number(e.strength)
  if (!Number.isFinite(s) || s <= 0) return 1.8
  return 1.2 + Math.max(0, Math.min(1, s)) * 2.2
}
/* 节点颜色＝对主角态度（己方蓝、敌对红、潜伏紫…），一眼看出敌我；无立场时用调色板轮转 */
function nodeColor(n: any, i: number): string {
  return stanceMeta(n.stance)?.color || (i === 0 ? '#2f6bff' : PALETTE[i % PALETTE.length])
}
/* 估算文字像素宽度（中文 1.0 字宽、ASCII 0.58），用于按内容自适应节点尺寸 */
function textWidth(s: string, fs: number): number {
  let w = 0
  for (const ch of (s || '')) w += /[\x00-\xff]/.test(ch) ? fs * 0.58 : fs
  return w
}
/* 按像素折行：保证矩形节点文字不溢出（maxW 为节点内可用宽度） */
function wrapPx(text: string, fs: number, maxW: number): string {
  const lines: string[] = []; let line = '', lw = 0
  for (const ch of (text || '')) {
    const cw = /[\x00-\xff]/.test(ch) ? fs * 0.58 : fs
    if (lw + cw > maxW && line) { lines.push(line); line = ch; lw = cw }
    else { line += ch; lw += cw }
  }
  if (line) lines.push(line)
  return lines.join('\n')
}
/* 主角识别：角色卡 role 含 主角/男主/主人公/主角团/女主 */
const PROTAG_ROLES = ['主角', '男主', '主人公', '主角团', '女主']
function isProtagonist(n: any): boolean {
  const r = n.role || n.identity || ''
  return PROTAG_ROLES.some(w => String(r).includes(w))
}

/* 势力筛人：点右侧「势力分布」里的标签只看该势力的人，再点一次取消 */
const factionFilter = ref('')
const visibleNodes = computed(() => {
  if (!factionFilter.value) return nodes.value
  return nodes.value.filter(n => (n.factionCategory || '未归属势力') === factionFilter.value)
})
function filterFaction(k: string) {
  factionFilter.value = factionFilter.value === k ? '' : k
  selName.value = ''
}
/* 势力分布：按势力大类统计人数，作为图谱的快速筛选入口 */
const factionGroups = computed(() => {
  const m = new Map<string, number>()
  for (const n of nodes.value) {
    const k = n.factionCategory || '未归属势力'
    m.set(k, (m.get(k) || 0) + 1)
  }
  return [...m.entries()].sort((a, b) => b[1] - a[1])
})
const g6Nodes = computed(() => visibleNodes.value.slice(0, 36))
const g6Edges = computed(() => {
  const ids = new Set(g6Nodes.value.map(n => n.name))
  return edges.value.filter(e => ids.has(e.a) && ids.has(e.b))
})

let g6: any = null
const g6Ref = ref<HTMLElement | null>(null)

/* ---- 排布方案：节点一多，力导向会把整张图揉成一团，看不清谁连谁 ----
   每张图都能换排布（同心圆 / 环形 / 网格 / 分层 / 力导向），泳道图可选回人工泳道。 */
type LayoutKind = 'preset' | 'force' | 'circular' | 'grid' | 'concentric' | 'dagre'
const LAYOUT_NAME: Record<LayoutKind, string> = {
  preset: '泳道', force: '力导向', circular: '环形',
  grid: '网格', concentric: '同心圆', dagre: '分层',
}
const LAYOUT_OPTS: Record<'people' | 'plot' | 'items', LayoutKind[]> = {
  people: ['concentric', 'circular', 'grid', 'force'],
  plot: ['preset', 'dagre', 'force', 'circular'],
  items: ['force', 'circular', 'grid', 'concentric'],
}
/* 默认值就是「排得开」的那一档：重要的人在内圈、名字互不压住 */
const peopleLayout = ref<LayoutKind>('concentric')
const plotLayout = ref<LayoutKind>('preset')
const itemLayout = ref<LayoutKind>('force')
/* 下拉统一给 string：在这里收窄回 LayoutKind */
function setPeopleLayout(v: string) { peopleLayout.value = v as LayoutKind }
function setPlotLayout(v: string) { plotLayout.value = v as LayoutKind }
function setItemLayout(v: string) { itemLayout.value = v as LayoutKind }

function layoutCfg(kind: LayoutKind, o: { nodeSize?: number | number[]; linkDistance?: number
  rankdir?: 'LR' | 'TB'; spacing?: number } = {}): any {
  const nodeSize = o.nodeSize ?? 60
  const spacing = o.spacing ?? 26
  switch (kind) {
    case 'force':
      return { type: 'force', preventOverlap: true, nodeSize, nodeSpacing: spacing,
        linkDistance: o.linkDistance ?? 150, nodeStrength: -110, edgeStrength: 0.6,
        collideStrength: 1, alphaDecay: 0.03 }
    case 'circular':
      // 环形排在圆弧上，间距给大一点，宽节点的标签才不会互相压住
      return { type: 'circular', preventOverlap: true, nodeSize, nodeSpacing: spacing * 2, divisions: 1 }
    case 'grid':
      return { type: 'grid', preventOverlap: true, nodeSize, nodeSpacing: spacing }
    case 'concentric':
      return { type: 'concentric', preventOverlap: true, nodeSize, nodeSpacing: spacing,
        maxLevelDiff: 0.6, sortBy: 'degree' }
    case 'dagre':
      return { type: 'dagre', rankdir: o.rankdir ?? 'LR', nodesep: 24, ranksep: 80,
        preventOverlap: true, nodeSize }
    default:
      return undefined                      // preset：用节点上的手工坐标
  }
}

/* 自动排布会把整张图缩进画布：节点多时缩放会到 0.3 以下、字全糊成一团。
   这里给最小缩放保底，剩下的部分拖动画布 / 滚轮看。
   注意 G6 在布局结束时还会再做一次自动 fitView，把缩放压回去，
   所以 afterlayout（以及一个兜底定时器）之后要再夹一次。 */
function fitGraph(g: any, minZoom = 0.5) {
  if (!g) return
  // 上限不能卡死在 1：内容比画布略小时 fitView 本可以放大一点铺满，
  // 压回 1 就会在右侧留一条白边。放宽到 1.25 既撑满又不至于把节点放大到糊。
  const MAX_ZOOM = 1.25
  const clamp = () => {
    try {
      if (g.get('destroyed')) return
      const z = g.getZoom()
      if (z < minZoom) g.zoomTo(minZoom)
      else if (z > MAX_ZOOM) g.zoomTo(MAX_ZOOM)
    } catch { /* 已销毁 */ }
  }
  let applying = false       // 自己触发的视口变化不算用户操作
  let userMoved = false
  const refit = () => {
    try {
      if (g.get('destroyed')) return
      applying = true
      g.fitView(24)
      clamp()
      applying = false
    } catch { /* 已销毁 */ }
  }
  try {
    /* 布局坐标是异步算出来的：render() 之后立刻 fitView 拿到的是初始坐标，
       布局一结束节点散到视口外，而缩放又被夹到上限，视觉上就是一张空白图。
       所以 afterlayout 必须重新 fit 一次，再夹缩放。 */
    g.once('afterlayout', refit)
    refit()
    // 个别布局不派发 afterlayout：1.2s 后补一次；用户已经拖动 / 缩放过就不打扰
    window.setTimeout(() => { if (!userMoved) refit() }, 1200)
    window.setTimeout(clamp, 1600)
    g.on('viewportchange', () => { if (!applying) userMoved = true })
  } catch { /* 画布已销毁 */ }
}

const graphDiag = ref('')
let g6SizeRetry = 0
function renderGraph() {
  const box = g6Ref.value
  if (!box) return
  const w = box.clientWidth, h = box.clientHeight
  if (!w || !h) {
    /* 刚切图层 / 切页签时容器可能还在重排（这一帧宽高为 0）：
       下一帧再试几次，否则画布会一直空着，只能靠手动「重排」才出来。 */
    if (g6SizeRetry < 3) {
      g6SizeRetry += 1
      requestAnimationFrame(() => renderGraph())
    }
    return
  }
  g6SizeRetry = 0
  graphDiag.value = ''
  if (g6) { g6.destroy(); g6 = null }
  const isFac = graphLayer.value === 'faction'
  const srcNodes = isFac ? factionNodes.value : visibleNodes.value
  const srcEdges = isFac ? factionEdges.value : edges.value
  const ns = srcNodes.slice(0, isFac ? 80 : 36)
  const ids = new Set(ns.map((n: any) => n.name))
  const es = srcEdges.filter((e: any) => ids.has(e.a) && ids.has(e.b))
  /* 节点：人物层底色＝对主角态度浅色、描边＝态度深色；势力层＝势力大类色 */
  const gNodes = ns.map((n, i) => {
    let fill = '#eef3ff', stroke = PALETTE[i % PALETTE.length]
    if (isFac) {
      const c = factionCategoryMeta(n.category)
      fill = c?.bg || '#eef3ff'; stroke = c?.color || stroke
    } else {
      const st = stanceMeta(n.stance)
      fill = st?.bg || '#eef3ff'; stroke = st?.color || stroke
    }
    const isPro = !isFac && isProtagonist(n)
    // 圆形尺寸按名字宽度自适应，保证文字不溢出；重要角色（出现章数多）再额外放大
    const tw = textWidth(n.name || '', 12)
    const base = isFac ? 26 : 18 + Math.min(n.count || 0, 60) / 60 * 26
    const size = Math.max(base, tw + 14)
    const style: any = { fill, stroke, lineWidth: isPro ? 3.4 : 2.2 }
    if (isPro) { style.stroke = '#f5a623'; style.shadowColor = 'rgba(245,166,35,.5)'; style.shadowBlur = 14 }
    return {
      id: n.name, label: n.name, size,
      style,
      labelCfg: { style: { fill: isPro ? '#a05a00' : '#1f2430', fontSize: 12, fontWeight: isPro ? 800 : 600 } },
    }
  })
  const gEdges = es.map((e: any) => {
    const color = isFac ? (factionRelationMeta(e.label)?.color || '#8a93a0') : relColor(e.label)
    return {
      source: e.a, target: e.b, label: e.label,
      style: {
        stroke: color, lineWidth: relWidth(e),
        endArrow: e.direction === '单向' ? { path: G6.Arrow.triangle(6, 8, 6), fill: color, stroke: color } : false,
        lineDash: e.secret ? [5, 4] : undefined,
      },
      labelCfg: { autoRotate: true, style: { fontSize: 10, fill: '#fff',
        background: { fill: color, stroke: color, padding: [2, 4, 2, 4], radius: 8 } } },
    }
  })
  // 布局按节点实际最大尺寸留间距，否则大节点会互相压住
  const maxSize = Math.max(30, ...gNodes.map((n: any) => Number(n.size) || 30))
  const cfg = layoutCfg(peopleLayout.value, {
    nodeSize: Math.round(maxSize) + 8,
    linkDistance: isFac ? 180 : 150,
    spacing: 18,
  })
  g6 = new G6.Graph({
    container: box, width: w, height: h,
    ...(cfg ? { layout: cfg } : {}),
    defaultNode: { type: 'circle' },
    defaultEdge: { type: 'line' },
    modes: { default: ['drag-canvas', 'zoom-canvas', 'drag-node'] },
    fitView: true, fitViewPadding: 24,
  })
  try {
    g6.data({ nodes: gNodes, edges: gEdges })
    g6.render()
    fitGraph(g6, 0.6)
    g6.on('node:click', (ev: any) => { const m = ev.item?.getModel(); if (m) pick(m.id) })
    syncHighlight()
  } catch (e: any) {
    graphDiag.value = '渲染失败：' + (e?.message || e)
    console.error('[storymap] 图谱渲染失败', e)
  }
}

/* 图层切换只改状态，重画交给上面的 watch(graphLayer)。
   这里若再 nextTick(renderGraph)，同一帧会重画两次：刚建好的 G6 被立刻销毁重建，
   偶发画布空白（要再点一次「重排」才出图）。 */
function setLayer(v: string) {
  const l = v === 'faction' ? 'faction' : 'person'
  if (graphLayer.value === l) return
  graphLayer.value = l
  factionFilter.value = ''
}

/* 选中高亮：直接改节点的 style 并带上它自己的 fill。
   若改用 G6 的 state 样式（nodeStateStyles），state 应用时会依据「状态样式」重建绘制属性，
   节点原本的 fill 会被冲掉、未选中节点再被 opacity 压到极低，视觉上就是「全部变成白底」。 */
function applyFocus(graph: any, selId: string | null) {
  if (!graph) return
  graph.getNodes().forEach((n: any) => {
    const m = n.getModel()
    const base = m.__base || (m.__base = { ...(m.style || {}) })
    const isSel = !!selId && m.id === selId
    const dim = !!selId && !isSel
    const lw = Number(base.lineWidth) || 1.5
    graph.updateItem(n, {
      style: {
        ...base,                              /* 保留各自 fill / radius / lineDash 等原始样式 */
        opacity: dim ? 0.45 : 1,
        lineWidth: isSel ? lw + 1.6 : lw,
        stroke: isSel ? '#2f6bff' : base.stroke,
        shadowColor: isSel ? 'rgba(47,107,255,.45)' : base.shadowColor,
        shadowBlur: isSel ? 16 : (base.shadowBlur ?? 0),
      },
    })
  })
  graph.getEdges().forEach((e: any) => {
    const m = e.getModel()
    const base = m.__base || (m.__base = { ...(m.style || {}) })
    const hit = !!selId && (m.source === selId || m.target === selId)
    const lw = Number(base.lineWidth) || 1.5
    graph.updateItem(e, {
      style: {
        ...base,
        opacity: !selId ? 1 : (hit ? 1 : 0.22),
        lineWidth: hit ? lw + 0.9 : lw,
      },
    })
  })
}

function syncHighlight() {
  applyFocus(g6, selName.value || null)
}

/* ---- 剧情脉络：时间线主干（因果推进链）+ 主线 / 人物 / 支线 / 伏笔 / 悬念泳道 ---- */
let g6Plot: any = null
const plotRef = ref<HTMLElement | null>(null)
const selPlot = ref<{ type: string; text: string } | null>(null)
/* 剧情脉络图层：时间线（现有泳道）/ 伏笔回收（埋下→回收链）/ 时间轴（卷界+事件锚点） */
const plotLayer = ref<'timeline' | 'foreshadow' | 'axis' | 'emotion'>('timeline')
/* 关键道具图层：列表（表格）/ 流向（道具-人物 / 道具-道具关系图） */
const itemLayer = ref<'list' | 'flow'>('list')
let g6Item: any = null
const itemRef = ref<HTMLElement | null>(null)
const PLOT_LABEL: Record<string, string> = {
  timeline: '时间线', mainline: '主线阶段', subplots: '支线 / 情感线',
  foreshadow: '伏笔与回收', suspense: '核心悬念', conflict: '核心冲突', person: '人物',
  volume: '卷界', event: '时间轴事件',
}

function renderPlot() {
  const box = plotRef.value
  if (!box) return
  const w = box.clientWidth, h = box.clientHeight
  if (!w || !h) return
  if (g6Plot) { g6Plot.destroy(); g6Plot = null }
  selPlot.value = null
  const p = plot.value || {}
  const tls: string[] = p.timeline || []
  if (!tls.length) return
  const gNodes: any[] = [], gEdges: any[] = []
  /* 列宽与行高都按内容算：列宽至少 150px（文字少折几行），
     每行高度取该行最高节点，下一行照它往下让——写死 96px 行距时，
     事件文字一折到 7 行（约 125px）就会压住下一行。 */
  const x0 = 120                                   // 左边留给「核心冲突」
  const per = Math.max(2, Math.min(tls.length, Math.floor((w - x0) / 150)))
  const colSpan = (w - x0) / per
  const colW = Math.max(96, Math.min(200, colSpan - 14))   // 不能超过列宽，否则同排节点互相压住
  const tTxt: string[] = tls.map(t => wrapPx(t, 11, colW - 20))
  const rowH: number[] = []
  tTxt.forEach((txt, i) => {
    const r = Math.floor(i / per)
    rowH[r] = Math.max(rowH[r] || 0, 20 + txt.split('\n').length * 15)
  })
  const rowTop: number[] = []
  let acc = 0
  rowH.forEach((hh, r) => { rowTop[r] = acc; acc += hh + 26 })
  // 主线阶段在顶部、人物一圈在中间、事件区从人物下方开始
  const mls0: string[] = p.mainline || []
  const mlTxts: string[] = mls0.map(m => wrapPx(m, 11, Math.max(90, w / Math.max(1, mls0.length) - 18)))
  const mlH = Math.max(44, ...mlTxts.map(t => 20 + t.split('\n').length * 15))
  const yMain = 22 + mlH / 2
  const yPeople = yMain + mlH / 2 + 64
  const yT0 = yPeople + 76                         // 事件区第一行的顶部
  // 时间线蛇形排布：偶数行左→右，奇数行右→左
  const tPos = (i: number) => {
    const r = Math.floor(i / per), k = i % per
    const kk = r % 2 === 0 ? k : per - 1 - k
    return { x: x0 + (kk + 0.5) * colSpan, y: yT0 + rowTop[r] + rowH[r] / 2 }
  }
  const tlBottom = yT0 + Math.max(0, acc - 26)
  const names: string[] = (data.value?.nodes || []).map((n: any) => n.name)

  // 挂接：优先找「该文本提到的人物所出现的时间线事件」，否则按序兜底
  const anchor = (s: string, used: Record<number, number>, fall: number): number => {
    let best = -1
    for (const nm of names) {
      if (nm && nm.length >= 2 && s.includes(nm)) {
        const idx = tls.findIndex(t => t.includes(nm))
        if (idx >= 0) { best = idx; break }
      }
    }
    if (best < 0) best = Math.max(0, Math.min(tls.length - 1, fall))
    used[best] = (used[best] || 0) + 1
    return best
  }
  /* 泳道：一条支线一行，一行放不下就折行；宽度按可用空间均分。
     文字长的节点会自动变高，返回这条泳道实际占的高度，后面的泳道照它往下让位
     （以前行距写死 96px，节点一折到 5 行就压到下一条泳道上）。 */
  const lane = (items: { text: string; t: number }[], top: number,
                fill: string, stroke: string, color: string, prefix: string, dash: boolean): number => {
    if (!items.length) return 0
    items.sort((a, b) => a.t - b.t)
    const per = Math.max(1, Math.min(items.length, Math.floor(w / 132)))
    const laneW = Math.min(190, w / per - 12)
    const txts: string[] = []
    const rowH: number[] = []
    items.forEach((it, k) => {
      const lt = wrapPx(it.text, 11, laneW - 20)
      txts[k] = lt
      const row = Math.floor(k / per)
      rowH[row] = Math.max(rowH[row] || 0, 22 + lt.split('\n').length * 15)
    })
    const rowTop: number[] = []
    let acc = 0
    rowH.forEach((hh, r) => { rowTop[r] = acc; acc += hh + 10 })
    items.forEach((it, k) => {
      const row = Math.floor(k / per), col = k % per
      const nh = 22 + txts[k].split('\n').length * 15
      gNodes.push({
        id: prefix + k, x: (col + 0.5) * (w / per), y: top + rowTop[row] + rowH[row] / 2,
        type: 'rect', size: [laneW, nh],
        label: txts[k],
        style: { fill, stroke, lineWidth: 1.4, radius: 8 },
        labelCfg: { style: { fill: color, fontSize: 11 } },
        _raw: { type: prefix, text: it.text },
      })
      gEdges.push({ source: prefix + k, target: 'T' + it.t,
        style: { stroke, lineWidth: 1.3, lineDash: dash ? [4, 4] : undefined } })
    })
    return Math.max(0, acc - 10)
  }

  // 时间线主干：相邻事件相连 = 因果 / 时序推进链（蛇形换行）
  tls.forEach((t, i) => {
    const pos = tPos(i)
    gNodes.push({
      id: 'T' + i, x: pos.x, y: pos.y, type: 'rect', size: [colW, 20 + tTxt[i].split('\n').length * 15],
      label: tTxt[i],
      style: { fill: '#e8f1ff', stroke: '#2f6bff', lineWidth: 1.6, radius: 8 },
      labelCfg: { style: { fill: '#1f3a6b', fontSize: 11 } },
      _raw: { type: 'timeline', text: t },
    })
    if (i) gEdges.push({ source: 'T' + (i - 1), target: 'T' + i, style: { stroke: '#2f6bff', lineWidth: 2.4 } })
  })

  // 主线阶段：在顶部按阶段数均分铺开（不再跟着蛇形列走，
  // 否则两个阶段可能落在同一列的两行上、被强行压到同一 y 而重叠）
  const mls: string[] = p.mainline || []
  mls.forEach((m, j) => {
    const ti = mls.length === 1 ? Math.floor(tls.length / 2)
      : Math.round(j * (tls.length - 1) / (mls.length - 1))
    const mlW = Math.max(90, w / Math.max(1, mls.length) - 18)
    gNodes.push({
      id: 'M' + j, x: (j + 0.5) * (w / mls.length), y: yMain, type: 'rect',
      size: [mlW, 20 + mlTxts[j].split('\n').length * 15],
      label: mlTxts[j], style: { fill: '#1c7ed6', stroke: '#1c7ed6', radius: 8 },
      labelCfg: { style: { fill: '#fff', fontSize: 11 } },
      _raw: { type: 'mainline', text: m },
    })
    gEdges.push({ source: 'M' + j, target: 'T' + ti, style: { stroke: '#9db8e8', lineWidth: 1.4, lineDash: [5, 4] } })
  })

  // 主要人物：圆点挂在其出场的时间线事件上
  const ppl = (data.value?.nodes || []).slice(0, 10)
  if (ppl.length) {
    const usedP: Record<number, number> = {}
    const pits = ppl.map((n: any, i: number) =>
      ({ text: n.name, t: anchor(n.name, usedP, Math.floor(i * tls.length / ppl.length)) }))
    pits.sort((a, b) => a.t - b.t)
    pits.forEach((it, k) => {
      gNodes.push({
        id: 'P' + k, x: (k + 0.5) * (w / pits.length), y: yPeople, type: 'circle', size: 40,
        label: it.text,
        style: { fill: '#d6336c', stroke: '#fff', lineWidth: 2,
          shadowColor: 'rgba(214,51,108,.35)', shadowBlur: 8 },
        labelCfg: { position: 'bottom', offset: 4, style: { fill: '#a61e4d', fontSize: 11, fontWeight: 700 } },
        _raw: { type: 'person', text: it.text },
      })
      // 人物 → 出场时间线：玫瑰色虚线，与蓝色因果主干区分（表示「出场关联」而非因果推进）
      gEdges.push({ source: 'P' + k, target: 'T' + it.t,
        style: { stroke: '#e64980', lineWidth: 1.4, lineDash: [4, 3], opacity: 0.8 } })
    })
  }

  // 支线（绿）/ 伏笔（紫）/ 悬念（橙）泳道：从上往下依次排，中间留 18px 空隙
  const uS: Record<number, number> = {}, uF: Record<number, number> = {}, uSu: Record<number, number> = {}
  let laneTop = tlBottom + 26
  const hSub = lane((p.subplots || []).map((s: string, i: number) => ({ text: s, t: anchor(s, uS, i * 2 + 1) })),
    laneTop, '#e6f7f0', '#0ca678', '#0b6b4f', 'S', true)
  if (hSub) laneTop += hSub + 18
  const hFore = lane((p.foreshadow || []).map((s: string, i: number) => ({ text: s, t: anchor(s, uF, i) })),
    laneTop, '#f5edff', '#ae3ec9', '#6d2aa8', 'F', true)
  if (hFore) laneTop += hFore + 18
  lane((p.suspense || []).map((s: string, i: number) => ({ text: s, t: anchor(s, uSu, tls.length - 1) })),
    laneTop, '#fff0e8', '#e8590c', '#a04000', 'Su', true)

  // 核心冲突：作为「因」指向时间线起点，放在左侧留白带里（原来压在最后一个事件上）
  if ((p.conflict || []).length) {
    const cTxt = wrapPx('冲突：' + p.conflict[0], 10, 76)
    gNodes.push({
      id: 'C0', x: 58, y: yT0 + Math.max(0, acc - 26) / 2, type: 'rect',
      size: [96, 16 + cTxt.split('\n').length * 14],
      label: cTxt,
      style: { fill: '#f4f6f9', stroke: '#8a93a0', lineWidth: 1.4, radius: 8 },
      labelCfg: { style: { fill: '#556', fontSize: 10 } },
      _raw: { type: 'conflict', text: p.conflict.join('；') },
    })
    gEdges.push({ source: 'C0', target: 'T0', style: { stroke: '#9aa3b0', lineWidth: 1.6 } })
  }

  // preset = 上面的手工泳道坐标；选了自动排布就交给布局引擎重排
  const cfg = layoutCfg(plotLayout.value, { nodeSize: [190, 92], linkDistance: 190, rankdir: 'LR' })
  g6Plot = new G6.Graph({
    container: box, width: w, height: h,
    ...(cfg ? { layout: cfg } : {}),
    defaultNode: { type: 'rect' }, defaultEdge: { type: 'line' },
    modes: { default: ['drag-canvas', 'zoom-canvas', 'drag-node'] },
    fitView: true, fitViewPadding: 18,
  })
  g6Plot.data({ nodes: gNodes, edges: gEdges })
  g6Plot.render()
  fitGraph(g6Plot, 0.7)
  g6Plot.on('node:click', (ev: any) => {
    const m = ev.item?.getModel()
    if (!m?._raw) return
    const same = selPlot.value && selPlot.value.text === m._raw.text && selPlot.value.type === m._raw.type
    selPlot.value = same ? null : m._raw
    syncPlotHighlight(same ? null : m.id)
  })
}

function syncPlotHighlight(selId: string | null) {
  applyFocus(g6Plot, selId)
}

/* 伏笔回收图：每行一个伏笔 = 埋下节点（紫）→ 边（标注回收章号）→ 回收节点（已回收绿 / 待确认灰） */
function renderForeshadow() {
  const box = plotRef.value
  if (!box) return
  const w = box.clientWidth, h = box.clientHeight
  if (!w || !h) return
  if (g6Plot) { g6Plot.destroy(); g6Plot = null }
  selPlot.value = null
  const fs: any[] = d.value.foreshadows || []
  if (!fs.length) return
  const gNodes: any[] = [], gEdges: any[] = []
  const colW = w - 60
  /* 每行按这一对节点的实际高度往下排（写死行距时，伏笔文字一折行就会压住下一行） */
  let yTop = 24
  fs.forEach((f, i) => {
    const seedId = 'FS' + i + 'a', payId = 'FS' + i + 'b'
    const done = f.status === '已回收'
    const fW = colW * 0.4
    const seedTxt = wrapPx(f.seed || f.text || '—', 11, fW - 20)
    const payTxt = wrapPx(f.payoff || '—', 11, fW - 20)
    const hs = 20 + seedTxt.split('\n').length * 15
    const hp = 20 + payTxt.split('\n').length * 15
    const y = yTop + Math.max(hs, hp) / 2
    yTop += Math.max(hs, hp) + 26
    gNodes.push({
      id: seedId, x: 30 + colW * 0.22, y, type: 'rect', size: [fW, hs],
      label: seedTxt,
      style: { fill: '#f5edff', stroke: '#ae3ec9', lineWidth: 1.6, radius: 8 },
      labelCfg: { style: { fill: '#6d2aa8', fontSize: 11 } },
      _raw: { type: 'foreshadow', text: '埋下：' + (f.seed || f.text || '') },
    })
    gNodes.push({
      id: payId, x: 30 + colW * 0.78, y, type: 'rect', size: [fW, hp],
      label: payTxt,
      style: { fill: done ? '#e6f7f0' : '#f1f3f5', stroke: done ? '#0ca678' : '#adb5bd', lineWidth: 1.6, radius: 8 },
      labelCfg: { style: { fill: done ? '#0b6b4f' : '#868e96', fontSize: 11 } },
      _raw: { type: 'foreshadow', text: '回收：' + (f.payoff || '待回收') + (f.chapter ? '（第' + f.chapter + '章）' : '') },
    })
    gEdges.push({
      source: seedId, target: payId,
      label: f.chapter ? ('第' + f.chapter + '章') : '待回收',
      style: { stroke: done ? '#0ca678' : '#adb5bd', lineWidth: 1.8,
        endArrow: { path: G6.Arrow.triangle(6, 8, 6), fill: done ? '#0ca678' : '#adb5bd', stroke: done ? '#0ca678' : '#adb5bd' } },
      labelCfg: { autoRotate: true, style: { fontSize: 10, fill: '#fff',
        background: { fill: done ? '#0ca678' : '#adb5bd', padding: [1, 4, 1, 4], radius: 6 } } },
    })
  })
  const cfg = layoutCfg(plotLayout.value, { nodeSize: [colW * 0.4, 80], linkDistance: 170 })
  g6Plot = new G6.Graph({
    container: box, width: w, height: h,
    ...(cfg ? { layout: cfg } : {}),
    modes: { default: ['drag-canvas', 'zoom-canvas', 'drag-node'] },
    fitView: true, fitViewPadding: 20,
  })
  g6Plot.data({ nodes: gNodes, edges: gEdges })
  g6Plot.render()
  fitGraph(g6Plot, 0.7)
  g6Plot.on('node:click', (ev: any) => {
    const m = ev.item?.getModel(); if (!m?._raw) return
    const same = selPlot.value && selPlot.value.text === m._raw.text && selPlot.value.type === m._raw.type
    selPlot.value = same ? null : m._raw
    syncPlotHighlight(same ? null : m.id)
  })
}

/* 时间轴图：按「卷界 / 事件」的时间顺序等距铺开（章号写在标签里），连成时间推进链 */
function renderTimelineAxis() {
  const box = plotRef.value
  if (!box) return
  const w = box.clientWidth, h = box.clientHeight
  if (!w || !h) return
  if (g6Plot) { g6Plot.destroy(); g6Plot = null }
  selPlot.value = null
  const evs: any[] = (d.value.timeEvents || []).slice()
  if (!evs.length) return
  const gNodes: any[] = [], gEdges: any[] = []
  const padX = 60
  const sorted = [...evs].sort((a, b) => (Number(a.chapter) || 0) - (Number(b.chapter) || 0))
  /* 以前按「章号 / 最大章号」定 x：事件都集中在第 1-14 章，而卷界排到第 256 章，
     十几个节点全挤在左边 5% 的宽度里叠成一坨。改成按事件顺序等距排（一个事件一个刻度，
     章号写在标签里），再按「右边界」逐行下压，放不下就换下一行。 */
  const n = sorted.length
  const slot = n > 1 ? (w - padX * 2) / (n - 1) : 0
  const axW = Math.min(180, Math.max(104, slot * 1.8))
  const cx = (i: number) => (n > 1 ? padX + slot * i : w / 2)
  const rowRight: number[] = [], rowH: number[] = []
  const boxes = sorted.map((e, i) => {
    const isVol = e.lane === 'volume'
    const x = Math.max(padX + axW / 2, Math.min(w - padX - axW / 2, cx(i)))
    const txt = wrapPx(e.text, 11, axW - 18)
    const nh = (isVol ? 34 : 26) + txt.split('\n').length * 14
    let row = 0
    while (rowRight[row] !== undefined && x - axW / 2 < rowRight[row] + 14) row++
    rowRight[row] = x + axW / 2
    rowH[row] = Math.max(rowH[row] || 0, nh)
    return { e, x, txt, nh, row, isVol }
  })
  const rowTop: number[] = []
  let acc = 0
  rowH.forEach((hh, r) => { rowTop[r] = acc; acc += hh + 30 })
  const y0 = Math.max(0, (h - Math.max(0, acc - 30)) / 2)
  boxes.forEach((b, i) => {
    const y = y0 + rowTop[b.row] + rowH[b.row] / 2
    gNodes.push({
      id: 'T' + i, x: b.x, y, type: 'rect', size: [axW, b.nh],
      label: b.txt,
      style: { fill: b.isVol ? '#fff0e8' : '#e8f1ff', stroke: b.isVol ? '#e8590c' : '#2f6bff', lineWidth: 1.6, radius: 8 },
      labelCfg: { style: { fill: b.isVol ? '#a04000' : '#1f3a6b', fontSize: 11 } },
      _raw: { type: b.isVol ? 'volume' : 'event', text: b.e.text + '（第' + (b.e.chapter || '?') + '章）' },
    })
    if (i) gEdges.push({ source: 'T' + (i - 1), target: 'T' + i, style: { stroke: '#2f6bff', lineWidth: 2 } })
  })
  const cfg = layoutCfg(plotLayout.value, { nodeSize: [axW, 70], linkDistance: 160 })
  g6Plot = new G6.Graph({
    container: box, width: w, height: h,
    ...(cfg ? { layout: cfg } : {}),
    modes: { default: ['drag-canvas', 'zoom-canvas', 'drag-node'] },
    fitView: true, fitViewPadding: 20,
  })
  g6Plot.data({ nodes: gNodes, edges: gEdges })
  g6Plot.render()
  fitGraph(g6Plot, 0.7)
  g6Plot.on('node:click', (ev: any) => {
    const m = ev.item?.getModel(); if (!m?._raw) return
    const same = selPlot.value && selPlot.value.text === m._raw.text && selPlot.value.type === m._raw.type
    selPlot.value = same ? null : m._raw
    syncPlotHighlight(same ? null : m.id)
  })
}

/* 道具流向图：节点＝道具（金）/ 人物（蓝），蓝边＝持有变更、红边＝克制 / 被克制，力导向排布 */
function renderItemFlow() {
  const box = itemRef.value
  if (!box) return
  const w = box.clientWidth, h = box.clientHeight
  if (!w || !h) return
  if (g6Item) { g6Item.destroy(); g6Item = null }
  const links: any[] = d.value.itemLinks || []
  if (!links.length) return
  const itemNames = new Set((items.value || []).map((it: any) => it.name))
  const nameSet = new Set<string>()
  links.forEach((l: any) => { if (l.from) nameSet.add(l.from); if (l.to) nameSet.add(l.to) })
  const gNodes = [...nameSet].map((nm) => {
    const isItem = itemNames.has(nm)
    const size = Math.max(isItem ? 26 : 18, textWidth(nm, 11) + 12)
    return {
      id: nm, label: nm, size,
      style: { fill: isItem ? '#fff9db' : '#e7f5ff', stroke: isItem ? '#f59f00' : '#4c6ef5', lineWidth: 2 },
      labelCfg: { style: { fill: '#1f2430', fontSize: 11, fontWeight: 600 } },
    }
  })
  const gEdges = links.map((l: any) => {
    const counter = l.type === 'counter'
    const owner = l.type === 'owner'
    const color = counter ? '#e03131' : owner ? '#868e96' : '#4c6ef5'
    const label = l.note || (counter ? '克制' : owner ? '持有' : '持有变更')
    return {
      source: l.from, target: l.to, label,
      style: { stroke: color, lineWidth: counter ? 2 : 1.6,
        endArrow: owner ? false : { path: G6.Arrow.triangle(6, 8, 6), fill: color, stroke: color } },
      labelCfg: { autoRotate: true, style: { fontSize: 10, fill: '#fff',
        background: { fill: color, padding: [1, 4, 1, 4], radius: 6 } } },
    }
  })
  const maxSize = Math.max(30, ...gNodes.map((n: any) => Number(n.size) || 30))
  const cfg = layoutCfg(itemLayout.value, { nodeSize: Math.round(maxSize) + 8, linkDistance: 130, spacing: 16 })
  g6Item = new G6.Graph({
    container: box, width: w, height: h,
    ...(cfg ? { layout: cfg } : {}),
    defaultNode: { type: 'circle' }, defaultEdge: { type: 'line' },
    modes: { default: ['drag-canvas', 'zoom-canvas', 'drag-node'] },
    fitView: true, fitViewPadding: 20,
  })
  g6Item.data({ nodes: gNodes, edges: gEdges })
  g6Item.render()
  fitGraph(g6Item, 0.6)
}

/* 剧情脉络按子图层选择渲染函数 */
function renderPlotLayer() {
  if (plotLayer.value === 'emotion') {
    // 情绪流是 DOM 柱图，不需要 G6 画布，销毁旧图避免残影
    if (g6Plot) { g6Plot.destroy(); g6Plot = null }
    return
  }
  if (plotLayer.value === 'timeline') renderPlot()
  else if (plotLayer.value === 'foreshadow') renderForeshadow()
  else renderTimelineAxis()
}
/* 同 setLayer：只改状态，重画由 watch([plotLayer, itemLayer]) 统一触发，避免同一帧画两次 */
function setPlotLayer(v: string) {
  const l = v === 'foreshadow' || v === 'axis' || v === 'emotion' ? v : 'timeline'
  if (plotLayer.value === l) return
  plotLayer.value = l
}
function setItemLayer(v: string) {
  const l = v === 'flow' ? 'flow' : 'list'
  if (itemLayer.value === l) return
  itemLayer.value = l
}

function onResize() {
  // 尺寸变化后只调整画布并重新适配，不重建图：重建会丢选中态、也会闪一下。
  // 情绪流等用 v-show 隐藏的容器宽高为 0，跳过以免把画布压成 0。
  const fit = (g: any, el: HTMLElement | null) => {
    const w = el?.clientWidth || 0, h = el?.clientHeight || 0
    if (!g || !w || !h) return
    try {
      g.changeSize(w, h)
      fitGraph(g, 0.5)      // 复用统一的最小缩放夹取，避免容器变小时字糊成一团
    } catch { /* 画布已销毁 */ }
  }
  fit(g6, g6Ref.value)
  fit(g6Plot, plotRef.value)
  fit(g6Item, itemRef.value)
  // 首次进入时图例/侧栏还会重排一次，当场读到的 clientHeight 往往比最终小十几像素；
  // 下一帧布局稳定后只同步尺寸（不再 fitView），避免画布比容器矮一截。
  requestAnimationFrame(() => {
    const sync = (g: any, el: HTMLElement | null) => {
      const w = el?.clientWidth || 0, h = el?.clientHeight || 0
      if (!g || !w || !h) return
      try { g.changeSize(w, h) } catch { /* 画布已销毁 */ }
    }
    sync(g6, g6Ref.value)
    sync(g6Plot, plotRef.value)
    sync(g6Item, itemRef.value)
  })
  // 首次渲染时容器还没布局出宽高（拿到 0 就 return 了）：尺寸出来后补画一次
  if (tab.value === 'people' && !g6 && g6Ref.value?.clientWidth) nextTick(renderGraph)
  else if (tab.value === 'plot' && !g6Plot && plotRef.value?.clientWidth) nextTick(renderPlotLayer)
  else if (tab.value === 'items' && itemLayer.value === 'flow' && !g6Item && itemRef.value?.clientWidth)
    nextTick(renderItemFlow)
}
/* ResizeObserver 会连续回调，节流合并，避免拖窗口时反复 fitView 抖动 */
function scheduleResize() {
  window.clearTimeout(rsTimer)
  rsTimer = window.setTimeout(onResize, 120)
}
function ensureGraph() {
  if (tab.value === 'people') nextTick(renderGraph)
  else if (tab.value === 'plot') nextTick(renderPlotLayer)
  else if (tab.value === 'items' && itemLayer.value === 'flow') nextTick(renderItemFlow)
  else {
    if (g6) { g6.destroy(); g6 = null }
    if (g6Plot) { g6Plot.destroy(); g6Plot = null }
    if (g6Item) { g6Item.destroy(); g6Item = null }
  }
}
const selNode = computed(() => {
  const id = selName.value
  return nodes.value.find(n => n.name === id) || factionNodes.value.find(n => n.name === id) || null
})
const selRelations = computed(() => {
  const id = selName.value
  const src = graphLayer.value === 'faction' ? factionEdges.value : edges.value
  return src.filter(e => e.a === id || e.b === id)
})
function pick(name: string) { selName.value = selName.value === name ? '' : name }

const sevTag = (s: string) => s === '高' ? 'red' : s === '中' ? 'orange' : 'gray'
const groupIcon: Record<string, string> = { 修炼体系: 'shield', 地理势力: 'dashboard', 核心规则: 'settings' }
const groupColor: Record<string, string> = { 修炼体系: 'purple', 地理势力: 'blue', 核心规则: 'green' }

const route = useRoute()
onMounted(async () => {
  await store.loadBooks().catch(() => {})
  load()
  /* 任务中心带 ?job= 点进来：直接显示那个任务的日志 */
  const qj = String((route.query.job as string) || '').trim()
  if (qj) {
    jid.value = qj
    logOpen.value = true
    genLines.value = []
    since = 0
    if (timer) clearInterval(timer)
    timer = setInterval(poll, 900)
  } else {
    await syncTask()
  }
  window.addEventListener('resize', scheduleResize)
  if (tab.value === 'people') nextTick(renderGraph)
})
let ro: ResizeObserver | null = null
let rsTimer = 0
/* 画布容器：窗口尺寸没变、但容器宽度/高度变了（侧栏折叠、图例重排、说明栏出现）时，
   只监听 window.resize 是收不到的，画布会一直停在初始尺寸、右边或底部留一条空白。
   直接观察三个画布盒子本身：外层容器高度是固定的，图例重排带来的十几像素变化
   传不到外层，只有盯住 .g6 才能让画布跟上。 */
const roLast = new WeakMap<Element, { w: number; h: number }>()
function observeCanvas() {
  if (ro) { ro.disconnect(); ro = null }
  if (typeof ResizeObserver === 'undefined') return
  ro = new ResizeObserver((entries) => {
    let changed = false
    for (const e of entries) {
      const el = e.target as HTMLElement
      const w = el.clientWidth, h = el.clientHeight
      const prev = roLast.get(el)
      // 阈值滤掉滚动条 / 取整抖动；changeSize 不会改变 .g6 自身尺寸，所以不会形成循环
      if (prev && Math.abs(w - prev.w) < 2 && Math.abs(h - prev.h) < 4) continue
      roLast.set(el, { w, h })
      changed = true
    }
    if (changed) scheduleResize()
  })
  for (const el of [g6Ref.value, plotRef.value, itemRef.value]) {
    if (!el) continue
    roLast.set(el, { w: el.clientWidth, h: el.clientHeight })
    ro.observe(el)
  }
}
watch([g6Ref, plotRef, itemRef], observeCanvas, { flush: 'post' })

/* 已在本页时从任务中心切任务：换日志面板 */
watch(() => route.query.job, (v) => {
  const id = String(v || '').trim()
  if (!id || id === jid.value) return
  jid.value = id
  genLines.value = []
  since = 0
  logOpen.value = true
  if (timer) clearInterval(timer)
  timer = setInterval(poll, 900)
})
watch(() => store.curBook(), () => {
  selName.value = ''
  data.value = null
  load()
})
watch(() => tab.value, ensureGraph)
watch([g6Nodes, g6Edges, factionNodes, factionEdges, graphLayer], () => { if (tab.value === 'people') nextTick(renderGraph) })
watch(selName, syncHighlight)
watch([plotLayer, itemLayer], () => {
  if (tab.value === 'plot') nextTick(renderPlotLayer)
  if (tab.value === 'items') nextTick(renderItemFlow)
})
watch([plot, data], () => { if (tab.value === 'plot') nextTick(renderPlotLayer) })
/* 换排布就重画（用 watch 而不是 select 的 change，避免 v-model 与渲染抢时序） */
watch(peopleLayout, () => { if (tab.value === 'people') nextTick(renderGraph) })
watch(plotLayout, () => { if (tab.value === 'plot') nextTick(renderPlotLayer) })
watch(itemLayout, () => { if (tab.value === 'items' && itemLayer.value === 'flow') nextTick(renderItemFlow) })
onUnmounted(() => {
  if (timer) clearInterval(timer)
  window.removeEventListener('resize', scheduleResize)
  window.clearTimeout(rsTimer)
  if (ro) { ro.disconnect(); ro = null }
  if (g6) { g6.destroy(); g6 = null }
  if (g6Plot) { g6Plot.destroy(); g6Plot = null }
  if (g6Item) { g6Item.destroy(); g6Item = null }
})
</script>

<template>
  <div v-if="!state.books.length" class="card"><EmptyBox title="还没有作品" desc="先「新建作品」并完成拆解" /></div>
  <template v-else>
    <div class="page-head">
      <div>
        <h1>设定图谱</h1>
        <p>人物关系 · 世界观设定 · 关键道具 · 一致性信息，由拆解产出迭代生成，续写改编时可直接对照。</p>
      </div>
    </div>

    <div v-if="logOpen" class="sm-genbar">
      <span class="g-dot" :class="{ off: !generating }"></span>
      <span>{{ generating ? '正在分析章节与设定…' : '该任务已结束' }}</span>
      <pre class="g-line">{{ genLines[genLines.length - 1] || '准备中…' }}</pre>
    </div>

    <div v-if="!data && !loading" class="card">
      <EmptyBox title="还没有设定图谱" desc="基于已拆解的章节与设定生成人物关系、世界观、关键道具与一致性检查" />
      <div class="sm-empty-act">
        <BackLink />
        <button class="btn" @click="generate"><Icon name="graph" :size="14" /> 生成图谱</button>
      </div>
    </div>

    <div v-else class="sm-layout">
      <div class="card sm-main">
        <div class="sm-topbar">
          <div class="sm-tabs">
            <button v-for="t in TABS" :key="t.key" :class="{ active: tab === t.key }" @click="tab = t.key">
              <Icon :name="t.icon" :size="13" /> {{ t.label }}
              <span class="tab-n" :class="{ warn: t.key === 'issues' && conflicts.length }">
                {{ t.key === 'people' ? nodes.length : t.key === 'plot' ? (plot?.timeline || []).length : t.key === 'world' ? worldPoints : t.key === 'map' ? mapRegions.length : t.key === 'items' ? items.length : conflicts.length }}
              </span>
            </button>
          </div>
          <div class="head-acts">
            <span v-if="data" class="tag" :class="data.ai ? 'green' : 'gray'">{{ data.ai ? 'AI 增强' : '程序统计' }}</span>
            <span v-if="data" class="sub">更新于 {{ data.generated_at }}</span>
            <button class="btn sm ghost" @click="generate">
              <Icon name="graph" :size="13" /> {{ generating ? '生成中…' : '生成图谱' }}
            </button>
          </div>
        </div>

        <div class="sm-body" :class="{ 'sm-body-fill': tab === 'map' }">
          <template v-if="tab === 'people'">
            <div v-if="!nodes.length" class="sm-nil">拆解产出里没有人物卡，先运行拆解</div>
            <div v-else class="people-wrap">
              <div class="graph-box">
                <div class="layer-switch">
                  <label class="lay-ctl" title="切换人物关系 / 势力关系图层">图层
                    <div style="width:112px">
                      <SelectBox compact :model-value="graphLayer" :search-from="99"
                                 :options="[{ label: '人物关系', value: 'person' },
                                            { label: '势力关系', value: 'faction' }]"
                                 @update:model-value="setLayer" />
                    </div>
                  </label>
                  <label class="lay-ctl" title="节点挤在一起时换一种排布">
                    排布
                    <div style="width:104px">
                      <SelectBox compact :model-value="peopleLayout" :search-from="99"
                                 :options="LAYOUT_OPTS.people.map(k => ({ label: LAYOUT_NAME[k], value: k }))"
                                 @update:model-value="setPeopleLayout" />
                    </div>
                  </label>
                  <button class="lay-btn" title="重新排一次" @click="renderGraph">重排</button>
                </div>
                <div ref="g6Ref" class="g6"></div>
                <div v-if="graphDiag" class="graph-hint" style="color:var(--red)">{{ graphDiag }}</div>
                <div class="graph-hint">
                  拖拽节点排布 · 滚轮缩放 · 点节点查看详情<br />
                  <template v-if="graphLayer === 'person'">节点色 = 对主角态度 · 连线色 = 关系类型 · 线越粗关系越重 · 虚线 = 不公开 · 箭头 = 单向</template>
                  <template v-else>节点色 = 势力大类 · 连线色 = 势力关系类型 · 虚线 = 暗中关系（不公开）</template>
                </div>
              </div>
              <div class="people-side">
                <div v-if="selNode" class="ps-card">
                  <div class="ps-name">{{ selNode.name }}</div>
                  <div v-if="graphLayer === 'person'" class="ps-meta">
                    <span class="tag gray">{{ selNode.role || '角色' }}</span>
                    <span class="sub">出现 {{ selNode.count }} 章 · 首现第 {{ selNode.first }} 章</span>
                  </div>
                  <div v-if="selNode.identity" class="ps-line"><b>身份</b>{{ selNode.identity }}</div>
                  <div v-if="selNode.alignment" class="ps-line"><b>人设</b>{{ selNode.alignment }}</div>
                  <div v-if="selNode.factionCategory || selNode.factionName" class="ps-line"><b>势力</b>
                    {{ selNode.factionCategory || '未分类' }}<template v-if="selNode.factionName"> · {{ selNode.factionName }}</template>
                    <template v-if="selNode.subFaction"> · {{ selNode.subFaction }}</template>
                    <template v-if="selNode.loyalty">（忠诚 {{ pct(selNode.loyalty) }}）</template>
                  </div>
                  <div v-if="selNode.stance" class="ps-line"><b>对主角</b>{{ selNode.stance }}</div>
                  <div v-if="selNode.relationType" class="ps-line"><b>关系</b>
                    {{ selNode.relationTo ? selNode.relationTo + ' · ' : '' }}{{ selNode.relationType
                    }}<template v-if="selNode.relationStrength">（强度 {{ pct(selNode.relationStrength) }}）</template></div>
                  <div v-if="selNode.goal" class="ps-line"><b>目标</b>{{ selNode.goal }}</div>
                <div v-if="selNode.category" class="ps-line"><b>大类</b>{{ selNode.category }}</div>
                <div v-if="selNode.desc" class="ps-line"><b>简介</b>{{ selNode.desc }}</div>
                <div v-if="selNode.relType" class="ps-line"><b>关系</b>{{ selNode.relTo ? selNode.relTo + ' · ' : '' }}{{ selNode.relType }}</div>
                  <div v-if="selRelations.length" class="ps-rel">
                    <span v-for="(r, i) in selRelations" :key="i" class="tag"
                          :style="{ color: relColor(r.label), background: factionCategoryMeta(selNode.factionCategory)?.bg || '#f6f7f9' }">
                      {{ r.a === selNode.name ? r.b : r.a }} · {{ r.label
                      }}<template v-if="r.strength"> {{ pct(r.strength) }}</template>
                      <template v-if="r.secret">（不公开）</template>
                    </span>
                  </div>
                </div>
                <div v-if="graphLayer === 'person' && factionGroups.length" class="ps-facs">
                  <div class="ps-facs-h">势力分布
                    <button v-if="factionFilter" class="link-btn" @click="filterFaction(factionFilter)">清除筛选</button>
                    <span v-else>点标签只看该势力的人</span>
                  </div>
                  <div class="ps-facs-list">
                    <button v-for="[k, c] in factionGroups" :key="k" class="tag"
                            :class="{ on: factionFilter === k }"
                            :style="{ color: factionCategoryMeta(k)?.color, background: factionCategoryMeta(k)?.bg }"
                            @click="filterFaction(k)">{{ k }} {{ c }}</button>
                  </div>
                </div>
                <div class="ps-list">
                  <div v-for="(n, i) in sideNodes" :key="n.name" class="ps-item"
                       :class="{ on: selName === n.name }" @click="pick(n.name)">
                    <span class="ps-dot" :style="{ background: nodeColor(n, i) }"></span>
                    <span class="ps-nm">{{ n.name }}</span>
                    <span class="ps-ct">{{ n.count }} 章</span>
                  </div>
                </div>
              </div>
            </div>
          </template>

          <template v-else-if="tab === 'plot'">
            <div v-if="plotLayer === 'timeline' && (!plot || !(plot.timeline || []).length)" class="sm-nil">
              设定库还没有「时间线」内容——在作品设定里补一段「时间线：…」即可看到剧情脉络
            </div>
            <div v-else-if="plotLayer === 'foreshadow' && !foreshadows.length" class="sm-nil">
              设定库还没有可解析的伏笔——在作品设定补「伏笔：…」或剧情脉络含伏笔即会在此展示
            </div>
            <div v-else-if="plotLayer === 'axis' && !timeEvents.length" class="sm-nil">
              设定库还没有时间轴事件（卷信息或时间线事件）
            </div>
            <div v-else class="people-wrap plot-wrap">
              <div class="graph-box">
                <div class="layer-switch">
                  <label class="lay-ctl" title="切换剧情视图">图层
                    <div style="width:118px">
                      <SelectBox compact :model-value="plotLayer" :search-from="99"
                                 :options="[{ label: '时间线', value: 'timeline' },
                                            { label: '伏笔回收', value: 'foreshadow' },
                                            { label: '时间轴', value: 'axis' },
                                            { label: '情绪流', value: 'emotion' }]"
                                 @update:model-value="setPlotLayer" />
                    </div>
                  </label>
                  <label v-if="plotLayer !== 'emotion'" class="lay-ctl" title="节点挤在一起时换一种排布">
                    排布
                    <div style="width:104px">
                      <SelectBox compact :model-value="plotLayout" :search-from="99"
                                 :options="LAYOUT_OPTS.plot.map(k => ({ label: LAYOUT_NAME[k], value: k }))"
                                 @update:model-value="setPlotLayout" />
                    </div>
                  </label>
                  <button v-if="plotLayer !== 'emotion'" class="lay-btn" title="重新排一次" @click="renderPlotLayer">重排</button>
                </div>
                <div v-if="plotLayer === 'timeline'" class="plot-legend">
                  <span class="lg"><i style="background:#2f6bff"></i>时间线（因果推进）</span>
                  <span class="lg"><i style="background:#1c7ed6"></i>主线阶段</span>
                  <span class="lg"><i style="background:#0ca678"></i>支线 / 情感线</span>
                  <span class="lg"><i style="background:#ae3ec9"></i>伏笔</span>
                  <span class="lg"><i style="background:#e8590c"></i>核心悬念</span>
                  <span class="lg"><i style="background:#e64980"></i>人物关联（虚线）</span>
                  <span class="lg"><i style="background:#d6336c;border-radius:50%"></i>人物</span>
                  <span class="lg src">{{ plot?.ai ? 'AI 生成' : '程序解析' }}</span>
                </div>
                <div ref="plotRef" class="g6" v-show="plotLayer !== 'emotion'"></div>
                <div v-if="plotLayer === 'emotion'" class="emo-box">
                  <div v-if="!emotionCurve.length" class="sm-nil">
                    还没有情绪流数据——重新拆解一次这本书，或在作品设定里给章节补上「情绪 / 张力」
                  </div>
                  <template v-else>
                    <div class="emo-chart">
                      <div v-for="p in emotionCurve" :key="'c' + p.chapter" class="emo-col"
                           :title="'第' + p.chapter + '章 · ' + (p.emotion || '未标情绪') + ' · 峰值 ' + (p.tension || 0) + '/10'">
                        <span class="emo-bar" :class="tensionTone(p.tension)"
                              :style="{ height: Math.max(4, (Number(p.tension) || 0) * 10) + '%' }"></span>
                        <span class="emo-ch">{{ p.chapter }}</span>
                      </div>
                    </div>
                    <div class="emo-legend">
                      <span class="lg"><i class="low"></i>1~3 铺垫</span>
                      <span class="lg"><i class="mid"></i>4~6 摩擦</span>
                      <span class="lg"><i class="hot"></i>7~9 爆发</span>
                      <span class="lg"><i class="hi"></i>10 命运级</span>
                      <span class="lg src">横轴=章号，柱高=情绪峰值</span>
                    </div>
                    <div class="emo-grid">
                      <div class="emo-pane">
                        <div class="emo-title">情绪走向（逐章）</div>
                        <div class="emo-rows">
                          <div v-for="p in emotionCurve" :key="'r' + p.chapter" class="emo-row">
                            <span class="er-ch">第{{ p.chapter }}章</span>
                            <span class="er-flow">
                              <template v-for="(e, j) in String(p.emotion || '').split('→')" :key="j">
                                <span v-if="j" class="er-arrow">→</span>
                                <span v-if="e" class="er-chip">{{ e }}</span>
                              </template>
                              <span v-if="!p.emotion" class="er-nil">未标情绪</span>
                            </span>
                            <span class="er-ten" v-if="p.tension">{{ p.tension }}/10</span>
                          </div>
                        </div>
                      </div>
                      <div class="emo-pane">
                        <div class="emo-title">
                          钩子类型分布
                          <span class="emo-note" v-if="hookStats.length">共 {{ hooks.length }} 个章末钩子</span>
                        </div>
                        <div class="hook-stats" v-if="hookStats.length">
                          <span v-for="s in hookStats" :key="s[0]" class="hs">{{ s[0] }}<b>{{ s[1] }}</b></span>
                        </div>
                        <div v-else class="er-nil">还没有章末钩子类型</div>
                        <div class="emo-title" style="margin-top:10px">爽点兑现（{{ payoffs.length }}）</div>
                        <div class="emo-list">
                          <div v-for="p in payoffs.slice(0, 8)" :key="'p' + p.chapter" class="el-row">
                            <span class="el-ch">第{{ p.chapter }}章</span><span>{{ p.text }}</span>
                          </div>
                          <div v-if="!payoffs.length" class="er-nil">还没有标注爽点</div>
                        </div>
                        <div class="emo-title" style="margin-top:10px">埋下的铺垫（{{ setups.length }}）</div>
                        <div class="emo-list">
                          <div v-for="p in setups.slice(0, 8)" :key="'s' + p.chapter" class="el-row">
                            <span class="el-ch">第{{ p.chapter }}章</span><span>{{ p.text }}</span>
                          </div>
                          <div v-if="!setups.length" class="er-nil">还没有标注铺垫</div>
                        </div>
                      </div>
                    </div>
                  </template>
                </div>
                <div class="graph-hint">
                  <template v-if="plotLayer === 'timeline'">横向 = 时间推进（因果链）· 滚轮缩放 · 拖拽画布 · 点节点查看完整内容</template>
                  <template v-else-if="plotLayer === 'foreshadow'">每行 = 一个伏笔：左侧埋下（紫）→ 右侧回收（绿=已回收 / 灰=待确认），连线标注回收章号 · 点节点看详情</template>
                  <template v-else-if="plotLayer === 'emotion'">柱高 = 情绪峰值 · 悬停看该章情绪走向 · 右侧看钩子类型分布与爽点 / 铺垫清单</template>
                  <template v-else>X 轴 = 章节号 · 橙=卷界节点 / 蓝=事件节点 · 连线＝时间推进链 · 点节点看详情</template>
                </div>
              </div>
              <div class="people-side">
                <div v-if="selPlot" class="ps-card">
                  <div class="ps-name">{{ PLOT_LABEL[selPlot.type] || selPlot.type }}</div>
                  <div class="ps-line">{{ selPlot.text }}</div>
                </div>
                <div v-else class="ps-card">
                  <div class="ps-name">{{ plotLayer === 'timeline' ? '剧情脉络' : plotLayer === 'foreshadow' ? '伏笔回收' : plotLayer === 'emotion' ? '情绪流' : '时间轴' }}</div>
                  <div class="ps-line" v-if="plotLayer === 'timeline'">
                    时间线 {{ (plot.timeline || []).length }} 条 · 主线 {{ (plot.mainline || []).length }} ·
                    支线 {{ (plot.subplots || []).length }} · 伏笔 {{ (plot.foreshadow || []).length }} ·
                    悬念 {{ (plot.suspense || []).length }} · 冲突 {{ (plot.conflict || []).length }}。点图上节点查看完整内容；人物圆点挂在其出场的时间线事件上。
                  </div>
                  <div class="ps-line" v-else-if="plotLayer === 'foreshadow'">
                    共 {{ foreshadows.length }} 条伏笔。每行左侧「埋下」、右侧「回收」（绿=已回收 / 灰=待确认），连线标注回收章号。点节点看完整内容。
                  </div>
                  <div class="ps-line" v-else-if="plotLayer === 'emotion'">
                    {{ emotionCurve.length }} 章有情绪标注 · {{ hooks.length }} 个章末钩子 · {{ payoffs.length }} 处爽点 ·
                    {{ setups.length }} 处铺垫。柱高＝情绪峰值（1~3 铺垫 / 4~6 摩擦 / 7~9 爆发 / 10 命运级）。
                  </div>
                  <div class="ps-line" v-else>
                    共 {{ timeEvents.length }} 个时间轴锚点（卷界 + 事件）。X 轴为章节号，橙=卷界、蓝=事件，连线为时间推进链。
                  </div>
                </div>
              </div>
            </div>
          </template>

          <template v-else-if="tab === 'world'">
            <div v-if="!world.length" class="sm-nil">拆解产出里没有世界观设定</div>
            <template v-else>
              <div class="world-grid">
                <div v-for="g in world" :key="g.group" class="world-card">
                  <div class="wc-head">
                    <span class="module-ico sm" :class="groupColor[g.group] || 'blue'">
                      <Icon :name="groupIcon[g.group] || 'file'" :size="14" />
                    </span>
                    <span class="wc-title">{{ g.group }}</span>
                    <span class="sub">{{ (g.points || []).length }} 条</span>
                  </div>
                  <div class="wc-list">
                    <div v-for="(p, i) in g.points" :key="i" class="wc-pt">
                      <span class="wc-txt">{{ p.text }}</span>
                      <span v-if="(p.chapters || []).length" class="wc-src">来源：第 {{ p.chapters.join('、') }} 章</span>
                    </div>
                  </div>
                </div>
              </div>
              <div v-if="d.era" class="era-bar"><b>时代背景</b>{{ d.era }}</div>
              <div v-if="chapters.length" class="chapter-summary">
                <div class="cs-head">
                  <span class="module-ico sm blue"><Icon name="book" :size="14" /></span>
                  <span class="wc-title">章节概括</span>
                  <span class="sub">{{ chapters.length }} 章</span>
                </div>
                <div class="cs-tools">
                  <input v-model="chapterQuery" class="cs-input" placeholder="搜索章号或标题" />
                  <div style="width:140px">
                    <SelectBox compact :model-value="chapterVol" allow-empty empty-label="全部卷"
                               :options="volumes.map(v => ({ label: v.title, value: v.title }))"
                               placeholder="全部卷" @update:model-value="v => chapterVol = v" />
                  </div>
                </div>
                <VirtualList class="cs-list" :items="filteredChapters" :estimate="96"
                             :key-of="(c: any) => c.no" v-slot="{ item: c }">
                  <div class="cs-item">
                    <div class="cs-meta">
                      <span class="cs-no">第 {{ c.no }} 章</span>
                      <span class="cs-title">{{ c.title }}</span>
                    </div>
                    <div v-if="c.summary" class="cs-sum">{{ c.summary }}</div>
                    <div v-if="(c.points || []).length" class="cs-points">
                      <span class="cs-pt-tag">要点</span>
                      <span v-for="(pt, i) in c.points.slice(0, 4)" :key="i" class="cs-pt">{{ pt }}</span>
                    </div>
                    <div v-if="(c.roles || []).length" class="cs-roles">
                      <span v-for="r in c.roles.slice(0, 10)" :key="r" class="chip">{{ r }}</span>
                    </div>
                  </div>
                </VirtualList>
              </div>
            </template>
          </template>

          <template v-else-if="tab === 'map'">
            <WorldMap :map-data="d.map" hint="当前作品还没有地图数据：点右上角「生成图谱」重新生成，地图会随人物、势力、章节一起产出。" />
          </template>

          <template v-else-if="tab === 'items'">
            <div class="items-wrap">
              <div class="graph-box">
                <div class="layer-switch">
                  <label class="lay-ctl" title="切换道具视图">视图
                    <div style="width:96px">
                      <SelectBox compact :model-value="itemLayer" :search-from="99"
                                 :options="[{ label: '列表', value: 'list' },
                                            { label: '流向', value: 'flow' }]"
                                 @update:model-value="setItemLayer" />
                    </div>
                  </label>
                  <template v-if="itemLayer === 'flow' && itemLinks.length">
                    <label class="lay-ctl" title="节点挤在一起时换一种排布">
                      排布
                      <div style="width:104px">
                        <SelectBox compact :model-value="itemLayout" :search-from="99"
                                   :options="LAYOUT_OPTS.items.map(k => ({ label: LAYOUT_NAME[k], value: k }))"
                                   @update:model-value="setItemLayout" />
                      </div>
                    </label>
                    <button class="lay-btn" title="重新排一次" @click="renderItemFlow">重排</button>
                  </template>
                </div>
                <div v-if="!items.length" class="sm-nil">拆解产出里没有关键道具</div>
                <template v-else>
                  <table v-if="itemLayer === 'list'" class="items-tb">
                    <thead>
                      <tr>
                        <th style="width:22%">道具</th><th style="width:20%">持有人</th>
                        <th>作用</th><th style="width:20%">关键章节</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="it in items" :key="it.name">
                        <td class="it-name">{{ it.name }}<div v-if="it.note" class="it-note">{{ it.note }}</div></td>
                        <td>{{ it.holder || '—' }}</td>
                        <td class="it-effect">{{ it.effect || '—' }}</td>
                        <td class="it-chs">
                          <span v-if="(it.chapters || []).length">第 {{ it.chapters.join('、') }} 章</span>
                          <span v-else>—</span>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                  <div v-else-if="!itemLinks.length" class="sm-nil">拆解产出里没有可解析的道具流向（持有人含「A → B」或作用含「克制 / 被克制」时生成）</div>
                  <template v-else>
                    <div ref="itemRef" class="g6"></div>
                    <div class="graph-hint">
                      金=道具 · 蓝=人物 · 蓝边=持有变更（A→B）· 灰边=持有 · 红边=克制 / 被克制 · 点节点不展开详情
                    </div>
                  </template>
                </template>
              </div>
            </div>
          </template>

          <template v-else>
            <div v-if="!conflicts.length" class="cons-ok">
              <Icon name="check" :size="16" /> 未发现明显的前后矛盾（道具数量 / 年龄 / 规则 / 时间线）
            </div>
            <div v-for="(c, i) in conflicts" :key="i" class="cons-card" :class="'sev-' + sevTag(c.severity)">
              <div class="cons-head">
                <span class="tag" :class="sevTag(c.severity)">严重度：{{ c.severity }}</span>
                <span class="cons-title">{{ c.title }}</span>
              </div>
              <div class="cons-detail">{{ c.detail }}</div>
              <div v-if="(c.chapters || []).length" class="cons-src">涉及：第 {{ c.chapters.join('、') }} 章</div>
            </div>
            <div class="cons-foot">一致性信息只做提示，不自动改写正文。</div>
          </template>
        </div>
      </div>
    </div>
  </template>
</template>

<style scoped>
.head-acts { display: flex; align-items: center; gap: 10px; }
.sub { font-size: 12px; color: var(--text-3); }
.sm-genbar { display: flex; align-items: center; gap: 10px; padding: 10px 14px; margin-bottom: 12px;
  border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--card);
  font-size: 12px; color: var(--text-2); }
.g-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--primary); animation: pulse 1s infinite; flex: none; }
.g-dot.off { background: var(--text-3, #8a94a6); animation: none; }
@keyframes pulse { 0%, 100% { opacity: 1 } 50% { opacity: .3 } }
.g-line { margin: 0; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-size: 12px; color: var(--text-3); font-family: inherit; }
.sm-empty-act { display: flex; gap: 10px; justify-content: center; padding: 0 0 20px; }

/* 占满视口剩余高度，内部各自滚动，页面不出现滚动条 */
.sm-layout { display: grid; grid-template-columns: 1fr; gap: 16px; flex: 1; min-height: 320px; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: var(--radius-md); }

.sm-main { display: flex; flex-direction: column; min-height: 0; overflow: hidden; padding: 0; }
/* 顶栏：左页签 + 右状态/刷新，底部一条分割线 */
.sm-topbar { display: flex; align-items: center; gap: 12px; padding: 8px 14px 0;
  border-bottom: 1px solid var(--border); flex: none; }
.sm-topbar .head-acts { display: flex; align-items: center; gap: 10px; flex: none; padding-bottom: 8px; }
.sm-tabs { display: flex; gap: 2px; flex: 1; min-width: 0; flex-wrap: wrap; }
.sm-tabs button { display: flex; align-items: center; gap: 6px; border: none; background: none; cursor: pointer;
  padding: 8px 12px; font-size: 13px; color: var(--text-2); border-radius: 8px 8px 0 0; }
.sm-tabs button.active { color: var(--text); font-weight: 700; background: var(--bg); }
.tab-n { font-size: 10px; background: var(--border-strong); color: var(--text-2);
  border-radius: 999px; padding: 0 6px; line-height: 15px; }
.tab-n.warn { background: var(--red); color: #fff; }
.sm-body { flex: 1; min-height: 0; overflow-y: auto; padding: 14px; }
/* 世界地图：占满内容区高度、自己按容器等比缩放，不出现内部滚动条 */
.sm-body.sm-body-fill { display: flex; flex-direction: column; overflow: hidden; }
.sm-body.sm-body-fill > * { flex: 1; min-height: 0; }
.sm-nil { font-size: 12px; color: var(--text-3); padding: 30px 0; text-align: center; }

/* 人物关系：容器不撑高不出滚动条，超高只在右侧人物标签列表内滚动 */
.people-wrap { display: grid; grid-template-columns: 1fr 260px; gap: 12px; height: 100%; min-height: 0; overflow: hidden; }
.items-wrap { display: flex; flex-direction: column; min-height: 0; height: 100%; }
.graph-box { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
/* 道具 tab 的 graph-box 不在 grid 里，得自己撑开，否则 .g6 高度为 0、流向图画不出来 */
.items-wrap .graph-box { flex: 1; min-height: 480px; }
.layer-switch { display: flex; align-items: center; gap: 12px; padding-bottom: 8px; flex: none; }
/* 图层 / 排布统一走下拉（与正文、设置等页面同一套交互）；
   第一个标签不参与靠右推，排布仍靠右，和图层分开避免误点 */
.lay-ctl { margin-left: auto; display: inline-flex; align-items: center; gap: 6px;
  font-size: 12px; color: var(--text-3); cursor: pointer; }
.layer-switch > .lay-ctl:first-child { margin-left: 0; }
.lay-btn { margin-left: 6px; padding: 5px 10px; border: 1px solid var(--border); background: var(--bg);
  border-radius: 999px; font-size: 12px; color: var(--text-2); cursor: pointer; transition: .15s; }
.lay-btn:hover { border-color: var(--border-strong); color: var(--text); }
/* 不要写 height:100%：父级高度为 auto 时它会被解析成画布自身高度，
   每次重画都把容器再撑高约一个画布高度（切图层时越切越高） */
.g6 { width: 100%; flex: 1; min-height: 0; }
.g6 canvas { outline: none; }
.graph-hint { font-size: 11px; color: var(--text-3); text-align: center; padding-top: 4px; }

/* 剧情脉络图例 */
.plot-legend { display: flex; flex-wrap: wrap; gap: 14px; padding: 0 4px 8px; font-size: 12px; color: var(--text-2); flex: none; }
.plot-legend .lg { display: inline-flex; align-items: center; gap: 5px; }
.plot-legend .lg i { width: 12px; height: 8px; border-radius: 2px; display: inline-block; }
.plot-legend .lg.src { margin-left: auto; color: var(--text-3); }

/* ---- 情绪流：柱状曲线 + 钩子分布 + 爽点/铺垫清单 ---- */
.emo-box { flex: 1; min-height: 0; overflow: auto; padding: 2px 4px 8px; }
.emo-chart { display: flex; align-items: flex-end; gap: 3px; height: 190px; padding: 6px 4px 0; border-bottom: 1px solid var(--border); }
.emo-col { flex: 1 1 0; min-width: 8px; display: flex; flex-direction: column; align-items: center; justify-content: flex-end;
  height: 100%; cursor: default; }
.emo-bar { width: 100%; max-width: 22px; border-radius: 3px 3px 0 0; background: var(--border-strong);
  transition: height .18s ease, filter .15s; }
.emo-col:hover .emo-bar { filter: brightness(1.25); }
.emo-bar.low { background: #4c6ef5; }
.emo-bar.mid { background: #15aabf; }
.emo-bar.hot { background: var(--orange); }
.emo-bar.hi  { background: var(--red); }
.emo-ch { font-size: 9px; color: var(--text-3); margin-top: 3px; font-variant-numeric: tabular-nums; }
.emo-legend { display: flex; flex-wrap: wrap; gap: 12px; padding: 8px 4px 10px; font-size: 11px; color: var(--text-2); }
.emo-legend .lg { display: inline-flex; align-items: center; gap: 4px; }
.emo-legend .lg i { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
.emo-legend .lg i.low { background: #4c6ef5; }
.emo-legend .lg i.mid { background: #15aabf; }
.emo-legend .lg i.hot { background: var(--orange); }
.emo-legend .lg i.hi  { background: var(--red); }
.emo-legend .lg.src { margin-left: auto; color: var(--text-3); }
.emo-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.emo-pane { border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 8px 10px; background: var(--card); }
.emo-title { font-size: 12px; font-weight: 600; color: var(--text); margin-bottom: 6px; }
.emo-note { font-weight: 400; font-size: 11px; color: var(--text-3); margin-left: 6px; }
.emo-rows { display: flex; flex-direction: column; gap: 3px; max-height: 210px; overflow: auto; }
.emo-row { display: flex; align-items: center; gap: 6px; font-size: 11px; line-height: 1.7; }
.er-ch { flex: none; width: 46px; color: var(--text-3); font-variant-numeric: tabular-nums; }
.er-flow { display: inline-flex; align-items: center; gap: 3px; flex-wrap: wrap; }
.er-chip { padding: 0 6px; border-radius: 999px; background: rgba(140, 120, 255, .14); color: #8c78ff; font-size: 11px; }
.er-arrow { color: var(--text-3); font-size: 10px; }
.er-ten { margin-left: auto; color: var(--text-3); font-variant-numeric: tabular-nums; }
.er-nil { color: var(--text-3); font-size: 11px; }
.hook-stats { display: flex; flex-wrap: wrap; gap: 6px; }
.hook-stats .hs { padding: 2px 8px; border: 1px solid var(--border); border-radius: 999px; font-size: 11px; color: var(--text-2); }
.hook-stats .hs b { margin-left: 4px; color: var(--text); font-variant-numeric: tabular-nums; }
.emo-list { display: flex; flex-direction: column; gap: 3px; max-height: 150px; overflow: auto; }
.el-row { display: flex; gap: 6px; font-size: 11px; line-height: 1.65; color: var(--text-2); }
.el-ch { flex: none; color: var(--text-3); font-variant-numeric: tabular-nums; }
/* 高度跟随可用区域：.people-wrap 已经给了 height:100%，这里只保留最小高度保底。
   不要再写 height:auto —— auto 会被画布尺寸反推，窗口每次缩放高度都会往上爬；
   也不要写死 clamp(...)，那样窗口变高时画布不会跟着长，底部留一大块空白。 */
.plot-wrap { min-height: 480px; }
.people-side { display: flex; flex-direction: column; gap: 10px; min-height: 0; border-left: 1px solid var(--border); padding-left: 12px; }
.ps-card { border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 10px; background: var(--bg); flex: none; }
.ps-name { font-size: 14px; font-weight: 700; margin-bottom: 6px; }
.ps-meta { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 6px; }
.ps-line { font-size: 12px; color: var(--text-2); line-height: 1.7; }
.ps-line b { color: var(--text-3); font-weight: 400; margin-right: 6px; }
.ps-rel { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 8px; }
.ps-rel .tag { font-size: 11px; }
/* 势力分布：一排可点的势力大类标签，点击后图谱与右侧名单一起收窄 */
.ps-facs { flex: none; border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 8px 10px; }
.ps-facs-h { display: flex; align-items: baseline; gap: 6px; font-size: 11px; font-weight: 600; color: var(--text-2); margin-bottom: 6px; }
.ps-facs-h span { font-weight: 400; color: var(--text-3); font-size: 10px; }
/* 势力标签等宽两列：名称长短不一时不再参差不齐 */
.ps-facs-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 4px; }
.ps-facs-list .tag {
  cursor: pointer; border: 1px solid transparent; justify-content: center;
  min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.ps-facs-list .tag.on { border-color: currentColor; font-weight: 600; }
.ps-list { flex: 1; min-height: 0; overflow-y: auto; }
.ps-item { display: flex; align-items: center; gap: 8px; padding: 5px 6px; border-radius: 6px; cursor: pointer; font-size: 12px; color: var(--text-2); }
.ps-item:hover { background: var(--bg); }
.ps-item.on { background: var(--primary-bg); color: var(--primary); }
.ps-dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
.ps-nm { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ps-ct { font-size: 11px; color: var(--text-3); }

/* 世界观 */
.world-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; }
.world-card { border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg); padding: 12px; }
.wc-head { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.module-ico { width: 26px; height: 26px; border-radius: 7px; display: inline-flex; align-items: center; justify-content: center; flex: none; }
.module-ico.blue { background: rgba(76, 110, 245, .14); color: #4c6ef5; }
.module-ico.green { background: rgba(18, 184, 134, .14); color: #12b886; }
.module-ico.purple { background: rgba(174, 62, 201, .14); color: #ae3ec9; }
.wc-title { font-size: 13px; font-weight: 700; flex: 1; }
.wc-list { display: flex; flex-direction: column; gap: 8px; }
.wc-pt { font-size: 12px; color: var(--text-2); line-height: 1.65; }
.wc-txt { display: block; }
.wc-src { display: block; font-size: 11px; color: var(--primary); margin-top: 2px; }
.era-bar { margin-top: 12px; padding: 10px 12px; border-radius: var(--radius-sm); background: var(--bg);
  border: 1px dashed var(--border-strong); font-size: 12px; color: var(--text-2); line-height: 1.7; }
.era-bar b { color: var(--text-3); font-weight: 400; margin-right: 8px; }

/* 章节概括 */
.chapter-summary { margin-top: 12px; padding: 12px 14px; border: 1px solid var(--border);
  border-radius: var(--radius-md); background: var(--card); }
.cs-head { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.cs-tools { display: flex; gap: 8px; margin-bottom: 10px; }
.cs-input { flex: 1; min-width: 0; padding: 6px 10px; border: 1px solid var(--border);
  border-radius: 8px; background: var(--bg); color: var(--text); font-size: 13px; font-family: inherit; }
.cs-select { padding: 6px 8px; border: 1px solid var(--border); border-radius: 8px;
  background: var(--bg); color: var(--text); font-size: 13px; font-family: inherit; }
.cs-list { max-height: 52vh; padding-right: 4px; }
.cs-item { padding: 8px 10px; border: 1px solid var(--border); border-radius: 8px; background: var(--bg); }
.cs-meta { display: flex; align-items: baseline; gap: 8px; margin-bottom: 4px; }
.cs-no { font-size: 12px; color: var(--text-3); flex: none; }
.cs-title { font-weight: 600; font-size: 13px; color: var(--text); }
.cs-sum { font-size: 12px; color: var(--text-2); line-height: 1.6;
  display: -webkit-box; line-clamp: 2; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.cs-roles { margin-top: 6px; display: flex; flex-wrap: wrap; gap: 4px; }
.cs-more { margin-top: 8px; font-size: 12px; color: var(--text-3); text-align: center; }
.cs-points { margin-top: 6px; display: flex; flex-wrap: wrap; gap: 4px; align-items: baseline; }
.cs-pt-tag { font-size: 11px; color: var(--text-3); flex: none; }
.cs-pt { font-size: 11px; color: var(--text-2); background: var(--bg); border: 1px solid var(--border);
  border-radius: 6px; padding: 1px 6px; }

/* 关键道具 */
.items-tb { width: 100%; border-collapse: collapse; font-size: 12px; }
.items-tb th { text-align: left; font-weight: 400; color: var(--text-3); font-size: 11px;
  padding: 8px 10px; border-bottom: 1px solid var(--border); white-space: nowrap; }
.items-tb td { padding: 10px; border-bottom: 1px solid var(--border); color: var(--text-2); vertical-align: top; line-height: 1.6; }
.items-tb tr:hover td { background: var(--bg); }
.it-name { color: var(--text); font-weight: 700; }
.it-note { font-weight: 400; font-size: 11px; color: var(--text-3); margin-top: 2px; }
.it-effect { color: var(--text-2); }
.it-chs { color: var(--text-3); }

/* 一致性 */
.cons-ok { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-2);
  padding: 16px; border: 1px dashed var(--border-strong); border-radius: var(--radius-sm); }
.cons-card { border: 1px solid var(--border); border-left: 3px solid var(--border-strong);
  border-radius: var(--radius-sm); padding: 10px 12px; margin-bottom: 10px; background: var(--card); }
.cons-card.sev-red { border-left-color: var(--red); }
.cons-card.sev-orange { border-left-color: var(--orange); }
.cons-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 6px; }
.cons-title { font-size: 13px; font-weight: 700; }
.spacer { flex: 1; }
.cons-detail { font-size: 12px; color: var(--text-2); line-height: 1.7; }
.cons-src { font-size: 11px; color: var(--text-3); margin-top: 4px; }
.cons-foot { font-size: 11px; color: var(--text-3); padding-top: 4px; }

@media (max-width: 1100px) {
  .sm-layout { grid-template-columns: 1fr; flex: none; }
  .sm-main { min-height: 480px; }
  /* 窄屏卡片高度由内容决定：地图页撤销 flex 填充，改由内容自然撑开 */
  .sm-body.sm-body-fill { display: block; overflow: visible; }
  .sm-body.sm-body-fill > * { flex: none; }
  .sm-topbar { flex-wrap: wrap; row-gap: 6px; }
  .people-wrap { grid-template-columns: 1fr; overflow: visible; }
  .people-side { border-left: none; border-top: 1px solid var(--border); padding-left: 0; padding-top: 12px; }
  /* 单列后高度由内容决定，.g6 的 height:100% 会解析成 0（画布建不出来）；
     这里补最小高度，和图例 / 工具栏一起把画布撑开 */
  .graph-box { min-height: 380px; }
}

/* 手机：顶部标签改成可横向滑动的一行，避免被右侧操作区挤成竖排文字 */
@media (max-width: 760px) {
  .sm-topbar { flex-direction: column; align-items: stretch; gap: 8px; padding: 10px 12px 0;
    min-width: 0; overflow: hidden; }
  .sm-tabs {
    flex-wrap: nowrap; overflow-x: auto; gap: 4px; padding-bottom: 6px;
    width: 100%; max-width: 100%; min-width: 0;
    scrollbar-width: none; -webkit-overflow-scrolling: touch;
  }
  .sm-tabs::-webkit-scrollbar { height: 0; }
  .sm-tabs button { flex: none; white-space: nowrap; padding: 7px 10px; }
  .sm-topbar .head-acts { width: 100%; max-width: 100%; justify-content: flex-start;
    flex-wrap: wrap; row-gap: 6px; padding-bottom: 8px; }
  .sm-topbar .head-acts .sub { white-space: normal; }
  .sm-body { padding: 10px 12px 14px; }
  .sm-main { min-height: 0; }
  .graph-box { min-height: 380px; }
  .layer-switch { flex-wrap: wrap; row-gap: 6px; }
  .people-side { max-height: 320px; overflow-y: auto; }
  .items-wrap { overflow-x: auto; }
  .items-tb { min-width: 560px; }
}
</style>
