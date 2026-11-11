<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from '../components/Icon.vue'
import EmptyBox from '../components/EmptyBox.vue'
import { api, pollJobById } from '../api'
import { useJobQueue } from '../composables/useJobQueue'
import { jobFailed, jobStatus, jobTarget, jobTone, stageName } from '../jobs'
import { store, state } from '../store'
import { fmtClock, fmtDur, fmtNum, fmtTime } from '../utils'
import { confirmBox, toast } from '../ui'
import type { JobSummary } from '../types'

/* 任务中心：左侧是分页的任务队列，右侧是所选任务的实时日志。
   日志按任务 id 轮询（/api/job?id=），多个任务并发时互不串台。
   URL 用 ?job=<id> 记住当前选中的任务，刷新 / 从别处跳回来都能直接回显。 */
const route = useRoute()
const router = useRouter()
const { jobs, running, maxRunning, refresh } = useJobQueue()

const PAGE = 8
const FILTERS = [
  { key: 'all', name: '全部' },
  { key: 'running', name: '运行中' },
  { key: 'done', name: '已完成' },
  { key: 'failed', name: '失败' },
] as const
type FilterKey = typeof FILTERS[number]['key']

const filter = ref<FilterKey>('all')
const page = ref(1)
const selId = ref('')
const lines = ref<string[]>([])
const since = ref(0)
const logEl = ref<HTMLElement | null>(null)
const logCardEl = ref<HTMLElement | null>(null)
/* 运行中任务的用时需要每秒重算，轮询日志时顺手更新 */
const tick = ref(Date.now())

const filtered = computed(() => {
  const all = jobs.value
  if (filter.value === 'running') return all.filter(j => j.running)
  if (filter.value === 'failed') return all.filter(jobFailed)
  if (filter.value === 'done') return all.filter(j => !j.running && !j.error && j.code === 0)
  return all
})
const pages = computed(() => Math.max(1, Math.ceil(filtered.value.length / PAGE)))
const pageJobs = computed(() => filtered.value.slice((page.value - 1) * PAGE, page.value * PAGE))
const sel = computed(() => jobs.value.find(j => j.id === selId.value) || null)
/* 清空全部只动已结束的任务；运行中的保留，否则子进程就没人能停了 */
const finishedCount = computed(() => jobs.value.filter(j => !j.running).length)

const elapsed = computed(() => {
  const j = sel.value
  if (!j) return 0
  const end = j.running ? tick.value / 1000 : (j.finished_at || j.created_at)
  return end - (j.created_at || end)
})

/* 任务列表随轮询变化：页码越界时收回，避免停在空白页 */
watch([filtered, pages], () => {
  if (page.value > pages.value) page.value = pages.value
  if (page.value < 1) page.value = 1
})

function setFilter(k: FilterKey) {
  filter.value = k
  page.value = 1
}

/* 选中任务：清空旧日志，从头按 id 拉新任务的输出 */
function focusJob(id: string) {
  if (!id) return
  let i = filtered.value.findIndex(j => j.id === id)
  // 目标不在当前筛选里（深链 / 任务被清理）：退回「全部」再定位，避免选中了却看不见
  if (i < 0 && filter.value !== 'all') {
    filter.value = 'all'
    i = filtered.value.findIndex(j => j.id === id)
  }
  selId.value = id
  lines.value = []
  since.value = 0
  page.value = i >= 0 ? Math.floor(i / PAGE) + 1 : 1
  pullLog()
}

