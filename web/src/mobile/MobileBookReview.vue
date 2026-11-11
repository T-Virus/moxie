<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import Icon from '../components/Icon.vue'
import { api, pollReview } from '../api'
import type { BatchReport, ReviewReportItem, SigningReport } from '../api'
import { state, store } from '../store'
import { toast } from '../ui'
import { fmtNum } from '../utils'

type Kind = 'batch' | 'signing'
const route = useRoute()
const tab = ref<Kind>(route.query.tab === 'signing' ? 'signing' : 'batch')
const meta = computed(() => state.books.find(b => b.name === store.curBook()) || null)
const book = computed(() => store.curBook())

const history = ref<ReviewReportItem[]>([])
const selectedFile = ref('')
const report = ref<BatchReport | SigningReport | null>(null)
const loading = ref(false)
const fetching = ref(false)
const running = ref(false)
const jobId = ref('')
const jobLines = ref<string[]>([])
const jobErr = ref('')
const incremental = ref(true)
const logOpen = ref(false)
let timer: any = null

const batchDetail = computed(() => tab.value === 'batch' ? report.value as BatchReport | null : null)
const signingDetail = computed(() => tab.value === 'signing' ? report.value as SigningReport | null : null)
const status = computed(() => String(meta.value?.status || '').trim() || '连载中')
/* 与封面页一致的入口条件：全书体检只在完结后开放，签约预检要成稿满 2 万字 */
const canBatch = computed(() => status.value === '已完结' && (meta.value?.n_manuscripts || 0) > 0)
const canSigning = computed(() => (meta.value?.manuscript_chars || 0) >= 20000)
const tabs = computed(() => [
  ...(canBatch.value ? [{ k: 'batch' as Kind, t: '全书体检' }] : []),
  ...(canSigning.value ? [{ k: 'signing' as Kind, t: '签约预检' }] : []),
])
const allowed = computed(() => tabs.value.some(x => x.k === tab.value))
const busy = computed(() => running.value)
const title = computed(() => tab.value === 'batch' ? '全书体检' : '签约预检')
const desc = computed(() => tab.value === 'batch'
  ? '对全部成稿逐章体检，汇总全书问题与高危项。'
  : '模拟平台签约，检查前 2 万字（约前 10 章）的开篇质量。')

function verdictCls(v: string) {
  if (v === '可投') return 'green'
  if (v === '需修改后再投') return 'gold'
  return 'red'
}
function levelCls(v: string) {
  if (v === '通过') return 'green'
  if (v === '警告') return 'gold'
  if (v === '高危') return 'red'
  return 'gray'
}
function sevCls(v: string) {
  return v === '高' ? 'red' : v === '中' ? 'gold' : 'gray'
}

async function loadHistory(pickLatest = false) {
  if (!book.value || !allowed.value) return
  loading.value = true
  try {
    const r = await api.reviewReports(book.value, tab.value)
    history.value = r.reports || []
    if (pickLatest || !history.value.some(x => x.file === selectedFile.value)) {
      await selectReport(history.value[0]?.file || '')
    }
  } catch (e: any) { toast(e.message, 'err') }
  finally { loading.value = false }
}
async function selectReport(file: string) {
  selectedFile.value = file
  report.value = null
  if (!file || !book.value) return
  fetching.value = true
  try {
    const r = await api.reviewReport<any>(book.value, tab.value, file)
    if (selectedFile.value === file) report.value = r.report
  } catch (e: any) { toast(e.message, 'err') }
  finally { fetching.value = false }
}

