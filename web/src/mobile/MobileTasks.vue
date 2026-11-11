<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from '../components/Icon.vue'
import Modal from '../components/Modal.vue'
import { api, pollJobById } from '../api'
import { useJobQueue } from '../composables/useJobQueue'
import { jobFailed, jobStatus, jobTarget, jobTone, stageName } from '../jobs'
import { state, store } from '../store'
import { fmtClock, fmtDur, fmtNum, fmtTime } from '../utils'
import { confirmBox, toast } from '../ui'
import type { JobSummary } from '../types'

const route = useRoute()
const router = useRouter()
const { jobs, running, maxRunning, ready, refresh } = useJobQueue()

const FILTERS = [
  { key: 'all', name: '全部' },
  { key: 'running', name: '运行中' },
  { key: 'done', name: '已完成' },
  { key: 'failed', name: '失败' },
] as const
type FilterKey = typeof FILTERS[number]['key']

const filter = ref<FilterKey>('all')
const visible = ref(16)
const detailId = ref('')
const lines = ref<string[]>([])
const since = ref(0)
const tick = ref(Date.now())
const logEl = ref<HTMLElement | null>(null)

const filtered = computed(() => {
  const all = jobs.value
  if (filter.value === 'running') return all.filter(j => j.running)
  if (filter.value === 'failed') return all.filter(jobFailed)
  if (filter.value === 'done') return all.filter(j => !j.running && !j.error && j.code === 0)
  return all
})
const shown = computed(() => filtered.value.slice(0, visible.value))
const hasMore = computed(() => filtered.value.length > visible.value)
const sel = computed(() => jobs.value.find(j => j.id === detailId.value) || null)
const detailOpen = computed(() => !!sel.value)
const finishedCount = computed(() => jobs.value.filter(j => !j.running).length)
const failedCount = computed(() => jobs.value.filter(jobFailed).length)
const elapsed = computed(() => {
  const j = sel.value
  if (!j) return 0
  const end = j.running ? tick.value / 1000 : (j.finished_at || j.created_at)
  return end - (j.created_at || end)
})

function counts(k: FilterKey) {
  if (k === 'running') return jobs.value.filter(j => j.running).length
  if (k === 'failed') return failedCount.value
  if (k === 'done') return jobs.value.filter(j => !j.running && !j.error && j.code === 0).length
  return jobs.value.length
}
function setFilter(k: FilterKey) { filter.value = k; visible.value = 16 }

function scrollBottom() {
  nextTick(() => { if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight })
}
async function pullLog() {
  const id = detailId.value
  if (!id) return
  const j = jobs.value.find(x => x.id === id)
  if (j && !j.running && j.total <= since.value) return
  try {
    const r = await pollJobById(id, since.value)
    if (id !== detailId.value) return
    if (r.total < since.value) { since.value = 0; lines.value = [] }
    if (r.lines?.length) {
      lines.value.push(...r.lines)
      if (lines.value.length > 3000) lines.value.splice(0, lines.value.length - 3000)
      scrollBottom()
    }
    since.value = r.total
  } catch { /* 服务未就绪时下一轮再试 */ }
}
function openJob(id: string) {
  if (!id) return
  detailId.value = id
  lines.value = []
  since.value = 0
  tick.value = Date.now()
  pullLog()
  router.replace({ path: '/tasks', query: { job: id } })
}
function closeJob() {
  detailId.value = ''
  lines.value = []
  since.value = 0
  router.replace({ path: '/tasks' })
}

