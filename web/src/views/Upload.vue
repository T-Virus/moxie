<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import Icon from '../components/Icon.vue'
import Collapse from '../components/Collapse.vue'
import SelectBox from '../components/SelectBox.vue'
import ComplianceGate from '../components/ComplianceGate.vue'
import { api, pollJobById } from '../api'
import { adoptJob, stageName } from '../jobs'
import { state, store } from '../store'
import { toast, confirmBox } from '../ui'
import { GENRE_PRESETS, TONE_PRESETS, VOICE_PRESETS } from '../storyPresets'
import { fmtSize } from '../utils'
import { usePersistedRef } from '../composables/usePersistedRef'

const router = useRouter()
const route = useRoute()
const sources = ref<any[]>([])
const lines = ref<string[]>([])
const job = ref({ running: false, code: null as number | null, stage: '' })

/* 实时日志面板：时间戳 / 跟随 / 过滤（全部·仅错误·仅通过）/ 清屏 / 停止 */
const lineTimes = ref<number[]>([])
const logShowTs = ref(true)
const logFollow = ref(true)
const logFilter = ref<'all' | 'err' | 'ok'>('all')
const logBoxEl = ref<HTMLElement | null>(null)
const RE_ERR = /\[x\]|错误|Error|Traceback|失败/i
const RE_OK = /\[完成\]|退出码 0|成功/i
function lineCls(l: string): string {
  if (RE_ERR.test(l)) return 'ln-err'
  if (RE_OK.test(l)) return 'ln-ok'
  if (/\[!\]|警告|跳过/i.test(l)) return 'ln-warn'
  return ''
}
const shownLines = computed(() =>
  lines.value.map((l, i) => ({ l, t: lineTimes.value[i] || 0 }))
    .filter(x => logFilter.value === 'all' ||
      (logFilter.value === 'err' ? RE_ERR.test(x.l) : RE_OK.test(x.l))))
const jobText = computed(() => {
  if (job.value.running) return '运行中' + (job.value.stage ? ' · ' + stageName(job.value.stage) : '')
  if (job.value.code === 0) return '已完成'
  if (job.value.code == null) return '空闲'
  return '失败（退出码 ' + job.value.code + '）'
})
/* 任务在后台并发跑，本页按钮不再随任务运行而禁用：
   「同一本书 + 同一阶段」的重复启动由后端 409 兜底并给出提示，
   换素材 / 换书名后随时可以再开一个任务，旧任务继续在后台跑（任务中心可见） */
function fmtTs(t: number): string {
  if (!t) return ''
  const d = new Date(t); const p = (n: number) => String(n).padStart(2, '0')
  return p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds())
}
watch(() => shownLines.value.length, async () => {
  if (!logFollow.value) return
  await nextTick()
  const el = logBoxEl.value
  if (el) el.scrollTop = el.scrollHeight
})
function clearLog() { lines.value = []; lineTimes.value = [] }
function stopJob() {
  api.stopJob(jid.value).then(() => toast('已请求停止', 'ok')).catch((e: any) => toast(e.message, 'err'))
}

/* 三模式：outline=大纲拆解  adapt=全文改编  blank=空白新书 */
const mode = usePersistedRef<'outline' | 'adapt' | 'blank'>('upload.mode', 'outline')
const keyHint = ref(false)

const srcInput = ref<HTMLInputElement | null>(null)
const dzOver = ref(false)

async function refreshSources() {
  try { sources.value = (await api.getSources()).sources || [] } catch { sources.value = [] }
}
async function delSource(name: string) {
  /* 有任务在跑时不再直接禁用按钮，改成在确认框里提醒：可能删掉正在读的素材 */
  const tip = job.value.running
    ? `有任务正在运行，删除源文件「${name}」可能导致它读不到素材。仍要删除？`
    : `删除源文件「${name}」？`
  if (!await confirmBox(tip, { danger: true, ok: '删除' })) return
  try { await api.deleteSource(name); refreshSources(); toast('已删除', 'ok') }
  catch (e: any) { toast(e.message, 'err') }
}

/* 素材选择：已上传的源文件点选为本次任务输入，默认取第一个。
   注意：sources 初始是空数组（还没拉到列表 / 接口失败），此时不能把已保存的选择清成 ''，
   否则每次切页返回、刷新都会被重置成第一个素材。只在「列表已就绪且原选择不在了」时才回退。 */
const selSrc = usePersistedRef('upload.selSrc', '')
watch(sources, (s) => {
  if (!s.length) return
  if (!s.some(x => x.name === selSrc.value)) selSrc.value = s[0].name
}, { immediate: true })

