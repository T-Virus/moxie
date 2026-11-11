<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import Icon from '../components/Icon.vue'
import BackLink from '../components/BackLink.vue'
import JobBar from '../components/JobBar.vue'
import LogBox from '../components/LogBox.vue'
import EmptyBox from '../components/EmptyBox.vue'
import SelectBox from '../components/SelectBox.vue'
import { api, pollReview } from '../api'
import type { BatchReport, SigningReport } from '../api'
import { state, store } from '../store'
import { toast, openFilePreview } from '../ui'
import { modelChoices } from '../modelChoices'
import { usePersistedRef } from '../composables/usePersistedRef'

const route = useRoute()
const opts = ref<any>(null)
const lines = ref<string[]>([])
const logExpand = ref(false)
const job = ref({ running: false, code: null as number | null, stage: '' })
/* 本页这条审查叫什么：由后端按「有没有真的调模型」定 —— AI 审查 / 程序体检 */
const jobTitle = ref('审查正文')
const keyHint = ref(false)

const chNo = usePersistedRef('review.chNo', '')
const chText = ref('')
const checks = usePersistedRef<string[]>('review.checks', [])
const topN = usePersistedRef('review.topN', '5')
const scope = usePersistedRef('review.scope', 'ai')
const rModel = usePersistedRef('review.rModel', state.model)
/* 「正文审查」工序绑定的档案：页面上回显当前实际会用的模型，避免「留空默认」看不出用谁 */
const boundReview = computed(() => store.profileFor('review'))
const baseline = ref<any>(null)
const result = ref<any>(null)
const reviewFiles = ref<Record<string, string>>({})
/* 本页这一条审查的任务 id：多任务并发时按 id 轮询 / 停止，不会串到别章 */
const taskId = ref('')
/* 换了章节号就重新定位任务：否则会一直显示上一章那条审查的结果 */
watch(chNo, () => {
  taskId.value = ''
  lines.value = []
  result.value = null
  reviewFiles.value = {}
  job.value.running = false
  job.value.code = null
  wasRunning = false
})

async function loadOpts() {
  try { opts.value = await api.reviewOptions() } catch { opts.value = null }
}
async function loadBaseline() {
  const no = chNo.value.trim()
  if (!no) { baseline.value = null; return }
  try {
    baseline.value = await api.reviewBaseline(store.curBook(), no)
  } catch (e: any) {
    baseline.value = { error: e.message }
  }
}
function onTextInput() {
  const n = chText.value.length
  chCount.value = n + ' 字' + (n > 60000 ? '（超过 60000 字上限，请按章分段）' : '')
}
const chCount = ref('0 字')

async function loadMsOptions() {
  try {
    const book = store.curBook()
    msOptions.value = book ? (await api.getOutputs({ book, kind: 'manuscript' })).files || [] : []
  } catch { msOptions.value = [] }
}
const msOptions = ref<any[]>([])
/* 选中的成稿（只用于回显：否则每次选完都跳回「手动粘贴正文」，看不出导入了哪一章） */
const msPick = ref('')
async function importMs(p: string) {
  msPick.value = p
  if (!p) return
  try { const r = await api.getOutput(p); chText.value = r.content; onTextInput() }
  catch (e: any) { toast(e.message, 'err') }
}

/* 章节号候选：直接列本书章节，避免手敲错号；也允许输入任意章号 */
const chapterOptions = ref<{ label: string; value: string }[]>([])
async function loadChapterOptions() {
  const book = store.curBook()
  if (!book) { chapterOptions.value = []; return }
  try {
    const ch = await api.getChapters(book)
    chapterOptions.value = (ch.chapters || []).map((c: any, i: number) => {
      const no = String(c.no ?? c.chapter_id
        ?? (String(c.title || '').match(/\d+/)?.[0] ?? i + 1))
      const t = String(c.title || c.name || '').trim()
      return { label: t ? `第 ${no} 章 · ${t}` : `第 ${no} 章`, value: no }
    })
  } catch { chapterOptions.value = [] }
}

/* 模型候选：与设置页档案同一套，留空 = 跟随「正文审查」工序绑定 */
const modelOptions = computed(() => modelChoices('review'))
const TOPN_OPTIONS = [
  { label: '3 条 · 只看最要紧的', value: '3' },
  { label: '5 条 · 默认', value: '5' },
  { label: '8 条', value: '8' },
  { label: '10 条 · 尽量全', value: '10' },
]

