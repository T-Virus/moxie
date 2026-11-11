<template>
  <main class="page plans">
    <div class="page-head">
      <h1 class="page-title">套餐与订阅</h1>
      <p class="page-sub">未登录也能查看全部套餐与权益；登录后可管理订阅与本月额度。</p>
    </div>

    <section v-if="session.account" class="plans__section">
      <div v-if="accountLoading" class="empty">正在加载订阅信息…</div>
      <div v-else-if="accountError" class="card plans__error" role="alert">
        <span>{{ accountError }}</span>
        <button type="button" class="btn btn--sm" @click="loadAccount">重试</button>
      </div>
      <template v-else>
        <div class="card plans__status">
          <div class="plans__status-main">
            <span class="plans__status-label">当前订阅</span>
            <h2 class="plans__status-name">
              {{ subscription ? subscription.plan.name : '未开通' }}
              <span v-if="subscription" class="badge badge--success">{{ statusText(subscription.status) }}</span>
              <span v-else class="badge">无生效套餐</span>
            </h2>
            <p v-if="subscription" class="plans__status-meta">
              到期时间 {{ formatDate(subscription.current_end_at) }} · 剩余
              {{ Math.max(0, Math.round(subscription.days_left)) }} 天
              <template v-if="subscription.cancel_at_period_end"> · 到期后不续费</template>
            </p>
            <p v-else class="plans__status-meta">
              订阅后可获得章节与 token 额度；当前降级为试用能力。
            </p>
          </div>
          <div class="plans__status-side">
            <p class="plans__period">
              账期 {{ formatDate(quota?.period_start) }} — {{ formatDate(quota?.period_end) }}
            </p>
            <p class="muted plans__hint">额度按月重置，一次性额度包优先顺延</p>
          </div>
        </div>

        <h2 class="plans__title plans__section-title">本月额度</h2>
        <div v-if="quota && quota.metrics.length" class="plans__quota">
          <div v-for="metric in quota.metrics" :key="metric.metric" class="card quota">
            <div class="quota__head">
              <span class="quota__name">
                <template v-if="metric.metric === 'books_month'">
                  本月可创作 {{ formatNumber(remaining(metric)) }} 本
                </template>
                <template v-else>{{ metricLabel(metric.metric) }}</template>
              </span>
              <span class="quota__value">
                <template v-if="metric.limit < 0">不限量</template>
                <template v-else-if="metric.metric === 'books_month'">
                  共 {{ formatNumber(metric.limit) }} 本
                </template>
                <template v-else>
                  {{ formatNumber(remaining(metric)) }} / {{ formatNumber(metric.limit) }}
                  {{ unitLabel(metric.unit) }}
                </template>
              </span>
            </div>
            <div class="quota__bar" aria-hidden="true">
              <span class="quota__used" :style="{ width: `${usedPercent(metric)}%` }" />
            </div>
            <p class="quota__meta">
              已用 {{ formatNumber(metric.used) }} · 预占 {{ formatNumber(metric.reserved) }}
              <span v-if="metric.pack_remaining"> · 额度包 {{ formatNumber(metric.pack_remaining) }}</span>
            </p>
          </div>
        </div>
        <div v-else class="empty">当前没有可用额度信息，可能是套餐未生效。</div>
      </template>
    </section>

    <section v-else class="plans__section">
      <div class="card plans__guest">
        <h2 class="plans__guest-title">登录后可查看你的订阅与额度</h2>
        <div class="plans__guest-actions">
          <RouterLink :to="{ name: 'login', query: { next: '/plans' } }" class="btn">登录</RouterLink>
          <RouterLink
            :to="{ name: 'login', query: { next: '/plans', tab: 'register' } }"
            class="btn btn--brand"
          >
            注册
          </RouterLink>
        </div>
      </div>
    </section>

    <section class="plans__section">
      <div class="plans__section-head">
        <h2 class="plans__title">可选套餐</h2>
        <div v-if="providers.length" class="plans__providers" role="group" aria-label="支付方式">
          <span class="plans__providers-label">支付方式</span>
          <button
            v-for="item in providers"
            :key="item.id"
            type="button"
            class="provider-chip"
            :class="{ 'is-on': provider === item.id }"
            :aria-pressed="provider === item.id"
            @click="provider = item.id"
          >
            {{ item.name }}
          </button>
        </div>
      </div>
      <p v-if="providersLoaded && !providers.length" class="plans__provider-hint" role="status">
        当前环境未开通在线支付渠道，暂时无法下单；请联系管理员或稍后再试。
      </p>
      <div v-if="plansLoading" class="empty">正在加载套餐…</div>
      <div v-else-if="plansError" class="card plans__error" role="alert">
        <span>{{ plansError }}</span>
        <button type="button" class="btn btn--sm" @click="loadPlans">重试</button>
      </div>
      <div v-else class="plans__grid">
        <article
          v-for="plan in plans"
          :key="plan.code"
          :data-plan="plan.code"
          class="card plan"
          :class="{
            'is-current': isCurrent(plan),
            'is-selected': selectedCode === plan.code && !isCurrent(plan),
          }"
        >
          <div class="plan__head">
            <h3 class="plan__name">{{ plan.name }}</h3>
            <div class="plan__badges">
              <span v-if="isCurrent(plan)" class="badge badge--brand">当前套餐</span>
              <span v-if="plan.recommended ?? plan.code === 'creator'" class="badge badge--violet">推荐</span>
              <span v-if="plan.best_value ?? plan.code === 'professional'" class="badge badge--success">最划算</span>
            </div>
          </div>
          <p class="plan__desc">{{ planDesc(plan) }}</p>
          <p class="plan__price">
            <strong>{{ formatMoney(plan.price_month_cents, plan.currency) }}</strong>
            <span>/ 月</span>
          </p>
          <p v-if="plan.price_year_cents > 0" class="plan__year">
            {{ formatMoney(plan.price_year_cents, plan.currency) }}/年（≈{{
              formatMoney(Math.round(plan.price_year_cents / 12), plan.currency)
            }}/月）
          </p>
          <ul v-if="planFeatures(plan).length" class="plan__features">
            <li v-for="feature in planFeatures(plan)" :key="feature">{{ feature }}</li>
          </ul>
          <ul v-if="planEntitlements(plan).length" class="plan__quota">
            <li v-for="item in planEntitlements(plan)" :key="item.key">
              <span>{{ entitlementText(item) }}</span>
            </li>
          </ul>
          <button
            type="button"
            class="btn plan__buy"
            :class="{ 'btn--brand': !isCurrent(plan) }"
            :disabled="isCurrent(plan) || buyingCode === plan.code || !provider"
            @click="buy(plan)"
          >
            {{ isCurrent(plan) ? '使用中' : buyingCode === plan.code ? '处理中…' : '立即购买' }}
          </button>
        </article>
      </div>
    </section>

    <Teleport to="body">
      <Transition name="toast">
        <div v-if="toastText" class="toast" role="alert">
          <span class="toast__text">{{ toastText }}</span>
          <button type="button" class="toast__close" aria-label="关闭提示" @click="closeToast">
            <svg viewBox="0 0 12 12" aria-hidden="true">
              <path d="M3 3l6 6M9 3l-6 6" fill="none" stroke="currentColor" stroke-width="1.4" />
            </svg>
          </button>
        </div>
      </Transition>
    </Teleport>
  </main>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { Plan, PlanEntitlement, QuotaMetric, QuotaSummary, Subscription } from '@/types'
