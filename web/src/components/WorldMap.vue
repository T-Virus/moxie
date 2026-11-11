<script setup lang="ts">
/* 设定地图：按 storymap.json 的 map 数据画矢量层级地图。
   · 区域按「区域 → 地点」逐级下钻，点击区块看该地的势力 / 角色 / 事件；
   · 顶部「剧情进度」可按章号回看，只显示第 N 章及之前发生的事；
   · 角色 / 势力 / 道具名称都能点回对应卡片页，数据与实体是同一份引用。 */
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import Icon from './Icon.vue'

const props = withDefaults(defineProps<{
  mapData?: any
  mobile?: boolean
  hint?: string
}>(), { mapData: null, mobile: false, hint: '' })

const router = useRouter()

const VW = 1000
const VH = 620
const PALETTE = [
  ['#eaf1ff', '#7d9fe8'], ['#e8f6f0', '#66b79b'], ['#fdf2e4', '#d8a75c'],
  ['#f4edfd', '#a98bd8'], ['#e9f6fb', '#66aecb'], ['#fdeeee', '#d98585'],
  ['#eef7e6', '#8fbb66'], ['#fdf0f7', '#cf8db3'],
]

const regions = computed<any[]>(() =>
  Array.isArray(props.mapData?.regions) ? props.mapData.regions.filter((r: any) => r?.name) : [])
const scenes = computed<any[]>(() =>
  Array.isArray(props.mapData?.scenes) ? props.mapData.scenes.filter((s: any) => Number(s?.chapter) > 0) : [])
const regionMap = computed(() => new Map<string, any>(regions.value.map((r: any) => [r.name, r])))
const maxCh = computed(() => scenes.value.reduce((m, s) => Math.max(m, Number(s.chapter) || 0), 0))
const limit = ref(1)
const path = ref<string[]>([])
const selected = ref('')
/* 换书 / 重新生成图谱后：进度条与下钻层级都回到初始状态 */
watch(() => props.mapData, () => {
  limit.value = maxCh.value || 1
  path.value = []
  selected.value = ''
}, { immediate: true })

const shown = computed(() => scenes.value.filter(s => Number(s.chapter) <= limit.value))

const parent = computed(() => path.value[path.value.length - 1] || '')
const curRegion = computed(() => (parent.value ? regionMap.value.get(parent.value) : null))

function childrenOf(name: string) {
  return regions.value.filter((r: any) => (r.parent || '') === name)
}
const children = computed(() => childrenOf(parent.value))

/** 该区域及其所有下级名称 */
function subtree(name: string): Set<string> {
  const out = new Set<string>([name])
  let add = true
  while (add) {
    add = false
    for (const r of regions.value) {
      if (r.parent && out.has(r.parent) && !out.has(r.name)) {
        out.add(r.name)
        add = true
      }
    }
  }
  return out
}

function scenesOf(names: Set<string>) {
  return shown.value.filter(s => names.has(String(s.region || '')))
}

function enter(region: any) {
  if (!region?.name || !childrenOf(region.name).length) return
  path.value = [...path.value, region.name]
  selected.value = ''
}
function select(region: any) { selected.value = region.name }
function goRoot() { path.value = []; selected.value = '' }
function goTo(i: number) { path.value = path.value.slice(0, i + 1); selected.value = '' }

