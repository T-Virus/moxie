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
</script>

<template>
  <PageHeader title="四账对账" desc="以订单为枢纽核对支付、额度、发票与退款账本，定位跨账不一致。">
    <button class="btn brand sm" :disabled="loading" @click="load">
      <Icon name="refresh" :size="14" />{{ loading ? '对账中…' : '开始对账' }}
    </button>
  </PageHeader>

  <NotReadyBanner v-if="notReady" />
  <div v-if="error" class="notice error">{{ error }}</div>

  <div class="card">
    <div class="card-head"><div class="card-title">查询条件</div></div>
    <div class="form-grid four-ledger-form">
      <label class="field"><span>内部订单号</span><input v-model="orderNo" class="input" placeholder="订单 ID" /></label>
      <label class="field"><span>渠道订单号</span><input v-model="externalOrderNo" class="input" placeholder="外部订单号" /></label>
      <label class="field"><span>账号 ID</span><input v-model="accountId" class="input" inputmode="numeric" placeholder="可选" /></label>
      <label class="field"><span>开始时间</span><input v-model="startAt" class="input" type="datetime-local" /></label>
      <label class="field"><span>结束时间</span><input v-model="endAt" class="input" type="datetime-local" /></label>
    </div>
    <p class="muted">留空则按最近 100 笔订单聚合；多 worker 部署时该视图只反映当前进程统计口径之外的数据库账本。</p>
  </div>

  <div v-if="!report" class="card">
    <StateBlock kind="empty" title="尚未对账" message="设置条件后点击「开始对账」。" />
  </div>

  <template v-else>
    <div class="kv-grid">
      <div class="kv"><span class="k">查询订单</span><span class="v mono">{{ formatNumber(report.summary.orders) }}</span></div>
      <div class="kv"><span class="k">异常总数</span><span class="v mono">{{ formatNumber(report.summary.anomaly_total) }}</span></div>
      <div v-for="code in anomalyCodes" :key="code" class="kv">
        <span class="k">{{ code }}</span><span class="v mono">{{ report.summary.by_code[code] }}</span>
      </div>
      <div class="kv"><span class="k">生成时间</span><span class="v">{{ formatTime(report.window.end_at) }}</span></div>
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
              <td class="mono">#{{ row.order_no }}<div class="muted">{{ row.provider }}</div></td>
              <td class="mono">#{{ row.account_id }}</td>
              <td>{{ row.kind }}</td>
              <td class="mono">{{ formatMoney(row.amount_cents) }}</td>
              <td>{{ String(row.payment.status || '—') }}<div class="muted mono">{{ row.paid_at ? formatTime(row.paid_at) : '—' }}</div></td>
              <td>{{ row.quota.grant_id ? `发放 #${row.quota.grant_id}` : '—' }}<div class="muted">{{ row.quota.metric || '—' }}</div></td>
              <td>{{ row.invoice.id ? String(row.invoice.status || '—') : '—' }}<div class="muted mono">{{ row.invoice.amount_cents ? formatMoney(Number(row.invoice.amount_cents)) : '—' }}</div></td>
              <td>{{ row.refund.count ? formatMoney(Number(row.refund.amount_cents || 0)) : '—' }}</td>
              <td :class="row.anomalies.length ? 'warn-text' : ''">{{ anomalyText(row.anomalies) }}</td>
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
              <td>{{ row.detail }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </template>
</template>

<style scoped>
.four-ledger-form {
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
}
.warn-text {
  color: var(--orange, #d97706);
}
</style>
