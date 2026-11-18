<template>
  <aside class="card task-center" aria-label="任务中心">
    <header class="task-center__head">
      <h2 class="task-center__title">任务中心</h2>
      <button type="button" class="btn btn--ghost btn--sm" :disabled="loading" @click="load()">
        刷新
      </button>
    </header>

    <div class="task-center__body">
      <div v-if="loading && !items.length" class="task-center__state">加载中…</div>
      <p v-else-if="!items.length" class="task-center__state">暂无任务</p>

      <ul v-else class="task-center__list">
        <li v-for="task in items" :key="task.run_id" class="task-center__item">
          <RouterLink
            :to="{ name: 'workspace', params: { id: task.run_id } }"
            class="task-center__link"
            :class="{ 'is-active': task.run_id === currentId }"
            :aria-current="task.run_id === currentId ? 'page' : undefined"
            :title="task.title || '未命名作品'"
          >
            <span class="task-center__name">{{ task.title || '未命名作品' }}</span>
          </RouterLink>
          <span
            class="badge task-center__badge"
            :class="taskStatusTone(task)"
            :title="isNodeFailure(task) ? task.error?.message : undefined"
          >
            {{ taskStatusLabel(task) }}
          </span>
          <span class="task-center__time" title="用时">{{ durationText(task) }}</span>
          <button
            v-if="canStop(task)"
            type="button"
            class="task-center__action"
            :disabled="!!busyId"
            @click="stop(task)"
          >
            {{ busyId === task.run_id ? '停止中…' : '停止' }}
          </button>
          <template v-else-if="canStart(task)">
            <button
              type="button"
              class="task-center__action task-center__action--start"
              :disabled="!!busyId"
              @click="isNodeFailure(task) ? retry(task) : resume(task)"
            >
              {{ pausedActionLabel(task) }}
            </button>
            <button
              type="button"
              class="task-center__action task-center__action--danger"
              :disabled="!!busyId"
              @click="openCancel(task)"
            >
              取消
            </button>
          </template>
          <button
            v-else-if="canRetryRun(task)"
            type="button"
            class="task-center__action task-center__action--start"
            :disabled="!!busyId"
            @click="retry(task)"
          >
            {{ busyId === task.run_id ? '重试中…' : '重试' }}
          </button>
        </li>
      </ul>
    </div>

    <nav v-if="total > PAGE_SIZE" class="task-center__pager" aria-label="任务分页">
      <button
        type="button"
        class="btn btn--ghost btn--sm"
        :disabled="loading || page === 1"
        @click="goPage(page - 1)"
      >
        上一页
      </button>
      <span class="task-center__page">{{ page }} / {{ pageCount }}</span>
      <button
        type="button"
        class="btn btn--ghost btn--sm"
        :disabled="loading || !hasNext"
        @click="goPage(page + 1)"
      >
        下一页
      </button>
    </nav>
  </aside>

  <AppDialog :open="!!cancelTarget" title="取消任务" @close="closeCancel">
    <p class="task-center__dialog-text">
      取消后任务停止推进，已完成阶段会保留，但无法继续。确定取消《{{
        cancelTarget?.title || '未命名作品'
      }}》吗？
    </p>
    <template #footer>
      <button type="button" class="btn" :disabled="!!busyId" @click="closeCancel">继续等待</button>
      <button type="button" class="btn btn--danger" :disabled="!!busyId" @click="confirmCancel">
        {{ busyId ? '取消中…' : '确认取消' }}
      </button>
    </template>
  </AppDialog>

  <ErrorDialog
    :open="!!notice"
    :title="notice?.title || '操作提示'"
    :message="notice?.message || ''"
    :tone="notice?.tone || 'error'"
    @close="closeNotice"
  />
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import AppDialog from '@/components/AppDialog.vue'
import ErrorDialog from '@/components/ErrorDialog.vue'
import type { RunDetail } from '@/types'
import { cancelRun, getRun, listRuns, pauseRun, resumeRun } from '@/services/agentApi'
import { useRunFeed } from '@/composables/useRunFeed'
import { ApiError } from '@/services/http'
import { STATUS_TONE, statusLabel } from '@/utils/format'