import {
  fetchPlans,
  fetchCurrentSubscription,
  fetchEntitlements,
  fetchPaymentProviders,
  formatMoney,
  formatDate,
  subscribePlan,
} from '@/services/billingApi'
import { ApiError } from '@/services/http'
import { session } from '@/stores/session'
import type { PaymentProviderOption } from '@/types'

const PLAN_INTENT_KEY = 'mx_plan_intent'
/** 在售三档：体验 → 创作 → 专业；接口返回的工作室版等已下架套餐一律过滤 */
const ALLOWED_PLAN_CODES = ['experience', 'creator', 'professional']
const ALLOWED_PLAN_NAMES = ['体验版', '创作版', '专业版']

function normalizePlans(list: Plan[]): Plan[] {
  const seen = new Set<string>()
  return list
    .filter(
      (plan) =>
        ALLOWED_PLAN_CODES.includes(plan.code) || ALLOWED_PLAN_NAMES.includes(plan.name),
    )
    .filter((plan) => {
      if (seen.has(plan.code)) return false
      seen.add(plan.code)
      return true
    })
    .sort((a, b) => a.price_month_cents - b.price_month_cents)
}

const route = useRoute()
const router = useRouter()

const plansLoading = ref(false)
const plansError = ref('')
const plans = ref<Plan[]>([])
const selectedCode = ref('')
const buyingCode = ref('')
/** 支付渠道由服务端按环境过滤，客户端不硬编码 mock */
const providers = ref<PaymentProviderOption[]>([])
const providersLoaded = ref(false)
const provider = ref('')

