<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from '../components/Icon.vue'
import EmptyBox from '../components/EmptyBox.vue'
import CoverModal from '../components/CoverModal.vue'
import Modal from '../components/Modal.vue'
import SelectBox from '../components/SelectBox.vue'
import { VOICE_PRESETS } from '../storyPresets'
import { api, pollExpand as pollExpandApi, pollReview as pollReviewApi } from '../api'
import type { HistoryVersion, SentinelResult, BatchReport, SigningReport,
  ReviewReportItem, ReviewReportKind } from '../api'
import { state, store } from '../store'
import { useBookDoc } from '../composables/useBookDoc'
import { useJobQueue } from '../composables/useJobQueue'
import { usePersistedRef } from '../composables/usePersistedRef'
import { toast, confirmBox } from '../ui'
import { fmtNum, genderTag } from '../utils'
import { stanceMeta, stanceTag as stanceTagOf } from '../factionMeta'
import type { SbSchema } from '../types'

const router = useRouter()
const { raw, fields, cards, factions, items, save } = useBookDoc()
const schema = ref<SbSchema | null>(null)

const meta = computed(() => state.books.find(b => b.name === store.curBook()) || null)
const statusOptions = ['连载中', '已完结']
/* 作品状态存 chapters.json 顶层（书籍级元数据，不进设定库文本——compose 只认 SB_FIELDS 会丢弃它）；
   回显依次取文档顶层 → stats → 按 has_chapters 兜底 */
const curStatus = computed(() => String((raw.value as any)?.status || '').trim()
  || (meta.value?.status as string) || '连载中')
const synopsis = computed(() => (meta.value?.synopsis || '').trim())
/* 简介在窄屏默认折叠三行，点「展开简介」看全文（桌面也跟着生效，但内容完整可见） */
const synopsisOpen = ref(false)
/* 章号：优先 no 字段，其次从 chapter_id / id / title 提取数字（如 "第1章"），最后用序号兜底 */
function chNo(c: any, i: number) {
  for (const k of ['no', 'chapter_id', 'id', 'title']) {
    const m = String(c?.[k] ?? '').match(/\d+/)
    if (m) return Number(m[0])
  }
  return i + 1
}
const chapters = computed<any[]>(() =>
  (raw.value?.chapters || []).map((c: any, i: number) => ({ ...c, _no: chNo(c, i) })))

/* 封面上传 */
const coverVer = ref(0)
const fileRef = ref<HTMLInputElement | null>(null)
function pickCover(f?: File | null) {
  if (!f || !meta.value) return
  if (!/^image\/(png|jpe?g|webp)$/.test(f.type)) return toast('仅支持 png / jpg / webp 图片', 'err')
  if (f.size > 5 * 1024 * 1024) return toast('图片过大（>5MB）', 'err')
  const reader = new FileReader()
  reader.onload = async () => {
    const b64 = (reader.result as string).split(',')[1]
    const ext = f.type === 'image/png' ? 'png' : f.type === 'image/webp' ? 'webp' : 'jpg'
    try {
      await api.uploadCover(store.curBook(), b64, ext)
      toast('封面已更新', 'ok')
      coverVer.value = Date.now()
      store.loadStats().catch(() => {})
    } catch (e: any) { toast(e.message, 'err') }
  }
  reader.readAsDataURL(f)
}
async function rmCover() {
  if (!meta.value) return
  if (!await confirmBox('移除当前封面？', { danger: true, ok: '移除' })) return
  try {
    await api.deleteCover(store.curBook())
    toast('已移除封面', 'ok')
    coverVer.value = Date.now()
    store.loadStats().catch(() => {})
  } catch (e: any) { toast(e.message, 'err') }
}

/* AI 封面弹窗：选平台制式 → 填作者 → 中文提示词自动转英文 → 出图并排版 */
const coverModal = ref(false)
function onCoverDone() {
  coverVer.value = Date.now()
  store.loadStats().catch(() => {})
}
async function dlCover() {
  if (!meta.value) return
  if (!meta.value.has_cover) return toast('还没有封面，请先生成或上传', 'err')
  try {
    const res = await fetch(api.coverUrl(meta.value.name, Date.now()))
    const blob = await res.blob()
    const ext = blob.type.includes('png') ? 'png' : blob.type.includes('webp') ? 'webp' : 'jpg'
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `封面-${meta.value.title || meta.value.name}.${ext}`
    a.click()
    URL.revokeObjectURL(a.href)
  } catch (e: any) { toast('下载失败', 'err') }
}

async function setStatus(v: string) {
  if (!raw.value) return
  ;(raw.value as any).status = v   // 存顶层：后端 PUT 原样保留；不写 fields（会被 compose_story_bible 丢弃）
  const ok = await save(true)   // 失败时 save 内部已提示错误，这里不能再报成功
  if (!ok) return
  store.loadStats().catch(() => {})
  toast('状态已更新为「' + v + '」', 'ok')
}

/* ---------------- 作品级检查入口：只发起任务，不跳转页面 ----------------
   已完结 → 全书体检（全部成稿逐章体检，汇总全书问题）；
   成稿满 2 万字 → 签约预审（平台签约只看前 2 万字）。
   发起后进度看右下角任务条，报告落在「产出文件 → AI 审查报告」。 */
const { runningJobs } = useJobQueue()
const isFinished = computed(() => curStatus.value === '已完结')
const canPrecheck = computed(() => (meta.value?.manuscript_chars || 0) >= 20000)
const runningTask = (name: string) => runningJobs.value.find(j =>
  j.stage === 'review' && j.book === store.curBook() && j.name === name)
const batchJob = computed(() => runningTask('全书体检'))
const signingJob = computed(() => runningTask('签约预审'))
const batchStarting = ref(false)
const signingStarting = ref(false)

async function startBatchReview(): Promise<string> {
  const book = store.curBook()
  if (!book || batchStarting.value) return ''
  const rc = store.callCreds('review')
  if (!rc.api_key) {
    toast('全书体检需要调用模型：请先在设置里给「正文审查」工序配好档案与 Key', 'err')
    return ''
  }
  batchStarting.value = true
  try {
    const r = await api.reviewBatchRun({
      book, incremental: true,
      api_key: rc.api_key, model: rc.model || undefined, base_url: rc.base_url || undefined,
    })
    toast('全书体检已启动：逐章进行，完成后自动刷新报告', 'ok')
    return r?.id || ''
  } catch (e: any) { toast(e.message, 'err'); return '' }
  finally { batchStarting.value = false }
}

async function startSigningReview(): Promise<string> {
  const book = store.curBook()
  if (!book || signingStarting.value) return ''
  const rc = store.callCreds('review')
  // 与「签约预审」页一致：没有 Key 也能跑程序初筛，只是模型复核会跳过
  if (!rc.api_key) toast('未配置 API Key：只跑程序初筛，模型复核会跳过', 'ok')
  signingStarting.value = true
  try {
    const r = await api.reviewSigningRun({
      book, api_key: rc.api_key, model: rc.model || undefined, base_url: rc.base_url || undefined,
    })
    toast('签约预审已启动：扫前 2 万字（≈前 10 章），完成后自动刷新报告', 'ok')
    return r?.id || ''
  } catch (e: any) { toast(e.message, 'err'); return '' }
  finally { signingStarting.value = false }
}

/* ---------------- 报告弹窗：当前 / 历史报告 + 再次执行 ----------------
   每次体检 / 预审后端都会落一份带时间戳的新报告，这里列出历史并回显结构。
   发起任务仍在后台跑，不跳转页面；任务结束自动刷新列表并选中最新一份。 */
const reportOpen = ref(false)
const reportKind = ref<ReviewReportKind>('batch')
const reportMeta = computed(() => reportKind.value === 'batch'
  ? { title: '全书体检', icon: 'shield', run: '再次体检', first: '开始体检', running: '体检中…' }
  : { title: '签约预审', icon: 'flag', run: '再次预审', first: '开始预审', running: '预审中…' })
const reportHistory = ref<ReviewReportItem[]>([])
const reportFile = ref('')
const reportDetail = ref<BatchReport | SigningReport | null>(null)
const reportLoading = ref(false)
const reportFetching = ref(false)
/* 正在跟进的报告类型：按任务 id 轮询，任务再快也能在结束后刷新（不依赖 /api/jobs 的 1.5s 轮询） */
const followingKind = ref<ReviewReportKind | ''>('')
let reportTimer: any = null
const reportBusy = computed(() => followingKind.value === reportKind.value
  || (reportKind.value === 'batch'
    ? !!batchJob.value || batchStarting.value
    : !!signingJob.value || signingStarting.value))
/* 当前 tab 对应的具体报告结构（模板里按类型分别渲染） */
const batchDetail = computed(() => reportKind.value === 'batch'
  ? reportDetail.value as BatchReport | null : null)
const signingDetail = computed(() => reportKind.value === 'signing'
  ? reportDetail.value as SigningReport | null : null)

async function openReport(kind: ReviewReportKind) {
  reportKind.value = kind
  reportFile.value = ''
  reportDetail.value = null
  reportOpen.value = true
  await loadReportHistory(true)
}

async function loadReportHistory(pickLatest = false) {
  const book = store.curBook()
  if (!book) return
  reportLoading.value = true
  try {
    const r = await api.reviewReports(book, reportKind.value)
    reportHistory.value = r.reports || []
    if (pickLatest || !reportHistory.value.some(x => x.file === reportFile.value)) {
      await selectReport(reportHistory.value[0]?.file || '')
    }
  } catch (e: any) { toast(e.message, 'err') }
  finally { reportLoading.value = false }
}

async function selectReport(file: string) {
  const book = store.curBook()
  reportFile.value = file
  reportDetail.value = null
  if (!file || !book) return
  reportFetching.value = true
  try {
    const r = await api.reviewReport(book, reportKind.value, file)
    if (reportFile.value === file) reportDetail.value = r.report
  } catch (e: any) { toast(e.message, 'err') }
  finally { reportFetching.value = false }
}

/* 任务结束后刷新历史并选中最新一份；弹窗已关或切了类型就只清状态 */
async function followReportTask(id: string, kind: ReviewReportKind) {
  const book = store.curBook()
  if (reportTimer) { clearTimeout(reportTimer); reportTimer = null }
  const tick = async () => {
    let running = false
    try {
      const j: any = await pollReviewApi(0, id, book, '')
      running = !!j.running
      if (!running && j.error) toast('报告生成失败：' + j.error, 'err')
    } catch { running = true }        // 网络抖动：继续等，别把任务当成已结束
    if (running) { reportTimer = setTimeout(tick, 900); return }
    reportTimer = null
    if (followingKind.value === kind) followingKind.value = ''
    if (reportOpen.value && reportKind.value === kind) await loadReportHistory(true)
  }
  await tick()
}

async function rerunReport() {
  if (reportBusy.value) return
  const kind = reportKind.value
  followingKind.value = kind
  const id = kind === 'batch' ? await startBatchReview() : await startSigningReview()
  if (!id) {
    followingKind.value = ''
    return
  }
  await followReportTask(id, kind)
}

onUnmounted(() => { if (reportTimer) { clearTimeout(reportTimer); reportTimer = null } })

/* 作品改名：目录名与书内元数据书名一起改；当前书指针随之切换 */
const editBookTitle = ref(false)
const bookTitleDraft = ref('')
const bookTitleRef = ref<HTMLInputElement | null>(null)
function startBookTitle() {
  if (!meta.value) return
  bookTitleDraft.value = meta.value.title || meta.value.name || ''
  editBookTitle.value = true
  nextTick(() => { bookTitleRef.value?.focus(); bookTitleRef.value?.select() })
}
async function saveBookTitle() {
  const from = store.curBook()
  const to = bookTitleDraft.value.trim()
  if (!to || to === from) { editBookTitle.value = false; return }
  try {
    const r = await api.renameBook(from, to)
    editBookTitle.value = false
    store.setBook(r.book || to)
    await store.loadBooks().catch(() => {})
    await store.loadStats().catch(() => {})
    toast('作品名已更新为「' + (r.book || to) + '」', 'ok')
  } catch (e: any) { toast(e.message, 'err') }
}

/* 章节工作台：左侧树 · 中间正文（可编辑） · 右侧概括 */
/* 标签色：角色按性别（男=蓝 女=红），势力按 9 类立场（与势力表同色系） */
const stanceTag = (v: string) => stanceTagOf(v)
const stanceNote = (v: string) => stanceMeta(v)?.note || ''
/* 势力大类直接取卡片上的 category（已与「阵营」合并，不再有第二套词） */
const campNote = (v: string) => String(factionMap.value[v]?.category || '')
const genderMap = computed<Record<string, string>>(() => {
  const m: Record<string, string> = {}
  for (const c of cards.value) if (c.name) m[c.name] = c.gender || ''
  return m
})
const stanceMap = computed<Record<string, string>>(() => {
  const m: Record<string, string> = {}
  for (const f of factions.value) if (f.name) m[f.name] = f.stance || ''
  return m
})
const factionMap = computed<Record<string, Record<string, string>>>(() => {
  const m: Record<string, Record<string, string>> = {}
  for (const f of factions.value) if (f.name) m[f.name] = f
  return m
})
/* 章名：优先手动编辑的章节标题（可覆盖），否则用成稿首行标题；去掉「第 N 章」前缀 */
function chName(c: any) {
  const ms = meta.value?.ms_by_no?.[String(c._no)]
  const raw = String(c.title || '').trim() || (ms && ms.title) || ''
  return raw.replace(/^第\s*\d+\s*章\s*[:：]?/, '').trim()
}
function chLabel(c: any) {
  const name = chName(c)
  return ('第 ' + c._no + ' 章' + (name ? ' ' + name : '')).trim()
}
/* 就地编辑章节名 */
const editingTitle = ref(false)
const titleDraft = ref('')
const titleInput = ref<HTMLInputElement | null>(null)
function startEditTitle() {
  if (!cur.value) return
  titleDraft.value = chName(cur.value)
  editingTitle.value = true
  nextTick(() => titleInput.value && titleInput.value.focus())
}
async function commitTitle() {
  if (!editingTitle.value) return
  editingTitle.value = false
  if (!cur.value) return
  const t = titleDraft.value.trim()
  if (t === chName(cur.value)) return
  cur.value.title = t
  try { await save(true); toast('章节名已保存', 'ok') } catch (e: any) { toast(e.message, 'err') }
}
function chInfo(c: any) {
  return meta.value?.ms_by_no?.[String(c._no)] || null
}

/* 页内正文审查：不跳转，在右栏「审查结果」标签页回显全部问题（只诊断不改写） */
const reviewOpts = ref<any>(null)
const reviewResult = ref<any>(null)
const reviewRunning = ref(false)
/* 这条审查的任务 id：多任务并发时靠它精确轮询 / 停止本页这一次审查，不误伤别章的任务 */
const reviewTaskId = ref('')
const reviewLines = ref<string[]>([])
const reviewErr = ref('')
let reviewTimer: any = null
let reviewSince = 0
const reviewTab = ref<'summary' | 'review' | 'sel'>('summary')
const reviewIssues = computed(() => (reviewResult.value?.issues as any[]) || [])
/* 审查结果记的是当时的正文；之后又改过正文，下标/引文就可能对不上，需要提示重审 */
const reviewStale = computed(() => {
  const t = (reviewResult.value as any)?.text
  return typeof t === 'string' && !!t && t !== msText.value
})
/* 正向 / 反向建议由后端对 Top 问题逐条生成，挂在 issue.advice 上 */
const adviceCount = computed(() => reviewIssues.value.filter((it: any) =>
  it?.advice && (it.advice.positive || it.advice.negative)).length)
const sevCls = (s: string) => s === '高' ? 'hi' : s === '中' ? 'mid' : 'lo'
/* 作品级报告弹窗：签约结论 / 预审检查项的配色，与「单章审查」页一致 */
const verdictCls = (v: string) => v === '可投' ? 'green' : v === '需修改后再投' ? 'orange' : 'red'
const signLevelCls = (lv: string) =>
  lv === '高危' ? 'red' : lv === '警告' ? 'orange' : lv === '通过' ? 'green' : 'gray'

