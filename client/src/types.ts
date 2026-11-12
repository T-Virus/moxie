/** 与后端固定的接口契约类型；workspace 内容字段为客户端可选扩展，缺失时降级展示。 */

export type Audience = 'male' | 'female'
export type RunLength = 'long' | 'short'
export type RunMode = 'hot' | 'reference' | 'custom'
/** 与 server 端 RUN_STATUSES 保持一致：queued/running/paused/succeeded/failed/canceled */
export type RunStatus =
  | 'queued'
  | 'running'
  | 'paused'
  | 'succeeded'
  | 'failed'
  | 'canceled'

/** 与 server 端 step 状态对齐：done 在接口中映射为 succeeded */
export type StageState = 'pending' | 'running' | 'succeeded' | 'failed' | 'skipped'
export type LogLevel = 'info' | 'warn' | 'error' | 'success'

export interface GenreItem {
  id: string
  name: string
  audience: Array<Audience | 'all'>
  tags: string[]
}

export interface GenresResponse {
  items: GenreItem[]
  custom_allowed: boolean
  /** 接口未就绪时前端使用内置预设，并把原因透传给页面 */
  degraded?: string
}

export interface GenreSelection {
  id: string | null
  name: string
}

export interface CreateRunOptions {
  /** 目标章数；留空按篇幅默认（长篇 12 / 短篇 6） */
  target_chapters?: number
  /** 续写新章数，追加在目标章数之后 */
  sequel_chapters?: number
  /** 参考改编的文风/方向 */
  adaptation_style?: string
  /** 参考改编的额外要求 */
  adaptation_extra?: string
}

export interface CreateRunPayload {
  mode: RunMode
  title: string
  audience: Audience
  length: RunLength
  genre: GenreSelection
  source_key?: string | null
  brief?: string | null
}

export interface CreateRunResponse {
  run_id: string
  /** 幂等命中已有运行时可能回传当前状态，而不是固定的 queued */
  status: RunStatus
  mode: RunMode
  created_at: string
  /** 服务端在幂等命中时会返回 false */
  created?: boolean
}

export interface Stage {
  id: string
  name: string
  state: StageState
  started_at: string | null
  finished_at: string | null
}

export interface QuotaInfo {
  metric: string
  limit: number
  used: number
  reserved: number
}

export interface Artifact {
  name: string
  kind: string
  size: number
}

export interface RunSummaryBlock {
  logline: string
  chapters_count: number
  characters_count: number
  /** 道具功法条数（服务端新增，旧数据可能没有） */
  items_count?: number
  /** 正文字数合计（服务端新增，旧数据可能没有） */
  word_count?: number
  /** 最近一次章节完成时间（服务端新增，旧数据可能没有） */
  updated_at?: string | null
  /** 参考写作全量分段数（旧数据可能没有） */
  segments_count?: number
  /** 热门写作前三章概览章数（旧数据可能没有） */
  preview_chapters_count?: number
}

/** 以下内容结构不是契约必选字段：真实后端逐步补齐，缺失时前端展示降级提示。 */
export interface ChapterContent {
  no: number
  title: string
  summary?: string
  content?: string
  words?: number
  /** 核心冲突（章节概括页） */
  conflict?: string
  /** 章末钩子 */
  hook?: string

  /* ---- 离线版章节字段（decomposed/chapters 落盘） ---- */
  /** 章节标识，如 ch-001 */
  chapter_id?: string
  /** 本章场景 */
  scene?: string
  /** 关键事件 */
  key_events?: string[]
  /** 情节要点（chapters.json points） */
  points?: string[]
  /** 本章角色 */
  roles?: string[]
  /** 本章势力 */
  factions?: string[]
  /** 本章道具 */
  items?: string[]
  /** 钩子类型 */
  hook_type?: string
  /** 情绪主线 */
  emotion?: string
  /** 张力值 0~10 */
  tension?: number
  /** 本章兑现 */
  payoff?: string
  /** 本章铺垫 */
  setup?: string
  /** 章节阶段 / 弧光位置（outline.chapters.arc） */
  arc?: string

  /* ---- docs 组5 规划字段（服务端未产出时显示占位） ---- */
  chapter_function?: string
  chapter_goal?: string
  beat_type?: string
  pov?: string
  time_span?: string
  word_target?: number
  word_actual?: number
  payoff_type?: string
  payoff_owner?: string
  payoff_intensity?: number
  tear_point?: string
  sweet_point?: string
  twist?: string
  new_characters?: string[]
  new_items?: string[]
  new_settings?: string[]
  foreshadow_ids?: string[]
  continuity_check?: string
  chapter_status?: string
  revision_note?: string
}

