<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import Icon from '../components/Icon.vue'
import MobilePicker from './MobilePicker.vue'
import ComplianceGate from '../components/ComplianceGate.vue'
import { api, pollJobById } from '../api'
import { adoptJob } from '../jobs'
import { state, store } from '../store'
import { GENRE_PRESETS, TONE_PRESETS, VOICE_PRESETS } from '../storyPresets'
import { confirmBox, toast } from '../ui'
import { fmtSize } from '../utils'

const router = useRouter()
const mode = ref<'outline' | 'adapt' | 'blank'>('outline')
const sources = ref<any[]>([])
const selSrc = ref('')
const srcInput = ref<HTMLInputElement | null>(null)
const fileBusy = ref(false)
const pasteOpen = ref(false)
const pasteName = ref('')
const pasteText = ref('')
const advOpen = ref(false)

const rBook = ref('')
const rLimit = ref('')
const rMaxChars = ref('')
const rChunkChars = ref('')
const rChunkCh = ref('')
const rDry = ref(false)
const rMaterial = ref('')
const rTone = ref('')
const rStyleV = ref('')
const rTarget = ref('')
const rSequel = ref('')
const rExtra = ref('')
const blankName = ref('')

const job = ref({ running: false, code: null as number | null, stage: '' })
const jid = ref('')
const lines = ref<string[]>([])
const logOpen = ref(true)
const phase = ref<'decompose' | 'adapt'>('decompose')
const srcBook = ref('')
const starting = ref(false)
const handledJid = ref('')

const MODE_DESC: Record<string, string> = {
  outline: '上传大纲，AI 拆出全书设定、人物卡、势力表与逐章任务，直接生成一部新书。',
  adapt: '上传全本 TXT，先拆解原书再改编重写，产出一部全新的书。',
  blank: '只填书名即可创建空白新书，设定、人物、势力、章节全部手动录入。',
}
/* 预设与桌面端「新建作品 / 改编设置」共用同一份词表，避免两端选出来的值不一样 */
const ADAPT_GENRES = GENRE_PRESETS
const ADAPT_TONES = TONE_PRESETS
const ADAPT_VOICES = VOICE_PRESETS

const jobText = computed(() => {
  if (job.value.running) return phase.value === 'adapt' ? '改编中' : '拆解中'
  if (job.value.code === 0) return '已完成'
  if (job.value.code == null) return '空闲'
  return '失败（退出码 ' + job.value.code + '）'
})
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
const canStart = computed(() => mode.value !== 'blank' && !!selSrc.value && !job.value.running && !starting.value)
const baseName = () => (selSrc.value || sources.value[0]?.name || '').replace(/\.(txt|md|markdown)$/i, '')

async function refreshSources() {
  try { sources.value = (await api.getSources()).sources || [] }
  catch { sources.value = [] }
}
watch(sources, s => {
  if (s.length && !s.some(x => x.name === selSrc.value)) selSrc.value = s[0].name
}, { immediate: true })

function pickFile(f: File) {
  if (!/\.(txt|md|markdown)$/i.test(f.name)) return toast('仅支持 .txt / .md 文件', 'err')
  if (f.size > 50 * 1024 * 1024) return toast('文件超过 50MB 上限', 'err')
  fileBusy.value = true
  const reader = new FileReader()
  reader.onload = async () => {
    const b64 = (reader.result as string).split(',')[1]
    try {
      await api.upload(f.name, { b64 })
      toast('已上传 ' + f.name, 'ok')
      selSrc.value = f.name
      await refreshSources()
    } catch (e: any) { toast(e.message, 'err') }
    finally { fileBusy.value = false }
  }
  reader.readAsDataURL(f)
}
async function savePaste() {
  const text = pasteText.value.trim()
  if (!text) return toast('请先粘贴内容', 'err')
  if (!/\.(txt|md|markdown)$/i.test(pasteName.value)) return toast('文件名需以 .txt / .md 结尾', 'err')
  try {
    await api.upload(pasteName.value, { text })
    toast('已保存 ' + pasteName.value, 'ok')
    selSrc.value = pasteName.value
    pasteText.value = ''
    pasteOpen.value = false
    await refreshSources()
  } catch (e: any) { toast(e.message, 'err') }
}
async function delSource(name: string) {
  if (!await confirmBox('删除源文件「' + name + '」？', { danger: true, ok: '删除' })) return
  try { await api.deleteSource(name); await refreshSources(); toast('已删除', 'ok') }
  catch (e: any) { toast(e.message, 'err') }
}

