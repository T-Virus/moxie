<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import Icon from '../components/Icon.vue'
import BackLink from '../components/BackLink.vue'
import JobBar from '../components/JobBar.vue'
import LogBox from '../components/LogBox.vue'
import EmptyBox from '../components/EmptyBox.vue'
import ComplianceGate from '../components/ComplianceGate.vue'
import { api, pollJobById } from '../api'
import { adoptJob, stageName } from '../jobs'
import { state, store } from '../store'
import { toast, openFilePreview, confirmBox } from '../ui'
import { fmtSize } from '../utils'
import { usePersistedRef } from '../composables/usePersistedRef'

const router = useRouter()
const route = useRoute()
const lines = ref<string[]>([])
const job = ref({ running: false, code: null as number | null, stage: '' })
const started = ref(false)
const keyHint = ref(false)
/* 开始时记下的书单：刷新后仍要能算出「哪一本是这次新增的」，所以持久化 */
const beforeBooks = usePersistedRef<string[]>('adapt.beforeBooks', [])
/* 本页当前任务 id：多任务并发时只回显这一个任务的日志 */
const jid = usePersistedRef('adapt.jobId', '')
/* 已完成收尾的任务 id：刷新后会丢内存状态，用 id 记账保证「改编完成」的收尾不丢也不重 */
const handledJid = usePersistedRef('adapt.handledJid', '')

const outBook = usePersistedRef('adapt.outBook', '')
const aStyle = usePersistedRef('adapt.aStyle', '')
const aTarget = usePersistedRef('adapt.aTarget', '')
const aSequel = usePersistedRef('adapt.aSequel', '')
const aModel = usePersistedRef('adapt.aModel', state.model)
/* 「改编全文」工序绑定的档案：回显当前实际会用的模型 */
const boundAdapt = computed(() => store.profileFor('adapt'))
const srcOutputs = ref<any[]>([])

async function refreshSrc() {
  try {
    // 只要本书的拆解数据（chapters.json / decomposed.json），不拉全量清单
    const book = store.curBook()
    srcOutputs.value = book ? (await api.getOutputs({ book, kind: 'core' })).files || [] : []
  } catch { srcOutputs.value = [] }
}

/* 版权与 AI 使用声明：改编前必须确认，服务端同样校验并留痕 */
const gate = ref<any>(null)
const ack = ref<any>(null)
async function ensureAck() {
  if (ack.value) return ack.value
  const a = await gate.value?.ask()
  if (a) ack.value = a
  return a || null
}

watch(() => store.curBook(), () => { ack.value = null })

async function run() {
  const compliance = await ensureAck()
  if (!compliance) return
  if (!store.callCreds('adapt').api_key) {
    // 没有 Key 也放行：后端生成本地改编骨架（沿用源书设定，只做章数映射）
    keyHint.value = true
    toast('未配置 API Key：将生成本地改编骨架（不换名、不换题材），配好 Key 再跑即为正式改编', '')
  }
  /* 源书必须在切换选中之前取定：下面会把选中切到目标书，
     否则连跑第二次时 curBook() 已经是目标书，会拿错源 */
  const src = store.curBook()
  const args: any = { book: src }
  const ob = outBook.value.trim()
  if (ob) {
    if (ob === src) return toast('新书名不能与源书名相同', 'err')
    args.out_book = ob
  }
  if (aStyle.value.trim()) args.style = aStyle.value.trim()
  const t = parseInt(aTarget.value, 10); if (t > 0) args.target_chapters = t
  const sq = parseInt(aSequel.value, 10); if (sq > 0) args.sequel_chapters = sq
  if (aModel.value.trim()) args.model = aModel.value.trim()
  beforeBooks.value = state.books.map(b => b.name)   // 本次开始前的书单，产出后用于找「新增的那一本」
  api.run(store.callCreds('adapt').api_key, 'adapt', args, compliance)
    .then((r) => {
      /* 后端受理后才切面板 / 切选中：被拒（同书同阶段 409 / 并发超限 429）时保持原样 */
      lines.value = []
      lastTotal = 0
      store.setOutputBook(ob)   // 登记产出书名（留空则由后端命名，无法预知）
      if (ob) store.setBook(ob)   // 一开始就把选中切到目标书，避免停在源书/第一本
      jid.value = r.id
      toast('改编任务已启动', 'ok')
    })
    .catch((e: any) => toast(e.message, 'err'))
}

let timer: any = null
let lastTotal = 0
async function poll() {
  if (!jid.value) return
  try {
    const j = await pollJobById(jid.value, 0)
    if (lastTotal > j.total) { lines.value = []; lastTotal = 0 }   // 日志被服务端截断，重新对齐
    if (j.lines.length) {
      for (let i = lastTotal; i < j.total; i++) lines.value.push(j.lines[i])
      if (lines.value.length > 3000) lines.value.splice(0, lines.value.length - 3000)
      lastTotal = j.total
    }
    job.value.running = j.running; job.value.code = j.code; job.value.stage = j.stage || ''
    if (j.running) started.value = true
    /* 从任务中心点进来只回看日志，不替用户做收尾；发起新任务后 jid 已变，不再算看历史 */
    const qj = String(route.query.job || '').trim()
    const viewOnly = !!qj && qj === jid.value
    if (!j.running && !viewOnly && j.id && j.id !== handledJid.value) {
      handledJid.value = j.id
      started.value = false
      if (j.code === 0) {
        const fresh = (await store.loadBooks()).map((b: any) => b.name).find(n => !beforeBooks.value.includes(n))
        if (fresh) {
          store.setOutputBook(fresh)
          await store.selectOutputBook()   // 选中刚改编出的新书，别停在源书上
          const ok = await confirmBox(`检测到改编产出《${fresh}》。保留这个名字，还是到「产出浏览」手动改名？`, { ok: '保留书名' })
          if (!ok) router.push('/outputs')
        }
        toast('改编完成', 'ok')
      } else {
        store.clearOutputBook()
      }
    }
  } catch { /* */ }
}

