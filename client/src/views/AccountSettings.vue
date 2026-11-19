<template>
  <main class="page account">
    <div class="account__head">
      <h1 class="account__title">账户设置</h1>
      <p class="account__desc">管理登录安全、订单退款、个人数据与账号状态。</p>
    </div>

    <SegmentedTabs :tabs="tabs" :model-value="tab" @update:model-value="onTab" />

    <div class="account__panel">
      <!-- 订阅与额度 -->
      <section v-if="tab === 'subscription'" class="card account__card">
        <SubscriptionTab />
      </section>

      <!-- 自有模型 Key（BYOK） -->
      <section v-else-if="tab === 'byok'" class="card account__card">
        <ByokTab />
      </section>

      <!-- 账号安全 -->
      <section v-else-if="tab === 'security'" class="card account__card">
        <div class="account__section-head">
          <h2>修改密码</h2>
          <p>修改后其它设备需要重新登录，当前设备保持登录。</p>
        </div>
        <form class="account__form" @submit.prevent="submitPassword">
          <div class="field">
            <label class="field__label" for="pwd-old">当前密码</label>
            <input
              id="pwd-old"
              v-model="pwd.old"
              class="input"
              type="password"
              autocomplete="current-password"
              placeholder="输入当前密码"
            />
          </div>
          <div class="field">
            <label class="field__label" for="pwd-new">新密码</label>
            <input
              id="pwd-new"
              v-model="pwd.next"
              class="input"
              type="password"
              autocomplete="new-password"
              placeholder="至少 8 位"
            />
          </div>
          <div class="field">
            <label class="field__label" for="pwd-confirm">确认新密码</label>
            <input
              id="pwd-confirm"
              v-model="pwd.confirm"
              class="input"
              type="password"
              autocomplete="new-password"
              placeholder="再输入一次"
            />
          </div>
          <p v-if="pwdError" class="account__error" role="alert">{{ pwdError }}</p>
          <p v-if="pwdInfo" class="account__info" role="status">{{ pwdInfo }}</p>
          <button class="btn btn--brand account__action" type="submit" :disabled="pwdSubmitting">
            {{ pwdSubmitting ? '保存中…' : '保存新密码' }}
          </button>
        </form>
      </section>

      <!-- 订单与退款 -->
      <section v-else-if="tab === 'orders'" class="card account__card">
        <div class="account__section-head">
          <h2>订单与退款</h2>
          <p>查看支付订单，对可退订单提交退款申请（管理端审核后原路退回）。</p>
        </div>
        <button class="btn btn--ghost btn--sm" type="button" :disabled="ordersLoading" @click="loadOrdersAndRefunds">
          {{ ordersLoading ? '刷新中…' : '刷新订单' }}
        </button>

        <p v-if="ordersError" class="account__error" role="alert">{{ ordersError }}</p>

        <div v-if="orders.length" class="account__orders">
          <div v-for="order in orders" :key="order.id" class="account__order">
            <div class="account__order-main">
              <span class="account__order-title">
                订单 #{{ order.id }}
                <span class="account__order-status" :class="`is-${order.status}`">{{ orderStatusLabel(order.status) }}</span>
              </span>
              <span class="account__order-meta">
                {{ orderKindLabel(order.kind) }} · {{ formatMoney(order.amount_cents, order.currency) }} ·
                {{ formatTime(order.created_at) }}
              </span>
              <span v-if="!isRefundable(order)" class="account__order-note">{{ orderUnavailableText(order) }}</span>
            </div>
            <button
              v-if="isRefundable(order)"
              class="btn btn--ghost btn--sm"
              type="button"
              :disabled="refundingOrderId === order.id"
              @click="openRefund(order)"
            >
              {{ refundingOrderId === order.id ? '查询中…' : '申请退款' }}
            </button>
          </div>
          <p v-if="!refundableOrders.length" class="account__hint">暂无可申请退款的订单，付款成功后可在此申请。</p>
        </div>
        <p v-else-if="!ordersLoading" class="account__hint">尚无订单记录。</p>

        <div v-if="refundTarget" class="account__refund-form">
          <p class="account__refund-quote">
            订单 #{{ refundTarget.order.id }} · 可退金额
            <strong>{{ formatMoney(refundTarget.quote.refundable_cents, refundTarget.order.currency) }}</strong>
            <span class="account__hint">（{{ refundMethodLabel(refundTarget.quote.method) }}，最终以审核为准）</span>
          </p>
          <div class="field">
            <label class="field__label" for="refund-reason">退款原因</label>
            <input
              id="refund-reason"
              v-model="refundReason"
              class="input"
              type="text"
              maxlength="200"
              placeholder="请简要说明退款原因"
              :aria-invalid="!!refundError"
            />
          </div>
          <p v-if="refundError" class="account__error" role="alert">{{ refundError }}</p>
          <div class="account__actions-row">
            <button class="btn btn--brand btn--sm" type="button" :disabled="refundSubmitting" @click="submitRefund">
              {{ refundSubmitting ? '提交中…' : '提交申请' }}
            </button>
            <button class="btn btn--ghost btn--sm" type="button" @click="closeRefund">取消</button>
          </div>
        </div>

        <div v-if="refunds.length" class="account__refunds">
          <p class="account__refunds-title">退款记录</p>
          <div v-for="refund in refunds" :key="refund.id" class="account__refund-row">
            <span>订单 #{{ refund.order_id }}</span>
            <span>{{ formatMoney(refund.amount_cents, refund.currency) }}</span>
            <span class="account__refund-status" :class="`is-${refund.status}`">{{ refundStatusLabel(refund.status) }}</span>
          </div>
        </div>
      </section>

      <!-- 数据与导出 -->
      <section v-else-if="tab === 'data'" class="card account__card">
        <div class="account__section-head">
          <h2>导出个人数据</h2>
          <p>下载账号、作品、任务、订单与同意留痕的结构化数据（JSON），不含密码与令牌哈希。</p>
        </div>
        <button class="btn btn--brand account__action" type="button" :disabled="exporting" @click="onExport">
          <span v-if="exporting" class="account__spinner" aria-hidden="true" />
          {{ exporting ? '导出中…' : '导出我的数据' }}
        </button>
        <p v-if="exportError" class="account__error" role="alert">{{ exportError }}</p>
        <p v-if="exportInfo" class="account__info" role="status">{{ exportInfo }}</p>
      </section>

      <!-- 注销账号 -->
      <section v-else class="card account__card account__card--danger">
        <div class="account__section-head">
          <h2>注销账号</h2>
          <p>提交后账号立即停止登录，全部会话撤销；宽限期结束后数据将被清除，此操作不可撤销。</p>
        </div>

        <div v-if="deletion" class="account__deletion" role="status">
          <p class="account__deletion-title">注销申请已提交</p>
          <p>状态：{{ statusLabel(deletion.status) }}</p>
          <p>预计清除时间：{{ formatDate(deletion.purge_at) }}</p>
          <p class="account__hint">宽限期内如需恢复账号，请联系客服处理。</p>
        </div>

        <template v-else>
          <div class="field">
            <label class="field__label" for="delete-password">当前密码</label>
            <input
              id="delete-password"
              v-model="password"
              class="input"
              type="password"
              autocomplete="current-password"
              placeholder="输入当前密码以确认身份"
              :aria-invalid="!!deleteError"
            />
          </div>
          <div class="field">
            <label class="field__label" for="delete-confirm">确认串</label>
            <input
              id="delete-confirm"
              v-model="confirmation"
              class="input"
              type="text"
              autocomplete="off"
              placeholder="请输入 DELETE_MY_ACCOUNT"
              :aria-invalid="!!deleteError"
            />
            <p class="account__hint">请输入 <code>DELETE_MY_ACCOUNT</code> 以确认你了解此操作不可撤销。</p>
          </div>
          <p v-if="deleteError" class="account__error" role="alert">{{ deleteError }}</p>
          <button class="btn btn--danger account__action" type="button" :disabled="deleting" @click="onDelete">
            <span v-if="deleting" class="account__spinner" aria-hidden="true" />
            {{ deleting ? '提交中…' : '提交注销申请' }}
          </button>
        </template>
      </section>
    </div>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import SegmentedTabs, { type SegmentedTab } from '@/components/SegmentedTabs.vue'