async function run() {
  if (busy.value || !book.value) return
  const rc = store.callCreds('review')
  if (tab.value === 'batch' && !rc.api_key) {
    toast('全书体检需要调用模型，请先在设置里配置「正文审查」的 Key', 'err')
    return
  }
  if (tab.value === 'signing' && !rc.api_key) {
    toast('未配置 Key：只跑程序初筛，模型复核会跳过', 'ok')
  }
  jobErr.value = ''
  jobLines.value = []
  logOpen.value = false
  try {
    const r = tab.value === 'batch'
      ? await api.reviewBatchRun({ book: book.value, incremental: incremental.value,
        api_key: rc.api_key, model: rc.model || undefined, base_url: rc.base_url || undefined })
      : await api.reviewSigningRun({ book: book.value,
        api_key: rc.api_key, model: rc.model || undefined, base_url: rc.base_url || undefined })
    jobId.value = r.id
    running.value = true
    toast(title.value + '已启动', 'ok')
    startPoll()
  } catch (e: any) { toast(e.message, 'err') }
}
function startPoll() {
  if (timer) clearInterval(timer)
  poll()
  timer = setInterval(poll, 1000)
}
async function poll() {
  if (!jobId.value || !book.value) return
  try {
    const j: any = await pollReview(0, jobId.value, book.value, '')
    jobLines.value = j.lines || []
    running.value = !!j.running
    jobErr.value = j.error || ''
    if (!j.running) {
      if (timer) { clearInterval(timer); timer = null }
      await loadHistory(true)
      if (j.error) toast('报告生成失败：' + j.error, 'err')
      else toast(title.value + '完成', 'ok')
    }
  } catch { /* 下一轮再试 */ }
}
function stop() {
  if (!jobId.value) return
  api.stopReview(jobId.value).then(() => { toast('已请求停止', 'ok'); poll() })
    .catch((e: any) => toast(e.message, 'err'))
}

watch(tab, async () => {
  report.value = null
  selectedFile.value = ''
  history.value = []
  jobLines.value = []
  jobErr.value = ''
  await loadHistory(true)
})
onMounted(() => {
  /* 从封面页只会在满足条件时跳进来；这里兜住直接打开 / 旧链接的情况 */
  if (!allowed.value) tab.value = tabs.value[0]?.k || 'batch'
  loadHistory()
})
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>