/* ---------------- 布局：按场景数加权的切片树，保证区块大小反映戏份 ---------------- */
type Cell = {
  region: any; d: string; cx: number; cy: number
  fill: string; stroke: string; fs: number; label: string
  scenes: number; chars: number; facs: number
}
function hash(s: string) {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619) }
  return h >>> 0
}
function blob(cx: number, cy: number, hw: number, hh: number, seed: string) {
  const n = 20
  let d = ''
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2
    const noise = ((hash(seed + '#' + i) % 100) / 100 - 0.5) * 0.16
    const x = cx + Math.cos(a) * hw * (0.9 + noise)
    const y = cy + Math.sin(a) * hh * (0.9 + noise)
    d += (i ? 'L' : 'M') + x.toFixed(1) + ' ' + y.toFixed(1)
  }
  return d + 'Z'
}
const cells = computed<Cell[]>(() => {
  const list = children.value
  if (!list.length) return []
  const items = list.map((r: any) => {
    const names = subtree(r.name)
    const ss = scenesOf(names)
    return {
      region: r, weight: Math.max(1, ss.length),
      scenes: ss.length,
      chars: new Set(ss.flatMap(s => s.characters || [])).size,
      facs: new Set(ss.flatMap(s => s.factions || [])).size,
    }
  })
  const rects: { item: any; x: number; y: number; w: number; h: number }[] = []
  const split = (arr: any[], x: number, y: number, w: number, h: number) => {
    if (!arr.length) return
    if (arr.length === 1) { rects.push({ item: arr[0], x, y, w, h }); return }
    const total = arr.reduce((n, it) => n + it.weight, 0)
    let acc = 0
    let cut = 1
    for (let i = 0; i < arr.length - 1; i++) {
      acc += arr[i].weight
      if (acc >= total / 2) { cut = i + 1; break }
      cut = i + 2
    }
    cut = Math.max(1, Math.min(arr.length - 1, cut))
    const ratio = Math.max(0.28, Math.min(0.72, acc / total))
    if (w >= h) {
      split(arr.slice(0, cut), x, y, w * ratio, h)
      split(arr.slice(cut), x + w * ratio, y, w * (1 - ratio), h)
    } else {
      split(arr.slice(0, cut), x, y, w, h * ratio)
      split(arr.slice(cut), x, y + h * ratio, w, h * (1 - ratio))
    }
  }
  split(items, 0, 0, VW, VH)
  return rects.map((rc, i) => {
    const pad = 10
    const w = Math.max(40, rc.w - pad * 2)
    const h = Math.max(40, rc.h - pad * 2)
    const cx = rc.x + rc.w / 2
    const cy = rc.y + rc.h / 2
    const [fill, stroke] = PALETTE[i % PALETTE.length]
    const name = String(rc.item.region.name)
    const label = name.length > 9 ? name.slice(0, 8) + '…' : name
    return {
      region: rc.item.region, d: blob(cx, cy, w / 2, h / 2, name),
      cx, cy, fill, stroke,
      fs: Math.max(10, Math.min(17, Math.round(Math.min(w, h) / 5))),
      label, scenes: rc.item.scenes, chars: rc.item.chars, facs: rc.item.facs,
    }
  })
})

/* ---------------- 详情：当前区域（含所有下级）的势力 / 角色 / 事件 ---------------- */
/* 选中某个区块看它自己；否则看当前下钻到的区域；世界层则汇总全部 */
const scopeNames = computed(() => {
  const base = selected.value || parent.value
  if (base) return subtree(base)
  return new Set<string>(regions.value.map((r: any) => r.name))
})
const detailScenes = computed(() =>
  scenesOf(scopeNames.value).slice().sort((a, b) => Number(a.chapter) - Number(b.chapter)))

type Agg = { name: string; chapters: number[]; events: { chapter: number; event: string; region: string }[] }
function aggregate(key: 'characters' | 'factions' | 'items'): Agg[] {
  const bag = new Map<string, Agg>()
  for (const s of detailScenes.value) {
    for (const n of s[key] || []) {
      const name = String(n || '').trim()
      if (!name) continue
      if (!bag.has(name)) bag.set(name, { name, chapters: [], events: [] })
      const item = bag.get(name) as Agg
      const ch = Number(s.chapter) || 0
      if (ch && !item.chapters.includes(ch)) item.chapters.push(ch)
      item.events.push({ chapter: ch, event: String(s.event || ''), region: String(s.region || '') })
    }
  }
  return Array.from(bag.values())
    .map(a => ({ ...a, chapters: a.chapters.sort((x, y) => x - y) }))
    .sort((a, b) => (a.chapters[0] || 0) - (b.chapters[0] || 0))
}
const charRows = computed(() => aggregate('characters'))
const facRows = computed(() => aggregate('factions'))
const itemRows = computed(() => aggregate('items'))
const regionCount = computed(() => scopeNames.value.size)
const sceneRows = computed(() => detailScenes.value.slice(0, 60))

