<template>
  <aside class="card task-center" aria-label="任务中心">
    <header class="task-center__head">
      <h2 class="task-center__title">任务中心</h2>
      <button type="button" class="btn btn--ghost btn--sm" :disabled="loading" @click="load">
        刷新
      </button>
    </header>

    <p v-if="actionError" class="task-center__action-error" role="alert">{{ actionError }}</p>

    <div class="task-center__body">
      <div v-if="loading && !items.length" class="task-center__state">加载中…</div>
      <p v-else-if="error" class="task-center__state task-center__state--error">{{ error }}</p>
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
          <span class="badge task-center__badge" :class="STATUS_TONE[task.status]">
            {{ statusLabel(task.status) }}
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
              @click="resume(task)"
            >
              {{ busyId === task.run_id ? '继续中…' : '继续' }}
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
    <div v-if="cancelError" class="alert" role="alert">{{ cancelError }}</div>
    <template #footer>
      <button type="button" class="btn" :disabled="!!busyId" @click="closeCancel">继续等待</button>
      <button type="button" class="btn btn--danger" :disabled="!!busyId" @click="confirmCancel">
        {{ busyId ? '取消中…' : '确认取消' }}
      </button>
    </template>
  </AppDialog>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import AppDialog from '@/components/AppDialog.vue'
import type { RunDetail } from '@/types'
import { cancelRun, listRuns, pauseRun, resumeRun } from '@/services/agentApi'
import { ApiError } from '@/services/http'
import { STATUS_TONE, statusLabel } from '@/utils/format'

const props = defineProps<{ currentId: string; status?: string }>()

const PAGE_SIZE = 8
const TERMINAL = ['succeeded', 'failed', 'canceled']

const items = ref<RunDetail[]>([])
const page = ref(1)
const total = ref(0)
const nextOffset = ref<number | undefined>(undefined)
const loading = ref(false)
const error = ref('')
const actionError = ref('')
const busyId = ref('')
const cancelTarget = ref<RunDetail | null>(null)
const cancelError = ref('')
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

function parseTime(iso?: string | null): number | null {
  if (!iso) return null
  const at = new Date(iso).getTime()
  return Number.isNaN(at) ? null : at
}

function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  if (total < 60) return `${total} 秒`
  const minutes = Math.floor(total / 60)
  const rest = total % 60
  return `${minutes} 分 ${String(rest).padStart(2, '0')} 秒`
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

function errorText(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message || fallback : fallback
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const result = await listRuns({}, { limit: PAGE_SIZE, offset: (page.value - 1) * PAGE_SIZE })
    items.value = result.items
    total.value = result.total ?? result.items.length
    nextOffset.value = result.next_offset
    syncTick()
  } catch {
    error.value = '任务列表加载失败'
  } finally {
    loading.value = false
  }
}

function goPage(next: number): void {
  if (next < 1 || next > pageCount.value) return
  page.value = next
  load()
}

/** 停止 = 暂停：任务进入 paused，可再选「开始」继续或「取消」终止 */
async function stop(task: RunDetail): Promise<void> {
  if (busyId.value) return
  busyId.value = task.run_id
  actionError.value = ''
  try {
    await pauseRun(task.run_id)
    await load()
  } catch (err) {
    actionError.value = errorText(err, '停止失败，请稍后重试')
  } finally {
    busyId.value = ''
  }
}

function openCancel(task: RunDetail): void {
  if (busyId.value) return
  cancelError.value = ''
  cancelTarget.value = task
}

function closeCancel(): void {
  if (busyId.value) return
  cancelTarget.value = null
  cancelError.value = ''
}

async function confirmCancel(): Promise<void> {
  const task = cancelTarget.value
  if (!task || busyId.value) return
  busyId.value = task.run_id
  cancelError.value = ''
  actionError.value = ''
  try {
    await cancelRun(task.run_id)
    cancelTarget.value = null
    await load()
  } catch (err) {
    cancelError.value = errorText(err, '取消失败，请稍后重试')
  } finally {
    busyId.value = ''
  }
}

async function resume(task: RunDetail): Promise<void> {
  if (busyId.value) return
  busyId.value = task.run_id
  actionError.value = ''
  try {
    await resumeRun(task.run_id, { approval: true })
    await load()
  } catch (err) {
    actionError.value = errorText(err, '继续失败，请稍后重试')
  } finally {
    busyId.value = ''
  }
}

watch([() => props.currentId, () => props.status], load)
onMounted(load)
onBeforeUnmount(() => {
  if (tickTimer !== null) window.clearInterval(tickTimer)
  tickTimer = null
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
  padding: 0 6px;
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

.task-center__state--error {
  color: var(--color-danger);
}

.task-center__action-error {
  flex: none;
  padding: 10px 16px;
  border-bottom: 1px solid var(--color-line);
  font-size: var(--text-xs);
  color: var(--color-danger);
}

.task-center__list {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
}

.task-center__item {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  height: var(--tc-row-h);
  padding: 0 6px;
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
  font-size: var(--text-md);
  font-weight: 700;
  color: var(--color-text-2);
}

.task-center__link.is-active .task-center__name {
  color: var(--color-brand);
  font-weight: 700;
}

.task-center__badge {
  flex: none;
  height: 20px;
  padding: 0 7px;
  font-size: 14px;
}

.task-center__action {
  flex: none;
  height: 24px;
  padding: 0 9px;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-pill);
  background: #fff;
  color: var(--color-text-2);
  font-size: 14px;
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
  font-size: 14px;
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