function pickFile(f: File) {
  if (!/\.(txt|md|markdown)$/i.test(f.name)) return toast('仅支持 .txt / .md 文件', 'err')
  if (f.size > 50 * 1024 * 1024) return toast('文件超过 50MB 上限', 'err')
  const reader = new FileReader()
  reader.onload = async () => {
    const b64 = (reader.result as string).split(',')[1]
    try { await api.upload(f.name, { b64 }); toast('已上传 ' + f.name, 'ok'); selSrc.value = f.name; refreshSources() }
    catch (e: any) { toast(e.message, 'err') }
  }
  reader.readAsDataURL(f)
}

/* 粘贴文本（收纳在折叠面板里，不占主视觉） */
const pasteName = ref('')
const pasteText = ref('')
async function savePaste() {
  const text = pasteText.value.trim()
  if (!text) return toast('请先粘贴内容', 'err')
  if (!/\.(txt|md|markdown)$/i.test(pasteName.value)) return toast('文件名需以 .txt / .md 结尾', 'err')
  try { await api.upload(pasteName.value, { text }); toast('已保存 ' + pasteName.value, 'ok'); pasteText.value = ''; selSrc.value = pasteName.value; refreshSources() }
  catch (e: any) { toast(e.message, 'err') }
}

const rBook = usePersistedRef('upload.rBook', ''); const rLimit = usePersistedRef('upload.rLimit', '')
const rMaxChars = usePersistedRef('upload.rMaxChars', ''); const rChunkChars = usePersistedRef('upload.rChunkChars', ''); const rChunkCh = usePersistedRef('upload.rChunkCh', ''); const rDry = usePersistedRef('upload.rDry', false)
/* 改编参数：题材 / 基调 / 文风 / 目标章数 / 续写章数 / 补充要求（对应旧版去抄袭改编） */
const rMaterial = usePersistedRef('upload.rMaterial', ''); const rTone = usePersistedRef('upload.rTone', ''); const rStyleV = usePersistedRef('upload.rStyleV', '')
const rTarget = usePersistedRef('upload.rTarget', ''); const rSequel = usePersistedRef('upload.rSequel', ''); const rExtra = usePersistedRef('upload.rExtra', '')
const blankName = usePersistedRef('upload.blankName', '')   // 空白新书书名
/* 傻瓜式预设：与「作品大纲」共用一套词，见 storyPresets.ts */
const ADAPT_GENRES = GENRE_PRESETS
const ADAPT_TONES = TONE_PRESETS
const ADAPT_VOICES = VOICE_PRESETS
/* 改编要求 = 题材 / 基调 / 文风 / 补充要求，按旧版格式拼接（--style 单字符串） */
const adaptStyle = computed(() => {
  const parts: string[] = []
  if (rMaterial.value.trim()) parts.push('题材改为「' + rMaterial.value.trim() + '」')
  if (rTone.value.trim()) parts.push('基调改为「' + rTone.value.trim() + '」')
  if (rStyleV.value.trim()) parts.push('文风改为「' + rStyleV.value.trim() + '」')
  let s = parts.join('，')
  const extra = rExtra.value.trim()
  if (extra) s += (s ? '；' : '') + extra
  return s
})

/* 全文改编：先拆解再改编（可选续跑设定图谱），记录源书名与阶段。
   这三个状态都落盘：任务跑着的时候刷新/切页回来，仍能接着回显同一条任务日志 */
const phase = usePersistedRef<'decompose' | 'adapt' | 'storymap'>('upload.phase', 'decompose')
const autoAdapt = usePersistedRef('upload.autoAdapt', false)
const srcBook = usePersistedRef('upload.srcBook', '')
/* 本页当前任务 id：多任务并发时，日志面板只跟这一个任务 */
const jid = usePersistedRef('upload.jobId', '')
/* 已经做过「完成收尾」的任务 id：刷新 / 换页回来后内存状态会丢，
   只靠内存标志会导致「拆解跑完但改编永远不开始」，这里按 id 记账防重也防漏 */
const handledJid = usePersistedRef('upload.handledJid', '')
/* 开始时记下的书单（持久化）：改编书名留空时，用「新增的那本」兜底选中 */
const beforeBooks = usePersistedRef<string[]>('upload.beforeBooks', [])

function baseName(): string {
  return (selSrc.value || sources.value[0]?.name || '').replace(/\.(txt|md|markdown)$/i, '')
}

