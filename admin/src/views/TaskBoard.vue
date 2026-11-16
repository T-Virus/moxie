<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api, errorMessage } from '../api'
import { can } from '../roles'
import { getRole } from '../session'
import { pushToast } from '../toast'
import type { TaskDashboard, TaskRow } from '../types'
import { formatNumber, formatTime } from '../ui'
import Icon from '../components/Icon.vue'
import PageHeader from '../components/PageHeader.vue'
import StateBlock from '../components/StateBlock.vue'
import StatusBadge from '../components/StatusBadge.vue'
import Modal from '../components/Modal.vue'
import type { TaskDetail } from '../types'

const role = getRole()
const canRetry = computed(() => can(role, 'tasks:write'))

const dashboard = ref<TaskDashboard | null>(null)
const loading = ref(false)
const error = ref('')
const autoRefresh = ref(true)
const retryingId = ref('')
const controllingId = ref('')

const detailTask = ref<TaskRow | null>(null)
const detail = ref<TaskDetail | null>(null)
const detailLoading = ref(false)
const detailError = ref('')

const detailMeta = computed<[string, unknown][]>(() => {
  const d = (detail.value?.detail || {}) as Record<string, unknown>
  const summary = (d.summary as Record<string, unknown>) || {}
  const chapters = Array.isArray(d.chapters) ? (d.chapters as unknown[]) : []
  const summaries = Array.isArray(d.chapter_summaries) ? (d.chapter_summaries as unknown[]) : []
  const volumes = Array.isArray(d.volumes) ? (d.volumes as unknown[]) : []
  return [
    ['状态', d.status],
    ['进度', typeof d.progress === 'number' ? `${d.progress}%` : undefined],
    ['错误码', d.error_code],
    ['尝试次数', d.attempts],
    ['正文章数', ((summary.chapters_count as number) ?? chapters.length) || undefined],
    ['概括章数', summaries.length || undefined],
    ['卷数', volumes.length || undefined],
    ['创建时间', d.created_at],
    ['开始时间', d.started_at],
    ['结束时间', d.finished_at],
  ].filter(([, v]) => v !== undefined && v !== null && v !== '') as [string, unknown][]
})

const detailStatus = computed(() => {
  const d = (detail.value?.detail || {}) as Record<string, unknown>
  return String(d.status || detailTask.value?.status || '')
})
const detailIsRun = computed(() => detailTask.value?.source === 'agent_run')
const detailLive = computed(() => ['queued', 'running', 'paused'].includes(detailStatus.value))

async function openDetail(task: TaskRow) {
  detailTask.value = task
  detail.value = null
  detailError.value = ''
  detailLoading.value = true
  try {
    detail.value = await api.taskDetail(String(task.id), task.source)
  } catch (e) {
    detailError.value = errorMessage(e)
  } finally {
    detailLoading.value = false
  }
}

function closeDetail() {
  detailTask.value = null
}

function taskList(key: 'running' | 'failed'): TaskRow[] {
  const data = dashboard.value
  if (!data) return []
  const direct = data[key] as TaskRow[] | undefined
  if (Array.isArray(direct)) return direct
  const prefixed = data[`${key}_tasks`] as TaskRow[] | undefined
  if (Array.isArray(prefixed)) return prefixed
  const nested = (data.tasks as Record<string, unknown> | undefined)?.[key]
  return Array.isArray(nested) ? nested as TaskRow[] : []
}

const runningTasks = computed(() => taskList('running'))
const failedTasks = computed(() => taskList('failed'))