/** 服务端 chapter_summarize 的逐章概括（字段名 chapter_no，映射后为 no） */
export interface ChapterSummary {
  no: number
  title: string
  summary?: string
  conflict?: string
  hook?: string
  words?: number
  chapter_id?: string
  scene?: string
  key_events?: string[]
  points?: string[]
  roles?: string[]
  factions?: string[]
  items?: string[]
  hook_type?: string
  emotion?: string
  tension?: number
  payoff?: string
  setup?: string
  arc?: string
  chapter_function?: string
  chapter_goal?: string
  beat_type?: string
  pov?: string
  time_span?: string
  word_target?: number
  word_actual?: number
  payoff_type?: string
  payoff_owner?: string
  payoff_intensity?: number
  tear_point?: string
  sweet_point?: string
  twist?: string
  new_characters?: string[]
  new_items?: string[]
  new_settings?: string[]
  foreshadow_ids?: string[]
  continuity_check?: string
  chapter_status?: string
  revision_note?: string
}

/** 大纲逐章节点（outline 技能产出，可与 chapter_summaries 按章号合并） */
export interface OutlineChapter {
  no: number
  title: string
  summary?: string
  key_events?: string[]
  hook?: string
  arc?: string
}

/** 卷（可选契约）：服务端未下发时前端按章节聚合为单卷 */
export interface VolumeContent {
  /** 卷序号，缺省按数组顺序 */
  no?: number
  /** 卷名，如「第一卷」 */
  title?: string
  /** 卷概括 */
  summary?: string
  /** 卷冲突主线 */
  conflict?: string
  /** 起始章号 */
  chapter_from?: number
  /** 结束章号 */
  chapter_to?: number
  /** 该卷下的逐章概括；缺省时按章号区间取全书章节 */
  chapters?: ChapterSummary[]

  /* ---- docs 组5 规划字段（服务端未产出时显示占位） ---- */
  /** 卷主题 */
  theme?: string
  /** 卷核心事件 */
  core_event?: string
  /** 卷矛盾轴 */
  conflict_axis?: string
  /** 卷末钩子 */
  end_hook?: string
  /** 卷内人物弧光 */
  arc?: string
  /** 卷节奏曲线 */
  tension_profile?: string
}

export interface CharacterContent {
  name: string
  /** 别名 / 曾用名 */
  alias?: string
  /** 身份（主角、关键配角…） */
  role?: string
  /** 角色类型：主角 / 配角 / 反派 / 群像 */
  type?: string
  gender?: string
  /** 阵营 */
  camp?: string
  /** 所属势力（离线 factionName / 服务端 affiliation 统一映射到这里） */
  faction?: string
  /** 势力名称原始字段（保留离线 factionName，展示统一用「势力名称」） */
  faction_name?: string
  personality?: string
  goal?: string
  first_chapter?: number
  /** 关系标签，如「兄妹」「宿敌」 */
  relations?: string[]
  description?: string

  /* ---- 旧客户端角色卡字段 ---- */
  race?: string
  /** 身份背景（年龄等常混在其中） */
  identity?: string
  /** 人设倾向：守序善良… */
  alignment?: string
  /** 对主角态度 */
  stance?: string
  /** 势力大类 */
  faction_category?: string
  /** 下属分支 */
  sub_faction?: string
  /** 忠诚度 0~1 */
  loyalty?: number
  join_chapter?: number
  leave_chapter?: number
  /** 关系对象 */
  relation_to?: string
  relation_type?: string
  relation_direction?: string
  /** 关系强度 0~1 */
  relation_strength?: number
  relation_public?: boolean
  /** 关系确立章节 */
  relation_chapter?: number
  /** 说话风格 */
  speech?: string
  /** 口头禅与常用词 */
  catchwords?: string
  /** 弱点 */
  weakness?: string

