<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errorMessage, normalizeList } from '../api'
import { can } from '../roles'
import { getRole } from '../session'
import { pushToast } from '../toast'
import type { AuditRow, PlanRow, SubscriptionRow } from '../types'
import {
  accountIdOf, accountLabel, compactJson, formatNumber, formatTime, planLabel, toDateInput,
} from '../ui'
import Icon from '../components/Icon.vue'
import Modal from '../components/Modal.vue'
import PageHeader from '../components/PageHeader.vue'
import Pager from '../components/Pager.vue'
import RowActions, { type RowAction } from '../components/RowActions.vue'
import StateBlock from '../components/StateBlock.vue'
import StatusBadge from '../components/StatusBadge.vue'
import UiSegmented from '../components/UiSegmented.vue'
import UiSelect from '../components/UiSelect.vue'
import UiDate from '../components/UiDate.vue'

const role = getRole()
const canAdjust = computed(() => can(role, 'subscriptions:write'))
const canQuota = computed(() => can(role, 'quota:write'))

const METRICS = [
  { key: 'books_month', label: '每月拆解书籍数', unit: '本' },
  { key: 'adapt_chapters', label: '每月改编章节数', unit: '章' },
  { key: 'review_month', label: '每月审校次数', unit: '次' },
  { key: 'concurrency', label: '并发任务数', unit: '个' },
  { key: 'seats', label: '席位数', unit: '席' },
  { key: 'managed_chars', label: '托管字数', unit: '字' },
  { key: 'storage_gb', label: '存储空间', unit: 'GB' },
  { key: 'custom', label: '自定义指标', unit: '' },
]

const q = ref('')
const status = ref('')
const page = ref(1)
const pageSize = 30
const rows = ref<SubscriptionRow[]>([])
const total = ref<number | null>(null)
const loading = ref(false)
const error = ref('')
const plans = ref<PlanRow[]>([])

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await api.subscriptions({ q: q.value.trim(), status: status.value, page: page.value, page_size: pageSize })
    const list = normalizeList<SubscriptionRow>(data)
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

async function loadPlans() {
  try {
    const data = await api.plans()
    plans.value = data.plans || []
  } catch {
    plans.value = []
  }
}

function search() {
  page.value = 1
  void load()
}

function setPage(next: number) {
  page.value = next
  void load()
}

onMounted(() => {
  void load()
  void loadPlans()
})

const modalOpen = ref(false)
const modalTab = ref<'subscription' | 'quota'>('subscription')
const targetRow = ref<SubscriptionRow | null>(null)
const submitting = ref(false)
const actionError = ref('')

const planCode = ref('')
const endAt = ref('')
const adjustNote = ref('')

const metric = ref('books_month')
const customMetric = ref('')
const quantity = ref('')
const quotaReason = ref('')

const auditRows = ref<AuditRow[]>([])
const auditLoading = ref(false)
const auditError = ref('')

const targetAccountId = computed(() => accountIdOf(targetRow.value))
const metricUnit = computed(() => METRICS.find(item => item.key === metric.value)?.unit || '')

function openModal(row: SubscriptionRow, tab: 'subscription' | 'quota') {
  targetRow.value = row
  modalTab.value = tab
  actionError.value = ''
  auditRows.value = []
  auditError.value = ''
  planCode.value = row.plan_code || (row.plan && typeof row.plan === 'object' ? row.plan.code || '' : '') || ''
  endAt.value = toDateInput(row.current_end_at)
  adjustNote.value = ''
  metric.value = 'books_month'
  customMetric.value = ''
  quantity.value = ''
  quotaReason.value = ''
  modalOpen.value = true
}

async function loadAudits(accountId: number, keyword: 'quota' | 'subscription') {
  auditLoading.value = true
  auditError.value = ''
  auditRows.value = []
  try {
    const query: Record<string, unknown> = { page: 1, page_size: 20 }
    if (keyword === 'quota') {
      Object.assign(query, { target_type: 'account', target_id: String(accountId), action: 'quota.adjust' })
    } else {
      const subId = targetRow.value?.id
      Object.assign(query, { target_type: 'subscription', target_id: subId ? String(subId) : undefined })
    }
    const data = await api.auditLogs(query)
    auditRows.value = normalizeList<AuditRow>(data).items
  } catch (e) {
    auditError.value = errorMessage(e)
  } finally {
    auditLoading.value = false
  }
}

async function submitSubscription() {
  if (!targetRow.value) return
  if (adjustNote.value.trim().length < 2) {
    actionError.value = '请填写调整原因（至少 2 个字），提交后会展示审计记录'
    return
  }
  submitting.value = true
  actionError.value = ''
  try {
    await api.adjustSubscription(targetRow.value.id, {
      plan_code: planCode.value || undefined,
      current_end_at: endAt.value ? `${endAt.value}T00:00:00+08:00` : undefined,
      note: adjustNote.value.trim(),
    })
    pushToast('订阅已调整，正在加载审计记录')
    await load()
    const accountId = targetAccountId.value
    await loadAudits(accountId ?? 0, 'subscription')
  } catch (e) {
    actionError.value = errorMessage(e)
  } finally {
    submitting.value = false
  }
}