/* 版权与 AI 使用声明：每次使用同一份来源时只确认一次，拆解→自动改编沿用，
   刷新页面后重新确认（避免「默认同意」）。服务端同样会校验并留痕。 */
const gate = ref<any>(null)
const gateStage = ref<'decompose' | 'adapt'>('decompose')
const ack = ref<any>(null)
const gateSource = computed(() => selSrc.value || sources.value[0]?.name || '')
async function ensureAck(stage: 'decompose' | 'adapt') {
  if (ack.value) return ack.value
  gateStage.value = stage
  const a = await gate.value?.ask()
  if (a) ack.value = a
  return a || null
}
/* 换源文件 / 换作品后重新确认，不能沿用上一份作品的授权 */
watch(gateSource, () => { ack.value = null })

async function runDecompose() {
  const src = selSrc.value || sources.value[0]?.name
  if (!src) return toast('请先上传源文件', 'err')
  const compliance = rDry.value ? null : await ensureAck('decompose')
  if (!rDry.value && !compliance) return
  const book = rBook.value.trim() || baseName()
  if (!book) return toast('请填写作品名或上传文件', 'err')
  /* 全文改编：拆解进一个临时「源书」（书名·源），再由它改编出用户真正想要的最终书名，
     否则拆解与改编会落到同一目录，后端会拒绝「改编成同名书」而让改编步骤整段跳过。 */
  const outName = mode.value === 'adapt' ? book + '·源' : book
  srcBook.value = outName
  /* UI 模式 → 拆解 --mode：大纲拆解=outline，全文改编=reference（通读全本） */
  const dmode = mode.value === 'adapt' ? 'reference' : 'outline'
  const args: any = { mode: dmode, source: src, book: outName }
  if (rLimit.value.trim()) args.limit = rLimit.value.trim()
  if (rMaxChars.value.trim()) args.max_chars = rMaxChars.value.trim()
  if (rChunkChars.value.trim()) args.chunk_chars = rChunkChars.value.trim()
  if (rChunkCh.value.trim()) args.chunk_chapters = rChunkCh.value.trim()
  if (rDry.value) args.dry_run = true
  phase.value = 'decompose'
  api.run(store.callCreds('decompose').api_key, 'decompose', args, compliance)
    .then((r) => {
      /* 后端受理后才重置面板：被拒（同书同阶段 409 / 并发超限 429）时保留原有日志 */
      lines.value = []
      lineTimes.value = []
      ;(job.value as any)._jid = ''
      jid.value = r.id
      toast('拆解任务已启动', 'ok')
    })
    .catch((e: any) => toast(e.message, 'err'))
}

async function runAdapt() {
  const compliance = rDry.value ? null : await ensureAck('adapt')
  if (!rDry.value && !compliance) { phase.value = 'decompose'; return }
  const args: any = { book: srcBook.value }
  const out = rBook.value.trim()
  if (out) args.out_book = out
  if (adaptStyle.value) args.style = adaptStyle.value
  const t = parseInt(rTarget.value, 10); if (t > 0) args.target_chapters = t
  const sq = parseInt(rSequel.value, 10); if (sq > 0) args.sequel_chapters = sq
  if (rDry.value) args.dry_run = true
  phase.value = 'adapt'
  api.run(store.callCreds('adapt').api_key, 'adapt', args, compliance)
    .then((r) => {
      lines.value.push('—— 开始改编为新书 ——')
      lineTimes.value.push(Date.now())
      ;(job.value as any)._jid = ''
      jid.value = r.id
      toast('改编任务已启动', 'ok')
    })
    .catch((e: any) => {
      toast(e.message, 'err')
      // 没启动成功就别让界面卡在「改编中」
      phase.value = 'decompose'
    })
}

async function start() {
  const compliance = rDry.value ? null : await ensureAck('decompose')
  if (!rDry.value && !compliance) return
  if (!store.callCreds('decompose').api_key) {
    // 没有 Key 也放行：后端会走本地规则（可编辑骨架），流水线不中断
    keyHint.value = true
    toast('未配置 API Key：本次将以本地模式生成骨架，不调用模型', '')
  }
  autoAdapt.value = mode.value === 'adapt'
  /* 最终产出书名：改编模式是 rBook（临时源书是「书名·源」，不能拿来当选中目标），
     大纲拆解是 rBook 或源文件名。拆解要跑完才写出 JSON，所以先登记目标书并让选中跟随它，
     落盘后再由 selectOutputBook 正式接管（期间不会被书单刷新改成第一本）。 */
  const target = mode.value === 'adapt' ? rBook.value.trim() : (rBook.value.trim() || baseName())
  store.setOutputBook(target)
  if (target && !rDry.value) store.setBook(target)
  beforeBooks.value = state.books.map(b => b.name)
  runDecompose()
}

