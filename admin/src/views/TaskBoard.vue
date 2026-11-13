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

const role = getRole()
const canRetry = computed(() => can(role, 'tasks:write'))

const dashboard = ref<TaskDashboard | null>(null)
const loading = ref(false)
const error = ref('')
const autoRefresh = ref(true)
const retryingId = ref('')

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
          <thead><tr><th>任务 ID</th><th>账号</th><th>来源 / 类型</th><th>作品</th><th>状态</th><th class="num">进度</th><th>开始时间</th><th>创建时间</th></tr></thead>
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
</template>