const detailTitle = computed(() => {
  if (selected.value) return regionMap.value.get(selected.value) || { name: selected.value }
  return curRegion.value || { name: '世界', kind: '总览' }
})
const canEnter = computed(() => !!selected.value && childrenOf(selected.value).length > 0)

function chRange(a: Agg) {
  if (!a.chapters.length) return ''
  const first = a.chapters[0]
  const last = a.chapters[a.chapters.length - 1]
  return first === last ? `第${first}章` : `第${first}–${last}章`
}
function go(kind: 'characters' | 'factions' | 'items') {
  router.push('/' + kind)
}
</script>

<template>
  <div class="wm" :class="{ 'is-mobile': mobile }">
    <div v-if="!regions.length" class="wm-empty">
      <span class="wm-empty-ico"><Icon name="map" :size="26" /></span>
      <b>还没有地图设定</b>
      <p>{{ hint || '在「设定图谱」里重新生成一次，地图会随人物、势力、章节一起产出；导入含图谱数据的数据包后也能直接查看。' }}</p>
    </div>

    <template v-else>
      <div class="wm-main">
        <div class="wm-bar">
          <div class="wm-crumbs">
            <button @click="goRoot">世界</button>
            <template v-for="(p, i) in path" :key="p + i">
              <Icon name="right" :size="11" />
              <button :class="{ on: i === path.length - 1 }" @click="goTo(i)">{{ p }}</button>
            </template>
          </div>
          <div v-if="maxCh" class="wm-filter">
            <span>剧情进度</span>
            <input v-model.number="limit" type="range" min="1" :max="maxCh" />
            <b>第 {{ limit }} 章</b>
            <button v-if="limit < maxCh" class="wm-all" @click="limit = maxCh">全部</button>
          </div>
        </div>

        <div class="wm-canvas">
          <svg :viewBox="`0 0 ${VW} ${VH}`" preserveAspectRatio="xMidYMid meet" role="img"
               aria-label="设定地图">
            <defs>
              <pattern id="wm-grid" width="40" height="40" patternUnits="userSpaceOnUse">
                <path d="M40 0H0V40" fill="none" stroke="#eef1ec" stroke-width="1" />
              </pattern>
            </defs>
            <rect :width="VW" :height="VH" fill="#fafbf8" />
            <rect :width="VW" :height="VH" fill="url(#wm-grid)" />
            <g v-for="c in cells" :key="c.region.name" class="wm-region"
               :class="{ on: selected === c.region.name }"
               @click="select(c.region)" @dblclick="enter(c.region)">
              <path :d="c.d" :fill="c.fill" :stroke="c.stroke"
                    :stroke-width="selected === c.region.name ? 2.6 : 1.4" />
              <text :x="c.cx" :y="c.cy - 2" :font-size="c.fs" text-anchor="middle"
                    class="wm-name">{{ c.label }}</text>
              <text :x="c.cx" :y="c.cy + c.fs + 8" font-size="10.5" text-anchor="middle"
                    class="wm-sub">{{ c.scenes }} 幕 · {{ c.chars }} 人 · {{ c.facs }} 势力</text>
            </g>
          </svg>
          <div class="wm-legend">
            <span><i class="wm-dot"></i>单击查看区块</span>
            <span><i class="wm-dot hollow"></i>双击或点「下钻」进入下级</span>
          </div>
        </div>
      </div>

      <aside class="wm-side">
        <div class="wm-detail-head">
          <div class="wm-dh-main">
            <span class="wm-kind">{{ detailTitle.kind || '区域' }}</span>
            <b>{{ detailTitle.name }}</b>
            <p v-if="detailTitle.desc">{{ detailTitle.desc }}</p>
          </div>
          <div class="wm-dh-acts">
            <button v-if="canEnter" class="wm-btn" @click="enter(regionMap.get(selected))">
              <Icon name="arrowDown" :size="13" /> 下钻
            </button>
            <button v-if="selected" class="wm-btn ghost" @click="selected = ''">取消选中</button>
          </div>
        </div>

        <div class="wm-kpis">
          <div class="wm-kpi"><b>{{ regionCount }}</b><span>地点</span></div>
          <div class="wm-kpi"><b>{{ detailScenes.length }}</b><span>场景</span></div>
          <div class="wm-kpi"><b>{{ charRows.length }}</b><span>角色</span></div>
          <div class="wm-kpi"><b>{{ facRows.length }}</b><span>势力</span></div>
        </div>

        <div class="wm-sec">
          <div class="wm-sec-head"><Icon name="flag" :size="13" /><b>势力分布</b>
            <span>{{ facRows.length }}</span></div>
          <div v-if="facRows.length" class="wm-chips">
            <button v-for="f in facRows" :key="f.name" class="wm-chip fac" @click="go('factions')">
              <span class="wm-chip-name">{{ f.name }}</span>
              <em>{{ chRange(f) }}</em>
            </button>
          </div>
          <p v-else class="wm-nil">该区域暂无势力记录</p>
        </div>

        <div class="wm-sec">
          <div class="wm-sec-head"><Icon name="user" :size="13" /><b>角色分布</b>
            <span>{{ charRows.length }}</span></div>
          <div v-if="charRows.length" class="wm-chips">
            <button v-for="c in charRows" :key="c.name" class="wm-chip" @click="go('characters')">
              <span class="wm-chip-name">{{ c.name }}</span>
              <em>{{ chRange(c) }}</em>
            </button>
          </div>
          <p v-else class="wm-nil">该区域暂无角色记录</p>
        </div>

        <div v-if="itemRows.length" class="wm-sec">
          <div class="wm-sec-head"><Icon name="shield" :size="13" /><b>关键道具</b>
            <span>{{ itemRows.length }}</span></div>
          <div class="wm-chips">
            <button v-for="it in itemRows" :key="it.name" class="wm-chip item" @click="go('items')">
              <span class="wm-chip-name">{{ it.name }}</span>
              <em>{{ chRange(it) }}</em>
            </button>
          </div>
        </div>

        <div class="wm-sec grow">
          <div class="wm-sec-head"><Icon name="list" :size="13" /><b>事件时间线</b>
            <span>{{ detailScenes.length }}</span></div>
          <div v-if="sceneRows.length" class="wm-events">
            <div v-for="(e, i) in sceneRows" :key="e.chapter + '-' + i" class="wm-event">
              <span class="wm-ch">第 {{ e.chapter }} 章</span>
              <div class="wm-ev-body">
                <b>{{ e.event || '（未记录事件）' }}</b>
                <small>
                  <span v-if="e.region" class="wm-ev-loc"><Icon name="map" :size="10" />{{ e.region }}</span>
                  <span v-for="n in (e.characters || []).slice(0, 5)" :key="n" class="wm-ev-tag">{{ n }}</span>
                  <span v-for="n in (e.factions || []).slice(0, 3)" :key="'f' + n"
                        class="wm-ev-tag fac">{{ n }}</span>
                </small>
              </div>
            </div>
            <p v-if="detailScenes.length > sceneRows.length" class="wm-more">
              只展示前 {{ sceneRows.length }} 条，共 {{ detailScenes.length }} 条
            </p>
          </div>
          <p v-else class="wm-nil">第 {{ limit }} 章之前，该区域还没有记录事件</p>
        </div>
      </aside>
    </template>
  </div>