<template>
  <div class="m-page m-secondary-page">
    <div v-if="!meta" class="m-empty" style="padding-top:60px">
      <span class="m-empty-ico"><Icon name="shield" :size="28" /></span>
      <b>还没有选择作品</b>
      <p>先在左侧抽屉选择一部作品。</p>
    </div>

    <template v-else>
      <div class="m-sec-head">
        <div class="m-sec-head-txt">{{ meta.title || meta.name }} · 成稿 {{ meta.n_manuscripts || 0 }} 章 / {{ fmtNum(meta.manuscript_chars || 0) }} 字</div>
      </div>

      <div v-if="tabs.length > 1" class="m-seg" style="margin-bottom:12px">
        <button v-for="t in tabs" :key="t.k" :class="{ on: tab === t.k }" @click="tab = t.k">
          {{ t.t }}
        </button>
      </div>

      <!-- 两个入口都没解锁：直接说明条件，不展示不可用的执行按钮 -->
      <div v-if="!allowed" class="m-card" style="padding:18px 16px">
        <div class="m-review-run-head">
          <span class="m-review-ico"><Icon name="shield" :size="20" /></span>
          <div>
            <b>作品审查暂未开放</b>
            <p>条件满足后会出现在作品封面页。</p>
          </div>
        </div>
        <div class="m-check-card" style="margin-top:12px">
          <div class="m-check-head">
            <b>全书体检</b>
            <span class="m-tag" :class="canBatch ? 'green' : 'gray'">{{ canBatch ? '可用' : '未解锁' }}</span>
          </div>
          <p>作品状态改为「已完结」且已有成稿后开放。</p>
        </div>
        <div class="m-check-card" style="margin-top:9px">
          <div class="m-check-head">
            <b>签约预检</b>
            <span class="m-tag" :class="canSigning ? 'green' : 'gray'">{{ canSigning ? '可用' : '未解锁' }}</span>
          </div>
          <p>成稿累计满 2 万字后开放（当前 {{ fmtNum(meta.manuscript_chars || 0) }} 字）。</p>
        </div>
      </div>

      <div v-if="allowed" class="m-card m-review-run">
        <div class="m-review-run-head">
          <span class="m-review-ico"><Icon :name="tab === 'batch' ? 'shield' : 'flag'" :size="20" /></span>
          <div>
            <b>{{ title }}</b>
            <p>{{ desc }}</p>
          </div>
        </div>
        <div v-if="tab === 'batch'" class="m-review-opts">
          <button class="m-toggle-row" @click="incremental = !incremental">
            <span><b>增量模式</b><small>只复查有变化的章节</small></span>
            <i class="m-toggle" :class="{ on: incremental }"><em></em></i>
          </button>
        </div>
        <p v-if="tab === 'batch' && !canBatch" class="m-hint">还没有成稿章节，先写几章正文再来体检。</p>
        <p v-if="tab === 'signing' && !canSigning" class="m-hint">成稿满 2 万字后可做签约预检。</p>

        <div v-if="running" class="m-review-progress">
          <div class="m-review-status"><span class="m-ai-pulse"></span>{{ title }}进行中…</div>
          <div class="m-review-log">
            <div v-if="!jobLines.length" class="m-review-log-empty">正在准备…</div>
            <div v-for="(l, i) in jobLines.slice(-80)" :key="i" class="m-review-line">{{ l }}</div>
          </div>
          <button class="m-btn sm danger" @click="stop"><Icon name="stop" :size="13" /> 停止</button>
        </div>

        <button class="m-btn block" style="margin-top:12px"
                :disabled="busy || (tab === 'batch' ? !canBatch : !canSigning)" @click="run">
          <Icon name="play" :size="14" />
          {{ busy ? '正在执行…' : (report ? '重新执行' : '开始' + title) }}
        </button>
      </div>

      <!-- 历史报告 -->
      <template v-if="allowed">
      <div class="m-sec-title" style="margin-top:18px">
        历史报告<span class="m-spacer"></span><span class="m-sub">{{ history.length }}</span>
      </div>
      <div v-if="history.length" class="m-chips">
        <button v-for="(h, i) in history" :key="h.file" class="m-chip"
                :class="{ on: selectedFile === h.file }" @click="selectReport(h.file)">
          {{ h.created_at }}{{ i === 0 ? ' · 最新' : '' }}
        </button>
      </div>
      <p v-else-if="!loading" class="m-hint" style="padding:0 4px">还没有报告，执行一次后会按时间留档。</p>

      <div v-if="fetching" class="m-empty" style="padding:28px 0">
        <b>正在读取报告…</b>
      </div>

      <!-- 全书体检报告 -->
      <template v-else-if="batchDetail">
        <div class="m-review-stats">
          <div><b>{{ batchDetail.n_done }}</b><span>已检章节</span></div>
          <div><b :class="{ bad: batchDetail.total_high }">{{ batchDetail.total_issues }}</b><span>问题总数</span></div>
          <div><b :class="{ bad: batchDetail.total_high }">{{ batchDetail.total_high }}</b><span>高危</span></div>
        </div>
        <div class="m-review-tags">
          <span class="m-tag blue">{{ batchDetail.created_at }}</span>
          <span class="m-tag gray">{{ batchDetail.incremental ? '增量' : '全量' }}</span>
          <span v-if="batchDetail.n_skipped" class="m-tag gray">跳过 {{ batchDetail.n_skipped }} 章</span>
        </div>
        <div class="m-rows" style="margin-top:10px">
          <div v-for="c in batchDetail.chapters" :key="c.no" class="m-review-chapter">
            <div class="m-review-ch-head">
              <b>第 {{ c.no }} 章</b>
              <span v-if="c.error" class="m-tag red">读取失败</span>
              <template v-else>
                <span class="m-tag gray">问题 {{ c.n_issues || 0 }}</span>
                <span v-if="c.n_high" class="m-tag red">高 {{ c.n_high }}</span>
              </template>
            </div>
            <p v-if="c.error" class="m-review-ch-err">{{ c.error }}</p>
            <p v-else-if="(c.top_issues || []).length" class="m-review-ch-top">
              {{ (c.top_issues || []).map(i => i.reason).join('；') }}
            </p>
            <p v-else class="m-hint">本章未发现问题</p>
          </div>
        </div>
      </template>

      <!-- 签约预检报告 -->
      <template v-else-if="signingDetail">
        <div class="m-signing-verdict">
          <span class="m-tag" :class="verdictCls(signingDetail.verdict)">{{ signingDetail.verdict }}</span>
          <b>{{ signingDetail.verdict_why || '—' }}</b>
          <p>前 {{ signingDetail.window_chapters }} 章 / {{ fmtNum(signingDetail.chars) }} 字 · {{ signingDetail.created }}</p>
        </div>
        <div class="m-rows" style="margin-top:10px">
          <div v-for="c in signingDetail.checks" :key="c.key" class="m-check-card">
            <div class="m-check-head">
              <b>{{ c.label }}</b>
              <span class="m-tag" :class="levelCls(c.level)">{{ c.level }}</span>
            </div>
            <p>{{ c.detail }}</p>
          </div>
        </div>
        <template v-if="(signingDetail.issues || []).length">
          <div class="m-sec-title" style="margin-top:16px">问题清单<span class="m-spacer"></span><span class="m-sub">{{ signingDetail.issues.length }}</span></div>
          <div class="m-rows">
            <div v-for="(x, i) in signingDetail.issues" :key="i" class="m-issue-card">
              <span class="m-tag" :class="sevCls(x.sev)">{{ x.sev }}</span>
              <span v-if="x.chapter" class="m-tag gray">第 {{ x.chapter }} 章</span>
              <p>{{ x.msg }}</p>
            </div>
          </div>
        </template>
      </template>

      <div v-else-if="!loading && !fetching" class="m-empty" style="padding-top:34px">
        <span class="m-empty-ico"><Icon :name="tab === 'batch' ? 'shield' : 'flag'" :size="27" /></span>
        <b>暂无{{ title }}报告</b>
        <p>点上方「开始{{ title }}」跑一次，报告会按时间留档。</p>
      </div>
      </template>
    </template>
  </div>
