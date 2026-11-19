<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { api, errorMessage, normalizeList, streamTaskEvents, streamTasksFeed } from '../api'
import { can } from '../roles'
import { getRole } from '../session'
import { pushToast } from '../toast'
import type { AdminFeedEvent, RunEvent, TaskDashboard, TaskDetail, TaskRow, TaskStage } from '../types'
import { formatNumber, formatTime } from '../ui'
import { useVirtualRows } from '../utils/useVirtualRows'
import Icon from '../components/Icon.vue'
import PageHeader from '../components/PageHeader.vue'
import Pager from '../components/Pager.vue'
import StateBlock from '../components/StateBlock.vue'
import StatusBadge from '../components/StatusBadge.vue'
import Modal from '../components/Modal.vue'

const role = getRole()
const canWrite = computed(() => can(role, 'tasks:write'))

const dashboard = ref<TaskDashboard | null>(null)
const tasks = ref<TaskRow[]>([])
const total = ref<number | null>(null)
const loading = ref(false)
const error = ref('')
const autoRefresh = ref(true)
const tick = ref(Date.now())

const statusFilter = ref('all')
const sourceFilter = ref('all')
const keyword = ref('')
const page = ref(1)
const pageSize = 20

const FILTERS = [
  { key: 'all', label: '全部' },
  { key: 'running', label: '运行中' },
  { key: 'queued', label: '排队中' },
  { key: 'paused', label: '已暂停' },
  { key: 'succeeded', label: '已完成' },
  { key: 'failed', label: '失败' },
  { key: 'canceled', label: '已取消' },
] as const

const queueDepth = computed(() => dashboard.value?.queue_depth ?? null)
const runningCount = computed(() => dashboard.value?.running_count ?? 0)
const failedCount = computed(() => dashboard.value?.failed_count ?? 0)
const retryableCount = computed(() => dashboard.value?.retryable_count ?? 0)

const liveCount = computed(
  () => tasks.value.filter((item) => ['queued', 'running'].includes(item.status)).length,
)

/* ---- 列表 -------------------------------------------------------------- */
async function loadDashboard() {
  try {
    dashboard.value = await api.taskDashboard()
  } catch (e) {
    if (!dashboard.value) error.value = errorMessage(e)
  }
}

async function loadList(silent = false) {
  if (!silent) loading.value = true
  try {
    const query: Record<string, unknown> = { page: page.value, page_size: pageSize }
    if (statusFilter.value !== 'all') query.status = statusFilter.value
    if (sourceFilter.value !== 'all') query.source = sourceFilter.value
    if (keyword.value.trim()) query.q = keyword.value.trim()
    const list = normalizeList<TaskRow>(await api.taskList(query))
    tasks.value = list.items
    total.value = list.total
    error.value = ''
  } catch (e) {
    error.value = errorMessage(e)
    tasks.value = []
    total.value = null
  } finally {
    loading.value = false
  }
}

async function refreshAll(silent = true) {
  await Promise.all([loadDashboard(), loadList(silent)])
}

function setStatus(key: string) {
  statusFilter.value = key
  page.value = 1
  void loadList()
}

function submitSearch() {
  page.value = 1
  void loadList()
}

function gotoPage(next: number) {
  page.value = next
  void loadList()
}

/* ---- 展示辅助 ---------------------------------------------------------- */
function shortId(id: unknown): string {
  return String(id || '')
}