function run() {
  const rc = store.callCreds('review')   // 审查工序绑定档案（如 ChatGPT）优先，回落全局兜底
  // 无 Key 也能跑：AI 项会跳过并标注，规则初筛与行文统计照常出结果
  if (!rc.api_key) { keyHint.value = true; toast('未配置 API Key：仅运行错别字规则初筛与行文统计', 'ok') }
  const cs = checks.value.length ? checks.value : (opts.value?.checks || [])
  const body: any = {
    book: store.curBook(),
    chapter_no: chNo.value.trim(),
    chapter_text: chText.value,
    checks: cs,
    top_n: parseInt(topN.value, 10) || 5,
    advice_scope: scope.value,
    api_key: rc.api_key,
  }
  if (rModel.value.trim()) body.model = rModel.value.trim()
  else if (rc.model) body.model = rc.model
  if (rc.base_url) body.base_url = rc.base_url
  if (!body.chapter_no) return toast('请填写章节号', 'err')
  if (!body.chapter_text.trim()) return toast('请粘贴或导入章节正文', 'err')
  if (!cs.length) return toast('请至少勾选一个检查项', 'err')
  lines.value = []; result.value = null; reviewFiles.value = {}
  api.reviewRun(body)
    .then((r: any) => {
      taskId.value = r?.id || ''
      // 后端按实际跑的东西起名：有 Key 且勾了模型检查项 → AI 审查，否则程序体检
      jobTitle.value = r?.title || '审查正文'
      toast('审查已开始', 'ok')
    })
    .catch((e: any) => toast(e.message, 'err'))
}

let timer: any = null
let wasRunning = false
async function poll() {
  try {
    // 每次全量拉取日志：开始新任务时后端会重置日志数组，
    // 用「增量游标 + 绝对下标」会错位，导致重跑时前面的日志整段丢失。
    // 按「本页任务 id」或「当前书 + 本页章节号」精确取：多任务并发时不会串到别章
    const j = await pollReview(0, taskId.value, store.curBook(), chNo.value.trim())
    taskId.value = j.id || taskId.value
    /* 别的作品发起的审查不该显示在本页（会把结论串到当前书上）。
       书单还没加载出当前书时（cur 为空）不做判断，避免把正在跑的任务误清掉 */
    const cur = store.curBook()
    if (j.book && cur && j.book !== cur) {
      lines.value = []; result.value = null; reviewFiles.value = {}
      job.value.running = false; job.value.code = null
      wasRunning = false
      return
    }
    lines.value = j.lines || []
    job.value.running = j.running
    job.value.code = j.error ? -1 : (!j.running && (j.result || j.stopped) ? 0 : null)
    job.value.stage = 'review'
    /* 接管（或刷新后回显）别处发起的审查时，名字以任务自己的为准：AI 审查 / 程序体检 */
    const nm = (j as any).name
    if (nm) jobTitle.value = nm
    if (j.files) reviewFiles.value = j.files
    if (wasRunning && !j.running) {
      if (j.error) { lines.value.push('[x] ' + j.error); toast(j.error, 'err') }
      else if (j.stopped) toast('审查已停止')
      else { toast('审查完成', 'ok'); result.value = j.result }
    } else if (!j.running && j.result && !result.value) {
      // 任务在两次轮询之间就结束了：直接补上结果，避免一直「等待审查」
      result.value = j.result
    }
    wasRunning = j.running
  } catch { /* */ }
}

function stopReview() {
  api.stopReview(taskId.value || undefined)
    .then(() => toast('已请求停止')).catch((e: any) => toast(e.message, 'err'))
}

/* ---------------- 问题定位：点一条问题 → 原文里高亮并滚到那一处 ----------------
   定位数据全部由后端随结果给出（issues[].span 是问题片段在正文里的起止下标，
   基准是 result.text），所以不依赖 AI 是否可用：纯规则体检（错别字初筛、高频词）
   同样能点开定位。老结果没有 text/span 时退回输入框正文 + 行号提示。 */
const curIssue = ref(-1)
const locOpen = ref(false)
const locBox = ref<HTMLElement | null>(null)

const srcText = computed(() => {
  const t = result.value?.text
  if (typeof t === 'string' && t) return t
  return chText.value.trim()
})

type LocSeg = { t: string; idxs: number[]; kind: 'plain' | 'ctx' | 'core' }
/* 把正文切成「普通文本 / 上下文 / 问题核心」三段式：
   问题核心用深色标出来，前后各带 CTX 个字浅色上下文——单字问题（标点、错字）
   也能一眼看到落点。重叠或相邻的核心区间合并，一段可属于多条问题。 */
const CTX = 10