/* 拆解完成后自动生成设定图谱（人物关系/世界观/关键道具/一致性），失败不影响拆解产出 */
function runStorymap() {
  const book = srcBook.value || rBook.value.trim() || baseName()
  api.run(store.callCreds('storymap').api_key, 'storymap', { book })
    .then((r) => {
      lines.value.push('—— 生成设定图谱（人物关系 / 世界观 / 关键道具 / 一致性）——')
      lineTimes.value.push(Date.now())
      ;(job.value as any)._jid = ''
      jid.value = r.id
      toast('设定图谱生成已启动', 'ok')
    })
    .catch((e: any) => {
      toast('设定图谱启动失败：' + e.message, 'err')
      store.loadBooks()
      phase.value = 'decompose'   // 回到拆解完成状态，不再等待图谱
    })
}

async function createBlank() {
  const name = blankName.value.trim()
  if (!name) return toast('请填写书名', 'err')
  const before = state.books.map(b => b.name)
  try {
    await api.createBook(name)
    await store.loadBooks()
    /* 后端会做书名清洗，用「新增的那本」确保选中真实目录名 */
    const fresh = state.books.map(b => b.name).find(n => !before.includes(n))
    store.setBook(fresh || name)
    toast('空白新书已创建', 'ok')
    router.push('/outline')
  } catch (e: any) { toast(e.message, 'err') }
}

let timer: any = null
async function poll() {
  if (!jid.value) return
  try {
    const j = await pollJobById(jid.value, 0)
    /* 换任务（拆解→改编→图谱）时从 0 读新任务的日志；同一任务内只追加增量 */
    const changed = (job.value as any)._jid !== j.id
    let start = changed ? 0 : ((job.value as any)._total || 0)
    if (!changed && start > j.total) {          // 服务端日志被截断，重新对齐，避免日志停更
      start = 0
      lines.value = []
      lineTimes.value = []
    }
    if (j.lines.length) {
      for (let i = start; i < j.total; i++) { lines.value.push(j.lines[i]); lineTimes.value.push(Date.now()) }
      if (lines.value.length > 3000) {
        const cut = lines.value.length - 3000
        lines.value.splice(0, cut); lineTimes.value.splice(0, cut)
      }
      ;(job.value as any)._total = j.total
    }
    ;(job.value as any)._jid = j.id
    ;(job.value as any)._book = j.book || ''
    job.value.running = j.running
    job.value.code = j.code
    job.value.stage = j.stage || ''
    if (j.stage === 'decompose' || j.stage === 'adapt' || j.stage === 'storymap') {
      phase.value = j.stage
    }
    /* 从任务中心点进来只是「看日志」，不能替用户继续跑后续阶段；
       但之后又发起新任务时 jid 已是新 id，不再算「看历史」 */
    const qj = String(route.query.job || '').trim()
    const viewOnly = !!qj && qj === jid.value
    if (!j.running && !viewOnly && j.id && j.id !== handledJid.value) {
      handledJid.value = j.id
      if (j.code === 0) {
        if (rDry.value) {
          // 试运行只打印 prompt，不调 AI、不落盘
          toast('试运行完成（仅打印提示词，未生成任何产出）', 'ok')
        } else if (autoAdapt.value && phase.value === 'decompose') {
          runAdapt()                       // 拆解完成 → 自动进入改编
        } else if (!autoAdapt.value && phase.value === 'decompose') {
          // 拆解完成 → 顺手生成设定图谱。等接口真正受理后再进入下一阶段，
          // 否则轮询可能先看到「未运行」而误报成功。
          phase.value = 'storymap'
          runStorymap()
        } else {
          if (autoAdapt.value && srcBook.value) {
            // 全文改编完成：源书是临时「·源」目录，改编已产出最终命名的书，删除中间源书，只留一本
            await api.deleteBook(srcBook.value).catch(() => {})
          }
          /* 选中刚产出的作品，别停在上一本；改编书名留空时改为选中「新增的那一本」 */
          if (!(await store.selectOutputBook())) {
            const fresh = state.books.map(b => b.name).find(n => !beforeBooks.value.includes(n))
            if (fresh) store.setBook(fresh)
          }
          if (autoAdapt.value) {
            toast('改编完成！新作品《' + (rBook.value.trim() || '新书') + '》已生成', 'ok')
          } else {
            toast(phase.value === 'storymap'
              ? '拆解完成！设定图谱已生成，可在「设定图谱」查看'
              : '拆解完成！可在「章节概括」查看产出', 'ok')
          }
          phase.value = 'decompose'
        }
      } else if (j.code !== 0) {
        if (phase.value === 'storymap') {
          // 图谱失败不影响拆解产出（书已产出，照常选中）
          await store.selectOutputBook()
          toast('设定图谱生成失败（拆解产出不受影响），可稍后在「设定图谱」页手动生成', 'err')
          phase.value = 'decompose'
        } else {
          store.clearOutputBook()
          toast('任务失败，请查看日志', 'err')
        }
      }
    }
  } catch { /* 忽略 */ }
}

