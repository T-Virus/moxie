// 与后端 src/webapp.py 约定的数据结构

export interface SourceFile {
  name: string
  size: number
}

export interface WeekPoint {
  date: string
  chars: number
}

export interface BookSummary {
  name: string
  title: string
  has_chapters: boolean
  has_decomposed: boolean
  n_chapters: number
  n_cards: number
  n_factions: number
  n_items?: number
  last_chapter_no: number
  last_chapter_title: string
  status: string
  author: string
  synopsis: string
  has_cover: boolean
  n_manuscripts: number
  ms_by_no: Record<string, { chars: number; mtime: string; title?: string }>
  manuscript_chars: number
  n_reviews: number
  mtime: number
  mtime_text: string
  week: WeekPoint[]
}

export interface Stats {
  books: BookSummary[]
  sources: number
}

/* AI 封面：平台制式、出图模型、文字风格、版式（后端 /api/cover/presets） */
export interface CoverOption {
  key: string
  name: string
  note?: string
}

export interface CoverPlatform extends CoverOption {
  width: number
  height: number
  fmt: string
}

export interface CoverPresets {
  platforms: CoverPlatform[]
  models: CoverOption[]
  styles: CoverOption[]
  layouts: CoverOption[]
  min_side: number
  max_side: number
  max_bytes: number
  font: string
}

export interface CoverResult {
  ok: boolean
  width: number
  height: number
  fmt: string
  bytes: number
  model: string
  /** 底图来源：ai = 配置的模型 / pollinations = 默认出图 / local = 本地绘制 / cached = 复用上次底图 */
  source?: 'ai' | 'pollinations' | 'local' | 'cached'
  /** 实际用上的 AI 模型名（source=ai 时） */
  ai_model?: string
  /** AI 模型出图失败、回退到默认链路时的原因 */
  ai_note?: string
  /** 出图接口不可用、已用本地代码绘制底图时为 true */
  fallback?: boolean
  /** 降级说明（含出图失败原因），正常生成时为空串 */
  notice?: string
  prompt_zh: string
  prompt_en: string
  translated: boolean
  theme: string
  matched: string[]
  style: string
  layout: string
  font: string
  elapsed: number
}

export interface Chapter {
  no?: number | string
  title?: string
  summary?: string
  points?: string[]
  roles?: string[]
  factions?: string[]
  /** 本章出现 / 使用的道具、功法、战技名称（引用道具功法表） */
  items?: string[]
  scene?: string
  conflict?: string
  hook?: string
  /** 章末钩子类型：悬念 / 危机 / 反转 / 期待 / 信息差 / 情感 */
  hook_type?: string
  /** 情绪主线，词表内 2~3 个词用 → 连起来，如「憋屈→怒→爽」 */
  emotion?: string
  /** 情绪峰值 1~10（0 = 未标注） */
  tension?: number
  /** 本章兑现的爽点 / 情绪释放 */
  payoff?: string
  /** 本章埋下的铺垫 / 伏笔 */
  setup?: string
  chapter_id?: string
  [k: string]: any
}

export type FieldTuple = [string, string]

/** 道具 / 功法卡：与角色卡、势力卡同级，拆解 / 改编时一起提取 */
export interface ItemCard {
  name?: string
  /** 类别：剧情道具 / 武学功法 / 战技 / 兵器 / 丹药 / 法宝 / 线索 / 其他 */
  kind?: string
  grade?: string
  /** 持有者 / 习得者（引用角色卡） */
  owner?: string
  /** 所属势力（引用势力表） */
  faction?: string
  chapter?: string | number
  effect?: string
  origin?: string
  desc?: string
  [k: string]: any
}

/** 批量改名：旧名 → 新名（空串表示删除后清空引用） */
export type RenameMap = Record<string, string>

export interface ChaptersData {
  chapters: Chapter[]
  book?: string
  story_bible?: string
  story_bible_fields?: Record<string, string>
  story_bible_cards?: Record<string, string>[]
  story_bible_factions?: Record<string, string>[]
  items?: ItemCard[]
  /** 批量改名 / 删除：服务端统一把章节与关系里的引用一起改掉 */
  renames?: Record<string, RenameMap>
  [k: string]: any
}

