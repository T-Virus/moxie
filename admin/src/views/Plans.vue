<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api, errorMessage } from '../api'
import { can } from '../roles'
import { getRole } from '../session'
import { pushToast } from '../toast'
import { formatMoney } from '../ui'
import Icon from '../components/Icon.vue'
import Modal from '../components/Modal.vue'
import PageHeader from '../components/PageHeader.vue'
import RowActions from '../components/RowActions.vue'
import StateBlock from '../components/StateBlock.vue'
import UiSelect from '../components/UiSelect.vue'
import type { AdminPlanRow, PlanUpdatePayload } from '../types'

const role = getRole()
const canWrite = computed(() => can(role, 'subscriptions:write'))

const ENTITLEMENT_LABELS: Record<string, string> = {
  books_month: '书籍 / 月',
  adapt_chapters: '改编章数 / 月',
  review_month: '体检次数 / 月',
  concurrency: '并发任务数',
  seats: '席位数',
  managed_chars: '托管字数 / 月',
  storage_gb: '存储空间（GB）',
}

function entitlementLabel(key: string): string {
  return ENTITLEMENT_LABELS[key] || key
}

const plans = ref<AdminPlanRow[]>([])
const loading = ref(false)
const error = ref('')

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const data = await api.adminPlans()
    plans.value = Array.isArray(data.plans) ? data.plans : []
  } catch (e) {
    plans.value = []
    error.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)

function entitlementSummary(plan: AdminPlanRow): string {
  if (!plan.entitlements?.length) return '—'
  return plan.entitlements.map((item) => `${entitlementLabel(item.key)} ${item.limit}`).join(' · ')
}

/* ---- 编辑 ---------------------------------------------------------------- */
const editOpen = ref(false)
const editing = ref<AdminPlanRow | null>(null)
const saving = ref(false)
const saveError = ref('')

const form = reactive({
  name: '',
  monthYuan: '',
  yearYuan: '',
  active: true,
  limits: {} as Record<string, number>,
})

function centsToYuan(cents: number): string {
  return (cents / 100).toFixed(2)
}

function openEdit(plan: AdminPlanRow): void {
  editing.value = plan
  form.name = plan.name
  form.monthYuan = centsToYuan(plan.price_month_cents)
  form.yearYuan = centsToYuan(plan.price_year_cents)
  form.active = plan.active
  form.limits = Object.fromEntries(
    (plan.entitlements || []).map((item) => [item.key, item.limit]),
  )
  saveError.value = ''
  editOpen.value = true
}

function closeEdit(): void {
  editing.value = null
  editOpen.value = false
}

/** 元 → 分；非法或负数返回 null，避免把错误价格写进数据库。 */
function yuanToCents(value: string): number | null {
  if (String(value).trim() === '') return null
  const num = Number(value)
  if (!Number.isFinite(num) || num < 0) return null
  return Math.round(num * 100)
}