const props = defineProps<{ currentId: string; status?: string }>()
const emit = defineEmits<{ (e: 'changed', runId?: string): void }>()

const PAGE_SIZE = 8
const TERMINAL = ['succeeded', 'failed', 'canceled']
/** 停止请求：running 的任务要等引擎在章节/段落边界落 paused，轮询确认避免「停止中…」悬挂 */
const STOP_POLL_INTERVAL = 2000
const STOP_POLL_TIMEOUT = 30000
const items = ref<RunDetail[]>([])
const page = ref(1)
const total = ref(0)
const nextOffset = ref<number | undefined>(undefined)
const loading = ref(false)
const busyId = ref('')
const cancelTarget = ref<RunDetail | null>(null)
/** 任务列表不再内联回显错误，统一走 ErrorDialog 弹出 */
const notice = ref<{ title: string; message: string; tone: 'error' | 'warn' | 'info' | 'success' } | null>(null)
/** 每秒推进一次，仅用于「生成中」行的耗时文本刷新 */
const now = ref(Date.now())
let tickTimer: number | null = null
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))
const hasNext = computed(() => nextOffset.value !== undefined)

function canStop(task: RunDetail): boolean {
  return task.status === 'queued' || task.status === 'running'
}

/** 暂停的运行都可以继续：审查暂停需在工作台确认，热门写作是被用户停止的 */
function canStart(task: RunDetail): boolean {
  return task.status === 'paused'
}

/** 节点失败会转成 paused（可续跑），此时带 error：语义上是「重试失败节点」而不是「继续」 */
function isNodeFailure(task: RunDetail): boolean {
  return task.status === 'paused' && !!task.error
}

/** 已停止=用户主动暂停；已中断=节点失败转暂停，需要重试 */
function taskStatusLabel(task: RunDetail): string {
  return isNodeFailure(task) ? '已中断' : statusLabel(task.status)
}

function taskStatusTone(task: RunDetail): string {
  return isNodeFailure(task) ? 'badge--danger' : STATUS_TONE[task.status]
}

function pausedActionLabel(task: RunDetail): string {
  const retry = isNodeFailure(task)
  if (busyId.value === task.run_id) return retry ? '重试中…' : '继续中…'
  return retry ? '重试' : '继续'
}

/** 失败运行可重试：服务端要求 retry_failed=true，只重跑失败节点 */
function canRetryRun(task: RunDetail): boolean {
  return task.status === 'failed'
}

function parseTime(iso?: string | null): number | null {
  if (!iso) return null
  const at = new Date(iso).getTime()
  return Number.isNaN(at) ? null : at
}

/** 用时统一压成 mm:ss，避免「11 分 21 秒」把标题和操作按钮挤出可视区 */
function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  const minutes = Math.floor(total / 60)
  const rest = total % 60
  return `${minutes}:${String(rest).padStart(2, '0')}`
}

/** 只有排队中/生成中才需要秒级刷新，暂停后用时定格 */
function isLive(task: RunDetail): boolean {
  return task.status === 'queued' || task.status === 'running'
}

/**
 * 用时：优先 duration_seconds，其次 finished_at - created_at；
 * 结束任务缺 finished_at 时用 updated_at 兜底并标「估算」；
 * 暂停任务停在暂停时刻，运行中显示到当前的已运行时长（每秒刷新）。
 */
function durationText(task: RunDetail): string {
  if (typeof task.duration_seconds === 'number' && task.duration_seconds >= 0) {
    return formatDuration(task.duration_seconds)
  }
  const start = parseTime(task.created_at)
  if (start === null) return ''
  if (task.status === 'paused') {
    const pausedAt = parseTime(task.updated_at) ?? parseTime(task.started_at)
    return formatDuration(((pausedAt ?? now.value) - start) / 1000)
  }
  const finished = TERMINAL.includes(task.status)
  if (finished) {
    const end = parseTime(task.finished_at)
    if (end !== null) return formatDuration((end - start) / 1000)
    // 缺 finished_at 时用 updated_at 估算；两者都缺则退到当前时间，避免出现空值
    const updated = parseTime(task.updated_at) ?? parseTime(task.started_at)
    return `${formatDuration(((updated ?? now.value) - start) / 1000)}（估算）`
  }
  return formatDuration((now.value - start) / 1000)
}

