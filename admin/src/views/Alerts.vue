<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errorMessage, normalizeList } from '../api'
import { can } from '../roles'
import { getRole } from '../session'
import { pushToast } from '../toast'
import type { AlertRow, NotificationBatchResult, NotificationDetail, NotificationRow, PushReceiptHistory } from '../types'
import { accountLabel, formatNumber, formatTime } from '../ui'
import { useVirtualRows } from '../utils/useVirtualRows'
import Icon from '../components/Icon.vue'
import Modal from '../components/Modal.vue'
import PageHeader from '../components/PageHeader.vue'
import RowActions, { type RowAction } from '../components/RowActions.vue'
import Pager from '../components/Pager.vue'
import StateBlock from '../components/StateBlock.vue'
import StatusBadge from '../components/StatusBadge.vue'
import UiSelect from '../components/UiSelect.vue'

// 两个长列表单页各取 200 条，定高虚拟滚动；Pager 负责跨页导航。
const ROW_HEIGHT = 48
const VIEWPORT_HEIGHT = 432

const role = getRole()
const canRetry = computed(() => can(role, 'notifications:write'))

const alertRows = ref<AlertRow[]>([])
const alertVirt = useVirtualRows(alertRows, ROW_HEIGHT, VIEWPORT_HEIGHT, 6)
const alertsLoading = ref(false)
const alertsError = ref('')
const alertPage = ref(1)
const alertPageSize = 200
const alertTotal = ref<number | null>(null)

async function loadAlerts() {
  alertsLoading.value = true
  alertsError.value = ''
  try {
    const data = await api.alerts({ page: alertPage.value, page_size: alertPageSize })
    const list = normalizeList<AlertRow>(data)
    alertRows.value = list.items
    alertTotal.value = list.total
  } catch (e) {
    alertRows.value = []
    alertTotal.value = null
    alertsError.value = errorMessage(e)
  } finally {
    alertsLoading.value = false
  }
}

function setAlertPage(next: number) {
  alertPage.value = next
  alertVirt.resetScroll()
  void loadAlerts()
}

const notifStatus = ref('')
const notifPage = ref(1)
const notifPageSize = 200
const notificationRows = ref<NotificationRow[]>([])
const notifVirt = useVirtualRows(notificationRows, ROW_HEIGHT, VIEWPORT_HEIGHT, 6)
const notifTotal = ref<number | null>(null)
const notifLoading = ref(false)
const notifError = ref('')
const retryingId = ref<number | null>(null)
const detailRow = ref<NotificationDetail | null>(null)
const detailLoading = ref(false)
const detailError = ref('')

const receiptRow = ref<PushReceiptHistory | null>(null)
const receiptLoading = ref(false)
const receiptError = ref('')

// 批量发送弹层
const batchOpen = ref(false)
const batchSubmitting = ref(false)
const batchAccounts = ref('')
const batchTitle = ref('')
const batchBody = ref('')
const batchChannels = ref<string[]>(['inapp', 'push'])
const batchResult = ref<NotificationBatchResult | null>(null)
const batchError = ref('')

const BATCH_CHANNELS = [
  { value: 'inapp', label: '站内信' },
  { value: 'push', label: '浏览器推送' },
  { value: 'email', label: '邮件' },
  { value: 'sms', label: '短信' },
]

function openBatch() {
  batchAccounts.value = ''
  batchTitle.value = ''
  batchBody.value = ''
  batchChannels.value = ['inapp', 'push']
  batchResult.value = null
  batchError.value = ''
  batchOpen.value = true
}

function parseAccountIds(raw: string): number[] {
  const ids = raw.split(/[\s,，]+/).map((s) => Number(s.trim())).filter((n) => Number.isInteger(n) && n > 0)
  return Array.from(new Set(ids))
}

