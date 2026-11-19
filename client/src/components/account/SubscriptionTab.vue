<template>
  <div class="subtab">
    <div v-if="loading" class="empty">正在加载订阅信息…</div>
    <div v-else-if="error" class="account__error" role="alert">
      <span>{{ error }}</span>
      <button type="button" class="btn btn--sm" @click="load">重试</button>
    </div>
    <template v-else>
      <div class="subtab__status">
        <div class="subtab__status-main">
          <span class="subtab__label">当前订阅</span>
          <h3 class="subtab__name">
            {{ subscription ? subscription.plan.name : '未开通' }}
            <span v-if="subscription" class="badge badge--success">{{ statusText(subscription.status) }}</span>
            <span v-else class="badge">无生效套餐</span>
          </h3>
          <p v-if="subscription" class="subtab__meta">
            到期时间 {{ formatDate(subscription.current_end_at) }} · 剩余
            {{ Math.max(0, Math.round(subscription.days_left)) }} 天
            <template v-if="subscription.cancel_at_period_end"> · 到期后不续费</template>
          </p>
          <p v-else class="subtab__meta">订阅后可获得章节与 token 额度；当前降级为试用能力。</p>
        </div>
        <div class="subtab__status-side">
          <p class="subtab__period">
            账期 {{ formatDate(quota?.period_start) }} — {{ formatDate(quota?.period_end) }}
          </p>
          <p class="subtab__hint">额度按月重置，一次性额度包优先顺延</p>
        </div>
      </div>

      <RouterLink to="/plans" class="subtab__link">查看并购买套餐 →</RouterLink>

      <h3 class="subtab__title">本月额度</h3>
      <div v-if="quota && quota.metrics.length" class="subtab__quota">
        <div v-for="metric in quota.metrics" :key="metric.metric" class="subtab__metric">
          <div class="subtab__metric-head">
            <span class="subtab__metric-name">
              <template v-if="metric.metric === 'books_month'">
                本月可创作 {{ formatNumber(remaining(metric)) }} 本
              </template>
              <template v-else>{{ metricLabel(metric.metric) }}</template>
            </span>
            <span class="subtab__metric-value">
              <template v-if="metric.limit < 0">不限量</template>
              <template v-else-if="metric.metric === 'books_month'">共 {{ formatNumber(metric.limit) }} 本</template>
              <template v-else>
                {{ formatNumber(remaining(metric)) }} / {{ formatNumber(metric.limit) }} {{ unitLabel(metric.unit) }}
              </template>
            </span>
          </div>
          <div class="subtab__bar" aria-hidden="true">
            <span class="subtab__bar-used" :style="{ width: `${usedPercent(metric)}%` }" />
          </div>
          <p class="subtab__metric-meta">
            已用 {{ formatNumber(metric.used) }} · 预占 {{ formatNumber(metric.reserved) }}
            <span v-if="metric.pack_remaining"> · 额度包 {{ formatNumber(metric.pack_remaining) }}</span>
          </p>
        </div>
      </div>
      <div v-else class="empty">当前没有可用额度信息，可能是套餐未生效。</div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { fetchCurrentSubscription, fetchEntitlements, formatDate } from '@/services/billingApi'
import type { QuotaMetric, QuotaSummary, Subscription } from '@/types'

const loading = ref(false)
const error = ref('')
const subscription = ref<Subscription | null>(null)
const quota = ref<QuotaSummary | null>(null)

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const results = await Promise.allSettled([fetchCurrentSubscription(), fetchEntitlements()])
    if (results[0].status === 'fulfilled') subscription.value = results[0].value
    if (results[1].status === 'fulfilled') quota.value = results[1].value
    const failed = results.find((item) => item.status === 'rejected') as PromiseRejectedResult | undefined
    if (failed) error.value = '部分订阅数据加载失败，请重试'
  } catch {
    error.value = '订阅数据加载失败，请稍后重试'
  } finally {
    loading.value = false
  }
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
    call: '次', gb: 'GB', chapter: '章', count: '个', seat: '席', book: '本', char: '字',
  }
  return map[unit] || unit
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

onMounted(() => {
  void load()
})
</script>

<style scoped>
.subtab {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.subtab__status {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--color-border, var(--border, #e5e7eb));
}

.subtab__label {
  font-size: var(--text-xs);
  color: var(--color-text-3);
}

.subtab__name {
  font-size: 17px;
  font-weight: 600;
  color: var(--color-text);
  margin: 4px 0 6px;
}

.subtab__name .badge {
  vertical-align: middle;
  margin-left: 6px;
}

.subtab__meta,
.subtab__period,
.subtab__hint {
  font-size: var(--text-xs);
  color: var(--color-text-2);
  line-height: 1.6;
  margin: 0;
}

.subtab__status-side {
  text-align: right;
}

.subtab__link {
  align-self: flex-start;
  font-size: var(--text-sm);
  color: var(--color-brand);
  text-decoration: none;
}
.subtab__link:hover {
  text-decoration: underline;
}

.subtab__title {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--color-text);
  margin: 0;
}

.subtab__quota {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
}

.subtab__metric {
  padding: 14px;
  border: 1px solid var(--color-border, var(--border, #e5e7eb));
  border-radius: var(--radius-md, 8px);
}

.subtab__metric-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
}

.subtab__metric-name {
  font-size: var(--text-sm);
  color: var(--color-text);
}

.subtab__metric-value {
  font-size: var(--text-xs);
  color: var(--color-text-2);
  white-space: nowrap;
}

.subtab__bar {
  height: 6px;
  border-radius: 999px;
  background: var(--color-bg-soft, var(--surface-2, #fafafa));
  overflow: hidden;
}

.subtab__bar-used {
  display: block;
  height: 100%;
  background: var(--color-brand);
}

.subtab__metric-meta {
  font-size: var(--text-xs);
  color: var(--color-text-3);
  margin: 8px 0 0;
}

.empty {
  padding: 20px;
  text-align: center;
  color: var(--color-text-3);
  font-size: var(--text-sm);
}
</style>