async function stopSel() {
  if (!sel.value) return
  try {
    await api.stopJob(sel.value.id)
    toast(sel.value.stage === 'review' ? '已释放审查任务' : '已请求停止', 'ok')
    await refresh(); pullLog()
  } catch (e: any) { toast(e.message, 'err') }
}
async function resumeSel() {
  const j = sel.value
  if (!j || j.running || !j.resumable) return
  const stageKey = j.stage === 'expand' ? 'expand_outline' : j.stage
  const pid = (state.studio?.bindings || {})[stageKey] || ''
  const apiKey = (pid ? store.profileKey(pid) : '') || state.key || ''
  if (!await confirmBox(`按原参数恢复任务「${j.label}」？`, { ok: '恢复运行' })) return
  try {
    const r = await api.resumeJob(j.id, apiKey)
    toast('已恢复，新任务 ' + r.id, 'ok')
    await refresh()
    openJob(r.id)
  } catch (e: any) { toast(e.message, 'err') }
}
async function clearLog() {
  if (!sel.value) return
  try {
    await api.clearJobLog(sel.value.id)
    lines.value = []; since.value = 0
    toast('已清屏', 'ok')
  } catch (e: any) { toast(e.message, 'err') }
}
async function delSel() {
  const j = sel.value
  if (!j) return
  if (j.running) return toast('任务正在运行，请先停止再删除')
  if (!await confirmBox(`删除任务 ${j.id}？日志会一并清除。`, { danger: true, ok: '删除' })) return
  try {
    await api.deleteJob(j.id)
    toast('已删除任务', 'ok')
    closeJob()
    await refresh()
  } catch (e: any) { toast(e.message, 'err') }
}
async function clearAll() {
  if (!finishedCount.value) return toast('没有可清空的任务')
  if (!await confirmBox(`清空 ${finishedCount.value} 个已结束任务？`
    + (running.value ? `运行中的 ${running.value} 个会保留。` : ''), { danger: true, ok: '清空' })) return
  try {
    const r = await api.clearJobs()
    toast(`已清空 ${r.removed} 个任务`, 'ok')
    await refresh()
  } catch (e: any) { toast(e.message, 'err') }
}
function openPage() {
  const j = sel.value
  if (!j) return
  if (j.channel === 'page' && j.book && j.book !== store.curBook()) store.setBook(j.book)
  const t = jobTarget(j)
  closeJob()
  /* 页内任务（生成正文 / 审查）在手机端落到沉浸式正文页；其余保持原落点 */
  if (t.path === '/overview' || t.path === '/expand' || t.path === '/review') {
    const ch = t.query.ch
    router.push(ch ? { path: '/manuscript', query: { ch } } : { path: '/manuscript' })
    return
  }
  router.push({ path: t.path, query: t.query })
}
async function copyLog() {
  try {
    await navigator.clipboard.writeText(lines.value.join('\n'))
    toast('日志已复制', 'ok')
  } catch { toast('复制失败', 'err') }
}
function lineClass(l: string) {
  if (/退出码\s+0\s*$/.test(l)) return 'ok'
  if (/退出码\s+[1-9]/.test(l) || /^\[x\]/.test(l)) return 'err'
  return ''
}
function jobPageLabel(j: JobSummary) {
  return j.channel === 'page' ? '查看生成结果' : '打开对应页面'
}

let timer: any = null
onMounted(() => {
  const q = String(route.query.job || '')
  if (q) openJob(q)
  timer = setInterval(() => { tick.value = Date.now(); if (detailId.value) pullLog() }, 1200)
})
onUnmounted(() => { if (timer) clearInterval(timer) })
watch(jobs, (list) => {
  if (!ready.value) return
  if (detailId.value && !list.some(j => j.id === detailId.value)) {
    detailId.value = ''; lines.value = []; since.value = 0
  }
})
</script>