async function loadReviewOpts() {
  try { reviewOpts.value = await api.reviewOptions() } catch { reviewOpts.value = null }
}
async function startReview(no: any) {
  const n = Number(no) || 0
  // 只拦「本章已经在审」和「本章正在生成」：别的章在跑不影响这里，各跑各的
  if (!n || reviewRunning.value || genRunning.value) return
  // 无 Key 也能审查：后端会跳过 AI 项，只跑行文统计与错别字规则初筛
  const rc = store.callCreds('review')   // 审查工序的绑定档案（如 ChatGPT）优先，回落全局
  if (!rc.api_key) toast('未配置 API Key：本次只跑程序体检（统计 + 错别字规则初筛）', 'ok')
  if (!msText.value.trim()) { toast('本章还没有正文，无法审查', 'err'); return }
  const checks = (reviewOpts.value?.checks as string[]) || []
  const body: any = {
    book: store.curBook(), chapter_no: n, chapter_text: msText.value,
    checks, top_n: 99, advice_scope: 'all', api_key: rc.api_key,
  }
  if (rc.model) body.model = rc.model
  if (rc.base_url) body.base_url = rc.base_url
  let started: any = null
  try { started = await api.reviewRun(body) } catch (e: any) { toast(e.message, 'err'); return }
  reviewTaskId.value = started?.id || ''
  reviewRunning.value = true; reviewErr.value = ''; reviewLines.value = []
  reviewResult.value = null; reviewTab.value = 'review'; reviewSince = 0
  curIssue.value = -1
  reviewTimer = setInterval(pollReviewInline, 900)
}
async function pollReviewInline() {
  try {
    const j: any = await pollReviewApi(reviewSince, reviewTaskId.value,
      store.curBook(), selNo.value)
    reviewSince = j.total
    if (j.lines && j.lines.length) {
      reviewLines.value.push(...j.lines)
      if (reviewLines.value.length > 2000) reviewLines.value.splice(0, reviewLines.value.length - 2000)
    }
    if (!j.running) {
      clearInterval(reviewTimer); reviewTimer = null; reviewRunning.value = false
      if (j.error) { reviewErr.value = j.error; toast('审查失败：' + j.error, 'err') }
      else if (j.stopped) toast('审查已停止 / 释放', 'ok')
      else { reviewResult.value = j.result; reviewErr.value = ''; toast('审查完成', 'ok') }
    }
  } catch { /* 轮询失败下一轮再试 */ }
}
function stopReview() {
  api.stopReview(reviewTaskId.value).then(() => toast('已请求停止', 'ok'))
    .catch((e: any) => toast(e.message, 'err'))
}
/* 释放审查：不等当前这一步跑完就解锁，本地同时停轮询、清进度。
   只释放这一条——别的章还在审的任务不受影响 */
async function releaseReview() {
  try { await api.releaseReview(reviewTaskId.value) } catch (e: any) { toast(e.message, 'err'); return }
  reviewTaskId.value = ''
  if (reviewTimer) { clearInterval(reviewTimer); reviewTimer = null }
  reviewRunning.value = false
  reviewResult.value = null
  reviewErr.value = ''
  reviewLines.value = []
  toast('已释放审查：可以切章或发起别的任务了', 'ok')
}
function clearReview() {
  if (reviewTimer) { clearInterval(reviewTimer); reviewTimer = null }
  reviewRunning.value = false; reviewResult.value = null; reviewErr.value = ''
  reviewLines.value = []; reviewTab.value = 'summary'; reviewTaskId.value = ''
  curIssue.value = -1
}

/* 页内单章正文生成：不跳转，直接按「作品大纲 + 角色卡 + 势力表 + 本章概括」流式生成，
   支持五种模式：按大纲生成（从零写）/ 续写（接着当前正文往下写，流式追加）/
   扩写（现有正文写得更丰满）/ 改写（换节奏文风重写，情节不变）/ 润色（文字层面打磨，不改内容）。
   支持文风切换（都市/玄幻/古言/悬疑/甜宠/爽文，默认沿用设定）与多版本候选（2/3/5 版）。
   生成时编辑器禁止输入，内容逐字回显，完成后解锁（后端同步落盘成稿） */
type GenMode = 'outline' | 'continue' | 'expand' | 'rewrite' | 'polish'
const genMode = usePersistedRef<GenMode>('overview.genMode', 'outline')
const genUsedMode = ref<GenMode>('outline')   // 本次生成实际用的模式（采纳时按它落地，避免中途改下拉框错位）
const genStyle = usePersistedRef<string>('overview.genStyle', '沿用设定')
const genCount = usePersistedRef<number>('overview.genCount', 3)
/* 下拉选中值统一是 string：在这里收窄成 GenMode，避免模板里到处断言 */
function setGenMode(v: string) { genMode.value = v as GenMode }
function setGenCount(v: string) { genCount.value = Number(v) || 3 }
const genRunning = ref(false)
const genError = ref('')
/* 后端正文任务状态（书 / 章 / 模式 / 耗时 / 上次失败原因）：
   像「执行拆解」一样跨页面保持——切走再回来能接管进行中的任务，失败原因也不会凭空消失 */
const genTask = ref<any>(null)
/* 本页这一次生成的任务 id：并发时按 id 轮询，不会把别章正在跑的任务显示到本章 */
const genTaskId = ref('')
/* 只有「本章正在生成」才算忙；别的章在生成不该禁用本章的按钮 */
const genBusy = computed(() => genRunning.value)
let genTimer: any = null
const genModeLabel: Record<GenMode, string> = {
  outline: '按大纲生成', continue: '续写', expand: '扩写', rewrite: '改写', polish: '润色',
}
/** 后端返回的模式字符串 → 中文标签（模板里避免写 TS 断言） */
function modeLabel(m: any): string { return genModeLabel[(m || 'outline') as GenMode] || '生成' }

async function genChapter(no: any) {
  const n = Number(no) || 0
  if (!n) return
  await startGen(genMode.value, 'chapter')
}

/* 生成范围：chapter=整章；selection=仅选中文字。
   before / after：选区前后的正文，供 AI 承接上下文（单句选区尤其需要） */
const genTarget = ref<{ scope: 'chapter' | 'selection'; start: number; end: number;
  text: string; before: string; after: string }>(
  { scope: 'chapter', start: 0, end: 0, text: '', before: '', after: '' })

/* 当前候选属于哪一类任务（整章 / 选区），以后端任务里的 scope 为准：
   genTarget 只在本次操作里有意义，切章 / 刷新后会归零，用它判断会把选区结果当成整章候选采纳 */
const genScope = ref<'chapter' | 'selection'>('chapter')

async function startGen(mode: GenMode, scope: 'chapter' | 'selection') {
  const n = Number(selNo.value) || 0
  if (!n || genRunning.value) return
  if (genTask.value?.running && Number(genTask.value.chapter_no) === n) {
    toast(`第 ${n} 章正在生成（${modeLabel(genTask.value.mode)}），请等它结束或先停止`, 'err')
    return
  }
  // 审查和生成互不阻塞：别的章在审 / 在写都不影响这里，只有「本章」在跑才拦
  const hasKey = !!(store.profileFor(scope === 'selection' ? 'expand_selection' : `expand_${mode}`)?.api_key || state.key)
  if (!hasKey) toast('未配置 API Key：将以本地骨架生成（不调用模型），配好 Key 后可重生成正文', '')
  const hasText = !!msText.value.trim()
  if (scope === 'chapter') {
    if (mode === 'outline') {
      if (hasText && !(await confirmBox('生成会覆盖本章正文，继续？', { ok: '覆盖并生成' }))) return
    } else if (!hasText) {
      toast(`本章还没有正文，无法「${genModeLabel[mode]}」，请先用「按大纲生成」`, 'err'); return
    } else if (mode !== 'continue' && !(await confirmBox('扩写 / 改写 / 润色会替换本章正文（采纳前不会改动，可随时对比），继续？', { ok: '开始' }))) return
  } else {
    // 选区操作：仅 continue / expand / rewrite
    if (!genTarget.value.text.trim()) { toast('请先在正文中选中一段文字', 'err'); return }
  }
  const existing = scope === 'selection' ? genTarget.value.text : (mode === 'outline' ? '' : msText.value)
  // 整章生成时必须清掉上次的选区，否则采纳候选时会把正文当选区替换，落到错误的偏移上
  if (scope === 'chapter') genTarget.value = { scope: 'chapter', start: 0, end: 0, text: '', before: '', after: '' }
  /* 多模型：按工序取绑定档案的凭据（选区 / 初稿 / 续写 / 改写…各绑各的）；没绑再回落全局 */
  const creds = store.callCreds(scope === 'selection' ? 'expand_selection' : `expand_${mode}`)
  let started: any = null
  try {
    started = await api.expandChapter({
      book: store.curBook(), chapter_no: n, api_key: creds.api_key, mode, text: existing,
      // scope 决定后端任务名（改写选区 / 整章改写）与候选落点，必须显式告知
      scope,
      // 选区在正文里的起止：后端随任务落盘，切书 / 切章回来恢复候选后仍能按原位采纳
      sel_start: scope === 'selection' ? genTarget.value.start : undefined,
      sel_end: scope === 'selection' ? genTarget.value.end : undefined,
      // 选区操作带上前后文：AI 才能把单句接得自然
      before: scope === 'selection' ? genTarget.value.before : undefined,
      after: scope === 'selection' ? genTarget.value.after : undefined,
      style: genStyle.value, count: genCount.value,
      // 绑定档案的模型 / 端点要带给后端，否则会退回服务端默认值（可能不是同一个服务商）
      model: creds.model || undefined,
      base_url: creds.base_url || undefined,
    })
  } catch (e: any) { toast(e.message, 'err'); return }
  genTaskId.value = started?.id || ''
  genUsedMode.value = mode
  genScope.value = scope
  genRunning.value = true
  genError.value = ''
  genStatus.value = ''
  genTask.value = { running: true, book: store.curBook(), chapter_no: n, mode, multi: mode !== 'outline',
    versions: [], recommended: 0, code: null, error: null, stopped: false,
    started_at: Date.now() / 1000, elapsed: 0 }
  if (scope === 'chapter') {
    if (mode === 'outline') msText.value = ''      // 大纲生成：清空，流式回显
    else originalText.value = msText.value        // 整章续写要拿原文做底
    msDirty.value = false
  }
  // 选区任务不动正文：既不清空也不该顺手抹掉「未保存」标记
  if (genTimer) clearInterval(genTimer)
  genTimer = setInterval(pollGen, 300)
}

async function pollGen() {
  try {
    /* 每次拉全量（服务端 text 是累计结果）：直接整体覆盖而不是增量拼接，
       这样接管任务、本地正文被文件覆盖等情况都不会出现丢字/重复。
       只认「本页这条任务」（按 id + 章号取），别章并发生成的内容不会串到这里 */
    const j = await pollExpandApi(0, store.curBook(), genTaskId.value, selNo.value)
    genTask.value = j
    // 任务性质以后端为准：接管 / 刷新后也能知道这是选区改写还是整章生成
    if (j.scope === 'selection' || j.scope === 'chapter') genScope.value = j.scope
    const taskCh = Number(j.chapter_no) || 0
    const mine = !taskCh || taskCh === Number(selNo.value)   // 任务是否属于当前正在看的这一章
    if (j.running) {
      if (j.multi) {
        // 多版本模式：进度显示在状态区，不写入编辑器
        if (mine) genStatus.value = j.text
      } else if (mine) {
        msText.value = j.text
        const el = document.querySelector('.ws-editor') as HTMLElement | null
        if (el) el.scrollTop = el.scrollHeight
      }
      return
    }
    clearInterval(genTimer); genTimer = null
    genRunning.value = false
    // 后端任务名已区分「改写选区」「整章改写」，直接用，别再用模式名糊一个
    const label = j.name || genModeLabel[(j.mode as GenMode) || genMode.value] || '生成'
    if (j.stopped) {
      toast('已停止生成（可重新点生成）', 'ok')
    } else if (j.code === 0) {
      if (j.multi && j.versions && j.versions.length) {
        if (mine) {
          candidates.value = j.versions
          recIndex.value = j.recommended || 0
          if (genScope.value === 'selection') {
            reviewTab.value = 'sel'          // 选区结果固定进「选区候选」tab，不弹窗打断
          } else {
            showCandidates.value = true
          }
        }
        toast(`第 ${taskCh || selNo.value} 章${label}已生成 ${j.versions.length} 个候选` +
              (mine ? (genScope.value === 'selection' ? '，见右栏「选区候选」' : '，请采纳其一')
                    : `，切回第 ${taskCh} 章可查看`), 'ok')
      } else if (mine) {
        msText.value = ''
        try {
          const fin: any = await api.getOutput(msPath(j.chapter_no || selNo.value))
          msText.value = fin.content || ''
        } catch { /* 拿不到就用已回显内容 */ }
        msDirty.value = false
        store.loadStats().catch(() => {})
        toast(`第 ${j.chapter_no || selNo.value} 章${label}完成`, 'ok')
      } else {
        toast(`第 ${taskCh} 章${label}完成`, 'ok')
      }
    } else {
      genError.value = j.error || '未知错误'
      // 大纲生成会先清空编辑器：失败时从成稿文件回滚，避免正文看起来被清掉
      if (mine && !j.multi) {
        try {
          const fin: any = await api.getOutput(msPath(j.chapter_no || selNo.value))
          msText.value = fin.content || ''
        } catch { /* 文件不存在：保持现状 */ }
        msDirty.value = false
      }
      toast(`${label}失败：` + genError.value, 'err')
    }
  } catch { /* 轮询失败下一轮再试 */ }
}

/* 任务状态保持：进入页面 / 切换章节后，接管仍在运行的正文任务；
   若上次任务已结束，则保留其失败原因（banner），不再随页面刷新丢掉 */
async function syncGenTask() {
  const book = store.curBook()
  if (!book || genRunning.value) return
  try {
    // 本章自己的任务（多任务并发时只接管这一章，别章在生成的进度留在任务中心看）
    const j = await pollExpandApi(0, book, '', selNo.value)
    genTaskId.value = j.id || ''
    const taskCh = Number(j.chapter_no) || 0
    if (j.running && j.book === book && taskCh === Number(selNo.value)) {
      genTask.value = j
      genRunning.value = true
      genUsedMode.value = (j.mode as GenMode) || 'outline'
      genMode.value = genUsedMode.value
      genScope.value = j.scope === 'selection' ? 'selection' : 'chapter'
      genStatus.value = j.multi ? j.text : ''
      if (!j.multi) msText.value = j.text
      if (genTimer) clearInterval(genTimer)
      genTimer = setInterval(pollGen, 300)
      toast(`已接管进行中的${j.name || genModeLabel[genUsedMode.value]}：第 ${j.chapter_no} 章`, 'ok')
    } else {
      genTaskId.value = ''
      const my = String(selNo.value)
      const live = (j.book === book && taskCh === Number(selNo.value)) ? j : null
      // 结果有两个来源：进程里这条任务，或这本书「这一章」的落盘快照。
      // 切书 / 切章 / 重启服务回来，候选和选区都得原样回来，不能让人重新生成一遍
      const snap = (j.last && String(j.last.chapter_no ?? '') === my &&
                    (!j.last.book || j.last.book === book)) ? j.last : null
      const res: any = (live?.versions?.length ? live : null) ||
                       (snap?.versions?.length ? snap : null)
      if (res) {
        candidates.value = res.versions
        recIndex.value = res.recommended || 0
        genScope.value = res.scope === 'selection' ? 'selection' : 'chapter'
        genUsedMode.value = (res.mode as GenMode) || genUsedMode.value
        genMode.value = genUsedMode.value        // 「查看 N 个候选」按钮按它判断
        if (genScope.value === 'selection') {
          restoreSelTarget(res.target)           // 选区还能对上就直接可采纳
          if (reviewTab.value === 'summary') reviewTab.value = 'sel'
        } else if (res.mode === 'continue' && !originalText.value && res.existing) {
          originalText.value = res.existing      // 整章续写采纳要接在这次生成前的原文之后
        }
      }
      const err = live ? j.error : (j.last?.error || null)
      const src = live || j.last
      genTask.value = err ? { ...src, running: false, error: err } : null
    }
  } catch { /* 服务未就绪时静默 */ }
}

/* 选中章节后同步审查任务：进行中的接管继续轮询，已结束的回显结果 / 失败原因。
   只认「本书 + 本章」的任务，避免把别章 / 别书的审查结果串进当前章。 */
async function syncReviewTask() {
  const book = store.curBook()
  if (!book || reviewRunning.value) return
  const my = String(selNo.value)
  try {
    // 只按「本书 + 本章」找：多任务并发时不会把别章正在跑的审查接管到本章
    const j: any = await pollReviewApi(0, '', book, selNo.value)
    // 新后端带顶层 book/chapter_no；旧后端回退取结果里的 meta，二者都拿不到则视为未知
    const jBook = j.book || j.result?.meta?.book || ''
    const jCh = String(j.chapter_no ?? j.result?.meta?.chapter_no ?? '')
    const sameBook = !jBook || jBook === book
    const sameCh = !!jCh && jCh === my
    if (j.running) {
      // 进行中：只有确认属于当前章（或旧后端未标注章号）才接管，防止在别章误显示审查进度
      if (!sameBook || (jCh && !sameCh)) return
      reviewTaskId.value = j.id || ''
      reviewRunning.value = true
      reviewLines.value = []
      reviewResult.value = null; reviewErr.value = ''
      reviewSince = 0
      reviewTab.value = 'review'
      if (reviewTimer) clearInterval(reviewTimer)
      reviewTimer = setInterval(pollReviewInline, 900)
      toast('已接管进行中的正文审查', 'ok')
    } else if ((j.result || j.stopped || j.error) && sameBook && sameCh) {
      // 已结束：仅当结果属于当前章时回显，切到别的章不会残留上一章的审查结论
      reviewResult.value = j.result || null
      reviewErr.value = j.error || ''
      reviewLines.value = (j.lines && j.lines.length) ? j.lines.slice(-2000) : []
      reviewTab.value = 'review'
      curIssue.value = -1
    }
  } catch { /* 服务未就绪时静默 */ }
}


