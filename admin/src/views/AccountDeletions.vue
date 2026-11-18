<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errorMessage, isMissingEndpoint } from '../api'
import { can } from '../roles'
import { getRole } from '../session'
import { pushToast } from '../toast'
import type { AccountDeletionRequestView } from '../types'
import { formatTime } from '../ui'
import Icon from '../components/Icon.vue'
import NotReadyBanner from '../components/NotReadyBanner.vue'
import PageHeader from '../components/PageHeader.vue'
import StateBlock from '../components/StateBlock.vue'
import StatusBadge from '../components/StatusBadge.vue'

const role = getRole()
const canRead = computed(() => can(role, 'users:read'))
const canWrite = computed(() => can(role, 'users:write'))

const status = ref('pending')
const page = ref(1)
const pageSize = 50
const items = ref<AccountDeletionRequestView[]>([])
const total = ref(0)
const loading = ref(false)
const error = ref('')
const notReady = ref(false)

const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

async function load(): Promise<void> {
  if (!canRead.value) return
  loading.value = true
  error.value = ''
  notReady.value = false
  try {
    const data = await api.accountDeletions(status.value, page.value, pageSize)
    items.value = data.items
    total.value = data.total
  } catch (e) {
    items.value = []
    notReady.value = isMissingEndpoint(e)
    error.value = errorMessage(e)
    pushToast(error.value, 'error')
  } finally {
    loading.value = false
  }
}

async function cancel(row: AccountDeletionRequestView): Promise<void> {
  if (!window.confirm(`确认撤销 #${row.id} 的注销申请？账号将恢复登录。`)) return
  try {
    await api.cancelAccountDeletion(row.id)
    pushToast('已撤销注销申请', 'info')
    await load()
  } catch (e) {
    pushToast(errorMessage(e), 'error')
  }
}

async function purge(row: AccountDeletionRequestView): Promise<void> {
  if (!window.confirm(`确认立即清除账号 #${row.account_id}？数据不可恢复。`)) return
  try {
    const result = await api.purgeAccountDeletion(row.id)
    if (result.deleted) pushToast('账号数据已清除', 'info')
    await load()
  } catch (e) {
    pushToast(errorMessage(e), 'error')
  }
}

function changePage(delta: number): void {
  const next = Math.min(pageCount.value, Math.max(1, page.value + delta))
  if (next !== page.value) {
    page.value = next
    void load()
  }
}

onMounted(() => void load())
</script>

<template>
  <PageHeader title="注销申请" desc="查看用户数据删除申请，按宽限期处理或由管理员立即清除。">
    <button class="btn ghost sm" :disabled="loading" @click="load">
      <Icon name="refresh" :size="14" />{{ loading ? '加载中…' : '刷新' }}
    </button>
  </PageHeader>

  <NotReadyBanner v-if="notReady" />
  <div v-if="error" class="notice error">{{ error }}</div>
  <div v-if="!canRead" class="notice warn">当前角色无权查看注销申请。</div>

  <div v-else class="card">
    <div class="card-head">
      <div class="card-title">申请列表<span class="sub">共 {{ total }} 条</span></div>
      <div class="spacer"></div>
      <select v-model="status" class="input" style="width: 140px" @change="page = 1; load()">
        <option value="pending">待处理</option>
        <option value="cancelled">已撤销</option>
        <option value="purged">已清除</option>
        <option value="">全部</option>
      </select>
    </div>

    <div v-if="!items.length" class="card">
      <StateBlock kind="empty" title="暂无申请" message="当前筛选条件下没有注销申请。" />
    </div>
    <div v-else class="table-wrap">
      <table class="data-table">
        <thead>
          <tr><th>申请 ID</th><th>账号 ID</th><th>状态</th><th>原因</th><th>申请时间</th><th>计划清除</th><th>撤销时间</th><th style="width: 160px">操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in items" :key="row.id">
            <td class="mono">#{{ row.id }}</td>
            <td class="mono">#{{ row.account_id }}</td>
            <td><StatusBadge :status="row.status" /></td>
            <td class="muted">{{ row.reason || '—' }}</td>
            <td>{{ formatTime(row.requested_at) }}</td>
            <td>{{ formatTime(row.purge_at) }}</td>
            <td>{{ formatTime(row.cancelled_at) }}</td>
            <td>
              <template v-if="row.status === 'pending' && canWrite">
                <button class="btn ghost sm" @click="cancel(row)">撤销</button>
                <button class="btn danger sm" style="margin-left: 6px" @click="purge(row)">立即清除</button>
              </template>
              <span v-else class="muted">—</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="pager">
      <button class="btn ghost sm" :disabled="page <= 1" @click="changePage(-1)">上一页</button>
      <span class="muted mono">{{ page }} / {{ pageCount }}</span>
      <button class="btn ghost sm" :disabled="page >= pageCount" @click="changePage(1)">下一页</button>
    </div>
  </div>
</template>