</template>

<style scoped>
.m-spacer { flex: 1; }
.m-review-run { padding: 15px; }
.m-review-run-head { display: flex; gap: 11px; align-items: flex-start; }
.m-review-ico {
  width: 42px; height: 42px; flex: none; border-radius: 13px;
  display: grid; place-items: center;
  background: var(--m-primary-soft); color: var(--m-primary);
}
.m-review-run-head b { font-size: 15px; font-weight: 650; }
.m-review-run-head p { margin-top: 4px; font-size: 11.5px; line-height: 1.55; color: var(--m-text3); }
.m-review-opts { margin-top: 11px; }
.m-review-progress {
  display: flex; flex-direction: column; gap: 9px;
  margin-top: 11px; padding: 11px; border-radius: 13px; background: #f7f9f5;
}
.m-review-status { display: flex; align-items: center; gap: 7px; font-size: 12px; color: var(--m-primary); }
.m-ai-pulse {
  width: 8px; height: 8px; border-radius: 50%; flex: none;
  background: var(--m-primary); box-shadow: 0 0 0 4px var(--m-primary-soft);
  animation: mPulse 1.2s infinite;
}
@keyframes mPulse { 50% { opacity: .4; } }
.m-review-log {
  max-height: 22dvh; min-height: 150px; overflow: auto; padding: 9px 10px; border-radius: 10px;
  background: #101a17; color: #b9cdc6;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 10px; line-height: 1.6;
}
.m-review-log-empty { color: #657a73; }
.m-review-line { white-space: pre-wrap; word-break: break-word; }
.m-review-stats {
  display: grid; grid-template-columns: repeat(3, 1fr);
  margin-top: 12px; padding: 13px 4px; background: #fff;
  border: 1px solid var(--m-line); border-radius: 17px;
}
.m-review-stats div { text-align: center; display: flex; flex-direction: column; gap: 3px; }
.m-review-stats div + div { border-left: 1px solid var(--m-line); }
.m-review-stats b { font-size: 22px; font-weight: 750; }
.m-review-stats b.bad { color: var(--m-red); }
.m-review-stats span { font-size: 10px; color: var(--m-text3); }
.m-review-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 9px; }
.m-review-chapter, .m-check-card, .m-issue-card {
  padding: 12px 14px; background: #fff;
  border: 1px solid var(--m-line); border-radius: 15px;
}
.m-review-ch-head { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.m-review-ch-head b { font-size: 13px; font-weight: 650; margin-right: auto; }
.m-review-ch-top { margin-top: 7px; font-size: 11.5px; line-height: 1.6; color: var(--m-text2); }
.m-review-ch-err { margin-top: 7px; font-size: 11.5px; color: var(--m-red); }
.m-signing-verdict {
  display: flex; flex-direction: column; gap: 8px;
  margin-top: 12px; padding: 15px; border-radius: 18px;
  background: #fff; border: 1px solid var(--m-line);
}
.m-signing-verdict b { font-size: 14px; line-height: 1.6; font-weight: 600; }
.m-signing-verdict p { font-size: 10.5px; color: var(--m-text3); }
.m-check-head { display: flex; align-items: center; gap: 8px; }
.m-check-head b { flex: 1; font-size: 13px; font-weight: 600; }
.m-check-card p { margin-top: 7px; font-size: 11.5px; line-height: 1.6; color: var(--m-text2); }
.m-issue-card { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.m-issue-card p { flex: 1 1 100%; font-size: 11.5px; line-height: 1.6; color: var(--m-text2); }
</style>