function formatClock(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(
    date.getMinutes(),
  )}:${pad(date.getSeconds())}`
}

/** 下次重试时间：到点前显示相对倒计时，到点后标注等待调度，便于运营判断卡单原因 */
function formatRetryTime(value: unknown): string {
  if (typeof value !== 'string' || !value) return ''
  const at = new Date(value).getTime()
  if (Number.isNaN(at)) return ''
  const seconds = Math.ceil((at - Date.now()) / 1000)
  const relative = seconds > 0 ? `${seconds} 秒后` : '已到点，等待调度'
  return `${relative}（${formatClock(value)}）`
}

function durationText(task: TaskRow): string {
  const start = task.started_at || task.created_at
  if (!start) return '—'
  const startAt = new Date(start).getTime()
  if (Number.isNaN(startAt)) return '—'
  const live = ['queued', 'running'].includes(task.status)
  const endAt = live
    ? tick.value
    : new Date(task.finished_at || task.last_activity_at || start).getTime()
  const seconds = Math.max(0, Math.floor((endAt - startAt) / 1000))
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

function sourceLabel(task: TaskRow): string {
  return task.source === 'agent_run' ? '写作运行' : '拆解任务'
}

function typeLabel(task: TaskRow): string {
  const mode = String(task.mode || '')
  const names: Record<string, string> = { hot: '热门创作', reference: '参考创作', custom: '自定义创作' }
  if (mode && names[mode]) return names[mode]
  return task.type || '—'
}

function isNodeFailure(task: TaskRow): boolean {
  return task.status === 'paused' && !!task.error_code
}

function statusLabelOf(task: TaskRow): string | undefined {
  return isNodeFailure(task) ? '已中断' : undefined
}

function isLive(task?: TaskRow | null): boolean {
  return !!task && ['queued', 'running', 'paused'].includes(task.status)
}

/* ---- 详情与日志 -------------------------------------------------------- */
const detailTask = ref<TaskRow | null>(null)
const detail = ref<TaskDetail | null>(null)
const detailLoading = ref(false)
const detailError = ref('')
const logEl = ref<HTMLElement | null>(null)
let detailController: AbortController | null = null
let detailFallbackTimer: number | null = null

const detailStatus = computed(() => {
  const d = (detail.value?.detail || {}) as Record<string, unknown>
  return String(d.status || detailTask.value?.status || '')
})
const detailIsRun = computed(() => detail.value?.source === 'agent_run')
const detailLive = computed(() => ['queued', 'running'].includes(detailStatus.value))

const stages = computed<TaskStage[]>(() => {
  const value = (detail.value?.detail || {}) as Record<string, unknown>
  return Array.isArray(value.stages) ? (value.stages as TaskStage[]) : []
})
const stageNames = computed<Record<string, string>>(() => {
  const map: Record<string, string> = {}
  for (const stage of stages.value) {
    map[stage.id] = stage.name || stage.id
  }
  return map
})
const taskSteps = computed<{ step_key: string; status: string; updated_at?: string | null }[]>(() => {
  const value = (detail.value?.detail || {}) as Record<string, unknown>
  return Array.isArray(value.steps)
    ? (value.steps as { step_key: string; status: string; updated_at?: string | null }[])
    : []
})
const events = computed<RunEvent[]>(() => detail.value?.events || [])

/* 任务日志最多 2000 条：定高行虚拟滚动，只渲染视口附近，避免长任务撑爆 DOM。
   任务表本身已分页（20/页），无需重复虚拟化。 */
const LOG_ROW_HEIGHT = 26
const LOG_VIEWPORT_HEIGHT = 460
const {
  scrollTop: logScrollTop,
  range: logRange,
  visibleRows: visibleEvents,
  onScroll: onLogScroll,
} = useVirtualRows(events, LOG_ROW_HEIGHT, LOG_VIEWPORT_HEIGHT, 8)

const detailMeta = computed<[string, unknown][]>(() => {
  const d = (detail.value?.detail || {}) as Record<string, unknown>
  const error = (d.error as Record<string, unknown>) || null
  return [
    ['状态', detailStatus.value],
    ['进度', typeof d.progress === 'number' ? `${d.progress}%` : undefined],
    ['来源', detailIsRun.value ? '写作运行' : '拆解任务'],
    ['模式', d.mode],
    ['错误码', error?.code || d.error_code],
    ['失败原因', error?.message || d.error_message],
    ['尝试次数', d.attempts],
    ['下次重试时间', formatRetryTime(d.next_retry_at) || undefined],
    ['创建时间', d.created_at],
    ['开始时间', d.started_at],
    ['结束时间', d.finished_at],
  ].filter(([, value]) => value !== undefined && value !== null && value !== '') as [
    string,
    unknown,
  ][]
})

function scrollLogToBottom(force = false) {
  const el = logEl.value
  if (!el) return
  const near = el.scrollHeight - el.scrollTop - el.clientHeight < 90
  if (!force && !near) return
  nextTick(() => {
    const target = logEl.value
    if (!target) return
    const bottom = target.scrollHeight
    target.scrollTop = bottom
    // 同步虚拟区间到尾部：否则滚动位置到底但只渲染开头几行
    logScrollTop.value = bottom
  })
}

function applyDetailStatus(status: string): void {
  if (!detail.value) return
  detail.value.detail = { ...(detail.value.detail || {}), status }
  if (detailTask.value) detailTask.value.status = status
  syncDetailStream()
}

async function connectDetail(signal: AbortSignal): Promise<void> {
  const task = detailTask.value
  if (!task) return
  let since = detail.value?.last_seq ?? 0
  while (!signal.aborted && detailLive.value) {
    try {
      await streamTaskEvents(
        String(task.id),
        task.source,
        since,
        (event: RunEvent) => {
          if (!detail.value) return
          if (detail.value.events.some((item) => item.seq === event.seq)) return
          detail.value.events.push(event)
          since = Math.max(since, event.seq)
          detail.value.last_seq = since
          scrollLogToBottom()
        },
        applyDetailStatus,
        signal,
      )
    } catch {
      if (!signal.aborted) startDetailFallback()
      return
    }
    if (signal.aborted || !detailLive.value) return
    await new Promise((resolve) => window.setTimeout(resolve, 300))
  }
}

function startDetailFallback(): void {
  if (detailFallbackTimer !== null || !detailLive.value) return
  detailFallbackTimer = window.setInterval(() => void refreshDetail(), 4000)
}

async function openDetail(task: TaskRow) {
  detailTask.value = task
  detail.value = null
  detailError.value = ''
  detailLoading.value = true
  stopDetailStream()
  try {
    detail.value = await api.taskDetail(String(task.id), task.source)
    scrollLogToBottom(true)
  } catch (e) {
    detailError.value = errorMessage(e)
  } finally {
    detailLoading.value = false
  }
  syncDetailStream()
}

async function refreshDetail() {
  const task = detailTask.value
  if (!task) return
  try {
    detail.value = await api.taskDetail(String(task.id), task.source)
    detailError.value = ''
    scrollLogToBottom()
  } catch (e) {
    detailError.value = errorMessage(e)
  }
  syncDetailStream()
}

/** 任务在跑就订阅详情事件流；SSE 不可用时自动降级为 4 秒整单刷新。 */
function syncDetailStream() {
  if (!detailLive.value) {
    stopDetailStream()
    return
  }
  if (detailController || detailFallbackTimer !== null) return
  detailController = new AbortController()
  void connectDetail(detailController.signal)
}

function closeDetail() {
  stopDetailStream()
  detailTask.value = null
  detail.value = null
  detailError.value = ''
}

function stopDetailStream() {
  detailController?.abort()
  detailController = null
  if (detailFallbackTimer !== null) {
    window.clearInterval(detailFallbackTimer)
    detailFallbackTimer = null
  }
}

const logText = computed(() =>
  events.value
    .map((ev) => `#${ev.seq} ${formatClock(ev.at)} [${ev.stage}] ${ev.message}`)
    .join('\n'),
)