  /* ---- 新增补全字段（docs/大纲字段总表 组3） ---- */
  age?: number
  appearance?: string
  quirks?: string[]
  strengths?: string[]
  flaws?: string[]
  core_desire?: string
  core_fear?: string
  backstory?: string
  /** 隐藏身份或秘密 */
  secret?: string
  /** 人物弧光（兼容字符串） */
  arc?: string
  /** 人物弧光结构化字段（docs 组3 arc.*） */
  arc_detail?: {
    type?: string
    start_state?: string
    turning_points?: string[]
    end_state?: string
    final_fate?: string
  }
  obstacle_methods?: string[]
  exit_reason?: string
  voice_sample?: string[]
  /** 视角章节（docs 组3 pov_chapters） */
  pov_chapters?: number[]
  /** 检索/筛选标签 */
  tags?: string[]
}

export interface FactionMember {
  name: string
  role?: string
  relation?: string
}

export interface FactionContent {
  name: string
  /** 势力类型：门派 / 家族 / 组织 / 王朝 */
  type?: string
  /** 势力大类：门派 / 商会 / 官方机构 / 隐秘组织… */
  category?: string
  leader?: string
  stance?: string
  territory?: string
  /** 势力诉求 / 目标（服务端 lore_extract 产出） */
  goal?: string
  members_count?: number
  first_chapter?: number
  description?: string
  members?: FactionMember[]
  /** 关联势力 */
  rel_to?: string
  /** 势力关系类型（结盟 / 敌对 / 附庸…） */
  rel_type?: string
  /** 关系强度 0~1 */
  rel_strength?: number
  /** 关系是否公开 */
  rel_public?: boolean
  /** 其他势力关系，如「第七调查组：敌对」 */
  relations?: string[]
}

export interface ItemContent {
  name: string
  /** 类别：功法 / 道具 / 丹药 / 兵器 */
  category?: string
  /** 品阶：凡品 / 灵品 / 玄品 / 天品 */
  grade?: string
  /** 归属角色或势力 */
  owner?: string
  /** 当前持有者 */
  holder?: string
  /** 所属势力 */
  faction?: string
  effect?: string
  cost?: string
  /** 来历 */
  origin?: string
  /** 数量 / 使用限制等备注 */
  note?: string
  first_chapter?: number
  /** 出现过的章节 */
  chapters?: number[]
  description?: string
  /** 关键道具后期作用（docs 组7 new，服务端未产出时占位） */
  payoff?: string
}

export interface WorldviewGroup {
  group?: string
  points?: Array<{ text?: string; chapters?: number[] }>
}

export interface MapRegion {
  name?: string
  parent?: string
  kind?: string
  desc?: string
  chapters?: number[]
}

export interface MapScene {
  chapter?: number
  region?: string
  characters?: string[]
  factions?: string[]
  items?: string[]
  event?: string
}

export interface PlotBlock {
  timeline?: string[]
  mainline?: string[]
  subplots?: string[]
  conflict?: string[]
  suspense?: string[]
  foreshadow?: string[]
}

export interface IndexEntry {
  chapter?: number
  text?: string
  type?: string
}

export interface ForeshadowEntry {
  text?: string
  seed?: string
  payoff?: string
  chapter?: number
  status?: string
}

export interface TimeEvent {
  chapter?: number
  text?: string
  is_volume?: boolean
}

export interface EmotionPoint {
  chapter?: number
  tension?: number
  emotion?: string
  hook?: string
}

export interface ItemLink {
  item?: string
  from?: string
  to?: string
  note?: string
  chapter?: number
}

export interface OpeningInfo {
  strategy?: string
  first_image?: string
  golden_finger_demo?: number
}

export interface SigningCheck {
  score?: number
  risk?: string
  suggestions?: string[]
  issues?: string[]
}

export interface OutlineContent {
  logline?: string
  themes?: string[]
  beats?: string[]
  /** 正式书名 / 备选书名（docs 组0） */
  book_title?: string
  title_alternatives?: string[]
  /** 全书梗概（D:book_summary） */
  book_summary?: string
  author?: string
  status?: string
  /** 时代背景（S:era） */
  era?: string
  /** 知识图谱是否 AI 生成（S:ai） */
  ai?: boolean
  /** 章节总数（S:n_chapters） */
  n_chapters?: number
  generated_at?: string
  source_type?: string
  language?: string
  schema_version?: string
  rights_status?: string
  /** 开篇设计（D:opening / C:opening） */
  opening?: OpeningInfo
  /** 题材与基调（story_bible.genre） */
  genre_tone?: string
  /** 作品基调 */
  tone?: string
  /** 作品简介（story_bible.synopsis） */
  synopsis?: string
  /** 目标读者画像（story_bible.audience） */
  audience?: string
  type_primary?: string
  type_secondary?: string[]
  core_hook?: string
  target_platform?: string[]
  /** 平台风格参数（docs 组1 new） */
  platform_style?: Record<string, unknown>
  target_reader_age?: string
  target_reader_gender?: string
  estimated_words?: number
  length_class?: string
  total_chapters_planned?: number
  chapter_words_target?: number
  serialization_pace?: string
  update_frequency?: string
  content_rating?: string
  series_plan?: string
  keywords?: string[]
  aigc_disclosure?: string
  /** 叙事人称 */
  person?: string
  /** 文风与语言 */
  style?: string
  /** 世界观与时代背景 */
  world?: string
  /** 力量体系与金手指 */
  power?: string
  /** 核心冲突 */
  conflict?: string
  /** 核心悬念 */
  suspense?: string
  /** 全书主线 */
  mainline?: string
  /** 写作禁忌与铁律 */
  taboos?: string