/** 有未结束任务时才开启秒级刷新，避免整表无意义重渲染 */
function syncTick(): void {
  const live = items.value.some(isLive)
  if (live && tickTimer === null) {
    tickTimer = window.setInterval(() => {
      now.value = Date.now()
    }, 1000)
  } else if (!live && tickTimer !== null) {
    window.clearInterval(tickTimer)
    tickTimer = null
  }
}

/**
 * 存在未结束任务（含 paused）时订阅账号级 SSE；服务端状态变更推送 refresh。
 * SSE 不可用时自动降级为 4 秒轮询，界面状态标记仍会跟随。
 */
const runFeed = useRunFeed({
  active: () => items.value.some((task) => !TERMINAL.includes(task.status)),
  refresh: () => {
    if (busyId.value) return // 操作进行中不打断按钮态
    void load(true)
  },
  pollIntervalMs: 4000,
})

function syncListPolling(): void {
  runFeed.sync(items.value.some((task) => !TERMINAL.includes(task.status)))
}

function errorText(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message || fallback : fallback
}

function showNotice(
  title: string,
  message: string,
  tone: 'error' | 'warn' | 'info' | 'success' = 'error',
): void {
  notice.value = { title, message, tone }
}

function closeNotice(): void {
  notice.value = null
}

async function load(silent = false): Promise<void> {
  if (!silent) loading.value = true
  try {
    const result = await listRuns({}, { limit: PAGE_SIZE, offset: (page.value - 1) * PAGE_SIZE })
    items.value = result.items
    total.value = result.total ?? result.items.length
    nextOffset.value = result.next_offset
    syncTick()
    syncListPolling()
  } catch {
    if (!silent) showNotice('加载失败', '任务列表加载失败，请稍后重试')
  } finally {
    if (!silent) loading.value = false
  }
}

function goPage(next: number): void {
  if (next < 1 || next > pageCount.value) return
  page.value = next
  load()
}

/** 轮询运行状态直到离开 queued/running；查询失败立即放弃，避免无意义等待 */
async function waitStopped(runId: string): Promise<boolean> {
  const deadline = Date.now() + STOP_POLL_TIMEOUT
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, STOP_POLL_INTERVAL))
    try {
      const detail = await getRun(runId)
      if (detail.status !== 'queued' && detail.status !== 'running') return true
    } catch {
      return false
    }
  }
  return false
}

/** 停止 = 暂停：任务进入 paused，可再选「开始」继续或「取消」终止 */
async function stop(task: RunDetail): Promise<void> {
  if (busyId.value) return
  busyId.value = task.run_id
  try {
    await pauseRun(task.run_id)
    // running 的任务由引擎在章节/段落边界落 paused：轮询确认后再放开按钮
    const stopped = await waitStopped(task.run_id)
    emit('changed', task.run_id)
    await load()
    if (!stopped) {
      showNotice('停止请求已提交', '任务将在当前章节完成后暂停，状态会自动刷新', 'info')
    }
  } catch (err) {
    showNotice('停止失败', errorText(err, '停止失败，请稍后重试'))
  } finally {
    busyId.value = ''
  }
}

function openCancel(task: RunDetail): void {
  if (busyId.value) return
  cancelTarget.value = task
}

function closeCancel(): void {
  if (busyId.value) return
  cancelTarget.value = null
}

async function confirmCancel(): Promise<void> {
  const task = cancelTarget.value
  if (!task || busyId.value) return
  busyId.value = task.run_id
  try {
    await cancelRun(task.run_id)
    cancelTarget.value = null
    // running 任务要等检查点才落 canceled，等一轮再回调，避免工作台闪现旧状态
    await waitStopped(task.run_id)
    emit('changed', task.run_id)
    await load()
  } catch (err) {
    cancelTarget.value = null
    showNotice('取消失败', errorText(err, '取消失败，请稍后重试'))
  } finally {
    busyId.value = ''
  }
}

async function resume(task: RunDetail): Promise<void> {
  if (busyId.value) return
  busyId.value = task.run_id
  try {
    await resumeRun(task.run_id, { approval: true })
    emit('changed', task.run_id)
    await load()
  } catch (err) {
    showNotice('继续失败', errorText(err, '继续失败，请稍后重试'))
  } finally {
    busyId.value = ''
  }
}

