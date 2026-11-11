<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errorMessage, isMissingEndpoint } from '../api'
import { can } from '../roles'
import { getRole } from '../session'
import { pushToast } from '../toast'
import type { ReconcileItem, ReconcileReport } from '../types'
import { formatMoney, formatNumber, formatTime, todayInputValue } from '../ui'
import Icon from '../components/Icon.vue'
import NotReadyBanner from '../components/NotReadyBanner.vue'
import PageHeader from '../components/PageHeader.vue'
import StateBlock from '../components/StateBlock.vue'
import StatusBadge from '../components/StatusBadge.vue'

const canRun = computed(() => can(getRole(), 'reconcile:write'))

const provider = ref('wechat')
const bizDate = ref(todayInputValue(-1))
const report = ref<ReconcileReport | null>(null)
const loading = ref(false)
const running = ref(false)
const exporting = ref(false)
const error = ref('')
const notReady = ref(false)
const notFound = ref(false)

const TYPE_LABELS: Record<string, string> = {
  matched: '已匹配',
  local_only: '本地单边',
  channel_only: '渠道单边',
  missing_local: '渠道有 / 本地无',
  missing_channel: '本地有 / 渠道无',
  amount_mismatch: '金额不一致',
  duplicate: '重复记录',
  status_mismatch: '状态不一致',
  refund_mismatch: '退款差异',
}

const SUMMARY_LABELS: Record<string, string> = {
  local_total: '本地总额',
  channel_total: '渠道总额',
  total_local: '本地总额',
  total_channel: '渠道总额',
  local_amount_cents: '本地总额',
  channel_amount_cents: '渠道总额',
  diff_count: '差异数量',
  matched: '已匹配',
  local_only: '本地单边',
  channel_only: '渠道单边',
  amount_mismatch: '金额不一致',
  duplicate: '重复记录',
  total: '记录总数',
  orders: '订单数',
}

function typeLabel(type?: string): string {
  if (!type) return '未分类'
  return TYPE_LABELS[type] || type
}

const items = computed<ReconcileItem[]>(() => report.value?.items || [])

const typeGroups = computed(() => {
  const map = new Map<string, number>()
  for (const item of items.value) {
    const key = item.type || 'unknown'
    map.set(key, (map.get(key) || 0) + 1)
  }
  return Array.from(map.entries()).map(([type, count]) => ({ type, count, label: typeLabel(type) }))
})

const filterType = ref('all')
const filteredItems = computed(() => {
  if (filterType.value === 'all') return items.value
  return items.value.filter(item => (item.type || 'unknown') === filterType.value)
})

const summaryEntries = computed(() => {
  const summary = report.value?.summary
  if (!summary || typeof summary !== 'object') return []
  return Object.entries(summary).map(([key, value]) => {
    const label = SUMMARY_LABELS[key] || key
    let display: string
    if (typeof value === 'number' && key.includes('cents')) display = formatMoney(value)
    else if (typeof value === 'number') display = formatNumber(value)
    else if (value === null || value === undefined) display = '—'
    else if (typeof value === 'object') display = JSON.stringify(value)
    else display = String(value)
    return { key, label, display, mono: key.includes('cents') || /id$/.test(key) }
  })
})

function reset() {
  report.value = null
  error.value = ''
  notReady.value = false
  notFound.value = false
  filterType.value = 'all'
}