/* 恢复选区任务的落点（后端跟着任务落盘的那份）。
   位置对得上就原样恢复，可以继续采纳；正文已经改过时也保留原文，
   由 selOffsetOk / adoptVersion 的校验拦下，绝不当成整章替换 */
function restoreSelTarget(tg: any) {
  if (!tg || typeof tg.start !== 'number' || typeof tg.end !== 'number') return
  const text = String(tg.text || '')
  if (!text) return
  genTarget.value = { scope: 'selection', start: tg.start, end: tg.end, text,
    before: tg.before || '', after: tg.after || '' }
}

function adoptVersion(i: number) {
  const v = candidates.value[i]
  if (!v) return
  const t = genTarget.value
  const used = genUsedMode.value
  // 选区任务但没有选区偏移（切过章 / 刷新过）：绝不能退化成「整章替换」
  if (genScope.value === 'selection' && t.scope !== 'selection') {
    toast('这是选区改写的结果，但选区位置已失效：请回到正文重新选中后再生成一次', 'err')
    return
  }
  if (t.scope === 'selection') {
    // 以当前正文为准并校验选区偏移：等待生成期间用户改过正文时拒绝落笔，避免丢改动
    if (msText.value.slice(t.start, t.end) !== t.text) {
      toast('正文已变化，选区位置失效，请重新选中后再生成', 'err'); return
    }
    const base = msText.value
    if (used === 'continue') {
      // 续写：在选区之后插入
      msText.value = base.slice(0, t.end) + (base.slice(t.end).startsWith('\n') ? '' : '\n\n')
        + v.text + base.slice(t.end)
    } else {
      // 扩写 / 改写 / 润色：替换选区
      msText.value = base.slice(0, t.start) + v.text + base.slice(t.end)
      // 标签与正文保持对齐：落点更新为采纳后的这段文字，而不是留在旧偏移上
      genTarget.value = { ...t, end: t.start + v.text.length, text: v.text }
    }
    msDirty.value = true
  } else if (used === 'continue') {
    const orig = (originalText.value || '').replace(/\s+$/, '')
    msText.value = (orig ? orig + '\n\n' : '') + v.text
  } else {
    msText.value = v.text
  }
  msDirty.value = true
  showCandidates.value = false
  toast(`已采纳第 ${i + 1} 版，可继续编辑后点「保存正文」`, 'ok')
}
async function copyVersion(i: number) {
  const v = candidates.value[i]
  if (!v) return
  try { await navigator.clipboard.writeText(v.text); toast('已复制到剪贴板', 'ok') }
  catch { toast('复制失败', 'err') }
}

/* 在正文里找原选区文字：先精确找，找不到再忽略空白差异找（复制粘贴改了空格时兜底） */
function findSelText(q: string): number {
  if (!q) return -1
  const first = msText.value.indexOf(q)
  if (first >= 0) return first
  const flat = q.replace(/\s+/g, '')
  if (flat.length > 1) {
    const { acc, idx } = flatBody.value
    const p = acc.indexOf(flat)
    if (p >= 0) return idx[p]
  }
  return -1
}

/* 点「润色选区」标签：在正文里框出原选区并滚到视口中间。
   偏移对不上时（切章 / 刷新回来、正文改过）按文字重新找位置，
   全文唯一命中就自动校正偏移——采纳按钮随之恢复可用 */
function locateSelTarget() {
  const t = genTarget.value
  if (t.scope !== 'selection' || !t.text) return
  let s = t.start, e = t.end
  if (!selSpan.value) {
    const idx = findSelText(t.text)
    if (idx < 0) { toast('原选区文字已不在正文中，无法定位', 'err'); return }
    const again = msText.value.indexOf(t.text, idx + 1)
    s = idx; e = idx + t.text.length
    if (again < 0) {
      genTarget.value = { ...t, start: s, end: e }
      toast('已按文字重新定位原选区，可继续采纳', 'ok')
    } else {
      toast('正文里有多处相同文字，仅定位到第一处；采纳请重新选中后再生成', 'ok')
    }
  }
  nextTick(() => {
    const ta = edEl.value
    if (!ta) return
    ta.focus()
    try { ta.setSelectionRange(s, e) } catch { /* 越界忽略 */ }
    syncHl()
    const mark = hlInner.value?.querySelector('mark.sel') as HTMLElement | null
    if (mark && ta.clientHeight) {
      const mr = mark.getBoundingClientRect()
      const tr = ta.getBoundingClientRect()
      ta.scrollTop = Math.max(0, ta.scrollTop + (mr.top - tr.top) - ta.clientHeight / 2 + mr.height / 2)
      syncHl()
    }
  })
}

const genIsMulti = computed(() => genMode.value !== 'outline')
const candidates = ref<{ text: string; note: string; chars: number }[]>([])
const recIndex = ref(0)
const showCandidates = ref(false)
const genStatus = ref('')
const originalText = ref('')

/* 选中文字后右键菜单：对选区做续写 / 扩写 / 改写（仍走三版候选 + 采纳） */
const ctxMenu = ref<{ x: number; y: number } | null>(null)
function onContextMenu(e: MouseEvent) {
  if (genRunning.value) return
  const ta = e.target as HTMLTextAreaElement
  if (!ta || ta.tagName !== 'TEXTAREA') return
  const s = ta.selectionStart, en = ta.selectionEnd
  if (s === en) return                       // 无选区 → 走系统默认菜单
  e.preventDefault()
  genTarget.value = { scope: 'selection', start: s, end: en, text: ta.value.slice(s, en),
    // 前文多带一点作语境，后文是「要接过去」的方向
    before: ta.value.slice(Math.max(0, s - 1200), s),
    after: ta.value.slice(en, en + 600) }
  ctxMenu.value = { x: e.clientX, y: e.clientY }
}
function hideCtx() { ctxMenu.value = null }
function selGen(mode: GenMode) {
  const m = ctxMenu.value; hideCtx()
  if (!m) return
  startGen(mode, 'selection')
}
function stopGen() {
  // 只停本页这一条：别的章还在并发生成，不能一起停掉
  api.stopExpand(genTaskId.value || undefined)
    .then(() => toast('已请求停止', 'ok')).catch((e: any) => toast(e.message, 'err'))
}
function closeCandidates() { showCandidates.value = false }

/* 沉浸式全屏写作：写作台卡片铺满整个视窗，Esc 或再点按钮退出 */
const wsFull = ref(false)
function toggleWsFull() {
  wsFull.value = !wsFull.value
  if (wsFull.value) {
    nextTick(() => (document.querySelector('.ws-editor') as HTMLTextAreaElement | null)?.focus())
  }
}
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && wsFull.value) wsFull.value = false
}
watch(wsFull, v => { document.body.style.overflow = v ? 'hidden' : '' })

/* 三栏 Splitter：左右栏可拖拽调宽、可收起，布局记忆到 localStorage */
const WS_KEY = 'ws.layout'
const savedWs = (() => { try { return JSON.parse(localStorage.getItem(WS_KEY) || '{}') as Record<string, unknown> } catch { return {} } })()
const treeW = ref(Number(savedWs.treeW) || 230)
const sideW = ref(Math.max(380, Number(savedWs.sideW) || 380))
const treeOff = ref(!!savedWs.treeOff)
const sideOff = ref(!!savedWs.sideOff)
function saveWsLayout() {
  try { localStorage.setItem(WS_KEY, JSON.stringify(
    { treeW: treeW.value, sideW: sideW.value, treeOff: treeOff.value, sideOff: sideOff.value })) } catch { /* 忽略 */ }
}
let dragPane: 'tree' | 'side' | null = null
let dragX0 = 0, dragW0 = 0
function startDrag(pane: 'tree' | 'side', e: PointerEvent) {
  if (pane === 'tree' ? treeOff.value : sideOff.value) return
  e.preventDefault()
  dragPane = pane; dragX0 = e.clientX
  dragW0 = pane === 'tree' ? treeW.value : sideW.value
  document.body.classList.add('ws-resizing')
  window.addEventListener('pointermove', onDragMove)
  window.addEventListener('pointerup', endDrag, { once: true })
}
function onDragMove(e: PointerEvent) {
  if (!dragPane) return
  const w = dragPane === 'tree' ? dragW0 + (e.clientX - dragX0) : dragW0 - (e.clientX - dragX0)
  if (dragPane === 'tree') {
    if (w < 110) { endDrag(); treeOff.value = true; return }
    treeW.value = Math.min(420, Math.max(160, w))
  } else {
    if (w < 150) { endDrag(); sideOff.value = true; return }
    sideW.value = Math.min(560, Math.max(380, w))
  }
}
function endDrag() {
  dragPane = null
  document.body.classList.remove('ws-resizing')
  window.removeEventListener('pointermove', onDragMove)
  saveWsLayout()
}
function toggleTree() { treeOff.value = !treeOff.value; saveWsLayout() }
function toggleSide() { sideOff.value = !sideOff.value; saveWsLayout() }
onMounted(() => {
  document.addEventListener('click', hideCtx)
  document.addEventListener('keydown', onKeydown)
  window.addEventListener('resize', syncHl)
  loadReviewOpts()
  // 任务同步放在 selectChapter 末尾（章节内容加载完之后）：先读到本章正文，再由任务接管流式回显，
  // 否则顺序反过来会把「生成中的半成品」当成原稿覆盖掉编辑器
})
onUnmounted(() => {
  if (genTimer) clearInterval(genTimer)
  if (reviewTimer) clearInterval(reviewTimer)
  document.removeEventListener('click', hideCtx)
  document.removeEventListener('keydown', onKeydown)
  window.removeEventListener('pointermove', onDragMove)
  window.removeEventListener('resize', syncHl)
  if (hlRO) { hlRO.disconnect(); hlRO = null }
  document.body.classList.remove('ws-resizing')
  document.body.style.overflow = ''
})
function msPath(no: any) {
  return `data/${store.curBook()}/manuscript/${String(Number(no) || 0).padStart(3, '0')}.txt`
}

const selNo = ref(0)
const msText = ref('')
const msLoading = ref(false)
const msDirty = ref(false)
const msSaving = ref(false)
/* 选区落点是否还能用：正文没被改过、且选区那一段文本仍然对得上 */
const selSpan = computed<[number, number] | null>(() => {
  const t = genTarget.value
  if (t.scope !== 'selection' || !msText.value) return null
  if (t.end <= t.start || t.end > msText.value.length) return null
  return msText.value.slice(t.start, t.end) === t.text ? [t.start, t.end] : null
})
const selOffsetOk = computed(() => genTarget.value.scope === 'selection' && !!selSpan.value)
const cur = computed(() => chapters.value.find(c => c._no === selNo.value) || null)
const curMs = computed(() => (selNo.value ? meta.value?.ms_by_no?.[String(selNo.value)] || null : null))

/* ---------------- 审查问题 → 正文定位 / 高亮 ----------------
   后端每条 issue 都带 span（相对「审查提交的正文」result.text 的起止下标）与 line。
   写作台的正文是原生 textarea，没有富文本能力，这里用「镜像层」画高亮：
   同一段正文用相同字体 / 行高 / 内边距铺在 textarea 底下，只给命中片段上底色，
   纵向跟着 textarea 滚动走。点一条问题 → 选中该片段并滚到视口中间。 */
const edEl = ref<HTMLTextAreaElement | null>(null)
const hlBox = ref<HTMLElement | null>(null)
const hlInner = ref<HTMLElement | null>(null)
const curIssue = ref(-1)

const htmlEsc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

/* 去掉空白后的正文 + 每个字在原文里的下标：引文与正文空格 / 换行不一致时兜底 */
const flatBody = computed(() => {
  const t = msText.value
  let acc = ''
  const idx: number[] = []
  for (let i = 0; i < t.length; i++) {
    if (!/\s/.test(t[i])) { acc += t[i]; idx.push(i) }
  }
  return { acc, idx }
})

/* 在「当前正文」里找这条问题的位置：span 命中 → 引文就近重找 → 行号兜底。
   审查之后用户可能又改过正文，所以不能直接信任后端下标。 */
function issueSpan(it: any): [number, number] | null {
  const t = msText.value
  const q = String(it?.quote || '')
  const sp = it?.span
  if (Array.isArray(sp) && sp.length === 2) {
    const s = Number(sp[0]) || 0
    const e = Number(sp[1]) || 0
    if (s >= 0 && e > s && e <= t.length && (!q || t.slice(s, e) === q)) return [s, e]
  }
  if (q) {
    const want = Number(it?.offset ?? (Array.isArray(sp) ? sp[0] : 0)) || 0
    let best = -1
    for (let i = t.indexOf(q); i >= 0; i = t.indexOf(q, i + 1)) {
      if (best < 0 || Math.abs(i - want) < Math.abs(best - want)) best = i
    }
    if (best >= 0) return [best, best + q.length]
    const flat = q.replace(/\s+/g, '')
    if (flat.length > 1) {
      const { acc, idx } = flatBody.value
      const p = acc.indexOf(flat)
      if (p >= 0) return [idx[p], idx[p + flat.length - 1] + 1]
    }
  }
  const line = Number(it?.line) || 0
  if (line > 0) {
    const lines = t.split('\n')
    let start = 0
    for (let i = 0; i < line - 1 && i < lines.length; i++) start += lines[i].length + 1
    if (start < t.length) return [start, start + Math.max(1, (lines[line - 1] || '').length)]
  }
  return null
}

const spanByIssue = computed(() => {
  const m = new Map<number, [number, number]>()
  reviewIssues.value.forEach((it: any, i: number) => {
    const sp = issueSpan(it)
    if (sp) m.set(i, sp)
  })
  return m
})

/* 高亮层 HTML：重叠区间合并成一块，一条 mark 可带多条问题（data-ixs）。
   选区任务的「原选区」也画进来（class=sel，蓝色），让标签和正文位置一眼对上 */
const hlHtml = computed(() => {
  const t = msText.value
  const sel = selSpan.value
  if (!t || (!spanByIssue.value.size && !sel)) return ''
  const items: { i: number | string; s: number; e: number }[] = [...spanByIssue.value.entries()]
    .map(([i, sp]) => ({ i, s: sp[0], e: Math.min(sp[1], t.length) }))
    .filter(x => x.e > x.s)
  if (sel) items.push({ i: 'sel', s: sel[0], e: Math.min(sel[1], t.length) })
  if (!items.length) return ''
  items.sort((a, b) => a.s - b.s || a.e - b.e)
  const blocks: { s: number; e: number; idxs: (number | string)[] }[] = []
  for (const it of items) {
    const last = blocks[blocks.length - 1]
    if (last && it.s < last.e) {
      last.e = Math.max(last.e, it.e)
      if (!last.idxs.includes(it.i)) last.idxs.push(it.i)
    } else blocks.push({ s: it.s, e: it.e, idxs: [it.i] })
  }
  let out = ''
  let pos = 0
  for (const b of blocks) {
    if (b.s > pos) out += htmlEsc(t.slice(pos, b.s))
    const cls = 'hl' + (b.idxs.includes('sel') ? ' sel' : '')
      + (b.idxs.includes(curIssue.value) ? ' on' : '')
    out += `<mark class="${cls}" data-ixs="${b.idxs.join(' ')}">${htmlEsc(t.slice(b.s, b.e))}</mark>`
    pos = b.e
  }
  if (pos < t.length) out += htmlEsc(t.slice(pos))
  return out
})
const hlOn = computed(() => !!hlHtml.value)

/* 镜像层与 textarea 严格对齐：宽度取 clientWidth（不含滚动条），纵向跟随滚动 */
function syncHl() {
  const ta = edEl.value
  if (!ta) return
  const box = hlBox.value
  const inner = hlInner.value
  if (box) box.style.width = ta.clientWidth + 'px'
  if (inner) inner.style.transform = `translateY(${-ta.scrollTop}px)`
}
watch(hlOn, v => { if (v) nextTick(syncHl) })

/* 编辑器宽度会随侧栏拖拽 / 窗口变化而变，镜像层要跟着重算宽度，否则折行对不上 */
let hlRO: ResizeObserver | null = null
watch(edEl, el => {
  if (hlRO) { hlRO.disconnect(); hlRO = null }
  if (el && typeof ResizeObserver !== 'undefined') {
    hlRO = new ResizeObserver(() => syncHl())
    hlRO.observe(el)
  }
  nextTick(syncHl)
})

function focusIssue(i: number) {
  const it = reviewIssues.value[i]
  if (!it) return
  curIssue.value = i
  const sp = spanByIssue.value.get(i) || issueSpan(it)
  if (!sp) {
    toast(it.line ? `这条没有原文片段，约在第 ${it.line} 行` : '这条没有可定位的原文片段', 'ok')
    return
  }
  nextTick(() => {
    const ta = edEl.value
    if (!ta) return
    ta.focus()
    try { ta.setSelectionRange(sp[0], sp[1]) } catch { /* 越界忽略 */ }
    syncHl()
    const mark = hlInner.value?.querySelector(`mark[data-ixs~="${i}"]`) as HTMLElement | null
    if (mark && ta.clientHeight) {
      const mr = mark.getBoundingClientRect()
      const tr = ta.getBoundingClientRect()
      const top = ta.scrollTop + (mr.top - tr.top) - ta.clientHeight / 2 + mr.height / 2
      ta.scrollTop = Math.max(0, top)
      syncHl()
    }
  })
}