async function save(): Promise<void> {
  if (!editing.value) return
  const name = form.name.trim()
  if (!name) {
    saveError.value = '套餐名称不能为空'
    return
  }
  const month = yuanToCents(form.monthYuan)
  const year = yuanToCents(form.yearYuan)
  if (month === null) {
    saveError.value = '月付价格必须是不小于 0 的数字（单位：元）'
    return
  }
  if (year === null) {
    saveError.value = '年付价格必须是不小于 0 的数字（单位：元）'
    return
  }
  const limits: Record<string, number> = {}
  for (const [key, value] of Object.entries(form.limits)) {
    const limit = Number(value)
    if (!Number.isInteger(limit) || limit < -1) {
      saveError.value = `${entitlementLabel(key)} 的上限必须是 -1（不限）或非负整数`
      return
    }
    limits[key] = limit
  }

  const payload: PlanUpdatePayload = {
    name,
    price_month_cents: month,
    price_year_cents: year,
    active: form.active,
    entitlements: limits,
  }
  saving.value = true
  saveError.value = ''
  try {
    const updated = await api.updatePlan(editing.value.code, payload)
    plans.value = plans.value.map((item) => (item.code === updated.code ? updated : item))
    pushToast('套餐已更新')
    closeEdit()
  } catch (e) {
    saveError.value = errorMessage(e)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <PageHeader
    title="套餐管理"
    desc="调整对外售卖的套餐名称、价格、上下架与权益上限；保存后立即影响用户端套餐页与下单金额。"
  >
    <button class="btn ghost" :disabled="loading" @click="load">
      <Icon name="refresh" :size="14" />{{ loading ? '加载中…' : '刷新' }}
    </button>
  </PageHeader>

  <div v-if="!canWrite" class="notice info">
    <div class="notice-body">
      <div class="notice-title">只读模式</div>
      <div>当前角色可查看套餐配置，修改价格与上下架需要管理员（admin）权限。</div>
    </div>
  </div>

  <div v-if="loading" class="card state-card">
    <StateBlock kind="loading" title="正在加载套餐…" />
  </div>
  <div v-else-if="error" class="card state-card">
    <StateBlock kind="error" :message="error" retry-label="重新加载" @retry="load" />
  </div>

  <div v-else class="card">
    <div class="table-wrap">
      <table class="data-table">
        <thead>
          <tr>
            <th style="width: 190px">套餐</th>
            <th>月付</th>
            <th>年付</th>
            <th style="width: 96px">状态</th>
            <th>权益上限</th>
            <th style="width: 96px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="plan in plans" :key="plan.code">
            <td>
              <div class="plan-name">{{ plan.name }}</div>
              <div class="muted small mono">{{ plan.code }}</div>
            </td>
            <td class="cell-time">{{ formatMoney(plan.price_month_cents, plan.currency) }}</td>
            <td class="cell-time">
              {{ plan.price_year_cents > 0 ? formatMoney(plan.price_year_cents, plan.currency) : '—' }}
            </td>
            <td>
              <span class="badge" :class="plan.active ? 'ok' : 'muted'">{{ plan.status }}</span>
            </td>
            <td>
              <div class="truncate" :title="entitlementSummary(plan)">{{ entitlementSummary(plan) }}</div>
            </td>
            <td>
              <RowActions v-if="canWrite" :actions="[{ label: '编辑', run: () => openEdit(plan) }]" />
              <span v-else class="muted">只读</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <Modal
    v-if="editOpen && editing"
    title="编辑套餐"
    :subtitle="`${editing.name} · ${editing.code}`"
    @close="closeEdit"
  >
    <div class="form-grid">
      <label class="field">
        <span>套餐名称</span>
        <input v-model="form.name" class="input" maxlength="120" />
      </label>
      <label class="field">
        <span>上架状态</span>
        <UiSelect
          v-model="form.active"
          :options="[
            { value: true, label: '上架' },
            { value: false, label: '已下架' },
          ]"
        />
      </label>
      <label class="field">
        <span>月付（元）</span>
        <input v-model="form.monthYuan" class="input" type="number" min="0" step="0.01" />
        <small>0 表示免费套餐，下单后直接生效</small>
      </label>
      <label class="field">
        <span>年付（元）</span>
        <input v-model="form.yearYuan" class="input" type="number" min="0" step="0.01" />
        <small>0 表示不提供年付</small>
      </label>
    </div>

    <div class="section-title">权益上限</div>
    <div class="form-grid cols-2">
      <label v-for="item in editing.entitlements" :key="item.key" class="field">
        <span>{{ entitlementLabel(item.key) }}<em class="limit-unit">{{ item.unit }}</em></span>
        <input v-model.number="form.limits[item.key]" class="input" type="number" min="-1" step="1" />
        <small>{{ item.key }} · -1 表示不限</small>
      </label>
    </div>

    <div v-if="saveError" class="notice error">{{ saveError }}</div>

    <template #footer>
      <button class="btn ghost sm" :disabled="saving" @click="closeEdit">取消</button>
      <button class="btn sm" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
    </template>
  </Modal>
</template>

<style scoped>
.state-card {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 220px;
}
.plan-name {
  font-weight: 600;
}
.limit-unit {
  margin-left: 6px;
  font-style: normal;
  font-weight: 400;
  color: var(--text-3);
}
</style>