  /* ---- 仅「作品大纲」分组回显（作品信息页不重复展示） ---- */
  /** 支线与情感线 */
  subplots?: string
  /** 主角设定 */
  protagonist?: string
  /** 主要配角 */
  supporting?: string
  /** 主要反派 */
  antagonist?: string
  /** 伏笔与回收 */
  foreshadow_text?: string
  /** 重要地点 */
  places?: string
  /** 关键道具（文本，story_bible.items） */
  items_text?: string
  /** 专有名词表 */
  terms?: string
  /** 时间线 */
  timeline?: string
  /** 地图设定 */
  map_text?: string
  /** 规则分组（S:worldview） */
  worldview?: WorldviewGroup[]
  /** 地图层级（S:map.levels） */
  map_levels?: string[]
  /** 区域结构（S:map.regions） */
  map_regions?: MapRegion[]
  /** 章节场景映射（S:map.scenes） */
  map_scenes?: MapScene[]
  /** 核心主题 */
  theme_core?: string
  /** 主题命题 */
  theme_statement?: string
  /** 卖点三句话 */
  selling_points?: string[]
  /** 创新点 */
  innovation_points?: string[]
  /** 结局类型 */
  ending_type?: string
  /** 对标作品 */
  comparative_titles?: string[]
  /** 结局后的世界 */
  ending_state?: string
  /** 主角最终命运 */
  protagonist_final_fate?: string
  /** 剧情结构（S:plot） */
  plot?: PlotBlock
  /** 卷划分（S:volumes） */
  volumes?: VolumeContent[]
  /** 钩子索引（S:hooks） */
  hooks?: IndexEntry[]
  /** 铺垫索引（S:setups） */
  setups?: IndexEntry[]
  /** 兑现索引（S:payoffs） */
  payoffs?: IndexEntry[]
  /** 连续性冲突（S:conflicts） */
  conflicts?: IndexEntry[]
  /** 伏笔台账（S:foreshadows） */
  foreshadows?: ForeshadowEntry[]
  /** 时间轴事件（S:timeEvents） */
  time_events?: TimeEvent[]
  /** 情绪与张力曲线（S:emotionCurve） */
  emotion_curve?: EmotionPoint[]
  /** 道具流向（S:itemLinks） */
  item_links?: ItemLink[]
  /** 签约体检（C:signing_check） */
  signing_check?: SigningCheck
  /** 完整性校验（docs 组8） */
  completeness_check?: {
    missing_fields?: string[]
    unfilled_payoff?: string[]
    unrecovered?: string[]
    arc_missing?: string[]
    no_hook?: string[]
  }
  /** 大纲完整度评分（docs 组8） */
  qa_score?: number
  /** 大纲逐章节点，用于与 chapter_summaries 合并字段 */
  chapters?: OutlineChapter[]
}

/** 通用集合编辑弹窗的字段定义（人物/势力/道具/卷章概览复用） */
export interface CollectionField {
  key: string
  label: string
  type?: 'text' | 'textarea' | 'number' | 'tags' | 'select'
  required?: boolean
  placeholder?: string
  presets?: string[]
  /** select 类型的备选项（带真实值与展示文案），优于 presets 文本 */
  options?: { value: string; label: string }[]
  full?: boolean
  rows?: number
  min?: number
  maxlength?: number
  hint?: string
}