async function copyLog() {
  try {
    await navigator.clipboard.writeText(logText.value)
    pushToast('日志已复制')
  } catch {
    pushToast('复制失败，请手动选择文本', 'error')
  }
}

function stageStateText(state: string): string {
  const map: Record<string, string> = {
    pending: '待开始',
    running: '进行中',
    succeeded: '已完成',
    failed: '失败',
  }
  return map[state] || state
}

/* ---- 操作 -------------------------------------------------------------- */
const retryingId = ref('')
const controllingId = ref('')

async function retryTask(task: TaskRow) {
  retryingId.value = String(task.id)
  try {
    await api.taskRetry(String(task.id))
    pushToast(`任务 ${task.id} 已重新入队`)
    await refreshAll(false)
    if (detailTask.value && String(detailTask.value.id) === String(task.id)) {
      await refreshDetail()
    }
  } catch (e) {
    pushToast(errorMessage(e), 'error')
  } finally {
    retryingId.value = ''
  }
}

type ControlAction = 'cancel' | 'pause' | 'resume' | 'force_cancel' | 'requeue'
const CONTROL_LABEL: Record<ControlAction, string> = {
  cancel: '取消',
  pause: '暂停',
  resume: '继续',
  force_cancel: '强制终止',
  requeue: '重新排队',
}

