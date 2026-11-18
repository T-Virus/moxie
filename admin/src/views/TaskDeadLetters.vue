<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api, errorMessage } from '../api'
import { can } from '../roles'
import { getRole } from '../session'
import { pushToast } from '../toast'
import type { TaskRow } from '../types'
import { formatNumber, formatTime } from '../ui'
import Icon from '../components/Icon.vue'
import PageHeader from '../components/PageHeader.vue'
import StateBlock from '../components/StateBlock.vue'

const canWrite = computed(() => can(getRole(), 'tasks:write'))
const keyword = ref('')
const loading = ref(false)
const items = ref<TaskRow[]>([])
const total = ref(0)
const selected = reactive<Set<string>>(new Set())
const error = ref('')

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const data = await api.deadLetters({ q: keyword.value.trim() || undefined, page_size: 100 })
    items.value = data.items
    total.value = data.total
    selected.clear()
  } catch (e) {
    items.value = []
    error.value = errorMessage(e)
    pushToast(error.value, 'error')
  } finally {
    loading.value = false
  }
}

function toggle(id: string): void {
  if (selected.has(id)) selected.delete(id)
  else selected.add(id)
}

async function replay(id: string): Promise<void> {
  if (!window.confirm(`确认重放任务 ${id}？将清空失败次数并重新入队。`)) return
  try {
    await api.replayDeadLetter(id, 'admin console replay')
    pushToast('已重放任务', 'info')
    await load()
  } catch (e) {
    pushToast(errorMessage(e), 'error')
  }
}

async function replayBatch(): Promise<void> {
  const ids = [...selected]
  if (!ids.length) {
    pushToast('请先选择任务', 'warn')
    return
  }
  if (!window.confirm(`确认批量重放 ${ids.length} 个任务？`)) return
  try {
    const result = await api.replayDeadLettersBatch(ids, 'admin console batch replay')
    pushToast(`重放完成：成功 ${result.succeeded}，失败 ${result.failed}`, result.failed ? 'warn' : 'info')
    await load()
  } catch (e) {
    pushToast(errorMessage(e), 'error')
  }
}

onMounted(() => void load())
</script>

<template>
  <PageHeader title="死信与重放" desc="重试耗尽的任务进入死信列表，可由管理员确认后重新入队。">
    <button class="btn ghost sm" :disabled="loading" @click="load">
      <Icon name="refresh" :size="14" />{{ loading ? '加载中…' : '刷新' }}
    </button>
  </PageHeader>

  <div v-if="error" class="notice error">{{ error }}</div>

  <div class="card">
    <div class="card-head">
      <div class="card-title">死信任务<span class="sub">共 {{ formatNumber(total) }} 条</span></div>
      <div class="spacer"></div>
      <input v-model="keyword" class="input" placeholder="任务 ID / 错误码" style="width: 220px" @keyup.enter="load" />
      <button class="btn ghost sm" :disabled="loading" @click="load">查询</button>
      <button class="btn brand sm" :disabled="!canWrite || !selected.size" @click="replayBatch">
        批量重放（{{ selected.size }}）
      </button>
    </div>

    <div v-if="!items.length" class="card">
      <StateBlock kind="empty" title="暂无死信" message="当前没有重试耗尽的任务。" />
    </div>
    <div v-else class="table-wrap">
      <table class="data-table">
        <thead>
          <tr><th style="width: 40px"></th><th>任务 ID</th><th>账号</th><th>类型</th><th>尝试次数</th><th>错误码</th><th>完成时间</th><th style="width: 90px">操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in items" :key="row.id">
            <td><input type="checkbox" :checked="selected.has(row.id)" @change="toggle(row.id)" /></td>
            <td class="mono">{{ row.id }}</td>
            <td class="mono">#{{ row.account_id }}</td>
            <td>{{ row.type }}</td>
            <td class="mono">{{ row.attempts }}</td>
            <td class="mono">{{ row.error_code || '—' }}</td>
            <td>{{ formatTime(row.finished_at) }}</td>
            <td>
              <button v-if="canWrite" class="btn ghost sm" @click="replay(row.id)">重放</button>
              <span v-else class="muted">—</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