<template>
  <div class="m-page m-secondary-page">
    <div class="m-sec-head">
      <div class="m-sec-head-txt">{{ running }} 个运行中 · 共 {{ jobs.length }} 个任务</div>
      <div class="m-sec-head-act">
        <button class="m-icon-btn" title="刷新" @click="refresh"><Icon name="refresh" :size="18" /></button>
        <button class="m-icon-btn" title="清空已结束任务" :disabled="!finishedCount" @click="clearAll">
          <Icon name="trash" :size="18" />
        </button>
      </div>
    </div>

    <!-- 概览 -->
    <div class="m-task-summary">
      <div class="m-task-sum-item live">
        <span class="m-task-pulse" :class="{ on: running > 0 }"></span>
        <b>{{ running }}<small>/{{ maxRunning }}</small></b>
        <span>运行中</span>
      </div>
      <div class="m-task-sum-item">
        <b>{{ finishedCount }}</b>
        <span>已结束</span>
      </div>
      <div class="m-task-sum-item">
        <b :class="{ bad: failedCount > 0 }">{{ failedCount }}</b>
        <span>失败</span>
      </div>
    </div>

    <div class="m-seg" style="margin:2px 0 12px">
      <button v-for="f in FILTERS" :key="f.key" :class="{ on: filter === f.key }"
              @click="setFilter(f.key)">
        {{ f.name }}<span v-if="counts(f.key)" class="m-seg-n">{{ counts(f.key) }}</span>
      </button>
    </div>

    <div v-if="shown.length" class="m-rows">
      <button v-for="j in shown" :key="j.id" class="m-row-card m-task-card" @click="openJob(j.id)">
        <span class="m-task-dot" :class="jobTone(j)"><i v-if="j.running"></i></span>
        <span class="m-row-main">
          <span class="m-row-title">
            <b>{{ j.label }}</b>
            <span class="m-tag" :class="jobTone(j)">{{ jobStatus(j) }}</span>
          </span>
          <span class="m-task-meta">
            {{ stageName(j.stage) }} · {{ fmtTime(j.created_at) }} · {{ fmtNum(j.total) }} 行日志
          </span>
          <span v-if="j.error" class="m-task-err">{{ j.error }}</span>
        </span>
        <Icon name="right" :size="14" class="m-row-arrow" />
      </button>

      <button v-if="hasMore" class="m-load-more" @click="visible += 20">
        还有 {{ filtered.length - visible }} 个，加载更多
      </button>
    </div>

    <div v-else class="m-empty" style="padding-top:48px">
      <span class="m-empty-ico"><Icon name="tasks" :size="28" /></span>
      <b>{{ jobs.length ? '该筛选下没有任务' : '还没有任务' }}</b>
      <p>{{ jobs.length ? '换一个筛选条件看看。' : '在新建作品、设定图谱或正文生成页发起任务后，会出现在这里。' }}</p>
    </div>

    <!-- 任务详情 -->
    <Modal :open="detailOpen" title="任务详情" @update:open="v => { if (!v) closeJob() }">
      <div v-if="sel" class="m-task-detail">
        <div class="m-task-detail-head">
          <span class="m-task-dot" :class="jobTone(sel)"><i v-if="sel.running"></i></span>
          <div class="m-task-detail-title">
            <b>{{ sel.label }}</b>
            <small>{{ sel.id }}</small>
          </div>
          <span class="m-tag" :class="jobTone(sel)">{{ jobStatus(sel) }}</span>
        </div>

        <div class="m-task-kv">
          <div><span>任务</span><b>{{ sel.name || stageName(sel.stage) }}</b></div>
          <div><span>开始</span><b>{{ fmtClock(sel.created_at) }}</b></div>
          <div><span>用时</span><b>{{ fmtDur(elapsed) }}</b></div>
          <div><span>日志</span><b>{{ fmtNum(lines.length) }} 行</b></div>
        </div>

        <div v-if="sel.error" class="m-task-error"><Icon name="shield" :size="14" /> {{ sel.error }}</div>

        <div class="m-task-console-label">
          <span>实时日志</span>
          <span>{{ sel.running ? '正在输出…' : '已结束' }}</span>
        </div>
        <div ref="logEl" class="m-task-console">
          <div v-for="(l, i) in lines" :key="i" class="m-task-line" :class="lineClass(l)">{{ l }}</div>
          <div v-if="!lines.length" class="m-task-console-empty">
            {{ sel.total ? '正在读取日志…' : '这个任务还没有日志' }}
          </div>
        </div>

        <div class="m-task-actions">
          <button class="m-btn sm ghost" @click="copyLog"><Icon name="copy" :size="14" /> 复制</button>
          <button class="m-btn sm ghost" @click="clearLog"><Icon name="refresh" :size="14" /> 清屏</button>
          <button v-if="!sel.running && sel.resumable" class="m-btn sm soft" @click="resumeSel">
            <Icon name="play" :size="14" /> 恢复
          </button>
          <button v-if="sel.running" class="m-btn sm danger" @click="stopSel">
            <Icon name="stop" :size="14" /> {{ sel.stage === 'review' ? '释放' : '停止' }}
          </button>
          <button class="m-btn sm ghost" @click="openPage"><Icon name="arrowR" :size="14" /> 页面</button>
          <button class="m-btn sm ghost" style="color:var(--m-red)" :disabled="sel.running" @click="delSel">
            <Icon name="trash" :size="14" /> 删除
          </button>
        </div>
      </div>

      <template #footer>
        <div class="m-modal-foot">
          <button class="m-btn ghost" @click="closeJob">关闭</button>
          <button v-if="sel" class="m-btn" @click="sel.running ? stopSel() : openPage()">
            {{ sel.running ? '停止任务' : jobPageLabel(sel) }}
          </button>
        </div>
      </template>
    </Modal>
  </div>