export interface SbSchema {
  sb_fields: FieldTuple[]
  card_fields: FieldTuple[]
  faction_fields: FieldTuple[]
  labels: Record<string, string>
  /* 角色：九宫格人设倾向 9 类 / 剧情功能 10 类，[key, 中文词, 释义] */
  card_alignments?: [string, string, string][]
  card_roles?: [string, string, string][]
  /* 关系类型 18 类：[key, 中文词, 释义, 例子]；relation_types 是兼容旧前端的中文词列表 */
  card_relation_kinds?: [string, string, string, string][]
  relation_types?: string[]
  relation_directions?: [string, string][]
  relations_hint?: string
  alignment_axes?: { rows: string[]; cols: string[] }
  /* 势力：大类 10 类 / 立场 9 类 / 势力关系 10 类，[key, 中文词, 释义(例子)] */
  faction_categories?: [string, string, string][]
  faction_stances?: [string, string, string][]
  faction_rel_types?: [string, string, string, string][]
  faction_relations_hint?: string
  /* 道具功法：字段 / 类别 / 分组，[key, 中文词, 释义] */
  item_fields?: FieldTuple[]
  item_kinds?: [string, string, string][]
  item_groups?: [string, string[]][]
  item_label?: string
  /* 表单分组：[[组名, [字段key…]], …]，顺序即展示顺序 */
  card_groups?: [string, string[]][]
  faction_groups?: [string, string[]][]
  card_label?: string
  faction_label?: string
}

export interface ReviewOptions {
  checks: string[]
  labels: Record<string, string>
  no_call: string[]
  advice_scopes: Record<string, string[]>
}

export interface ReviewBaseline {
  book: string
  chapter_no: any
  chapter_id?: string
  title?: string
  chapter_summary?: string
  chapter_points?: string[]
  chapter_scene?: string
  chapter_roles?: string[]
  synopsis_preview?: string
  has_synopsis: boolean
  has_chapter_summary: boolean
  has_setting: boolean
  n_cards: number
  n_factions: number
  n_chapters: number
  setting_keys?: string[]
  notes?: string[]
}

export interface ReviewIssue {
  type: string
  type_label?: string
  kind?: string
  category?: string
  ref?: string
  severity?: string
  sid?: string
  quote?: string
  suggest?: string
  reason?: string
}

export interface ReviewResult {
  meta?: any
  theme?: { level?: string; summary?: string }
  risk?: { n_high?: number; n_risk?: number }
  stats?: any
  issues?: ReviewIssue[]
  skipped?: { label: string; reason: string }[]
  disclaimer?: string
  [k: string]: any
}

export interface OutputFile {
  name: string
  path: string
  size: number
  /** 来源：书名（data/<书名>/…）或旧批次名，旧根数据为「旧根数据」 */
  group: string
  book?: string
  /** core=拆解数据 / review=审查报告 / manuscript=正文 / batch=历史批次 */
  kind?: string
  /** 类别中文标签：章节数据 / 全书设定 / AI 审查报告 / 正文扩写 / 历史批次 / 旧数据 */
  label?: string
}

/** /api/outputs 响应：page 缺省时为全量（书内页面用），带 page 时只返回该页 */
export interface OutputsResp {
  files: OutputFile[]
  total: number
  groups: string[]
  page?: number
  page_size?: number
  page_count?: number
}

export interface JobState {
  id: string
  running: boolean
  stage?: string
  label?: string
  book?: string
  out_book?: string
  code?: number | null
  queued?: string[]
  lines: string[]
  total: number
  error?: string | null
  stopped?: boolean
  created_at?: number
  finished_at?: number
  result?: ReviewResult
  files?: Record<string, string>
}

/** 任务中心用的轻量任务摘要（不含日志正文） */
export interface JobSummary {
  id: string
  stage: string
  label: string
  /* 纯任务名（动词短语，如「生成正文」「程序体检」），不带书名 / 章节 */
  name?: string
  book: string
  out_book?: string
  running: boolean
  code: number | null
  error: string | null
  stopped: boolean
  total: number
  created_at: number
  finished_at: number
  /* 页内通道任务（AI 审查 / 正文生成）：带章节号，跳转时能直接定位到那一章 */
  channel?: 'page'
  /* 发起这个任务时所在的页面（hash 路由），任务中心 / 悬浮条按它跳回去 */
  origin?: string
  chapter_no?: string
  /* 服务重启时正在跑的任务会被标记「中断」；子进程类任务（拆解/改编/扩写/图谱）可一键恢复 */
  interrupted?: boolean
  resumable?: boolean
}

/** AI 审查任务状态：额外带归属书 / 章，供切页、换书时按章精确接管或回显 */
export interface ReviewJobState extends JobState {
  book: string
  chapter_no: string
}