/* ---------------- 创建流程 ---------------- */
function resetJob() {
  job.value = { running: false, code: null, stage: '' }
  lines.value = []
  jid.value = ''
  handledJid.value = ''
}
/* 版权与 AI 使用声明：拆解 / 改编前确认一次，服务端校验并留痕 */
const gate = ref<any>(null)
const gateStage = ref<'decompose' | 'adapt'>('decompose')
const ack = ref<any>(null)
async function ensureAck(stage: 'decompose' | 'adapt') {
  if (ack.value) return ack.value
  gateStage.value = stage
  const a = await gate.value?.ask()
  if (a) ack.value = a
  return a || null
}
watch(() => selSrc.value || sources.value[0]?.name || '', () => { ack.value = null })

async function start() {
  if (!canStart.value) return
  const compliance = rDry.value ? null : await ensureAck('decompose')
  if (!rDry.value && !compliance) return
  const book = rBook.value.trim() || baseName()
  if (!book) return toast('请填写作品名或上传素材', 'err')
  const finalBook = book
  srcBook.value = mode.value === 'adapt' ? book + '·源' : book
  phase.value = 'decompose'
  if (!rDry.value) {
    store.setOutputBook(finalBook)
    store.setBook(finalBook)
  }
  const args: any = {
    mode: mode.value === 'adapt' ? 'reference' : 'outline',
    source: selSrc.value,
    book: srcBook.value,
  }
  if (rLimit.value.trim()) args.limit = rLimit.value.trim()
  if (rMaxChars.value.trim()) args.max_chars = rMaxChars.value.trim()
  if (rChunkChars.value.trim()) args.chunk_chars = rChunkChars.value.trim()
  if (rChunkCh.value.trim()) args.chunk_chapters = rChunkCh.value.trim()
  if (rDry.value) args.dry_run = true
  starting.value = true
  api.run(store.callCreds('decompose').api_key, 'decompose', args, compliance)
    .then((r) => {
      lines.value = []
      jid.value = r.id
      job.value = { running: true, code: null, stage: 'decompose' }
      logOpen.value = true
      toast('拆解任务已启动', 'ok')
      startPoll()
    })
    .catch((e: any) => toast(e.message, 'err'))
    .finally(() => { starting.value = false })
}
async function runAdapt() {
  const compliance = rDry.value ? null : await ensureAck('adapt')
  if (!rDry.value && !compliance) return
  const finalBook = rBook.value.trim() || baseName()
  phase.value = 'adapt'
  const args: any = { book: srcBook.value, out_book: finalBook }
  if (adaptStyle.value) args.style = adaptStyle.value
  const t = parseInt(rTarget.value, 10); if (t > 0) args.target_chapters = t
  const sq = parseInt(rSequel.value, 10); if (sq > 0) args.sequel_chapters = sq
  if (rDry.value) args.dry_run = true
  api.run(store.callCreds('adapt').api_key, 'adapt', args, compliance)
    .then((r) => {
      jid.value = r.id
      job.value = { running: true, code: null, stage: 'adapt' }
      handledJid.value = ''
      startPoll()
      toast('改编任务已启动', 'ok')
    })
    .catch((e: any) => {
      toast(e.message, 'err')
      phase.value = 'decompose'
      store.clearOutputBook()
    })
}
async function finishSuccess() {
  if (rDry.value) {
    toast('试跑完成，未生成任何产出', 'ok')
    store.clearOutputBook()
    return
  }
  if (phase.value === 'adapt') {
    await api.deleteBook(srcBook.value).catch(() => {})
  }
  await store.loadBooks().catch(() => [])
  await store.loadStats().catch(() => null)
  const selected = await store.selectOutputBook().catch(() => false)
  if (!selected && store.curBook()) store.setBook(store.curBook())
  toast(phase.value === 'adapt' ? '改编完成，新作品已生成' : '拆解完成，作品已生成', 'ok')
  router.push('/overview')
}
let timer: any = null
function startPoll() {
  if (timer) clearInterval(timer)
  poll()
  timer = setInterval(poll, 1000)
}
async function poll() {
  if (!jid.value) return
  try {
    const j = await pollJobById(jid.value, 0)
    lines.value = j.lines || []
    job.value.running = j.running
    job.value.code = j.code
    job.value.stage = j.stage || ''
    if (!j.running && j.id && j.id !== handledJid.value) {
      handledJid.value = j.id
      if (timer) { clearInterval(timer); timer = null }
      if (j.code === 0) {
        if (phase.value === 'decompose' && mode.value === 'adapt') {
          runAdapt()
        } else {
          await finishSuccess()
        }
      } else if (j.code !== 0) {
        store.clearOutputBook()
        toast('任务失败，请查看日志', 'err')
      }
    }
  } catch { /* 服务未就绪时下一轮再试 */ }
}
function stopJob() {
  if (!jid.value) return
  api.stopJob(jid.value).then(() => toast('已请求停止', 'ok')).catch((e: any) => toast(e.message, 'err'))
}
async function createBlank() {
  const name = blankName.value.trim()
  if (!name) return toast('请填写书名', 'err')
  try {
    const before = state.books.map(b => b.name)
    await api.createBook(name)
    await store.loadBooks()
    const fresh = state.books.map(b => b.name).find(n => !before.includes(n))
    store.setBook(fresh || name)
    toast('空白新书已创建', 'ok')
    router.push('/outline')
  } catch (e: any) { toast(e.message, 'err') }
}