const locSegs = computed<LocSeg[]>(() => {
  const s = srcText.value
  const marks: { s: number; e: number; i: number }[] = []
  ;(result.value?.issues || []).forEach((it: any, i: number) => {
    const sp = it?.span
    if (Array.isArray(sp) && sp.length === 2 && sp[0] >= 0 && sp[1] > sp[0]) {
      marks.push({ s: sp[0], e: Math.min(sp[1], s.length), i })
    }
  })
  if (!marks.length) return s ? [{ t: s, idxs: [], kind: 'plain' }] : []
  marks.sort((a, b) => a.s - b.s || a.e - b.e)
  const cores: { s: number; e: number; idxs: number[] }[] = []
  for (const m of marks) {
    const last = cores[cores.length - 1]
    // 只合并真正重叠的区间：首尾相接的两条问题保持各自高亮，颜色才分得清
    if (last && m.s < last.e) {
      last.e = Math.max(last.e, m.e)
      if (!last.idxs.includes(m.i)) last.idxs.push(m.i)
    } else cores.push({ s: m.s, e: m.e, idxs: [m.i] })
  }
  const out: LocSeg[] = []
  let pos = 0
  cores.forEach((c, k) => {
    // 上下文不越过相邻核心，避免两条问题的浅色块粘在一起
    const lo = Math.max(pos, k > 0 ? cores[k - 1].e : 0, c.s - CTX)
    const hi = Math.min(k + 1 < cores.length ? cores[k + 1].s : s.length, c.e + CTX)
    if (lo > pos) out.push({ t: s.slice(pos, lo), idxs: [], kind: 'plain' })
    if (c.s > lo) out.push({ t: s.slice(lo, c.s), idxs: c.idxs, kind: 'ctx' })
    out.push({ t: s.slice(c.s, c.e), idxs: c.idxs, kind: 'core' })
    if (hi > c.e) out.push({ t: s.slice(c.e, hi), idxs: c.idxs, kind: 'ctx' })
    pos = hi > c.e ? hi : c.e
  })
  if (pos < s.length) out.push({ t: s.slice(pos), idxs: [], kind: 'plain' })
  return out
})

const nLocated = computed(() => (result.value?.issues || []).filter((it: any) => Array.isArray(it?.span)).length)
const sevOf = (i: number) => {
  const v = (result.value?.issues || [])[i]?.severity
  return v === '高' ? 'hi' : v === '中' ? 'mid' : 'lo'
}

function focusIssue(i: number) {
  const it = (result.value?.issues || [])[i]
  if (!it) return
  curIssue.value = i
  if (!Array.isArray(it.span)) {
    toast(it.line ? `这条没有原文片段，约在第 ${it.line} 行` : '这条没有可定位的原文片段', 'ok')
    return
  }
  locOpen.value = true
  nextTick(() => {
    const box = locBox.value
    // 优先滚到「核心片段」，其次上下文块
    const el = (box?.querySelector(`.mk[data-ix~="${i}"]`)
      || box?.querySelector(`[data-ix~="${i}"]`)) as HTMLElement | null
    if (box && el) {
      // 只滚定位面板，不把整页带走
      const top = el.offsetTop - box.clientHeight / 2 + el.offsetHeight / 2
      box.scrollTo({ top: Math.max(0, top), behavior: 'smooth' })
    } else if (el) {
      el.scrollIntoView({ block: 'center', behavior: 'smooth' })
    }
  })
}

/* 用户正在选字复制时不要跳走 */
function issueClick(i: number) {
  if (String(window.getSelection?.() || '').trim()) return
  focusIssue(i)
}

watch(result, () => {
  curIssue.value = -1
  locOpen.value = false
})

async function copyLog() {
  if (!lines.value.length) return
  try {
    await navigator.clipboard.writeText(lines.value.join('\n'))
    toast('日志已复制', 'ok')
  } catch {
    toast('复制失败，请手动选择文本', 'err')
  }
}

watch(() => store.curBook(), () => {
  msPick.value = ''
  loadBaseline(); loadMsOptions(); loadChapterOptions(); loadBatchReport(); loadSigningReport()
})
onMounted(async () => {
  await store.loadBooks().catch(() => {})
  const qch = String((route.query.ch as string) || '').trim()
  if (qch) { chNo.value = qch; loadBaseline() }
  loadOpts(); loadMsOptions(); loadChapterOptions(); loadBatchReport(); loadSigningReport()
  poll()
  timer = setInterval(() => { poll(); pollBatch(); pollSigning() }, 900)
})
onUnmounted(() => clearInterval(timer))

const sevCls = (s: string) => s === '高' ? 'hi' : s === '中' ? 'mid' : 'lo'

/* ---------------- 全书体检（P2）：所有成稿章节批量过一遍审查，汇总全书问题 ---------------- */
const batchId = ref('')
const batchRunning = ref(false)
const batchLines = ref<string[]>([])
const batchReport = ref<BatchReport | null>(null)
const batchInc = usePersistedRef('review.batchInc', true)

async function loadBatchReport() {
  const book = store.curBook()
  if (!book) { batchReport.value = null; return }
  try { batchReport.value = (await api.getReviewBatch(book)).report } catch { batchReport.value = null }
}

async function runBatch() {
  const book = store.curBook()
  if (!book) return toast('请先选择作品', 'err')
  const rc = store.callCreds('review')
  if (!rc.api_key) return toast('全书体检需要调用模型：请先在设置里给「正文审查」工序配好档案与 Key', 'err')
  const cs = checks.value.length ? checks.value : (opts.value?.checks || [])
  try {
    const r = await api.reviewBatchRun({
      book, incremental: batchInc.value, checks: cs,
      api_key: rc.api_key, model: rModel.value.trim() || rc.model || undefined,
      base_url: rc.base_url || undefined,
    })
    batchId.value = r.id || ''
    batchRunning.value = true
    batchLines.value = []
    toast('全书体检已启动（逐章进行，可随时离开本页）', 'ok')
  } catch (e: any) { toast(e.message, 'err') }
}

