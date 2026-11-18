<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api, errorMessage } from '../api'
import { pushToast } from '../toast'
import type { ModelUsageSummary } from '../types'
import { formatNumber, formatTime } from '../ui'
import PageHeader from '../components/PageHeader.vue'
import StateBlock from '../components/StateBlock.vue'

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

const maxCost = computed(() => Math.max(1, ...(summary.value?.items || []).map((row) => row.cost_cents)))
const yuan = (cents: number): string => `¥${(cents / 100).toFixed(2)}`

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

function barWidth(cost: number): string {
  return `${Math.max(2, (cost / maxCost.value) * 100)}%`
}

onMounted(load)
</script>

<template>
  <div>
    <PageHeader
      title="模型消费统计"
      desc="统一汇总服务端所有模型调用：Agent 写作、网关代理、拆书与改编任务。按模型 / 供应商 / 账户 / 日期查看 token 与成本，避免跨平台查日志对账。"
    >
      <button class="btn" :disabled="loading" @click="load">刷新统计</button>
    </PageHeader>

    <div class="card filters">
      <label class="field">
        <span>统计周期</span>
        <select v-model.number="filters.days">
          <option :value="7">近 7 天</option>
          <option :value="30">近 30 天</option>
          <option :value="90">近 90 天</option>
          <option :value="366">近一年</option>
        </select>
      </label>
      <label class="field">
        <span>聚合维度</span>
        <select v-model="filters.group_by">
          <option v-for="option in GROUP_OPTIONS" :key="option.value" :value="option.value">{{ option.label }}</option>
        </select>
      </label>
      <label class="field">
        <span>供应商</span>
        <input v-model="filters.provider" type="text" placeholder="如 DeepSeek / OpenAI" @keyup.enter="load" />
      </label>
      <label class="field">
        <span>模型</span>
        <input v-model="filters.model" type="text" placeholder="如 deepseek-chat" @keyup.enter="load" />
      </label>
      <label class="field">
        <span>调用渠道</span>
        <input v-model="filters.route" type="text" placeholder="managed / byok / stub" @keyup.enter="load" />
      </label>
      <button class="btn ghost apply" @click="load">应用筛选</button>
    </div>

    <div v-if="loading" class="card"><StateBlock kind="loading" title="汇总消费数据…" /></div>
    <div v-else-if="error" class="card"><StateBlock kind="error" :message="error" /></div>
    <template v-else-if="summary">
      <div class="cards">
        <div class="card metric">
          <span>Token 总量</span>
          <strong>{{ formatNumber(summary.total_tokens) }}</strong>
        </div>
        <div class="card metric">
          <span>成本合计</span>
          <strong class="cost">{{ yuan(summary.total_cost_cents) }}</strong>
        </div>
        <div class="card metric">
          <span>计费事件</span>
          <strong>{{ formatNumber(summary.total_calls) }}</strong>
        </div>
        <div class="card metric">
          <span>统计说明</span>
          <strong class="small">扫描 {{ formatNumber(summary.scanned_rows) }} 条{{ summary.truncated ? '（已截断）' : '' }}</strong>
        </div>
      </div>

      <div class="card table-card">
        <div class="table-head">
          <h2>消费明细</h2>
          <span class="muted small">生成时间 {{ formatTime(summary.generated_at) }}</span>
        </div>
        <table class="table">
          <thead>
            <tr>
              <th>{{ GROUP_OPTIONS.find((o) => o.value === summary?.group_by)?.label || '维度' }}</th>
              <th>供应商</th>
              <th>Token</th>
              <th>成本</th>
              <th>占比</th>
              <th>计费事件</th>
              <th>账户数</th>
              <th>模型数</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in summary.items" :key="row.key">
              <td class="mono">{{ row.label }}</td>
              <td>{{ row.provider || '—' }}</td>
              <td>{{ formatNumber(row.tokens) }}</td>
              <td class="cost">{{ yuan(row.cost_cents) }}</td>
              <td>
                <div class="bar"><span :style="{ width: barWidth(row.cost_cents) }" /></div>
              </td>
              <td>{{ formatNumber(row.calls) }}</td>
              <td>{{ row.account_count }}</td>
              <td>{{ row.model_count }}</td>
            </tr>
            <tr v-if="!summary.items.length">
              <td colspan="8" class="muted center">当前筛选条件下暂无消费记录</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>

<style scoped>
.filters { display: grid; grid-template-columns: repeat(5, minmax(140px, 1fr)) auto; gap: 12px; align-items: end; }
.filters .apply { margin-bottom: 1px; }
.cards { display: grid; grid-template-columns: repeat(4, minmax(160px, 1fr)); gap: 12px; margin: 14px 0; }
.metric { display: grid; gap: 6px; }
.metric span { color: var(--muted, #6b7280); font-size: 12px; }
.metric strong { font-size: 22px; }
.metric strong.cost, td.cost { color: var(--red, #d92d20); font-weight: 600; }
.metric .small { font-size: 13px; font-weight: 400; }
.table-card { overflow-x: auto; }
.table-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.table-head h2 { font-size: 15px; margin: 0; }
.table { width: 100%; border-collapse: collapse; }
.table th, .table td { padding: 9px 12px; border-bottom: 1px solid var(--line, #e5e8ee); text-align: left; white-space: nowrap; }
.table th { font-size: 12px; color: var(--muted, #6b7280); font-weight: 600; }
.bar { width: 90px; height: 6px; border-radius: 999px; background: var(--border, #e5e8ee); overflow: hidden; }
.bar span { display: block; height: 100%; background: var(--primary, #4f8ef7); }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
.small { font-size: 12px; }
.center { text-align: center; padding: 24px 0; }
</style>