async function controlTask(task: TaskRow, action: ControlAction) {
  if (action === 'force_cancel') {
    const ok = window.confirm(
      `确认强制终止任务 ${task.id}？\n该操作会让任务立即落 canceled 终态并释放预占额度，正在执行的 worker 结果将被丢弃。`,
    )
    if (!ok) return
  }
  if (action === 'requeue') {
    const ok = window.confirm(
      `确认将任务 ${task.id} 重新排队？\n仅在该任务确认卡死时使用，重复投递可能造成同一任务被并发执行。`,
    )
    if (!ok) return
  }
  controllingId.value = String(task.id)
  try {
    const res = await api.taskControl(String(task.id), action, task.source)
    pushToast(`任务 ${task.id} ${CONTROL_LABEL[action]}成功${res?.status ? `（当前状态：${res.status}）` : ''}`)
    await refreshAll(false)
    if (detailTask.value && String(detailTask.value.id) === String(task.id)) {
      await refreshDetail()
    }
  } catch (e) {
    pushToast(errorMessage(e), 'error')
  } finally {
    controllingId.value = ''
  }
}

let feedController: AbortController | null = null
let feedFallbackTimer: number | null = null
let clockTimer: number | null = null

async function connectFeed(signal: AbortSignal): Promise<void> {
  while (!signal.aborted && autoRefresh.value) {
    try {
      await streamTasksFeed((event: AdminFeedEvent) => {
        if (event.type === 'refresh' && !document.hidden) void refreshAll(true)
      }, signal)
    } catch {
      if (!signal.aborted) startFeedFallback()
      return
    }
    if (signal.aborted || !autoRefresh.value) return
    await new Promise((resolve) => window.setTimeout(resolve, 300))
  }
}

function startFeedFallback(): void {
  if (feedFallbackTimer !== null || !autoRefresh.value) return
  feedFallbackTimer = window.setInterval(() => {
    if (!autoRefresh.value || document.hidden) return
    void refreshAll(true)
  }, 10_000)
}

function syncFeed(): void {
  if (!autoRefresh.value) {
    feedController?.abort()
    feedController = null
    if (feedFallbackTimer !== null) {
      window.clearInterval(feedFallbackTimer)
      feedFallbackTimer = null
    }
    return
  }
  if (feedController || feedFallbackTimer !== null) return
  feedController = new AbortController()
  void connectFeed(feedController.signal)
}

watch(autoRefresh, syncFeed)

onMounted(() => {
  void refreshAll(false)
  syncFeed()
  clockTimer = window.setInterval(() => {
    tick.value = Date.now()
  }, 1000)
})
onUnmounted(() => {
  feedController?.abort()
  feedController = null
  if (feedFallbackTimer !== null) window.clearInterval(feedFallbackTimer)
  if (clockTimer !== null) window.clearInterval(clockTimer)
  stopDetailStream()
})
</script>