async function submitQuota() {
  if (!targetRow.value) return
  const accountId = targetAccountId.value
  if (!accountId) {
    actionError.value = '无法从该订阅记录确定账号 ID'
    return
  }
  const metricKey = metric.value === 'custom' ? customMetric.value.trim() : metric.value
  if (!metricKey) {
    actionError.value = '请选择或填写额度指标'
    return
  }
  const value = Number(quantity.value)
  if (!Number.isFinite(value) || value === 0) {
    actionError.value = '调整数量必须为非零数字（可为负数）'
    return
  }
  if (!Number.isInteger(value)) {
    actionError.value = '调整数量必须为整数'
    return
  }
  if (quotaReason.value.trim().length < 2) {
    actionError.value = '请填写调整原因（至少 2 个字）'
    return
  }
  submitting.value = true
  actionError.value = ''
  try {
    await api.quotaAdjust(accountId, {
      metric: metricKey,
      quantity: value,
      reason: quotaReason.value.trim(),
    })
    pushToast('额度已调整，正在加载审计记录')
    await load()
    await loadAudits(accountId, 'quota')
  } catch (e) {
    actionError.value = errorMessage(e)
  } finally {
    submitting.value = false
  }
}

function auditDetail(row: AuditRow): string {
  return compactJson(row.meta)
}

function subscriptionActions(row: SubscriptionRow): RowAction[] {
  const actions: RowAction[] = []
  if (canAdjust.value) actions.push({ label: '调整订阅', run: () => openModal(row, 'subscription') })
  if (canQuota.value) actions.push({ label: '额度调整', run: () => openModal(row, 'quota') })
  return actions
}
</script>