</template>

<style scoped>
.wm { display: grid; grid-template-columns: minmax(0, 1fr) 344px; grid-template-rows: minmax(0, 1fr); gap: 14px; height: 100%; min-height: 0; }
.wm-main { min-width: 0; min-height: 0; display: flex; flex-direction: column; gap: 10px; }
.wm-bar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.wm-crumbs { display: flex; align-items: center; gap: 4px; color: var(--text-3); font-size: 12px; flex: 1; min-width: 0; }
.wm-crumbs button {
  border: 0; background: none; padding: 3px 6px; border-radius: 6px; cursor: pointer;
  color: var(--text-2); font-size: 12px; white-space: nowrap;
}
.wm-crumbs button:hover { background: var(--bg); color: var(--text); }
.wm-crumbs button.on { color: var(--primary); font-weight: 700; background: var(--primary-bg); }
.wm-filter { display: flex; align-items: center; gap: 8px; flex: none; font-size: 11.5px; color: var(--text-3); }
.wm-filter input { width: 130px; accent-color: var(--primary); }
.wm-filter b { color: var(--text-2); font-weight: 650; font-variant-numeric: tabular-nums; }
.wm-all { border: 0; background: none; color: var(--primary); font-size: 11.5px; cursor: pointer; }

.wm-canvas {
  position: relative; border: 1px solid var(--border); border-radius: 12px;
  background: #fafbf8; overflow: hidden; flex: 1; min-height: 0;
  display: flex; align-items: center; justify-content: center;
}
/* 高度跟随容器：SVG 按 viewBox 等比缩放并居中，窗口变高变矮都不会溢出或留大片空白 */
.wm-canvas svg { display: block; width: 100%; height: 100%; min-height: 0; }
.wm-region { cursor: pointer; transition: opacity .15s; }
.wm-region:hover { opacity: .86; }
.wm-region.on { filter: drop-shadow(0 2px 6px rgba(30, 60, 40, .14)); }
.wm-name { fill: var(--text); font-weight: 700; pointer-events: none; }
.wm-sub { fill: var(--text-3); pointer-events: none; }
.wm-legend { position: absolute; left: 10px; bottom: 8px; display: flex; gap: 12px;
  font-size: 10.5px; color: var(--text-3); background: rgba(255, 255, 255, .82);
  padding: 3px 8px; border-radius: 7px; pointer-events: none; }