onMounted(async () => {
  await store.loadBooks().catch(() => {})
  refreshSources()
  /* 任务中心点「查看」进来时带 ?job=id：直接回显那个任务的日志 */
  const qj = String((route.query.job as string) || '').trim()
  if (qj && qj !== jid.value) {
    jid.value = qj
    lines.value = []
    lineTimes.value = []
    ;(job.value as any)._jid = ''
  }
  /* 本页没有自己的任务时，认领仍在后台跑的同类任务（刷新 / 换浏览器后也能接上） */
  if (!jid.value) {
    const a = await adoptJob(['decompose', 'adapt', 'storymap'], '')
    if (a && a.running) {
      jid.value = a.id
      srcBook.value = a.book || srcBook.value
    }
  }
  poll()
  timer = setInterval(poll, 900)
})
onUnmounted(() => clearInterval(timer))

/* 已在「新建作品」页时，从任务中心切到另一个任务：立刻换面板内容 */
watch(() => route.query.job, (v) => {
  const id = String(v || '').trim()
  if (!id || id === jid.value) return
  jid.value = id
  lines.value = []
  lineTimes.value = []
  ;(job.value as any)._jid = ''
  poll()
})

/* 模式说明 */
const MODE_DESC: Record<string, string> = {
  outline: '上传大纲，AI 拆出全书设定、人物卡、势力表与逐章任务，直接生成一部新书。',
  adapt: '上传全本 TXT，先拆解原书再改编重写，产出一部全新的书（可指定新书名与风格）。',
  blank: '只填书名即可创建空白新书，作品设定、人物、势力、章节全部由你手动录入。',
}
</script>