<template>
  <PageHeader title="订阅与权益" desc="查看订阅状态与到期时间，调整套餐、续期时间或手工增减额度。所有调整必须填写原因并可在审计日志追溯。">
    <span v-if="!canAdjust && !canQuota" class="badge muted">support 只读</span>
    <button class="btn ghost sm" :disabled="loading" @click="load">
      <Icon name="refresh" :size="14" />刷新
    </button>
  </PageHeader>

  <div v-if="!canAdjust && !canQuota" class="notice info">
    <div class="notice-body">
      <div class="notice-title">只读模式</div>
      <div>当前角色可查看订阅与权益，但套餐调整、续期与额度手工调整需要管理员（admin）权限。</div>
    </div>
  </div>

  <div class="card">
    <form class="toolbar" @submit.prevent="search">
      <div class="tb-group tb-search">
        <input v-model="q" class="input" placeholder="搜索账号 / 套餐 / 订阅 ID" />
      </div>
      <UiSelect
        v-model="status"
        class="tb-select"
        variant="toolbar"
        placeholder="全部状态"
        :options="[
          { value: 'active', label: '有效' },
          { value: 'trialing', label: '试用中' },
          { value: 'past_due', label: '已逾期' },
          { value: 'canceled', label: '已取消' },
          { value: 'expired', label: '已过期' },
        ]"
        @change="search"
      />
      <button class="btn sm" type="submit" :disabled="loading">查询</button>
      <div class="spacer"></div>
      <span class="muted" style="font-size: 12px">共 {{ total === null ? '—' : formatNumber(total) }} 条订阅</span>
    </form>

    <div v-if="loading && !rows.length">
      <StateBlock kind="loading" title="正在加载订阅…" />
    </div>
    <div v-else-if="error">
      <StateBlock kind="error" title="订阅列表加载失败" :message="error" retry-label="重试" @retry="load" />
    </div>
    <div v-else-if="!rows.length">
      <StateBlock kind="empty" title="暂无订阅记录" message="当前筛选条件下没有订阅数据。" />
    </div>
    <template v-else>
      <div class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th style="width: 72px">ID</th>
              <th>账号</th>
              <th>套餐</th>
              <th style="width: 94px">状态</th>
              <th>当前周期</th>
              <th style="width: 76px">剩余天数</th>
              <th style="width: 64px">席位</th>
              <th style="width: 96px">渠道</th>
              <th style="width: 170px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.id">
              <td class="mono">#{{ row.id }}</td>
              <td>
                <div class="truncate" :title="`${accountLabel(row)} · 账号 #${accountIdOf(row) ?? '—'}`">
                  {{ accountLabel(row) }} · 账号 #{{ accountIdOf(row) ?? '—' }}
                </div>
              </td>
              <td>{{ planLabel(row) }}</td>
              <td><StatusBadge :value="row.status" dot /></td>
              <td class="muted period-cell">
                {{ formatTime(row.current_start_at) }} 至 {{ formatTime(row.current_end_at) }}
              </td>
              <td class="num">{{ row.days_left ?? '—' }}</td>
              <td class="num">{{ row.seats ?? '—' }}</td>
              <td class="muted">{{ row.provider || '—' }}</td>
              <td>
                <RowActions v-if="canAdjust || canQuota" :actions="subscriptionActions(row)" />
                <span v-else class="muted">只读</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <Pager :page="page" :page-size="pageSize" :total="total" :loading="loading" @update:page="setPage" />
    </template>
  </div>

  <Modal v-if="modalOpen" :title="modalTab === 'subscription' ? '调整订阅与权益' : '手工调整额度'"
    :subtitle="targetRow ? `#${targetRow.id} · ${accountLabel(targetRow)} · 账号 #${targetAccountId ?? '—'}` : ''"
    @close="modalOpen = false">
    <UiSegmented
      v-model="modalTab"
      size="md"
      :options="[
        { value: 'subscription', label: '套餐 / 到期时间' },
        { value: 'quota', label: '额度调整' },
      ]"
    />

    <form v-if="modalTab === 'subscription'" id="sub-adjust-form" class="form-grid" @submit.prevent="submitSubscription">
      <div class="field">
        <label>套餐</label>
        <UiSelect
          v-model="planCode"
          placeholder="保持不变"
          :options="plans.map(plan => ({ value: plan.code, label: plan.name || plan.code }))"
        />
        <span class="hint">候选来自 GET /v1/plans；也可保持不变只调整到期时间。</span>
      </div>
      <div class="field">
        <label>到期时间</label>
        <UiDate v-model="endAt" placeholder="选择到期日期" />
        <span class="hint">提交为带时区的 ISO 8601（+08:00）。</span>
      </div>
      <div class="field span-2">
        <label>调整原因<span class="required">*</span></label>
        <textarea v-model="adjustNote" class="textarea" placeholder="例如：客服补偿 7 天有效期 / 升级到专业版"></textarea>
        <span class="hint">原因会写入审计日志，提交成功后在本弹窗下方展示审计记录。</span>
      </div>
      <div v-if="actionError" class="notice error span-2">{{ actionError }}</div>
    </form>

    <form v-else id="quota-adjust-form" class="form-grid" @submit.prevent="submitQuota">
      <div class="field">
        <label>额度指标<span class="required">*</span></label>
        <UiSelect
          v-model="metric"
          :options="METRICS.map(item => ({ value: item.key, label: `${item.label}（${item.key}）` }))"
        />
      </div>
      <div class="field">
        <label>{{ metric === 'custom' ? '自定义指标键' : '调整数量' }}<span class="required">*</span></label>
        <input v-if="metric === 'custom'" v-model="customMetric" class="input" placeholder="例如 books_month" />
        <input v-else v-model="quantity" class="input" type="number" step="1" placeholder="正数增加，负数扣减" />
        <span class="hint">{{ metric === 'custom' ? '自定义指标需与服务端 entitlements key 一致。' : `单位：${metricUnit || '—'}，填写整数，可为负数扣减。` }}</span>
      </div>
      <div v-if="metric === 'custom'" class="field">
        <label>调整数量<span class="required">*</span></label>
        <input v-model="quantity" class="input" type="number" step="1" placeholder="正数增加，负数扣减" />
      </div>
      <div class="field" :class="{ 'span-2': metric !== 'custom' }">
        <label>调整原因<span class="required">*</span></label>
        <textarea v-model="quotaReason" class="textarea" placeholder="例如：补偿误扣的 20 章节额度"></textarea>
      </div>
      <div v-if="actionError" class="notice error span-2">{{ actionError }}</div>
    </form>

    <div class="section-sub">最近审计记录</div>
    <div v-if="auditLoading"><StateBlock kind="loading" title="正在加载审计记录…" /></div>
    <StateBlock v-else-if="auditError" kind="error" title="审计记录加载失败" :message="auditError" />
    <div v-else-if="auditRows.length" class="table-wrap">
      <table class="data-table">
        <thead><tr><th style="width: 150px">时间</th><th>操作</th><th>对象</th><th>明细</th></tr></thead>
        <tbody>
          <tr v-for="item in auditRows" :key="item.id">
            <td class="muted cell-time">{{ formatTime(item.created_at) }}</td>
            <td class="mono">{{ item.action }}</td>
            <td class="mono">
              {{ item.target_type || '—' }}<template v-if="item.target_id"> #{{ item.target_id }}</template>
            </td>
            <td class="mono" style="max-width: 320px; word-break: break-word">{{ auditDetail(item) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <StateBlock v-else kind="empty" title="暂无审计记录" message="提交调整后，这里会展示该账号最近的额度 / 订阅审计记录。" />

    <template #footer>
      <button class="btn ghost" type="button" @click="modalOpen = false">关闭</button>
      <button
        class="btn"
        type="submit"
        :form="modalTab === 'subscription' ? 'sub-adjust-form' : 'quota-adjust-form'"
        :disabled="submitting"
      >{{ submitting ? '提交中…' : (modalTab === 'subscription' ? '提交调整' : '提交额度调整') }}</button>
    </template>
  </Modal>
</template>

<style scoped>
/* 当前周期：起止时间同行展示，列宽足够时不折行 */
.period-cell { white-space: nowrap; }
</style>