async function pollBatch() {
  if (!batchId.value) return
  try {
    const j = await pollReview(0, batchId.value, store.curBook(), '')
    batchLines.value = j.lines || []
    batchRunning.value = j.running
    if (!j.running && (j.result || j.error || j.stopped)) {
      if (j.error) toast('体检失败：' + j.error, 'err')
      else if (!j.stopped) toast('全书体检完成', 'ok')
      await loadBatchReport()
      batchId.value = ''
    }
  } catch { /* */ }
}

/* ---------------- 签约预审（P0）：跨章扫前 2 万字，模拟签约编辑看开篇 ---------------- */
const signingId = ref('')
const signingRunning = ref(false)
const signingLines = ref<string[]>([])
const signingReport = ref<SigningReport | null>(null)

async function loadSigningReport() {
  const book = store.curBook()
  if (!book) { signingReport.value = null; return }
  try { signingReport.value = (await api.getReviewSigning(book)).report } catch { signingReport.value = null }
}

async function runSigning() {
  const book = store.curBook()
  if (!book) return toast('请先选择作品', 'err')
  const rc = store.callCreds('review')
  // 无 Key 也能跑：程序初筛（开头信号 / 章末钩子 / 爽点节奏）照出，模型复核跳过
  if (!rc.api_key) toast('未配置 API Key：只跑程序初筛，模型复核（金手指实演 / 主动性）会跳过', 'ok')
  try {
    const r = await api.reviewSigningRun({
      book, api_key: rc.api_key, model: rModel.value.trim() || rc.model || undefined,
      base_url: rc.base_url || undefined,
    })
    signingId.value = r.id || ''
    signingRunning.value = true
    signingLines.value = []
    toast('签约预审已启动：扫前 2 万字（≈前 10 章）', 'ok')
  } catch (e: any) { toast(e.message, 'err') }
}

async function pollSigning() {
  if (!signingId.value) return
  try {
    const j = await pollReview(0, signingId.value, store.curBook(), '')
    signingLines.value = j.lines || []
    signingRunning.value = j.running
    if (!j.running && (j.result || j.error || j.stopped)) {
      if (j.error) toast('预审失败：' + j.error, 'err')
      else if (!j.stopped) {
        const v = j.result?.verdict || ''
        toast('签约预审完成' + (v ? '：' + v : ''), v === '可投' ? 'ok' : 'err')
      }
      await loadSigningReport()
      signingId.value = ''
    }
  } catch { /* */ }
}

const signCls = (lv: string) =>
  lv === '高危' ? 'red' : lv === '警告' ? 'orange' : lv === '通过' ? 'green' : 'gray'
</script>

