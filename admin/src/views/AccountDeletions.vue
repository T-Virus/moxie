<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errorMessage, isMissingEndpoint } from '../api'
import { can } from '../roles'
import { getRole } from '../session'
import { pushToast } from '../toast'
import type { AccountDeletionRequestView } from '../types'
import { formatTime } from '../ui'
import { confirm } from '../dialog'
import Icon from '../components/Icon.vue'
import NotReadyBanner from '../components/NotReadyBanner.vue'
import PageHeader from '../components/PageHeader.vue'
import Pager from '../components/Pager.vue'
import RowActions, { type RowAction } from '../components/RowActions.vue'
import StateBlock from '../components/StateBlock.vue'
import StatusBadge from '../components/StatusBadge.vue'
import UiSelect from '../components/UiSelect.vue'

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
  if (!await confirm({ title: '撤销注销申请', message: `确认撤销 #${row.id} 的注销申请？账号将恢复登录。`, confirmText: '确认撤销' })) return
  try {
    await api.cancelAccountDeletion(row.id)
    pushToast('已撤销注销申请', 'info')
    await load()
  } catch (e) {
    pushToast(errorMessage(e), 'error')
  }
}

async function purge(row: AccountDeletionRequestView): Promise<void> {
  if (!await confirm({ title: '立即清除账号', message: `确认立即清除账号 #${row.account_id}？该操作不可恢复，账号全部数据将被永久删除。`, danger: true, confirmText: '立即清除' })) return
  try {
    const result = await api.purgeAccountDeletion(row.id)
    if (result.deleted) pushToast('账号数据已清除', 'info')
    await load()
  } catch (e) {
    pushToast(errorMessage(e), 'error')
  }
}

function setPage(next: number): void {
  const target = Math.min(pageCount.value, Math.max(1, next))
  if (target !== page.value) {
    page.value = target
    void load()
  }
}

onMounted(() => void load())

function deletionActions(row: AccountDeletionRequestView): RowAction[] {
  if (row.status !== 'pending' || !canWrite.value) return []
  return [
    { label: '撤销', run: () => cancel(row) },
    { label: '立即清除', tone: 'danger', run: () => purge(row) },
  ]
}
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
      <UiSelect
        v-model="status"
        size="sm"
        variant="toolbar"
        placeholder="全部"
        :options="[
          { value: 'pending', label: '待处理' },
          { value: 'cancelled', label: '已撤销' },
          { value: 'purged', label: '已清除' },
        ]"
        @change="page = 1; load()"
      />
    </div>

    <div v-if="!items.length" class="state-wrap">
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
            <td><StatusBadge :value="row.status" dot /></td>
            <td class="muted"><div class="truncate" :title="row.reason || ''">{{ row.reason || '—' }}</div></td>
            <td class="cell-time">{{ formatTime(row.requested_at) }}</td>
            <td class="cell-time">{{ formatTime(row.purge_at) }}</td>
            <td class="cell-time">{{ formatTime(row.cancelled_at) }}</td>
            <td>
              <RowActions v-if="deletionActions(row).length" :actions="deletionActions(row)" />
              <span v-else class="muted">—</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <Pager :page="page" :page-size="pageSize" :total="total" :loading="loading" @update:page="setPage" />
  </div>
</template>