</template>

<style scoped>
.m-task-summary {
  display: grid; grid-template-columns: 1.2fr 1fr 1fr; gap: 8px;
  padding: 14px 8px; background: #fff; border: 1px solid var(--m-line);
  border-radius: 20px; box-shadow: var(--m-shadow);
}
.m-task-sum-item { position: relative; text-align: center; display: flex; flex-direction: column; gap: 3px; }
.m-task-sum-item + .m-task-sum-item::before {
  content: ''; position: absolute; left: 0; top: 15%; bottom: 15%; width: 1px; background: var(--m-line);
}
.m-task-sum-item b { font-size: 24px; font-weight: 750; letter-spacing: -.6px; line-height: 1.1; }
.m-task-sum-item b small { font-size: 12px; font-weight: 500; color: var(--m-text3); margin-left: 1px; }
.m-task-sum-item b.bad { color: var(--m-red); }
.m-task-sum-item > span:last-child { font-size: 10.5px; color: var(--m-text3); }
.m-task-pulse { width: 7px; height: 7px; border-radius: 50%; background: #cfd6d0; margin: 0 auto 2px; }
.m-task-pulse.on { background: var(--m-green); box-shadow: 0 0 0 4px #e5f7ef; animation: mPulse 1.2s infinite; }
@keyframes mPulse { 50% { opacity: .45; } }
.m-seg-n {
  display: inline-block; margin-left: 4px; font-size: 9.5px; line-height: 15px;
  padding: 0 5px; border-radius: 8px; background: rgba(20, 30, 27, .07); color: inherit;
}
.m-task-card { align-items: center; }
.m-task-dot {
  width: 10px; height: 10px; border-radius: 50%; flex: none; position: relative;
  background: #aab2ac; margin-top: 2px;
}
.m-task-dot.blue { background: var(--m-primary); }
.m-task-dot.green { background: var(--m-green); }
.m-task-dot.red { background: var(--m-red); }
.m-task-dot.gray { background: #aab2ac; }
.m-task-dot i {
  position: absolute; inset: -4px; border-radius: 50%;
  border: 2px solid currentColor; opacity: .35; animation: mPulse 1.2s infinite;
}
.m-task-meta { display: block; margin-top: 5px; font-size: 10.5px; color: var(--m-text3); }
.m-task-err {
  display: block; margin-top: 5px; font-size: 11px; color: var(--m-red);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.m-task-detail { display: flex; flex-direction: column; gap: 13px; }
.m-task-detail-head { display: flex; align-items: center; gap: 9px; }
.m-task-detail-title { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.m-task-detail-title b { font-size: 15px; font-weight: 650; }
.m-task-detail-title small { font-size: 10.5px; color: var(--m-text3); font-family: ui-monospace, monospace; }
.m-task-kv {
  display: grid; grid-template-columns: 1fr 1fr; gap: 8px 10px;
  padding: 11px 12px; border-radius: 13px; background: #f7f9f5;
}
.m-task-kv div { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.m-task-kv span { font-size: 10px; color: var(--m-text3); }
.m-task-kv b { font-size: 12px; font-weight: 600; color: var(--m-text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.m-task-error {
  display: flex; gap: 6px; align-items: flex-start; padding: 10px 12px;
  border-radius: 12px; background: var(--m-red-soft); color: var(--m-red); font-size: 12px; line-height: 1.55;
}
.m-task-console-label { display: flex; justify-content: space-between; font-size: 11px; color: var(--m-text3); }
.m-task-console {
  max-height: 34dvh; min-height: 150px; overflow-y: auto; padding: 12px;
  border-radius: 14px; background: #101a17; color: #b9cdc6;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px; line-height: 1.65;
}
.m-task-line { white-space: pre-wrap; word-break: break-word; }
.m-task-line.ok { color: #6fd6a8; }
.m-task-line.err { color: #ff9287; }
.m-task-console-empty { color: #657a73; }
.m-task-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.m-task-actions .m-btn { flex: 1 0 30%; }
</style>
