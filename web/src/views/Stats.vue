<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import Icon from '../components/Icon.vue'
import SelectBox from '../components/SelectBox.vue'
import { api } from '../api'
import type { UsageSummary, WritingStats } from '../api'
import { toast, confirmBox } from '../ui'

const usage = ref<UsageSummary | null>(null)
const writing = ref<WritingStats | null>(null)
const days = ref(30)
const loading = ref(true)

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
  if (!await confirmBox(
    '清空全部统计？\n会同时清掉「模型调用用量」和「码字统计」，不影响正文与设置。',
    { danger: true, ok: '清空统计' })) return
  try {
    const r: any = await api.clearUsage()
    const okAll = r?.usage !== false && r?.writing !== false
    toast(okAll ? '统计已清空' : '部分统计文件正被占用，请稍后再试', okAll ? 'ok' : 'err')
    await load()
  } catch (e: any) { toast(e.message, 'err') }
}

const fmtTok = (n: number) => n >= 1e6 ? (n / 1e6).toFixed(2) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'k' : String(n || 0)
const fmtCost = (n: number) => '¥' + (n || 0).toFixed(4).replace(/0+$/, '').replace(/\.$/, '.0')
const fmtSec = (s: number) => s >= 3600 ? (s / 3600).toFixed(1) + ' 小时'
  : s >= 60 ? (s / 60).toFixed(1) + ' 分钟' : (s || 0).toFixed(0) + ' 秒'

/* 近 N 天调用量柱图（纯 CSS，无依赖） */
const dayRows = computed(() => {
  const d = usage.value?.by_day || {}
  const rows = Object.entries(d).map(([date, r]: [string, any]) => ({ date, ...r }))
  const max = Math.max(1, ...rows.map(r => r.prompt_tokens + r.completion_tokens))
  return { rows, max }
})
const weekMax = computed(() => Math.max(1, ...(writing.value?.week || []).map(w => w.chars)))
const pct = computed(() => {
  const w = writing.value
  if (!w || !w.goal) return 0
  return Math.min(100, Math.round((w.today / w.goal) * 100))
})