/* 点问题卡片就是明确要定位：不做"编辑器里有选区就跳过"的保护，
   否则连着点第二条会毫无反应（上一条的选区还在，正好把自己挡住）。 */
function issueClick(i: number) {
  focusIssue(i)
}
/* 当前章在原始数据里的复制时间标记 */
const curCopiedAt = computed(() => {
  if (!cur.value) return ''
  const src = raw.value?.chapters?.find((x, i) => chNo(x, i) === cur.value!._no)
  return src?.copiedAt || ''
})
/* 正文复制到剪贴板，并记录复制时间（随章节数据保存） */
async function copyMs() {
  if (!cur.value) return
  if (!msText.value.trim()) { toast('本章还没有正文', 'err'); return }
  try {
    await navigator.clipboard.writeText(msText.value)
    const src = raw.value?.chapters?.find((x, i) => chNo(x, i) === cur.value!._no)
    if (src) {
      src.copiedAt = new Date().toLocaleString('zh-CN', { hour12: false })
      save(true).catch(() => {})
    }
    toast('正文已复制到剪贴板', 'ok')
  } catch (e) {
    toast('复制失败，请检查浏览器权限', 'err')
  }
}

/* 卷分组：章节带 volume / vol 字段则分卷，否则平铺为「全部章节」 */
const tree = computed<{ name: string; items: any[] }[]>(() => {
  const chs = chapters.value
  const hasVol = chs.some(c => String(c.volume || c.vol || '').trim())
  if (!hasVol) return [{ name: '全部章节', items: chs }]
  const groups: { name: string; items: any[] }[] = []
  const idx: Record<string, number> = {}
  for (const c of chs) {
    const v = String(c.volume || c.vol || '').trim() || '未分卷'
    if (idx[v] === undefined) { idx[v] = groups.length; groups.push({ name: v, items: [] }) }
    groups[idx[v]].items.push(c)
  }
  return groups
})

async function selectChapter(c: any) {
  /* 切章不再被任何任务挡住：本章的生成 / 审查都在后台各自跑，
     这里只是先松开本页的流式回显（否则新的章节内容会被旧任务的输出覆盖），
     切回本章会自动接管继续显示进度。任务中心 / 悬浮条随时能看、能停。 */
  if (genRunning.value) {
    if (genTimer) { clearInterval(genTimer); genTimer = null }
    genRunning.value = false
    genTask.value = null
    genTaskId.value = ''
    toast('本章生成仍在后台进行，可在任务中心查看或停止', 'ok')
  }
  if (showCandidates.value) showCandidates.value = false
  candidates.value = []
  genTarget.value = { scope: 'chapter', start: 0, end: 0, text: '', before: '', after: '' }
  originalText.value = ''
  clearReview()
  selNo.value = Number(c._no) || 0
  // 记住每本书看到哪一章：多本书来回切，回来还是原来的章，审查结论 / 候选也都在
  try { localStorage.setItem('fw.ch.' + store.curBook(), String(selNo.value)) } catch { /* 隐私模式 */ }
  msText.value = ''
  msDirty.value = false
  if (!selNo.value) return
  msLoading.value = true
  try {
    const j: any = await api.getOutput(msPath(selNo.value))
    msText.value = j.content || ''
  } catch { msText.value = '' }   // 没有就没有：空编辑器直接写
  msLoading.value = false
  syncGenTask()                   // 选中章节后同步后端任务状态（接管 / 回显上次结果）
  syncReviewTask()                // 同理：接管后台审查 / 回显本章上次审查结论
}
async function saveMs() {
  if (!selNo.value) return
  msSaving.value = true
  try {
    await api.saveManuscript(store.curBook(), selNo.value, msText.value)
    msDirty.value = false
    toast('正文已保存', 'ok')
    store.loadStats().catch(() => {})
  } catch (e: any) { toast(e.message, 'err') }
  msSaving.value = false
}

/* ---------------- 版本历史（P0）：写前自动留档，可对比 / 回滚 ---------------- */
const histOpen = ref(false)
const histLoading = ref(false)
const histList = ref<HistoryVersion[]>([])
const histCurrent = ref<{ chars: number; preview: string } | null>(null)
/* 弹层内查看：'' = 版本列表；text = 该版全文；diff = 与当前正文的行级对比 */
const histMode = ref<'' | 'text' | 'diff'>('')
const histPick = ref<HistoryVersion | null>(null)
const histTitle = ref('')
const histBody = ref('')
const histBusy = ref(false)

/* 把 unified diff 拆成带类型的行，前端才能给增删行上色（后端只给原始文本） */
const diffLines = computed(() => {
  if (histMode.value !== 'diff' || !histBody.value) return [] as { kind: string; sign: string; text: string }[]
  const out: { kind: string; sign: string; text: string }[] = []
  for (const raw of histBody.value.split('\n')) {
    if (raw.startsWith('+++ ') || raw.startsWith('--- ')) {
      out.push({ kind: 'meta', sign: '', text: raw }); continue
    }
    if (raw.startsWith('@@')) {
      out.push({ kind: 'hunk', sign: '', text: raw }); continue
    }
    if (!raw) {
      out.push({ kind: 'ctx', sign: ' ', text: '' }); continue
    }
    const sign = raw[0]
    out.push({
      kind: sign === '+' ? 'add' : sign === '-' ? 'del' : 'ctx',
      sign,
      text: raw.slice(1),
    })
  }
  return out
})
const diffStat = computed(() => ({
  add: diffLines.value.filter(l => l.kind === 'add').length,
  del: diffLines.value.filter(l => l.kind === 'del').length,
}))

function closeHistory() {
  histOpen.value = false
  histMode.value = ''
  histPick.value = null
}
function backToHistList() {
  histMode.value = ''
  histPick.value = null
}
async function openHistory() {
  if (!selNo.value) return
  histOpen.value = true
  histLoading.value = true
  histMode.value = ''
  histPick.value = null
  try {
    const r = await api.getHistory(store.curBook(), selNo.value)
    histList.value = r.versions || []
    histCurrent.value = r.current
  } catch (e: any) { toast(e.message, 'err') }
  histLoading.value = false
}
async function histViewText(v: HistoryVersion) {
  histPick.value = v
  histMode.value = 'text'
  histTitle.value = `${v.mtime_text} · ${v.chars} 字${v.note ? ' · ' + v.note : ''}`
  histBody.value = ''
  histBusy.value = true
  try {
    const r = await api.getHistoryText(store.curBook(), selNo.value, v.file)
    histBody.value = r.text
  } catch (e: any) {
    toast(e.message, 'err')
    histMode.value = ''
  }
  histBusy.value = false
}
async function histViewDiff(v: HistoryVersion) {
  histPick.value = v
  histMode.value = 'diff'
  histTitle.value = `${v.mtime_text} → 当前正文`
  histBody.value = ''
  histBusy.value = true
  try {
    const r = await api.getHistoryDiff(store.curBook(), selNo.value, v.file)
    histBody.value = r.diff || ''
  } catch (e: any) {
    toast(e.message, 'err')
    histMode.value = ''
  }
  histBusy.value = false
}
async function histRollback(v: HistoryVersion) {
  if (!await confirmBox(
    `回滚到 ${v.mtime_text} 的版本？当前正文会先自动留一份快照（回滚本身也能再撤销）。`,
    { ok: '回滚', danger: true })) return
  histBusy.value = true
  try {
    await api.rollbackHistory(store.curBook(), selNo.value, v.file)
    const j: any = await api.getOutput(msPath(selNo.value)).catch(() => null)
    msText.value = j?.content || ''
    msDirty.value = false
    toast('已回滚', 'ok')
    histMode.value = ''
    histPick.value = null
    await openHistory()           // 刷新列表（回滚前的快照也会出现）
    store.loadStats().catch(() => {})
  } catch (e: any) { toast(e.message, 'err') }
  histBusy.value = false
}

/* ---------------- 敏感词预检（P1）：本地规则秒出，不耗 Token ---------------- */
const scanOpen = ref(false)
const scanLoading = ref(false)
const scanResult = ref<SentinelResult | null>(null)
async function scanChapter() {
  if (!selNo.value) return
  scanOpen.value = true
  scanLoading.value = true
  scanResult.value = null
  try {
    /* 编辑器里有未保存的改动就扫当前文本，否则扫磁盘上的成稿 */
    scanResult.value = msDirty.value || !curMs.value
      ? await api.sentinelScan({ text: msText.value })
      : await api.sentinelScan({ book: store.curBook(), no: selNo.value })
  } catch (e: any) { toast(e.message, 'err'); scanOpen.value = false }
  scanLoading.value = false
}

/* ---------------- 审查 → 改写闭环（P1）：审查结论变成「必须修复」清单 ---------------- */
async function fixFromReview() {
  const n = Number(selNo.value) || 0
  if (!n || genRunning.value || reviewRunning.value) return
  if (!reviewIssues.value.length) { toast('当前没有审查结论：请先「开始审查」', 'err'); return }
  if (!msText.value.trim()) { toast('本章还没有正文，无法改写', 'err'); return }
  if (!await confirmBox(
    '将把上方审查结论作为「必须修复」清单交给 AI 改写本章（生成候选，采纳后才会写入正文），继续？',
    { ok: '开始改写' })) return
  const creds = store.callCreds('expand_rewrite')
  let started: any = null
  try {
    started = await api.expandChapter({
      book: store.curBook(), chapter_no: n, api_key: creds.api_key,
      mode: 'rewrite', fix_from_review: true, text: msText.value,
      style: genStyle.value, count: genCount.value,
      model: creds.model || undefined, base_url: creds.base_url || undefined,
    })
  } catch (e: any) { toast(e.message, 'err'); return }
  genTaskId.value = started?.id || ''
  genUsedMode.value = 'rewrite'
  genMode.value = 'rewrite'
  genScope.value = 'chapter'
  genRunning.value = true
  genError.value = ''
  genStatus.value = ''
  genTask.value = { running: true, book: store.curBook(), chapter_no: n, mode: 'rewrite', multi: true,
    versions: [], recommended: 0, code: null, error: null, stopped: false,
    started_at: Date.now() / 1000, elapsed: 0 }
  originalText.value = msText.value
  msDirty.value = false
  if (genTimer) clearInterval(genTimer)
  genTimer = setInterval(pollGen, 300)
  toast('按审查意见改写已启动：完成后在候选版本里采纳', 'ok')
}

/* 从「设定图谱」/ 任务条等页面跳转过来时带 ?ch=N（定位到该章）、?tab=review（直接展开审查结果），
   都没有就默认第一章 */
const route = useRoute()
let wantCh = Number(route.query.ch || 0) || 0
let wantTab = String(route.query.tab || '')
/* 定位到带过来的章节：已经停在这一章就只切 tab、不重载正文（不打断正在看的编辑） */
async function gotoWantCh() {
  if ((!wantCh && !wantTab) || !chapters.value.length) return   // 书还没载入：等 chapters watcher 再调
  const ch = wantCh, tab = wantTab
  wantCh = 0; wantTab = ''
  const hit = ch ? chapters.value.find(c => Number(c._no) === ch) : null
  if (hit) {
    if (Number(selNo.value) === Number(hit._no)) {
      // 同一章：只把右栏切到「审查结果」并同步任务（结果 / 进行中进度），不动编辑器
      if (tab === 'review') { reviewTab.value = 'review'; syncReviewTask() }
      return
    }
    await selectChapter(hit)
  }
  if (tab === 'review') reviewTab.value = 'review'
}
watch(() => [route.query.ch, route.query.tab], ([ch, tab]) => {
  wantCh = Number(ch || 0) || 0
  wantTab = String(tab || '')
  gotoWantCh()
})
watch(chapters, async () => {
  if (!chapters.value.length) return
  if (wantCh || wantTab) { await gotoWantCh(); if (selNo.value) return }
  if (!selNo.value) {
    // 优先回到这本书上次停留的章节（多本书同时改时不用每次重新点）
    const saved = Number(localStorage.getItem('fw.ch.' + store.curBook()) || 0) || 0
    const hit = saved ? chapters.value.find(c => Number(c._no) === saved) : null
    selectChapter(hit || chapters.value[0])
  }
})
watch(() => store.curBook(), () => {
  if (genTimer) { clearInterval(genTimer); genTimer = null }
  synopsisOpen.value = false
  genRunning.value = false
  genTask.value = null
  showCandidates.value = false; candidates.value = []
  clearReview()
  selNo.value = 0; msText.value = ''; msDirty.value = false
  // 换书时 URL 上的定位参数要重新生效（任务条跳到「同章号的另一本书」时 query 不变，
  // 只有 curBook 变了，这里补一次，chapters 重载后 gotoWantCh 才能选中目标章）
  wantCh = Number(route.query.ch || 0) || 0
  wantTab = String(route.query.tab || '')
})


/* 内容模块顺序：先实体（势力 / 角色 / 道具），再大纲与章节，图谱收尾 */
const moduleLinks = [
  { icon: 'movie', color: 'purple', t: '势力表', page: '/factions', n: () => (meta.value?.n_factions || 0) + '', copy: true },
  { icon: 'pen', color: 'green', t: '角色卡', page: '/characters', n: () => (meta.value?.n_cards || 0) + '', copy: true },
  { icon: 'shield', color: 'teal', t: '道具功法', page: '/items', n: () => (meta.value?.n_items || 0) + '', copy: true },
  { icon: 'list', color: 'blue', t: '作品大纲', page: '/outline', n: () => '', copy: true },
  { icon: 'file', color: 'orange', t: '章节概括', page: '/chapters', n: () => (meta.value?.n_chapters || 0) + ' 章', copy: false },
  { icon: 'graph', color: 'purple', t: '设定图谱', page: '/storymap', n: () => '', copy: false },
]

/* 模块内容复制到剪贴板（纯文本） */
async function copyModule(t: string) {
  const lines: string[] = []
  if (t === '作品大纲') {
    const labels = Object.fromEntries(schema.value?.sb_fields || [])
    for (const [k, v] of Object.entries(fields.value)) {
      if (String(v || '').trim()) lines.push((labels[k] || k) + '：' + v)
    }
  } else if (t === '角色卡' || t === '势力表' || t === '道具功法') {
    const list = t === '角色卡' ? cards.value : t === '势力表' ? factions.value : items.value
    const labels = Object.fromEntries(
      (t === '角色卡' ? schema.value?.card_fields
        : t === '势力表' ? schema.value?.faction_fields
          : schema.value?.item_fields) || [])
    for (const it of list) {
      lines.push('【' + (it.name || '未命名') + '】')
      for (const [k, lb] of Object.entries(labels)) {
        if (k === 'name') continue
        if (String(it[k] || '').trim()) lines.push(lb + '：' + it[k])
      }
      lines.push('')
    }
  }
  const text = lines.join('\n').trim()
  if (!text) { toast('暂无可复制的内容', 'err'); return }
  try {
    await navigator.clipboard.writeText(text)
    toast('已复制到剪贴板', 'ok')
  } catch (e) {
    toast('复制失败，请检查浏览器权限', 'err')
  }
}

onMounted(() => {
  store.loadStats().catch(() => {})
  api.getSchema().then(s => schema.value = s).catch(() => {})
})
</script>