async function query() {
  if (!bizDate.value) {
    error.value = '请选择对账日期'
    return
  }
  loading.value = true
  reset()
  try {
    report.value = await api.reconcile(provider.value, bizDate.value)
  } catch (e) {
    if (isMissingEndpoint(e)) notReady.value = true
    else if ((e as any)?.status === 404 || (e as any)?.code === 'reconcile_not_found') notFound.value = true
    else error.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

async function run() {
  if (!canRun.value) {
    pushToast('仅管理员可以生成对账报告', 'error')
    return
  }
  if (!bizDate.value) {
    error.value = '请选择对账日期'
    return
  }
  running.value = true
  error.value = ''
  notReady.value = false
  try {
    const result = await api.runReconcile(provider.value, bizDate.value)
    if (result && (result.items || result.summary)) report.value = result
    else await query()
    pushToast('对账任务已完成')
  } catch (e) {
    if (isMissingEndpoint(e)) notReady.value = true
    else error.value = errorMessage(e)
  } finally {
    running.value = false
  }
}

async function exportCsv() {
  exporting.value = true
  try {
    await api.exportReconcile(provider.value, bizDate.value)
    pushToast('对账 CSV 已开始下载')
  } catch (e) {
    if (isMissingEndpoint(e)) notReady.value = true
    else pushToast(errorMessage(e), 'error')
  } finally {
    exporting.value = false
  }
}

onMounted(query)
</script>

<template>
  <PageHeader title="对账" desc="按渠道与日期查询支付对账报告，查看差异分类并导出 CSV。导出使用带 Bearer Token 的请求下载，Token 不会出现在 URL 中。">
    <button class="btn ghost sm" :disabled="exporting || !report" @click="exportCsv">
      <Icon name="download" :size="14" />{{ exporting ? '导出中…' : '导出 CSV' }}
    </button>
  </PageHeader>

  <div v-if="!canRun" class="notice info">
    <div class="notice-body">
      <div class="notice-title">只读模式</div>
      <div>当前角色可查询对账报告并导出 CSV；生成对账需要管理员（admin）权限。</div>
    </div>
  </div>

  <div class="card">
    <form class="toolbar" style="padding-bottom: 0; border-bottom: none; margin-bottom: 0" @submit.prevent="query">
      <div class="tb-group">
        <select v-model="provider" class="select tb-select">
          <option value="wechat">微信支付</option>
          <option value="alipay">支付宝</option>
          <option value="stripe">Stripe</option>
        </select>
      </div>
      <div class="tb-group">
        <input v-model="bizDate" class="input" type="date" style="width: 170px" />
      </div>
      <button class="btn sm" type="submit" :disabled="loading">{{ loading ? '查询中…' : '查询报告' }}</button>
      <button v-if="canRun" class="btn ghost sm" type="button" :disabled="running" @click="run">
        <Icon name="play" :size="13" />{{ running ? '生成中…' : '生成对账' }}
      </button>
    </form>
  </div>

  <div v-if="loading" class="card">
    <StateBlock kind="loading" title="正在查询对账报告…" />
  </div>
  <div v-else-if="notReady" class="card">
    <NotReadyBanner endpoint="GET /v1/admin/payments/reconcile" message="对账接口当前不可用，请确认服务端已注册支付对账路由。" />
    <StateBlock kind="notready" title="对账接口未就绪" message="页面已按 provider + biz_date 约定封装，服务端就绪后可直接使用。"
      endpoint="GET /v1/admin/payments/reconcile?provider=&biz_date=" retry-label="重新查询" @retry="query" />
  </div>
  <div v-else-if="error" class="card">
    <StateBlock kind="error" title="对账查询失败" :message="error" retry-label="重试" @retry="query" />
  </div>
  <div v-else-if="notFound" class="card">
    <StateBlock kind="empty" title="该日期暂无对账报告"
      :message="canRun ? '可点击「生成对账」拉取渠道账单并与本地订单比对。' : '当前角色为只读，请联系管理员生成对账报告后刷新查询。'"
      retry-label="重新查询" @retry="query">
      <button v-if="canRun" class="btn sm" :disabled="running" @click="run">{{ running ? '生成中…' : '生成对账' }}</button>
    </StateBlock>
  </div>
  <div v-else-if="!report" class="card">
    <StateBlock kind="empty" title="选择渠道与日期后查询" message="默认查询昨天的微信支付对账报告。" retry-label="查询昨天" @retry="query" />
  </div>
  <template v-else>
    <div class="card">
      <div class="card-head">
        <div class="card-title">
          {{ provider }} · {{ report.biz_date }}
          <span class="sub">对账报告</span>
        </div>
        <div class="spacer"></div>
        <StatusBadge v-if="report.status" :value="report.status" />
        <span v-if="report.channel_source" class="badge muted">来源 {{ report.channel_source }}</span>
        <span v-if="report.id" class="badge muted">报告 #{{ report.id }}</span>
        <span class="muted mono" style="font-size: 11.5px">查询于 {{ formatTime(new Date().toISOString()) }}</span>
      </div>

      <div v-if="summaryEntries.length" class="report-summary">
        <div v-for="entry in summaryEntries" :key="entry.key" class="report-item">
          <div class="k">{{ entry.label }}</div>
          <div class="v" :class="{ mono: entry.mono }">{{ entry.display }}</div>
        </div>
      </div>
      <div v-else class="notice info" style="margin-bottom: 14px">该报告未返回 summary，以下直接展示差异明细。</div>

      <div class="card-head">
        <div class="card-title">差异分类</div>
        <div class="spacer"></div>
        <div class="tabs">
          <button :class="{ active: filterType === 'all' }" @click="filterType = 'all'">
            全部<span class="count">{{ items.length }}</span>
          </button>
          <button v-for="group in typeGroups" :key="group.type" :class="{ active: filterType === group.type }"
            @click="filterType = group.type">
            {{ group.label }}<span class="count">{{ group.count }}</span>
          </button>
        </div>
      </div>

      <div v-if="!filteredItems.length" class="state" style="padding: 22px">
        <div class="state-title">{{ items.length ? '该分类下无记录' : '无差异记录' }}</div>
        <div class="state-msg">{{ items.length ? '切换到「全部」查看其他差异。' : '本地订单与渠道账单一致。' }}</div>
      </div>
      <div v-else class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th style="width: 120px">差异类型</th>
              <th>外部订单号</th>
              <th style="width: 90px">本地订单</th>
              <th class="num" style="width: 110px">本地金额</th>
              <th class="num" style="width: 110px">渠道金额</th>
              <th class="num" style="width: 70px">数量</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(item, index) in filteredItems" :key="index">
              <td><span class="badge" :class="item.type === 'matched' ? 'ok' : 'warn'">{{ typeLabel(item.type) }}</span></td>
              <td class="mono truncate" :title="item.external_order_no || ''">{{ item.external_order_no || '—' }}</td>
              <td class="mono">{{ item.order_id ? `#${item.order_id}` : '—' }}</td>
              <td class="num">{{ item.local_amount_cents !== undefined ? formatMoney(item.local_amount_cents) : (item.amount_cents !== undefined ? formatMoney(item.amount_cents) : '—') }}</td>
              <td class="num">{{ item.channel_amount_cents !== undefined ? formatMoney(item.channel_amount_cents) : '—' }}</td>
              <td class="num">{{ item.count ?? '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </template>
</template>