<template>
  <div v-if="!opts" class="card"><EmptyBox title="AI 审查模块不可用" desc="请确认已安装 openai 库（与拆解同源）" /></div>
  <div v-else>
    <div class="page-head"><div><h1>单章审查</h1>
      <p>只诊断、不改写：AI 味 / 主题偏离 / 错别字 / 设定一致性 / 违规风险 / 逻辑连贯 / 伏笔支线 / 行文质检。</p></div>
    </div>
    <div class="toolbar"><BackLink /><span class="spacer"></span></div>

    <div class="grid cols-2" style="align-items:start">
      <div>
        <div class="card">
          <div class="card-head"><div class="card-title">审查设置</div></div>
          <div class="form-row">
            <div class="field"><label>章节号<span class="req">*</span></label>
              <SelectBox :model-value="chNo" :options="chapterOptions" allow-empty allow-custom
                         empty-label="选择章节" placeholder="选择章节，或输入章节号"
                         @update:model-value="v => { chNo = v; loadBaseline() }" /></div>
            <div class="field"><label>导入本书成稿</label>
              <SelectBox :model-value="msPick" :search-from="6"
                         :options="[{ label: '手动粘贴正文', value: '' },
                                    ...msOptions.map(f => ({ label: f.name.split('/').pop() || f.name, value: f.path }))]"
                         @update:model-value="v => importMs(v)" /></div>
          </div>
          <div class="field"><label>章节正文<span class="req">*</span></label>
            <textarea class="textarea" v-model="chText" @input="onTextInput" style="min-height:180px" placeholder="粘贴本章正文…"></textarea>
            <div class="hint">{{ chCount }}</div></div>
          <div class="field"><label>检查项</label>
            <div class="check-group">
              <label class="check" v-for="c in opts.checks" :key="c">
                <input type="checkbox" :value="c" v-model="checks" /> {{ opts.labels[c] || c }}</label>
            </div></div>
          <div class="form-row">
            <div class="field"><label>Top 问题条数</label>
              <SelectBox :model-value="topN" :options="TOPN_OPTIONS" allow-custom
                         @update:model-value="v => topN = v" /></div>
            <div class="field"><label>建议范围</label>
              <SelectBox :model-value="scope" :search-from="99"
                         :options="[{ label: '仅 AI 味', value: 'ai' },
                                    { label: 'AI 味 + 违规风险 + 逻辑连贯', value: 'all' }]"
                         @update:model-value="v => scope = v" /></div>
          </div>
          <div class="field"><label>模型</label>
            <SelectBox :model-value="rModel" :options="modelOptions" allow-empty allow-custom
                       empty-label="默认（跟随工序绑定）" placeholder="选择或输入模型名"
                       @update:model-value="v => rModel = v" /></div>
          <div class="hint" v-if="rModel.trim()">本次使用：<b>{{ rModel.trim() }}</b>（页面临时指定，优先于工序绑定）</div>
          <div class="hint" v-else-if="boundReview">
            当前档案：<b>{{ boundReview.profile.name }}</b>（{{ boundReview.profile.model }}）
            <span v-if="!boundReview.api_key" style="color:var(--orange)"> · 该档案还没填 Key</span>
          </div>
          <div class="hint" v-else>未绑定档案，使用默认 deepseek-v4-flash</div>
          <div v-if="keyHint" class="hint">未配置 API Key：只跑错别字规则初筛与行文统计（结果仍可定位原文），配好 Key 后可看完整审查。</div>
          <div style="display:flex;gap:10px;margin-top:8px">
            <button class="btn lg" style="flex:1" @click="run"><Icon name="play" :size="14" /> 开始审查</button>
          </div>
        </div>

        <!-- 全书体检：所有成稿章节批量过一遍审查，汇总全书问题清单 -->
        <div class="card" style="margin-top:16px">
          <div class="card-head"><div class="card-title">全书体检</div>
            <span class="sub" v-if="batchReport">{{ batchReport.created_at }}</span></div>
          <div class="hint" style="margin:0 0 10px">
            对本书全部成稿章节逐章跑一遍审查，汇总一张全书问题清单；报告存 review/ 目录。
          </div>
          <label class="check" style="margin-bottom:10px">
            <input type="checkbox" v-model="batchInc" /> 增量模式：报告比正文新的章节跳过（省钱省时间）
          </label>
          <div style="display:flex;gap:10px">
            <button class="btn" style="flex:1" :disabled="batchRunning" @click="runBatch">
              <Icon name="shield" :size="14" /> {{ batchRunning ? '体检中…' : '开始全书体检' }}</button>
            <button class="btn ghost" :disabled="batchRunning" @click="loadBatchReport">刷新报告</button>
          </div>
          <div v-if="batchRunning && batchLines.length" class="batch-log">
            <div v-for="(l, i) in batchLines.slice(-6)" :key="i">{{ l }}</div>
          </div>
          <template v-if="batchReport && !batchRunning">
            <div style="display:flex;gap:8px;flex-wrap:wrap;margin:12px 0 8px">
              <span class="tag blue">{{ batchReport.n_done }} 章已检</span>
              <span class="tag gray" v-if="batchReport.n_skipped">跳过 {{ batchReport.n_skipped }} 章</span>
              <span class="tag" :class="batchReport.total_high ? 'red' : (batchReport.total_issues ? 'orange' : 'green')">
                问题 {{ batchReport.total_issues }} · 高 {{ batchReport.total_high }}</span>
            </div>
            <table class="table">
              <thead><tr><th>章</th><th>问题</th><th>高</th><th>Top 问题</th></tr></thead>
              <tbody>
                <tr v-for="c in batchReport.chapters" :key="c.no">
                  <td>第 {{ c.no }} 章</td>
                  <template v-if="c.error"><td colspan="3" style="color:var(--red)">{{ c.error }}</td></template>
                  <template v-else>
                    <td>{{ c.n_issues }}</td>
                    <td><span v-if="c.n_high" class="sev hi">{{ c.n_high }}</span><span v-else>0</span></td>
                    <td style="font-size:12px;color:var(--text-2)">
                      {{ (c.top_issues || []).map(i => i.reason).join('；') || '—' }}
                    </td>
                  </template>
                </tr>
              </tbody>
            </table>
          </template>
          <div v-else-if="!batchRunning" class="hint" style="text-align:center;padding:8px 0">暂无体检报告</div>
        </div>

        <!-- 签约预审：编辑只看前 2 万字（≈前 10 章），投稿前先过一遍 -->
        <div class="card" style="margin-top:16px">
          <div class="card-head"><div class="card-title">签约预审</div>
            <span class="sub" v-if="signingReport">{{ signingReport.created }}</span></div>
          <div class="hint" style="margin:0 0 10px">
            平台签约审核只看前 2 万字。本检查跨章扫成稿：开头吸引力 / 金手指实演 / 主角主动性 /
            爽点节奏 / 章末钩子，报告存 review/ 目录。
          </div>
          <div style="display:flex;gap:10px">
            <button class="btn" style="flex:1" :disabled="signingRunning" @click="runSigning">
              <Icon name="flag" :size="14" /> {{ signingRunning ? '预审中…' : '开始签约预审' }}</button>
            <button class="btn ghost" :disabled="signingRunning" @click="loadSigningReport">刷新报告</button>
          </div>
          <div v-if="signingRunning && signingLines.length" class="batch-log">
            <div v-for="(l, i) in signingLines.slice(-6)" :key="i">{{ l }}</div>
          </div>
          <template v-if="signingReport && !signingRunning">
            <div style="display:flex;gap:8px;flex-wrap:wrap;margin:12px 0 8px">
              <span class="tag" :class="signingReport.verdict === '可投' ? 'green' : (signingReport.verdict === '需修改后再投' ? 'orange' : 'red')">
                {{ signingReport.verdict }}</span>
              <span class="tag gray">前 {{ signingReport.window_chapters }} 章 / {{ signingReport.chars }} 字</span>
              <span class="tag blue" v-if="signingReport.verdict_why">{{ signingReport.verdict_why }}</span>
            </div>
            <table class="table">
              <thead><tr><th>检查项</th><th>结论</th><th>依据</th></tr></thead>
              <tbody>
                <tr v-for="c in signingReport.checks" :key="c.key">
                  <td>{{ c.label }}</td>
                  <td><span class="tag" :class="signCls(c.level)">{{ c.level }}</span></td>
                  <td style="font-size:12px;color:var(--text-2)">{{ c.detail }}</td>
                </tr>
              </tbody>
            </table>
            <details v-if="(signingReport.issues || []).length" style="margin-top:10px">
              <summary class="hint" style="cursor:pointer">问题清单（含骨架体检，共 {{ signingReport.issues.length }} 条）</summary>
              <div v-for="(x, i) in signingReport.issues" :key="i" class="hint" style="margin-top:4px">
                <span class="sev" :class="sevCls(x.sev)">{{ x.sev }}</span>
                <b v-if="x.chapter"> 第{{ x.chapter }}章 </b>{{ x.msg }}
              </div>
            </details>
          </template>
          <div v-else-if="!signingRunning" class="hint" style="text-align:center;padding:8px 0">暂无预审报告</div>
        </div>

        <div v-if="baseline" class="card" style="margin-top:16px">
          <div class="card-head"><div class="card-title">比对基准</div>
            <span class="sub" v-if="baseline.chapter_no">第 {{ baseline.chapter_no }} 章 · {{ baseline.title || baseline.chapter_id }}</span></div>
          <template v-if="baseline.error">
            <div class="hint" style="color:var(--red)">{{ baseline.error }}</div>
          </template>
          <template v-else>
            <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px">
              <span class="tag" :class="baseline.has_synopsis ? 'green' : 'gray'">全书梗概 {{ baseline.has_synopsis ? '✓' : '缺' }}</span>
              <span class="tag" :class="baseline.has_chapter_summary ? 'green' : 'gray'">本章摘要 {{ baseline.has_chapter_summary ? '✓' : '缺' }}</span>
              <span class="tag" :class="baseline.has_setting ? 'green' : 'gray'">设定库 {{ baseline.has_setting ? `✓ ${baseline.n_cards} 人卡 / ${baseline.n_factions} 势力` : '缺' }}</span>
              <span class="tag blue">全书 {{ baseline.n_chapters }} 章</span>
              <span class="tag" :class="baseline.n_prev ? 'blue' : 'gray'">前文记忆 {{ baseline.n_prev || 0 }} 章</span>
              <span class="tag" :class="baseline.has_timeline ? 'green' : 'gray'">时间线 {{ baseline.has_timeline ? '✓' : '缺' }}</span>
              <span class="tag" :class="baseline.has_foreshadow ? 'green' : 'gray'">伏笔 {{ baseline.has_foreshadow ? '✓' : '缺' }}</span>
            </div>
            <div v-for="n in (baseline.notes || [])" :key="n" class="hint" style="color:var(--orange)">⚠ {{ n }}</div>
            <div v-if="baseline.chapter_summary" class="hint"><b>本章摘要：</b>{{ baseline.chapter_summary }}</div>
            <div v-if="(baseline.chapter_points || []).length" class="hint"><b>关键事件：</b>{{ baseline.chapter_points.join('；') }}</div>
            <div v-if="baseline.chapter_conflict" class="hint"><b>核心冲突：</b>{{ baseline.chapter_conflict }}</div>
            <div v-if="baseline.chapter_hook" class="hint"><b>章末钩子：</b>{{ baseline.chapter_hook }}</div>
          </template>
        </div>
      </div>

      <!-- 结果 -->
      <div class="card">
        <div class="card-head"><div class="card-title">审查结果</div></div>
        <div v-if="!result" class="empty">
          <Icon name="shield" :size="44" /><b>等待审查</b><span>填好左侧设置并开始审查</span>
        </div>
        <div v-else>
          <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
            <span class="tag blue">正文 {{ result.meta?.chars || 0 }} 字</span>
            <span class="tag gray">{{ result.meta?.n_paragraphs || 0 }} 段 / {{ result.meta?.n_sentences || 0 }} 句</span>
            <span v-if="result.theme && result.theme.level" class="tag" :class="result.theme.level === '无' ? 'green' : 'red'">主题偏离：{{ result.theme.level }}</span>
            <span v-if="result.risk" class="tag" :class="result.risk.n_high ? 'red' : result.risk.n_risk ? 'orange' : 'green'">违规风险：{{ result.risk.n_high || 0 }} 高 / {{ result.risk.n_risk || 0 }} 条</span>
            <span v-if="(result.issues || []).length" class="tag orange">共 {{ result.issues.length }} 条问题</span>
            <span v-else class="tag green">未发现问题 🎉</span>
          </div>
          <div v-if="result.theme && result.theme.summary" class="hint" style="margin-bottom:12px"><b>主题判断：</b>{{ result.theme.summary }}</div>

          <!-- 原文定位：点下面任一问题，这里滚到对应位置并高亮 -->
          <div v-if="srcText && (result.issues || []).length" class="loc-wrap">
            <div class="loc-head">
              <b style="font-size:13px">原文定位</b>
              <span class="hint">{{ nLocated }} / {{ result.issues.length }} 条可定位 · 点问题即跳到对应位置</span>
              <button class="btn" style="margin-left:auto;padding:4px 10px;font-size:12px" @click="locOpen = !locOpen">
                {{ locOpen ? '收起原文' : '展开原文' }}
              </button>
            </div>
            <div v-show="locOpen" ref="locBox" class="loc-body"><template v-for="(seg, k) in locSegs" :key="k"><span
                v-if="seg.kind === 'ctx'" class="mk-ctx" :class="sevOf(seg.idxs[0])" :data-ix="seg.idxs.join(' ')"
                @click="issueClick(seg.idxs[0])">{{ seg.t }}</span><span
                v-else-if="seg.kind === 'core'" class="mk"
                :class="[sevOf(seg.idxs[0]), { active: seg.idxs.includes(curIssue) }]"
                :data-ix="seg.idxs.join(' ')" @click="issueClick(seg.idxs[0])">{{ seg.t }}</span><template
                v-else>{{ seg.t }}</template></template></div>
            <div v-if="!locOpen" class="hint" style="padding:0 12px 10px">正文已收起（点「展开原文」或直接点某条问题）</div>
          </div>

          <div v-for="(it, i) in (result.issues || [])" :key="i" class="issue"
               :class="{ 'issue-cur': curIssue === i, 'issue-loc': Array.isArray(it.span) }"
               @click="issueClick(i)">
            <div class="issue-head">
              <span class="tag blue">{{ it.type_label || it.type }}</span>
              <span v-if="it.kind" class="tag gray">{{ it.kind }}</span>
              <span v-if="it.category" class="tag gray">{{ it.category }}</span>
              <span v-if="it.ref" class="tag purple">依据：{{ it.ref }}</span>
              <span v-if="it.severity" class="sev" :class="sevCls(it.severity)">{{ it.severity }}</span>
              <span v-if="it.sid" class="tag gray">{{ it.sid }}</span>
              <span class="spacer"></span>
              <span v-if="it.line" class="hint" style="font-size:12px">第 {{ it.line }} 行</span>
              <span v-if="Array.isArray(it.span)" class="loc-btn">定位原文</span>
              <span v-else class="hint" style="font-size:12px">无原文片段</span>
            </div>
            <div v-if="it.quote" class="issue-quote">「{{ it.quote }}」</div>
            <div v-if="it.suggest" class="reason"><b>建议：</b>{{ it.suggest }}</div>
            <div v-if="it.reason" class="reason">{{ it.reason }}</div>
            <div v-if="it.advice && (it.advice.positive || it.advice.negative)" class="advice">
              <div v-if="it.advice.positive" class="adv-pos"><b>正向建议：</b>{{ it.advice.positive }}</div>
              <div v-if="it.advice.negative" class="adv-neg"><b>反向建议：</b>{{ it.advice.negative }}</div>
            </div>
          </div>

          <div v-if="(result.stats_report || []).length" style="margin-top:16px">
            <b style="font-size:13px">章节质检</b>
            <div v-for="r in result.stats_report" :key="r.name" style="margin-top:8px;padding-top:8px;border-top:1px solid var(--line)">
              <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
                <b style="font-size:12.5px">{{ r.name }}</b>
                <span class="tag" :class="r.level === '正常' ? 'green' : (r.level === '注意' || r.level === '偏高' || r.level === '偏弱' || r.level === '偏平' ? 'orange' : 'gray')">{{ r.level }}</span>
                <span class="hint" style="font-size:12px">{{ r.value }}</span>
              </div>
              <div class="hint" style="margin-top:2px">{{ r.tip }}</div>
            </div>
          </div>

          <div v-if="(result.foreshadow || []).length" style="margin-top:16px">
            <b style="font-size:13px">伏笔 / 支线回收</b>
            <div v-for="(f, i) in result.foreshadow" :key="i" style="display:flex;gap:8px;align-items:flex-start;margin-top:6px">
              <span class="tag" :class="(f.status === '已回收' || f.status === '支线已闭环') ? 'green' : (f.status === '超期未回收' ? 'red' : 'orange')">{{ f.status }}</span>
              <span><b>{{ f.title }}</b><span v-if="f.note">：{{ f.note }}</span><span v-if="f.evidence" class="hint">（原文：{{ f.evidence }}）</span></span>
            </div>
          </div>

          <div v-if="result.risk && (result.risk.reasons || []).length" class="hint" style="margin-top:12px">
            <b>风险依据：</b>{{ (result.risk.reasons || []).join('；') }}
          </div>

          <div v-for="s in (result.skipped || [])" :key="s.label" class="hint" style="color:var(--orange)">跳过：{{ s.label }}（{{ s.reason }}）</div>
          <div v-if="result.disclaimer" class="hint" style="margin-top:10px">{{ result.disclaimer }}</div>

          <div v-if="Object.keys(reviewFiles).length" style="margin-top:12px">
            <b style="font-size:12px;color:var(--text-2)">报告文件：</b>
            <button v-for="(p, k) in reviewFiles" :key="k" class="link-btn" style="margin-left:8px" @click="openFilePreview(p, p)">{{ k.toUpperCase() }}</button>
          </div>
        </div>
      </div>
    </div>

    <div class="card" style="margin-top:16px">
      <div class="card-head" style="display:flex;align-items:center;gap:8px">
        <div class="card-title">审查日志</div>
        <span class="hint" style="margin-left:auto">{{ lines.length }} 行</span>
        <button class="btn" style="padding:4px 10px;font-size:12px" @click="logExpand = !logExpand">{{ logExpand ? '收起' : '展开全部' }}</button>
        <button class="btn" style="padding:4px 10px;font-size:12px" :disabled="!lines.length" @click="copyLog">复制日志</button>
      </div>
      <JobBar :running="job.running" :code="job.code" :label="jobTitle"
              @stop="stopReview" />
      <div class="rv-log" :class="{ expand: logExpand }"><LogBox :lines="lines" /></div>
    </div>
  </div>