<template>
  <PageHeader title="任务看板" desc="所有用户任务的完整记录（排队 / 运行 / 暂停 / 完成 / 失败 / 取消）。点击任意任务即可查看执行过程与任务日志，支持取消、暂停、继续、重新排队与强制终止。状态变化通过 SSE 实时刷新，接口不支持时自动降级为定时刷新。">
    <label class="badge muted" style="cursor: pointer">
      <input v-model="autoRefresh" type="checkbox" style="margin-right: 5px" />自动刷新
    </label>
    <button class="btn ghost sm" :disabled="loading" @click="refreshAll(false)">
      <Icon name="refresh" :size="14" />{{ loading ? '刷新中…' : '立即刷新' }}
    </button>
  </PageHeader>

  <div class="stat-grid">
    <div class="stat-card teal">
      <div class="stat-label">队列深度</div>
      <div class="stat-value">{{ queueDepth === null ? '—' : formatNumber(queueDepth) }}</div>
      <div class="stat-desc">等待 worker 领取的任务数</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">运行中</div>
      <div class="stat-value">{{ formatNumber(runningCount) }}</div>
      <div class="stat-desc">{{ liveCount ? `当前页 ${liveCount} 条活跃` : '当前持有租约的任务' }}</div>
    </div>
    <div class="stat-card red">
      <div class="stat-label">失败任务</div>
      <div class="stat-value">{{ formatNumber(failedCount) }}</div>
      <div class="stat-desc">最近失败 / 待处理</div>
    </div>
    <div class="stat-card orange">
      <div class="stat-label">可重试</div>
      <div class="stat-value">{{ formatNumber(retryableCount) }}</div>
      <div class="stat-desc">满足重试条件的任务</div>
    </div>
  </div>

  <div class="card">
    <div class="card-head">
      <div class="card-title">任务记录<span class="sub">{{ total === null ? '' : `${formatNumber(total)} 条` }}</span></div>
      <div class="spacer"></div>
      <span class="muted" style="font-size: 11.5px">
        看板生成时间 {{ formatTime(dashboard?.generated_at) }}
      </span>
    </div>

    <div class="filter-row">
      <button
        v-for="item in FILTERS"
        :key="item.key"
        type="button"
        class="filter-chip"
        :class="{ on: statusFilter === item.key }"
        @click="setStatus(item.key)"
      >
        {{ item.label }}
      </button>
      <span class="spacer"></span>
      <select v-model="sourceFilter" class="input mini" @change="submitSearch">
        <option value="all">全部来源</option>
        <option value="agent_run">写作运行</option>
        <option value="task">拆解任务</option>
      </select>
      <input
        v-model="keyword"
        class="input mini"
        placeholder="任务ID / 作品名 / 账号ID"
        @keyup.enter="submitSearch"
      />
      <button class="btn sm" :disabled="loading" @click="submitSearch">
        {{ loading ? '查询中…' : '查询' }}
      </button>
    </div>

    <div v-if="loading && !tasks.length" class="card">
      <StateBlock kind="loading" title="正在加载任务记录…" />
    </div>
    <div v-else-if="error" class="card">
      <StateBlock kind="error" title="任务记录加载失败" :message="error" retry-label="重试" @retry="refreshAll(false)" />
    </div>
    <template v-else>
      <div v-if="tasks.length" class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th>任务 ID</th>
              <th>账号</th>
              <th>来源 / 类型</th>
              <th>作品</th>
              <th>状态</th>
              <th class="num">进度</th>
              <th>创建时间</th>
              <th class="num">用时</th>
              <th>最近活动</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="task in tasks" :key="`${task.source}-${task.id}`" class="row-click" @click="openDetail(task)">
              <td class="mono truncate" :title="shortId(task.id)">{{ shortId(task.id) }}</td>
              <td>{{ task.account_id ? `#${task.account_id}` : '—' }}</td>
              <td>
                <span class="badge muted" style="font-size: 11px">{{ sourceLabel(task) }}</span>
                {{ typeLabel(task) }}
              </td>
              <td class="truncate" :title="task.title || ''">{{ task.title || '—' }}</td>
              <td>
                <StatusBadge :value="task.status" :label="statusLabelOf(task)" dot />
                <span v-if="task.stalled" class="badge danger" style="margin-left: 4px; font-size: 11px">疑似卡死</span>
              </td>
              <td class="num">{{ task.progress ?? 0 }}%</td>
              <td class="muted">{{ formatTime(task.created_at) }}</td>
              <td class="num muted">{{ durationText(task) }}</td>
              <td class="muted">{{ formatTime(task.last_activity_at || task.started_at) }}</td>
              <td>
                <div class="actions">
                  <button class="btn ghost sm" @click.stop="openDetail(task)">日志</button>
                  <template v-if="canWrite">
                    <button
                      v-if="task.status === 'failed'"
                      class="btn ghost sm"
                      :disabled="retryingId === String(task.id)"
                      @click.stop="retryTask(task)"
                    >
                      {{ retryingId === String(task.id) ? '提交中…' : '重试' }}
                    </button>
                    <button
                      v-if="task.status === 'paused' && task.source === 'agent_run'"
                      class="btn ghost sm"
                      :disabled="controllingId === String(task.id)"
                      @click.stop="controlTask(task, 'resume')"
                    >继续</button>
                    <button
                      v-if="task.status === 'running' && task.source === 'agent_run'"
                      class="btn ghost sm"
                      :disabled="controllingId === String(task.id)"
                      @click.stop="controlTask(task, 'pause')"
                    >暂停</button>
                    <button
                      v-if="['queued', 'running', 'paused'].includes(task.status)"
                      class="btn ghost sm"
                      :disabled="controllingId === String(task.id)"
                      @click.stop="controlTask(task, 'force_cancel')"
                    >终止</button>
                  </template>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <StateBlock
        v-else
        kind="empty"
        title="没有匹配的任务"
        message="所有用户任务都会记录在这里；换一个状态筛选或清空关键词再看看。"
      />
      <Pager
        v-if="total !== null"
        :page="page"
        :page-size="pageSize"
        :total="total"
        :loading="loading"
        @update:page="gotoPage"
      />
    </template>
  </div>

  <Modal
    v-if="detailTask"
    :title="`任务日志 ${detailTask.id}`"
    :subtitle="`${sourceLabel(detailTask)} · ${detailTask.title || typeLabel(detailTask)}`"
    size="wide"
    @close="closeDetail"
  >
    <div v-if="detailLoading && !detail" class="card">
      <StateBlock kind="loading" title="加载执行过程…" />
    </div>
    <div v-else-if="detailError && !detail" class="card">
      <StateBlock kind="error" :message="detailError" />
    </div>
    <template v-else-if="detail">
      <div class="detail-meta">
        <div v-for="[label, value] in detailMeta" :key="label" class="detail-meta__item">
          <span class="detail-meta__label">{{ label }}</span>
          <span class="detail-meta__value">{{ value }}</span>
        </div>
      </div>

      <template v-if="stages.length">
        <h4 class="event-title">阶段进度</h4>
        <div class="stage-track">
          <span
            v-for="stage in stages"
            :key="stage.id"
            class="stage-chip"
            :class="`stage-${stage.state}`"
            :title="`${stage.started_at || ''} → ${stage.finished_at || ''}`"
          >
            <i class="stage-dot"></i>{{ stage.name || stage.id }}
            <em>{{ stageStateText(stage.state) }}</em>
          </span>
        </div>
      </template>
      <template v-else-if="taskSteps.length">
        <h4 class="event-title">任务步骤</h4>
        <div class="stage-track">
          <span
            v-for="step in taskSteps"
            :key="step.step_key"
            class="stage-chip"
            :class="`stage-${step.status === 'done' ? 'succeeded' : step.status}`"
            :title="step.updated_at || ''"
          >
            <i class="stage-dot"></i>{{ step.step_key }}
            <em>{{ stageStateText(step.status === 'done' ? 'succeeded' : step.status) }}</em>
          </span>
        </div>
      </template>

      <div class="log-head">
        <h4 class="event-title">任务日志<span class="sub">{{ events.length }} 条</span></h4>
        <span class="spacer"></span>
        <span v-if="detailLive" class="badge info" style="font-size: 11px">运行中 · 自动刷新</span>
        <span v-if="detail.truncated" class="badge warn" style="font-size: 11px">日志过多，仅展示最近 2000 条</span>
        <button class="btn ghost sm" @click="copyLog">
          <Icon name="copy" :size="13" />复制日志
        </button>
        <button class="btn ghost sm" @click="refreshDetail">刷新</button>
      </div>

      <div ref="logEl" class="task-log" @scroll.passive="onLogScroll">
        <div v-if="!events.length" class="task-log__empty">暂无执行日志。</div>
        <template v-else>
          <div class="task-log__spacer" :style="{ height: `${logRange.paddingTop}px` }" />
          <div
            v-for="ev in visibleEvents"
            :key="ev.seq"
            class="task-log__line"
            :class="`lvl-${ev.level}`"
            :title="ev.message"
          >
            <span class="task-log__seq">#{{ ev.seq }}</span>
            <span class="task-log__at">{{ formatClock(ev.at) }}</span>
            <span class="task-log__stage" :title="ev.stage">{{ stageNames[ev.stage] || ev.stage }}</span>
            <span class="task-log__msg">{{ ev.message }}</span>
          </div>
          <div class="task-log__spacer" :style="{ height: `${logRange.paddingBottom}px` }" />
        </template>
      </div>
    </template>

    <template #footer>
      <div class="spacer"></div>
      <template v-if="canWrite && detailTask">
        <button
          v-if="detailStatus === 'failed'"
          class="btn ghost sm"
          :disabled="retryingId === String(detailTask.id)"
          @click="retryTask(detailTask)"
        >重试</button>
        <button
          v-if="detailIsRun && detailStatus === 'running'"
          class="btn ghost sm"
          :disabled="controllingId === String(detailTask.id)"
          @click="controlTask(detailTask, 'pause')"
        >暂停</button>
        <button
          v-if="detailIsRun && ['paused', 'failed'].includes(detailStatus)"
          class="btn ghost sm"
          :disabled="controllingId === String(detailTask.id)"
          @click="controlTask(detailTask, 'resume')"
        >继续</button>
        <button
          v-if="isLive(detailTask)"
          class="btn ghost sm"
          :disabled="controllingId === String(detailTask.id)"
          @click="controlTask(detailTask, 'requeue')"
        >重新排队</button>
        <button
          v-if="isLive(detailTask)"
          class="btn ghost sm"
          :disabled="controllingId === String(detailTask.id)"
          @click="controlTask(detailTask, 'cancel')"
        >取消</button>
        <button
          v-if="isLive(detailTask)"
          class="btn ghost sm"
          :disabled="controllingId === String(detailTask.id)"
          @click="controlTask(detailTask, 'force_cancel')"
        >强制终止</button>
      </template>
    </template>
  </Modal>