const accountLoading = ref(false)
const accountError = ref('')
const subscription = ref<Subscription | null>(null)
const quota = ref<QuotaSummary | null>(null)

const toastText = ref('')
let toastTimer: ReturnType<typeof setTimeout> | null = null

function showToast(message: string): void {
  if (!message) return
  toastText.value = message
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => {
    toastText.value = ''
    toastTimer = null
  }, 6000)
}

function closeToast(): void {
  toastText.value = ''
  if (toastTimer) {
    clearTimeout(toastTimer)
    toastTimer = null
  }
}

function readIntent(): string {
  const fromQuery = route.query.plan
  if (typeof fromQuery === 'string' && fromQuery) return fromQuery
  try {
    const raw = sessionStorage.getItem(PLAN_INTENT_KEY)
    const parsed = raw ? (JSON.parse(raw) as { planId?: string }) : null
    return parsed?.planId || ''
  } catch {
    return ''
  }
}

function rememberIntent(planId: string): void {
  sessionStorage.setItem(PLAN_INTENT_KEY, JSON.stringify({ planId, at: Date.now() }))
}

function isCurrent(plan: Plan): boolean {
  return subscription.value?.plan.code === plan.code
}

function statusText(status: string): string {
  const map: Record<string, string> = {
    active: '生效中',
    trialing: '试用中',
    past_due: '已逾期',
    canceled: '已取消',
    expired: '已过期',
    paused: '已暂停',
  }
  return map[status] || status
}

function metricLabel(key: string): string {
  const map: Record<string, string> = {
    books_month: '本月可创作',
    adapt_chapters: '可改编章节',
    managed_chars: '可托管字符',
    review_month: '本月审查次数',
    concurrency: '并发任务',
    chapters: '章节额度',
    tokens: '模型 token',
    seats: '协作席位',
    storage_gb: '存储空间',
  }
  return map[key] || key
}

function unitLabel(unit: string): string {
  const map: Record<string, string> = {
    call: '次',
    gb: 'GB',
    chapter: '章',
    count: '个',
    seat: '席',
    book: '本',
    char: '字',
  }
  return map[unit] || unit
}

function planDesc(plan: Plan): string {
  if (plan.description) return plan.description
  const map: Record<string, string> = {
    experience: '先跑通一本书的完整流程，适合初次尝试',
    creator: '适合稳定日更的个人创作者，兼顾产量与成本',
    professional: '适合多书并行的全职作者，重视设定一致性与质量校验',
  }
  return map[plan.code] || '按需选择的创作方案'
}

const ENTITLEMENT_ORDER = [
  'books_month',
  'adapt_chapters',
  'managed_chars',
  'review_month',
  'concurrency',
  'seats',
  'storage_gb',
]