watch(() => store.curBook(), refreshSrc)
onMounted(async () => {
  await store.loadBooks().catch(() => {})
  beforeBooks.value = state.books.map(b => b.name)
  refreshSrc()
  /* 接管仍在后台跑的改编任务（按任务 id 认领，不会串到别的任务） */
  const qj = String((route.query.job as string) || '').trim()
  if (qj) {
    jid.value = qj
  } else {
    const a = await adoptJob(['adapt'])
    if (a && a.running) { jid.value = a.id; lastTotal = 0; started.value = true }
  }
  poll()
  timer = setInterval(poll, 900)
})
onUnmounted(() => clearInterval(timer))

/* 已在改编页时从任务中心切到另一个任务：换日志面板 */
watch(() => route.query.job, (v) => {
  const id = String(v || '').trim()
  if (!id || id === jid.value) return
  jid.value = id
  lines.value = []
  lastTotal = 0
  started.value = false
  poll()
})
</script>

<template>
  <div v-if="!state.books.some(b => b.has_decomposed || b.has_chapters)" class="card">
    <EmptyBox title="没有可改编的书" desc="改编需要先完成拆解——去「上传与拆解」跑一次" />
  </div>
  <template v-else>
    <div class="page-head"><div><h1>改编创作</h1>
      <p>书级改名 + 逐章换题材文风 + 名词映射；可扩写 / 压缩章数，或续写新章。</p></div>
    </div>
    <div class="toolbar"><BackLink /><span class="spacer"></span></div>

    <div class="grid cols-2" style="align-items:start">
      <div class="card">
        <div class="card-head"><div class="card-title">改编设置</div></div>
        <div class="field"><label>改编后书名（留空 = AI 生成）</label>
          <input class="input" v-model="outBook" placeholder="新书名（不能与原书同名）" /></div>
        <div class="field"><label>目标题材 / 文风</label>
          <input class="input" v-model="aStyle" placeholder="如：都市高武 · 爽感直给，短句为主" />
          <div class="hint">给出新题材方向与语言风格，AI 会按它重写每章的任务与文风。</div></div>
        <div class="form-row">
          <div class="field"><label>目标章数（扩缩，可空）</label><input class="input" v-model="aTarget" placeholder="保持原章数" /></div>
          <div class="field"><label>续写新章数（可空）</label><input class="input" v-model="aSequel" placeholder="0" /></div>
        </div>
        <div class="field"><label>模型（留空默认）</label><input class="input" v-model="aModel" placeholder="deepseek-v4-flash" /></div>
        <div class="hint" v-if="aModel.trim()">本次使用：<b>{{ aModel.trim() }}</b>（页面临时指定，优先于工序绑定）</div>
        <div class="hint" v-else-if="boundAdapt">
          当前档案：<b>{{ boundAdapt.profile.name }}</b>（{{ boundAdapt.profile.model }}）
          <span v-if="!boundAdapt.api_key" style="color:var(--orange)"> · 该档案还没填 Key</span>
        </div>
        <div class="hint" v-else>未绑定档案，使用默认 deepseek-v4-flash</div>
        <div v-if="keyHint" class="hint">未配置 API Key：将生成本地改编骨架（沿用源书设定，只做章数映射），配好 Key 后重跑即为正式改编。</div>
        <button class="btn lg" style="width:100%;margin-top:10px" @click="run"><Icon name="play" :size="14" /> 开始改编</button>
      </div>

      <div class="card">
        <div class="card-head"><div class="card-title">源书产出</div><span class="sub">《{{ store.curBook() }}》</span></div>
        <table v-if="srcOutputs.length" class="table">
          <thead><tr><th>文件</th><th>大小</th><th style="text-align:right">操作</th></tr></thead>
          <tbody>
            <tr v-for="f in srcOutputs" :key="f.path">
              <td>{{ f.name.split('/').pop() }}</td>
              <td>{{ fmtSize(f.size) }}</td>
              <td><div class="ops"><button class="link-btn" @click="openFilePreview(f.path, f.name)">预览</button></div></td>
            </tr>
          </tbody>
        </table>
        <EmptyBox v-else title="该书暂无拆解产出" desc="请先运行拆解" />
      </div>
    </div>

    <div class="card" style="margin-top:16px">
      <div class="card-head"><div class="card-title">任务日志</div></div>
      <JobBar :running="job.running" :code="job.code" :label="stageName(job.stage)"
              @stop="() => api.stopJob(jid).then(() => toast('已请求停止')).catch((e:any)=>toast(e.message,'err'))" />
      <LogBox :lines="lines" />
    </div>

    <ComplianceGate ref="gate" stage="adapt" :source="store.curBook()" :out-book="outBook" />
  </template>
</template>