async function submitBatch() {
  const accountIds = parseAccountIds(batchAccounts.value)
  if (!accountIds.length) {
    batchError.value = '请填写至少一个有效账号 ID（用逗号或空格分隔）'
    return
  }
  batchSubmitting.value = true
  batchError.value = ''
  try {
    batchResult.value = await api.sendNotificationBatch({
      account_ids: accountIds,
      title: batchTitle.value,
      body: batchBody.value,
      channels: batchChannels.value,
    })
    pushToast(`批量发送完成：成功 ${batchResult.value.sent}/${batchResult.value.total}`)
    await loadNotifications()
  } catch (e) {
    batchError.value = errorMessage(e)
  } finally {
    batchSubmitting.value = false
  }
}

function toggleBatchChannel(value: string) {
  batchChannels.value = batchChannels.value.includes(value)
    ? batchChannels.value.filter((c) => c !== value)
    : [...batchChannels.value, value]
}

async function openReceipts(row: NotificationRow) {
  receiptRow.value = null
  receiptError.value = ''
  receiptLoading.value = true
  try {
    const data = await api.notificationReceipts(row.id)
    receiptRow.value = data.delivery
  } catch (e) {
    receiptError.value = errorMessage(e)
  } finally {
    receiptLoading.value = false
  }
}

/** 下次重试时间：相对当前时间的倒计时（过去/空显示 —）。 */
function retryHint(iso?: string | null): string {
  if (!iso) return '—'
  const target = new Date(iso).getTime()
  if (!Number.isFinite(target)) return '—'
  const seconds = Math.round((target - Date.now()) / 1000)
  if (seconds <= 0) return '立即可重试'
  if (seconds < 60) return `${seconds}s 后`
  if (seconds < 3600) return `${Math.ceil(seconds / 60)}m 后`
  return formatTime(iso)
}

/** 列表送达摘要：delivered/subscribers，含失效订阅数。 */
function deliveryHint(row: NotificationRow): string {
  const s = row.meta_summary
  if (!s || !s.subscribers) return '—'
  const delivered = s.delivered ?? 0
  const expired = s.expired_count ?? 0
  let text = `${delivered}/${s.subscribers}`
  if (expired) text += ` · 失效 ${expired}`
  return text
}

async function openDetail(row: NotificationRow) {
  detailRow.value = null
  detailError.value = ''
  detailLoading.value = true
  try {
    const data = await api.notificationDetail(row.id)
    detailRow.value = data.delivery
  } catch (e) {
    detailError.value = errorMessage(e)
  } finally {
    detailLoading.value = false
  }
}

async function loadNotifications() {
  notifLoading.value = true
  notifError.value = ''
  try {
    const data = await api.notifications({ status: notifStatus.value, page: notifPage.value, page_size: notifPageSize })
    const list = normalizeList<NotificationRow>(data)
    notificationRows.value = list.items
    notifTotal.value = list.total
  } catch (e) {
    notificationRows.value = []
    notifTotal.value = null
    notifError.value = errorMessage(e)
  } finally {
    notifLoading.value = false
  }
}

function changeNotifStatus() {
  notifPage.value = 1
  notifVirt.resetScroll()
  void loadNotifications()
}

function setNotifPage(next: number) {
  notifPage.value = next
  notifVirt.resetScroll()
  void loadNotifications()
}

async function retryNotification(row: NotificationRow) {
  retryingId.value = row.id
  try {
    await api.retryNotification(row.id)
    pushToast(`通知 ${row.id} 已重新发送`)
    await loadNotifications()
  } catch (e) {
    pushToast(errorMessage(e), 'error')
  } finally {
    retryingId.value = null
  }
}

onMounted(() => {
  void loadAlerts()
  void loadNotifications()
})

function notifActions(row: NotificationRow): RowAction[] {
  const actions: RowAction[] = [{ label: '详情', run: () => openDetail(row) }]
  if (row.channel === 'push') actions.push({ label: '回执', run: () => openReceipts(row) })
  if (canRetry.value && ['failed', 'skipped'].includes(row.status)) {
    actions.push({
      label: retryingId.value === row.id ? '提交中…' : '重试',
      disabled: retryingId.value === row.id,
      run: () => retryNotification(row),
    })
  }
  return actions
}
</script>

