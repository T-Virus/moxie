/**
 * Agent 接口层：页面只调用这里，全部数据来自在线服务端。
 * SSE 用 fetch + ReadableStream 解析，便于携带 Authorization（EventSource 无法带请求头）。
 */
import type {
  Audience,
  ChapterContent,
  ChapterSummary,
  CharacterContent,
  CreateRunPayload,
  CreateRunResponse,
  EmotionPoint,
  FactionContent,
  FactionMember,
  ForeshadowEntry,
  GenresResponse,
  GenreSelection,
  IndexEntry,
  ItemContent,
  ItemLink,
  MapRegion,
  MapScene,
  OpeningInfo,
  OutlineChapter,
  OutlineContent,
  PlotBlock,
  RunDetail,
  RunEvent,
  RunLength,
  RunListResult,
  RunMode,
  ResumePayload,
  SigningCheck,
  TimeEvent,
  UploadResponse,
  VolumeContent,
  WorldviewGroup,
} from '@/types'
import { API_BASE } from './config'
import {
  ApiError,
  apiDownload,
  apiFetch,
  extractError,
  getAccessToken,
} from './http'
import {
  decryptJson,
  decryptSse,
  getPayloadSession,
  payloadHeaders,
  type PayloadSession,
} from './payloadCrypto'

export async function fetchGenres(): Promise<GenresResponse> {
  return apiFetch<GenresResponse>('/genres')
}

export async function createRun(payload: CreateRunPayload): Promise<CreateRunResponse> {
  const idempotencyKey =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `idem_${Date.now()}_${Math.random().toString(36).slice(2)}`

  const headers: Record<string, string> = { 'Idempotency-Key': idempotencyKey }
  if (payload.mode === 'reference') {
    // 参考写作会把用户上传的作品用于改编，服务端版权闸门要求显式确认；
    // 缺少该头会返回 422 rights_confirmation_required（生产环境不可关闭）。
    headers['X-Rights-Confirmed'] = 'true'
  }
  return apiFetch<CreateRunResponse>('/agent-runs', {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
  })
}

export async function uploadSource(file: File): Promise<UploadResponse> {
  const form = new FormData()
  form.append('file', file)
  return apiFetch<UploadResponse>('/uploads', { method: 'POST', body: form })
}

type RawRun = Omit<
  RunDetail,
  'chapters' | 'chapter_summaries' | 'characters' | 'factions' | 'items' | 'outline'
> & {
  chapters?: Array<Record<string, unknown>>
  chapter_summaries?: Array<Record<string, unknown>>
  characters?: Array<Record<string, unknown>>
  factions?: Array<Record<string, unknown>>
  items?: Array<Record<string, unknown>>
  outline?: Record<string, unknown> | null
  story_bible?: Record<string, unknown> | null
}

