<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errorMessage, normalizeList } from '../api'
import { can } from '../roles'
import { getRole } from '../session'
import { pushToast } from '../toast'
import type { OrderRow, RefundRow } from '../types'
import {
  accountLabel, formatMoney, formatNumber, formatTime, prettyJson,
} from '../ui'
import Icon from '../components/Icon.vue'
import Modal from '../components/Modal.vue'
import PageHeader from '../components/PageHeader.vue'
import Pager from '../components/Pager.vue'
import StateBlock from '../components/StateBlock.vue'
import StatusBadge from '../components/StatusBadge.vue'

const role = getRole()
const canRefund = computed(() => can(role, 'refunds:write'))

const q = ref('')
const status = ref('')
const provider = ref('')
const page = ref(1)
const pageSize = 30
const rows = ref<OrderRow[]>([])
const total = ref<number | null>(null)
const loading = ref(false)
const error = ref('')

async function loadOrders() {
  loading.value = true
  error.value = ''
  try {
    const data = await api.orders({ q: q.value.trim(), status: status.value, provider: provider.value, page: page.value, page_size: pageSize })
    const list = normalizeList<OrderRow>(data)
    rows.value = list.items
    total.value = list.total
  } catch (e) {
    rows.value = []
    total.value = null
    error.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  void loadOrders()
}

function setPage(next: number) {
  page.value = next
  void loadOrders()
}

const refundRows = ref<RefundRow[]>([])
const refundLoading = ref(false)
const refundError = ref('')
const refundTab = ref<'pending' | 'all'>('pending')

const PENDING_STATUSES = ['pending', 'requested', 'processing', 'approving', 'created', 'retry_pending']

async function loadRefunds() {
  refundLoading.value = true
  refundError.value = ''
  try {
    const data = await api.refunds()
    const list = normalizeList<RefundRow>(data)
    refundRows.value = list.items
  } catch (e) {
    refundRows.value = []
    refundError.value = errorMessage(e)
  } finally {
    refundLoading.value = false
  }
}

const pendingRefunds = computed(() =>
  refundRows.value.filter(item => PENDING_STATUSES.includes(String(item.status || '').toLowerCase())),
)
const visibleRefunds = computed(() => (refundTab.value === 'pending' ? pendingRefunds.value : refundRows.value))

onMounted(() => {
  void loadOrders()
  void loadRefunds()
})

const orderOpen = ref(false)
const selectedOrder = ref<OrderRow | null>(null)
const orderDetail = ref<{ order: OrderRow; refunds?: RefundRow[] } | null>(null)
const orderLoading = ref(false)
const orderError = ref('')

const orderEvenRecords = computed<RefundRow[]>(() => {
  const fromDetail = orderDetail.value?.refunds
  if (Array.isArray(fromDetail) && fromDetail.length) return fromDetail
  if (!selectedOrder.value) return []
  return refundRows.value.filter(item => item.order_id === selectedOrder.value?.id)
})
const currentOrder = computed<OrderRow | null>(() => orderDetail.value?.order || selectedOrder.value)

async function openOrder(row: OrderRow) {
  selectedOrder.value = row
  orderOpen.value = true
  orderDetail.value = null
  orderError.value = ''
  orderLoading.value = true
  try {
    orderDetail.value = await api.orderDetail(row.id)
  } catch (e) {
    orderError.value = errorMessage(e)
  } finally {
    orderLoading.value = false
  }
}

const decisionOpen = ref(false)
const decisionMode = ref<'approve' | 'reject' | 'direct'>('approve')
const decisionRefund = ref<RefundRow | null>(null)
const decisionOrder = ref<OrderRow | null>(null)
const decisionNote = ref('')
const decisionAmount = ref('')
const decisionError = ref('')
const decisionSubmitting = ref(false)

const decisionTitle = computed(() => {
  if (decisionMode.value === 'approve') return '通过退款申请'
  if (decisionMode.value === 'reject') return '拒绝退款申请'
  return '直接发起退款'
})

function openDecision(mode: 'approve' | 'reject' | 'direct', options: { refund?: RefundRow; order?: OrderRow }) {
  decisionMode.value = mode
  decisionRefund.value = options.refund || null
  decisionOrder.value = options.order || null
  decisionNote.value = ''
  decisionAmount.value = ''
  decisionError.value = ''
  decisionOpen.value = true
}

async function submitDecision() {
  if (decisionMode.value === 'reject' && decisionNote.value.trim().length < 2) {
    decisionError.value = '拒绝退款必须填写备注（至少 2 个字）'
    return
  }
  if (decisionMode.value === 'direct') {
    if (!decisionOrder.value) return
    if (decisionNote.value.trim().length < 2) {
      decisionError.value = '请填写退款原因（至少 2 个字）'
      return
    }
    if (decisionAmount.value) {
      const amount = Number(decisionAmount.value)
      if (!Number.isFinite(amount) || amount <= 0) {
        decisionError.value = '退款金额必须为正数（单位：元）'
        return
      }
    }
  }
  decisionSubmitting.value = true
  decisionError.value = ''
  try {
    if (decisionMode.value === 'approve' && decisionRefund.value) {
      await api.approveRefund(decisionRefund.value.id, decisionNote.value.trim())
      pushToast('退款申请已通过')
    } else if (decisionMode.value === 'reject' && decisionRefund.value) {
      await api.rejectRefund(decisionRefund.value.id, decisionNote.value.trim())
      pushToast('退款申请已拒绝')
    } else if (decisionMode.value === 'direct' && decisionOrder.value) {
      const body: { amount_cents?: number; reason: string } = { reason: decisionNote.value.trim() }
      if (decisionAmount.value) body.amount_cents = Math.round(Number(decisionAmount.value) * 100)
      await api.directRefund(decisionOrder.value.id, body)
      pushToast('退款已发起')
    }
    decisionOpen.value = false
    await Promise.all([loadOrders(), loadRefunds()])
    if (orderOpen.value && selectedOrder.value) await openOrder(selectedOrder.value)
  } catch (e) {
    decisionError.value = errorMessage(e)
  } finally {
    decisionSubmitting.value = false
  }
}
</script>

<template>
  <PageHeader title="订单与退款" desc="查看全量订单与退款状态，审批退款申请或直接发起退款。退款审批与直接退款都需要备注并写入审计日志。">
    <span v-if="!canRefund" class="badge muted">support 只读</span>
    <button class="btn ghost sm" :disabled="loading" @click="loadOrders">
      <Icon name="refresh" :size="14" />刷新订单
    </button>
  </PageHeader>

  <div v-if="!canRefund" class="notice info">
    <div class="notice-body">
      <div class="notice-title">只读模式</div>
      <div>当前角色可查看订单与退款记录，但审批与直接退款需要管理员（admin）权限。</div>
    </div>
  </div>

  <div class="card">
    <div class="card-head">
      <div class="card-title">订单列表<span class="sub">{{ total === null ? '—' : formatNumber(total) }} 条</span></div>
    </div>
    <form class="toolbar" @submit.prevent="search">
      <div class="tb-group tb-search">
        <input v-model="q" class="input" placeholder="搜索订单号 / 外部单号 / 账号" />
      </div>
      <select v-model="status" class="select tb-select" @change="search">
        <option value="">全部状态</option>
        <option value="created">已创建</option>
        <option value="pending">待支付</option>
        <option value="paid">已支付</option>
        <option value="failed">支付失败</option>
        <option value="refunded">已退款</option>
        <option value="partially_refunded">部分退款</option>
        <option value="canceled">已取消</option>
      </select>
      <select v-model="provider" class="select tb-select" @change="search">
        <option value="">全部渠道</option>
        <option value="wechat">微信支付</option>
        <option value="alipay">支付宝</option>
        <option value="stripe">Stripe</option>
        <option value="mock">Mock / 测试</option>
      </select>
      <button class="btn sm" type="submit" :disabled="loading">查询</button>
    </form>

    <div v-if="loading && !rows.length">
      <StateBlock kind="loading" title="正在加载订单…" />
    </div>
    <div v-else-if="error">
      <StateBlock kind="error" title="订单列表加载失败" :message="error" retry-label="重试" @retry="loadOrders" />
    </div>
    <div v-else-if="!rows.length">
      <StateBlock kind="empty" title="暂无订单" message="调整搜索条件或等待新的支付订单。" />
    </div>
    <template v-else>
      <div class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th style="width: 90px">订单 ID</th>
              <th>账号</th>
              <th class="num" style="width: 100px">金额</th>
              <th style="width: 100px">状态</th>
              <th style="width: 92px">渠道</th>
              <th>类型 / 周期</th>
              <th class="num" style="width: 92px">已退</th>
              <th style="width: 128px">创建时间</th>
              <th style="width: 150px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.id">
              <td>
                <div class="mono">#{{ row.id }}</div>
                <div v-if="row.external_order_no" class="muted mono truncate" style="font-size: 11px" :title="row.external_order_no">
                  {{ row.external_order_no }}
                </div>
              </td>
              <td>{{ accountLabel(row) }}</td>
              <td class="num">{{ formatMoney(row.amount_cents, row.currency) }}</td>
              <td><StatusBadge :value="row.status" dot /></td>
              <td class="muted">{{ row.provider }}</td>
              <td class="muted">{{ row.kind || '—' }}<span v-if="row.cycle"> · {{ row.cycle }}</span></td>
              <td class="num">{{ formatMoney(row.refunded_cents || 0, row.currency) }}</td>
              <td class="muted">{{ formatTime(row.created_at) }}</td>
              <td>
                <div class="actions">
                  <button class="btn ghost sm" @click="openOrder(row)">详情</button>
                  <button v-if="canRefund && row.status === 'paid'" class="btn danger-ghost sm"
                    @click="openDecision('direct', { order: row })">退款</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <Pager :page="page" :page-size="pageSize" :total="total" :loading="loading" @update:page="setPage" />
    </template>
  </div>

  <div class="card">
    <div class="card-head">
      <div class="card-title">退款审批<span class="sub">待审批 {{ pendingRefunds.length }} 条 / 全部 {{ refundRows.length }} 条</span></div>
      <div class="spacer"></div>
      <div class="tabs">
        <button :class="{ active: refundTab === 'pending' }" @click="refundTab = 'pending'">
          待审批<span class="count">{{ pendingRefunds.length }}</span>
        </button>
        <button :class="{ active: refundTab === 'all' }" @click="refundTab = 'all'">
          全部<span class="count">{{ refundRows.length }}</span>
        </button>
      </div>
      <button class="btn ghost sm" :disabled="refundLoading" @click="loadRefunds">
        <Icon name="refresh" :size="14" />刷新
      </button>
    </div>

    <div v-if="refundLoading && !refundRows.length"><StateBlock kind="loading" title="正在加载退款记录…" /></div>
    <div v-else-if="refundError">
      <StateBlock kind="error" title="退款记录加载失败" :message="refundError" retry-label="重试" @retry="loadRefunds" />
    </div>
    <div v-else-if="!visibleRefunds.length">
      <StateBlock kind="empty" :title="refundTab === 'pending' ? '没有待审批退款' : '暂无退款记录'"
        :message="refundTab === 'pending' ? '所有退款申请均已处理。' : '尚未产生退款申请。'" />
    </div>
    <div v-else class="table-wrap">
      <table class="data-table">
        <thead>
          <tr>
            <th style="width: 80px">ID</th>
            <th style="width: 90px">订单</th>
            <th class="num" style="width: 100px">金额</th>
            <th style="width: 100px">状态</th>
            <th>原因 / 备注</th>
            <th style="width: 126px">申请时间</th>
            <th style="width: 120px">渠道</th>
            <th style="width: 150px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in visibleRefunds" :key="item.id">
            <td class="mono">#{{ item.id }}</td>
            <td class="mono">#{{ item.order_id }}</td>
            <td class="num">{{ formatMoney(item.amount_cents, item.currency) }}</td>
            <td><StatusBadge :value="item.status" dot /></td>
            <td>
              <div class="truncate" :title="item.reason || item.note || ''">{{ item.reason || item.note || '—' }}</div>
              <div v-if="item.note && item.reason" class="muted truncate" style="font-size: 11.5px">{{ item.note }}</div>
            </td>
            <td class="muted">{{ formatTime(item.requested_at) }}</td>
            <td class="muted">{{ item.provider }}</td>
            <td>
              <div v-if="canRefund" class="actions">
                <button class="btn ghost sm" @click="openDecision('approve', { refund: item })">通过</button>
                <button class="btn danger-ghost sm" @click="openDecision('reject', { refund: item })">拒绝</button>
              </div>
              <span v-else class="muted" style="font-size: 12px">只读</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="notice info" style="margin: 14px 0 0">
      <div class="notice-body">
        通过 / 拒绝使用 <span class="inline-code">POST /v1/admin/refunds/{id}/approve|reject</span>；
        直接退款使用 <span class="inline-code">POST /v1/admin/orders/{id}/refund</span>。操作会写入审计日志。
      </div>
    </div>
  </div>

  <Modal v-if="orderOpen" title="订单详情" :subtitle="currentOrder ? `#${currentOrder.id} · ${accountLabel(currentOrder)}` : ''"
    size="wide" @close="orderOpen = false">
    <div v-if="orderLoading"><StateBlock kind="loading" title="正在加载订单详情…" /></div>
    <div v-else-if="orderError">
      <StateBlock kind="error" title="订单详情加载失败" :message="orderError" retry-label="重试"
        @retry="selectedOrder && openOrder(selectedOrder)" />
    </div>
    <template v-if="currentOrder">
      <div class="kv-grid">
        <div class="kv"><span class="k">订单 ID</span><span class="v mono">#{{ currentOrder.id }}</span></div>
        <div class="kv"><span class="k">账号</span><span class="v">{{ accountLabel(currentOrder) }}</span></div>
        <div class="kv"><span class="k">金额</span><span class="v">{{ formatMoney(currentOrder.amount_cents, currentOrder.currency) }}</span></div>
        <div class="kv"><span class="k">已退款</span><span class="v">{{ formatMoney(currentOrder.refunded_cents || 0, currentOrder.currency) }}</span></div>
        <div class="kv"><span class="k">状态</span><span class="v"><StatusBadge :value="currentOrder.status" dot /></span></div>
        <div class="kv"><span class="k">渠道</span><span class="v">{{ currentOrder.provider }}</span></div>
        <div class="kv"><span class="k">类型 / 周期</span><span class="v">{{ currentOrder.kind || '—' }}<span v-if="currentOrder.cycle"> / {{ currentOrder.cycle }}</span></span></div>
        <div class="kv"><span class="k">订阅 ID</span><span class="v mono">{{ currentOrder.subscription_id ? `#${currentOrder.subscription_id}` : '—' }}</span></div>
        <div class="kv"><span class="k">外部单号</span><span class="v mono">{{ currentOrder.external_order_no || '—' }}</span></div>
        <div class="kv"><span class="k">渠道交易号</span><span class="v mono">{{ currentOrder.provider_txn_id || '—' }}</span></div>
        <div class="kv"><span class="k">创建时间</span><span class="v">{{ formatTime(currentOrder.created_at) }}</span></div>
        <div class="kv"><span class="k">支付时间</span><span class="v">{{ formatTime(currentOrder.paid_at) }}</span></div>
        <div class="kv"><span class="k">失败原因</span><span class="v">{{ currentOrder.failure_reason || '—' }}</span></div>
      </div>

      <div v-if="currentOrder.meta" class="section-sub">附加信息</div>
      <div v-if="currentOrder.meta" class="json-block">{{ prettyJson(currentOrder.meta) }}</div>

      <div class="section-sub">关联退款</div>
      <div v-if="orderEvenRecords.length" class="table-wrap">
        <table class="data-table">
          <thead><tr><th>ID</th><th class="num">金额</th><th>状态</th><th>原因</th><th>申请时间</th><th>完成时间</th></tr></thead>
          <tbody>
            <tr v-for="item in orderEvenRecords" :key="item.id">
              <td class="mono">#{{ item.id }}</td>
              <td class="num">{{ formatMoney(item.amount_cents, item.currency) }}</td>
              <td><StatusBadge :value="item.status" /></td>
              <td class="truncate" :title="item.reason || item.note || ''">{{ item.reason || item.note || '—' }}</td>
              <td class="muted">{{ formatTime(item.requested_at) }}</td>
              <td class="muted">{{ formatTime(item.succeeded_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="muted" style="font-size: 12.5px">该订单暂无退款记录</div>
    </template>
    <template #footer>
      <button class="btn ghost sm" @click="orderOpen = false">关闭</button>
      <button v-if="canRefund && currentOrder && currentOrder.status === 'paid'" class="btn danger-ghost sm"
        @click="openDecision('direct', { order: currentOrder }); orderOpen = false">直接退款</button>
    </template>
  </Modal>

  <Modal v-if="decisionOpen" :title="decisionTitle"
    :subtitle="decisionRefund ? `退款 #${decisionRefund.id} · 订单 #${decisionRefund.order_id}` : decisionOrder ? `订单 #${decisionOrder.id} · ${accountLabel(decisionOrder)}` : ''"
    size="narrow" @close="decisionOpen = false">
    <div class="form-grid" style="grid-template-columns: 1fr">
      <div v-if="decisionMode === 'direct'" class="field">
        <label>退款金额（元）</label>
        <input v-model="decisionAmount" class="input" type="number" min="0.01" step="0.01" placeholder="留空表示全额退款" />
        <span class="hint">全额 {{ decisionOrder ? formatMoney(decisionOrder.amount_cents, decisionOrder.currency) : '—' }}</span>
      </div>
      <div class="field">
        <label>{{ decisionMode === 'reject' ? '拒绝备注' : '备注 / 原因' }}<span v-if="decisionMode !== 'approve'" class="required">*</span></label>
        <textarea v-model="decisionNote" class="textarea"
          :placeholder="decisionMode === 'reject' ? '请说明拒绝原因，将回传给用户' : '例如：用户重复支付，原路退回'"></textarea>
        <span class="hint">内容会写入审计日志，请勿填写敏感凭据。</span>
      </div>
    </div>
    <div v-if="decisionError" class="notice error" style="margin: 12px 0 0">{{ decisionError }}</div>
    <template #footer>
      <button class="btn ghost sm" :disabled="decisionSubmitting" @click="decisionOpen = false">取消</button>
      <button class="btn" :class="decisionMode === 'reject' ? 'danger' : ''" :disabled="decisionSubmitting" @click="submitDecision">
        {{ decisionSubmitting ? '提交中…' : (decisionMode === 'approve' ? '确认通过' : decisionMode === 'reject' ? '确认拒绝' : '确认退款') }}
      </button>
    </template>
  </Modal>
</template>