/** 额度矩阵转成中文可读条目：每月 1 本书 / 可改编 20 章 / 可托管 50,000 字 / 1 个并发任务 */
function entitlementText(item: PlanEntitlement): string {
  const n = item.limit < 0 ? '不限' : formatNumber(item.limit)
  const map: Record<string, string> = {
    books_month: `每月 ${n} 本书`,
    adapt_chapters: `可改编 ${n} 章`,
    managed_chars: `可托管 ${n} 字`,
    review_month: `每月 ${n} 次审查`,
    concurrency: `${n} 个并发任务`,
    chapters: `每月 ${n} 章额度`,
    tokens: `每月 ${n} token`,
    seats: `${n} 个协作席位`,
    storage_gb: `${n} GB 存储空间`,
  }
  return map[item.key] || ''
}

/** 已由 features 字典展示的额度不再重复列出 */
function planEntitlements(plan: Plan): PlanEntitlement[] {
  const featureKeys = Array.isArray(plan.features) ? [] : Object.keys(plan.features)
  return plan.entitlements
    .filter((item) => !featureKeys.includes(item.key))
    .sort((a, b) => {
      const ai = ENTITLEMENT_ORDER.indexOf(a.key)
      const bi = ENTITLEMENT_ORDER.indexOf(b.key)
      return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi)
    })
}

/** 服务端 plan.features 是字典（books_month/adapt_chapters/byok/support…），转成中文条目。 */
function planFeatures(plan: Plan): string[] {
  const features = plan.features
  if (Array.isArray(features)) {
    return features.filter(
      (item) =>
        item &&
        !['支持自带密钥（BYOK）', '平台托管模型', '优先技术支持'].includes(item),
    )
  }
  return Object.entries(features)
    .map(([key, value]) => featureText(key, value))
    .filter((text): text is string => Boolean(text))
}

function featureText(key: string, value: string | boolean | number): string {
  // BYOK / 平台托管 / 优先技术支持不对外展示
  if (key === 'byok' || key === 'managed') return ''
  if (key === 'support') {
    if (value === 'priority') return ''
    if (value === 'community') return ''
    if (value === 'none') return ''
    return String(value)
  }
  const n = typeof value === 'number' ? formatNumber(value) : String(value)
  const map: Record<string, string> = {
    books_month: `每月 ${n} 本书`,
    adapt_chapters: `可改编 ${n} 章`,
    managed_chars: `可托管 ${n} 字`,
    review_month: `每月 ${n} 次审查`,
    concurrency: `支持 ${n} 个并发任务`,
    chapters: `每月 ${n} 章生成额度`,
    tokens: `每月 ${n} token`,
    seats: `${n} 个协作席位`,
    storage_gb: `${n} GB 存储空间`,
  }
  return map[key] || ''
}

function formatNumber(value: number): string {
  return value.toLocaleString('zh-CN')
}

function remaining(metric: QuotaMetric): number {
  if (metric.limit < 0) return 0
  return Math.max(0, metric.limit - metric.used - metric.reserved)
}

function usedPercent(metric: QuotaMetric): number {
  if (metric.limit <= 0) return 0
  return Math.min(100, Math.round(((metric.used + metric.reserved) / metric.limit) * 100))
}

function errorText(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401) return '登录状态已失效，请重新登录'
    if (err.status === 0) return '无法连接服务端，请检查网络后重试'
    return err.message
  }
  return '请求失败，请稍后重试'
}

async function revealSelected(): Promise<void> {
  if (!session.account || !selectedCode.value) return
  const plan = plans.value.find((item) => item.code === selectedCode.value)
  if (!plan) return
  await nextTick()
  document
    .querySelector(`[data-plan="${selectedCode.value}"]`)
    ?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  showToast(`已为你保留「${plan.name}」套餐，可继续购买`)
}

async function loadProviders(): Promise<void> {
  try {
    const items = await fetchPaymentProviders()
    providers.value = items
    if (!items.some((item) => item.id === provider.value)) {
      provider.value = items[0]?.id || ''
    }
  } catch {
    providers.value = []
    provider.value = ''
  } finally {
    providersLoaded.value = true
  }
}

