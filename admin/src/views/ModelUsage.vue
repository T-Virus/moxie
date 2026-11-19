<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api, errorMessage } from '../api'
import { pushToast } from '../toast'
import type { ModelUsageSummary } from '../types'
import { formatNumber, formatTime } from '../ui'
import Icon from '../components/Icon.vue'
import PageHeader from '../components/PageHeader.vue'
import StateBlock from '../components/StateBlock.vue'
import UiSelect from '../components/UiSelect.vue'

const loading = ref(true)
const error = ref('')
const summary = ref<ModelUsageSummary | null>(null)
const filters = reactive({ days: 30, group_by: 'model', provider: '', model: '', route: '' })

const GROUP_OPTIONS = [
  { value: 'model', label: '按模型' },
  { value: 'provider', label: '按供应商' },
  { value: 'account', label: '按账户' },
  { value: 'day', label: '按日期' },
]

const yuan = (cents: number): string => `¥${(cents / 100).toFixed(2)}`

function share(cents: number): number {
  const total = summary.value?.total_cost_cents || 0
  return total > 0 ? (cents / total) * 100 : 0
}

function shareText(cents: number): string {
  const value = share(cents)
  return `${value >= 0.1 ? value.toFixed(1) : value.toFixed(2)}%`
}

function barWidth(cents: number): string {
  return `${Math.max(2, share(cents))}%`
}

const groupLabel = computed(
  () => GROUP_OPTIONS.find((o) => o.value === summary.value?.group_by)?.label || '维度',
)

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    summary.value = await api.modelUsage({
      days: filters.days,
      group_by: filters.group_by,
      provider: filters.provider.trim(),
      model: filters.model.trim(),
      route: filters.route.trim(),
    })
  } catch (e) {
    error.value = errorMessage(e)
    pushToast(errorMessage(e), 'error')
  } finally {
    loading.value = false
  }
}

function resetFilters(): void {
  filters.days = 30
  filters.group_by = 'model'
  filters.provider = ''
  filters.model = ''
  filters.route = ''
  void load()
}

onMounted(load)
</script>