import ByokTab from '@/components/account/ByokTab.vue'
import SubscriptionTab from '@/components/account/SubscriptionTab.vue'
import {
  authErrorMessage,
  changePassword,
  exportMyData,
  requestAccountDeletion,
  type AccountDeletionRequestView,
} from '@/services/authApi'
import {
  fetchOrders,
  fetchRefundQuote,
  fetchRefunds,
  formatMoney,
  requestRefund,
} from '@/services/billingApi'
import { ApiError } from '@/services/http'
import { resetSession } from '@/stores/session'
import { saveFile } from '@/utils/download'
import type { RefundQuote, UserOrder, UserRefund } from '@/types'

type AccountTab = 'subscription' | 'byok' | 'security' | 'orders' | 'data' | 'danger'

const tabs: SegmentedTab[] = [
  { id: 'subscription', label: '订阅与额度' },
  { id: 'byok', label: '自有模型' },
  { id: 'security', label: '账号安全' },
  { id: 'orders', label: '订单与退款' },
  { id: 'data', label: '数据与导出' },
  { id: 'danger', label: '注销账号' },
]
const ACCOUNT_TABS: AccountTab[] = ['subscription', 'byok', 'security', 'orders', 'data', 'danger']

const route = useRoute()
const router = useRouter()
const tab = ref<AccountTab>('subscription')

