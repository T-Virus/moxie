<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import Icon from '../components/Icon.vue'
import { api } from '../api'
import type { UsageSummary, WritingStats } from '../api'
import { confirmBox, toast } from '../ui'

const usage = ref<UsageSummary | null>(null)
const writing = ref<WritingStats | null>(null)
const days = ref(30)
const loading = ref(true)
const tab = ref<'profile' | 'stage' | 'model' | 'book'>('profile')

async function load() {
  loading.value = true
  try {
    const [u, w] = await Promise.all([api.getUsage(days.value), api.getWritingStats()])
    usage.value = u
    writing.value = w
  } catch (e: any) {
    toast('统计载入失败：' + (e.message || e), 'err')
  } finally {
    loading.value = false
  }
}
onMounted(load)

async function clearAll() {
  if (!await confirmBox('清空全部统计？会同时清掉用量记录与码字统计，不影响正文与设置。',
    { danger: true, ok: '清空统计' })) return
  try {
    await api.clearUsage()
    toast('统计已清空', 'ok')
    await load()
  } catch (e: any) { toast(e.message, 'err') }
}

const fmtTok = (n: number) => n >= 1e6 ? (n / 1e6).toFixed(2) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'k' : String(n || 0)
const fmtCost = (n: number) => '¥' + (n || 0).toFixed(4).replace(/0+$/, '').replace(/\.$/, '.0')
const fmtSec = (s: number) => s >= 3600 ? (s / 3600).toFixed(1) + ' 小时' : s >= 60 ? (s / 60).toFixed(1) + ' 分钟' : (s || 0).toFixed(0) + ' 秒'

const dayRows = computed(() => {
  const d = usage.value?.by_day || {}
  const rows = Object.entries(d).map(([date, r]: [string, any]) => ({ date, ...r }))
  const max = Math.max(1, ...rows.map(r => r.prompt_tokens + r.completion_tokens))
  return { rows, max }
})
const weekMax = computed(() => Math.max(1, ...(writing.value?.week || []).map(w => w.chars)))
const goalPct = computed(() => {
  const w = writing.value
  if (!w || !w.goal) return 0
  return Math.min(100, Math.round((w.today / w.goal) * 100))
})

type Row = { name: string; calls: number; prompt_tokens: number; completion_tokens: number; elapsed: number; cost: number }
function toRows(rec: Record<string, any> | undefined): Row[] {
  return Object.entries(rec || {}).map(([name, r]) => ({ name, ...(r as any) }))
    .sort((a, b) => b.cost - a.cost || b.calls - a.calls)
}
const byProfile = computed(() => toRows(usage.value?.by_profile))
const byStage = computed(() => toRows(usage.value?.by_stage))
const byModel = computed(() => toRows(usage.value?.by_model))
const byBook = computed(() => toRows(usage.value?.by_book))
const totalCost = computed(() => usage.value?.cost.all || 0)
const activeRows = computed(() => {
  if (tab.value === 'stage') return byStage.value
  if (tab.value === 'model') return byModel.value
  if (tab.value === 'book') return byBook.value
  return byProfile.value
})
const TABS = [
  { key: 'profile', name: '档案' },
  { key: 'stage', name: '工序' },
  { key: 'model', name: '模型' },
  { key: 'book', name: '作品' },
] as const
</script>