</template>

<style scoped>
.rv-log.expand :deep(.logbox) { max-height: none; }
.batch-log { margin-top: 10px; background: var(--bg); border: 1px solid var(--border);
  border-radius: var(--radius-sm); padding: 8px 10px; font-size: 12px; color: var(--text-2);
  line-height: 1.7; max-height: 130px; overflow: auto; }

/* ---- 正向 / 反向建议 ---- */
.advice { margin-top: 7px; display: flex; flex-direction: column; gap: 5px; }
.adv-pos, .adv-neg { font-size: 12px; line-height: 1.6; padding: 6px 9px; border-radius: var(--radius-sm); }
.adv-pos { color: var(--green); background: var(--green-bg); }
.adv-neg { color: var(--red); background: var(--red-bg); }

/* ---- 原文定位 ---- */
.loc-wrap { border: 1px solid var(--border); border-radius: var(--radius-sm); overflow: hidden; margin-bottom: 14px; }
.loc-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 8px 12px; background: #f7f8fa; }
.loc-body { position: relative; max-height: 420px; overflow: auto; padding: 12px 14px;
  font-size: 13px; line-height: 1.95; white-space: pre-wrap; word-break: break-word; color: var(--text-1, inherit); }

/* 高亮按严重度分色：高=红、中=橙、低=蓝；当前定位那一条更亮 */
.mk { cursor: pointer; border-radius: 3px; padding: 0 1px; }
.mk-ctx { cursor: pointer; border-radius: 2px; }
.mk-ctx.hi { background: rgba(244, 63, 94, .06); }
.mk-ctx.mid { background: rgba(245, 158, 11, .07); }
.mk-ctx.lo { background: rgba(59, 130, 246, .06); }
.mk.hi { background: rgba(244, 63, 94, .16); box-shadow: inset 0 -2px 0 rgba(244, 63, 94, .6); }
.mk.mid { background: rgba(245, 158, 11, .16); box-shadow: inset 0 -2px 0 rgba(245, 158, 11, .6); }
.mk.lo { background: rgba(59, 130, 246, .14); box-shadow: inset 0 -2px 0 rgba(59, 130, 246, .5); }
.mk:hover { background: rgba(245, 158, 11, .3); }
.mk.active { background: rgba(245, 158, 11, .46); box-shadow: 0 0 0 2px rgba(245, 158, 11, .55); }

.issue-loc { cursor: pointer; transition: background .15s, border-color .15s; }
.issue-loc:hover { border-color: var(--border-strong); background: #fafbfc; }
.issue-cur { border-color: rgba(245, 158, 11, .65); background: rgba(245, 158, 11, .07); }
.issue-head .spacer { flex: 1; }
.loc-btn { font-size: 12px; color: var(--text-2); text-decoration: underline; text-underline-offset: 2px; }
.issue-loc:hover .loc-btn { color: var(--text-1, inherit); }
</style>