onMounted(async () => {
  await store.loadBooks().catch(() => {})
  refreshSources()
  /* 回到本页时接管仍在后台跑的拆解 / 改编任务，日志不会丢 */
  const a = await adoptJob(['decompose', 'adapt'], '')
  if (a?.running) {
    const tempBook = String(a.book || '')
    const isAdapt = a.stage === 'adapt' || tempBook.endsWith('·源')
    if (isAdapt) mode.value = 'adapt'
    phase.value = a.stage === 'adapt' ? 'adapt' : 'decompose'
    srcBook.value = tempBook
    if (isAdapt) rBook.value = String(a.out_book || tempBook.replace(/·源$/, ''))
    store.setOutputBook(isAdapt ? rBook.value : tempBook)
    jid.value = a.id
    job.value = { running: true, code: null, stage: a.stage || 'decompose' }
    startPoll()
  }
})
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>

<template>
  <div class="m-page m-secondary-page">
    <div class="m-sec-head">
      <div class="m-sec-head-txt">选择一种创建方式，开始你的创作</div>
    </div>

    <!-- 创建方式 -->
    <div class="m-seg m-new-modes">
      <button :disabled="job.running" :class="{ on: mode === 'outline' }" @click="mode = 'outline'">大纲拆解</button>
      <button :disabled="job.running" :class="{ on: mode === 'adapt' }" @click="mode = 'adapt'">全文改编</button>
      <button :disabled="job.running" :class="{ on: mode === 'blank' }" @click="mode = 'blank'">空白新书</button>
    </div>
    <p class="m-new-desc">{{ MODE_DESC[mode] }}</p>

    <!-- 空白新书 -->
    <template v-if="mode === 'blank'">
      <div class="m-card">
        <div class="m-field">
          <label>新书书名</label>
          <input class="m-input" v-model="blankName" placeholder="如：长夜行歌" @keydown.enter="createBlank" />
        </div>
        <button class="m-btn block" style="margin-top:14px" :disabled="!blankName.trim()" @click="createBlank">
          <Icon name="plus" :size="15" /> 创建空白新书
        </button>
        <p class="m-hint" style="margin-top:10px">创建后进入「作品大纲」，设定、人物、势力与章节在各模块手动填写。</p>
      </div>
    </template>

    <!-- 大纲拆解 / 全文改编 -->
    <template v-else>
      <!-- 1. 素材 -->
      <div class="m-card m-upload-step">
        <div class="m-step-head"><span class="m-step-n">1</span><b>上传素材</b></div>
        <button class="m-upload-drop" :class="{ busy: fileBusy }" @click="srcInput?.click()">
          <Icon name="cloud" :size="28" />
          <b>{{ fileBusy ? '正在上传…' : '选择 .txt / .md 文件' }}</b>
          <span>.txt / .md ≤ 50MB · {{ mode === 'adapt' ? '建议上传全本' : '建议上传大纲' }}</span>
        </button>
        <input ref="srcInput" type="file" accept=".txt,.md,.markdown" hidden
               @change="e => { const f = (e.target as HTMLInputElement).files?.[0]; if (f) pickFile(f); (e.target as HTMLInputElement).value = '' }" />

        <div v-if="sources.length" class="m-src-list">
          <div v-for="s in sources" :key="s.name" class="m-src-item" :class="{ on: selSrc === s.name }"
               @click="selSrc = s.name">
            <span class="m-radio" :class="{ on: selSrc === s.name }"></span>
            <Icon name="file" :size="15" />
            <span class="m-src-name">{{ s.name }}</span>
            <span class="m-src-size">{{ fmtSize(s.size) }}</span>
            <button class="m-src-del" @click.stop="delSource(s.name)"><Icon name="trash" :size="13" /></button>
          </div>
        </div>
        <p v-else class="m-hint" style="margin-top:9px">还没有源文件，上传后即可开始。</p>

        <button class="m-link" style="margin-top:6px" @click="pasteOpen = !pasteOpen">
          {{ pasteOpen ? '收起粘贴区' : '或直接粘贴文本' }}
          <Icon :name="pasteOpen ? 'down' : 'right'" :size="12" />
        </button>
        <div v-if="pasteOpen" class="m-paste">
          <textarea class="m-textarea" v-model="pasteText" style="min-height:96px" placeholder="粘贴全本 / 大纲内容…"></textarea>
          <div class="m-form-2" style="margin-top:8px">
            <input class="m-input" v-model="pasteName" placeholder="文件名，如：我的小说.txt" />
            <button class="m-btn ghost sm" style="height:44px" @click="savePaste">保存为素材</button>
          </div>
        </div>
      </div>

      <!-- 2. 设置 -->
      <div class="m-card m-upload-step">
        <div class="m-step-head"><span class="m-step-n">2</span><b>拆解设置</b></div>
        <div class="m-form">
          <div class="m-field">
            <label>目标书名<em>留空 = 源文件名</em></label>
            <input class="m-input" v-model="rBook" placeholder="如：长夜行歌" />
          </div>
          <div class="m-field">
            <label>只拆前 N 章<em>留空 = 全部</em></label>
            <input class="m-input" v-model="rLimit" inputmode="numeric" placeholder="全部" />
          </div>
          <button class="m-link" style="align-self:flex-start" @click="advOpen = !advOpen">
            {{ advOpen ? '收起高级选项' : '高级选项（分段策略 / 上限）' }}
            <Icon :name="advOpen ? 'down' : 'right'" :size="12" />
          </button>
          <template v-if="advOpen">
            <div class="m-form-2">
              <div class="m-field">
                <label>分段阈值</label>
                <input class="m-input" v-model="rChunkChars" inputmode="numeric" placeholder="120000" />
              </div>
              <div class="m-field">
                <label>每段章数</label>
                <input class="m-input" v-model="rChunkCh" placeholder="10-16" />
              </div>
            </div>
            <div class="m-field">
              <label>总字数上限<em>留空 = 不限制</em></label>
              <input class="m-input" v-model="rMaxChars" inputmode="numeric" placeholder="超长会自动分段" />
            </div>
            <button class="m-toggle-row" @click="rDry = !rDry">
              <span><b>试跑模式</b><small>真正调用 API，但结果不落盘</small></span>
              <i class="m-toggle" :class="{ on: rDry }"><em></em></i>
            </button>
          </template>
        </div>
      </div>

      <!-- 3. 改编设置 -->
      <div v-if="mode === 'adapt'" class="m-card m-upload-step">
        <div class="m-step-head"><span class="m-step-n">3</span><b>改编设置</b></div>
        <div class="m-form">
          <div class="m-field">
            <label>题材<em>留空 = 只换皮不改题材</em></label>
            <input class="m-input" v-model="rMaterial" placeholder="可直接填写，或点「+ 预设」挑选" />
            <MobilePicker chip :model-value="rMaterial" :options="ADAPT_GENRES" title="选择题材预设"
                          empty-label="不指定（只换皮不改题材）" placeholder="+ 预设"
                          @update:model-value="v => rMaterial = v" />
          </div>
          <div class="m-field">
            <label>基调<em>全书情绪走向</em></label>
            <input class="m-input" v-model="rTone" placeholder="如：热血爽文" />
            <MobilePicker chip :model-value="rTone" :options="ADAPT_TONES" title="选择基调预设"
                          empty-label="不指定" placeholder="+ 预设"
                          @update:model-value="v => rTone = v" />
          </div>
          <div class="m-field">
            <label>文风<em>叙事语言风格</em></label>
            <input class="m-input" v-model="rStyleV" placeholder="如：快节奏爽文" />
            <MobilePicker chip :model-value="rStyleV" :options="ADAPT_VOICES" title="选择文风预设"
                          empty-label="不指定" placeholder="+ 预设"
                          @update:model-value="v => rStyleV = v" />
          </div>
          <div class="m-form-2">
            <div class="m-field">
              <label>目标章数<em>留空同源书</em></label>
              <input class="m-input" v-model="rTarget" inputmode="numeric" placeholder="如 60" />
            </div>
            <div class="m-field">
              <label>续写章数<em>0 = 不续写</em></label>
              <input class="m-input" v-model="rSequel" inputmode="numeric" placeholder="如 10" />
            </div>
          </div>
          <div class="m-field">
            <label>补充要求<em>可选</em></label>
            <textarea class="m-textarea" v-model="rExtra" style="min-height:74px"
                      placeholder="如：主角改为女性、加入直播元素、反派洗白结局……"></textarea>
          </div>
        </div>
      </div>

      <button class="m-btn block m-upload-run" :disabled="!canStart" @click="start">
        <Icon name="play" :size="15" />
        {{ starting ? '正在启动…' : (mode === 'adapt' ? '开始拆解并改编' : '开始拆解') }}
      </button>
      <p v-if="!selSrc" class="m-hint" style="text-align:center;margin-top:8px">先上传或选择一个素材文件</p>

      <!-- 实时日志 -->
      <div class="m-card m-upload-log">
        <button class="m-upload-log-head" @click="logOpen = !logOpen">
          <span class="m-upload-state" :class="job.running ? 'run' : job.code === 0 ? 'ok' : job.code == null ? 'idle' : 'err'">
            <i></i>{{ jobText }}
          </span>
          <span class="m-hint" style="margin-left:auto">{{ lines.length }} 行</span>
          <Icon :name="logOpen ? 'down' : 'right'" :size="14" class="m-row-arrow" />
        </button>
        <template v-if="logOpen">
          <div class="m-upload-log-acts">
            <button class="m-btn sm ghost" :disabled="!job.running" @click="stopJob"><Icon name="stop" :size="12" /> 停止</button>
            <button class="m-btn sm ghost" :disabled="!lines.length" @click="lines = []"><Icon name="refresh" :size="12" /> 清屏</button>
          </div>
          <div class="m-upload-console">
            <div v-if="!lines.length" class="m-upload-empty">等待任务开始…</div>
            <div v-for="(l, i) in lines" :key="i" class="m-upload-line" :class="{ err: /\[x\]|错误|失败/i.test(l), ok: /\[完成\]|退出码 0|成功/i.test(l) }">{{ l }}</div>
          </div>
        </template>
      </div>
    </template>

    <ComplianceGate ref="gate" :stage="gateStage"
                    :source="selSrc || sources[0]?.name || ''" :out-book="rBook" />
  </div>