<template>
  <div class="nb-page">
    <div class="nb-body">
      <!-- 左：表单（标题只回显在卡片左上，容器顶部不再重复） -->
      <div class="card nb-form">
        <div class="card-head">
          <div class="card-title">新建作品</div>
          <span class="sub">选择一种创建方式，开始你的创作</span>
        </div>
        <div class="nb-modes">
          <button class="nb-mode" :class="{ on: mode === 'outline' }" @click="mode = 'outline'">
            <Icon name="list" :size="16" /> 大纲拆解
          </button>
          <button class="nb-mode" :class="{ on: mode === 'adapt' }" @click="mode = 'adapt'">
            <Icon name="movie" :size="16" /> 全文改编
          </button>
          <button class="nb-mode" :class="{ on: mode === 'blank' }" @click="mode = 'blank'">
            <Icon name="pen" :size="16" /> 空白新书
          </button>
        </div>
        <div class="nb-desc">{{ MODE_DESC[mode] }}</div>

        <!-- 空白新书：一行式表单 -->
        <template v-if="mode === 'blank'">
          <div class="nb-blank">
            <input class="input" v-model="blankName" placeholder="输入新书名，如：长夜行歌"
                   @keydown.enter="createBlank" />
            <button class="btn" :disabled="!blankName.trim()" @click="createBlank">
              <Icon name="plus" :size="14" /> 创建新书</button>
          </div>
          <div class="hint">创建后自动跳转「作品大纲」，设定 / 人物 / 势力 / 章节在各模块手动填写。</div>
        </template>

        <!-- 大纲拆解 / 全文改编：步骤式单列 -->
        <template v-else>
          <div class="nb-grid">
            <!-- ① 上传素材 -->
            <div class="nb-col">
              <div class="nb-sec"><span class="nb-step">1</span>上传素材</div>
              <div class="dropzone nb-dz" :class="{ over: dzOver }"
                   @click="srcInput?.click()"
                   @dragover.prevent="dzOver = true" @dragleave="dzOver = false"
                   @drop.prevent="dzOver = false; pickFile($event.dataTransfer.files[0])">
                <Icon name="cloud" :size="26" />
                <b>点击选择或拖入文件</b>
                <span>.txt / .md ≤ 50MB · {{ mode === 'adapt' ? '建议上传全本' : '建议上传大纲' }}</span>
              </div>
              <input ref="srcInput" type="file" accept=".txt,.md,.markdown" hidden
                     @change="e => { const f = (e.target as HTMLInputElement).files?.[0]; if (f) pickFile(f); (e.target as HTMLInputElement).value = '' }" />

              <div class="nb-srcs">
                <div v-for="s in sources" :key="s.name" class="nb-src" :class="{ on: selSrc === s.name }"
                     :title="selSrc === s.name ? '本次任务使用该素材' : '点击选择为本次任务输入'"
                     @click="selSrc = s.name">
                  <span class="rd"></span>
                  <Icon name="file" :size="14" />
                  <span class="nm" :title="s.name">{{ s.name }}</span>
                  <span class="sz">{{ fmtSize(s.size) }}</span>
                  <button class="link-btn red" @click.stop="delSource(s.name)">删除</button>
                </div>
                <div v-if="!sources.length" class="nb-nosrc">还没有源文件，上传后即可开始</div>
                <div v-else class="nb-nosrc">点击素材行选择本次任务使用的文件</div>
              </div>

              <Collapse>
                <template #head>或直接粘贴文本</template>
                <textarea class="textarea" v-model="pasteText" style="min-height:96px" placeholder="粘贴全本 / 大纲内容…"></textarea>
                <div class="form-row" style="margin-top:8px">
                  <input class="input" v-model="pasteName" placeholder="保存文件名（如：我的小说.txt）" />
                  <button class="btn ghost" style="flex:none" @click="savePaste">保存为源文件</button>
                </div>
              </Collapse>
            </div>

            <!-- ② 拆解设置 -->
            <div class="nb-col">
              <div class="nb-sec"><span class="nb-step">2</span>拆解设置</div>
              <div class="form-row">
              <div class="field"><label>目标书名（留空 = 源文件名）</label>
                <input class="input" v-model="rBook" placeholder="如：长夜行歌" /></div>
              <div class="field"><label>只拆前 N 章（留空 = 全部）</label>
                <input class="input" v-model="rLimit" placeholder="全部" /></div>
              </div>
              <div v-if="mode === 'adapt'" class="hint" style="margin-top:-4px">
              全文改编会先把上传原著拆解成临时源书，再改写为以此书名命名的新书；跑完只保留这一本。
              </div>
              <Collapse>
                <template #head>高级选项（分段策略 / 上限）</template>
                <div class="form-row">
                  <div class="field"><label>分段阈值 chunk-chars</label>
                    <input class="input" v-model="rChunkChars" placeholder="120000" /></div>
                  <div class="field"><label>每段章数区间 chunk-chapters</label>
                    <input class="input" v-model="rChunkCh" placeholder="10-16" /></div>
                </div>
                <div class="field"><label>总字数上限 max-chars（留空 = 不限制）</label>
                  <input class="input" v-model="rMaxChars" placeholder="超长会自动分段而不是截断" /></div>
                <label class="check"><input type="checkbox" v-model="rDry" /> 试跑模式 dry-run（真正调用 API，但结果不落盘）</label>
              </Collapse>

              <!-- ③ 改编设置（仅全文改编模式） -->
              <template v-if="mode === 'adapt'">
                <div class="nb-sec" style="margin-top:20px"><span class="nb-step">3</span>改编设置</div>
                <div class="field"><label>题材（改编成什么题材，留空 = 只换皮不改题材）</label>
                  <SelectBox v-model="rMaterial" :options="ADAPT_GENRES" allow-custom allow-empty
                             empty-label="留空（只换皮不改题材）" placeholder="点选预设，或直接输入自定义题材" /></div>
                <div class="form-row">
                  <div class="field"><label>基调（全书情绪走向，留空 = 顺应原著基调换新）</label>
                    <SelectBox v-model="rTone" :options="ADAPT_TONES" allow-custom allow-empty
                               empty-label="留空（顺应原著基调）" placeholder="点选预设，或直接输入自定义基调" /></div>
                  <div class="field"><label>文风（叙事语言风格，留空 = 默认快节奏网文风）</label>
                    <SelectBox v-model="rStyleV" :options="ADAPT_VOICES" allow-custom allow-empty
                               empty-label="留空（默认快节奏网文风）" placeholder="点选预设，或直接输入自定义文风" /></div>
                </div>
                <div class="form-row">
                  <div class="field"><label>目标章数（留空 = 与源书一致）</label>
                    <input class="input" v-model="rTarget" placeholder="如：60" /></div>
                  <div class="field"><label>续写章数（0 / 留空 = 不续写）</label>
                    <input class="input" v-model="rSequel" placeholder="如：10" /></div>
                </div>
                <div class="field"><label>补充要求（可选）</label>
                  <textarea class="textarea" v-model="rExtra" style="min-height:64px"
                            placeholder="其他个性化要求，如：主角改为女性、加入直播元素、反派洗白结局……留空 = 默认换皮改编（全部名词重命名）"></textarea></div>
              </template>

              <div style="margin-top:16px">
                <button class="btn lg nb-run" :disabled="!sources.length" @click="start">
                  <Icon name="play" :size="14" /> {{ mode === 'adapt' ? '开始拆解并改编' : '开始拆解' }}</button>
                <div v-if="keyHint" class="hint" style="margin-top:8px">未配置 API Key：将以本地模式生成可编辑骨架（不调用模型），配好 Key 后可重跑提升质量。</div>
              </div>
            </div>
          </div>
        </template>
      </div>

      <!-- 右：实时日志 -->
      <div class="card nb-log">
        <div class="nb-log-head">
          <div class="card-title">实时日志</div>
          <span class="state" :class="job.running ? 'run' : job.code === 0 ? 'ok' : job.code == null ? 'idle' : 'err'">
            <span class="dot"></span>{{ jobText }}
          </span>
          <span style="flex:1"></span>
          <button class="btn sm ghost" :disabled="!job.running" @click="stopJob">停止</button>
          <button class="btn sm ghost" :disabled="!lines.length" @click="clearLog">清屏</button>
        </div>
        <div class="nb-log-tools">
          <label class="check"><input type="checkbox" v-model="logShowTs" /> 时间戳</label>
          <label class="check"><input type="checkbox" v-model="logFollow" /> 跟随</label>
          <span style="flex:1"></span>
          <div class="seg">
            <button :class="{ on: logFilter === 'all' }" @click="logFilter = 'all'">全部</button>
            <button :class="{ on: logFilter === 'err' }" @click="logFilter = 'err'">仅错误</button>
            <button :class="{ on: logFilter === 'ok' }" @click="logFilter = 'ok'">仅通过</button>
          </div>
        </div>
        <div class="nb-logscroll">
          <div class="logbox" ref="logBoxEl">
            <div v-if="!shownLines.length" class="nb-log-empty">等待任务开始… 点击左表单「开始拆解」后，这里会实时显示进度与输出</div>
            <div v-for="(x, i) in shownLines" :key="i" :class="lineCls(x.l)">
              <span v-if="logShowTs && x.t" class="ln-ts">{{ fmtTs(x.t) }}</span>{{ x.l }}
            </div>
          </div>
        </div>
      </div>
    </div>

    <ComplianceGate ref="gate" :stage="gateStage" :source="gateSource" :out-book="rBook" />
  </div>
