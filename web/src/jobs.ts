/** 任务（后台作业）相关的共用小工具：多任务并发时，各页面按任务 id 各自回显日志。 */
import { listJobs } from './api'
import type { JobSummary } from './types'

/** 任务 → 页面：任务没有记录发起页面时（老任务）按阶段兜底 */
export const JOB_ROUTE: Record<string, string> = {
  decompose: '/upload',
  adapt: '/upload',        // 全文改编在「新建作品」页发起，日志也回显在那里
  storymap: '/storymap',
  expand: '/expand',
  // 正文审查的结果回显在「正文目录」页右栏的「审查结果」tab，不跳单章审查页
  review: '/overview',
  write: '/overview',      // 正文生成就在正文目录页
}
export function jobRoute(stage: string): string {
  return JOB_ROUTE[stage] || '/overview'
}

/** 阶段 → 任务名（动词短语，和任务中心标题用同一套叫法） */
export const STAGE_NAME: Record<string, string> = {
  decompose: '拆解大纲',
  adapt: '改编全文',
  storymap: '生成设定图谱',
  expand: '批量扩写',
  review: '审查正文',
  write: '生成正文',
}
export function stageName(stage: string): string {
  return STAGE_NAME[stage] || stage || '任务'
}

/** 任务失败：有错误，或退出码非 0 且不是人为停止 */
export function jobFailed(j: JobSummary): boolean {
  return !j.running && (!!j.error || (j.code !== 0 && !j.stopped))
}

/** 一句话状态：运行中 / 已停止 / 失败 / 已完成 */
export function jobStatus(j: JobSummary): string {
  if (j.running) return '运行中'
  if (j.stopped) return '已停止'
  if (jobFailed(j)) return '失败'
  return '已完成'
}

/** 状态配色：对应 .tag 的 blue / green / red / gray */
export function jobTone(j: JobSummary): string {
  if (j.running) return 'blue'
  if (j.stopped) return 'gray'
  if (jobFailed(j)) return 'red'
  return 'green'
}

/** 发起页面（hash 路由）→ { path, query }；只认站内相对路径 */
export function parseOrigin(origin?: string): { path: string; query: Record<string, string> } | null {
  const s = String(origin || '').trim()
  if (!s || !s.startsWith('/') || s.startsWith('//') || s.includes('://')) return null
  const [path, qs] = s.split('?')
  const query: Record<string, string> = {}
  for (const part of (qs || '').split('&')) {
    if (!part) continue
    const i = part.indexOf('=')
    const k = decodeURIComponent(i < 0 ? part : part.slice(0, i))
    const v = i < 0 ? '' : decodeURIComponent(part.slice(i + 1))
    if (k && k !== 'job') query[k] = v      // job= 是「当时在看哪个任务」，回跳时重新指定
  }
  return { path: path || '/', query }
}

/**
 * 点任务 → 回它「发起时所在的页面」（页面自己会接管进度 / 回显日志）。
 * 只有老任务没有 origin 时才按阶段兜底。
 */
export function jobTarget(j: JobSummary): { path: string; query: Record<string, string> } {
  const o = parseOrigin(j.origin)
  const query: Record<string, string> = { ...(o?.query || {}) }
  if (j.stage === 'review') {
    // 审查有固定落点：正文目录 → 那一章的「审查结果」
    delete query.job
    query.tab = 'review'
    if (j.chapter_no) query.ch = String(j.chapter_no)
    return { path: '/overview', query }
  }
  if (j.channel === 'page') {
    delete query.job                  // 页内任务由页面自己接管，不需要 ?job=
    if (!query.ch && j.chapter_no) query.ch = String(j.chapter_no)
    return { path: o?.path || jobRoute(j.stage), query }
  }
  query.job = j.id                    // 子进程任务：页面用 ?job= 回显它自己的日志
  return { path: o?.path || jobRoute(j.stage), query }
}

/**
 * 找本站页能「接管」的同类任务：优先运行中的，其次最近结束的。
 * 用于进页面 / 刷新后，把还在后台跑的任务日志接回面板。
 */
export async function adoptJob(stages: string[], book = ''): Promise<JobSummary | null> {
  let jobs: JobSummary[] = []
  try { jobs = (await listJobs()).jobs } catch { return null }
  const hit = jobs.filter(j => stages.includes(j.stage))
  if (!hit.length) return null
  const same = book ? hit.filter(j => !j.book || j.book === book) : hit
  const pool = same.length ? same : hit
  return pool.find(j => j.running) || pool[0]
}