/** 失败重试：只重置失败节点，已完成节点复用 checkpoint */
async function retry(task: RunDetail): Promise<void> {
  if (busyId.value) return
  busyId.value = task.run_id
  try {
    await resumeRun(task.run_id, { approval: true, retry_failed: true })
    emit('changed', task.run_id)
    await load()
  } catch (err) {
    showNotice('重试失败', errorText(err, '重试失败，请稍后重试'))
  } finally {
    busyId.value = ''
  }
}

watch([() => props.currentId, () => props.status], () => load())
onMounted(() => load())
onBeforeUnmount(() => {
  if (tickTimer !== null) window.clearInterval(tickTimer)
  tickTimer = null
  runFeed.stop()
})
</script>

<style scoped>
.task-center {
  /* 固定高度 = 8 行 + 表头 + 分页（另含卡片上下 2px 边框），行数不足时也不塌陷 */
  --tc-row-h: 43px;
  display: flex;
  flex-direction: column;
  height: calc(var(--tc-row-h) * 8 + 112px);
  min-width: 0;
  align-self: start;
  overflow: hidden;
}

.task-center__head {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  height: 53px;
  padding: 0 16px;
  border-bottom: 1px solid var(--color-line);
}

.task-center__title {
  font-size: var(--text-md);
  font-weight: 700;
}

.task-center__body {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  min-height: 0;
  padding: 0 4px;
}

.task-center__state {
  display: flex;
  flex: 1 1 auto;
  align-items: center;
  justify-content: center;
  padding: 16px;
  font-size: var(--text-xs);
  color: var(--color-text-3);
}

.task-center__list {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  /* 行内「状态 + 用时 + 继续 + 取消」是最宽组合，禁止横向滚动条 */
  overflow-x: hidden;
}

.task-center__item {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  overflow: hidden;
  height: var(--tc-row-h);
  padding: 0 4px;
}

.task-center__item + .task-center__item {
  border-top: 1px solid var(--color-line);
}

.task-center__item:hover {
  background: var(--color-bg-softer);
}

.task-center__link {
  flex: 1 1 auto;
  min-width: 0;
  color: inherit;
}

.task-center__name {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  /* 与徽章/用时同字号同行高，保证整行文字水平对齐 */
  font-size: var(--text-sm);
  line-height: 20px;
  font-weight: 400;
  color: var(--color-text-2);
}

.task-center__link.is-active .task-center__name {
  color: var(--color-brand);
}

.task-center__badge {
  flex: none;
  height: 18px;
  padding: 0 5px;
  font-size: 12px;
  line-height: 18px;
  white-space: nowrap;
}

.task-center__action {
  flex: none;
  height: 22px;
  padding: 0 7px;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-pill);
  background: #fff;
  color: var(--color-text-2);
  font-size: 12px;
  font-family: inherit;
}

/* 仅按钮响应 hover，避免只读文本看起来可点 */
button.task-center__action:hover:not(:disabled) {
  border-color: var(--color-brand);
  color: var(--color-brand);
}

.task-center__action:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.task-center__action--start {
  border-color: rgba(13, 148, 136, 0.45);
  color: var(--color-brand);
}

.task-center__action--danger {
  border-color: #f3c3bf;
  color: var(--color-danger);
}

button.task-center__action--danger:hover:not(:disabled) {
  border-color: var(--color-danger);
  background: var(--color-danger-soft);
  color: var(--color-danger);
}

.task-center__dialog-text {
  color: var(--color-text-2);
  font-size: 14px;
  line-height: 1.7;
}

.task-center__time {
  flex: none;
  font-size: 12px;
  line-height: 18px;
  color: var(--color-text-3);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.task-center__pager {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  height: 57px;
  padding: 0 10px;
  border-top: 1px solid var(--color-line);
}

.task-center__page {
  font-size: 14px;
  color: var(--color-text-3);
  font-family: var(--font-mono);
}

/* 窄屏下任务中心落到内容下方，占满整列宽度 */
@media (max-width: 980px) {
  .task-center {
    align-self: stretch;
  }
}
</style>