<template>
  <div v-if="!state.books.length" class="card">
    <EmptyBox title="还没有作品" desc="点击左侧「新建作品」，上传全本或大纲开始创作" />
  </div>
  <div v-else-if="!meta" class="card"><EmptyBox title="请在左侧选择一部作品" /></div>
  <template v-else>
    <!-- 书籍信息区 -->
    <div class="card overview-card">
      <div class="ov-cover" @click="fileRef?.click()" title="点击上传 / 更换封面">
        <img v-if="meta.has_cover" :src="api.coverUrl(meta.name, coverVer)" alt="封面" />
        <div v-else class="ov-cover-ph">
          <Icon name="cloud" :size="26" />
          <span>{{ meta.title || meta.name }}</span>
        </div>
        <div class="ov-cover-mask"><Icon name="upload" :size="16" /> 更换封面</div>
      </div>
      <input ref="fileRef" type="file" accept="image/png,image/jpeg,image/webp" hidden
             @change="e => { pickCover((e.target as HTMLInputElement).files?.[0]); (e.target as HTMLInputElement).value = '' }" />

      <div class="ov-meta">
        <div class="ov-title" v-if="!editBookTitle">
          <span>{{ meta.title || meta.name }}</span>
          <button class="icon-btn" title="修改作品名" @click="startBookTitle"><Icon name="edit" :size="14" /></button>
        </div>
        <div class="ov-title" v-else>
          <input ref="bookTitleRef" class="input" v-model="bookTitleDraft" maxlength="80"
                 style="width:320px" @keyup.enter="saveBookTitle" @keyup.esc="editBookTitle = false" />
          <button class="btn sm" @click="saveBookTitle">保存</button>
          <button class="btn sm ghost" @click="editBookTitle = false">取消</button>
        </div>
        <div class="ov-rows">
          <div class="ov-row">
            <span class="k">作品状态</span>
            <div class="ov-status">
              <label v-for="s in statusOptions" :key="s" class="ov-radio">
                <input type="radio" name="book-status" :value="s"
                       :checked="curStatus === s"
                       @change="setStatus(s)" /> {{ s }}
              </label>
              <button v-if="meta.has_cover" class="link-btn red" style="margin-left:auto" @click="rmCover">移除封面</button>
            </div>
          </div>
          <div class="ov-row"><span class="k">作者</span>
            <span>{{ meta.author || '未填写（生成封面时填写，会自动补「著」）' }}</span></div>
          <div class="ov-row"><span class="k">最新章节</span>
            <span>{{ meta.last_chapter_title ? `第 ${meta.last_chapter_no || ''} 章 ${meta.last_chapter_title}` : '暂无章节' }}</span></div>
          <div class="ov-row"><span class="k">更新时间</span><span>{{ meta.mtime_text }}</span></div>
          <div class="ov-row"><span class="k">累计字数</span>
            <span>{{ fmtNum(meta.manuscript_chars || 0) }} 字 · {{ meta.n_chapters || 0 }} 章 · 成稿 {{ meta.n_manuscripts || 0 }} 章</span></div>
          <div class="ov-row col">
            <span class="k">作品简介</span>
            <p v-if="synopsis" class="ov-intro" :class="{ clamp: !synopsisOpen }">{{ synopsis }}</p>
            <a v-else class="ov-intro-empty link-btn" @click="router.push('/outline')">
              暂无简介，去「作品大纲」填写 →</a>
            <button v-if="synopsis && synopsis.length > 90" class="link-btn ov-more"
                    @click="synopsisOpen = !synopsisOpen">{{ synopsisOpen ? '收起简介' : '展开简介' }}</button>
          </div>
          <div class="ov-row ov-acts">
            <button class="btn sm" title="AI 出底图并排版「书名 + 作者 + 著」，按平台尺寸输出"
                    @click="coverModal = true"><Icon name="edit" :size="13" /> AI 生成封面</button>
            <button class="btn sm ghost" :disabled="!meta.has_cover" title="下载封面源文件"
                    @click="dlCover"><Icon name="download" :size="13" /> 下载封面</button>
            <!-- 作品级检查：点开看当前 / 历史报告，弹窗里可再次执行；任务本身不跳转页面 -->
            <button v-if="isFinished" class="btn sm ghost"
                    :disabled="!!batchJob || batchStarting"
                    :title="batchJob ? '全书体检进行中：进度看右下角任务条'
                      : '查看当前 / 历史体检报告，可再次体检（后台跑，不离开本页）'"
                    @click="openReport('batch')">
              <Icon name="shield" :size="13" /> {{ batchJob || batchStarting ? '体检中…' : '全书体检' }}
            </button>
            <button v-if="canPrecheck" class="btn sm ghost"
                    :disabled="!!signingJob || signingStarting"
                    :title="signingJob ? '签约预审进行中：进度看右下角任务条'
                      : '查看当前 / 历史预审报告，可再次预审（后台跑，不离开本页）'"
                    @click="openReport('signing')">
              <Icon name="flag" :size="13" /> {{ signingJob || signingStarting ? '预审中…' : '签约预审' }}
            </button>
          </div>
        </div>
      </div>

      <div class="ov-side">
        <div class="ov-side-title">内容模块</div>
        <div v-for="m in moduleLinks" :key="m.t" class="ov-mod-link" @click="router.push(m.page)">
          <span class="module-ico sm" :class="m.color"><Icon :name="m.icon" :size="15" /></span>
          <span class="ov-mod-name">{{ m.t }}</span>
          <span class="ov-mod-n">{{ m.n() }}</span>
          <span class="head-acts">
            <button v-if="m.copy" class="icon-btn" :title="'复制' + m.t + '到剪贴板'"
                    @click.stop="copyModule(m.t)"><Icon name="copy" :size="14" /></button>
          </span>
        </div>
      </div>
    </div>

    <!-- 章节工作台：树 / 正文 / 概括（全屏时整卡铺满视窗） -->
    <div class="card" :class="{ 'ws-full': wsFull }" style="margin-top:16px">
      <div class="card-head">
        <div class="card-title">目录<span class="sub">{{ chapters.length }} 章 · 点选章节，中间直接阅读 / 书写正文</span></div>
        <span class="spacer"></span>
        <button class="icon-btn" :title="wsFull ? '退出全屏（Esc）' : '沉浸式全屏写作'" @click="toggleWsFull">
          <Icon :name="wsFull ? 'shrink' : 'expand'" :size="16" />
        </button>
      </div>

      <EmptyBox v-if="!chapters.length" title="暂无章节" desc="完成拆解后自动生成目录，也可在「章节概括」手动添加" />
      <div v-else class="ws">
        <!-- 左：章节树（Splitter 可拖宽 / 可收起） -->
        <div class="ws-tree" v-show="!treeOff" :style="{ flex: 'none', width: treeW + 'px' }">
          <div v-for="g in tree" :key="g.name" class="tree-group">
            <div class="tree-vol" v-if="tree.length > 1 || g.name !== '全部章节'">{{ g.name }}</div>
            <button v-for="c in g.items" :key="String(c._no) + String(c.title)" class="tree-ch"
                    :class="{ on: c._no === selNo }" @click="selectChapter(c)" :title="chLabel(c)">
              <span class="tc-dot" :class="{ g: chInfo(c) }"></span>
              <span class="tc-name">{{ chLabel(c) }}</span>
            </button>
          </div>
        </div>

        <div class="ws-split" title="拖拽调宽 · 拖到头或双击收起" @pointerdown="startDrag('tree', $event)" @dblclick="toggleTree">
          <button class="split-btn" :title="treeOff ? '展开目录' : '收起目录'" @click.stop="toggleTree">
            <Icon :name="treeOff ? 'right' : 'left'" :size="12" />
          </button>
        </div>

        <!-- 中：正文（可编辑） -->
        <div class="ws-main">
          <div class="ws-main-head">
            <template v-if="cur">
              <b>第 {{ cur._no }} 章</b>
              <template v-if="editingTitle">
                <input ref="titleInput" v-model="titleDraft" class="title-edit"
                       placeholder="输入章节名" @keydown.enter="($event.target as HTMLInputElement).blur()"
                       @keydown.esc="editingTitle = false" @blur="commitTitle" />
              </template>
              <template v-else>
                <span>{{ chName(cur) || '未命名' }}</span>
                <button class="icon-btn sm" title="编辑章节名" @click="startEditTitle"><Icon name="edit" :size="13" /></button>
              </template>
              <span class="ms-copy-grp">
                <span v-if="curCopiedAt" class="tag green" :title="'复制于 ' + curCopiedAt">已复制 · {{ curCopiedAt }}</span>
                <button class="btn sm ghost" :disabled="!selNo || !msText.trim()" title="复制正文到剪贴板"
                        @click="copyMs"><Icon name="copy" :size="13" /> 复制</button>
              </span>
            </template>
            <b v-else>选择左侧章节</b>
            <span class="spacer"></span>
            <template v-if="genRunning">
              <button class="btn sm" disabled><Icon name="pen" :size="13" /> {{ genModeLabel[genMode] }}中…</button>
              <button class="btn sm danger-ghost" @click="stopGen">停止</button>
            </template>
            <template v-else>
              <div style="width:118px">
                <SelectBox compact :model-value="genMode" :search-from="99"
                           :options="[{label:'按大纲生成',value:'outline'},{label:'续写',value:'continue'},{label:'扩写',value:'expand'},{label:'改写',value:'rewrite'},{label:'润色',value:'polish'}]"
                           @update:model-value="setGenMode" />
              </div>
              <div style="width:100px">
                <SelectBox compact :model-value="genStyle" :search-from="99"
                           :options="['沿用设定', ...VOICE_PRESETS]"
                           @update:model-value="v => genStyle = v" />
              </div>
              <div v-if="genMode !== 'outline'" style="width:78px">
                <SelectBox compact :model-value="String(genCount)" :search-from="99"
                           :options="[{label:'2 版',value:'2'},{label:'3 版',value:'3'},{label:'5 版',value:'5'}]"
                           @update:model-value="setGenCount" />
              </div>
              <button class="btn sm" :disabled="!selNo || genBusy" @click="genChapter(selNo)"><Icon name="pen" :size="13" /> 生成</button>
              <button v-if="genScope === 'chapter' && candidates.length && genMode !== 'outline'" class="btn sm ghost"
                      @click="showCandidates = true">查看 {{ candidates.length }} 个候选</button>
            </template>
            <button class="btn sm ghost" :disabled="!selNo || genBusy || reviewRunning" @click="startReview(selNo)"><Icon name="shield" :size="13" /> 正文审查</button>
          </div>
          <!-- 正文任务状态条：跨页面保持，离开本章也看得到进展 / 上次失败原因 -->
          <div v-if="genTask && genTask.running" class="ws-task">
            <span class="wst-dot"></span>
            <span class="wst-txt">
              <b>正文任务进行中</b>
              第 {{ genTask.chapter_no }} 章 · {{ genTask.name || modeLabel(genTask.mode) }}
              <template v-if="genScope === 'selection'">（只生成候选，采纳后才改动正文）</template>
              <template v-else-if="Number(genTask.chapter_no) !== selNo">（可继续浏览其他章，任务不受影响）</template>
            </span>
            <span class="wst-meta">已用 {{ Math.round(Number(genTask.elapsed) || 0) }}s</span>
            <button class="btn sm danger-ghost" @click="stopGen">停止</button>
          </div>
          <div v-else-if="genTask && genTask.error" class="ws-task err">
            <span class="wst-dot"></span>
            <span class="wst-txt">
              <b>上次生成失败</b>
              第 {{ genTask.chapter_no }} 章 · {{ genTask.name || modeLabel(genTask.mode) }}：{{ genTask.error }}
            </span>
            <button class="icon-btn sm" title="忽略" @click="genTask = null"><Icon name="close" :size="13" /></button>
          </div>
          <!-- 审查在后台独立线程里跑：不在「审查结果」tab 时也要有可见的进度与释放入口 -->
          <div v-if="reviewRunning && reviewTab !== 'review'" class="ws-task">
            <span class="wst-dot"></span>
            <span class="wst-txt">
              <b>第 {{ selNo }} 章正文审查中</b>
              可以继续切章 / 做别的（进度在右栏「审查结果」，任务中心也能看）
            </span>
            <button class="btn sm ghost" @click="reviewTab = 'review'">看进度</button>
            <button class="btn sm danger-ghost" @click="releaseReview">释放</button>
          </div>
          <div v-if="!selNo" class="ws-empty">从左侧选择一章开始创作</div>
          <div v-else-if="msLoading" class="ws-empty">正文读取中…</div>
          <div v-else-if="genIsMulti && genRunning && genScope === 'chapter'" class="ws-genstatus">
            <div class="gs-title"><Icon name="pen" :size="14" /> AI 正在生成 {{ candidates.length || 3 }} 个候选方向…</div>
            <pre class="gs-log">{{ genStatus || '准备中…' }}</pre>
          </div>
          <div v-else class="ws-editor-wrap">
            <!-- 审查问题高亮层：与正文逐字对齐，只画底色，不挡鼠标也不参与选中 -->
            <div v-if="hlOn" ref="hlBox" class="ws-hl" aria-hidden="true">
              <div ref="hlInner" class="ws-hl-inner" v-html="hlHtml"></div>
            </div>
            <textarea ref="edEl" v-model="msText" class="ws-editor" spellcheck="false"
                      :disabled="genRunning" @input="msDirty = true" @contextmenu="onContextMenu"
                      @scroll="syncHl"
                      :placeholder="genRunning ? 'AI 正在生成本章正文…'
                        : (curMs ? '' : '本章还没有正文，可以直接在此书写，或点击「正文生成」让 AI 扩写')"></textarea>
          </div>
          <div class="ws-main-foot" v-if="selNo">
            <span>{{ msText.length }} 字<template v-if="genRunning"> · AI 生成中，正文暂不可编辑</template><template v-if="curMs"> · 成稿 {{ fmtNum(curMs.chars) }} 字 · {{ curMs.mtime }}</template></span>
            <span class="spacer"></span>
            <div class="ws-foot-acts">
              <button class="btn sm ghost" :disabled="genRunning" title="本章正文的版本历史：每次覆盖前自动留档，可对比 / 回滚"
                      @click="openHistory"><Icon name="list" :size="13" /> 历史</button>
              <button class="btn sm" :disabled="!msDirty || msSaving || genRunning" @click="saveMs">
                <Icon name="check" :size="13" /> {{ msSaving ? '保存中…' : '保存正文' }}</button>
            </div>
          </div>
        </div>

        <!-- 候选版本弹层：续写/扩写/改写生成三版，推荐后采纳写入 -->
        <Teleport to="body">
          <div v-if="ctxMenu" class="ctx-menu" :style="{ left: ctxMenu.x + 'px', top: ctxMenu.y + 'px' }"
               @click.stop>
            <div class="ctx-hint">对选中文字操作（生成三版候选）</div>
            <button class="ctx-item" @click="selGen('continue')"><Icon name="pen" :size="14" /> 续写选区</button>
            <button class="ctx-item" @click="selGen('expand')"><Icon name="pen" :size="14" /> 扩写选区</button>
            <button class="ctx-item" @click="selGen('rewrite')"><Icon name="pen" :size="14" /> 改写选区</button>
            <button class="ctx-item" @click="selGen('polish')"><Icon name="pen" :size="14" /> 润色选区</button>
          </div>
          <div v-if="showCandidates" class="cand-mask" @click.self="closeCandidates">
            <div class="cand-modal">
              <div class="cand-head">
                <div class="cand-title">AI {{ genModeLabel[genMode] }} · {{ candidates.length }} 个候选方向<small>选择一版「采纳」写入正文，其余可关闭后重生成</small></div>
                <button class="icon-btn" @click="closeCandidates" title="关闭"><Icon name="close" :size="16" /></button>
              </div>
              <div class="cand-list cols">
                <div v-for="(v, i) in candidates" :key="i" class="cand-card"
                     :class="{ rec: i === recIndex }">
                  <div class="cand-card-head">
                    <span class="cand-badge" :class="{ rec: i === recIndex }">{{ i === recIndex ? '推荐' : '方向 ' + (i + 1) }}</span>
                    <span class="cand-note">{{ v.note }}</span>
                    <span class="cand-chars">{{ v.chars }} 字</span>
                  </div>
                  <div class="cand-body"><pre>{{ v.text }}</pre></div>
                  <div class="cand-acts">
                    <button class="btn sm" @click="adoptVersion(i)"><Icon name="check" :size="13" /> 采纳并写入</button>
                    <button class="btn sm ghost" @click="copyVersion(i)"><Icon name="copy" :size="13" /> 复制</button>
                  </div>
                </div>
              </div>
              <div class="cand-foot">
                <span class="sub">采纳后可在编辑器继续润色，再点「保存正文」落盘</span>
                <button class="btn sm ghost" @click="closeCandidates">关闭</button>
              </div>
            </div>
          </div>

          <!-- 版本历史弹层：写前留档 / 行级对比 / 一键回滚 -->
          <div v-if="histOpen" class="cand-mask" @click.self="closeHistory">
            <div class="cand-modal hist-modal">
              <div class="cand-head">
                <div class="cand-title">第 {{ selNo }} 章 · 版本历史
                  <small>每次 AI 生成 / 手工保存覆盖正文前自动留档（保留最近 30 份）</small></div>
                <button class="icon-btn" @click="closeHistory" title="关闭"><Icon name="close" :size="16" /></button>
              </div>
              <template v-if="histMode">
                <div class="hist-detail-head">
                  <button class="btn sm ghost" @click="backToHistList"><Icon name="left" :size="12" /> 返回列表</button>
                  <div class="hist-title">{{ histTitle }}</div>
                  <span v-if="histMode === 'diff' && !histBusy" class="hist-stat">
                    <span class="add">+{{ diffStat.add }}</span>
                    <span class="del">-{{ diffStat.del }}</span>
                  </span>
                  <button class="btn sm danger-ghost" :disabled="histBusy || !histPick"
                          @click="histPick && histRollback(histPick)">回滚到此版本</button>
                </div>
                <div class="cand-list hist-detail-body">
                  <div v-if="histBusy" class="ws-side-empty">读取中…</div>
                  <template v-else-if="histMode === 'diff'">
                    <div v-if="!diffLines.length" class="ws-side-empty">与当前正文一致，没有差异</div>
                    <template v-else>
                      <div class="diff-legend">
                        <span class="lg del">- 历史版本</span>
                        <span class="lg add">+ 当前正文</span>
                        <span class="diff-hint">仅显示有改动的段落（上下各 2 行上下文）</span>
                      </div>
                      <div class="diff-view">
                        <div v-for="(l, i) in diffLines" :key="i" class="diff-line" :class="l.kind">
                          <span class="diff-sign">{{ l.sign || ' ' }}</span>
                          <span class="diff-text">{{ l.text }}</span>
                        </div>
                      </div>
                    </template>
                  </template>
                  <pre v-else class="hist-body">{{ histBody }}</pre>
                </div>
              </template>
              <div v-else class="cand-list">
                <div v-if="histLoading" class="ws-side-empty">读取中…</div>
                <template v-else>
                  <div v-if="histCurrent" class="hist-cur">
                    当前正文：{{ histCurrent.chars }} 字 · {{ histCurrent.preview || '（空）' }}…
                  </div>
                  <div v-if="!histList.length" class="ws-side-empty">
                    还没有历史版本：正文第一次被 AI 生成 / 保存覆盖时会自动留档
                  </div>
                  <div v-for="v in histList" :key="v.file" class="hist-item">
                    <div class="hist-meta">
                      <b>{{ v.mtime_text }}</b>
                      <span class="tag gray">{{ v.chars }} 字</span>
                      <span v-if="v.note" class="tag blue">{{ v.note }}</span>
                      <div class="hist-preview">{{ v.preview }}…</div>
                    </div>
                    <div class="hist-acts">
                      <button class="link-btn" :disabled="histBusy" @click="histViewText(v)">查看</button>
                      <button class="link-btn" :disabled="histBusy" @click="histViewDiff(v)">对比当前</button>
                      <button class="link-btn red" :disabled="histBusy" @click="histRollback(v)">回滚</button>
                    </div>
                  </div>
                </template>
              </div>
            </div>
          </div>

          <!-- 敏感词预检弹层：本地规则，秒出不耗 Token -->
          <div v-if="scanOpen" class="cand-mask" @click.self="scanOpen = false">
            <div class="cand-modal">
              <div class="cand-head">
                <div class="cand-title">第 {{ selNo }} 章 · 敏感词预检
                  <small>本地词表规则扫描（config/sensitive_words.txt 可自增），不调用模型</small></div>
                <button class="icon-btn" @click="scanOpen = false" title="关闭"><Icon name="close" :size="16" /></button>
              </div>
              <div class="cand-list">
                <div v-if="scanLoading" class="ws-side-empty">扫描中…</div>
                <template v-else-if="scanResult">
                  <div class="rev-summary" style="margin-bottom:10px">
                    <span class="tag gray">共 {{ scanResult.total }} 处命中</span>
                    <span class="tag" :class="scanResult.n_high ? 'red' : 'green'">高严重度 {{ scanResult.n_high }}</span>
                    <span v-if="scanResult.chars" class="tag gray">{{ scanResult.chars }} 字</span>
                  </div>
                  <div v-if="!scanResult.hits.length" class="ws-side-empty">未命中任何敏感词 🎉</div>
                  <div v-for="h in scanResult.hits" :key="h.word" class="hist-item">
                    <div class="hist-meta">
                      <b>{{ h.word }}</b>
                      <span class="sev" :class="h.level === '高' ? 'hi' : h.level === '中' ? 'mid' : 'lo'">{{ h.level }}</span>
                      <span class="tag gray">{{ h.category }}</span>
                      <span class="tag orange">{{ h.count }} 处</span>
                      <div class="hist-preview" v-for="(s, i) in (h.samples || []).slice(0, 3)" :key="i">…{{ s.context }}…</div>
                    </div>
                  </div>
                </template>
              </div>
            </div>
          </div>
        </Teleport>

        <!-- 右：本章概括 / 审查结果（页内，不跳转，Splitter 可拖宽 / 可收起） -->
        <div v-if="cur" class="ws-split" title="拖拽调宽 · 拖到头或双击收起"
             @pointerdown="startDrag('side', $event)" @dblclick="toggleSide">
          <button class="split-btn" :title="sideOff ? '展开侧栏' : '收起侧栏'" @click.stop="toggleSide">
            <Icon :name="sideOff ? 'left' : 'right'" :size="12" />
          </button>
        </div>
        <div class="ws-side" v-if="cur" v-show="!sideOff" :style="{ flex: 'none', width: sideW + 'px' }">
          <div class="ws-side-tabs">
            <button :class="{ active: reviewTab === 'summary' }" @click="reviewTab = 'summary'">本章概括</button>
            <button :class="{ active: reviewTab === 'review' }" @click="reviewTab = 'review'">
              审查结果<span v-if="reviewIssues.length" class="tab-badge">{{ reviewIssues.length }}</span>
            </button>
            <button :class="{ active: reviewTab === 'sel' }" @click="reviewTab = 'sel'">
              选区候选<span v-if="genScope === 'selection' && candidates.length" class="tab-badge">{{ candidates.length }}</span>
            </button>
          </div>
          <div class="ws-side-body">
            <template v-if="reviewTab === 'summary'">
              <div class="cf cf-block"><span class="k">摘要</span><p>{{ cur.summary || '—' }}</p></div>
              <div class="cf" v-if="(cur.points || []).length"><span class="k">事件</span>
                <ol class="pts"><li v-for="(p, j) in cur.points" :key="j">{{ p }}</li></ol></div>
              <div class="cf" v-if="cur.conflict"><span class="k">核心冲突</span><span>{{ cur.conflict }}</span></div>
              <div class="cf" v-if="cur.emotion || cur.tension">
                <span class="k">情绪流</span>
                <span class="flow-wrap">
                  <span v-if="cur.emotion" class="flow-emo">
                    <template v-for="(e, j) in String(cur.emotion).split('→')" :key="j">
                      <span v-if="j" class="flow-arrow">→</span><span class="emo-chip">{{ e }}</span>
                    </template>
                  </span>
                  <span v-if="cur.tension" class="flow-ten" :title="'情绪峰值 ' + cur.tension + '/10'">
                    <span class="ten-bar"><i :style="{ width: Math.min(100, cur.tension * 10) + '%' }"></i></span>
                    <span class="ten-num">{{ cur.tension }}/10</span>
                  </span>
                </span>
              </div>
              <div class="cf" v-if="cur.payoff"><span class="k">本章兑现</span><span>{{ cur.payoff }}</span></div>
              <div class="cf" v-if="cur.setup"><span class="k">本章铺垫</span><span>{{ cur.setup }}</span></div>
              <div class="cf" v-if="cur.hook_type || cur.hook"><span class="k">章末钩子</span>
                <span class="hook-wrap">
                  <span v-if="cur.hook_type" class="hook-chip">{{ cur.hook_type }}</span>
                  <span v-if="cur.hook">{{ cur.hook }}</span>
                  <span v-if="!cur.hook_type && !cur.hook">—</span>
                </span>
              </div>
              <div class="cf"><span class="k">地点</span><span>{{ cur.scene || '—' }}</span></div>
              <div class="cf"><span class="k">出场人物</span>
                <span class="tags" v-if="(cur.roles || []).length"><span v-for="r in cur.roles" :key="r" class="tag" :class="genderTag(genderMap[r])" title="出场角色"><Icon name="user" :size="11" />{{ r }}</span></span>
                <span v-else>—</span></div>
              <div class="cf"><span class="k">入场势力</span>
                <span class="tags" v-if="(cur.factions || []).length"><span v-for="f in cur.factions" :key="f" class="tag"
                  :class="stanceTag(stanceMap[f])"
                  :title="'涉及势力｜阵营：' + (campNote(f) || '未标注') + '｜立场：' + (stanceNote(stanceMap[f]) || '未标注')"><Icon name="flag" :size="11" />{{ f }}</span></span>
                <span v-else>—</span></div>
            </template>
            <template v-else-if="reviewTab === 'review'">
              <div class="rev-actions">
                <button class="btn sm" :disabled="!selNo || genRunning || reviewRunning" @click="startReview(selNo)">
                  <Icon name="shield" :size="13" /> {{ reviewRunning ? '审查中…' : '开始审查' }}</button>
                <button v-if="reviewRunning" class="btn sm danger-ghost" @click="stopReview"
                        title="停下当前这一步后退出">停止</button>
                <button v-if="reviewRunning" class="btn sm ghost" @click="releaseReview"
                        title="立即解锁：不等当前这一步跑完，马上可切章 / 发起别的任务">释放</button>
                <button v-if="!reviewRunning && reviewIssues.length" class="btn sm" :disabled="genRunning"
                        title="把审查结论作为「必须修复」清单交给 AI 改写本章（候选确认后才写入正文）"
                        @click="fixFromReview"><Icon name="pen" :size="13" /> 按审查意见改写</button>
                <button v-if="!reviewRunning" class="btn sm ghost" :disabled="!selNo || genRunning"
                        title="本地敏感词规则扫描：秒出结果，不耗 Token（词表在 config/sensitive_words.txt 可自增）"
                        @click="scanChapter"><Icon name="search" :size="13" /> 敏感词预检</button>
              </div>
              <div v-if="reviewRunning" class="rev-prog">
                <div v-for="(l, i) in reviewLines" :key="i" class="rev-line">{{ l }}</div>
              </div>
              <div v-else-if="reviewErr" class="rev-err">{{ reviewErr }}</div>
              <div v-else-if="!reviewResult" class="ws-side-empty">点击「开始审查」对本章做只诊断不改写的体检，结果在此罗列全部问题</div>
              <template v-else>
                <div class="rev-summary">
                  <span class="tag gray">{{ reviewResult.meta?.chars || 0 }} 字</span>
                  <span v-if="reviewResult.theme" class="tag"
                        :class="(reviewResult.theme.level === '无' || reviewResult.theme.level === '低') ? 'green' : 'orange'">主题偏离：{{ reviewResult.theme.level }}</span>
                  <span v-if="reviewResult.risk" class="tag"
                        :class="(reviewResult.risk.n_high || 0) ? 'red' : (reviewResult.risk.n_risk || 0) ? 'orange' : 'green'">风险 {{ reviewResult.risk.n_high || 0 }}高/{{ reviewResult.risk.n_risk || 0 }}</span>
                  <span v-if="reviewIssues.length" class="tag orange">问题 {{ reviewIssues.length }}</span>
                  <span v-else class="tag green">未发现问题</span>
                  <span v-if="adviceCount" class="tag green">正/反建议 {{ adviceCount }} 组</span>
                </div>
                <div v-if="reviewResult.theme?.summary" class="rev-theme">主题判断：{{ reviewResult.theme.summary }}</div>
                <div v-if="reviewStale" class="rev-stale">
                  正文在审查后又改动过，问题位置可能对不上，建议重新审查
                  <button class="btn sm" :disabled="reviewRunning" @click="startReview(selNo)">重新审查</button>
                </div>
                <div v-for="(it, i) in reviewIssues" :key="i" class="rev-issue"
                     :class="{ on: curIssue === i, locatable: spanByIssue.has(i) }"
                     :title="spanByIssue.has(i) ? '点击跳到正文对应位置并高亮' : (it.line ? `没有原文片段，约在第 ${it.line} 行` : '没有可定位的原文片段')"
                     @click="issueClick(i)">
                  <div class="rev-issue-head">
                    <span class="tag blue">{{ it.type_label || it.type }}</span>
                    <span v-if="it.severity" class="sev" :class="sevCls(it.severity)">{{ it.severity }}</span>
                    <span class="rev-issue-title">{{ it.title }}</span>
                    <span v-if="it.line" class="rev-line-no">第 {{ it.line }} 行</span>
                  </div>
                  <div v-if="it.quote" class="rev-quote">「{{ it.quote }}」</div>
                  <div v-if="it.fix" class="rev-suggest"><b>改法：</b>{{ it.fix }}</div>
                  <div v-if="it.suggest" class="rev-suggest"><b>修正：</b>{{ it.suggest }}</div>
                  <div v-if="it.reason" class="rev-reason">{{ it.reason }}</div>
                  <div v-if="it.advice && (it.advice.positive || it.advice.negative)" class="rev-advice">
                    <div v-if="it.advice.positive" class="rev-adv pos">
                      <b>正向建议</b><span>{{ it.advice.positive }}</span></div>
                    <div v-if="it.advice.negative" class="rev-adv neg">
                      <b>反向建议</b><span>{{ it.advice.negative }}</span></div>
                  </div>
                  <div class="rev-loc">
                    <template v-if="spanByIssue.has(i)">
                      <Icon name="search" :size="11" /> 定位原文
                    </template>
                    <template v-else>无原文片段<span v-if="it.line"> · 约在第 {{ it.line }} 行</span></template>
                  </div>
                </div>
                <div v-if="reviewIssues.length && !adviceCount" class="rev-skip">本次没有正向 / 反向建议：这一步要过模型，未配置 API Key 或未勾选「Top 问题建议生成」时会跳过（见下方跳过说明）</div>
                <div v-for="s in (reviewResult.skipped || [])" :key="s.label" class="rev-skip">跳过：{{ s.label }}（{{ s.reason }}）</div>
              </template>
            </template>
            <!-- 选区候选：右键对选中文字生成后，三版候选固定列在这里供采纳 -->
            <template v-else-if="reviewTab === 'sel'">
              <template v-if="genScope === 'selection' && candidates.length">
                <!-- 选区偏移只在本页有效：切章 / 刷新后 genTarget 归零，此时候选只能复制，不能落笔 -->
                <div class="sel-head">
                  <span class="tag blue">{{ modeLabel(genUsedMode) }}选区</span>
                  <span v-if="genTarget.scope === 'selection'" class="sel-src link"
                        :title="'原选区：' + genTarget.text + '（点击在正文中定位）'"
                        @click="locateSelTarget">{{ genTarget.text }}</span>
                  <span v-else class="sel-src">原选区（已失效）</span>
                </div>
                <div v-if="!selOffsetOk" class="sel-hint">
                  选区位置已失效（正文改过，或这次是在别的章节生成的）：候选可复制，如需替换正文请重新选中后再生成
                </div>
                <div v-for="(v, i) in candidates" :key="i" class="sel-cand" :class="{ rec: i === recIndex }">
                  <div class="sel-cand-head">
                    <span class="tag" :class="i === recIndex ? 'green' : 'gray'">
                      {{ i + 1 }}{{ i === recIndex ? ' · 推荐' : '' }}</span>
                    <span class="sel-note" :title="v.note">{{ v.note }}</span>
                    <span class="sel-chars">{{ v.chars }} 字</span>
                  </div>
                  <pre class="sel-text">{{ v.text }}</pre>
                  <div class="sel-acts">
                    <button class="btn sm" :disabled="!selOffsetOk"
                            @click="adoptVersion(i)"><Icon name="check" :size="13" /> 采纳</button>
                    <button class="btn sm ghost" @click="copyVersion(i)"><Icon name="copy" :size="13" /> 复制</button>
                  </div>
                </div>
                <div v-if="selOffsetOk" class="sel-hint">采纳会{{ genUsedMode === 'continue' ? '插入选区之后' : '整段替换原选区' }}，之后可继续编辑并「保存正文」落盘</div>
              </template>
              <div v-else class="ws-side-empty">在正文中选中一段文字 → 右键「续写 / 扩写 / 改写 / 润色选区」，AI 会结合选区前后文生成候选，列在这里供采纳</div>
            </template>
          </div>
        </div>
      </div>
    </div>

    <!-- 全书体检 / 签约预审：当前报告 + 历史报告 + 再次执行（不跳转页面） -->
    <Modal v-model:open="reportOpen" wide
           :title="(meta.title || meta.name) + ' · ' + reportMeta.title + '报告'">
      <div class="rp">
        <div class="rp-hist">
          <div class="rp-hist-head">历史报告<span class="rp-count">{{ reportHistory.length }}</span></div>
          <div v-if="reportLoading && !reportHistory.length" class="hint">读取中…</div>
          <div v-else-if="!reportHistory.length" class="hint">
            暂无报告：点下方「{{ reportMeta.first }}」跑一次，之后每次都会留档</div>
          <button v-for="(h, i) in reportHistory" :key="h.file" class="rp-hist-item"
                  :class="{ on: h.file === reportFile }" @click="selectReport(h.file)">
            <span class="rp-hist-time">{{ h.created_at }}<i v-if="i === 0">最新</i></span>
            <span v-if="reportKind === 'batch'">
              问题 {{ h.total_issues || 0 }} · 高 {{ h.total_high || 0 }} ·
              {{ h.n_done || 0 }}/{{ h.n_chapters || 0 }} 章{{ h.incremental ? ' · 增量' : ' · 全量' }}
            </span>
            <span v-else>{{ h.verdict || '—' }} · 前 {{ h.window_chapters || 0 }} 章 /
              {{ fmtNum(h.chars || 0) }} 字 · 问题 {{ h.n_issues || 0 }}</span>
          </button>
        </div>

        <div class="rp-detail">
          <div v-if="reportFetching" class="hint">读取报告…</div>
          <template v-else-if="batchDetail">
            <div class="rp-tags">
              <span class="tag blue">{{ batchDetail.created_at }}</span>
              <span class="tag gray">{{ batchDetail.incremental ? '增量模式' : '全量模式' }}</span>
              <span class="tag green">{{ batchDetail.n_done }} 章已检</span>
              <span v-if="batchDetail.n_skipped" class="tag gray">跳过 {{ batchDetail.n_skipped }} 章</span>
              <span class="tag"
                    :class="batchDetail.total_high ? 'red' : (batchDetail.total_issues ? 'orange' : 'green')">
                问题 {{ batchDetail.total_issues }} · 高 {{ batchDetail.total_high }}</span>
            </div>
            <table class="table">
              <thead><tr><th>章</th><th>问题</th><th>高</th><th>Top 问题</th></tr></thead>
              <tbody>
                <tr v-for="c in batchDetail.chapters" :key="c.no">
                  <td>第 {{ c.no }} 章</td>
                  <template v-if="c.error"><td colspan="3" class="rp-err">{{ c.error }}</td></template>
                  <template v-else>
                    <td>{{ c.n_issues }}</td>
                    <td><span v-if="c.n_high" class="sev hi">{{ c.n_high }}</span><span v-else>0</span></td>
                    <td class="rp-top">{{ (c.top_issues || []).map(i => i.reason).join('；') || '—' }}</td>
                  </template>
                </tr>
              </tbody>
            </table>
          </template>

          <template v-else-if="signingDetail">
            <div class="rp-tags">
              <span class="tag" :class="verdictCls(signingDetail.verdict)">{{ signingDetail.verdict }}</span>
              <span class="tag gray">前 {{ signingDetail.window_chapters }} 章 /
                {{ fmtNum(signingDetail.chars) }} 字</span>
              <span class="tag blue">{{ signingDetail.created }}</span>
            </div>
            <p v-if="signingDetail.verdict_why" class="hint rp-why">{{ signingDetail.verdict_why }}</p>
            <table class="table">
              <thead><tr><th>检查项</th><th>结论</th><th>依据</th></tr></thead>
              <tbody>
                <tr v-for="c in signingDetail.checks" :key="c.key">
                  <td>{{ c.label }}</td>
                  <td><span class="tag" :class="signLevelCls(c.level)">{{ c.level }}</span></td>
                  <td class="rp-top">{{ c.detail }}</td>
                </tr>
              </tbody>
            </table>
            <details v-if="(signingDetail.issues || []).length" class="rp-issues">
              <summary class="hint">问题清单（{{ signingDetail.issues.length }} 条）</summary>
              <div v-for="(x, i) in signingDetail.issues" :key="i" class="rp-issue">
                <span class="sev" :class="sevCls(x.sev)">{{ x.sev }}</span>
                <b v-if="x.chapter"> 第{{ x.chapter }}章 </b>{{ x.msg }}
              </div>
            </details>
          </template>

          <div v-else class="rp-empty">
            <Icon :name="reportMeta.icon" :size="40" />
            <b>暂无{{ reportMeta.title }}报告</b>
            <span>点下方「{{ reportMeta.first }}」对本书跑一次，报告会按时间留档</span>
          </div>
        </div>
      </div>
      <template #footer>
        <span class="rp-foot-hint" v-if="reportLoading || reportBusy">
          {{ reportBusy ? reportMeta.running + '，结束后自动刷新' : '刷新中…' }}</span>
        <button class="btn ghost" @click="reportOpen = false">关闭</button>
        <button class="btn" :disabled="reportBusy" @click="rerunReport">
          <Icon :name="reportMeta.icon" :size="14" />
          {{ reportBusy ? reportMeta.running : (reportHistory.length ? reportMeta.run : reportMeta.first) }}
        </button>
      </template>
    </Modal>

    <CoverModal v-model:open="coverModal" :book="meta.name" :title="meta.title || meta.name"
                :author="meta.author" @done="onCoverDone" />
  </template>