const metrics = computed(() => {
  const t = usage.value?.total
  const calls = t?.calls || 0
  const toks = (t?.prompt_tokens || 0) + (t?.completion_tokens || 0)
  const cost = usage.value?.cost.all || 0
  return [
    { key: 'calls', icon: 'tasks', tone: 'teal', label: '调用次数',
      value: String(calls), sub: `近 ${days.value} 天` },
    { key: 'tokens', icon: 'file', tone: 'blue', label: '输入 / 输出 tokens',
      value: `${fmtTok(t?.prompt_tokens || 0)} / ${fmtTok(t?.completion_tokens || 0)}`,
      sub: `合计 ${fmtTok(toks)}` },
    { key: 'time', icon: 'refresh', tone: 'purple', label: '累计耗时',
      value: fmtSec(t?.elapsed || 0), sub: calls ? `平均 ${fmtSec((t?.elapsed || 0) / calls)} / 次` : '—' },
    { key: 'cost', icon: 'dashboard', tone: 'gold', label: '估算成本',
      value: fmtCost(cost), sub: calls ? `平均 ${fmtCost(cost / calls)} / 次` : '—' },
  ]
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

/* 相对最大值的条宽：占比条不按总成本算时，小项也看得见 */
function barW(rows: Row[], cost: number) {
  const max = Math.max(1e-9, ...rows.map(r => r.cost))
  return Math.max(2, Math.round((cost / max) * 100))
}
function share(cost: number) {
  if (!totalCost.value) return 0
  return Math.round((cost / totalCost.value) * 100)
}

const groups = computed(() => [
  { key: 'stage', title: '按工序', icon: 'settings', rows: byStage.value },
  { key: 'model', title: '按模型', icon: 'graph', rows: byModel.value },
  { key: 'book', title: '按作品', icon: 'book', rows: byBook.value },
])
</script>

<template>
  <div class="st">
    <div class="st-head">
      <div class="st-title">
        <h2>用量与成本</h2>
        <p>近 {{ days }} 天的 Token、耗时与费用，按模型档案 / 工序 / 作品拆分</p>
      </div>
      <div class="st-tools">
        <div style="width:132px">
          <SelectBox :model-value="String(days)" :search-from="99"
                     :options="[{label:'近 7 天',value:'7'},{label:'近 30 天',value:'30'},{label:'近 90 天',value:'90'}]"
                     @update:model-value="v => { days = Number(v) || 30; load() }" />
        </div>
        <button class="btn ghost" @click="load"><Icon name="refresh" :size="14" /> 刷新</button>
        <button class="btn ghost st-clear" @click="clearAll"><Icon name="trash" :size="14" /> 清空统计</button>
      </div>
    </div>

    <div v-if="loading" class="st-loading">正在汇总用量记录…</div>

    <template v-else-if="usage">
      <!-- 指标卡 -->
      <div class="st-tiles">
        <div v-for="m in metrics" :key="m.key" class="st-tile" :class="m.tone">
          <div class="st-tile-head">
            <span class="st-tile-label">{{ m.label }}</span>
            <span class="st-tile-ico"><Icon :name="m.icon" :size="15" /></span>
          </div>
          <b class="st-tile-value">{{ m.value }}</b>
          <span class="st-tile-sub">{{ m.sub }}</span>
        </div>
      </div>
      <p v-if="usage.total.estimated" class="st-note">
        其中 {{ usage.total.estimated }} 次调用接口未返回 usage，tokens 按字数估算（中文约 1.5 字 / token）。
      </p>

      <!-- 码字目标 + 调用量 -->
      <div class="st-row2">
        <section class="st-panel">
          <div class="st-panel-head">
            <b>码字目标</b>
            <span v-if="writing" class="st-chip" :class="{ on: writing.streak > 1 }">
              连续 {{ writing.streak || 0 }} 天
            </span>
          </div>
          <template v-if="writing">
            <div class="st-goal-top">
              <b>{{ writing.today }}</b>
              <span>/ {{ writing.goal || '未设目标' }} 字</span>
              <em>{{ pct }}%</em>
            </div>
            <div class="st-goal-bar"><i :style="{ width: pct + '%' }"></i></div>
            <div class="st-week">
              <div v-for="d in writing.week" :key="d.date" class="st-wb"
                   :title="d.date + '：' + d.chars + ' 字'">
                <div class="st-wb-bar"><i :style="{ height: Math.max(2, Math.round(d.chars / weekMax * 54)) + 'px' }"></i></div>
                <span>{{ d.date.slice(5) }}</span>
              </div>
            </div>
          </template>
          <div v-else class="st-empty-inline">还没有码字记录</div>
        </section>

        <section class="st-panel">
          <div class="st-panel-head">
            <b>调用量</b>
            <span>近 {{ days }} 天 · 按 token 计</span>
          </div>
          <div v-if="!dayRows.rows.length" class="st-empty-inline">近 {{ days }} 天还没有模型调用</div>
          <div v-else class="st-chart">
            <div v-for="d in dayRows.rows" :key="d.date" class="st-db"
                 :title="`${d.date}：${d.calls} 次 / ${fmtTok(d.prompt_tokens + d.completion_tokens)} tokens / ${fmtCost(d.cost)}`">
              <div class="st-db-bar">
                <i :style="{ height: Math.max(3, Math.round((d.prompt_tokens + d.completion_tokens) / dayRows.max * 92)) + 'px' }"></i>
              </div>
              <span>{{ d.date.slice(5) }}</span>
            </div>
          </div>
        </section>
      </div>

      <!-- 按档案 -->
      <section class="st-panel">
        <div class="st-panel-head"><b>按模型档案</b><span>成本占比</span></div>
        <div v-if="byProfile.length" class="st-rank">
          <div v-for="r in byProfile" :key="r.name" class="st-rank-row">
            <span class="st-rank-avatar">{{ (r.name || '?').slice(0, 1) }}</span>
            <span class="st-rank-name">
              <b>{{ r.name }}</b>
              <small>{{ r.calls }} 次 · {{ fmtTok(r.prompt_tokens + r.completion_tokens) }} tokens · {{ fmtSec(r.elapsed) }}</small>
            </span>
            <span class="st-rank-bar"><i :style="{ width: barW(byProfile, r.cost) + '%' }"></i></span>
            <span class="st-rank-cost">{{ fmtCost(r.cost) }}</span>
            <span class="st-rank-pct">{{ share(r.cost) }}%</span>
          </div>
        </div>
        <div v-else class="st-empty-inline">还没有调用记录：跑一次拆解 / 正文生成后这里会自动累计</div>
      </section>

      <!-- 按工序 / 模型 / 作品 -->
      <div class="st-row3">
        <section v-for="g in groups" :key="g.key" class="st-panel">
          <div class="st-panel-head">
            <b><Icon :name="g.icon" :size="13" /> {{ g.title }}</b>
            <span>{{ g.rows.length }} 项</span>
          </div>
          <div v-if="g.rows.length" class="st-mini">
            <div v-for="r in g.rows" :key="r.name" class="st-mini-row">
              <span class="st-mini-main">
                <b :title="r.name">{{ r.name }}</b>
                <small>{{ r.calls }} 次 · {{ fmtTok(r.prompt_tokens + r.completion_tokens) }} tokens</small>
              </span>
              <span class="st-mini-bar"><i :style="{ width: barW(g.rows, r.cost) + '%' }"></i></span>
              <span class="st-mini-cost">{{ fmtCost(r.cost) }}</span>
            </div>
          </div>
          <div v-else class="st-empty-inline">暂无记录</div>
        </section>
      </div>
    </template>

    <div v-else class="st-empty">
      <span class="st-empty-ico"><Icon name="dashboard" :size="26" /></span>
      <b>统计暂时不可用</b>
      <p>数据目录读取失败，稍后点「刷新」再试。</p>
      <button class="btn ghost" @click="load">重新载入</button>
    </div>
  </div>
</template>

<style scoped>
.st { display: flex; flex-direction: column; gap: 14px; }
.st-head { display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; flex-wrap: wrap; }
.st-title h2 { margin: 0; font-size: 21px; letter-spacing: -.3px; }
.st-title p { margin: 4px 0 0; font-size: 12.5px; color: var(--text-3); }
.st-tools { display: flex; align-items: center; gap: 8px; }
.st-clear { color: var(--red); }
.st-loading {
  padding: 40px; text-align: center; color: var(--text-3); font-size: 13px;
  background: var(--card); border: 1px solid var(--border); border-radius: 14px;
}
.st-note { margin: -4px 2px 0; font-size: 12px; color: var(--text-3); }

/* 指标卡：独立样式，不再借用全局 .card，彻底避免卡片间距影响高度对齐 */
.st-tiles { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; align-items: stretch; }
.st-tile {
  position: relative; display: flex; flex-direction: column; min-height: 110px;
  padding: 14px 16px; border-radius: 15px; overflow: hidden;
  background: var(--card); border: 1px solid var(--border);
  box-shadow: 0 1px 2px rgba(16, 32, 27, .04);
  --tone: var(--primary); --tone-soft: var(--primary-bg);
}
.st-tile.teal { --tone: #0f766e; --tone-soft: #e7f4f1; }
.st-tile.blue { --tone: #1c7ed6; --tone-soft: #e9f2fc; }
.st-tile.purple { --tone: #7048e8; --tone-soft: #f0ecfd; }
.st-tile.gold { --tone: #e8590c; --tone-soft: #fff2e8; }
/* 右上角一枚淡色圆形装饰，让四个指标块有层次但不抢数字 */
.st-tile::after {
  content: ''; position: absolute; right: -26px; top: -30px;
  width: 96px; height: 96px; border-radius: 50%;
  background: var(--tone); opacity: .07; pointer-events: none;
}
.st-tile-head { display: flex; align-items: center; gap: 8px; }
.st-tile-label { font-size: 11.5px; color: var(--text-3); font-weight: 500; }
.st-tile-ico {
  margin-left: auto; width: 26px; height: 26px; flex: none; border-radius: 9px;
  display: grid; place-items: center; background: var(--tone-soft); color: var(--tone);
}
.st-tile-value {
  margin-top: auto; font-size: 23px; font-weight: 750; letter-spacing: -.6px;
  color: var(--text); line-height: 1.2;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.st-tile-sub { margin-top: 3px; font-size: 11px; color: var(--text-3); }

/* 双列 / 三列面板 */
.st-row2 { display: grid; grid-template-columns: 1fr 1.45fr; gap: 14px; }
.st-row3 { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
.st-panel {
  padding: 15px 16px; min-width: 0;
  background: var(--card); border: 1px solid var(--border);
  border-radius: var(--radius-md, 12px);
  box-shadow: 0 1px 2px rgba(16, 32, 27, .04);
}
.st-panel-head { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.st-panel-head b { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 700; color: var(--text); }
.st-panel-head span { margin-left: auto; font-size: 11px; color: var(--text-3); }
.st-chip { padding: 1px 7px; border-radius: 999px; background: var(--bg); color: var(--text-3) !important; font-size: 10.5px !important; }
.st-chip.on { background: var(--green-bg, #e7f6ee); color: var(--green, #0ca678) !important; }

/* 码字目标 */
.st-goal-top { display: flex; align-items: baseline; gap: 6px; }
.st-goal-top b { font-size: 26px; font-weight: 750; color: var(--primary); letter-spacing: -.6px; }
.st-goal-top span { font-size: 12px; color: var(--text-3); }
.st-goal-top em { margin-left: auto; font-style: normal; font-size: 12px; color: var(--text-2); font-weight: 600; }
.st-goal-bar { height: 8px; margin: 9px 0 14px; border-radius: 5px; background: var(--bg); overflow: hidden; }
.st-goal-bar i { display: block; height: 100%; border-radius: 5px;
  background: linear-gradient(90deg, var(--primary), #2fbfa8); transition: width .3s; }
.st-week { display: flex; gap: 6px; align-items: flex-end; }
.st-wb { flex: 1; min-width: 0; text-align: center; }
.st-wb-bar { height: 56px; display: flex; align-items: flex-end; justify-content: center; }
.st-wb-bar i { display: block; width: 58%; max-width: 26px; border-radius: 4px 4px 0 0;
  background: var(--primary-bg); border-bottom: 2px solid var(--primary); }
.st-wb span { display: block; margin-top: 4px; font-size: 10px; color: var(--text-3); }

/* 调用量柱图 */
.st-chart { display: flex; align-items: flex-end; gap: 4px; height: 128px; overflow-x: auto; padding-bottom: 2px; }
.st-db { min-width: 20px; flex: 1; text-align: center; display: flex; flex-direction: column; justify-content: flex-end; }
.st-db-bar { height: 96px; display: flex; align-items: flex-end; justify-content: center; }
.st-db-bar i { display: block; width: 68%; max-width: 22px; border-radius: 4px 4px 0 0;
  background: linear-gradient(180deg, #2fbfa8, var(--primary)); opacity: .85; }
.st-db span { margin-top: 4px; font-size: 10px; color: var(--text-3); white-space: nowrap; }

/* 档案排名 */
.st-rank { display: flex; flex-direction: column; gap: 2px; }
.st-rank-row {
  display: grid; grid-template-columns: 30px minmax(140px, 1.1fr) minmax(80px, 1fr) 84px 44px;
  align-items: center; gap: 12px; padding: 9px 6px; border-radius: 10px;
}
.st-rank-row:hover { background: var(--bg); }
.st-rank-avatar {
  width: 30px; height: 30px; border-radius: 10px; display: grid; place-items: center;
  background: var(--primary-bg); color: var(--primary); font-size: 13px; font-weight: 700;
}
.st-rank-name { min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.st-rank-name b { font-size: 12.5px; font-weight: 650; color: var(--text);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.st-rank-name small { font-size: 10.5px; color: var(--text-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.st-rank-bar { height: 8px; border-radius: 4px; background: var(--bg); overflow: hidden; }
.st-rank-bar i { display: block; height: 100%; border-radius: 4px;
  background: linear-gradient(90deg, var(--primary), #63cbb9); }
.st-rank-cost { text-align: right; font-size: 12px; font-weight: 650; color: var(--text); }
.st-rank-pct { text-align: right; font-size: 11px; color: var(--text-3); }

/* 三列小排行 */
.st-mini { display: flex; flex-direction: column; gap: 2px; }
.st-mini-row { display: grid; grid-template-columns: minmax(0, 1fr) 56px 72px;
  align-items: center; gap: 10px; padding: 7px 4px; border-radius: 9px; }
.st-mini-row:hover { background: var(--bg); }
.st-mini-main { min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.st-mini-main b { font-size: 12px; font-weight: 600; color: var(--text);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.st-mini-main small { font-size: 10.5px; color: var(--text-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.st-mini-bar { height: 6px; border-radius: 3px; background: var(--bg); overflow: hidden; }
.st-mini-bar i { display: block; height: 100%; border-radius: 3px; background: var(--primary); opacity: .75; }
.st-mini-cost { text-align: right; font-size: 11.5px; font-weight: 600; color: var(--text-2); }

.st-empty-inline { padding: 22px 6px; text-align: center; font-size: 12px; color: var(--text-3); }
.st-empty { padding: 60px 20px; display: flex; flex-direction: column; align-items: center; gap: 6px;
  text-align: center; color: var(--text-3);
  background: var(--card); border: 1px solid var(--border); border-radius: 14px; }
.st-empty-ico { width: 56px; height: 56px; border-radius: 18px; display: grid; place-items: center;
  background: var(--bg); color: var(--text-3); margin-bottom: 4px; }
.st-empty b { font-size: 14px; color: var(--text-2); }
.st-empty p { font-size: 12px; margin: 0; }
.st-empty .btn { margin-top: 8px; }

/* 平板 / 窄屏 */
@media (max-width: 1100px) {
  /* 两列时各行等高：否则「调用次数」那张会被同内容撑得比下一行高一截 */
  .st-tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); grid-auto-rows: 1fr; }
  .st-row2 { grid-template-columns: 1fr; }
  .st-row3 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .st-rank-row { grid-template-columns: 30px minmax(0, 1fr) minmax(60px, .9fr) 76px 40px; }
}
@media (max-width: 760px) {
  .st-row3 { grid-template-columns: 1fr; }
  .st-rank-row { grid-template-columns: 30px minmax(0, 1fr) 70px 40px; }
  .st-rank-bar { display: none; }
}
@media (max-width: 620px) {
  .st-tiles { grid-template-columns: 1fr; }
  .st-head { flex-direction: column; align-items: flex-start; }
  .st-tools { width: 100%; flex-wrap: wrap; }
}
</style>