function onTab(value: string): void {
  tab.value = value as AccountTab
  void router.replace({ path: '/account', query: { tab: value } })
}

watch(
  () => route.query.tab,
  (value) => {
    if (ACCOUNT_TABS.includes(value as AccountTab)) tab.value = value as AccountTab
  },
  { immediate: true },
)

// 修改密码
const pwd = reactive({ old: '', next: '', confirm: '' })
const pwdSubmitting = ref(false)
const pwdError = ref('')
const pwdInfo = ref('')

// 导出数据
const exporting = ref(false)
const exportError = ref('')
const exportInfo = ref('')

// 注销账号
const password = ref('')
const confirmation = ref('')
const deleting = ref(false)
const deleteError = ref('')
const deletion = ref<AccountDeletionRequestView | null>(null)

// 订单与退款
const orders = ref<UserOrder[]>([])
const refunds = ref<UserRefund[]>([])
const ordersLoading = ref(false)
const ordersError = ref('')
const refundingOrderId = ref<number | null>(null)
const refundTarget = ref<{ order: UserOrder; quote: RefundQuote } | null>(null)
const refundReason = ref('')
const refundSubmitting = ref(false)
const refundError = ref('')

// 可申请退款：已支付/部分退款且未全额退
function isRefundable(o: UserOrder): boolean {
  return ['paid', 'partially_refunded', 'refunded'].includes(o.status) && o.refunded_cents < o.amount_cents
}
const refundableOrders = computed(() => orders.value.filter(isRefundable))

// 不可退订单的说明文案，让用户明白为什么没有「申请退款」按钮
function orderUnavailableText(o: UserOrder): string {
  if (o.status === 'pending') return '待支付，付款成功后可申请退款'
  if (o.status === 'canceled') return '已取消，无法退款'
  if (o.refunded_cents >= o.amount_cents) return '已全额退款'
  return o.status === 'refunded' ? '已退款' : '当前状态暂不支持退款'
}

onMounted(() => {
  void loadOrdersAndRefunds()
})

async function submitPassword(): Promise<void> {
  pwdError.value = ''
  pwdInfo.value = ''
  if (!pwd.old) {
    pwdError.value = '请输入当前密码'
    return
  }
  if (pwd.next.length < 8) {
    pwdError.value = '新密码至少 8 位'
    return
  }
  if (pwd.next !== pwd.confirm) {
    pwdError.value = '两次输入的新密码不一致'
    return
  }
  if (pwd.next === pwd.old) {
    pwdError.value = '新密码不能与当前密码相同'
    return
  }
  pwdSubmitting.value = true
  try {
    const result = await changePassword(pwd.old, pwd.next)
    pwd.old = ''
    pwd.next = ''
    pwd.confirm = ''
    pwdInfo.value = result.message || '密码已更新，其它设备需重新登录。'
  } catch (err) {
    pwdError.value =
      err instanceof ApiError ? authErrorMessage(err.status, err.code, err.message) : '修改失败，请稍后重试'
  } finally {
    pwdSubmitting.value = false
  }
}