function str(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function num(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

/** 技能产出可能是数组，也可能被模型写成单个对象，统一收敛为列表。 */
function recordList(value: unknown): Array<Record<string, unknown>> {
  if (Array.isArray(value)) {
    return value.filter((item): item is Record<string, unknown> => !!item && typeof item === 'object')
  }
  if (value && typeof value === 'object') return [value as Record<string, unknown>]
  return []
}

/** 服务端关系是 [{target,type}]，客户端展示为「对象（关系）」字符串。 */
function relationLabels(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value
    .map((rel) => {
      if (typeof rel === 'string') return rel.trim()
      if (!rel || typeof rel !== 'object') return ''
      const item = rel as Record<string, unknown>
      const target = str(item.target) || str(item.name) || str(item.to)
      const type = str(item.type) || str(item.relation) || str(item.kind)
      if (!target) return ''
      return type ? `${target}（${type}）` : target
    })
    .filter(Boolean)
}

/** 字符串列表：兼容数组与「换行 / 分号 / 竖线」分隔的落盘形式。 */
function listText(...values: unknown[]): string[] {
  const out: string[] = []
  for (const value of values) {
    if (Array.isArray(value)) {
      value.forEach((item) => {
        const text = str(item)
        if (text) out.push(text)
      })
      continue
    }
    if (typeof value === 'string') {
      value
        .split(/[\n；;｜|]/)
        .map((item) => item.trim())
        .filter(Boolean)
        .forEach((item) => out.push(item))
    }
  }
  return out
}

function listNum(...values: unknown[]): number[] {
  for (const value of values) {
    if (Array.isArray(value)) {
      const list = value
        .map((item) => num(item) ?? (typeof item === 'string' ? Number(item) : undefined))
        .filter((item): item is number => typeof item === 'number' && Number.isFinite(item))
      if (list.length) return list
    }
  }
  return []
}

/** 章节扩展字段：离线版 decomposed/chapters.json 与 docs 组5 的字段名兼容。 */
function chapterExtra(item: Record<string, unknown>) {
  const keyEvents = listText(item.key_events, item.keyEvents)
  const points = listText(item.points, item.beats)
  const roles = listText(item.roles, item.characters)
  return {
    chapter_id:
      str(item.chapter_id) || str(item.chapterId) || str(item.id) || undefined,
    scene: str(item.scene) || undefined,
    key_events: keyEvents.length ? keyEvents : undefined,
    points: points.length ? points : undefined,
    roles: roles.length ? roles : undefined,
    factions: listText(item.factions).length ? listText(item.factions) : undefined,
    items: listText(item.items).length ? listText(item.items) : undefined,
    hook_type: str(item.hook_type) || str(item.hookType) || undefined,
    emotion: str(item.emotion) || undefined,
    tension: num(item.tension) ?? undefined,
    payoff: str(item.payoff) || undefined,
    setup: str(item.setup) || undefined,
    arc: str(item.arc) || undefined,
    chapter_function:
      str(item.chapter_function) || str(item.chapterFunction) || undefined,
    chapter_goal: str(item.chapter_goal) || str(item.chapterGoal) || undefined,
    beat_type: str(item.beat_type) || str(item.beatType) || undefined,
    pov: str(item.pov) || undefined,
    time_span: str(item.time_span) || str(item.timeSpan) || undefined,
    word_target: num(item.word_target) ?? num(item.wordTarget) ?? undefined,
    word_actual: num(item.word_actual) ?? num(item.wordActual) ?? undefined,
    payoff_type: str(item.payoff_type) || str(item.payoffType) || undefined,
    payoff_owner: str(item.payoff_owner) || str(item.payoffOwner) || undefined,
    payoff_intensity:
      num(item.payoff_intensity) ?? num(item.payoffIntensity) ?? undefined,
    tear_point: str(item.tear_point) || str(item.tearPoint) || undefined,
    sweet_point: str(item.sweet_point) || str(item.sweetPoint) || undefined,
    twist: str(item.twist) || undefined,
    new_characters:
      listText(item.new_characters, item.newCharacters).length
        ? listText(item.new_characters, item.newCharacters)
        : undefined,
    new_items: listText(item.new_items, item.newItems).length
      ? listText(item.new_items, item.newItems)
      : undefined,
    new_settings: listText(item.new_settings, item.newSettings).length
      ? listText(item.new_settings, item.newSettings)
      : undefined,
    foreshadow_ids: listText(item.foreshadow_ids, item.foreshadowIds).length
      ? listText(item.foreshadow_ids, item.foreshadowIds)
      : undefined,
    continuity_check:
      str(item.continuity_check) || str(item.continuityCheck) || undefined,
    chapter_status: str(item.chapter_status) || str(item.chapterStatus) || undefined,
    revision_note: str(item.revision_note) || str(item.revisionNote) || undefined,
  }
}

function mapVolume(item: Record<string, unknown>, index: number): VolumeContent {
  const chapters = recordList(item.chapters).map((chapter, chapterIndex) => {
    const no = num(chapter.chapter) ?? num(chapter.no) ?? chapterIndex + 1
    return {
      no,
      title: str(chapter.title) || `第 ${no} 章`,
      summary: str(chapter.summary) || undefined,
      conflict: str(chapter.conflict) || undefined,
      hook: str(chapter.hook) || undefined,
      words: num(chapter.word_count) ?? num(chapter.words) ?? undefined,
      ...chapterExtra(chapter),
    }
  })
  return {
    no: num(item.no) ?? index + 1,
    title: str(item.title) || undefined,
    summary: str(item.summary) || undefined,
    conflict: str(item.conflict) || undefined,
    chapter_from: num(item.chapter_from) ?? num(item.from) ?? undefined,
    chapter_to: num(item.chapter_to) ?? num(item.to) ?? undefined,
    chapters: chapters.length ? chapters : undefined,
    theme: str(item.theme) || undefined,
    core_event: str(item.core_event) || str(item.coreEvent) || undefined,
    conflict_axis: str(item.conflict_axis) || str(item.conflictAxis) || undefined,
    end_hook: str(item.end_hook) || str(item.endHook) || undefined,
    arc: str(item.arc) || undefined,
    tension_profile:
      str(item.tension_profile) || str(item.tensionProfile) || undefined,
  }
}

function mapWorldview(value: unknown): WorldviewGroup[] {
  return recordList(value).map((group) => ({
    group: str(group.group) || str(group.name) || undefined,
    points: recordList(group.points).map((point) => ({
      text: str(point.text) || str(point.content) || undefined,
      chapters: listNum(point.chapters),
    })),
  }))
}

function mapMapRegions(value: unknown): MapRegion[] {
  return recordList(value).map((region) => ({
    name: str(region.name) || undefined,
    parent: str(region.parent) || undefined,
    kind: str(region.kind) || str(region.type) || undefined,
    desc: str(region.desc) || str(region.description) || undefined,
    chapters: listNum(region.chapters),
  }))
}

function mapMapScenes(value: unknown): MapScene[] {
  return recordList(value).map((scene) => ({
    chapter: num(scene.chapter) ?? undefined,
    region: str(scene.region) || undefined,
    characters: listText(scene.characters),
    factions: listText(scene.factions),
    items: listText(scene.items),
    event: str(scene.event) || undefined,
  }))
}

function mapPlot(value: unknown): PlotBlock | undefined {
  if (!value || typeof value !== 'object') return undefined
  const item = value as Record<string, unknown>
  return {
    timeline: listText(item.timeline),
    mainline: listText(item.mainline),
    subplots: listText(item.subplots),
    conflict: listText(item.conflict),
    suspense: listText(item.suspense),
    foreshadow: listText(item.foreshadow),
  }
}

function mapIndex(value: unknown): IndexEntry[] {
  return recordList(value).map((entry) => ({
    chapter: num(entry.chapter) ?? undefined,
    text: str(entry.text) || str(entry.title) || str(entry.note) || undefined,
    type: str(entry.type) || undefined,
  }))
}

function mapForeshadows(value: unknown): ForeshadowEntry[] {
  return recordList(value).map((item) => ({
    text: str(item.text) || undefined,
    seed: str(item.seed) || undefined,
    payoff: str(item.payoff) || undefined,
    chapter: num(item.chapter) ?? undefined,
    status: str(item.status) || undefined,
  }))
}

function mapTimeEvents(value: unknown): TimeEvent[] {
  return recordList(value).map((item) => ({
    chapter: num(item.chapter) ?? undefined,
    text: str(item.text) || undefined,
    is_volume: typeof item.is_volume === 'boolean' ? item.is_volume : undefined,
  }))
}

function mapEmotionCurve(value: unknown): EmotionPoint[] {
  return recordList(value).map((item) => ({
    chapter: num(item.chapter) ?? undefined,
    tension: num(item.tension) ?? undefined,
    emotion: str(item.emotion) || undefined,
    hook: str(item.hook) || undefined,
  }))
}

function mapItemLinks(value: unknown): ItemLink[] {
  return recordList(value).map((item) => ({
    item: str(item.item) || str(item.name) || undefined,
    from: str(item.from) || undefined,
    to: str(item.to) || undefined,
    note: str(item.note) || undefined,
    chapter: num(item.chapter) ?? undefined,
  }))
}

function mapOpening(value: unknown): OpeningInfo | undefined {
  if (!value || typeof value !== 'object') return undefined
  const item = value as Record<string, unknown>
  const golden = num(item.golden_finger_demo) ?? num(item.goldenFingerDemo)
  if (!str(item.strategy) && !str(item.first_image) && golden === undefined) {
    return undefined
  }
  return {
    strategy: str(item.strategy) || undefined,
    first_image: str(item.first_image) || str(item.firstImage) || undefined,
    golden_finger_demo: golden,
  }
}

function mapOutlineChapters(value: unknown): OutlineChapter[] {
  return recordList(value).map((item, index) => {
    const no = num(item.chapter) ?? num(item.no) ?? index + 1
    return {
      no,
      title: str(item.title) || `第 ${no} 章`,
      summary: str(item.summary) || undefined,
      key_events: listText(item.key_events, item.keyEvents).length
        ? listText(item.key_events, item.keyEvents)
        : undefined,
      hook: str(item.hook) || undefined,
      arc: str(item.arc) || undefined,
    }
  })
}

function mapCompleteness(
  value: unknown,
): OutlineContent['completeness_check'] {
  if (!value || typeof value !== 'object') return undefined
  const item = value as Record<string, unknown>
  return {
    missing_fields: listText(item.missing_fields, item.missingFields),
    unfilled_payoff: listText(item.unfilled_payoff, item.unfilledPayoff),
    unrecovered: listText(item.unrecovered),
    arc_missing: listText(item.arc_missing, item.arcMissing),
    no_hook: listText(item.no_hook, item.noHook),
  }
}

function mapSigningCheck(value: unknown): SigningCheck | undefined {
  if (!value || typeof value !== 'object') return undefined
  const item = value as Record<string, unknown>
  return {
    score: num(item.score) ?? undefined,
    risk: str(item.risk) || str(item.level) || undefined,
    suggestions: listText(item.suggestions),
    issues: listText(item.issues),
  }
}

/**
 * 服务端 agent-runs 返回技能原始结构（chapter/personality/stance/theme…），
 * 这里映射成工作台可渲染的字段；缺字段时保留空数组/占位，不让页面报错。
 */
function normalizeRunDetail(raw: RawRun): RunDetail {
  const chapters: ChapterContent[] = recordList(raw.chapters).map((item, index) => {
    const content = str(item.content)
    return {
      no: num(item.chapter) ?? num(item.no) ?? index + 1,
      title: str(item.title) || `第 ${index + 1} 章`,
      summary: str(item.summary) || undefined,
      content: content || undefined,
      words: num(item.word_count) ?? num(item.words) ?? (content ? content.length : 0),
      conflict: str(item.conflict) || undefined,
      hook: str(item.hook) || undefined,
      ...chapterExtra(item),
    }
  })

  // chapter_summarize 用 chapter_no，正文用 chapter；统一映射为 no 并按章号排序，
  // 保证「章节概括」与「作品正文」逐章一一对应。
  const chapterSummaries: ChapterSummary[] = recordList(raw.chapter_summaries)
    .map((item, index) => {
      const no = num(item.chapter_no) ?? num(item.chapter) ?? num(item.no) ?? index + 1
      return {
        no,
        title: str(item.title) || `第 ${no} 章`,
        summary: str(item.summary) || undefined,
        conflict: str(item.conflict) || undefined,
        hook: str(item.hook) || undefined,
        words: num(item.word_count) ?? num(item.words) ?? undefined,
        ...chapterExtra(item),
      }
    })
    .sort((a, b) => a.no - b.no)

  // 服务端角色：role=主角/配角/反派，identity=身份，affiliation=所属势力，
  // relations=[{target,type}]。客户端把 role 映射为「角色类型」、identity 映射为「身份」。
  const characters: CharacterContent[] = recordList(raw.characters)
    .filter((item) => str(item.name))
    .map((item) => {
      const roleType = str(item.role)
      const identity = str(item.identity)
      const personality = str(item.personality)
      const factionName =
        str(item.factionName) || str(item.faction_name) || str(item.faction)
      const faction = str(item.affiliation) || factionName
      const arcRecord =
        item.arc && typeof item.arc === 'object'
          ? (item.arc as Record<string, unknown>)
          : null
      const textList = (...values: unknown[]): string[] =>
        values
          .flatMap((value) =>
            Array.isArray(value)
              ? value.map(str)
              : typeof value === 'string'
                ? value.split(/[\n；;｜|]/)
                : [],
          )
          .map((text) => text.trim())
          .filter(Boolean)
      return {
        name: str(item.name),
        alias: str(item.alias) || undefined,
        role: identity || roleType || undefined,
        type: roleType || undefined,
        gender: str(item.gender) || undefined,
        camp: str(item.camp) || str(item.stance) || undefined,
        faction: faction || undefined,
        faction_name: factionName || faction || undefined,
        personality: personality || undefined,
        goal: str(item.goal) || undefined,
        first_chapter: num(item.first_chapter) ?? num(item.chapter) ?? undefined,
        relations: relationLabels(item.relations),
        description:
          str(item.description) ||
          [str(item.appearance), str(item.arc)].filter(Boolean).join(' · ') ||
          [personality, str(item.goal)].filter(Boolean).join(' · ') ||
          undefined,
        // 旧客户端角色卡字段
        race: str(item.race) || undefined,
        identity: identity || undefined,
        alignment: str(item.alignment) || undefined,
        stance: str(item.stance) || undefined,
        faction_category: str(item.factionCategory) || str(item.faction_category) || undefined,
        sub_faction: str(item.subFaction) || str(item.sub_faction) || undefined,
        loyalty: num(item.loyalty) ?? undefined,
        join_chapter: num(item.joinChapter) ?? num(item.join_chapter) ?? undefined,
        leave_chapter: num(item.leaveChapter) ?? num(item.leave_chapter) ?? undefined,
        relation_to: str(item.relationTo) || str(item.relation_to) || undefined,
        relation_type: str(item.relationType) || str(item.relation_type) || undefined,
        relation_direction:
          str(item.relationDirection) || str(item.relation_direction) || undefined,
        relation_strength: num(item.relationStrength) ?? num(item.relation_strength) ?? undefined,
        relation_public:
          typeof item.isPublic === 'boolean'
            ? item.isPublic
            : typeof item.relation_public === 'boolean'
              ? item.relation_public
              : undefined,
        relation_chapter: num(item.chapter) ?? num(item.relation_chapter) ?? undefined,
        speech: str(item.speech) || undefined,
        catchwords: str(item.catchwords) || undefined,
        weakness: str(item.weakness) || undefined,
        // 新增补全字段
        age: num(item.age) ?? undefined,
        appearance: str(item.appearance) || undefined,
        quirks: textList(item.quirks),
        strengths: textList(item.strengths),
        flaws: textList(item.flaws),
        core_desire: str(item.core_desire) || str(item.coreDesire) || undefined,
        core_fear: str(item.core_fear) || str(item.coreFear) || undefined,
        backstory: str(item.backstory) || undefined,
        secret: str(item.secret) || undefined,
        arc: str(item.arc) || undefined,
        arc_detail: arcRecord
          ? {
              type: str(arcRecord.type) || undefined,
              start_state:
                str(arcRecord.start_state) || str(arcRecord.startState) || undefined,
              turning_points: textList(
                arcRecord.turning_points,
                arcRecord.turningPoints,
              ),
              end_state:
                str(arcRecord.end_state) || str(arcRecord.endState) || undefined,
              final_fate:
                str(arcRecord.final_fate) || str(arcRecord.finalFate) || undefined,
            }
          : undefined,
        obstacle_methods: textList(item.obstacle_methods),
        exit_reason: str(item.exit_reason) || undefined,
        voice_sample: textList(item.voice_sample),
        pov_chapters: listNum(item.pov_chapters, item.povChapters),
        tags: textList(item.tags),
      }
    })

  // 服务端势力 members 可能是字符串数组，relations=[{target,type}]；
  // 统一成成员对象，并把关系补进成员的 relation 字段，避免势力表明细为空。
  const factions: FactionContent[] = recordList(raw.factions)
    .filter((item) => str(item.name))
    .map((item) => {
      const relations = Array.isArray(item.relations) ? item.relations : []
      const relationMap = new Map<string, string>()
      relations.forEach((rel) => {
        if (!rel || typeof rel !== 'object') return
        const target = str((rel as Record<string, unknown>).target)
        const type = str((rel as Record<string, unknown>).type)
        if (target) relationMap.set(target, type)
      })

      const rawMembers: unknown[] = Array.isArray(item.members) ? item.members : []
      const members: FactionMember[] = []
      rawMembers.forEach((member) => {
        if (typeof member === 'string') {
          const name = member.trim()
          if (name) members.push({ name, relation: relationMap.get(name) })
          return
        }
        if (member && typeof member === 'object') {
          const record = member as Record<string, unknown>
          const name = str(record.name)
          if (name) {
            members.push({
              name,
              role: str(record.role) || str(record.identity) || undefined,
              relation: str(record.relation) || relationMap.get(name),
            })
          }
        }
      })
      // 只有关系、没有成员名单时，把关系对象补成成员，保证关系可见
      relationMap.forEach((type, target) => {
        if (!members.some((member) => member.name === target)) {
          members.push({ name: target, relation: type })
        }
      })

      return {
        name: str(item.name),
        type: str(item.type) || str(item.category) || undefined,
        category: str(item.category) || undefined,
        leader: str(item.leader) || undefined,
        stance: str(item.stance) || undefined,
        territory: str(item.territory) || undefined,
        goal: str(item.goal) || undefined,
        // 服务端缺 members_count 且没有成员明细时保持空，避免页面误显示 0
        members_count: num(item.members_count) ?? (members.length ? members.length : undefined),
        first_chapter: num(item.first_chapter) ?? num(item.chapter) ?? undefined,
        description: str(item.description) || str(item.desc) || undefined,
        members,
        rel_to:
          str(item.relTo) ||
          str(item.rel_to) ||
          str(item.relationTo) ||
          undefined,
        rel_type:
          str(item.relType) ||
          str(item.rel_type) ||
          str(item.relationType) ||
          undefined,
        rel_strength: num(item.relStrength) ?? num(item.rel_strength) ?? undefined,
        rel_public:
          typeof item.relPublic === 'boolean'
            ? item.relPublic
            : typeof item.rel_public === 'boolean'
              ? item.rel_public
              : undefined,
        relations: relationLabels(item.relations),
      }
    })

  // 服务端道具功法没有 description，正文在 notes / effect 里，映射为描述展示。
  const items: ItemContent[] = recordList(raw.items)
    .filter((item) => str(item.name))
    .map((item) => ({
      name: str(item.name),
      category: str(item.category) || str(item.kind) || undefined,
      grade: str(item.grade) || undefined,
      owner: str(item.owner) || undefined,
      holder: str(item.holder) || undefined,
      faction: str(item.faction) || undefined,
      effect: str(item.effect) || undefined,
      cost: str(item.cost) || undefined,
      origin: str(item.origin) || undefined,
      note: str(item.note) || undefined,
      first_chapter: num(item.first_chapter) ?? num(item.chapter) ?? undefined,
      chapters: Array.isArray(item.chapters)
        ? item.chapters.map((no) => num(no)).filter((no): no is number => no !== null)
        : undefined,
      description:
        str(item.description) ||
        str(item.notes) ||
        str(item.desc) ||
        str(item.effect) ||
        undefined,
      payoff:
        str(item.payoff) ||
        str(item.item_payoff) ||
        str(item.itemPayoff) ||
        undefined,
    }))

  // 卷字段：服务端未下发时为空，卷章概览会按章节聚合为单卷。
  const volumes: VolumeContent[] = recordList(raw.volumes).map((item, index) =>
    mapVolume(item, index),
  )

  let outline: OutlineContent | undefined
  const hasOutline = !!raw.outline && typeof raw.outline === 'object'
  const hasBible = !!raw.story_bible && typeof raw.story_bible === 'object'
  if (hasOutline || hasBible) {
    const source = (hasOutline ? raw.outline : {}) as Record<string, unknown>
    const beats = Array.isArray(source.beats)
      ? source.beats.map(str).filter(Boolean)
      : recordList(source.chapters)
          .map((item) => {
            const no = num(item.chapter)
            const title = str(item.title)
            const summary = str(item.summary)
            return `第 ${no ?? '?'} 章${title ? ` ${title}` : ''}${summary ? `：${summary}` : ''}`
          })
    const themes = Array.isArray(source.themes)
      ? source.themes.map(str).filter(Boolean)
      : [str(source.theme)].filter(Boolean)
    // 大纲基础信息：outline 本体优先，回退服务端 story_bible（对齐 docs/大纲字段总表 组1）
    const bible =
      raw.story_bible && typeof raw.story_bible === 'object'
        ? (raw.story_bible as Record<string, unknown>)
        : source.story_bible && typeof source.story_bible === 'object'
          ? (source.story_bible as Record<string, unknown>)
          : {}
    const root = raw as Record<string, unknown>
    const opening =
      mapOpening(source.opening) ||
      mapOpening(bible.opening) ||
      mapOpening(root.opening)
    const outlineVolumes = recordList(source.volumes).map((volume, index) =>
      mapVolume(volume, index),
    )
    const outlineChapters = mapOutlineChapters(source.chapters)
    // 数组字段兼容「数组」与「分号/换行分隔的字符串」两种落盘形式
    const strList = (...values: unknown[]): string[] => {
      for (const value of values) {
        if (Array.isArray(value)) {
          const list = value.map(str).filter(Boolean)
          if (list.length) return list
        }
        if (typeof value === 'string' && value.trim()) {
          return value
            .split(/[\n；;]/)
            .map((item) => item.trim())
            .filter(Boolean)
        }
      }
      return []
    }
    outline = {
      logline: str(source.logline) || raw.summary?.logline || undefined,
      themes,
      beats,
      book_title:
        str(source.book_title) || str(bible.book_title) || str(root.book_title) || undefined,
      title_alternatives: strList(source.title_alternatives, bible.title_alternatives),
      book_summary:
        str(source.book_summary) || str(bible.book_summary) || undefined,
      author: str(source.author) || str(bible.author) || undefined,
      status: str(source.status) || str(bible.status) || undefined,
      era: str(source.era) || str(bible.era) || undefined,
      ai:
        typeof source.ai === 'boolean'
          ? source.ai
          : typeof bible.ai === 'boolean'
            ? bible.ai
            : undefined,
      n_chapters:
        num(source.n_chapters) ??
        num(bible.n_chapters) ??
        raw.summary?.chapters_count,
      generated_at:
        str(source.generated_at) || str(bible.generated_at) || undefined,
      source_type: str(source.source_type) || str(bible.source_type) || undefined,
      language: str(source.language) || str(bible.language) || undefined,
      schema_version:
        str(source.schema_version) || str(bible.schema_version) || undefined,
      rights_status:
        str(source.rights_status) || str(bible.rights_status) || undefined,
      opening,
      genre_tone: str(source.genre_tone) || str(source.genre) || str(bible.genre) || undefined,
      tone: str(source.tone) || str(bible.tone) || undefined,
      synopsis: str(source.synopsis) || str(bible.synopsis) || undefined,
      audience: str(source.audience) || str(bible.audience) || undefined,
      type_primary:
        str(source.type_primary) || str(bible.type_primary) || undefined,
      type_secondary: strList(source.type_secondary, bible.type_secondary),
      core_hook: str(source.core_hook) || str(bible.core_hook) || undefined,
      target_platform: strList(source.target_platform, bible.target_platform),
      platform_style:
        (source.platform_style || bible.platform_style) &&
        typeof (source.platform_style || bible.platform_style) === 'object'
          ? ((source.platform_style || bible.platform_style) as Record<string, unknown>)
          : undefined,
      target_reader_age:
        str(source.target_reader_age) || str(bible.target_reader_age) || undefined,
      target_reader_gender:
        str(source.target_reader_gender) ||
        str(bible.target_reader_gender) ||
        undefined,
      estimated_words:
        num(source.estimated_words) ?? num(bible.estimated_words) ?? undefined,
      length_class:
        str(source.length_class) || str(bible.length_class) || undefined,
      total_chapters_planned:
        num(source.total_chapters_planned) ??
        num(bible.total_chapters_planned) ??
        undefined,
      chapter_words_target:
        num(source.chapter_words_target) ??
        num(bible.chapter_words_target) ??
        undefined,
      serialization_pace:
        str(source.serialization_pace) ||
        str(bible.serialization_pace) ||
        undefined,
      update_frequency:
        str(source.update_frequency) || str(bible.update_frequency) || undefined,
      content_rating:
        str(source.content_rating) || str(bible.content_rating) || undefined,
      series_plan: str(source.series_plan) || str(bible.series_plan) || undefined,
      keywords: strList(source.keywords, bible.keywords),
      aigc_disclosure:
        str(source.aigc_disclosure) || str(bible.aigc_disclosure) || undefined,
      person: str(source.person) || str(bible.person) || undefined,
      style: str(source.style) || str(bible.style) || undefined,
      world: str(source.world) || str(bible.world) || undefined,
      power: str(source.power) || str(bible.power) || undefined,
      conflict: str(source.conflict) || str(bible.conflict) || undefined,
      suspense: str(source.suspense) || str(bible.suspense) || undefined,
      mainline: str(source.mainline) || str(bible.mainline) || undefined,
      taboos: str(source.taboos) || str(bible.taboos) || undefined,
      subplots: str(source.subplots) || str(bible.subplots) || undefined,
      protagonist: str(source.protagonist) || str(bible.protagonist) || undefined,
      supporting: str(source.supporting) || str(bible.supporting) || undefined,
      antagonist: str(source.antagonist) || str(bible.antagonist) || undefined,
      foreshadow_text: str(source.foreshadow) || str(bible.foreshadow) || undefined,
      places: str(source.places) || str(bible.places) || undefined,
      items_text:
        str(source.items) ||
        str(bible.items) ||
        listText(source.items, bible.items).join('、') ||
        undefined,
      terms: str(source.terms) || str(bible.terms) || undefined,
      timeline: str(source.timeline) || str(bible.timeline) || undefined,
      map_text: str(source.map) || str(bible.map) || undefined,
      worldview: mapWorldview(source.worldview || bible.worldview),
      map_levels: strList(source.map_levels, bible.map_levels),
      map_regions: mapMapRegions(source.map_regions || bible.map_regions),
      map_scenes: mapMapScenes(source.map_scenes || bible.map_scenes),
      theme_core: str(source.theme_core) || str(bible.theme_core) || undefined,
      theme_statement: str(source.theme_statement) || str(bible.theme_statement) || undefined,
      selling_points: strList(source.selling_points, bible.selling_points),
      innovation_points: strList(source.innovation_points, bible.innovation_points),
      ending_type: str(source.ending_type) || str(bible.ending_type) || undefined,
      comparative_titles: strList(source.comparative_titles, bible.comparative_titles),
      ending_state: str(source.ending_state) || str(bible.ending_state) || undefined,
      protagonist_final_fate:
        str(source.protagonist_final_fate) || str(bible.protagonist_final_fate) || undefined,
      plot: mapPlot(source.plot || bible.plot),
      volumes: outlineVolumes.length ? outlineVolumes : undefined,
      hooks: mapIndex(source.hooks || bible.hooks),
      setups: mapIndex(source.setups || bible.setups),
      payoffs: mapIndex(source.payoffs || bible.payoffs),
      conflicts: mapIndex(source.conflicts || bible.conflicts),
      foreshadows: mapForeshadows(source.foreshadows || bible.foreshadows),
      time_events: mapTimeEvents(source.timeEvents || bible.timeEvents),
      emotion_curve: mapEmotionCurve(source.emotionCurve || bible.emotionCurve),
      item_links: mapItemLinks(source.itemLinks || bible.itemLinks),
      signing_check:
        mapSigningCheck(source.signing_check) ||
        mapSigningCheck(bible.signing_check) ||
        mapSigningCheck(root.signing_check),
      completeness_check:
        mapCompleteness(source.completeness_check) ||
        mapCompleteness(bible.completeness_check) ||
        mapCompleteness(root.completeness_check),
      qa_score: num(source.qa_score) ?? num(bible.qa_score) ?? undefined,
      chapters: outlineChapters.length ? outlineChapters : undefined,
    }
  }

  return {
    ...raw,
    status: (typeof raw.status === 'string' ? raw.status : 'queued') as RunDetail['status'],
    stages: Array.isArray(raw.stages) ? raw.stages : [],
    artifacts: Array.isArray(raw.artifacts) ? raw.artifacts : [],
    chapters,
    chapter_summaries: chapterSummaries,
    chapter_hidden: Array.isArray(raw.chapter_hidden) ? raw.chapter_hidden : [],
    characters,
    factions,
    items,
    volumes: volumes.length ? volumes : raw.volumes,
    outline,
  }
}

export async function getRun(runId: string): Promise<RunDetail> {
  const raw = await apiFetch<RawRun>(`/agent-runs/${encodeURIComponent(runId)}`)
  return normalizeRunDetail(raw)
}

export interface RunInfoUpdatePayload {
  title?: string
  author?: string
  status_label?: '连载中' | '已签约' | '已完结'
  audience?: Audience
  length?: RunLength
  genre?: GenreSelection
  logline?: string
  synopsis?: string
  themes?: string[]
  person?: string
  style?: string
  world?: string
  conflict?: string
  mainline?: string
  selling_points?: string[]
  core_hook?: string
  suspense?: string
  subplots?: string
  beats?: string[]
  protagonist?: string
  supporting?: string
  antagonist?: string
  foreshadow_text?: string
  power?: string
  places?: string
  items_text?: string
  terms?: string
  timeline?: string
  map_text?: string
  theme_core?: string
  theme_statement?: string
  innovation_points?: string[]
  ending_type?: string
  ending_state?: string
  protagonist_final_fate?: string
  comparative_titles?: string[]
  taboos?: string
  tone?: string
  target_platform?: string[]
  target_reader_age?: string
  update_frequency?: string
  serialization_pace?: string
  content_rating?: string
}

/** 编辑作品信息：必填字段与可选字段一起提交，后端覆盖到 meta.info。 */
export async function updateRunInfo(
  runId: string,
  payload: RunInfoUpdatePayload,
): Promise<RunDetail> {
  const raw = await apiFetch<RawRun>(`/agent-runs/${encodeURIComponent(runId)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
  return normalizeRunDetail(raw)
}

/** 人物/势力/道具/卷章概览：整组覆盖，未提交的集合保持原值 */
export interface RunCollectionsUpdatePayload {
  characters?: CharacterContent[]
  factions?: FactionContent[]
  items?: ItemContent[]
  volumes?: VolumeContent[]
  chapter_summaries?: ChapterSummary[]
  chapter_hidden?: number[]
}

export async function updateRunCollections(
  runId: string,
  payload: RunCollectionsUpdatePayload,
): Promise<RunDetail> {
  const raw = await apiFetch<RawRun>(
    `/agent-runs/${encodeURIComponent(runId)}/collections`,
    {
      method: 'PATCH',
      body: JSON.stringify(payload),
    },
  )
  return normalizeRunDetail(raw)
}

export async function deleteRun(runId: string): Promise<{ deleted: boolean }> {
  return apiFetch<{ deleted: boolean }>(`/agent-runs/${encodeURIComponent(runId)}`, {
    method: 'DELETE',
  })
}

export async function cancelRun(runId: string): Promise<void> {
  await apiFetch(`/agent-runs/${encodeURIComponent(runId)}/cancel`, { method: 'POST' })
}

/** 停止任务 = 暂停：进入 paused 后可「开始」继续或「取消」终止 */
export async function pauseRun(runId: string): Promise<void> {
  await apiFetch(`/agent-runs/${encodeURIComponent(runId)}/pause`, { method: 'POST' })
}

export async function resumeRun(runId: string, payload: ResumePayload): Promise<void> {
  const headers: Record<string, string> = {}
  await apiFetch(`/agent-runs/${encodeURIComponent(runId)}/resume`, {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
  })
}

export interface CoverOptions {
  prompt?: string
  style?: 'gold' | 'white' | 'ink'
  layout?: 'top' | 'middle' | 'bottom'
}

export interface CoverResult {
  run_id: string
  cover_url: string
  cover: NonNullable<RunDetail['cover']>
}

/** 生成 AI 封面：服务端模型优先，失败自动降级免费/本地绘制。 */
export async function generateRunCover(
  runId: string,
  options: CoverOptions = {},
): Promise<CoverResult> {
  return apiFetch<CoverResult>(`/agent-runs/${encodeURIComponent(runId)}/cover`, {
    method: 'POST',
    body: JSON.stringify(options),
  })
}

/** 封面接口需要登录态，必须带 Authorization 拉取。 */
export async function fetchRunCover(path: string): Promise<File> {
  return apiDownload(path, 'cover.jpg')
}

/** 用户上传封面；服务端校验图片并统一压缩为 JPEG。 */
export async function uploadRunCover(runId: string, file: File): Promise<CoverResult> {
  const form = new FormData()
  form.append('file', file)
  return apiFetch<CoverResult>(`/agent-runs/${encodeURIComponent(runId)}/cover/upload`, {
    method: 'POST',
    body: form,
  })
}

export async function deleteRunCover(runId: string): Promise<{ deleted: boolean }> {
  return apiFetch<{ deleted: boolean }>(`/agent-runs/${encodeURIComponent(runId)}/cover`, {
    method: 'DELETE',
  })
}

export async function downloadArtifact(runId: string, name: string): Promise<File> {
  return apiDownload(
    `/agent-runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(name)}`,
    name,
  )
}

/** 整本交付包：正文/章纲/设定/体检/AIGC 声明打包 zip */
export async function downloadExportBundle(runId: string, title?: string): Promise<File> {
  const fallback = `${(title || runId).trim() || runId}-交付包.zip`
  return apiDownload(`/agent-runs/${encodeURIComponent(runId)}/export`, fallback)
}

/** 作品列表筛选条件；空字符串/null 表示「全部」 */
export interface RunFilters {
  mode?: RunMode | ''
  audience?: Audience | ''
  length?: RunLength | ''
  genre?: string
  /** 按书名模糊搜索；服务端未支持时由客户端过滤兜底 */
  q?: string
}

function runFilterQuery(filters: RunFilters): string {
  const params = new URLSearchParams()
  if (filters.mode) params.set('mode', filters.mode)
  if (filters.audience) params.set('audience', filters.audience)
  if (filters.length) params.set('length', filters.length)
  if (filters.genre) params.set('genre', filters.genre)
  if (filters.q) params.set('q', filters.q)
  const text = params.toString()
  return text ? `&${text}` : ''
}

/** 后端筛选参数未生效时，客户端按 AND 组合再次过滤 */
function applyRunFilters(items: RunDetail[], filters: RunFilters): RunDetail[] {
  return items.filter((item) => {
    if (filters.mode && item.mode !== filters.mode) return false
    if (filters.audience && item.audience !== filters.audience) return false
    if (filters.length && item.length !== filters.length) return false
    if (
      filters.genre &&
      item.genre?.id !== filters.genre &&
      item.genre?.name !== filters.genre
    ) {
      return false
    }
    if (filters.q && !String(item.title || '').toLowerCase().includes(filters.q.toLowerCase())) {
      return false
    }
    return true
  })
}

interface RawRunList {
  items?: RawRun[]
  total?: number
  next_offset?: number
}

/** 列表翻页参数；不传时保持原有「一次取 50 条」的行为 */
export interface RunListOptions {
  limit?: number
  offset?: number
}

async function fetchRunList(
  query: string,
  options: RunListOptions = {},
): Promise<{ items: RunDetail[]; total?: number; next_offset?: number }> {
  const limit = options.limit ?? 50
  const offset = Math.max(0, options.offset ?? 0)
  const data = await apiFetch<RawRunList>(`/agent-runs?limit=${limit}&offset=${offset}${query}`)
  return {
    items: (data.items || []).map(normalizeRunDetail),
    total: typeof data.total === 'number' ? data.total : undefined,
    next_offset: typeof data.next_offset === 'number' ? data.next_offset : undefined,
  }
}

/** 历史列表：带筛选参数请求，并用服务端 total 展示「共 N 部」。 */
export async function listRuns(
  filters: RunFilters = {},
  options: RunListOptions = {},
): Promise<RunListResult> {
  const query = runFilterQuery(filters)
  let result: { items: RunDetail[]; total?: number; next_offset?: number }
  try {
    result = await fetchRunList(query, options)
  } catch (err) {
    // 筛选参数尚未上线（400/404/405/422/501）时退回全量请求，再在客户端过滤
    if (!query || !(err instanceof ApiError) || ![400, 404, 405, 422, 501].includes(err.status)) {
      throw err
    }
    result = await fetchRunList('', options)
  }
  const items = applyRunFilters(result.items, filters)
  return {
    items,
    // 服务端 total 已按筛选条件统计；回退全量时按本地过滤结果计数
    total: result.total ?? items.length,
    next_offset: result.next_offset,
  }
}

/**
 * 订阅事件流：正常返回时由调用方在完成后 abort。
 * 接口未实现（404/405/501）时抛 ApiError，调用方降级为轮询并在界面提示。
 */
export async function streamRunEvents(
  runId: string,
  since: number,
  onEvent: (event: RunEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const url = `${API_BASE}/agent-runs/${encodeURIComponent(runId)}/events?since=${since}`
  const pathQuery = (() => {
    try {
      const parsed = new URL(url, window.location.origin)
      return parsed.pathname + parsed.search
    } catch {
      return url
    }
  })()
  const session = await getPayloadSession()
  const resp = await fetch(url, {
    headers: {
      Accept: 'text/event-stream',
      ...(getAccessToken() ? { Authorization: `Bearer ${getAccessToken()}` } : {}),
      ...payloadHeaders(session),
    },
    signal,
  }).catch((err) => {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw new ApiError(0, 'network_error', '无法连接服务端，请检查网络与后端地址')
  })

  if (!resp.ok || !resp.body) {
    const text = await readSseError(resp, session, pathQuery)
    throw extractError(resp.status, text ? safeJson(text) : null)
  }

  const streamEncrypted = resp.headers.get('x-payload-sse') === '1'
  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const blocks = buffer.split(/\r?\n\r?\n/)
    buffer = blocks.pop() || ''
    for (const block of blocks) {
      const dataLines = block
        .split(/\r?\n/)
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trim())
        .join('')
      if (!dataLines) continue
      try {
        const raw = streamEncrypted
          ? await decryptSse(session, pathQuery, dataLines)
          : dataLines
        const event = JSON.parse(raw) as RunEvent
        if (typeof event.seq === 'number') onEvent(event)
      } catch {
        // 忽略格式错误的心跳/注释帧，保持流不中断
      }
    }
  }
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text)
  } catch {
    return { error: { code: 'invalid_response', message: '服务端返回了非 JSON 内容' } }
  }
}

async function readSseError(
  resp: Response,
  session: PayloadSession,
  pathQuery: string,
): Promise<string> {
  if (resp.headers.get('x-payload-encrypted') === '1') {
    const nonce = resp.headers.get('x-payload-nonce') || ''
    try {
      return await decryptJson(
        session,
        'GET',
        pathQuery,
        nonce,
        await resp.arrayBuffer(),
      )
    } catch {
      return ''
    }
  }
  return resp.text()
}