</template>

<style scoped>
.overview-card { display: flex; gap: 26px; align-items: flex-start; flex-wrap: wrap; }
.ov-cover { position: relative; width: 190px; height: 260px; border-radius: 12px; overflow: hidden; cursor: pointer; flex: none;
  background: linear-gradient(160deg, #3a4a63, #222c3d); }
.ov-cover img { width: 100%; height: 100%; object-fit: cover; display: block; }
.ov-cover-ph { width: 100%; height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; color: #fff; }
.ov-cover-ph svg { color: rgba(255, 255, 255, .55); }
.ov-cover-ph span { font-size: 18px; font-weight: 700; letter-spacing: 2px; }
.ov-cover-mask { position: absolute; inset: auto 0 0 0; background: rgba(31, 35, 41, .62); color: #fff; font-size: 12px;
  display: flex; align-items: center; justify-content: center; gap: 6px; padding: 8px 0; opacity: 0; transition: opacity .15s; }
.ov-cover:hover .ov-cover-mask { opacity: 1; }
.ov-meta { flex: 1; min-width: 300px; }
.ov-title { font-size: 22px; font-weight: 700; margin-bottom: 14px; display: flex; align-items: center; gap: 8px; }
.ov-title .icon-btn { opacity: .45; }
.ov-title:hover .icon-btn { opacity: 1; }
.ov-rows { display: flex; flex-direction: column; gap: 10px; }
.ov-row { display: flex; align-items: center; gap: 12px; font-size: 13px; color: var(--text-2); }
.ov-row.col { flex-direction: column; align-items: stretch; }
.ov-row .k { flex: none; width: 64px; color: var(--text-3); font-size: 12px; }
.ov-radio { display: inline-flex; align-items: center; gap: 5px; font-size: 13px; color: var(--text-2);
  cursor: pointer; margin-right: 16px; user-select: none; }
.ov-radio input { accent-color: var(--primary); cursor: pointer; }
.ov-intro { margin: 0; font-size: 13px; line-height: 1.7; color: var(--text-2); white-space: pre-wrap; }
.ov-intro-empty { font-size: 13px; }

.ov-side { width: 210px; flex: none; }
.ov-side-title { font-size: 12px; color: var(--text-3); margin-bottom: 8px; }
.ov-mod-link { display: flex; align-items: center; gap: 9px; width: 100%; padding: 8px 10px; border: 1px solid var(--border);
  border-radius: var(--radius-sm); background: var(--bg); cursor: pointer; margin-bottom: 8px; font-size: 13px; color: var(--text);
  transition: border-color .12s, background .12s; }
.ov-mod-link:hover { border-color: var(--primary); background: var(--primary-bg); }
.ov-mod-link .head-acts .icon-btn { width: 28px; height: 28px; }
.module-ico.sm { width: 24px; height: 24px; border-radius: 6px; flex: none; }
.ov-mod-name { font-weight: 600; }
.ov-mod-n { font-size: 11px; color: var(--text-3); }

/* 章节工作台：树 · 正文 · 概括 */
/* 三栏 Splitter 布局：左右栏宽度可拖拽（inline style 控制），中栏自适应；
   高度跟视口走：小屏不顶天立地，4K 不浪费空间 */
.ws { display: flex; align-items: stretch; height: clamp(480px, 74vh, 1200px); }
.ws-main { flex: 1 1 auto; }
.ws-split { flex: none; width: 12px; cursor: col-resize; display: flex; align-items: center;
  justify-content: center; position: relative; touch-action: none; }
.ws-split::before { content: ''; width: 3px; height: 64px; border-radius: 2px;
  background: var(--border); transition: background .15s, height .15s; }
.ws-split:hover::before, body.ws-resizing .ws-split::before { background: var(--primary); height: 100%; }
.split-btn { position: relative; z-index: 1; width: 18px; height: 18px; padding: 0; border-radius: 50%;
  border: 1px solid var(--border); background: var(--card); color: var(--text-3);
  display: flex; align-items: center; justify-content: center; cursor: pointer; }
.split-btn:hover { color: var(--primary); border-color: var(--primary); }
body.ws-resizing { cursor: col-resize; user-select: none; }
body.ws-resizing iframe { pointer-events: none; }
/* 沉浸式全屏：整卡 fixed 铺满视窗，栏宽沿用用户拖拽记忆 */
.card.ws-full { position: fixed; inset: 0; z-index: 80; margin: 0 !important; border-radius: 0;
  box-shadow: none; display: flex; flex-direction: column; overflow: hidden; }
.ws-full .card-head { flex: none; margin-bottom: 12px; }
.ws-full .ws { flex: 1; height: auto; min-height: 0; }
.ws-tree { border: 1px solid var(--border); border-radius: var(--radius-md); overflow-y: auto;
  padding: 8px; background: var(--bg); }
.ws-tree::-webkit-scrollbar { width: 7px; }
.ws-tree::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 4px; }
.tree-vol { font-size: 12px; font-weight: 700; color: var(--text-2); padding: 8px 6px 4px; }
.tree-ch { display: flex; align-items: center; gap: 7px; width: 100%; text-align: left; border: none; background: none;
  padding: 6px 8px; border-radius: 6px; cursor: pointer; font-size: 12px; color: var(--text-2); min-width: 0; }
.tree-ch:hover { background: #f2f3f5; color: var(--text); }
.tree-ch.on { background: var(--primary-bg); color: var(--primary); font-weight: 600; }
.tc-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--border-strong); flex: none; }
.tc-dot.g { background: var(--green); }
.tc-name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }

.ws-main { border: 1px solid var(--border); border-radius: var(--radius-md); display: flex;
  flex-direction: column; flex: 1 1 auto; min-width: 200px; background: var(--card); }
.ws-main-head { display: flex; align-items: center; gap: 8px; padding: 10px 12px;
  border-bottom: 1px solid var(--border); font-size: 14px; flex-wrap: wrap; row-gap: 6px; }
.title-edit { width: min(260px, 60vw); border: 1px solid var(--primary); border-radius: 4px; outline: none;
  font-size: 14px; padding: 2px 6px; color: var(--text); background: var(--card); }
.icon-btn.sm { width: 24px; height: 24px; padding: 0; border-radius: 5px; color: var(--text-2); }
.gen-mode { height: 30px; border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--card); color: var(--text); font-size: 12px; padding: 0 6px; cursor: pointer; outline: none; }
.gen-mode:focus { border-color: var(--primary); }
.ms-copy-grp { margin-left: 0; display: flex; align-items: center; gap: 8px; flex: none; }
.ws-editor-wrap { position: relative; flex: 1; min-height: 0; display: flex; }
/* 审查高亮镜像层：字体 / 行高 / 内边距必须与 .ws-editor 完全一致，否则会错位 */
.ws-hl { position: absolute; inset: 0 auto 0 0; overflow: hidden; pointer-events: none; z-index: 0; }
.ws-hl-inner { padding: 14px 16px; font-size: 14px; line-height: 1.9; font-family: inherit;
  white-space: pre-wrap; overflow-wrap: break-word; color: transparent; }
.ws-hl mark.hl { background: rgba(255, 176, 32, .3); color: transparent; border-radius: 2px;
  box-shadow: 0 0 0 1px rgba(255, 145, 0, .35) inset; }
.ws-hl mark.hl.on { background: rgba(255, 122, 0, .5); box-shadow: 0 0 0 1px rgba(230, 100, 0, .6) inset; }
.ws-editor { position: relative; z-index: 1; flex: 1; border: none; outline: none; resize: none; padding: 14px 16px; font-size: 14px;
  line-height: 1.9; font-family: inherit; color: var(--text); background: none; }
.ws-genstatus { flex: 1; display: flex; flex-direction: column; padding: 14px 16px; min-height: 0; }
.gs-title { font-size: 13px; color: var(--text-2); display: flex; align-items: center; gap: 6px; margin-bottom: 10px; }
.gs-log { flex: 1; margin: 0; overflow-y: auto; white-space: pre-wrap; word-break: break-word;
  font-size: 13px; line-height: 1.8; color: var(--text-2); background: var(--bg);
  border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 12px; }
.ws-empty { flex: 1; display: flex; align-items: center; justify-content: center;
  color: var(--text-3); font-size: 13px; }

/* 正文任务状态条（跨页面保持的任务状态） */
.ws-task { display: flex; align-items: center; gap: 8px; padding: 7px 12px; flex: none;
  font-size: 12px; color: var(--text-2); background: var(--bg);
  border-bottom: 1px solid var(--border); }
.ws-task.err { background: #fdf3f2; color: #a03028; }
.ws-task .wst-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--primary);
  flex: none; animation: wst-blink 1.2s ease-in-out infinite; }