.wm-legend span { display: inline-flex; align-items: center; gap: 4px; }
.wm-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--primary); display: inline-block; }
.wm-dot.hollow { background: none; border: 1.5px solid var(--primary); }

.wm-side {
  border: 1px solid var(--border); border-radius: 12px; background: var(--card);
  padding: 13px; display: flex; flex-direction: column; gap: 11px;
  max-height: none; overflow-y: auto; min-height: 0;
}
.wm-detail-head { display: flex; align-items: flex-start; gap: 8px; }
.wm-dh-main { flex: 1; min-width: 0; }
.wm-kind { display: inline-block; font-size: 10px; color: var(--primary); background: var(--primary-bg);
  border-radius: 5px; padding: 1px 6px; margin-bottom: 5px; }
.wm-dh-main b { display: block; font-size: 15px; font-weight: 700; }
.wm-dh-main p { margin-top: 4px; font-size: 11.5px; line-height: 1.55; color: var(--text-3); }
.wm-dh-acts { display: flex; flex-direction: column; gap: 5px; flex: none; }
.wm-btn { display: inline-flex; align-items: center; gap: 3px; border: 1px solid var(--primary);
  background: var(--primary); color: #fff; border-radius: 7px; padding: 4px 8px; font-size: 11px; cursor: pointer; }
.wm-btn.ghost { background: none; border-color: var(--border); color: var(--text-3); }

.wm-kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }
.wm-kpi { background: var(--bg); border-radius: 8px; padding: 7px 4px; text-align: center; }
.wm-kpi b { display: block; font-size: 15px; font-weight: 750; font-variant-numeric: tabular-nums; }
.wm-kpi span { font-size: 10px; color: var(--text-3); }

