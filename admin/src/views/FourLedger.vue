<script setup lang="ts">
import { computed, ref } from 'vue'
import { api, errorMessage, isMissingEndpoint } from '../api'
import { pushToast } from '../toast'
import type { FourLedgerReconcileReport } from '../types'
import { formatMoney, formatNumber, formatTime } from '../ui'
import Icon from '../components/Icon.vue'
import NotReadyBanner from '../components/NotReadyBanner.vue'
import PageHeader from '../components/PageHeader.vue'
import StateBlock from '../components/StateBlock.vue'
import UiDate from '../components/UiDate.vue'

const orderNo = ref('')
const externalOrderNo = ref('')
const accountId = ref('')
const startAt = ref('')
const endAt = ref('')
const report = ref<FourLedgerReconcileReport | null>(null)
const loading = ref(false)
const error = ref('')
const notReady = ref(false)
const notFound = ref(false)

const anomalyCodes = computed(() => Object.keys(report.value?.summary.by_code || {}))

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  notReady.value = false
  notFound.value = false
  try {
    const query: Record<string, unknown> = { limit: 100 }
    if (orderNo.value.trim()) query.order_no = orderNo.value.trim()
    if (externalOrderNo.value.trim()) query.external_order_no = externalOrderNo.value.trim()
    if (accountId.value.trim()) query.account_id = Number(accountId.value.trim())
    if (startAt.value) query.start_at = startAt.value
    if (endAt.value) query.end_at = endAt.value
    report.value = await api.fourLedgerReconcile(query)
  } catch (e) {
    report.value = null
    notReady.value = isMissingEndpoint(e)
    notFound.value = false
    error.value = errorMessage(e)
    pushToast(error.value, 'error')
  } finally {
    loading.value = false
  }
}

function anomalyText(codes: string[]): string {
  return codes.length ? codes.join('、') : '—'
}

function reset() {
  orderNo.value = ''
  externalOrderNo.value = ''
  accountId.value = ''
  startAt.value = ''
  endAt.value = ''
  report.value = null
  error.value = ''
  notReady.value = false
  notFound.value = false
}
</script>

