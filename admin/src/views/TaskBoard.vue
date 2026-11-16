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

let timer: number | null = null
onMounted(() => {
  void load()
  timer = window.setInterval(() => {
    if (autoRefresh.value) void load()
  }, 30_000)
})
onUnmounted(() => {
  if (timer !== null) window.clearInterval(timer)
})
</script>

<template>
  <PageHeader title="任务看板" desc="聚合拆解/改编任务与创作页触发的写作运行，查看队列深度、运行中与失败任务并重试。页面每 30 秒自动刷新。">
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
      <div class="stat-desc">当前持有租约的任务</div>
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
          <thead><tr><th>任务 ID</th><th>账号</th><th>来源 / 类型</th><th>作品</th><th>状态</th><th class="num">进度</th><th>开始时间</th><th>创建时间</th><th>操作</th></tr></thead>
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
              <td class="muted">{{ formatTime(task.created_at) }}</td>
              <td><button class="btn ghost sm" @click="openDetail(task)">详情</button></td>
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