function select(id: string) {
  if (id === selId.value) return
  focusJob(id)
  router.replace({ path: '/tasks', query: { job: id } })
  /* 手机/平板是上下排：点任务后直接带到日志面板，不用自己往下滚 */
  if (window.innerWidth <= 900) {
    nextTick(() => logCardEl.value?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  }
}

function scrollBottom(force = false) {
  const el = logEl.value
  if (!el) return
  const near = el.scrollHeight - el.scrollTop - el.clientHeight < 90
  if (!force && !near) return          // 用户往回翻看时不要强行拽回底部
  nextTick(() => {
    const e = logEl.value
    if (e) e.scrollTop = e.scrollHeight
  })
}

/* 增量拉取所选任务的日志 */
async function pullLog() {
  const id = selId.value
  if (!id) return
  const j = jobs.value.find(x => x.id === id)
  // 任务已结束且日志行数已经追平：不必再请求
  if (j && !j.running && j.total <= since.value) return
  try {
    const r = await pollJobById(id, since.value)
    if (id !== selId.value) return     // 期间切了任务，丢弃旧响应
    if (r.total < since.value) {       // 服务重启 / 日志被截断：重新对齐
      since.value = 0
      lines.value = []
      return
    }
    if (r.lines && r.lines.length) {
      lines.value.push(...r.lines)
      if (lines.value.length > 3000) lines.value.splice(0, lines.value.length - 3000)
      scrollBottom()
    }
    since.value = r.total
  } catch { /* 服务未就绪时静默 */ }
}

async function stopSel() {
  const id = selId.value
  if (!id) return
  const review = sel.value?.stage === 'review'
  try {
    await api.stopJob(id)
    toast(review ? '已释放审查：可以切章或发起别的任务了'
      : '已停止 ' + (sel.value?.label || id), 'ok')
    refresh()
    pullLog()
  } catch (e: any) { toast(e.message, 'err') }
}

/* 清屏：只清掉本任务的日志行，任务与状态保留（运行中的也能清，清完继续追加新行） */
async function clearSelLog() {
  const id = selId.value
  if (!id) return
  try {
    await api.clearJobLog(id)
    lines.value = []
    since.value = 0
    toast('已清屏 ' + id, 'ok')
    refresh()
  } catch (e: any) { toast(e.message, 'err') }
}

/* 断点恢复（P0）：中断 / 失败 / 被停的任务按原参数重跑；批量扩写自动跳过已有成稿的章节。
   Key 不落盘，恢复时从该工序绑定的档案（或全局兜底）里取本机保存的 Key。 */
async function resumeSel() {
  const j = sel.value
  if (!j || j.running || !j.resumable) return
  const stageKey = j.stage === 'expand' ? 'expand_outline' : j.stage
  const pid = (state.studio?.bindings || {})[stageKey] || ''
  const apiKey = (pid ? store.profileKey(pid) : '') || state.key || ''
  if (!await confirmBox(
    `按原参数恢复任务「${j.label}」？${j.stage === 'expand' ? '已完成成稿的章节会自动跳过，只补没写成的。' : ''}`,
    { ok: '恢复运行' })) return
  try {
    const r = await api.resumeJob(j.id, apiKey)
    toast(`已恢复，新任务 ${r.id} 开始运行`, 'ok')
    await refresh()
    if (r.id) selId.value = r.id
  } catch (e: any) { toast(e.message, 'err') }
}

/* 删除后落到相邻任务上，避免右栏空一下；没有任务了就回到空态并清掉 ?job */
async function afterRemove(next: JobSummary | null) {
  selId.value = ''
  lines.value = []
  since.value = 0
  await refresh()
  const alive = next && jobs.value.some(j => j.id === next.id) ? next.id : (jobs.value[0]?.id || '')
  if (alive) focusJob(alive)
  router.replace({ path: '/tasks', query: alive ? { job: alive } : {} })
}

async function deleteSel() {
  const j = sel.value
  if (!j) return
  if (j.running) return toast('任务正在运行，请先停止再删除')
  if (!await confirmBox(`删除任务 ${j.id}（${j.label}）？日志会一并清除。`,
    { danger: true, ok: '删除' })) return
  const list = filtered.value
  const i = list.findIndex(x => x.id === j.id)
  const next = list[i + 1] || list[i - 1] || null
  try {
    await api.deleteJob(j.id)
    toast('已删除任务 ' + j.id, 'ok')
    await afterRemove(next)
  } catch (e: any) { toast(e.message, 'err') }
}

/* 标题栏的「清空全部任务」：一次清掉所有已结束的任务 */
async function clearAll() {
  if (!finishedCount.value) return toast('没有可清空的任务（运行中的会保留）')
  if (!await confirmBox(`清空 ${finishedCount.value} 个已结束的任务？`
    + (running.value ? `运行中的 ${running.value} 个会保留。` : ''), { danger: true, ok: '清空' })) return
  try {
    const r = await api.clearJobs()
    toast(`已清空 ${r.removed} 个任务`, 'ok')
    await afterRemove(null)
  } catch (e: any) { toast(e.message, 'err') }
}

function openPage() {
  const j = sel.value
  if (!j) return
  // 回到这个任务「发起时所在的页面」：页面自己会接管进度 / 按 ?job= 回显日志
  if (j.channel === 'page' && j.book && j.book !== store.curBook()) store.setBook(j.book)
  const t = jobTarget(j)
  router.push({ path: t.path, query: t.query })
}

async function copyLog() {
  try {
    await navigator.clipboard.writeText(lines.value.join('\n'))
    toast('日志已复制', 'ok')
  } catch { toast('复制失败，请手动选择文本', 'err') }
}

/* 退出码 / 报错行高亮，长日志里更容易定位断点 */
function lineClass(l: string) {
  if (/退出码\s+0\s*$/.test(l)) return 'ok'
  if (/退出码\s+[1-9]/.test(l) || /^\[x\]/.test(l)) return 'err'
  return ''
}

let logTimer: any = null
onMounted(() => {
  const q = String(route.query.job || '')
  if (q) focusJob(q)
  else if (jobs.value.length) focusJob(jobs.value[0].id)
  logTimer = setInterval(() => { tick.value = Date.now(); pullLog() }, 1200)
})
onUnmounted(() => { if (logTimer) clearInterval(logTimer) })

/* 队列首次到货 / 选中任务被清理时，自动落到一个有效任务上 */
watch(jobs, (list) => {
  if (!list.length) {                  // 任务被清空（或全被删掉）：右栏回到空态
    selId.value = ''
    lines.value = []
    since.value = 0
    return
  }
  if (selId.value && list.some(j => j.id === selId.value)) return
  const q = String(route.query.job || '')
  const want = q && list.some(j => j.id === q) ? q : list[0].id
  focusJob(want)
})

/* 从悬浮条等入口跳到 ?job=xxx 时同步切换 */
watch(() => route.query.job, (v) => {
  const id = String(v || '')
  if (id && id !== selId.value) focusJob(id)
})
</script>

<template>
  <div class="page-head tc-head">
    <div class="tc-head-txt">
      <h1>任务中心</h1>
      <p>后台任务队列：多个任务可同时运行，选中任意一个即可查看它自己的实时日志。</p>
    </div>
    <span class="tag" :class="running ? 'blue' : 'gray'">
      <i class="dot" :class="{ live: running }"></i>{{ running }} / {{ maxRunning }} 运行中
    </span>
    <button class="btn ghost sm" :disabled="!finishedCount" @click="clearAll"
            :title="running ? '运行中的任务会保留' : '删除全部已结束的任务记录'">
      <Icon name="trash" :size="13" /> 清空全部任务
    </button>
  </div>

  <div class="tc-grid">
    <!-- 左：分页任务队列 -->
    <section class="tc-card tc-queue">
      <div class="tc-card-head">
        <div class="card-title">任务队列 <span class="sub">{{ filtered.length }} 个</span></div>
        <span class="spacer"></span>
      </div>

      <div class="tc-filter seg">
        <button v-for="f in FILTERS" :key="f.key" :class="{ on: filter === f.key }"
                @click="setFilter(f.key)">{{ f.name }}</button>
      </div>

      <div class="tc-list">
        <button v-for="j in pageJobs" :key="j.id" class="tc-row" :class="{ on: j.id === selId }"
                @click="select(j.id)">
          <span class="tc-dot" :class="[jobTone(j), j.running ? 'live' : '']"></span>
          <span class="tc-row-body">
            <span class="tc-row-title">{{ j.label }}</span>
            <span class="tc-row-meta">
              {{ j.id }} · {{ fmtTime(j.created_at) }} · {{ fmtNum(j.total) }} 行
            </span>
          </span>
          <span class="tag" :class="jobTone(j)">{{ jobStatus(j) }}</span>
        </button>
        <EmptyBox v-if="!filtered.length"
                  :title="jobs.length ? '该筛选下没有任务' : '还没有任务'"
                  :desc="jobs.length ? '换一个筛选条件看看' : '在新建作品 / 设定图谱 / 正文生成等页面发起任务后会出现在这里'" />
      </div>

      <div class="tc-pager">
        <span class="tc-count">共 {{ filtered.length }} 个 · 每页 {{ PAGE }}</span>
        <span class="spacer"></span>
        <button class="btn ghost sm" :disabled="page <= 1" title="上一页" @click="page--">
          <Icon name="left" :size="12" />
        </button>
        <span class="tc-pg">{{ page }} / {{ pages }}</span>
        <button class="btn ghost sm" :disabled="page >= pages" title="下一页" @click="page++">
          <Icon name="right" :size="12" />
        </button>
      </div>
    </section>

    <!-- 右：所选任务的日志 -->
    <section class="tc-card tc-logcard" ref="logCardEl">
      <div class="tc-card-head">
        <div class="card-title">任务日志
          <span class="sub">{{ sel ? sel.label : '未选择任务' }}</span>
        </div>
        <span class="spacer"></span>
        <div v-if="sel" class="tc-head-acts">
          <span class="tag" :class="jobTone(sel)">
            <i v-if="sel.running" class="dot live"></i>{{ jobStatus(sel) }}
          </span>
          <button class="btn ghost sm icon-only" title="复制全部日志" @click="copyLog">
            <Icon name="copy" :size="13" />
          </button>
          <!-- 审查是页内任务，卡住的是整章的编辑：「停止」直接就是「释放」，立刻解锁 -->
          <!-- 中断 / 失败 / 被停的子进程任务：按原参数一键恢复（批量扩写自动跳过已成稿章节） -->
          <button v-if="!sel.running && sel.resumable" class="btn sm"
                  title="按原参数重新运行；批量扩写会跳过已完成章节（断点续跑）" @click="resumeSel">
            <Icon name="play" :size="12" /> 恢复
          </button>
          <button v-if="sel.running" class="btn danger-ghost sm" @click="stopSel"
                  :title="sel.stage === 'review'
                    ? '立即释放：不等当前这一步跑完，马上可切章 / 发起别的生成或审查'
                    : '停止这个任务'">
            <Icon name="stop" :size="12" /> {{ sel.stage === 'review' ? '释放' : '停止' }}
          </button>
          <button class="btn ghost sm icon-only" title="清屏：只清空本任务的日志" @click="clearSelLog">
            <Icon name="refresh" :size="13" />
          </button>
          <button class="btn danger-ghost sm icon-only" :disabled="sel.running"
                  :title="sel.running ? '运行中的任务需先停止再删除' : '删除这个任务'" @click="deleteSel">
            <Icon name="trash" :size="13" />
          </button>
          <button class="btn ghost sm icon-only" title="打开对应页面" @click="openPage">
            <Icon name="arrowR" :size="13" />
          </button>
        </div>
      </div>

      <div v-if="sel" class="tc-meta">
        <span class="tc-kv"><b>编号</b>{{ sel.id }}</span>
        <span class="tc-kv"><b>任务</b>{{ sel.name || stageName(sel.stage) }}</span>
        <span class="tc-kv"><b>开始</b>{{ fmtClock(sel.created_at) }}</span>
        <span class="tc-kv"><b>用时</b>{{ fmtDur(elapsed) }}</span>
        <span class="tc-kv"><b>日志</b>{{ fmtNum(lines.length) }} 行</span>
        <span v-if="sel.error" class="tc-err">{{ sel.error }}</span>
      </div>

      <div ref="logEl" class="tc-log">
        <div v-for="(l, i) in lines" :key="i" class="tc-line" :class="lineClass(l)">{{ l }}</div>
        <div v-if="!lines.length" class="tc-log-empty">
          {{ sel ? (sel.total ? '正在读取日志…' : '这个任务没有日志（可能刚清屏）') : '左侧选择一个任务查看日志' }}
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.tc-head { display: flex; align-items: flex-end; gap: 14px; }
.tc-head-txt { flex: 1; }

/* 左右两栏卡片，占满视口剩余高度；各自内部滚动，页面不出滚动条 */
.tc-grid { display: flex; gap: 16px; flex: 1; min-height: 0; }
.tc-card {
  display: flex; flex-direction: column; min-height: 0;
  background: var(--card); border: 1px solid var(--border);
  border-radius: var(--radius); box-shadow: var(--shadow);
}
.tc-queue { width: 380px; flex: none; }
.tc-logcard { flex: 1; min-width: 0; }

.tc-card-head { display: flex; align-items: center; gap: 8px; padding: 13px 16px 8px; flex-wrap: wrap; row-gap: 6px; }
.tc-card-head .spacer { flex: 1; }
/* 标题不被按钮挤压换行（窄屏曾把「任务日志」挤成竖排单字） */
.tc-card-head .card-title { white-space: nowrap; flex: none; }
.tc-card-head .card-title .sub { max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
/* 右卡动作多（复制 / 停止 / 清屏 / 删除 / 打开）：放到独立操作组里整体换行 */
.tc-head-acts { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; margin-left: auto; }
.tc-logcard .tc-card-head .card-title { min-width: 0; }
.tc-logcard .tc-card-head .card-title .sub { max-width: 180px; }
.tc-card-head .icon-only { padding: 0 7px; }

/* 筛选 */
.tc-filter { display: flex; margin: 2px 14px 10px; }
.tc-filter button { flex: 1; padding: 6px 0; }

/* 队列列表 */
.tc-list { flex: 1; min-height: 0; overflow: auto; padding: 0 10px 8px; display: flex; flex-direction: column; gap: 4px; }
.tc-list::-webkit-scrollbar { width: 7px; }
.tc-list::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 4px; }
.tc-row {
  display: flex; align-items: center; gap: 9px; padding: 9px 10px; width: 100%;
  border: 1px solid transparent; border-radius: 9px; background: none; cursor: pointer;
  text-align: left; transition: background .12s, border-color .12s;
}
.tc-row:hover { background: #f7f8fa; }
.tc-row.on { background: var(--primary-bg); border-color: rgba(51, 112, 255, .28); }
.tc-dot { width: 8px; height: 8px; border-radius: 50%; flex: none; background: var(--text-3); }
.tc-dot.blue { background: var(--primary); }
.tc-dot.green { background: var(--green); }
.tc-dot.red { background: var(--red); }
.tc-dot.gray { background: var(--text-3); }
.tc-dot.live { animation: pulse 1.1s infinite; }
.tc-row-body { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 2px; }
.tc-row-title { font-size: 13px; font-weight: 600; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tc-row-meta { font-size: 11px; color: var(--text-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tc-list :deep(.empty) { padding: 28px 12px; }

/* 分页 */
.tc-pager { display: flex; align-items: center; gap: 8px; padding: 10px 14px; border-top: 1px solid var(--border); }
.tc-count { font-size: 11px; color: var(--text-3); }
.tc-pg { font-size: 12px; color: var(--text-2); min-width: 48px; text-align: center; }
.tc-pager .btn.sm { padding: 0 9px; }

/* 日志面板 */
.tc-meta { display: flex; flex-wrap: wrap; gap: 5px 14px; padding: 0 16px 10px; font-size: 11.5px; color: var(--text-3); }
.tc-kv b { font-weight: 500; color: var(--text-2); margin-right: 5px; }
.tc-err { color: var(--red); }
.tc-log {
  flex: 1; min-height: 0; overflow: auto; margin: 0 14px 14px; padding: 10px 12px;
  background: #0f1622; border-radius: 10px; color: #c6d3e6;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px; line-height: 1.65;
}
.tc-log::-webkit-scrollbar { width: 8px; height: 8px; }
.tc-log::-webkit-scrollbar-thumb { background: #33415c; border-radius: 4px; }
.tc-line { white-space: pre-wrap; word-break: break-word; }
.tc-line.ok { color: #5fd39a; }
.tc-line.err { color: #ff8b7d; }
.tc-log-empty { color: #6c7c93; }

@media (max-width: 1080px) {
  .tc-queue { width: 320px; }
}
/* 手机：队列与日志上下排，页面整体滚动，两块都给固定可用高度 */
@media (max-width: 900px) {
  .tc-grid { flex-direction: column; flex: none; overflow: visible; }
  .tc-queue { width: 100%; height: 300px; }
  .tc-logcard { flex: none; height: min(70vh, 520px); min-height: 360px; }
  .tc-head { flex-wrap: wrap; align-items: center; gap: 8px; }
}
@media (max-width: 1200px) {
  /* 窄桌面：日志卡变窄，任务名让位给操作按钮，避免整行按钮被挤到第二行 */
  .tc-logcard .tc-card-head .card-title .sub { display: none; }
}
@media (max-width: 640px) {
  .tc-card-head { padding: 10px 12px 8px; }
  /* 页头说明占满一行，状态与「清空」按钮换到下一行，不再把说明挤成窄条 */
  .tc-head { align-items: flex-start; }
  .tc-head-txt { flex: 1 1 100%; }
  /* 手机上任务名放不下：只留「任务日志」，任务名在下方元信息里已有 */
  .tc-logcard .tc-card-head .card-title .sub { display: none; }
  .tc-head-acts { gap: 6px; }
  .tc-head-acts .btn { padding: 0 9px; }
  .tc-head-acts .btn.icon-only { padding: 0 7px; }
  .tc-meta { padding: 0 12px 8px; }
  .tc-log { margin: 0 10px 10px; }
}
</style>