<template>
  <div class="m-page m-secondary-page">
    <div class="m-sec-head">
      <div class="m-sec-head-txt">Token、耗时与成本，按档案 / 工序 / 模型 / 作品拆分</div>
      <div class="m-sec-head-act">
        <button class="m-icon-btn" title="刷新" @click="load"><Icon name="refresh" :size="18" /></button>
        <button class="m-icon-btn" title="清空统计" @click="clearAll"><Icon name="trash" :size="18" /></button>
      </div>
    </div>

    <div class="m-seg" style="margin-bottom:12px">
      <button v-for="d in [7, 30, 90]" :key="d" :class="{ on: days === d }" @click="days = d; load()">
        近 {{ d }} 天
      </button>
    </div>

    <div v-if="loading" class="m-empty" style="padding-top:50px">
      <span class="m-empty-ico"><Icon name="dashboard" :size="26" /></span>
      <b>正在统计</b>
      <p>汇总本机调用记录…</p>
    </div>

    <template v-else-if="usage">
      <!-- KPI -->
      <div class="m-kpi-grid">
        <div class="m-kpi teal">
          <div class="m-kpi-head">
            <span class="m-kpi-label">调用次数</span>
            <span class="m-kpi-ico"><Icon name="tasks" :size="14" /></span>
          </div>
          <b>{{ usage.total.calls }}</b>
          <small>近 {{ days }} 天</small>
        </div>
        <div class="m-kpi blue">
          <div class="m-kpi-head">
            <span class="m-kpi-label">Tokens</span>
            <span class="m-kpi-ico"><Icon name="file" :size="14" /></span>
          </div>
          <b>{{ fmtTok(usage.total.prompt_tokens) }}<i>/</i>{{ fmtTok(usage.total.completion_tokens) }}</b>
          <small>输入 / 输出</small>
        </div>
        <div class="m-kpi purple">
          <div class="m-kpi-head">
            <span class="m-kpi-label">累计耗时</span>
            <span class="m-kpi-ico"><Icon name="refresh" :size="14" /></span>
          </div>
          <b>{{ fmtSec(usage.total.elapsed) }}</b>
          <small>近 {{ days }} 天调用时间</small>
        </div>
        <div class="m-kpi gold">
          <div class="m-kpi-head">
            <span class="m-kpi-label">估算成本</span>
            <span class="m-kpi-ico"><Icon name="dashboard" :size="14" /></span>
          </div>
          <b class="money">{{ fmtCost(usage.cost.all) }}</b>
          <small>近 {{ days }} 天 · 按档案单价</small>
        </div>
      </div>
      <p v-if="usage.total.estimated" class="m-hint" style="padding:6px 4px 0">
        其中 {{ usage.total.estimated }} 次调用的 tokens 为估算值。
      </p>

      <!-- 码字目标 -->
      <div v-if="writing" class="m-card" style="margin-top:14px">
        <div class="m-card-head">
          <b>码字目标</b>
          <span v-if="writing.streak > 1" class="m-tag green">连续 {{ writing.streak }} 天</span>
          <span class="m-spacer"></span>
          <span class="m-sub">今日</span>
        </div>
        <div class="m-goal-line">
          <b>{{ writing.today }}</b>
          <span>/ {{ writing.goal || '未设目标' }} 字</span>
          <span class="m-goal-pct">{{ goalPct }}%</span>
        </div>
        <div class="m-goal-bar"><i :style="{ width: goalPct + '%' }"></i></div>
        <div class="m-week-bars">
          <div v-for="d in writing.week" :key="d.date" class="m-wb-col">
            <div class="m-wb-bar"><i :style="{ height: Math.max(3, Math.round(d.chars / weekMax * 52)) + 'px' }"></i></div>
            <span>{{ d.date.slice(5) }}</span>
          </div>
        </div>
      </div>

      <!-- 调用量曲线 -->
      <div class="m-card" style="margin-top:12px">
        <div class="m-card-head"><b>调用量</b><span class="m-sub">近 {{ days }} 天 · tokens</span></div>
        <div v-if="!dayRows.rows.length" class="m-hint" style="padding:14px 0">暂无记录</div>
        <div v-else class="m-day-bars">
          <div v-for="(d, i) in dayRows.rows" :key="d.date" class="m-db-col">
            <div class="m-db-bar">
              <i :style="{ height: Math.max(3, Math.round((d.prompt_tokens + d.completion_tokens) / dayRows.max * 74)) + 'px' }"></i>
            </div>
            <span v-if="i % 5 === 0 || i === dayRows.rows.length - 1">{{ d.date.slice(5) }}</span>
          </div>
        </div>
      </div>

      <!-- 拆分 -->
      <div class="m-sec-title" style="margin-top:18px">用量拆分</div>
      <div class="m-seg" style="margin-bottom:10px">
        <button v-for="t in TABS" :key="t.key" :class="{ on: tab === t.key }" @click="tab = t.key">
          {{ t.name }}
        </button>
      </div>

      <div v-if="activeRows.length" class="m-rows">
        <div v-for="r in activeRows" :key="r.name" class="m-usage-row">
          <div class="m-usage-top">
            <b>{{ r.name }}</b>
            <span>{{ fmtCost(r.cost) }}</span>
          </div>
          <div class="m-usage-bar">
            <i :style="{ width: (totalCost ? Math.max(2, r.cost / totalCost * 100) : 0) + '%' }"></i>
          </div>
          <div class="m-usage-meta">
            <span>{{ r.calls }} 次</span>
            <span>{{ fmtTok(r.prompt_tokens + r.completion_tokens) }} tokens</span>
            <span>{{ fmtSec(r.elapsed) }}</span>
          </div>
        </div>
      </div>
      <div v-else class="m-empty" style="padding:28px 0 12px">
        <b>暂无记录</b>
        <p>发起 AI 任务后，这里会按维度汇总。</p>
      </div>
    </template>
  </div>