</template>

<style scoped>
.m-new-modes { margin-bottom: 8px; }
.m-new-desc { padding: 0 4px 12px; font-size: 12px; line-height: 1.6; color: var(--m-text3); }
.m-upload-step + .m-upload-step { margin-top: 12px; }
.m-step-head { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.m-step-head b { font-size: 14px; font-weight: 650; }
.m-step-n {
  width: 22px; height: 22px; flex: none; border-radius: 50%;
  display: grid; place-items: center;
  background: var(--m-primary-soft); color: var(--m-primary);
  font-size: 11px; font-weight: 700;
}
.m-upload-drop {
  display: flex; flex-direction: column; align-items: center; gap: 5px;
  width: 100%; padding: 22px 14px;
  border: 1px dashed var(--m-line-strong); border-radius: 16px;
  background: #fafbf8; color: var(--m-text2); text-align: center;
}
.m-upload-drop:active { border-color: var(--m-primary); background: var(--m-primary-soft); }
.m-upload-drop b { font-size: 13.5px; font-weight: 600; color: var(--m-text); }
.m-upload-drop span { font-size: 10.5px; color: var(--m-text3); }
.m-upload-drop svg { color: var(--m-primary); }
.m-src-list { display: flex; flex-direction: column; gap: 6px; margin-top: 10px; }
.m-src-item {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 11px; border: 1px solid var(--m-line); border-radius: 12px;
  background: #fff; color: var(--m-text2); font-size: 12px;
}
.m-src-item.on { border-color: var(--m-primary); background: var(--m-primary-soft); }
.m-radio { width: 14px; height: 14px; border-radius: 50%; border: 1.5px solid #c5ccc6; flex: none; }
.m-radio.on { border: 4px solid var(--m-primary); background: #fff; }
.m-src-name { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--m-text); }
.m-src-size { font-size: 10px; color: var(--m-text3); flex: none; }
.m-src-del { width: 28px; height: 28px; border: 0; border-radius: 8px; background: transparent; color: var(--m-text3); display: grid; place-items: center; }
.m-src-del:active { background: var(--m-red-soft); color: var(--m-red); }
.m-paste { margin-top: 8px; padding-top: 10px; border-top: 1px solid #f2f4f0; }
.m-upload-run { margin-top: 14px; height: 48px; }
.m-upload-log { margin-top: 14px; padding: 0; overflow: hidden; }
.m-upload-log-head { display: flex; align-items: center; gap: 8px; width: 100%; padding: 12px 14px; border: 0; background: none; }
.m-upload-state { display: inline-flex; align-items: center; gap: 5px; font-size: 11.5px; font-weight: 600; }
.m-upload-state i { width: 7px; height: 7px; border-radius: 50%; background: #aab2ac; }
.m-upload-state.run { color: var(--m-primary); }
.m-upload-state.run i { background: var(--m-primary); box-shadow: 0 0 0 3px var(--m-primary-soft); animation: mPulse 1.1s infinite; }
.m-upload-state.ok { color: var(--m-green); }
.m-upload-state.ok i { background: var(--m-green); }
.m-upload-state.err { color: var(--m-red); }
.m-upload-state.err i { background: var(--m-red); }
@keyframes mPulse { 50% { opacity: .4; } }
.m-upload-log-acts { display: flex; gap: 8px; padding: 0 14px 9px; }
.m-upload-console {
  max-height: 30dvh; min-height: 140px; overflow: auto; margin: 0 14px 14px; padding: 10px 12px;
  border-radius: 12px; background: #101a17; color: #b9cdc6;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 10.5px; line-height: 1.65;
}
.m-upload-line { white-space: pre-wrap; word-break: break-word; }
.m-upload-line.ok { color: #6fd6a8; }
.m-upload-line.err { color: #ff9287; }
.m-upload-empty { color: #657a73; }
</style>