async function onExport(): Promise<void> {
  exporting.value = true
  exportError.value = ''
  exportInfo.value = ''
  try {
    const data = await exportMyData()
    const date = new Date().toISOString().slice(0, 10)
    const file = new File([JSON.stringify(data, null, 2)], `moxie-data-${date}.json`, {
      type: 'application/json',
    })
    saveFile(file)
    exportInfo.value = '数据已导出，请检查浏览器下载。'
  } catch (err) {
    exportError.value =
      err instanceof ApiError ? authErrorMessage(err.status, err.code, err.message) : '导出失败，请稍后重试'
  } finally {
    exporting.value = false
  }
}

async function loadOrdersAndRefunds(): Promise<void> {
  ordersLoading.value = true
  ordersError.value = ''
  try {
    const [orderList, refundList] = await Promise.all([fetchOrders(), fetchRefunds()])
    orders.value = orderList
    refunds.value = refundList
  } catch (err) {
    ordersError.value =
      err instanceof ApiError ? authErrorMessage(err.status, err.code, err.message) : '加载失败，请稍后重试'
  } finally {
    ordersLoading.value = false
  }
}

async function openRefund(order: UserOrder): Promise<void> {
  refundError.value = ''
  refundingOrderId.value = order.id
  try {
    const quote = await fetchRefundQuote(order.id)
    if (quote.refundable_cents <= 0) {
      ordersError.value = '该订单按已用量折算后无可退金额'
      return
    }
    refundTarget.value = { order, quote }
    refundReason.value = ''
  } catch (err) {
    ordersError.value =
      err instanceof ApiError ? authErrorMessage(err.status, err.code, err.message) : '查询可退金额失败'
  } finally {
    refundingOrderId.value = null
  }
}

function closeRefund(): void {
  refundTarget.value = null
  refundError.value = ''
}

async function submitRefund(): Promise<void> {
  if (!refundTarget.value) return
  refundError.value = ''
  if (refundReason.value.trim().length < 2) {
    refundError.value = '请填写退款原因（至少 2 个字）'
    return
  }
  refundSubmitting.value = true
  try {
    await requestRefund(refundTarget.value.order.id, refundReason.value.trim())
    closeRefund()
    await loadOrdersAndRefunds()
  } catch (err) {
    refundError.value =
      err instanceof ApiError ? authErrorMessage(err.status, err.code, err.message) : '提交失败，请稍后重试'
  } finally {
    refundSubmitting.value = false
  }
}

async function onDelete(): Promise<void> {
  deleteError.value = ''
  if (!password.value) {
    deleteError.value = '请输入当前密码'
    return
  }
  if (confirmation.value.trim() !== 'DELETE_MY_ACCOUNT') {
    deleteError.value = '确认串不正确，请输入 DELETE_MY_ACCOUNT'
    return
  }
  deleting.value = true
  try {
    deletion.value = await requestAccountDeletion(password.value)
    resetSession()
    password.value = ''
    confirmation.value = ''
  } catch (err) {
    deleteError.value =
      err instanceof ApiError ? authErrorMessage(err.status, err.code, err.message) : '提交失败，请稍后重试'
  } finally {
    deleting.value = false
  }
}

function formatTime(value: string | null): string {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('zh-CN', { hour12: false })
}

function orderKindLabel(kind: string): string {
  const map: Record<string, string> = {
    purchase: '订阅购买',
    renewal: '订阅续费',
    upgrade: '套餐升级',
    credit_pack: '额度包',
  }
  return map[kind] || kind
}

function orderStatusLabel(status: string): string {
  const map: Record<string, string> = {
    pending: '待支付',
    paid: '已支付',
    refunded: '已退款',
    partially_refunded: '部分退款',
    canceled: '已取消',
  }
  return map[status] || status
}

function refundMethodLabel(method: string): string {
  const map: Record<string, string> = {
    credit_pack_unused: '按剩余额度折算',
    upgrade_remaining_time: '按剩余时长折算',
    subscription_usage: '按已用量折算',
    ungranted: '额度未发放',
    no_subscription: '无关联订阅',
  }
  return map[method] || method
}

function refundStatusLabel(status: string): string {
  const map: Record<string, string> = {
    pending: '待审核',
    processing: '退款中',
    succeeded: '已退款',
    failed: '未通过',
  }
  return map[status] || status
}

function statusLabel(status: string): string {
  if (status === 'pending') return '待清除'
  if (status === 'cancelled') return '已撤销'
  if (status === 'purged') return '已清除'
  return status
}

function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN')
}
</script>