async function loadPlans(): Promise<void> {
  plansLoading.value = true
  plansError.value = ''
  try {
    const list = normalizePlans(await fetchPlans())
    if (!list.length) throw new Error('暂无可售套餐')
    plans.value = list
    await revealSelected()
  } catch (err) {
    plans.value = []
    plansError.value =
      err instanceof ApiError ? err.message : '套餐加载失败，请检查网络后重试'
  } finally {
    plansLoading.value = false
  }
}

async function loadAccount(): Promise<void> {
  accountLoading.value = true
  accountError.value = ''
  try {
    const [subResult, quotaResult] = await Promise.allSettled([
      fetchCurrentSubscription(),
      fetchEntitlements(),
    ])
    if (subResult.status === 'fulfilled') subscription.value = subResult.value
    if (quotaResult.status === 'fulfilled') quota.value = quotaResult.value

    const failures = [subResult, quotaResult].filter((item) => item.status === 'rejected')
    if (failures.length) {
      const reason = (failures[0] as PromiseRejectedResult).reason
      accountError.value =
        reason instanceof ApiError ? reason.message : '订阅数据加载失败，请稍后重试'
      showToast(errorText(reason))
    }
  } finally {
    accountLoading.value = false
  }
}

async function buy(plan: Plan): Promise<void> {
  if (buyingCode.value || isCurrent(plan)) return

  if (!session.account) {
    rememberIntent(plan.code)
    selectedCode.value = plan.code
    await router.push({ name: 'login', query: { next: `/plans?plan=${plan.code}` } })
    return
  }

  if (!provider.value) {
    showToast('当前没有可用的支付渠道，请稍后再试')
    return
  }

  buyingCode.value = plan.code
  try {
    const result = await subscribePlan(plan.code, 'month', provider.value)
    subscription.value = result.subscription
    selectedCode.value = plan.code
    sessionStorage.removeItem(PLAN_INTENT_KEY)
    showToast(
      result.payment
        ? `已创建「${plan.name}」订单，请完成支付`
        : `已开通「${plan.name}」月付，额度将在下次刷新后更新`,
    )
  } catch (err) {
    showToast(errorText(err))
  } finally {
    buyingCode.value = ''
  }
}

onMounted(() => {
  selectedCode.value = readIntent()
  void loadProviders()
  void loadPlans()
  if (session.account) void loadAccount()
})

onBeforeUnmount(() => {
  if (toastTimer) clearTimeout(toastTimer)
})
</script>

<style scoped>
.plans__guest {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-5) var(--space-6);
}

.plans__guest-title {
  font-size: var(--text-md);
  font-weight: 600;
}

.plans__guest-actions {
  display: flex;
  gap: 8px;
  flex: none;
}

.plans__error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-5);
  color: var(--color-text-2);
  font-size: var(--text-sm);
}

.plans__section {
  margin-top: var(--space-8);
}

.plans__section-title {
  margin: var(--space-6) 0 0;
}

.plans__title {
  font-size: var(--text-md);
  font-weight: 700;
  margin-bottom: var(--space-4);
}

.plans__section-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.plans__section-head .plans__title {
  margin-bottom: 0;
}

.plans__providers {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.plans__providers-label {
  margin-right: 4px;
  font-size: var(--text-xs);
  color: var(--color-text-3);
}

.provider-chip {
  height: 30px;
  padding: 0 12px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--color-border, rgba(255, 255, 255, 0.16));
  background: transparent;
  color: var(--color-text-2);
  font-size: var(--text-xs);
  transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
}

.provider-chip:hover {
  color: #fff;
}

.provider-chip.is-on {
  border-color: var(--color-brand);
  background: color-mix(in srgb, var(--color-brand) 14%, transparent);
  color: var(--color-brand);
  font-weight: 600;
}

.plans__provider-hint {
  margin-bottom: var(--space-4);
  color: var(--color-text-3);
  font-size: var(--text-sm);
}

.plans__status {
  display: flex;
  justify-content: space-between;
  gap: var(--space-6);
  padding: var(--space-6);
}