</template>

<style scoped>
.m-kpi-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 9px; grid-auto-rows: 1fr; }
.m-kpi {
  position: relative; display: flex; flex-direction: column; gap: 4px;
  min-height: 104px; padding: 13px 14px; overflow: hidden;
  background: #fff; border: 1px solid var(--m-line); border-radius: 17px;
  box-shadow: 0 1px 2px rgba(20, 30, 27, .03);
  --tone: #0f766e; --tone-soft: #e7f4f1;
}
.m-kpi.teal { --tone: #0f766e; --tone-soft: #e7f4f1; }
.m-kpi.blue { --tone: #1c7ed6; --tone-soft: #e9f2fc; }
.m-kpi.purple { --tone: #7048e8; --tone-soft: #f0ecfd; }
.m-kpi.gold { --tone: #e8590c; --tone-soft: #fff2e8; }
.m-kpi::after {
  content: ''; position: absolute; right: -24px; top: -26px;
  width: 82px; height: 82px; border-radius: 50%;
  background: var(--tone); opacity: .06; pointer-events: none;
}
.m-kpi-head { display: flex; align-items: center; gap: 8px; }
.m-kpi-label { font-size: 10.5px; color: var(--m-text3); }
.m-kpi-ico {
  margin-left: auto; width: 24px; height: 24px; flex: none; border-radius: 8px;
  display: grid; place-items: center; background: var(--tone-soft); color: var(--tone);
}
.m-kpi b {
  margin-top: auto; font-size: 21px; font-weight: 750;
  letter-spacing: -.5px; line-height: 1.2;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.m-kpi b.money { color: var(--m-primary); }
.m-kpi b i { font-style: normal; color: var(--m-text3); font-weight: 400; margin: 0 2px; font-size: 16px; }
.m-kpi small { font-size: 9.5px; color: var(--m-text3); }
.m-goal-line { display: flex; align-items: baseline; gap: 5px; margin: 2px 0 9px; font-size: 12px; color: var(--m-text3); }
.m-goal-line b { font-size: 26px; font-weight: 750; color: var(--m-primary); letter-spacing: -.5px; }
.m-goal-pct { margin-left: auto; font-size: 11px; color: var(--m-primary); font-weight: 650; }
.m-goal-bar { height: 8px; border-radius: 5px; background: #eef0ec; overflow: hidden; }
.m-goal-bar i { display: block; height: 100%; border-radius: 5px; background: linear-gradient(90deg, #12847a, #16a394); }
.m-week-bars { display: flex; gap: 5px; align-items: flex-end; margin-top: 14px; }
.m-wb-col { flex: 1; text-align: center; }
.m-wb-bar { height: 54px; display: flex; align-items: flex-end; justify-content: center; }
.m-wb-bar i { display: block; width: 62%; background: var(--m-primary-soft); border-bottom: 2px solid var(--m-primary); border-radius: 4px 4px 0 0; }
.m-wb-col span { display: block; margin-top: 4px; font-size: 9px; color: var(--m-text3); }
.m-day-bars {
  display: flex; gap: 3px; align-items: flex-end;
  margin-top: 10px; padding: 0 1px 2px; overflow-x: auto;
}
.m-db-col { flex: 1 0 16px; min-width: 16px; max-width: 26px; text-align: center; }
.m-db-bar { height: 78px; display: flex; align-items: flex-end; justify-content: center; }
.m-db-bar i { display: block; width: 68%; border-radius: 3px 3px 0 0; background: linear-gradient(180deg, #23a394, #0f766e); opacity: .8; }
.m-db-col span { display: block; margin-top: 4px; font-size: 8px; color: var(--m-text3); white-space: nowrap; }
.m-usage-row {
  padding: 12px 14px; background: #fff;
  border: 1px solid var(--m-line); border-radius: 15px;
}
.m-usage-top { display: flex; align-items: baseline; gap: 8px; }
.m-usage-top b { flex: 1; min-width: 0; font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.m-usage-top span { font-size: 12px; font-weight: 650; color: var(--m-primary); }
.m-usage-bar { height: 5px; margin-top: 8px; border-radius: 3px; background: #eef0ec; overflow: hidden; }
.m-usage-bar i { display: block; height: 100%; border-radius: 3px; background: var(--m-primary); }
.m-usage-meta { display: flex; gap: 10px; margin-top: 7px; font-size: 10px; color: var(--m-text3); }
</style>