</template>

<style scoped>
.filter-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 0 0 12px;
}
.filter-row .spacer {
  flex: 1;
}
.filter-chip {
  height: 26px;
  padding: 0 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-pill, 999px);
  background: #fff;
  color: var(--text-2);
  font-size: 12px;
  cursor: pointer;
}
.filter-chip:hover {
  border-color: var(--brand, #0d9488);
  color: var(--brand, #0d9488);
}
.filter-chip.on {
  background: var(--brand, #0d9488);
  border-color: var(--brand, #0d9488);
  color: #fff;
}
.input.mini {
  width: 150px;
  height: 28px;
  font-size: 12px;
}
.row-click {
  cursor: pointer;
}

.detail-meta {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 10px 18px;
  margin-bottom: 16px;
}
.detail-meta__item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.detail-meta__label {
  font-size: 11px;
  color: var(--color-text-3, #8a94a6);
}
.detail-meta__value {
  font-size: 13px;
  font-weight: 600;
  word-break: break-word;
}

.event-title {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 700;
}
.event-title .sub {
  margin-left: 6px;
  font-size: 11.5px;
  font-weight: 400;
  color: var(--text-3);
}

.stage-track {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 16px;
}
.stage-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 24px;
  padding: 0 9px;
  border-radius: 999px;
  background: #f2f5f4;
  color: var(--text-2);
  font-size: 12px;
}
.stage-chip em {
  font-style: normal;
  font-size: 11px;
  color: var(--text-3);
}
.stage-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}
.stage-running {
  background: var(--blue-bg, #e8f1ff);
  color: var(--blue, #2563eb);
}
.stage-succeeded {
  background: var(--green-bg, #e8f7ef);
  color: var(--green, #15803d);
}
.stage-failed {
  background: var(--red-bg, #fdecec);
  color: var(--red, #dc2626);
}

.log-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.log-head .spacer {
  flex: 1;
}
.log-head .event-title {
  margin: 0;
}

.task-log {
  max-height: 460px;
  min-height: 160px;
  overflow: auto;
  padding: 10px 12px;
  background: #0f1622;
  border-radius: 10px;
  color: #c6d3e6;
  font-family: var(--mono, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace);
  font-size: 12px;
  line-height: 1.7;
}
.task-log__empty {
  color: #6c7c93;
}
.task-log__spacer {
  flex: none;
}

.task-log__line {
  display: grid;
  grid-template-columns: 52px 108px 130px 1fr;
  gap: 10px;
  align-items: center;
  height: 26px;
  padding: 0;
  box-sizing: border-box;
}
.task-log__line:hover {
  background: rgba(255, 255, 255, 0.04);
}
.task-log__seq {
  color: #64748b;
  font-variant-numeric: tabular-nums;
}
.task-log__at {
  color: #8ba0bb;
  font-variant-numeric: tabular-nums;
}
.task-log__stage {
  color: #5fd39a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.task-log__msg {
  /* 定高虚拟行：超长消息单行省略，完整内容看 title 或「复制日志」 */
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.task-log__line.lvl-warning .task-log__msg {
  color: #fbbf24;
}
.task-log__line.lvl-error .task-log__msg {
  color: #ff8b7d;
}
@media (max-width: 760px) {
  .task-log__line {
    grid-template-columns: 44px 1fr;
  }
  .task-log__stage,
  .task-log__at {
    display: none;
  }
  .input.mini {
    width: 120px;
  }
}
</style>