.plans__status-label {
  font-size: var(--text-xs);
  color: var(--color-text-3);
  letter-spacing: 0.06em;
}

.plans__status-name {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--text-lg);
  margin-top: 4px;
}

.plans__status-meta {
  margin-top: 6px;
  font-size: var(--text-sm);
  color: var(--color-text-2);
}

.plans__status-side {
  text-align: right;
}

.plans__period {
  font-size: var(--text-sm);
  color: var(--color-text-2);
}

.plans__hint {
  font-size: var(--text-xs);
  margin-top: 4px;
}

.plans__quota {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
}

.quota {
  padding: 16px 18px;
}

.quota__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}

.quota__name {
  font-size: var(--text-sm);
  font-weight: 600;
}

.quota__value {
  font-size: var(--text-sm);
  color: var(--color-text-2);
  font-family: var(--font-mono);
}

.quota__bar {
  height: 6px;
  border-radius: var(--radius-pill);
  background: var(--color-bg-soft);
  margin: 12px 0 8px;
  overflow: hidden;
}

.quota__used {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--color-brand), #2dd4bf);
}

.quota__meta {
  font-size: var(--text-xs);
  color: var(--color-text-3);
}

.plans__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: var(--space-4);
}

.plan {
  padding: var(--space-5);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.plan.is-current {
  border-color: #b7e4df;
  box-shadow: 0 0 0 3px rgba(13, 148, 136, 0.08);
}

.plan.is-selected {
  border-color: var(--color-brand);
  box-shadow: 0 0 0 3px rgba(13, 148, 136, 0.12);
}

.plan__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}

.plan__name {
  font-size: var(--text-md);
  font-weight: 700;
}

.plan__badges {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.plan__desc {
  font-size: var(--text-xs);
  color: var(--color-text-3);
}

.plan__price {
  margin-top: var(--space-2);
  color: var(--color-text-2);
  font-size: var(--text-sm);
}

.plan__price strong {
  font-size: var(--text-xl);
  color: var(--color-text);
  font-weight: 700;
}

.plan__year {
  font-size: var(--text-xs);
  color: var(--color-text-3);
}

.plan__features {
  margin-top: var(--space-3);
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: var(--text-sm);
  color: var(--color-text-2);
}

.plan__features li::before {
  content: '·';
  color: var(--color-brand);
  margin-right: 6px;
  font-weight: 700;
}

.plan__quota {
  margin-top: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px dashed var(--color-line);
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: var(--text-xs);
  color: var(--color-text-3);
}

.plan__quota li {
  display: flex;
  justify-content: space-between;
}

.plan__buy {
  margin-top: auto;
}

.toast {
  position: fixed;
  left: 50%;
  bottom: 24px;
  z-index: 100;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  width: max-content;
  max-width: min(440px, calc(100vw - 32px));
  padding: 12px 12px 12px 16px;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  background: rgba(13, 24, 35, 0.96);
  color: #e8f1f8;
  font-size: var(--text-sm);
  line-height: 1.6;
  box-shadow: var(--shadow-lg);
  transform: translateX(-50%);
}

.toast__text {
  flex: 1;
  min-width: 0;
}

.toast__close {
  flex: none;
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  margin-top: 1px;
  border-radius: 50%;
  color: rgba(232, 241, 248, 0.7);
}

.toast__close:hover {
  background: rgba(255, 255, 255, 0.14);
  color: #fff;
}

.toast__close svg {
  width: 10px;
  height: 10px;
}

.toast-enter-active,
.toast-leave-active {
  transition: opacity var(--dur-fast) var(--ease), transform var(--dur-fast) var(--ease);
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translate(-50%, 8px);
}

@media (max-width: 640px) {
  .plans__guest,
  .plans__status {
    flex-direction: column;
    align-items: flex-start;
  }

  .plans__guest-actions {
    width: 100%;
  }

  .plans__guest-actions .btn {
    flex: 1;
  }

  .plans__status-side {
    text-align: left;
  }

  .plans__title {
    margin-top: var(--space-2);
  }
}
</style>