export interface RunDetail {
  run_id: string
  mode: RunMode
  title: string
  audience: Audience
  length: RunLength
  genre: GenreSelection
  /** 创作高级选项（目标章数 / 续写 / 改编方向） */
  options?: CreateRunOptions
  status: RunStatus
  /** 作品信息里维护的连载状态：连载中 / 已签约 / 已完结 */
  status_label?: string
  progress: number
  /** GET 契约未强制，列表页/排序使用；缺失时展示「—」 */
  created_at?: string
  stages: Stage[]
  current_stage: string | null
  quota: QuotaInfo | null
  artifacts: Artifact[]
  summary: RunSummaryBlock | null
  error: { code?: string; message?: string } | null
  // 可选扩展
  chapters?: ChapterContent[]
  chapter_summaries?: ChapterSummary[]
  /** 卷章概览中手工删除的章号（仅隐藏概览，不影响正文） */
  chapter_hidden?: number[]
  /** 卷划分；服务端未下发时由前端按章节聚合为单卷 */
  volumes?: VolumeContent[]
  characters?: CharacterContent[]
  factions?: FactionContent[]
  items?: ItemContent[]
  outline?: OutlineContent
  /** 封面图（配置或产物），缺失时前端用书名首字生成占位封面 */
  cover_url?: string
  /** AI 封面元信息：来源、尺寸、提示词等 */
  cover?: RunCover | null
  /** 最近一次运行更新时间 */
  updated_at?: string
  /** 服务端开始执行时间；旧接口可能缺失 */
  started_at?: string | null
  /** 服务端结束时间；未结束或旧接口缺失时为空 */
  finished_at?: string | null
  /** 服务端直接给出的总耗时（秒），存在时优先展示 */
  duration_seconds?: number | null
}

export interface RunCover {
  fmt?: string
  width?: number
  height?: number
  size?: number
  /** ai | pollinations | local */
  source?: string
  model?: string
  fallback?: boolean
  prompt?: string
  style?: string
  layout?: string
  updated_at?: string
  notice?: string
}

export interface RunEvent {
  seq: number
  stage: string
  level: LogLevel
  message: string
  at: string
}

export interface UploadResponse {
  source_key: string
  filename: string
  size: number
  content_type: string
}

export interface ResumePayload {
  input?: { chapter_no: number; content: string }
  approval?: boolean
}

/* ---------- 认证 / 订阅（沿用现服务端路径） ---------- */

export interface Account {
  id: number
  email: string | null
  phone: string | null
  status: string
  role: string
  created_at: string | null
}

export interface AuthResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  refresh_expires_in: number
  account: Account
}

export interface PlanEntitlement {
  key: string
  limit: number
  unit: string
  reset_period: string
}

export interface Plan {
  code: string
  name: string
  price_month_cents: number
  price_year_cents: number
  currency: string
  /** 服务端实际返回字典：{"managed":false,"support":"community"} */
  features: string[] | Record<string, string | boolean | number>
  entitlements: PlanEntitlement[]
  /** 套餐定位描述（服务端未返回时客户端按 code 兜底） */
  description?: string
  /** 推荐标记（服务端未返回时按 code 兜底） */
  recommended?: boolean
  /** 最划算标记 */
  best_value?: boolean
}

export interface Subscription {
  id: number
  status: string
  plan: { code: string; name: string }
  seats: number
  cancel_at_period_end: boolean
  current_start_at: string
  current_end_at: string
  days_left: number
  provider: string
  version: number
  renewal_reminder?: boolean
}

export interface PaymentProviderOption {
  id: string
  name: string
  /** mock/fake 仅测试环境出现 */
  test_only: boolean
}

export interface QuotaMetric {
  metric: string
  unit: string
  limit: number
  used: number
  reserved: number
  remaining: number
  pack_remaining?: number
  total_remaining?: number
}

export interface CreditPack {
  metric?: string
  remaining?: number
  [key: string]: unknown
}

export interface QuotaSummary {
  plan: { code: string; name: string; status: string } | null
  period_start: string
  period_end: string
  metrics: QuotaMetric[]
  /** 服务端 /v1/entitlements 的额度包合并视图字段名是 credits */
  credits?: CreditPack[]
  packs?: CreditPack[]
  server_time?: string
}

export interface RunListResult {
  items: RunDetail[]
  /** 服务端返回的命中总数（未翻页），列表页「共 N 部」以此为准 */
  total?: number
  /** 下一页起始偏移；无更多数据时为空 */
  next_offset?: number
  /** 服务端尚未提供列表接口时，使用本地记录并给出可读说明 */
  degraded?: string
}