</template>

<style scoped>
/* 占满视口、内部滚动，外部不出现滚动条 */
.nb-page { flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }

/* 关键：grid 行高必须约束为可用高度，否则右侧日志列会被内容撑高、
   超出 .nb-page 的 overflow:hidden 后底部日志永远看不到 */
.nb-body { flex: 1; min-height: 0; display: grid; grid-template-columns: 35fr 65fr; grid-template-rows: minmax(0, 1fr); gap: 16px; }
.nb-form { min-width: 0; overflow-y: auto; }
.nb-log { min-width: 0; min-height: 0; margin-top: 0; display: flex; flex-direction: column; }

/* 日志头部：标题 + 状态 + 停止/清屏 */
.nb-log-head { display: flex; align-items: center; gap: 12px; }
.nb-log-head .state { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600; color: var(--text-2); }
.nb-log-head .state .dot { width: 8px; height: 8px; border-radius: 50%; background: #c3c7cd; flex: none; }
.nb-log-head .state.run .dot { background: var(--orange); animation: pulse 1.1s infinite; }
.nb-log-head .state.ok .dot { background: var(--green); }
.nb-log-head .state.err .dot { background: var(--red); }

/* 工具行：时间戳 / 跟随 / 过滤 */
.nb-log-tools { display: flex; align-items: center; gap: 16px; margin-top: 10px; padding-bottom: 10px; border-bottom: 1px dashed var(--border); }
.nb-log-tools .check { padding: 0; font-size: 12.5px; color: var(--text-2); }
.nb-log-tools .seg button { padding: 4px 12px; font-size: 12.5px; }

/* 日志体：填满剩余高度，内部滚动 */
.nb-logscroll { flex: 1; min-height: 0; overflow-y: auto; margin-top: 12px; display: flex; }
.nb-log :deep(.logbox) { max-height: none; height: 100%; flex: 1; }
.nb-log-empty { display: flex; align-items: center; justify-content: center; color: #5b6472; padding: 24px; text-align: center; }
.ln-ts { color: #66707f; margin-right: 8px; user-select: none; }

/* 模式切换：紧凑分段控件 */
.nb-modes { display: inline-flex; background: #f2f3f5; border-radius: var(--radius-sm); padding: 3px; gap: 2px; }
.nb-mode { display: inline-flex; align-items: center; gap: 6px; border: none; background: none;
  padding: 7px 18px; border-radius: 6px; font-size: 13px; color: var(--text-2); cursor: pointer; }
.nb-mode:hover { color: var(--text); }
.nb-mode.on { background: var(--card); color: var(--text); font-weight: 600; box-shadow: var(--shadow); }
.nb-mode.on:deep(svg) { color: var(--primary); }
.nb-desc { font-size: 12.5px; color: var(--text-3); margin: 10px 2px 0; }

/* 空白新书：一行式 */
.nb-blank { display: flex; gap: 10px; margin-top: 18px; }
.nb-blank .input { max-width: 360px; }

/* 步骤式单列排版 */
.nb-grid { display: flex; flex-direction: column; gap: 22px; margin-top: 18px; }
.nb-sec { display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 700; margin-bottom: 12px; }
.nb-step { width: 20px; height: 20px; border-radius: 50%; background: var(--primary); color: #fff;
  display: inline-flex; align-items: center; justify-content: center; font-size: 12px; flex: none; }

/* 紧凑拖放区 */
.nb-dz { padding: 18px 16px; }
.nb-dz :deep(svg) { width: 26px; height: 26px; margin-bottom: 6px; }
.nb-dz b { font-size: 13px; }
.nb-dz span { font-size: 12px; }

/* 源文件列表（紧凑行式，可点选） */
.nb-srcs { margin: 10px 0 14px; display: flex; flex-direction: column; }
.nb-src { display: flex; align-items: center; gap: 8px; padding: 7px 10px; border: 1px solid var(--border);
  border-radius: 8px; margin-top: 6px; font-size: 13px; color: var(--text-2); background: var(--bg);
  cursor: pointer; transition: border-color .12s, background .12s; }
.nb-src:hover { border-color: var(--border-strong); }
.nb-src .rd { width: 12px; height: 12px; border-radius: 50%; border: 1.5px solid var(--border-strong); flex: none; background: var(--card); }
.nb-src.on { border-color: var(--primary); background: var(--primary-bg); }
.nb-src.on .rd { border-color: var(--primary); background: var(--primary); box-shadow: inset 0 0 0 2px #fff; }
.nb-src.on .nm { color: var(--primary); font-weight: 600; }
.nb-src .link-btn:disabled { opacity: .4; cursor: not-allowed; }
.nb-src .nm { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text); }
.nb-src .sz { font-size: 12px; color: var(--text-3); }
.nb-nosrc { font-size: 12.5px; color: var(--text-3); padding: 6px 2px; }

/* 任务运行中：模式切换与开始按钮禁用态 */
.nb-run:disabled { opacity: .6; cursor: not-allowed; }

/* CTA 按钮：不铺满，右对齐主操作 */
.nb-run { width: 100%; }

/* 1280 左右的窄桌面：表单列加宽，三种新建方式保持单行 */
@media (max-width: 1360px) {
  .nb-body { grid-template-columns: 42fr 58fr; }
  .nb-mode { padding: 7px 10px; font-size: 12px; }
}

@media (max-width: 900px) {
  /* 手机：表单与日志上下排，整页滚动；表单区不再被压成 0 高 */
  .nb-page { overflow: visible; }
  .nb-body { grid-template-columns: 1fr; grid-template-rows: none; flex: none; overflow: visible; }
  .nb-form { overflow: visible; }
  .nb-log { height: 320px; }
  .nb-blank { flex-wrap: wrap; }
  .nb-blank .input { max-width: 100%; }
  /* 三种新建方式放不下时横向滚动，而不是把「大纲拆解」拆成两行 */
  .nb-modes { width: 100%; overflow-x: auto; }
  .nb-mode { flex: none; padding: 7px 12px; font-size: 12.5px; white-space: nowrap; }
}
</style>