.wm-sec { display: flex; flex-direction: column; gap: 6px; }
.wm-sec.grow { flex: 1; min-height: 0; }
.wm-sec-head { display: flex; align-items: center; gap: 5px; color: var(--text-2); font-size: 12px; }
.wm-sec-head b { font-weight: 650; }
.wm-sec-head span { margin-left: auto; font-size: 10.5px; color: var(--text-3); }
.wm-chips { display: flex; flex-wrap: wrap; gap: 5px; }
.wm-chip { display: inline-flex; align-items: center; gap: 5px; border: 1px solid var(--border);
  background: var(--panel, #fff); border-radius: 7px; padding: 3px 7px; font-size: 11.5px;
  color: var(--text); cursor: pointer; max-width: 100%; }
.wm-chip:hover { border-color: var(--primary); color: var(--primary); }
.wm-chip.fac { background: #fdf7ea; border-color: #f0e0bd; }
.wm-chip.item { background: #eaf7f3; border-color: #c8e8de; }
.wm-chip-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 120px; }
.wm-chip em { font-style: normal; font-size: 10px; color: var(--text-3); flex: none; }
.wm-nil { font-size: 11.5px; color: var(--text-3); padding: 4px 2px; }

.wm-events { display: flex; flex-direction: column; gap: 6px; }
.wm-event { display: flex; gap: 7px; align-items: flex-start; }
.wm-ch { flex: none; min-width: 52px; font-size: 10px; color: var(--primary);
  background: var(--primary-bg); border-radius: 5px; padding: 2px 5px; text-align: center;
  font-variant-numeric: tabular-nums; }
.wm-ev-body { flex: 1; min-width: 0; }
.wm-ev-body b { display: block; font-size: 11.5px; font-weight: 600; line-height: 1.5; }
.wm-ev-body small { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 3px; }
.wm-ev-loc { display: inline-flex; align-items: center; gap: 2px; font-size: 10px; color: var(--text-3); }
.wm-ev-tag { font-size: 9.5px; color: var(--text-2); background: var(--bg); border-radius: 4px; padding: 0 4px; }
.wm-ev-tag.fac { background: #fdf7ea; color: #9a6a1c; }
.wm-more { font-size: 10px; color: var(--text-3); text-align: center; padding-top: 3px; }

.wm-empty { grid-column: 1 / -1; display: flex; flex-direction: column; align-items: center;
  gap: 7px; padding: 64px 20px; text-align: center; }
.wm-empty-ico { width: 52px; height: 52px; border-radius: 15px; background: var(--bg);
  display: grid; place-items: center; color: var(--text-3); }
.wm-empty b { font-size: 14px; }
.wm-empty p { max-width: 460px; font-size: 12px; line-height: 1.65; color: var(--text-3); }

/* 安卓端：地图在上、详情在下，控件放大到可触控 */
.wm.is-mobile { display: flex; flex-direction: column; gap: 12px; height: auto; }
.wm.is-mobile .wm-bar { gap: 8px; }
.wm.is-mobile .wm-crumbs button { font-size: 13px; padding: 5px 8px; }
.wm.is-mobile .wm-filter { width: 100%; justify-content: space-between; font-size: 12px; }
.wm.is-mobile .wm-filter input { flex: 1; width: auto; height: 28px; }
.wm.is-mobile .wm-canvas { border-radius: 16px; flex: none; display: block; }
.wm.is-mobile .wm-canvas svg { width: 100%; height: auto; max-height: 44vh; }
.wm.is-mobile .wm-legend { display: none; }
.wm.is-mobile .wm-side { max-height: none; border-radius: 16px; }
.wm.is-mobile .wm-btn { min-height: 34px; padding: 6px 12px; font-size: 12px; }
.wm.is-mobile .wm-chip { min-height: 30px; font-size: 12px; }
.wm.is-mobile .wm-empty { padding: 52px 18px; }
.wm.is-mobile .wm-empty b { font-size: 15px; }
.wm.is-mobile .wm-empty p { font-size: 12.5px; }

/* 窄屏（页面自身滚动、卡片高度不再受视口约束）：
   地图按内容自然高度显示，右侧详情限高并内部滚动，避免把整块画布撑成超高 */
@media (max-width: 1100px) {
  .wm { height: auto; grid-template-rows: auto; }
  .wm-canvas { flex: none; display: block; }
  .wm-canvas svg { width: 100%; height: auto; }
  .wm-side { max-height: 60vh; }
}
</style>
