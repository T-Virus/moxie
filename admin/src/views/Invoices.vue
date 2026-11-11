<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errorMessage, normalizeList } from '../api'
import { can } from '../roles'
import { getRole } from '../session'
import { pushToast } from '../toast'
import type { InvoiceRow } from '../types'
import { accountLabel, formatMoney, formatNumber, formatTime } from '../ui'
import Icon from '../components/Icon.vue'
import Modal from '../components/Modal.vue'
import PageHeader from '../components/PageHeader.vue'
import Pager from '../components/Pager.vue'
import StateBlock from '../components/StateBlock.vue'
import StatusBadge from '../components/StatusBadge.vue'

const role = getRole()
const canWrite = computed(() => can(role, 'invoices:write'))

const status = ref('')
const page = ref(1)
const pageSize = 20
const allRows = ref<InvoiceRow[]>([])
const loading = ref(false)
const error = ref('')

const filteredRows = computed(() => {
  if (!status.value) return allRows.value
  if (status.value === 'voided') {
    return allRows.value.filter(row => row.status === 'voided' || row.status === 'rejected')
  }
  return allRows.value.filter(row => row.status === status.value)
})

const visibleRows = computed(() => {
  const start = (page.value - 1) * pageSize
  return filteredRows.value.slice(start, start + pageSize)
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await api.invoices({})
    allRows.value = normalizeList<InvoiceRow>(data).items
  } catch (e) {
    allRows.value = []
    error.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

function changeStatus() {
  page.value = 1
}

function setPage(next: number) {
  page.value = next
}

onMounted(load)

const actionOpen = ref(false)
const actionMode = ref<'issue' | 'void'>('issue')
const target = ref<InvoiceRow | null>(null)
const note = ref('')
const submitting = ref(false)
const actionError = ref('')

function openAction(row: InvoiceRow, mode: 'issue' | 'void') {
  target.value = row
  actionMode.value = mode
  note.value = ''
  actionError.value = ''
  actionOpen.value = true
}

async function submitAction() {
  if (!target.value) return
  if (actionMode.value === 'void' && note.value.trim().length < 2) {
    actionError.value = '作废发票必须填写原因（至少 2 个字）'
    return
  }
  submitting.value = true
  actionError.value = ''
  try {
    await api.updateInvoice(target.value.id, actionMode.value === 'issue' ? 'issued' : 'voided', note.value.trim())
    pushToast(actionMode.value === 'issue' ? '发票已开具' : '发票已作废')
    actionOpen.value = false
    await load()
  } catch (e) {
    actionError.value = errorMessage(e)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <PageHeader title="发票" desc="查看开票申请记录，执行开具或作废。操作会记录处理备注，作废必须填写原因。">
    <span v-if="!canWrite" class="badge muted">support 只读</span>
    <button class="btn ghost sm" :disabled="loading" @click="load">
      <Icon name="refresh" :size="14" />刷新
    </button>
  </PageHeader>

  <div v-if="!canWrite" class="notice info">
    <div class="notice-body">
      <div class="notice-title">只读模式</div>
      <div>当前角色可查看开票记录，但开具与作废需要管理员（admin）权限。</div>
    </div>
  </div>

  <div class="card">
    <div class="toolbar">
      <select v-model="status" class="select tb-select" @change="changeStatus">
        <option value="">全部状态</option>
        <option value="requested">待开票</option>
        <option value="issued">已开具</option>
        <option value="voided">已作废</option>
      </select>
      <div class="spacer"></div>
      <span class="muted" style="font-size: 12px">共 {{ formatNumber(filteredRows.length) }} 条开票记录</span>
    </div>

    <div v-if="loading && !allRows.length">
      <StateBlock kind="loading" title="正在加载开票记录…" />
    </div>
    <div v-else-if="error">
      <StateBlock kind="error" title="开票记录加载失败" :message="error" retry-label="重试" @retry="load" />
    </div>
    <div v-else-if="!filteredRows.length">
      <StateBlock kind="empty" title="暂无开票记录" message="当前筛选条件下没有发票申请。" />
    </div>
    <template v-else>
      <div class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th style="width: 72px">ID</th>
              <th style="width: 88px">订单</th>
              <th>抬头</th>
              <th>税号 / 邮箱</th>
              <th class="num" style="width: 100px">金额</th>
              <th style="width: 110px">状态</th>
              <th style="width: 128px">申请时间</th>
              <th style="width: 128px">开具时间</th>
              <th style="width: 76px">处理人</th>
              <th style="width: 140px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in visibleRows" :key="row.id">
              <td class="mono">#{{ row.id }}</td>
              <td class="mono">#{{ row.order_id }}</td>
              <td>
                <div>{{ row.title }}</div>
                <div v-if="row.note" class="muted truncate" style="font-size: 11.5px" :title="row.note">{{ row.note }}</div>
              </td>
              <td>
                <div class="mono" style="font-size: 11.5px">{{ row.tax_no || '—' }}</div>
                <div class="muted" style="font-size: 11.5px">{{ row.email || accountLabel(row) }}</div>
              </td>
              <td class="num">{{ formatMoney(row.amount_cents) }}</td>
              <td><StatusBadge :value="row.status" dot /></td>
              <td class="muted">{{ formatTime(row.created_at) }}</td>
              <td class="muted">{{ formatTime(row.issued_at) }}</td>
              <td class="mono muted">{{ row.admin_id ? `#${row.admin_id}` : '—' }}</td>
              <td>
                <div class="actions">
                  <button v-if="canWrite && row.status === 'requested'" class="btn ghost sm" @click="openAction(row, 'issue')">开具</button>
                  <button v-if="canWrite && row.status === 'issued'" class="btn danger-ghost sm" @click="openAction(row, 'void')">作废</button>
                  <span v-if="!canWrite || (row.status !== 'requested' && row.status !== 'issued')" class="muted" style="font-size: 12px">—</span>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <Pager :page="page" :page-size="pageSize" :total="filteredRows.length" :loading="loading" @update:page="setPage" />
    </template>
  </div>

  <Modal v-if="actionOpen" :title="actionMode === 'issue' ? '开具发票' : '作废发票'"
    :subtitle="target ? `发票 #${target.id} · 订单 #${target.order_id} · ${target.title}` : ''" size="narrow"
    @close="actionOpen = false">
    <div class="notice" :class="actionMode === 'issue' ? 'info' : 'warn'" style="margin-bottom: 14px">
      {{ actionMode === 'issue'
        ? '开具后将把发票状态置为 issued，并通过通知渠道发送给用户（以服务端实现为准）。'
        : '作废将把发票状态置为 voided，不会自动重新开票。' }}
    </div>
    <div class="field">
      <label>{{ actionMode === 'issue' ? '处理备注' : '作废原因' }}<span v-if="actionMode === 'void'" class="required">*</span></label>
      <textarea v-model="note" class="textarea"
        :placeholder="actionMode === 'issue' ? '可填写发票号或开票备注' : '请说明作废原因，将写入审计日志'"></textarea>
    </div>
    <div v-if="actionError" class="notice error" style="margin: 12px 0 0">{{ actionError }}</div>
    <template #footer>
      <button class="btn ghost sm" :disabled="submitting" @click="actionOpen = false">取消</button>
      <button class="btn" :class="actionMode === 'void' ? 'danger' : ''" :disabled="submitting" @click="submitAction">
        {{ submitting ? '提交中…' : (actionMode === 'issue' ? '确认开具' : '确认作废') }}
      </button>
    </template>
  </Modal>
</template>