<template>
  <PageHeader title="告警与通知" desc="查看异常用量告警与通知发送记录（成功 / 失败 / 重试）。">
    <span v-if="!canRetry" class="badge muted">support 只读</span>
    <button v-if="canRetry" class="btn primary sm" @click="openBatch">
      <Icon name="plus" :size="14" />批量发送
    </button>
    <button class="btn ghost sm" :disabled="alertsLoading || notifLoading"
      @click="loadAlerts(); loadNotifications()">
      <Icon name="refresh" :size="14" />刷新全部
    </button>
  </PageHeader>

  <div v-if="!canRetry" class="notice info">
    <div class="notice-body">
      <div class="notice-title">只读模式</div>
      <div>当前角色可查看异常用量告警与通知发送记录；通知重试需要管理员（admin）权限。</div>
    </div>
  </div>

  <div class="card">
    <div class="card-head">
      <div class="card-title">异常用量告警<span class="sub">{{ alertTotal === null ? `${alertRows.length} 条` : `${formatNumber(alertTotal)} 条` }}</span></div>
      <div class="spacer"></div>
      <button class="btn ghost sm" :disabled="alertsLoading" @click="loadAlerts">
        <Icon name="refresh" :size="14" />刷新
      </button>
    </div>

    <div v-if="alertsLoading && !alertRows.length"><StateBlock kind="loading" title="正在加载告警…" /></div>
    <div v-else-if="alertsError">
      <StateBlock kind="error" title="告警加载失败" :message="alertsError" retry-label="重试" @retry="loadAlerts" />
    </div>
    <div v-else-if="!alertRows.length">
      <StateBlock kind="empty" title="暂无异常用量告警" message="当前没有超过阈值的用量记录。" />
    </div>
    <template v-else>
      <div class="table-wrap vtable" :style="{ maxHeight: `${VIEWPORT_HEIGHT + 40}px` }" @scroll.passive="alertVirt.onScroll">
        <table class="data-table vtable">
          <thead>
            <tr><th style="width: 96px">级别</th><th>账号</th><th>指标</th><th class="num">用量</th><th class="num">阈值</th><th>说明</th><th style="width: 96px">状态</th><th style="width: 150px">触发时间</th></tr>
          </thead>
          <tbody>
            <tr v-if="alertVirt.range.value.paddingTop" class="vtable-spacer" :style="{ height: `${alertVirt.range.value.paddingTop}px` }"><td colspan="8" /></tr>
            <tr v-for="(item, i) in alertVirt.visibleRows.value" :key="item.id ?? item.metric ?? `row-${alertVirt.range.value.start + i}`" class="vtable-row vtable-row--tall">
              <td><StatusBadge :value="item.level || 'info'" /></td>
              <td>
                <div class="truncate" :title="`${accountLabel(item)}${item.account_id ? ` · 账号 #${item.account_id}` : ''}`">
                  {{ accountLabel(item) }}<template v-if="item.account_id"> · 账号 #{{ item.account_id }}</template>
                </div>
              </td>
              <td class="mono">{{ item.metric || '—' }}</td>
              <td class="num">{{ formatNumber(item.quantity) }}</td>
              <td class="num">{{ formatNumber(item.threshold) }}</td>
              <td class="truncate" :title="item.message || ''">{{ item.message || '—' }}</td>
              <td><StatusBadge :value="item.status || 'pending'" /></td>
              <td class="muted cell-time">{{ formatTime(item.created_at) }}</td>
            </tr>
            <tr v-if="alertVirt.range.value.paddingBottom" class="vtable-spacer" :style="{ height: `${alertVirt.range.value.paddingBottom}px` }"><td colspan="8" /></tr>
          </tbody>
        </table>
      </div>
      <Pager :page="alertPage" :page-size="alertPageSize" :total="alertTotal" :loading="alertsLoading" @update:page="setAlertPage" />
    </template>
  </div>

  <div class="card">
    <div class="card-head">
      <div class="card-title">通知发送记录<span class="sub">{{ notifTotal === null ? '' : `${formatNumber(notifTotal)} 条` }}</span></div>
      <div class="spacer"></div>
      <UiSelect
        v-model="notifStatus"
        size="sm"
        variant="toolbar"
        placeholder="全部状态"
        :options="[
          { value: 'queued', label: '待发送' },
          { value: 'sent', label: '已发送' },
          { value: 'failed', label: '失败' },
          { value: 'skipped', label: '已跳过' },
        ]"
        @change="changeNotifStatus"
      />
      <button class="btn ghost sm" :disabled="notifLoading" @click="loadNotifications">
        <Icon name="refresh" :size="14" />刷新
      </button>
    </div>

    <div v-if="notifLoading && !notificationRows.length"><StateBlock kind="loading" title="正在加载通知记录…" /></div>
    <div v-else-if="notifError">
      <StateBlock kind="error" title="通知记录加载失败" :message="notifError" retry-label="重试" @retry="loadNotifications" />
    </div>
    <div v-else-if="!notificationRows.length">
      <StateBlock kind="empty" title="暂无通知记录" message="当前筛选条件下没有发送记录。" />
    </div>
    <template v-else>
      <div class="table-wrap vtable" :style="{ maxHeight: `${VIEWPORT_HEIGHT + 40}px` }" @scroll.passive="notifVirt.onScroll">
        <table class="data-table vtable">
          <thead>
            <tr>
              <th style="width: 72px">ID</th>
              <th style="width: 92px">渠道</th>
              <th>接收方</th>
              <th>主题 / 模板</th>
              <th style="width: 96px">状态</th>
              <th class="num" style="width: 64px">尝试</th>
              <th style="width: 96px">送达</th>
              <th style="width: 100px">下次重试</th>
              <th>最后错误</th>
              <th style="width: 150px">创建时间</th>
              <th style="width: 130px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="notifVirt.range.value.paddingTop" class="vtable-spacer" :style="{ height: `${notifVirt.range.value.paddingTop}px` }"><td colspan="11" /></tr>
            <tr v-for="row in notifVirt.visibleRows.value" :key="row.id" class="vtable-row vtable-row--tall">
              <td class="mono">#{{ row.id }}</td>
              <td>{{ row.channel || '—' }}</td>
              <td>{{ row.recipient || '—' }}</td>
              <td>
                <div class="subject-line">
                  <span class="subject-name" :title="row.subject || row.template || ''">
                    {{ row.subject || row.template || '—' }}
                  </span>
                  <span v-if="row.subject && row.template" class="muted small subject-tpl" :title="row.template">
                    {{ row.template }}
                  </span>
                </div>
              </td>
              <td><StatusBadge :value="row.status" dot /></td>
              <td class="num">{{ row.attempts ?? '—' }}/{{ row.max_attempts ?? '—' }}</td>
              <td class="mono" style="font-size: 12px">{{ deliveryHint(row) }}</td>
              <td class="mono" style="font-size: 12px" :title="row.next_retry_at || ''">{{ retryHint(row.next_retry_at) }}</td>
              <td class="truncate" :title="row.last_error || ''">{{ row.last_error || '—' }}</td>
              <td class="muted cell-time">{{ formatTime(row.created_at) }}</td>
              <td><RowActions :actions="notifActions(row)" /></td>
            </tr>
            <tr v-if="notifVirt.range.value.paddingBottom" class="vtable-spacer" :style="{ height: `${notifVirt.range.value.paddingBottom}px` }"><td colspan="11" /></tr>
          </tbody>
        </table>
      </div>
      <Pager :page="notifPage" :page-size="notifPageSize" :total="notifTotal" :loading="notifLoading" @update:page="setNotifPage" />
    </template>
  </div>

  <Modal v-if="detailLoading || detailRow || detailError" title="投递详情"
    :subtitle="detailRow ? `#${detailRow.id} · ${detailRow.channel || '—'}` : undefined"
    size="wide" @close="detailRow = null; detailError = ''">
    <div v-if="detailLoading"><StateBlock kind="loading" title="正在加载投递详情…" /></div>
    <div v-else-if="detailError"><StateBlock kind="error" title="加载失败" :message="detailError" /></div>
    <template v-else-if="detailRow">
      <dl class="detail-grid">
        <div><dt>状态</dt><dd><StatusBadge :value="detailRow.status" dot /></dd></div>
        <div><dt>接收方</dt><dd class="mono">{{ detailRow.recipient || '—' }}</dd></div>
        <div><dt>主题 / 模板</dt><dd>{{ detailRow.subject || detailRow.template || '—' }}</dd></div>
        <div><dt>尝试次数</dt><dd class="mono">{{ detailRow.attempts ?? '—' }} / {{ detailRow.max_attempts ?? '—' }}</dd></div>
        <div><dt>创建时间</dt><dd>{{ formatTime(detailRow.created_at) }}</dd></div>
        <div><dt>发送时间</dt><dd>{{ formatTime(detailRow.sent_at) }}</dd></div>
        <div><dt>下次重试</dt><dd class="mono">{{ retryHint(detailRow.next_retry_at) }}</dd></div>
        <div><dt>Provider ID</dt><dd class="mono">{{ detailRow.provider_message_id || '—' }}</dd></div>
      </dl>
      <div v-if="detailRow.last_error" class="notice error">
        <div class="notice-body"><div class="notice-title">最后错误</div><div class="mono">{{ detailRow.last_error }}</div></div>
      </div>

      <h4 class="detail-section">逐订阅回执（{{ detailRow.meta.receipts?.length || 0 }}）</h4>
      <div v-if="!detailRow.meta.receipts?.length" class="muted">无回执记录（非 push 渠道或未发送）。</div>
      <table v-else class="data-table">
        <thead><tr><th>订阅 ID</th><th>状态</th><th>HTTP</th><th>建议退避</th><th>错误</th></tr></thead>
        <tbody>
          <tr v-for="(r, i) in detailRow.meta.receipts" :key="`${r.sub_id}-${i}`">
            <td class="mono">#{{ r.sub_id }}</td>
            <td><StatusBadge :value="r.status" dot /></td>
            <td class="mono">{{ r.http_status ?? '—' }}</td>
            <td class="mono">{{ r.retry_after_seconds != null ? `${r.retry_after_seconds}s` : '—' }}</td>
            <td class="truncate" :title="r.error || ''">{{ r.error || '—' }}</td>
          </tr>
        </tbody>
      </table>
      <div v-if="detailRow.meta.reason" class="muted small">
        原因：{{ detailRow.meta.reason }}
      </div>
    </template>
  </Modal>

  <!-- 批量发送 -->
  <Modal v-if="batchOpen" title="批量发送通知" subtitle="共享内容，逐账号独立投递"
    size="wide" @close="batchOpen = false">
    <form id="batch-notify-form" class="form-grid single-col" @submit.prevent="submitBatch">
      <div class="field">
        <label>账号 ID<span class="required">*</span></label>
        <textarea v-model="batchAccounts" rows="2" class="textarea mono" placeholder="逗号或空格分隔，最多 200 个，例如：12, 34, 56"></textarea>
        <span class="hint">填写一个或多个有效账号 ID，用逗号或空格分隔。</span>
      </div>
      <div class="field">
        <label>标题</label>
        <input v-model="batchTitle" class="input" type="text" maxlength="120" placeholder="通知标题" />
      </div>
      <div class="field">
        <label>正文</label>
        <textarea v-model="batchBody" rows="3" maxlength="2000" class="textarea" placeholder="通知正文"></textarea>
      </div>
      <div class="field">
        <label>发送渠道</label>
        <div class="check-row">
          <label v-for="ch in BATCH_CHANNELS" :key="ch.value" class="check-item">
            <input type="checkbox" :checked="batchChannels.includes(ch.value)"
              @change="toggleBatchChannel(ch.value)" />
            <span>{{ ch.label }}</span>
          </label>
        </div>
      </div>
      <div v-if="batchError" class="notice error">
        <div class="notice-body"><div class="notice-title">发送失败</div><div>{{ batchError }}</div></div>
      </div>
      <div v-if="batchResult" class="notice info">
        <div class="notice-body">
          <div class="notice-title">发送结果 · 批次 {{ batchResult.batch_id }}</div>
          <div>成功 {{ batchResult.sent }} / 总数 {{ batchResult.total }}，跳过 {{ batchResult.skipped }}</div>
          <div v-for="r in batchResult.results" :key="r.account_id" class="result-line">
            账号 #{{ r.account_id }}：{{ r.status }}<span v-if="r.detail"> · {{ r.detail }}</span>
          </div>
        </div>
      </div>
    </form>
    <template #footer>
      <button class="btn ghost" type="button" @click="batchOpen = false">关闭</button>
      <button class="btn" type="submit" form="batch-notify-form" :disabled="batchSubmitting || !batchChannels.length">
        {{ batchSubmitting ? '发送中…' : '确认发送' }}
      </button>
    </template>
  </Modal>

  <!-- 结构化回执历史 -->
  <Modal v-if="receiptLoading || receiptRow || receiptError" title="推送回执历史"
    :subtitle="receiptRow ? `#${receiptRow.delivery_id} · ${receiptRow.channel}` : undefined"
    size="wide" @close="receiptRow = null; receiptError = ''">
    <div v-if="receiptLoading"><StateBlock kind="loading" title="正在加载回执历史…" /></div>
    <div v-else-if="receiptError"><StateBlock kind="error" title="加载失败" :message="receiptError" /></div>
    <template v-else-if="receiptRow">
      <dl class="detail-grid">
        <div><dt>状态</dt><dd><StatusBadge :value="receiptRow.status" dot /></dd></div>
        <div><dt>订阅 / 送达</dt><dd class="mono">{{ receiptRow.delivered }}/{{ receiptRow.subscribers }}</dd></div>
        <div><dt>尝试次数</dt><dd class="mono">{{ receiptRow.attempts }}</dd></div>
        <div><dt>失效订阅</dt><dd class="mono">{{ receiptRow.expired.length }}</dd></div>
        <div><dt>建议退避</dt><dd class="mono">{{ receiptRow.retry_after_seconds != null ? `${receiptRow.retry_after_seconds}s` : '—' }}</dd></div>
        <div><dt>下次重试</dt><dd class="mono">{{ retryHint(receiptRow.next_retry_at) }}</dd></div>
      </dl>
      <div v-if="receiptRow.reason" class="notice info">
        <div class="notice-body"><div class="notice-title">处理说明</div><div>{{ receiptRow.reason }}</div></div>
      </div>
      <h4 class="detail-section">逐订阅回执（{{ receiptRow.receipts.length }}）</h4>
      <div v-if="!receiptRow.receipts.length" class="muted">无回执记录。</div>
      <table v-else class="data-table">
        <thead><tr><th>订阅 ID</th><th>状态</th><th>HTTP</th><th>建议退避</th><th>错误</th></tr></thead>
        <tbody>
          <tr v-for="(r, i) in receiptRow.receipts" :key="`${r.sub_id}-${i}`">
            <td class="mono">#{{ r.sub_id }}</td>
            <td><StatusBadge :value="r.status" dot /></td>
            <td class="mono">{{ r.http_status ?? '—' }}</td>
            <td class="mono">{{ r.retry_after_seconds != null ? `${r.retry_after_seconds}s` : '—' }}</td>
            <td class="truncate" :title="r.error || ''">{{ r.error || '—' }}</td>
          </tr>
        </tbody>
      </table>
    </template>
  </Modal>
</template>

<style scoped>
/* 主题与模板同排展示（虚拟滚动按固定行高计算，单元格内不能换行） */
.subject-line { display: flex; align-items: baseline; gap: 8px; min-width: 0; }
.subject-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.subject-tpl { flex: none; max-width: 50%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