const queueDepth = computed(() => dashboard.value?.queue_depth ?? null)
const runningCount = computed(() => dashboard.value?.running_count ?? runningTasks.value.length)
const failedCount = computed(() => dashboard.value?.failed_count ?? failedTasks.value.length)
const stalledCount = computed(() => runningTasks.value.filter((task) => task.stalled).length)
const retryableCount = computed(() => {
  if (typeof dashboard.value?.retryable_count === 'number') return dashboard.value.retryable_count
  return failedTasks.value.filter(item => ['failed', 'retry_pending', 'queued'].includes(String(item.status))).length
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    dashboard.value = await api.taskDashboard()
  } catch (e) {
    dashboard.value = null
    error.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

async function retryTask(task: TaskRow) {
  retryingId.value = String(task.id)
  try {
    await api.taskRetry(String(task.id))
    pushToast(`任务 ${task.id} 已重新入队`)
    await load()
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
  const label = CONTROL_LABEL[action]
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
    pushToast(`任务 ${task.id} ${label}成功${res?.status ? `（当前状态：${res.status}）` : ''}`)
    await load()
    if (detailTask.value && String(detailTask.value.id) === String(task.id)) {
      await openDetail(detailTask.value)
    }
  } catch (e) {
    pushToast(errorMessage(e), 'error')
  } finally {
    controllingId.value = ''
  }
}

let timer: number | null = null
onMounted(() => {
  void load()
  // 运行中任务状态变化快，30 秒刷新一次在排查卡死时会误判，改为 10 秒
  timer = window.setInterval(() => {
    if (autoRefresh.value) void load()
  }, 10_000)
})
onUnmounted(() => {
  if (timer !== null) window.clearInterval(timer)
})
</script>

<template>
  <PageHeader title="任务看板" desc="聚合拆解/改编任务与创作页触发的写作运行，查看队列深度、运行中与失败任务，并可直接取消、暂停、继续、重新排队或强制终止。页面每 10 秒自动刷新。">
    <label class="badge muted" style="cursor: pointer">
      <input v-model="autoRefresh" type="checkbox" style="margin-right: 5px" />自动刷新
    </label>
    <button class="btn ghost sm" :disabled="loading" @click="load">
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
      <div class="stat-desc">{{ stalledCount ? `${stalledCount} 条疑似卡死，建议强制终止` : '当前持有租约的任务' }}</div>
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

  <div v-if="loading && !dashboard && !error" class="card">
    <StateBlock kind="loading" title="正在加载任务看板…" />
  </div>

  <div v-else-if="error" class="card">
    <StateBlock kind="error" title="任务看板加载失败" :message="error" retry-label="重试" @retry="load" />
  </div>

  <template v-else-if="dashboard">
    <div class="card">
      <div class="card-head">
        <div class="card-title">运行中任务<span class="sub">{{ runningTasks.length }} 条</span></div>
        <div class="spacer"></div>
        <span class="muted" style="font-size: 11.5px">看板生成时间 {{ formatTime(dashboard.generated_at) }}</span>
      </div>
      <div v-if="runningTasks.length" class="table-wrap">
        <table class="data-table">
          <thead><tr><th>任务 ID</th><th>账号</th><th>来源 / 类型</th><th>作品</th><th>状态</th><th class="num">进度</th><th>开始时间</th><th>最近活动</th><th>创建时间</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="task in runningTasks" :key="task.id">
              <td class="mono truncate" :title="String(task.id)">{{ task.id }}</td>
              <td>{{ task.account_id ? `#${task.account_id}` : '—' }}</td>
              <td>
                <span class="badge muted" style="font-size: 11px">{{ task.source === 'agent_run' ? '写作运行' : '拆解任务' }}</span>
                {{ task.type || '—' }}
              </td>
              <td class="truncate" :title="task.title || ''">{{ task.title || '—' }}</td>
              <td><StatusBadge :value="task.status" dot /></td>
              <td class="num">{{ task.progress ?? 0 }}%</td>
              <td class="muted">{{ formatTime(task.started_at) }}</td>
              <td class="muted">
                {{ formatTime(task.last_activity_at || task.started_at) }}
                <span v-if="task.stalled" class="badge danger" style="margin-left: 4px; font-size: 11px">疑似卡死</span>
              </td>
              <td class="muted">{{ formatTime(task.created_at) }}</td>
              <td>
                <button class="btn ghost sm" @click="openDetail(task)">详情</button>
                <template v-if="canRetry">
                  <button
                    class="btn ghost sm"
                    :disabled="controllingId === String(task.id)"
                    @click="controlTask(task, 'cancel')"
                  >取消</button>
                  <button
                    class="btn ghost sm"
                    :disabled="controllingId === String(task.id)"
                    @click="controlTask(task, 'force_cancel')"
                  >强制终止</button>
                </template>
                <span v-else class="muted" style="font-size: 12px">只读</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <StateBlock v-else kind="empty" title="当前没有运行中的任务" message="队列空闲或任务尚未被 worker 领取。" />
    </div>

    <div class="card">
      <div class="card-head">
        <div class="card-title">失败任务<span class="sub">{{ failedTasks.length }} 条</span></div>
        <div class="spacer"></div>
        <span v-if="!canRetry" class="badge muted">support 只读</span>
      </div>
      <div v-if="failedTasks.length" class="table-wrap">
        <table class="data-table">
          <thead>
            <tr><th>任务 ID</th><th>账号</th><th>来源 / 类型</th><th>作品</th><th>状态</th><th>错误码</th><th class="num">尝试</th><th>创建时间</th><th style="width: 90px">操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="task in failedTasks" :key="task.id">
              <td class="mono truncate" :title="String(task.id)">{{ task.id }}</td>
              <td>{{ task.account_id ? `#${task.account_id}` : '—' }}</td>
              <td>
                <span class="badge muted" style="font-size: 11px">{{ task.source === 'agent_run' ? '写作运行' : '拆解任务' }}</span>
                {{ task.type || '—' }}
              </td>
              <td class="truncate" :title="task.title || ''">{{ task.title || '—' }}</td>
              <td><StatusBadge :value="task.status" dot /></td>
              <td class="mono">{{ task.error_code || '—' }}</td>
              <td class="num">{{ task.attempts ?? '—' }}</td>
              <td class="muted">{{ formatTime(task.created_at) }}</td>
              <td>
                <button class="btn ghost sm" @click="openDetail(task)">详情</button>
                <button v-if="canRetry" class="btn ghost sm" :disabled="retryingId === String(task.id)" @click="retryTask(task)">
                  {{ retryingId === String(task.id) ? '提交中…' : '重试' }}
                </button>
                <span v-else class="muted" style="font-size: 12px">只读</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <StateBlock v-else kind="empty" title="没有失败任务" message="最近没有需要处理的失败任务。" />
    </div>
  </template>

  <Modal
    v-if="detailTask"
    :title="`任务详情 ${detailTask.id}`"
    :subtitle="`${detailTask.source === 'agent_run' ? '写作运行' : '拆解任务'} · ${detailTask.title || '未命名作品'}`"
    size="wide"
    @close="closeDetail"
  >
    <div v-if="detailLoading" class="card">
      <StateBlock kind="loading" title="加载执行过程…" />
    </div>
    <div v-else-if="detailError" class="card">
      <StateBlock kind="error" :message="detailError" />
    </div>
    <template v-else-if="detail">
      <div class="detail-meta">
        <div v-for="[label, value] in detailMeta" :key="label" class="detail-meta__item">
          <span class="detail-meta__label">{{ label }}</span>
          <span class="detail-meta__value">{{ value }}</span>
        </div>
      </div>
      <h4 class="event-title">执行过程（{{ detail.events.length }} 条）</h4>
      <div v-if="!detail.events.length" class="muted">暂无执行过程事件。</div>
      <ul v-else class="event-log">
        <li v-for="ev in detail.events" :key="ev.seq" :class="['event-log__item', `lvl-${ev.level}`]">
          <span class="event-log__seq">#{{ ev.seq }}</span>
          <span class="event-log__stage">{{ ev.stage }}</span>
          <span class="event-log__at muted">{{ formatTime(ev.at) }}</span>
          <span class="event-log__msg">{{ ev.message }}</span>
        </li>
      </ul>
    </template>
    <template #footer>
      <button v-if="detailTask" class="btn ghost sm" @click="openDetail(detailTask)">刷新</button>
      <div class="spacer"></div>
      <template v-if="canRetry && detailTask">
        <button
          v-if="detailStatus === 'failed'"
          class="btn ghost sm"
          :disabled="retryingId === String(detailTask.id)"
          @click="retryTask(detailTask)"
        >重试</button>
        <button
          v-if="detailIsRun && ['queued', 'running'].includes(detailStatus)"
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
          v-if="detailLive"
          class="btn ghost sm"
          :disabled="controllingId === String(detailTask.id)"
          @click="controlTask(detailTask, 'requeue')"
        >重新排队</button>
        <button
          v-if="detailLive"
          class="btn ghost sm"
          :disabled="controllingId === String(detailTask.id)"
          @click="controlTask(detailTask, 'cancel')"
        >取消</button>
        <button
          v-if="detailLive"
          class="btn ghost sm"
          :disabled="controllingId === String(detailTask.id)"
          @click="controlTask(detailTask, 'force_cancel')"
        >强制终止</button>
      </template>
    </template>
  </Modal>
</template>

<style scoped>
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
}
.event-title {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 700;
}
.event-log {
  max-height: 420px;
  overflow-y: auto;
  margin: 0;
  padding: 0;
  list-style: none;
  border: 1px solid var(--color-line, #e6e8ec);
  border-radius: 8px;
}
.event-log__item {
  display: grid;
  grid-template-columns: 44px 120px 132px 1fr;
  gap: 8px;
  align-items: baseline;
  padding: 7px 12px;
  font-size: 12.5px;
  border-bottom: 1px solid var(--color-line, #e6e8ec);
}
.event-log__item:last-child {
  border-bottom: none;
}
.event-log__seq {
  color: var(--color-text-3, #8a94a6);
  font-variant-numeric: tabular-nums;
}
.event-log__stage {
  font-weight: 600;
  color: var(--color-brand, #0d9488);
}
.event-log__at {
  font-variant-numeric: tabular-nums;
}
.event-log__msg {
  white-space: pre-wrap;
  word-break: break-word;
}
.event-log__item.lvl-warning .event-log__msg {
  color: #b45309;
}
.event-log__item.lvl-error .event-log__msg {
  color: #dc2626;
}
</style>
