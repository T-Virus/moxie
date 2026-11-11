import type {
  Stats, BookSummary, SourceFile, ChaptersData, SbSchema,
  ReviewOptions, ReviewBaseline, OutputFile, OutputsResp,
  JobState, JobSummary, ReviewJobState, CoverPresets, CoverResult,
} from './types'

/* 服务端每次运行注入的会话令牌：打包后写请求必须带回，挡住外部脚本直接调接口。
   开发模式（Vite 页面由 Vite 自己返回）拿不到令牌，后端在非打包形态不校验。 */
const MW_TOKEN = (window as any).__mwToken || ''
const mwHeaders = (): Record<string, string> =>
  MW_TOKEN ? { 'X-MW-Token': MW_TOKEN } : {}

async function request<T = any>(path: string, opt?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    ...opt,
    headers: { 'Content-Type': 'application/json', ...mwHeaders() },
  })
  const raw = await r.text()
  let j: any
  try {
    j = raw ? JSON.parse(raw) : {}
  } catch {
    // 后端未加载该接口时会把请求兜底成 index.html，这里给出可读原因
    throw new Error(`接口 ${path} 返回了非 JSON 内容（HTTP ${r.status}），` +
      '多半是后端还是旧版本，请完全退出应用后重新启动')
  }
  // 注意：任务类接口在失败时返回 HTTP 200 + 顶层 error 字段（running:false），
  // 由轮询逻辑按 j.error/j.code 处理。这里只在真正的非 2xx 时抛错，
  // 否则 200 的失败响应会被提前 throw 并被空 catch 静默吞掉，导致 UI 卡在「运行中」。
  if (!r.ok) throw new Error((j && j.error) || r.statusText)
  return j as T
}
/** 发起任务的页面（当前 hash 路由），后端记进任务里，任务中心点回来时跳这里 */
function currentOrigin(): string {
  const h = location.hash.replace(/^#/, '') || '/'
  const [path, qs] = h.split('?')
  // 去掉「当时正在看哪个任务」，否则回跳后会重复挂上旧任务
  const keep = (qs || '').split('&').filter(p => p && !/^job=/.test(p))
  return keep.length ? `${path || '/'}?${keep.join('&')}` : (path || '/')
}

/* 所有写请求都带上 origin：后端只有任务类接口会用它，其余接口忽略 */
const post = <T = any>(path: string, body?: any) =>
  request<T>(path, {
    method: 'POST',
    body: JSON.stringify({ ...(body || {}), origin: currentOrigin() }),
  })

export const api = {
  getStats: () => request<Stats>('/api/stats'),
  getBooks: () => request<{ books: BookSummary[] }>('/api/books'),
  getSources: () => request<{ sources: SourceFile[] }>('/api/sources'),

  upload: (name: string, data: { b64?: string; text?: string }) =>
    post('/api/upload', { name, ...data }),
  deleteSource: (name: string) => post('/api/source/delete', { name }),

  // 封面
  coverUrl: (book: string, t: number | string = 0) =>
    '/api/cover?book=' + encodeURIComponent(book) + (t ? '&t=' + t : ''),
  uploadCover: (book: string, b64: string, ext: string) =>
    post('/api/cover', { book, b64, ext }),
  deleteCover: (book: string) => post('/api/cover/delete', { book }),

  // AI 封面：平台制式 / 中文提示词转英文 / 出图 + 本地排版
  coverPresets: () => request<CoverPresets>('/api/cover/presets'),
  coverTranslate: (text: string) =>
    post<{ prompt_en: string; translated: boolean; theme: string; matched: string[] }>(
      '/api/cover/translate', { text }),
  coverGenerate: (body: {
    book: string; title: string; author: string; prompt: string;
    width: number; height: number; fmt: string; model: string;
    style: string; layout: string; seed?: string | number; reuse_base?: boolean;
    /* 「AI 封面底图」工序绑定的档案：有 Key 时优先用该模型出图，失败自动回退 */
    api_key?: string; base_url?: string; ai_model?: string;
  }) => post<CoverResult>('/api/cover/generate', body),

  /* 桌面端：在资源管理器打开目录（导出目录 / 数据目录），手机端会返回 400 */
  openPath: (path: string) => post<{ ok: boolean; path: string }>('/api/open/path', { path }),

  /* 提交任务：返回本次任务的 id，页面据此轮询自己的日志（支持多任务并发） */
  /* compliance：拆解 / 改编前必须带的权利与 AI 使用声明（服务端校验并留痕） */
  run: (api_key: string, stage: string, args: any, compliance?: any) =>
    post<{ ok: boolean; id: string; stage: string; label: string }>(
      '/api/run', { api_key, stage, args, ...(compliance ? { compliance } : {}) }),
  /* 本地自动备份：每次保存前由服务端快照，最多保留 20 份 */
  listBackups: (book: string) =>
    request<{ ok: boolean; files: { file: string; size: number; mtime: string }[] }>(
      '/api/backups?book=' + encodeURIComponent(book)),
  restoreBackup: (book: string, file: string) =>
    post<{ ok: boolean; file: string }>('/api/backups/restore', { book, file }),
  stopJob: (id = '') => post<{ ok: boolean; ids: string[] }>('/api/job/stop', { id }),
  /* 清屏：只清空该任务的日志行，任务本身保留（运行中也能清，后续输出继续追加） */
  clearJobLog: (id: string) => post<{ ok: boolean; id: string }>('/api/job/clear', { id }),
  /* 删除单个任务（运行中会被后端拦下，需先停止） */
  deleteJob: (id: string) => post<{ ok: boolean; id: string }>('/api/job/delete', { id }),
  /* 清空全部任务：只删已结束的，运行中的保留 */
  clearJobs: () => post<{ ok: boolean; removed: number; ids: string[] }>('/api/jobs/clear', {}),

  // 单章正文生成（页内流式）：mode = outline 按大纲 / continue 续写 / expand 扩写 / rewrite 改写
  // before / after：选区操作时选中文本的前后文，供 AI 承接（整章生成为空）
  // scope：chapter=整章生成 / selection=只对选中片段生成候选（决定后端任务名与候选落点）
  expandChapter: (body: { book: string; chapter_no: number; api_key?: string; model?: string;
    base_url?: string; temperature?: number; mode?: string; text?: string;
    scope?: 'chapter' | 'selection';
    /* 审查→改写闭环：true 时后端把该章最近审查结论作为「必须修复」指令追加进改写提示词（强制 rewrite） */
    fix_from_review?: boolean;
    /* 选区在正文里的起止：后端随任务落盘，切书 / 切章回来还能按原位采纳 */
    sel_start?: number; sel_end?: number;
    before?: string; after?: string; style?: string; count?: number }) =>
    post<{ ok: boolean; id: string; chapter_no: number }>('/api/expand/chapter', body),
  /* 停某一条正文生成（不同章可以并发，所以必须按任务 id 停，不能停「全局那一条」） */
  stopExpand: (id?: string) => post('/api/expand/stop', id ? { id } : {}),

  getChapters: (book: string) =>
    request<ChaptersData>('/api/chapters?book=' + encodeURIComponent(book)),
  putChapters: (book: string, body: ChaptersData) =>
    request('/api/chapters?book=' + encodeURIComponent(book),
      { method: 'PUT', body: JSON.stringify(body) }),
  createBook: (name: string) =>
    request('/api/chapters?book=' + encodeURIComponent(name),
      { method: 'PUT', body: JSON.stringify({ story_bible_fields: {}, story_bible_cards: [], story_bible_factions: [], chapters: [] }) }),
  deleteBook: (book: string) => post('/api/book/delete', { book }),

  /* 数据同步：导出包用口令加密（AES-256-GCM），导入时用同一口令解开 */
  dataSyncStatus: () => request<{ busy: boolean; books: number }>('/api/data/status'),
  /* 导出第一步：口令换一次性下载票据（口令不进下载 URL / 历史记录） */
  prepareExport: (password: string) =>
    post<{ ok: boolean; ticket: string }>('/api/data/export/prepare', { password }),
  /* 客户端（pywebview）没有下载目录：由服务端加密后存到 exe 同级 exports/ 并返回绝对路径 */
  exportDataSave: (password: string) =>
    post<{ ok: boolean; path: string; bytes: number; books: number }>(
      '/api/data/export/save', { password }),
  exportDataZip: async (ticket: string): Promise<Blob> => {
    const r = await fetch('/api/data/export?ticket=' + encodeURIComponent(ticket),
      { headers: mwHeaders() })
    if (!r.ok) {
      let msg = '导出失败'
      try { const j = await r.json(); msg = j?.error || msg } catch { /* 非 JSON 用默认文案 */ }
      throw new Error(msg)
    }
    return r.blob()
  },
  importDataZip: (zip: string, replace: boolean, password: string) =>
    post<{ ok: boolean; books: string[]; files: number; bytes: number; backup: string }>(
      '/api/data/import', { zip, replace, password }),

  getSchema: () => request<SbSchema>('/api/schema'),

  /* 一键批量改名：只返回建议映射，确认后再随 PUT /api/chapters 的 renames 落盘 */
  renameEntities: (body: {
    book: string; kind: 'characters' | 'factions' | 'items';
    api_key?: string; model?: string; base_url?: string; style?: string; names?: string[];
  }) => post<{ ok: boolean; kind: string; name_map: { old: string; new: string }[] }>(
    '/api/entities/rename', body),
  getStorymap: (book: string) =>
    request<{ ok: boolean; data: any }>('/api/storymap?book=' + encodeURIComponent(book)),
  getStorymapPlot: (book: string) =>
    request<any>('/api/storymap/plot?book=' + encodeURIComponent(book)),
  /* 世界地图：storymap.json 里的地图优先，缺失时后端用设定库 + 逐章数据现算 */
  getBookMap: (book: string) =>
    request<{ ok: boolean; map: any; generated_at?: string; ai?: boolean }>(
      '/api/map?book=' + encodeURIComponent(book)),
  renameBook: (from: string, to: string) =>
    post<{ book: string }>('/api/book/rename', { from, to }),

  /* 产出清单：page>=1 走服务端分页（大目录只取一页）；不带 page 为全量（书内小范围列表用） */
  getOutputs: (p: {
    q?: string; group?: string; book?: string; kind?: string; page?: number; pageSize?: number
  } = {}) => {
    const sp = new URLSearchParams()
    if (p.q) sp.set('q', p.q)
    if (p.group) sp.set('group', p.group)
    if (p.book) sp.set('book', p.book)
    if (p.kind) sp.set('kind', p.kind)
    if (p.page && p.page > 0) sp.set('page', String(p.page))
    if (p.pageSize) sp.set('page_size', String(p.pageSize))
    const s = sp.toString()
    return request<OutputsResp>('/api/outputs' + (s ? '?' + s : ''))
  },
  getOutput: (path: string, dl = false) =>
    request<{ name: string; content: string; truncated?: boolean; size?: number }>(
      '/api/output?path=' + encodeURIComponent(path) + (dl ? '&dl=1' : '')),
  deleteOutput: (path: string) => post('/api/output/delete', { path }),
  saveManuscript: (book: string, no: number, text: string) =>
    post<{ ok: boolean; chars: number }>('/api/manuscript/save', { book, no, text }),
  clearOutputs: (dry: boolean) => post('/api/outputs/clear', { dry }),

  // 审查
  reviewOptions: () => request<ReviewOptions>('/api/review/options'),
  reviewBaseline: (book: string, chapter_no: string) =>
    request<ReviewBaseline>(
      '/api/review/baseline?book=' + encodeURIComponent(book) +
      '&chapter_no=' + encodeURIComponent(chapter_no)),
  reviewRun: (body: any) => post<{ ok: boolean; checks: string[]; id: string; title?: string }>('/api/review/run', body),
  stopReview: (id?: string) => post('/api/review/stop', id ? { id } : {}),
  /* 释放：立刻解锁（不等当前这一步跑完），好让用户切章 / 发起别的生成或审查 */
  releaseReview: (id?: string) =>
    post<{ ok: boolean; released: boolean }>('/api/review/release', id ? { id } : {}),

  /* ---------------- 多模型工作台设置 ---------------- */
  /* 模型档案库 + 工序绑定 + 服务商预设 + 日更目标 + 记忆开关（Key 不落盘，前端自己存 localStorage） */
  getStudio: () => request<StudioData>('/api/studio'),
  putStudio: (data: any) =>
    request<StudioData>('/api/studio', { method: 'PUT', body: JSON.stringify(data) }),

  /* ---------------- 用量与码字统计 ---------------- */
  getUsage: (days = 30) => request<UsageSummary>('/api/usage?days=' + days),
  clearUsage: () => post('/api/usage/clear', {}),
  getWritingStats: () => request<WritingStats>('/api/stats/writing'),

  /* ---------------- 提示词模板库 ---------------- */
  getPrompts: () => request<{ items: PromptItem[] }>('/api/prompts'),
  putPrompt: (key: string, text: string) =>
    request<{ key: string; overridden: boolean }>('/api/prompts',
      { method: 'PUT', body: JSON.stringify({ key, text }) }),

  /* ---------------- 敏感词 ---------------- */
  getSentinelWords: () => request<{ words: SentinelWord[] }>('/api/sentinel/words'),
  /* words 接受字符串数组，或一行一个（可带「|级别|类别」）的文本 */
  putSentinelWords: (words: string[] | string) =>
    request<{ ok: boolean; count: number }>('/api/sentinel/words', {
      method: 'PUT',
      body: JSON.stringify({
        words: Array.isArray(words)
          ? words
          : words.split('\n').map(s => s.trim()).filter(Boolean)
            .map(line => { const p = line.split('|'); return { word: p[0], level: p[1] || '中', category: p[2] || '通用' } }),
      }),
    }),
  /* text=直接扫文本；book+no=扫单章；只给 book=扫全书 */
  sentinelScan: (body: { text?: string; book?: string; no?: number }) =>
    post<SentinelResult>('/api/sentinel/scan', body),

  /* ---------------- 版本历史 ---------------- */
  getHistory: (book: string, no: number) =>
    request<HistoryList>(
      '/api/history?book=' + encodeURIComponent(book) + '&no=' + no),
  getHistoryText: (book: string, no: number, file: string) =>
    request<{ text: string; chars: number }>(
      '/api/history/text?book=' + encodeURIComponent(book) +
      '&no=' + no + '&file=' + encodeURIComponent(file)),
  getHistoryDiff: (book: string, no: number, file: string) =>
    request<{ diff: string }>('/api/history/diff?book=' + encodeURIComponent(book) +
      '&no=' + no + '&file=' + encodeURIComponent(file)),
  rollbackHistory: (book: string, no: number, file: string) =>
    post<{ ok: boolean }>('/api/history/rollback', { book, no, file }),

  /* ---------------- 跨章记忆 ---------------- */
  getMemoryStatus: (book: string) =>
    request<MemoryStatus>('/api/memory/status?book=' + encodeURIComponent(book)),
  /* q 留空 + chapter_no 时后端自动用该章大纲当检索词（预览「生成这章会拿到哪些前文」） */
  memorySearch: (book: string, q = '', chapterNo = 0) =>
    request<{ hits: MemoryHit[] }>(
      '/api/memory/search?book=' + encodeURIComponent(book) +
      '&q=' + encodeURIComponent(q) + (chapterNo ? '&chapter_no=' + chapterNo : '')),

  /* ---------------- 全书体检 ---------------- */
  reviewBatchRun: (body: { book: string; incremental?: boolean; checks?: string[];
    api_key?: string; model?: string; base_url?: string }) =>
    post<{ ok: boolean; id: string }>('/api/review/batch', body),
  getReviewBatch: (book: string) =>
    request<{ report: BatchReport | null }>('/api/review/batch?book=' + encodeURIComponent(book)),
  /* 签约预审：扫前 2 万字（≈前 10 章），程序初筛 + 一次模型复核 */
  reviewSigningRun: (body: { book: string; api_key?: string; model?: string; base_url?: string }) =>
    post<{ ok: boolean; id: string }>('/api/review/signing', body),
  getReviewSigning: (book: string) =>
    request<{ report: SigningReport | null }>('/api/review/signing?book=' + encodeURIComponent(book)),
  /* 作品级报告历史：每次执行都会留一份，弹窗里可回看当前 / 历史报告并再次执行 */
  reviewReports: (book: string, kind: ReviewReportKind) =>
    request<{ reports: ReviewReportItem[] }>(
      '/api/review/reports?book=' + encodeURIComponent(book) + '&kind=' + kind),
  reviewReport: <T = any>(book: string, kind: ReviewReportKind, file: string) =>
    request<{ report: T | null }>(
      '/api/review/report?book=' + encodeURIComponent(book) + '&kind=' + kind +
      '&file=' + encodeURIComponent(file)),

  /* ---------------- 断点恢复 ---------------- */
  resumeJob: (id: string, api_key = '') =>
    post<{ ok: boolean; id: string; stage: string; label: string; resumed_from: string }>(
      '/api/job/resume', { id, api_key }),
}

/* ---------------- 新能力类型 ---------------- */
export interface ModelProfile {
  name: string; provider: string; base_url: string; model: string
  temperature?: number | null; price_in?: number; price_out?: number
}
export interface ProviderPreset {
  provider: string; base_url: string; models: string[]
  price_in: number; price_out: number; note: string
}
export interface StudioData {
  profiles: Record<string, ModelProfile>
  bindings: Record<string, string>
  stage_models: Record<string, any>
  prices: { in: number; out: number }
  daily_goal: number
  memory: { enabled: boolean; top_k: number; max_chars: number }
  prompt_overrides: Record<string, string>
  stage_label?: Record<string, string>
  provider_presets?: ProviderPreset[]
}
export interface UsageRow {
  calls: number; prompt_tokens: number; completion_tokens: number
  elapsed: number; cost: number
}
export interface UsageSummary {
  total: { calls: number; prompt_tokens: number; completion_tokens: number; elapsed: number; estimated: number }
  cost: { all: number; currency: string; prices: { in: number; out: number } }
  by_stage: Record<string, UsageRow>
  by_model: Record<string, UsageRow>
  by_profile: Record<string, UsageRow>
  by_book: Record<string, UsageRow>
  by_day: Record<string, UsageRow>
  days: number
}
export interface WritingStats {
  goal: number; today: number; progress: number | null; streak: number
  week: { date: string; chars: number }[]
}
export interface PromptItem {
  key: string; label: string; stage: string; default: string; override: string
  effective: string; overridden: boolean; editable: boolean; note: string
}
export interface SentinelWord { word: string; level: string; category: string }
export interface SentinelHit {
  word: string; level: string; category: string; count: number
  /* 命中样例：span=[起,止] 下标；context=带【】标注的上下文片段 */
  samples?: { span: [number, number]; context: string }[]
}
export interface SentinelResult {
  hits: SentinelHit[]; total: number; n_high: number; chars?: number
  scope?: string; no?: number
  /* 全书扫描时按章汇总 */
  chapters?: { no: number; total: number; n_high: number; hits: { word: string; level: string; count: number }[] }[]
}
export interface HistoryVersion {
  file: string; ts: number; mtime_text: string; chars: number; note: string; preview: string
}
export interface HistoryList {
  versions: HistoryVersion[]
  current: { chars: number; preview: string } | null
}
export interface MemoryStatus { chapters: number; with_text: number; nouns: number; built_at: number }
export interface MemoryHit {
  no: number; title: string; score: number; matched_nouns: string[]
  summary: string; head: string; tail: string; chars: number
}
export interface BatchChapter {
  no: number; chars?: number; n_issues?: number; n_high?: number; theme?: string
  top_issues?: { type: string; severity: string; reason: string; quote: string }[]
  error?: string
}
export interface BatchReport {
  book: string; ts: number; created_at: string; checks: string[]; incremental: boolean
  n_chapters: number; n_done: number; n_skipped: number
  total_issues: number; total_high: number; chapters: BatchChapter[]
}

/* ---------------- 签约预审（跨章扫前 2 万字） ---------------- */
export interface SigningCheck {
  key: string; label: string
  level: '通过' | '警告' | '高危' | '未检'
  detail: string
}
export interface SigningReport {
  kind: 'signing_precheck'; book: string
  window_chapters: number; chars: number
  verdict: string; verdict_why: string
  checks: SigningCheck[]
  issues: { sev: string; chapter: number; msg: string }[]
  created: string
}

/* ---------------- 作品级报告历史（全书体检 / 签约预审） ---------------- */
export type ReviewReportKind = 'batch' | 'signing'
export interface ReviewReportItem {
  file: string; mtime: number; created_at: string
  /* 全书体检 */
  n_chapters?: number; n_done?: number; n_skipped?: number
  total_issues?: number; total_high?: number; incremental?: boolean
  /* 签约预审 */
  verdict?: string; chars?: number; window_chapters?: number
  n_issues?: number; n_high?: number
}

/** 任务中心：全部任务（含已结束的，新的在前） */
export function listJobs() {
  return request<{ jobs: JobSummary[]; running: number; max_running: number }>('/api/jobs')
}
/** 轮询某个任务自己的实时日志：多任务并发时各页面互不串台 */
export function pollJobById(id: string, since = 0) {
  return request<JobState>('/api/job?id=' + encodeURIComponent(id) + '&since=' + since)
}
/** 审查任务状态：按任务 id 精确取；没给 id 时按「书 + 章」取本章最近一条 */
export function pollReview(since: number, id = '', book = '', chapterNo: string | number = '') {
  return request<ReviewJobState>('/api/review/job?since=' + since +
    (id ? '&id=' + encodeURIComponent(id) : '') +
    (book ? '&book=' + encodeURIComponent(book) : '') +
    (chapterNo ? '&chapter_no=' + encodeURIComponent(String(chapterNo)) : ''))
}
/** 选区任务记录的「选中哪一段」：原文 + 起止 + 前后文 */
export interface ExpandTarget {
  start: number
  end: number
  text: string
  before?: string
  after?: string
}

/** 正文生成任务状态（含上次任务快照，供页面切换/刷新后保持状态） */
export interface ExpandJobState {
  /** 这条页内任务自己的 id：多任务并发时按它回显 / 停止 */
  id: string
  running: boolean
  book: string
  chapter_no: number | null
  mode: string
  /** chapter=整章生成 / selection=选区改写（决定候选进「整章候选」还是「选区候选」） */
  scope?: 'chapter' | 'selection'
  /** 后端给的任务名，如「改写选区」「整章润色」「生成正文」 */
  name?: string
  multi: boolean
  versions: { text: string; note: string; chars: number }[]
  recommended: number
  /** 选区任务的原选区（起止 + 原文）：切书回来要按它恢复「采纳」落点 */
  target?: ExpandTarget | null
  /** 生成前的正文（整章续写采纳时要接在它后面） */
  existing?: string
  code: number | null
  error: string | null
  stopped: boolean
  text: string
  total: number
  started_at: number
  finished_at: number
  elapsed: number
  last: null | {
    book: string
    chapter_no: number | null
    /** 任务名（如「改写选区」），落盘快照里也带着，状态条文案不会空 */
    name?: string
    mode: string
    scope?: 'chapter' | 'selection'
    multi: boolean
    code: number | null
    error: string | null
    stopped: boolean
    versions: { text: string; note: string; chars: number }[]
    recommended: number
    target?: ExpandTarget | null
    existing?: string
    versions_count: number
    chars: number
    started_at: number
    finished_at: number
    saved_at: number
  }
}
/** 正文生成状态：按任务 id 精确取（并发时各章互不串台）；没给 id 时按「书 + 章」取本章最近一条 */
export function pollExpand(since: number, book = '', id = '', chapterNo: string | number = '') {
  return request<ExpandJobState>('/api/expand/job?since=' + since +
    (book ? '&book=' + encodeURIComponent(book) : '') +
    (id ? '&id=' + encodeURIComponent(id) : '') +
    (chapterNo ? '&chapter_no=' + encodeURIComponent(String(chapterNo)) : ''))
}