<template>
  <PageHeader title="四账对账" desc="以订单为枢纽核对支付、额度、发票与退款账本，定位跨账不一致。" />

  <NotReadyBanner v-if="notReady" />
  <div v-if="error" class="notice error">{{ error }}</div>

  <div class="card">
    <div class="card-head">
      <div class="card-title">查询条件<span class="sub">留空则统计最近 100 笔订单</span></div>
      <div class="spacer"></div>
      <button class="btn ghost sm" :disabled="loading" @click="reset">重置</button>
      <button class="btn sm" :disabled="loading" @click="load">
        <Icon name="refresh" :size="14" />{{ loading ? '对账中…' : '开始对账' }}
      </button>
    </div>
    <div class="form-grid cols-3">
      <div class="field">
        <label>内部订单号</label>
        <input v-model="orderNo" class="input" placeholder="按订单 ID 精确匹配" @keyup.enter="load" />
      </div>
      <div class="field">
        <label>渠道订单号</label>
        <input v-model="externalOrderNo" class="input" placeholder="渠道交易号 / 外部单号" @keyup.enter="load" />
      </div>
      <div class="field">
        <label>账号 ID</label>
        <input v-model="accountId" class="input" inputmode="numeric" placeholder="可选" @keyup.enter="load" />
      </div>
      <div class="field">
        <label>开始时间</label>
        <UiDate v-model="startAt" mode="datetime" placeholder="选择开始时间" />
      </div>
      <div class="field">
        <label>结束时间</label>
        <UiDate v-model="endAt" mode="datetime" placeholder="选择结束时间" />
      </div>
    </div>
  </div>

  <div v-if="!report" class="card">
    <StateBlock kind="empty" title="尚未对账" message="设置条件后点击「开始对账」。" />
  </div>

  <template v-else>
    <div class="card">
      <div class="card-head">
        <div class="card-title">对账概览<span class="sub">生成于 {{ formatTime(report.window.end_at) }}</span></div>
        <div class="spacer"></div>
        <span class="badge" :class="report.summary.anomaly_total > 0 ? 'warn' : 'ok'">
          {{ report.summary.anomaly_total > 0 ? `发现 ${report.summary.anomaly_total} 处异常` : '四账一致' }}
        </span>
      </div>
      <div class="stat-grid ledger-summary">
        <div class="stat-card">
          <div class="stat-label">查询订单</div>
          <div class="stat-value">{{ formatNumber(report.summary.orders) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">明细条数</div>
          <div class="stat-value">{{ formatNumber(report.groups.length) }}</div>
        </div>
        <div class="stat-card" :class="report.summary.anomaly_total > 0 ? 'orange' : 'teal'">
          <div class="stat-label">异常总数</div>
          <div class="stat-value">{{ formatNumber(report.summary.anomaly_total) }}</div>
        </div>
      </div>
      <div v-if="anomalyCodes.length" class="ledger-codes">
        <span v-for="code in anomalyCodes" :key="code" class="badge warn">{{ code }} × {{ report.summary.by_code[code] }}</span>
      </div>
    </div>

    <div class="card">
      <div class="card-head"><div class="card-title">订单四账明细</div><div class="spacer"></div><span class="badge muted">{{ report.groups.length }} 条</span></div>
      <div class="table-wrap">
        <table class="data-table">
          <thead>
            <tr><th>订单</th><th>账号</th><th>类型</th><th>金额</th><th>支付</th><th>额度</th><th>发票</th><th>退款</th><th>异常</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in report.groups" :key="row.order_id">
              <td class="mono">#{{ row.order_no }}<span class="muted"> · {{ row.provider }}</span></td>
              <td class="mono">#{{ row.account_id }}</td>
              <td>{{ row.kind }}</td>
              <td class="mono">{{ formatMoney(row.amount_cents) }}</td>
              <td>{{ String(row.payment.status || '—') }}<span class="muted mono"> · {{ row.paid_at ? formatTime(row.paid_at) : '—' }}</span></td>
              <td>{{ row.quota.grant_id ? `发放 #${row.quota.grant_id}` : '—' }}<span class="muted"> · {{ row.quota.metric || '—' }}</span></td>
              <td>{{ row.invoice.id ? String(row.invoice.status || '—') : '—' }}<span class="muted mono"> · {{ row.invoice.amount_cents ? formatMoney(Number(row.invoice.amount_cents)) : '—' }}</span></td>
              <td>{{ row.refund.count ? formatMoney(Number(row.refund.amount_cents || 0)) : '—' }}</td>
              <td :class="row.anomalies.length ? 'warn-text' : ''">
                <div class="truncate" :title="anomalyText(row.anomalies)">{{ anomalyText(row.anomalies) }}</div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="report.anomalies.length" class="card">
      <div class="card-head"><div class="card-title">异常明细</div></div>
      <div class="table-wrap">
        <table class="data-table">
          <thead><tr><th>订单</th><th>代码</th><th>级别</th><th>说明</th></tr></thead>
          <tbody>
            <tr v-for="(row, index) in report.anomalies" :key="`${row.order_id}-${row.code}-${index}`">
              <td class="mono">#{{ row.order_no }}</td>
              <td class="mono">{{ row.code }}</td>
              <td>{{ row.severity }}</td>
              <td><div class="truncate" :title="row.detail">{{ row.detail }}</div></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </template>
</template>

<style scoped>
.ledger-summary { grid-template-columns: repeat(3, minmax(0, 1fr)); }
@media (max-width: 900px) {
  .ledger-summary { grid-template-columns: 1fr; }
}
.ledger-codes { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.warn-text {
  color: var(--orange, #d97706);
}
</style>