.ws-task.err .wst-dot { background: #d94a3d; animation: none; }
.ws-task .wst-txt { min-width: 0; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ws-task .wst-txt b { font-weight: 700; margin-right: 6px; color: var(--text); }
.ws-task .wst-meta { flex: none; color: var(--text-3); }
@keyframes wst-blink { 0%, 100% { opacity: 1; } 50% { opacity: .35; } }

/* 候选版本弹层 */
.cand-mask { position: fixed; inset: 0; background: rgba(15, 18, 24, .55); z-index: 100;
  display: flex; align-items: center; justify-content: center; padding: 24px; }

/* 编辑器右键菜单（选中文字后） */
.ctx-menu { position: fixed; z-index: 120; min-width: 168px; background: var(--card);
  border: 1px solid var(--border); border-radius: var(--radius-sm); box-shadow: 0 8px 26px rgba(0, 0, 0, .28);
  padding: 6px; }
.ctx-hint { font-size: 11px; color: var(--text-3); padding: 4px 8px 6px; border-bottom: 1px solid var(--border); margin-bottom: 4px; }
.ctx-item { display: flex; align-items: center; gap: 8px; width: 100%; text-align: left; border: none;
  background: none; padding: 8px 10px; border-radius: 6px; cursor: pointer; font-size: 13px; color: var(--text); }
.ctx-item:hover { background: var(--primary-bg); color: var(--primary); }

.cand-modal { width: min(1080px, 96vw); max-height: 90vh; background: var(--card); border-radius: var(--radius-md);
  border: 1px solid var(--border); display: flex; flex-direction: column; box-shadow: 0 18px 50px rgba(0, 0, 0, .35); }
.cand-head { display: flex; align-items: flex-start; gap: 12px; padding: 16px 18px; border-bottom: 1px solid var(--border); }
.cand-title { font-size: 15px; font-weight: 700; flex: 1; display: flex; flex-direction: column; gap: 4px; }
.cand-title small { font-weight: 400; font-size: 12px; color: var(--text-3); }
/* 弹层主体：默认单列（版本历史 / 敏感词等）；候选面板加 .cols 才是三列等宽。
   三列用 minmax(0, 1fr) 而不是 1fr —— 1fr 的最小宽度是内容宽度，卡片头/按钮
   一撑就超宽；overflow-x 显式关掉，避免 overflow-y 把横向也变成可滚动。 */
.cand-list { display: grid; grid-template-columns: minmax(0, 1fr); gap: 14px; padding: 16px 18px;
  overflow-y: auto; overflow-x: hidden; }
.cand-list.cols { grid-template-columns: repeat(3, minmax(0, 1fr)); align-items: stretch; }
.cand-card { border: 1px solid var(--border); border-radius: var(--radius-md); display: flex; flex-direction: column;
  min-width: 0; background: var(--bg); }
.cand-card.rec { border-color: var(--primary); box-shadow: 0 0 0 2px var(--primary-bg) inset; }
.cand-card-head { display: flex; align-items: center; gap: 8px; padding: 10px 12px; border-bottom: 1px solid var(--border); }
.cand-badge { font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 999px; background: var(--border-strong); color: var(--text-2); flex: none; }
.cand-badge.rec { background: var(--primary); color: #fff; }
.cand-note { font-size: 12px; color: var(--text-2); flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cand-chars { font-size: 11px; color: var(--text-3); flex: none; }
.cand-body { flex: 1 1 auto; overflow-y: auto; min-height: 160px; max-height: 46vh; padding: 12px; }
.cand-body pre { margin: 0; white-space: pre-wrap; word-break: break-word; font-size: 13px; line-height: 1.85; font-family: inherit; color: var(--text); }
.cand-acts { flex: none; display: flex; flex-wrap: wrap; gap: 8px; padding: 10px 12px; border-top: 1px solid var(--border); margin-top: auto; }
.cand-foot { display: flex; align-items: center; gap: 12px; padding: 12px 18px; border-top: 1px solid var(--border); }
.cand-foot .sub { font-size: 12px; color: var(--text-3); flex: 1; }
@media (max-width: 900px) {
  .cand-list.cols { grid-template-columns: 1fr; }
  .cand-body { max-height: 30vh; }
}
.ws-main-foot { display: flex; align-items: center; padding: 8px 12px 8px 24px;
  border-top: 1px solid var(--border); font-size: 12px; color: var(--text-3); }
.ws-main-foot .spacer { flex: 1; }
.ws-foot-acts { display: flex; align-items: center; gap: 10px; flex: none; }

.ws-side { border: 1px solid var(--border); border-radius: var(--radius-md);
  background: var(--bg); display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
.ws-side-tabs { display: flex; gap: 4px; padding: 8px 10px 0; flex: none; }
.ws-side-tabs button { border: none; background: none; padding: 6px 10px; font-size: 12px; cursor: pointer;
  color: var(--text-2); border-radius: 6px 6px 0 0; position: relative; }
.ws-side-tabs button.active { color: var(--text); font-weight: 700; background: var(--card); }
.tab-badge { margin-left: 6px; font-size: 10px; background: var(--orange); color: #fff; border-radius: 999px;
  padding: 0 6px; line-height: 15px; display: inline-block; }
.ws-side-body { flex: 1; min-height: 0; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 10px; }
.ws-side-body::-webkit-scrollbar { width: 7px; }
.ws-side-body::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 4px; }
.ws-side-title { font-size: 13px; font-weight: 700; }

/* 选区候选 tab */
.sel-head { display: flex; align-items: flex-start; gap: 6px; }
.sel-head .tag { flex: none; margin-top: 1px; }
.sel-src { flex: 1; min-width: 0; font-size: 11px; color: var(--text-3); line-height: 1.5;
  display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden; word-break: break-all; }
.sel-src.link { cursor: pointer; border-bottom: 1px dashed var(--border-strong); }
.sel-src.link:hover { color: var(--primary); border-bottom-color: var(--primary); }
/* 正文里原选区的高亮：与审查问题的橙色区分开 */
.ws-hl mark.hl.sel { background: rgba(47, 107, 255, .16);
  box-shadow: 0 0 0 1px rgba(47, 107, 255, .38) inset; }
.sel-cand { border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--card); padding: 8px 10px; }
.sel-cand.rec { border-color: var(--green); }
.sel-cand-head { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.sel-note { flex: 1; min-width: 0; font-size: 11px; color: var(--text-3);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sel-chars { flex: none; font-size: 11px; color: var(--text-3); }
.sel-text { margin: 0; max-height: 140px; overflow-y: auto; white-space: pre-wrap;
  word-break: break-word; font-size: 12px; line-height: 1.7; font-family: inherit; color: var(--text); }
.sel-acts { display: flex; gap: 8px; margin-top: 8px; }
.sel-hint { font-size: 11px; color: var(--text-3); line-height: 1.6; }

.cf { font-size: 12px; color: var(--text-2); line-height: 1.6; min-width: 0; }
.cf .k { display: inline-block; margin-right: 8px; color: var(--text-3); font-size: 11px; flex: none; }
.cf > p { display: inline; margin: 0; }
/* 摘要单独成段：标签在上、正文整宽，避免和字段标签挤在一行里变成一堵字墙 */
.cf.cf-block { display: block; }
.cf.cf-block .k { display: block; margin: 0 0 5px; letter-spacing: .04em; }
.cf.cf-block > p { display: block; font-size: 13px; line-height: 1.9; }
.cf .tags { display: inline-flex; flex-wrap: wrap; gap: 5px; vertical-align: middle; }
.cf .tag { font-size: 11px; }
.pts { margin: 2px 0 0; padding-left: 18px; color: var(--text-2); }
.pts li { margin-bottom: 2px; }

/* 情绪流：拆解标好的情绪走向 / 峰值 / 兑现 / 铺垫 / 钩子类型 */
.flow-wrap { display: inline-flex; align-items: center; gap: 8px; flex-wrap: wrap; vertical-align: middle; }
.flow-emo { display: inline-flex; align-items: center; gap: 4px; }
.emo-chip { padding: 1px 7px; border-radius: 999px; background: var(--purple-bg, rgba(140, 120, 255, .14));
  color: var(--purple, #8c78ff); font-size: 11px; line-height: 1.7; }
.flow-arrow { color: var(--text-3); font-size: 11px; }
.flow-ten { display: inline-flex; align-items: center; gap: 5px; }
.ten-bar { display: inline-block; width: 54px; height: 4px; border-radius: 2px; background: var(--border); overflow: hidden; }
.ten-bar i { display: block; height: 100%; background: linear-gradient(90deg, var(--orange), var(--red));
  border-radius: 2px; transition: width .2s; }
.ten-num { font-size: 11px; color: var(--text-3); font-variant-numeric: tabular-nums; }
.hook-wrap { display: inline-flex; align-items: baseline; gap: 6px; flex-wrap: wrap; }
.hook-chip { padding: 0 6px; border-radius: var(--radius-sm); border: 1px solid var(--border);
  background: var(--bg-2, rgba(255, 255, 255, .04)); color: var(--text-2); font-size: 11px; line-height: 1.7; flex: none; }

/* 页内审查结果 */
.rev-actions { display: flex; gap: 8px; flex: none; flex-wrap: wrap; }
.rev-prog { flex: 1; min-height: 0; overflow-y: auto; background: var(--card); border: 1px solid var(--border);
  border-radius: var(--radius-sm); padding: 10px; }
.rev-line { font-size: 12px; line-height: 1.7; color: var(--text-2); white-space: pre-wrap; word-break: break-word; }
.rev-err { color: var(--red); font-size: 12px; }
.ws-side-empty { color: var(--text-3); font-size: 12px; padding: 18px 4px; text-align: center; }
.rev-summary { display: flex; flex-wrap: wrap; gap: 6px; flex: none; }
.rev-theme { font-size: 12px; color: var(--text-2); line-height: 1.6; }
.rev-stale { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 12px; line-height: 1.5;
  color: var(--orange); background: rgba(255, 145, 0, .1); border: 1px solid rgba(255, 145, 0, .35);
  border-radius: var(--radius-sm); padding: 7px 9px; }
.rev-issue { border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 9px 10px; background: var(--card); }
.rev-advice { display: flex; flex-direction: column; gap: 5px; margin-top: 7px; }
.rev-adv { display: flex; gap: 7px; font-size: 12px; line-height: 1.6; padding: 6px 8px; border-radius: var(--radius-sm); }
.rev-adv b { flex: none; font-weight: 600; }
.rev-adv.pos { color: var(--green); background: var(--green-bg); }
.rev-adv.neg { color: var(--red); background: var(--red-bg); }
.rev-issue.locatable { cursor: pointer; }
.rev-issue.locatable:hover { border-color: var(--primary); }
.rev-issue.on { border-color: var(--orange); box-shadow: 0 0 0 1px var(--orange) inset; }
.rev-line-no { font-size: 11px; color: var(--text-3); flex: none; }
.rev-loc { margin-top: 6px; font-size: 11px; color: var(--text-3); display: flex; align-items: center; gap: 4px; }
.rev-issue.locatable .rev-loc { color: var(--primary); }
.rev-issue-head { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; flex-wrap: wrap; }
.rev-issue-title { font-size: 12px; font-weight: 700; color: var(--text); flex: 1; min-width: 0; }
.rev-quote { font-size: 12px; color: var(--text); background: var(--bg); border-left: 3px solid var(--border-strong);
  padding: 4px 8px; margin-bottom: 6px; border-radius: 0 4px 4px 0; }
.rev-suggest { font-size: 12px; color: var(--text); line-height: 1.6; }
.rev-reason { font-size: 12px; color: var(--text-2); line-height: 1.6; margin-top: 2px; }
.rev-skip { font-size: 11px; color: var(--orange); }
.sev { font-size: 11px; font-weight: 700; padding: 1px 7px; border-radius: 999px; }
.sev.hi { background: var(--red); color: #fff; }
.sev.mid { background: var(--orange); color: #fff; }
.sev.lo { background: var(--border-strong); color: var(--text-2); }

/* 作品级报告弹窗：左侧历史列表 + 右侧报告结构，底部再次执行 */
.rp { display: flex; gap: 16px; align-items: stretch; min-height: 320px; }
.rp-hist { width: 200px; flex: none; display: flex; flex-direction: column; gap: 4px;
  max-height: 62vh; overflow-y: auto; padding-right: 12px; border-right: 1px solid var(--border); }
.rp-hist-head { display: flex; align-items: center; gap: 6px; margin-bottom: 4px;
  font-size: 12px; color: var(--text-3); }
.rp-count { font-size: 11px; line-height: 16px; padding: 0 6px; border-radius: 9px;
  background: var(--bg); color: var(--text-2); }
.rp-hist-item { display: flex; flex-direction: column; gap: 3px; padding: 7px 9px; text-align: left;
  border: 1px solid transparent; border-radius: 8px; background: none; cursor: pointer;
  font-size: 12px; line-height: 1.5; color: var(--text-2); }
.rp-hist-item:hover { background: var(--bg); }
.rp-hist-item.on { background: var(--primary-bg); border-color: var(--primary); color: var(--primary); }
.rp-hist-time { display: flex; align-items: center; gap: 6px; font-size: 12.5px; font-weight: 600; }
.rp-hist-time i { font-style: normal; font-size: 10px; font-weight: 400; padding: 0 5px;
  border-radius: 4px; background: var(--green-bg); color: var(--green); }
.rp-detail { flex: 1; min-width: 0; max-height: 62vh; overflow-y: auto; padding-right: 4px; }
.rp-tags { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
.rp-why { margin: 0 0 10px; }
.rp-top { font-size: 12px; color: var(--text-2); }
.rp-err { color: var(--red); }
/* 空态：图标在上、文字在下居中，避免图标被挤到左侧、和文案不在一条中轴上 */
.rp-empty { padding: 64px 20px; display: flex; flex-direction: column; align-items: center;
  justify-content: center; text-align: center; font-size: 13px; color: var(--text-3); }
.rp-empty svg { display: block; color: #d5d9df; margin-bottom: 10px; }
.rp-empty b { display: block; margin-bottom: 4px; font-size: 14px; color: var(--text-2); }
.rp-empty span { display: block; }
.rp-issues { margin-top: 10px; }
.rp-issue { margin-top: 4px; font-size: 12.5px; line-height: 1.7; color: var(--text-2); }
.rp-foot-hint { margin-right: auto; font-size: 12px; color: var(--text-3); }

/* 版本历史 / 敏感词弹层 */
.hist-modal { width: min(1060px, 96vw); }
.hist-cur { font-size: 12px; color: var(--text-2); background: var(--bg); border-radius: var(--radius-sm);
  padding: 8px 10px; margin-bottom: 10px; }
.hist-item { display: flex; gap: 10px; align-items: flex-start; border: 1px solid var(--border);
  border-radius: var(--radius-sm); padding: 10px 12px; margin-bottom: 8px; background: var(--card); }
.hist-meta { flex: 1; min-width: 0; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; font-size: 12.5px; }
.hist-preview { width: 100%; font-size: 12px; color: var(--text-3); margin-top: 4px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hist-acts { flex: none; display: flex; gap: 2px; }
.hist-title { font-size: 13px; font-weight: 600; margin-bottom: 8px; }
.hist-body { max-height: 55vh; overflow: auto; background: var(--bg); border: 1px solid var(--border);
  border-radius: var(--radius-sm); padding: 12px; font-size: 12.5px; line-height: 1.8; white-space: pre-wrap;
  word-break: break-word; margin: 0; }
/* 单版详情：顶部固定操作条 + 下方独立滚动，返回 / 回滚不必滚回顶部 */
.hist-detail-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; flex: none;
  padding: 10px 18px; border-bottom: 1px solid var(--border); background: var(--card); }
.hist-detail-head .hist-title { margin: 0; flex: 1; min-width: 180px; font-weight: 600; color: var(--text-2); }
.hist-stat { display: inline-flex; align-items: center; gap: 8px; flex: none; font-size: 12px;
  font-variant-numeric: tabular-nums; }
.hist-stat .add { color: var(--green); font-weight: 700; }
.hist-stat .del { color: var(--red); font-weight: 700; }
.hist-detail-body { flex: 1; min-height: 0; align-content: start; }
.hist-detail-body .hist-body { max-height: none; flex: 1; }

/* 行级 diff：新增绿底 / 删除红底 + 左侧色条，减号行不再是普通灰字 */
.diff-legend { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; font-size: 11.5px; }
.diff-legend .lg { padding: 1px 8px; border-radius: 999px; font-weight: 600; }
.diff-legend .lg.del { color: var(--red); background: var(--red-bg); }
.diff-legend .lg.add { color: var(--green); background: var(--green-bg); }
.diff-hint { color: var(--text-3); }
.diff-view { border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--card); overflow: hidden; }
.diff-line { display: flex; align-items: flex-start; gap: 8px; padding: 2px 12px;
  font-size: 12.5px; line-height: 1.8; color: var(--text-2); }
.diff-line .diff-sign { flex: none; width: 12px; text-align: center; user-select: none;
  font-family: Consolas, monospace; color: var(--text-3); }
.diff-line .diff-text { flex: 1; min-width: 0; white-space: pre-wrap; word-break: break-word; }
.diff-line.add { background: rgba(24, 160, 88, .12); box-shadow: inset 3px 0 0 var(--green); }
.diff-line.add .diff-sign { color: var(--green); font-weight: 700; }
.diff-line.add .diff-text { color: var(--text); }
.diff-line.del { background: rgba(217, 74, 61, .13); box-shadow: inset 3px 0 0 var(--red); }
.diff-line.del .diff-sign { color: var(--red); font-weight: 700; }
.diff-line.del .diff-text { color: var(--text); }
.diff-line.hunk { background: var(--primary-bg); color: var(--primary); font-size: 11.5px; padding: 4px 12px; }
.diff-line.meta { color: var(--text-3); font-size: 11.5px; }
@media (max-width: 1360px) {
  /* 1280 宽度下三栏会把正文压到 350px 左右：提前改竖排，
     目录在上（限高纵滚）、正文占满整行、概括/审查在下。 */
  .ws { flex-direction: column; height: auto; }
  .ws-tree { display: block !important; width: 100% !important; max-height: 200px; }
  .ws-main { min-width: 0; min-height: 480px; }
  .ws-side { display: flex !important; width: 100% !important; max-height: 380px; }
  .ws-split { display: none; }
  .ws-editor { min-height: 420px; }
}
@media (max-width: 1200px) {
  .ov-side { width: 100%; }
}
@media (max-width: 760px) {
  .overview-card { gap: 14px; padding: 16px; }
  .ov-cover { width: 88px; height: 120px; border-radius: 12px; }
  /* 封面与信息并排，信息列允许收缩：360px 屏也放得下，不用整块换行浪费高度 */
  .ov-meta { min-width: 0; flex: 1 1 0; }
  .ov-title { font-size: 19px; flex-wrap: wrap; margin-bottom: 8px; }
  .ov-title > span { flex: 1; min-width: 0; word-break: break-word; }
  .ov-title .icon-btn { flex: none; }
  .ov-title .input { flex: 1 1 200px; }
  .ov-rows { gap: 8px; margin-top: 6px; }
  .ov-row { flex-wrap: wrap; gap: 8px; font-size: 13px; }
  .ov-row .k { width: 56px; font-size: 11.5px; }
  .ov-status { flex: 1; min-width: 0; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .ov-radio { margin-right: 0; padding: 4px 11px; border-radius: 999px;
    background: #f4f5f7; font-size: 12px; gap: 6px; }
  .ov-radio:has(input:checked) { background: var(--primary-bg); color: var(--primary); font-weight: 600; }
  .ov-cover-ph span { display: -webkit-box; -webkit-line-clamp: 3; line-clamp: 3;
    -webkit-box-orient: vertical; overflow: hidden; font-size: 13px; line-height: 1.5;
    letter-spacing: 0; word-break: break-all; }
  .ov-acts { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .ov-acts .btn { width: 100%; }
  .ov-side { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; width: 100%; }
  .ov-side-title { grid-column: 1 / -1; margin: 0 0 2px; }
  .ov-mod-link { position: relative; flex-direction: column; align-items: flex-start;
    gap: 6px; padding: 12px; border: 1px solid var(--border); border-radius: 12px; background: #fafbfc; }
  .ov-mod-link .head-acts { position: absolute; top: 6px; right: 6px; }
  .ws-main-head { flex-wrap: wrap; row-gap: 6px; padding: 8px 10px; }
  .ws-main { min-height: 420px; }
  .ws-tree { max-height: 160px; }
  .ws-side { max-height: 55vh; }
  .ws-main-foot { flex-wrap: wrap; gap: 6px; padding-left: 12px; }
  .cand-mask { padding: 10px; }
  .cand-list { padding: 12px; }
  .cand-head, .cand-foot { padding-left: 12px; padding-right: 12px; }
  .hist-item { flex-wrap: wrap; }
  .ctx-menu { max-width: calc(100vw - 20px); }
  /* 报告弹窗：窄屏改成「历史在上（横滑）/ 报告在下」 */
  .rp { flex-direction: column; min-height: 0; }
  .rp-hist { width: auto; flex-direction: row; max-height: none; overflow-x: auto;
    padding: 0 0 10px; border-right: none; border-bottom: 1px solid var(--border); }
  .rp-hist-head { display: none; }
  .rp-hist-item { flex: none; max-width: 220px; }
  .rp-detail { max-height: 48vh; }
  .rp-foot-hint { display: none; }
}
/* 超窄屏（≤380px）：封面再缩一档，字段改成「标签在上、值在下」，避免两列表格挤成竖排字 */
@media (max-width: 380px) {
  .ov-cover { width: 64px; height: 88px; }
  .ov-cover-ph { gap: 6px; }
  .ov-cover-ph span { font-size: 11.5px; -webkit-line-clamp: 3; }
  .ov-title { font-size: 17px; }
  .ov-rows { gap: 6px; }
  .ov-row { flex-direction: column; align-items: flex-start; gap: 3px; }
  .ov-row .k { width: auto; }
  .ov-row.col { gap: 3px; }
  .ov-status { width: 100%; flex-wrap: wrap; }
  .ov-acts { grid-template-columns: 1fr 1fr; }
  .ov-acts .btn { padding: 0 8px; font-size: 12.5px; }
}
/* 无 hover 设备：封面「更换封面」与标题旁操作常驻，否则手机上无从发现 */
@media (hover: none) {
  .ov-cover-mask { opacity: 1; }
  .ov-title .icon-btn { opacity: .8; }
}

</style>