<style scoped>
.account {
  padding-top: 36px;
}

.account__head {
  text-align: center;
  margin-bottom: 20px;
}

.account__title {
  font-size: 24px;
  font-weight: 700;
  color: var(--color-text);
  margin: 0 0 8px;
}

.account__desc {
  font-size: var(--text-sm);
  color: var(--color-text-2);
  line-height: 1.6;
  margin: 0;
}

.account__panel {
  margin-top: 20px;
}

.account__card {
  padding: 28px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.account__section-head {
  padding-bottom: 16px;
  border-bottom: 1px solid var(--color-border, var(--border, #e5e7eb));
}

.account__section-head h2 {
  font-size: 17px;
  font-weight: 600;
  color: var(--color-text);
  margin: 0 0 6px;
}

.account__section-head p {
  font-size: var(--text-sm);
  color: var(--color-text-2);
  line-height: 1.7;
  margin: 0;
}

.account__form {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 420px;
}

.account__orders {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.account__order {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--color-border, var(--border, #e5e7eb));
  border-radius: var(--radius-md, 8px);
}

.account__order-main {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.account__order-title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--color-text);
}

.account__order-status {
  font-size: var(--text-xs);
  font-weight: 500;
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--color-bg-soft);
  color: var(--color-text-2);
}
.account__order-status.is-paid { background: var(--color-success-soft, #ecfdf3); color: var(--color-success, #067647); }
.account__order-status.is-pending,
.account__order-status.is-processing,
.account__order-status.is-requested { background: var(--color-warn-soft, #fffaeb); color: var(--color-warn, #b54708); }
.account__order-status.is-refunded,
.account__order-status.is-partially_refunded { background: #f2ebff; color: var(--color-accent, #7c3aed); }
.account__order-status.is-canceled { background: var(--color-bg-soft); color: var(--color-text-3); }

.account__order-meta {
  font-size: var(--text-xs);
  color: var(--color-text-2);
}

.account__order-note {
  font-size: var(--text-xs);
  color: var(--color-text-3);
}

.account__refund-form {
  padding: 16px;
  border-radius: var(--radius-md, 8px);
  background: var(--color-bg-soft, var(--surface-2, #fafafa));
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.account__refund-quote {
  font-size: var(--text-sm);
  color: var(--color-text-2);
  margin: 0;
}

.account__refund-quote strong {
  color: var(--color-text);
}

.account__actions-row {
  display: flex;
  gap: 8px;
}

.account__refunds {
  margin-top: 4px;
  border-top: 1px solid var(--color-border, var(--border, #e5e7eb));
  padding-top: 12px;
}

.account__refunds-title {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--color-text);
  margin: 0 0 8px;
}

.account__refund-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 6px 0;
  font-size: var(--text-xs);
  color: var(--color-text-2);
}

.account__refund-status.is-succeeded {
  color: var(--color-success, #1a9c6b);
}
.account__refund-status.is-pending,
.account__refund-status.is-processing {
  color: var(--color-warn, #b45309);
}
.account__refund-status.is-failed {
  color: var(--color-danger, #dc2626);
}

.account__card--danger {
  border-color: rgba(220, 38, 38, 0.35);
}

.account__card--danger .account__section-head h2 {
  color: var(--color-danger, #dc2626);
}

.account__action {
  height: 42px;
  max-width: 260px;
}

.account__spinner {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 2px solid rgba(255, 255, 255, 0.4);
  border-top-color: #fff;
  animation: account-spin 0.7s linear infinite;
}

@keyframes account-spin {
  to {
    transform: rotate(360deg);
  }
}

.account__error {
  font-size: var(--text-xs);
  color: var(--color-danger);
  margin: 0;
}

.account__info {
  font-size: var(--text-xs);
  color: var(--color-success, #1a9c6b);
  margin: 0;
}

.account__hint {
  font-size: var(--text-xs);
  color: var(--color-text-3);
  margin: 4px 0 0;
  line-height: 1.6;
}

.account__hint code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  color: var(--color-text-2);
}

.account__deletion {
  padding: 16px;
  border-radius: var(--radius-md);
  background: var(--color-bg-soft);
  font-size: var(--text-sm);
  color: var(--color-text-2);
}

.account__deletion p {
  margin: 4px 0;
}

.account__deletion-title {
  font-weight: 600;
  color: var(--color-text);
}
</style>