<template>
  <div class="usage-page">
    <PageHeader
      title="模型消费统计"
      desc="统一汇总服务端所有模型调用：Agent 写作、网关代理、拆书与改编任务。按模型 / 供应商 / 账户 / 日期查看 token 与成本，避免跨平台查日志对账。"
    >
      <button class="btn" :disabled="loading" @click="load">
        <Icon name="refresh" :size="14" />{{ loading ? '统计中…' : '刷新统计' }}
      </button>
    </PageHeader>

    <div class="card filter-card">
      <div class="filter-grid">
        <label class="field">
          <span>统计周期</span>
          <UiSelect
            v-model="filters.days"
            :options="[
              { value: 7, label: '近 7 天' },
              { value: 30, label: '近 30 天' },
              { value: 90, label: '近 90 天' },
              { value: 366, label: '近一年' },
            ]"
          />
        </label>
        <label class="field">
          <span>聚合维度</span>
          <UiSelect v-model="filters.group_by" :options="GROUP_OPTIONS" />
        </label>
        <label class="field">
          <span>供应商</span>
          <input v-model="filters.provider" class="input" type="text" placeholder="如 DeepSeek / OpenAI" @keyup.enter="load" />
        </label>
        <label class="field">
          <span>模型</span>
          <input v-model="filters.model" class="input" type="text" placeholder="如 deepseek-chat" @keyup.enter="load" />
        </label>
        <label class="field">
          <span>调用渠道</span>
          <input v-model="filters.route" class="input" type="text" placeholder="managed / byok / stub" @keyup.enter="load" />
        </label>
      </div>
      <div class="filter-actions">
        <button class="btn ghost" @click="resetFilters">重置</button>
        <button class="btn" :disabled="loading" @click="load">应用筛选</button>
      </div>
    </div>

    <div v-if="loading" class="card"><StateBlock kind="loading" title="汇总消费数据…" /></div>
    <div v-else-if="error" class="card"><StateBlock kind="error" :message="error" /></div>
    <template v-else-if="summary">
      <div class="stat-grid usage-stats">
        <div class="stat-card teal">
          <div class="stat-top"><span class="stat-label">Token 总量</span><span class="stat-ico"><Icon name="model-usage" :size="16" /></span></div>
          <div class="stat-value">{{ formatNumber(summary.total_tokens) }}</div>
          <div class="stat-desc">统计周期内累计消耗</div>
        </div>
        <div class="stat-card red">
          <div class="stat-top"><span class="stat-label">成本合计</span><span class="stat-ico"><Icon name="orders" :size="16" /></span></div>
          <div class="stat-value">{{ yuan(summary.total_cost_cents) }}</div>
          <div class="stat-desc">按调用计费汇总</div>
        </div>
        <div class="stat-card purple">
          <div class="stat-top"><span class="stat-label">计费事件</span><span class="stat-ico"><Icon name="tasks" :size="16" /></span></div>
          <div class="stat-value">{{ formatNumber(summary.total_calls) }}</div>
          <div class="stat-desc">成功计入成本次数</div>
        </div>
        <div class="stat-card orange">
          <div class="stat-top"><span class="stat-label">扫描记录</span><span class="stat-ico"><Icon name="audit" :size="16" /></span></div>
          <div class="stat-value">{{ formatNumber(summary.scanned_rows) }}</div>
          <div class="stat-desc">{{ summary.truncated ? '数据已截断' : '完整覆盖所选周期' }}</div>
        </div>
      </div>

      <div class="card table-card usage-table-card">
        <div class="card-head">
          <div class="card-title">消费明细<span class="sub">按{{ groupLabel }}聚合</span></div>
          <div class="spacer"></div>
          <span class="muted small">生成时间 {{ formatTime(summary.generated_at) }}</span>
        </div>
        <div class="table-wrap usage-table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>{{ groupLabel }}</th>
                <th>供应商</th>
                <th class="num">Token</th>
                <th class="num">成本</th>
                <th style="min-width: 150px">占比</th>
                <th class="num">计费事件</th>
                <th class="num">账户数</th>
                <th class="num">模型数</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in summary.items" :key="row.key">
                <td>{{ row.label }}</td>
                <td>{{ row.provider || '—' }}</td>
                <td class="num mono">{{ formatNumber(row.tokens) }}</td>
                <td class="num mono cost">{{ yuan(row.cost_cents) }}</td>
                <td>
                  <div class="share-cell">
                    <span class="meter"><i :style="{ width: barWidth(row.cost_cents) }" /></span>
                    <span class="share-value mono">{{ shareText(row.cost_cents) }}</span>
                  </div>
                </td>
                <td class="num mono">{{ formatNumber(row.calls) }}</td>
                <td class="num mono">{{ row.account_count }}</td>
                <td class="num mono">{{ row.model_count }}</td>
              </tr>
              <tr v-if="!summary.items.length" class="empty-row">
                <td colspan="8">当前筛选条件下暂无消费记录</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.usage-page { display: flex; flex-direction: column; gap: 14px; flex: 1; min-height: 0; }

.filter-card { display: flex; align-items: flex-end; gap: 16px; flex: none; }
.filter-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; flex: 1; min-width: 0; }
.filter-actions { display: flex; gap: 8px; flex: none; padding-bottom: 1px; }
@media (max-width: 1100px) {
  .filter-card { flex-direction: column; align-items: stretch; }
  .filter-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .filter-actions { justify-content: flex-end; }
}

.usage-stats { flex: none; }
.stat-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.stat-ico { width: 28px; height: 28px; border-radius: 8px; display: inline-flex; align-items: center; justify-content: center; background: rgba(0,0,0,.04); }
.stat-card.teal .stat-ico { color: var(--primary); background: var(--primary-bg); }
.stat-card.red .stat-ico { color: var(--red); background: var(--red-bg); }
.stat-card.purple .stat-ico { color: var(--purple); background: var(--purple-bg); }
.stat-card.orange .stat-ico { color: var(--orange); background: var(--orange-bg); }
.stat-card .stat-value { color: var(--text); }
.stat-card.red .stat-value { color: var(--red); }

.usage-table-card { flex: 1 1 auto; display: flex; flex-direction: column; min-height: 0; }
.usage-table-wrap { flex: 1 1 auto; min-height: 0; }
.share-cell { display: flex; align-items: center; gap: 8px; }
.share-cell .meter { width: 90px; flex: none; }
.share-value { font-size: 11.5px; color: var(--text-2); white-space: nowrap; }
.data-table .cost { color: var(--red); font-weight: 600; }
</style>
