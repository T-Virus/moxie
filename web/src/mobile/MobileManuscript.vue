<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import Icon from '../components/Icon.vue'
import Modal from '../components/Modal.vue'
import ManuscriptSelectionSheet from './ManuscriptSelectionSheet.vue'
import ManuscriptReviewSheet from './ManuscriptReviewSheet.vue'
import ManuscriptHistorySheet from './ManuscriptHistorySheet.vue'
import MobilePicker from './MobilePicker.vue'
import { api, pollExpand } from '../api'
import { VOICE_PRESETS } from '../storyPresets'
import { state, store } from '../store'
import { useBookDoc } from '../composables/useBookDoc'
import { confirmBox, toast } from '../ui'
import { fmtNum } from '../utils'

const route = useRoute()
const router = useRouter()
const { raw, chapters, load } = useBookDoc()

const kw = ref('')
const filter = ref<'all' | 'done' | 'todo'>('all')
const visible = ref(40)
const text = ref('')
const loading = ref(false)
const saving = ref(false)
const dirty = ref(false)
const ta = ref<HTMLTextAreaElement | null>(null)

/* ---------------- AI 写作 ---------------- */
type AiMode = 'outline' | 'continue' | 'expand' | 'rewrite' | 'polish'
const AI_MODES: { key: AiMode; name: string; hint: string }[] = [
  { key: 'outline', name: '按大纲生成', hint: '根据章节任务从零写整章' },
  { key: 'continue', name: '续写', hint: '接着本章末尾继续往下写' },
  { key: 'expand', name: '扩写', hint: '把现有正文写得更丰满' },
  { key: 'rewrite', name: '改写', hint: '换节奏与文风重写，情节不变' },
  { key: 'polish', name: '润色', hint: '文字层面打磨，不改内容' },
]
/* 与桌面「正文」同一套文风预设（来自 storyPresets，和改编设置共用词表） */
const AI_STYLES = ['沿用设定', ...VOICE_PRESETS]
/* 候选版本数：续写 / 扩写 / 改写 / 润色可挑 2 / 3 / 5 版 */
const AI_COUNTS = [
  { label: '2 版', value: '2' },
  { label: '3 版', value: '3' },
  { label: '5 版', value: '5' },
]
type AiVersion = { text: string; note: string; chars: number }
const aiOpen = ref(false)
const aiMode = ref<AiMode>('outline')
const aiStyle = ref('沿用设定')
const aiCount = ref('3')
const aiRunning = ref(false)
const aiStatus = ref('')
const aiText = ref('')
const aiVersions = ref<AiVersion[]>([])
const aiRecommended = ref(0)
const aiErr = ref('')
const aiJobId = ref('')
const aiFix = ref(false)
const selOpen = ref(false)
const selStart = ref(0)
const selEnd = ref(0)
const selSelected = ref('')
const reviewOpen = ref(false)
/* 工具面板：选区 / 审查 / 历史版本 / 复制，收进一个入口，避免底栏挤成一排小按钮 */
const toolsOpen = ref(false)
const histOpen = ref(false)
let aiTimer: any = null
let aiBaseText = ''
const aiModeMeta = computed(() => AI_MODES.find(m => m.key === aiMode.value) || AI_MODES[0])

onMounted(() => { store.loadBooks().catch(() => {}); load() })

const meta = computed(() => state.books.find(b => b.name === store.curBook()) || null)
const book = computed(() => store.curBook())
const msMap = computed<Record<string, any>>(() => meta.value?.ms_by_no || {})
const readerNo = computed(() => Number(route.query.ch) || 0)
const reader = computed(() => readerNo.value > 0)

function noOf(c: any, i = 0): number {
  for (const k of ['no', 'chapter_id', 'id', 'title']) {
    const m = String(c?.[k] ?? '').match(/\d+/)
    if (m) return Number(m[0])
  }
  return i + 1
}
const doneCount = computed(() =>
  chapters.value.filter((c, i) => !!msMap.value[String(noOf(c, i))]).length)
const totalChars = computed(() => Number(meta.value?.manuscript_chars) || 0)

const rows = computed(() => {
  const k = kw.value.trim().toLowerCase()
  return chapters.value.map((c, i) => ({ c, i, no: noOf(c, i) }))
    .filter(r => {
      if (filter.value === 'done' && !msMap.value[String(r.no)]) return false
      if (filter.value === 'todo' && msMap.value[String(r.no)]) return false
      return true
    })
    .filter(r => {
      if (!k) return true
      return String(r.c.title || '').toLowerCase().includes(k) || String(r.no).includes(k)
    })
})
const shown = computed(() => rows.value.slice(0, visible.value))
const hasMore = computed(() => rows.value.length > visible.value)
watch([kw, filter], () => { visible.value = 40 })

const ordered = computed(() =>
  chapters.value.map((c, i) => ({ c, i, no: noOf(c, i) })).sort((a, b) => a.no - b.no))
const curIndex = computed(() => ordered.value.findIndex(x => x.no === readerNo.value))
const prevCh = computed(() => (curIndex.value > 0 ? ordered.value[curIndex.value - 1] : null))
const nextCh = computed(() => (curIndex.value >= 0 && curIndex.value < ordered.value.length - 1
  ? ordered.value[curIndex.value + 1] : null))

const curChapter = computed(() => {
  const no = readerNo.value
  return chapters.value.find((c, i) => noOf(c, i) === no) || null
})
const curTitle = computed(() =>
  String(curChapter.value?.title || msMap.value[String(readerNo.value)]?.title || '未命名章节'))
const curMs = computed(() => msMap.value[String(readerNo.value)] || null)

function msPath(no: number) {
  return `data/${book.value}/manuscript/${String(Number(no) || 0).padStart(3, '0')}.txt`
}
function openChapter(no: number) {
  router.push({ path: '/manuscript', query: { ch: String(no) } })
}
function exitReader() {
  if (window.history.length > 1) router.back()
  else router.push('/manuscript')
}

async function loadText() {
  if (!reader.value || !book.value) { text.value = ''; return }
  loading.value = true
  dirty.value = false
  selSelected.value = ''
  selStart.value = 0
  selEnd.value = 0
  try {
    const r = await api.getOutput(msPath(readerNo.value))
    text.value = r.content || ''
  } catch {
    text.value = ''
  } finally {
    loading.value = false
  }
}
watch(readerNo, () => { if (reader.value) loadText() }, { immediate: true })

async function saveText(silent = false) {
  if (!reader.value || !book.value || saving.value) return false
  saving.value = true
  try {
    await api.saveManuscript(book.value, readerNo.value, text.value)
    dirty.value = false
    if (!silent) toast('正文已保存', 'ok')
    store.loadStats().catch(() => {})
    return true
  } catch (e: any) {
    toast(e.message || '保存失败', 'err')
    return false
  } finally {
    saving.value = false
  }
}
onBeforeRouteLeave(async () => {
  if (reader.value && dirty.value) {
    const ok = await saveText(true)
    if (!ok) return false
  }
  return true
})

/* 编辑区高度固定为剩余视口（textarea 自己滚动）：长章节不再把整页撑成几万像素，
   避免滚动时频繁重排导致触控卡顿。 */
function onInput() {
  dirty.value = true
}
/* 选区：安卓长按选择后通过 select / touchend 事件记录范围 */
function captureSelection() {
  const el = ta.value
  if (!el) return
  const s = el.selectionStart || 0
  const e = el.selectionEnd || 0
  selStart.value = s
  selEnd.value = e
  selSelected.value = e > s ? text.value.slice(s, e) : ''
}
function captureSelectionLater() { setTimeout(captureSelection, 80) }
function openSelection() {
  captureSelection()
  if (!selSelected.value.trim()) return toast('请先在正文里长按选择一段文字', 'err')
  toolsOpen.value = false
  selOpen.value = true
}
/* 历史版本：先把未保存的正文落盘，保证「当前正文」就是屏幕上看到的这一版 */
async function openHistory() {
  if (dirty.value) {
    const ok = await saveText(true)
    if (!ok) return
  }
  toolsOpen.value = false
  histOpen.value = true
}
async function onRestored() {
  await loadText()
  store.loadStats().catch(() => {})
}
function openReview() {
  toolsOpen.value = false
  reviewOpen.value = true
}
/* ---------------- 定位：从审查问题 / 选区候选回到正文对应位置 ----------------
   textarea 不支持局部高亮，用「聚焦 + 选中 + 估算滚动」实现定位；
   选区被选中后键盘可能会弹出，这是移动端能给出最明确的原文位置反馈。 */
function locateRange(start: number, end: number, tip = '已定位到原文') {
  const el = ta.value
  if (!el) return
  nextTick(() => {
    const t = text.value
    const s = Math.max(0, Math.min(t.length, start))
    const e = Math.max(s, Math.min(t.length, end))
    el.focus({ preventScroll: true })
    try { el.setSelectionRange(s, e) } catch { /* 某些内核不支持时只滚动 */ }
    const line = t.slice(0, s).split('\n').length - 1
    el.scrollTop = Math.max(0, line * 33 - el.clientHeight / 3)
    toast(tip, 'ok')
  })
}
/* 审查问题只给引文 / 行号：优先按引文找，找不到再按行号兜底 */
function locateQuote(quote: string, line?: number) {
  const t = text.value
  const q = (quote || '').trim()
  let s = q ? t.indexOf(q) : -1
  if (s < 0 && q) {
    const head = q.slice(0, 20)
    s = head ? t.indexOf(head) : -1
    if (s >= 0) return locateRange(s, s + q.length)
  }
  if (s >= 0) return locateRange(s, s + q.length)
  if (line && line > 0) {
    const lines = t.split('\n')
    const n = Math.max(0, Math.min(line - 1, lines.length - 1))
    const idx = lines.slice(0, n).join('\n').length + (n > 0 ? 1 : 0)
    return locateRange(idx, Math.min(t.length, idx + 1), '找不到原句，已定位到大致行')
  }
  toast('正文里找不到这段文字（可能已被修改）', 'err')
}
function onLocateIssue(p: { quote?: string; line?: number }) {
  reviewOpen.value = false
  nextTick(() => locateQuote(p.quote || '', p.line))
}
function onLocateSelection() {
  selOpen.value = false
  locateRange(selStart.value, selEnd.value, '已定位到原选区')
}
function onAdoptSelection(next: string, start?: number, end?: number) {
  text.value = next
  dirty.value = true
  selSelected.value = ''
  if (typeof start === 'number') locateRange(start, end ?? start, '已写入正文，已定位到改动处')
}
function onFixReview() {
  reviewOpen.value = false
  aiMode.value = 'rewrite'
  openAI(true)
}
async function copyText() {
  if (!text.value.trim()) return toast('本章还没有正文', 'err')
  try {
    await navigator.clipboard.writeText(text.value)
    toast('正文已复制到剪贴板', 'ok')
  } catch { toast('复制失败，请检查浏览器权限', 'err') }
}
async function goChapter(no: number) {
  if (!no || no === readerNo.value) return
  if (dirty.value) {
    const ok = await saveText(true)
    if (!ok) return
  }
  router.replace({ path: '/manuscript', query: { ch: String(no) } })
}

/* ---------------- AI 写作流程 ---------------- */
function openAI(fix = false) {
  aiFix.value = fix
  aiOpen.value = true
  aiErr.value = ''
  aiStatus.value = ''
  aiText.value = ''
  aiVersions.value = []
  aiRecommended.value = 0
  aiBaseText = text.value
  if (!text.value.trim() && aiMode.value !== 'outline') aiMode.value = 'outline'
}

async function startAI() {
  if (!reader.value || aiRunning.value) return
  if (aiMode.value !== 'outline' && !text.value.trim()) {
    toast('本章还没有正文，无法' + aiModeMeta.value.name, 'err')
    return
  }
  if (aiMode.value === 'outline' && text.value.trim()) {
    if (!await confirmBox('按大纲生成会覆盖本章正文（后台直接落盘），继续？', { ok: '覆盖生成' })) return
  }
  const creds = store.callCreds('expand_' + aiMode.value)
  aiBaseText = text.value
  aiErr.value = ''
  aiVersions.value = []
  aiRecommended.value = 0
  aiText.value = ''
  aiStatus.value = '正在准备…'
  try {
    const started = await api.expandChapter({
      book: book.value,
      chapter_no: readerNo.value,
      api_key: creds.api_key || undefined,
      model: creds.model || undefined,
      base_url: creds.base_url || undefined,
      mode: aiMode.value,
      text: aiMode.value === 'outline' ? '' : text.value,
      scope: 'chapter',
      style: aiStyle.value,
      count: Number(aiCount.value) || 3,
      fix_from_review: aiFix.value || undefined,
    })
    aiJobId.value = started.id
    aiRunning.value = true
    if (aiTimer) clearInterval(aiTimer)
    aiTimer = setInterval(pollAI, 900)
  } catch (e: any) {
    aiRunning.value = false
    aiStatus.value = ''
    aiErr.value = e.message || '启动失败'
  }
}

async function pollAI() {
  if (!aiJobId.value || !reader.value) return
  try {
    const j = await pollExpand(0, book.value, aiJobId.value, readerNo.value)
    if (j.running) {
      aiStatus.value = j.text || (j.multi ? '正在生成候选…' : '正在生成正文…')
      if (!j.multi) aiText.value = j.text
      return
    }
    if (aiTimer) { clearInterval(aiTimer); aiTimer = null }
    aiRunning.value = false
    if (j.stopped) {
      aiStatus.value = '已停止生成'
      return
    }
    if (j.code === 0) {
      if (j.versions?.length) {
        aiVersions.value = j.versions
        aiRecommended.value = j.recommended || 0
        aiStatus.value = ''
        toast(`已生成 ${j.versions.length} 个候选`, 'ok')
      } else {
        try {
          const r = await api.getOutput(msPath(readerNo.value))
          text.value = r.content || ''
          dirty.value = false
        } catch { /* 保留流式回显 */ }
        aiStatus.value = '生成完成，正文已写入本章'
        store.loadStats().catch(() => {})
        toast('生成完成', 'ok')
      }
    } else {
      aiErr.value = j.error || '生成失败'
      aiStatus.value = ''
    }
  } catch { /* 下一轮再试 */ }
}

async function stopAI() {
  if (!aiJobId.value) return
  try {
    await api.stopExpand(aiJobId.value)
    toast('已请求停止', 'ok')
  } catch (e: any) { toast(e.message, 'err') }
}
function closeAI() {
  if (aiRunning.value && aiJobId.value) {
    api.stopExpand(aiJobId.value).catch(() => {})
    aiRunning.value = false
  }
  if (aiTimer) { clearInterval(aiTimer); aiTimer = null }
  aiOpen.value = false
  aiStatus.value = ''
  aiFix.value = false
}
function adoptVersion(i: number) {
  const v = aiVersions.value[i]
  if (!v) return
  if (aiMode.value === 'continue') {
    const base = aiBaseText.replace(/\s+$/, '')
    text.value = (base ? base + '\n\n' : '') + v.text
  } else {
    text.value = v.text
  }
  dirty.value = true
  aiOpen.value = false
  aiVersions.value = []
  aiStatus.value = ''
  /* 整章替换后回到正文开头，避免停在旧的滚动位置看不到新内容 */
  nextTick(() => { const el = ta.value; if (el) el.scrollTop = 0 })
  toast('已采纳候选，请保存正文', 'ok')
}
onBeforeUnmount(() => {
  if (aiTimer) clearInterval(aiTimer)
  if (aiRunning.value && aiJobId.value) api.stopExpand(aiJobId.value).catch(() => {})
})
</script>

<template>
  <!-- 沉浸阅读 / 编辑 -->
  <div v-if="reader" class="m-reader">
    <header class="m-reader-head">
      <button class="m-icon-btn" title="返回" @click="exitReader"><Icon name="left" :size="20" /></button>
      <div class="m-reader-title">
        <b>第 {{ readerNo }} 章</b>
        <small>{{ dirty ? '有未保存的修改' : (curMs ? '已保存到本地' : '未成稿') }}</small>
      </div>
      <button class="m-reader-save" :disabled="saving || !dirty" @click="saveText()">
        {{ saving ? '保存中' : '保存' }}
      </button>
    </header>

    <div class="m-reader-body">
      <h1 class="m-reader-h1">{{ curTitle }}</h1>
      <div class="m-reader-meta">
        <span><Icon name="file" :size="11" />{{ text.length }} 字</span>
        <span v-if="curMs"><Icon name="check" :size="11" />{{ curMs.chars }} 字成稿</span>
        <span v-if="curMs"><Icon name="refresh" :size="11" />{{ curMs.mtime }}</span>
        <span v-if="dirty" class="m-tag gold">未保存</span>
      </div>
      <div class="m-reader-divider"></div>

      <div v-if="loading" class="m-reader-empty">正在读取本章正文…</div>
      <template v-else>
        <textarea ref="ta" class="m-reader-text" v-model="text" @input="onInput"
                  @select="captureSelection" @mouseup="captureSelection"
                  @touchend="captureSelectionLater" @keyup="captureSelection"
                  placeholder="本章还没有正文。&#10;&#10;可以在这里直接落笔，也可以点下方「AI 写作」按章节大纲生成。"></textarea>
      </template>
    </div>

    <footer class="m-reader-foot">
      <button class="m-reader-nav" :disabled="!prevCh" title="上一章" @click="prevCh && goChapter(prevCh.no)">
        <Icon name="left" :size="18" />
      </button>
      <span class="m-reader-pos">{{ curIndex >= 0 ? curIndex + 1 : '—' }} / {{ ordered.length }}</span>
      <button class="m-reader-nav" :disabled="!nextCh" title="下一章" @click="nextCh && goChapter(nextCh.no)">
        <Icon name="right" :size="18" />
      </button>
      <button class="m-reader-tool" :class="{ on: !!selSelected }" @click="toolsOpen = true">
        工具<span v-if="selSelected.trim()" class="m-reader-dot"></span>
      </button>
      <span class="m-reader-foot-spacer"></span>
      <button class="m-reader-ai" @click="openAI()"><Icon name="pen" :size="15" /> AI 写作</button>
    </footer>

    <!-- 工具面板：选区改写 / 正文审查 / 历史版本 / 复制本章 -->
    <Modal :open="toolsOpen" title="正文工具" @update:open="v => toolsOpen = v">
      <div class="m-tools">
        <button class="m-tool-row" @click="openSelection">
          <span class="m-tool-ico blue"><Icon name="edit" :size="18" /></span>
          <span class="m-tool-txt">
            <b>选区改写</b>
            <small>{{ selSelected.trim() ? `已选中 ${selSelected.length} 字，可局部重写` : '先在正文里长按选中一段，再点这里' }}</small>
          </span>
          <Icon name="right" :size="14" class="m-row-arrow" />
        </button>
        <button class="m-tool-row" @click="openReview">
          <span class="m-tool-ico green"><Icon name="shield" :size="18" /></span>
          <span class="m-tool-txt"><b>正文审查</b><small>逐项检查逻辑、文风与错别字</small></span>
          <Icon name="right" :size="14" class="m-row-arrow" />
        </button>
        <button class="m-tool-row" @click="openHistory">
          <span class="m-tool-ico gold"><Icon name="refresh" :size="18" /></span>
          <span class="m-tool-txt"><b>历史版本</b><small>预览、对比与回滚旧稿</small></span>
          <Icon name="right" :size="14" class="m-row-arrow" />
        </button>
        <button class="m-tool-row" @click="copyText(); toolsOpen = false">
          <span class="m-tool-ico gray"><Icon name="copy" :size="18" /></span>
          <span class="m-tool-txt"><b>复制本章</b><small>整章正文复制到剪贴板</small></span>
          <Icon name="right" :size="14" class="m-row-arrow" />
        </button>
      </div>
    </Modal>

    <!-- 历史版本 -->
    <ManuscriptHistorySheet
      :open="histOpen" :book="book" :chapter-no="readerNo"
      @update:open="v => histOpen = v" @restored="onRestored" />

    <!-- AI 写作抽屉 -->
    <Modal :open="aiOpen" title="AI 写作" @update:open="v => { if (!v) closeAI() }">
      <div class="m-ai-form">
        <div class="m-field">
          <label>写作方式<em>{{ aiModeMeta.hint }}</em></label>
          <div class="m-pick">
            <button v-for="m in AI_MODES" :key="m.key" :class="{ on: aiMode === m.key }"
                    :disabled="aiRunning || aiFix" @click="aiMode = m.key">{{ m.name }}</button>
          </div>
        </div>
        <div class="m-field">
          <label>文风</label>
          <MobilePicker v-model="aiStyle" title="选择文风" :options="AI_STYLES"
                        :allow-empty="false" :disabled="aiRunning" />
        </div>
        <div v-if="aiMode !== 'outline'" class="m-field">
          <label>候选版本数<em>生成后挑一版采纳</em></label>
          <MobilePicker v-model="aiCount" title="选择候选版本数" :options="AI_COUNTS"
                        :allow-empty="false" :disabled="aiRunning" />
        </div>
        <p v-if="aiFix" class="m-hint" style="color:var(--m-primary)">已带入本章审查意见，将按「必须修复」清单改写。</p>
        <p v-else-if="aiMode !== 'outline'" class="m-hint">将基于当前正文生成候选，采纳后才会替换正文。</p>
        <p v-else class="m-hint">按大纲生成会先覆盖本章正文；生成完成后自动写入。</p>

        <div v-if="aiRunning" class="m-ai-running">
          <div class="m-ai-status"><span class="m-ai-pulse"></span>{{ aiStatus || '正在生成…' }}</div>
          <pre v-if="aiText" class="m-ai-stream">{{ aiText.slice(-1200) }}</pre>
          <button class="m-btn sm danger" style="align-self:flex-start" @click="stopAI">
            <Icon name="stop" :size="13" /> 停止生成
          </button>
        </div>

        <div v-if="aiErr" class="m-ai-error"><Icon name="shield" :size="14" /> {{ aiErr }}</div>

        <div v-if="aiVersions.length" class="m-ai-versions">
          <div class="m-ai-versions-head">选择一个版本采纳<span>共 {{ aiVersions.length }} 版</span></div>
          <div v-for="(v, i) in aiVersions" :key="i" class="m-ai-version">
            <div class="m-ai-version-head">
              <b>版本 {{ i + 1 }}</b>
              <span v-if="i === aiRecommended" class="m-tag green">推荐</span>
              <span class="m-hint" style="margin-left:auto">{{ v.chars || v.text.length }} 字</span>
            </div>
            <p class="m-ai-version-note" v-if="v.note">{{ v.note }}</p>
            <pre class="m-ai-version-text">{{ v.text.slice(0, 420) }}{{ v.text.length > 420 ? '…' : '' }}</pre>
            <button class="m-btn sm soft" @click="adoptVersion(i)"><Icon name="check" :size="13" /> 采纳这一版</button>
          </div>
        </div>
      </div>

      <template #footer>
        <div class="m-modal-foot">
          <button class="m-btn ghost" @click="closeAI">{{ aiRunning ? '后台停止并关闭' : '关闭' }}</button>
          <button v-if="!aiRunning" class="m-btn" @click="startAI">
            <Icon name="play" :size="14" /> {{ aiVersions.length ? '重新生成' : '开始生成' }}
          </button>
        </div>
      </template>
    </Modal>

    <!-- 选区候选 -->
    <ManuscriptSelectionSheet
      :open="selOpen" :book="book" :chapter-no="readerNo" :text="text"
      :start="selStart" :end="selEnd" :selected="selSelected"
      @update:open="v => selOpen = v" @adopt="onAdoptSelection"
      @locate="onLocateSelection" />

    <!-- 正文审查 -->
    <ManuscriptReviewSheet
      :open="reviewOpen" :book="book" :chapter-no="readerNo" :text="text"
      @update:open="v => reviewOpen = v" @fix="onFixReview"
      @locate="onLocateIssue" />
  </div>

  <!-- 正文目录 -->
  <div v-else class="m-page">
    <div class="m-head">
      <div>
        <h1>正文</h1>
        <p>{{ doneCount }} 章成稿 · {{ fmtNum(totalChars) }} 字 · 点开章节即可阅读与书写</p>
      </div>
    </div>

    <div v-if="!state.books.length" class="m-empty" style="padding-top:70px">
      <span class="m-empty-ico"><Icon name="book" :size="28" /></span>
      <b>还没有作品</b>
      <p>先新建作品并完成拆解，成稿会出现在这里。</p>
    </div>

    <div v-else-if="!raw" class="m-empty" style="padding-top:70px">
      <span class="m-empty-ico"><Icon name="refresh" :size="28" /></span>
      <b>正在载入正文</b>
      <p>从本地作品数据里读取章节…</p>
    </div>

    <template v-else>
      <div class="m-searchbar">
        <Icon name="search" :size="16" />
        <input v-model="kw" placeholder="搜索章号或标题" />
        <button v-if="kw" class="m-clear" @click="kw = ''"><Icon name="close" :size="13" /></button>
      </div>

      <div class="m-seg" style="margin-bottom:11px">
        <button :class="{ on: filter === 'all' }" @click="filter = 'all'">全部 {{ chapters.length }}</button>
        <button :class="{ on: filter === 'done' }" @click="filter = 'done'">已成稿 {{ doneCount }}</button>
        <button :class="{ on: filter === 'todo' }" @click="filter = 'todo'">未成稿 {{ chapters.length - doneCount }}</button>
      </div>

      <div v-if="chapters.length" class="m-ms-list">
        <button v-for="r in shown" :key="r.i" class="m-ms-card" @click="openChapter(r.no)">
          <span class="m-ch-no" :class="{ has: !!msMap[String(r.no)] }">
            <template v-if="msMap[String(r.no)]">第<b>{{ r.no }}</b>章</template>
            <template v-else><b>{{ r.no }}</b>章</template>
          </span>
          <span class="m-ms-card-main">
            <b>{{ r.c.title || '未命名章节' }}</b>
            <small>
              <template v-if="msMap[String(r.no)]">
                <span style="color:var(--m-green)">已成稿</span>
                <span>· {{ fmtNum(msMap[String(r.no)]?.chars || 0) }} 字</span>
                <span>· {{ msMap[String(r.no)]?.mtime }}</span>
              </template>
              <template v-else>
                <span>未成稿</span>
                <span v-if="r.c.summary">· {{ r.c.summary.slice(0, 26) }}{{ r.c.summary.length > 26 ? '…' : '' }}</span>
              </template>
            </small>
          </span>
          <span v-if="msMap[String(r.no)]" class="m-tag green m-ms-state">阅读</span>
          <span v-else class="m-tag gray m-ms-state">去写</span>
        </button>

        <button v-if="hasMore" class="m-load-more" @click="visible += 50">
          还有 {{ rows.length - visible }} 章，加载更多
        </button>
      </div>

      <div v-else class="m-empty">
        <span class="m-empty-ico"><Icon name="book" :size="28" /></span>
        <b>{{ chapters.length ? '没有匹配的章节' : '还没有章节' }}</b>
        <p>{{ chapters.length ? '换个章号、标题或筛选条件试试。' : '先到「章节概括」创建章节，再回来写正文。' }}</p>
        <button v-if="!chapters.length" class="m-btn" @click="router.push('/chapters')">
          <Icon name="file" :size="15" /> 去章节概括
        </button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.m-reader-nav {
  width: 36px; height: 36px; flex: none; border: 0; border-radius: 11px;
  background: #f0ede4; color: #5d6258;
  display: grid; place-items: center;
}
.m-reader-nav:disabled { opacity: .35; }
.m-reader-pos { font-size: 11px; color: #8f8b7f; min-width: 38px; text-align: center; flex: none; }
.m-reader-tool {
  height: 34px; padding: 0 9px; flex: none;
  border: 0; border-radius: 10px; background: #f0ede4;
  color: #5d6258; font-size: 12px;
}
.m-reader-tool.on { background: var(--m-primary-soft); color: var(--m-primary); font-weight: 650; }
.m-reader-dot {
  display: inline-block; width: 5px; height: 5px; margin-left: 4px;
  border-radius: 50%; background: var(--m-primary); vertical-align: middle;
}
.m-tools { display: flex; flex-direction: column; gap: 4px; }
.m-tool-row {
  display: flex; align-items: center; gap: 11px; width: 100%;
  padding: 11px 4px; border: 0; border-radius: 13px; background: none;
  color: var(--m-text); text-align: left;
}
.m-tool-row:active { background: #f6f8f4; }
.m-tool-row + .m-tool-row { border-top: 1px solid #f2f4f0; }
.m-tool-ico {
  width: 38px; height: 38px; flex: none; border-radius: 12px;
  display: grid; place-items: center;
}
.m-tool-ico.blue { background: #eaf1ff; color: #3a6fd8; }
.m-tool-ico.green { background: var(--m-primary-soft); color: var(--m-primary); }
.m-tool-ico.gold { background: var(--m-gold-soft, #fdf5e6); color: #a36a1c; }
.m-tool-ico.gray { background: #f2f4f0; color: #6b7168; }
.m-tool-txt { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.m-tool-txt b { font-size: 14px; font-weight: 650; }
.m-tool-txt small { font-size: 11px; color: var(--m-text3); line-height: 1.5; }
.m-reader-foot-spacer { flex: 1; min-width: 2px; }
.m-reader-ai {
  height: 40px; padding: 0 15px; border: 0; border-radius: 12px;
  background: var(--m-primary); color: #fff;
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 13px; font-weight: 600; flex: none;
}
.m-reader-ai:active { background: var(--m-primary-dark); }
.m-ai-form { display: flex; flex-direction: column; gap: 14px; }
.m-ai-running { display: flex; flex-direction: column; gap: 9px; }
.m-ai-status {
  display: flex; align-items: center; gap: 8px;
  font-size: 12px; color: var(--m-text2); line-height: 1.5;
}
.m-ai-pulse {
  width: 8px; height: 8px; border-radius: 50%; flex: none;
  background: var(--m-primary); box-shadow: 0 0 0 4px var(--m-primary-soft);
  animation: mPulse 1.2s infinite;
}
@keyframes mPulse { 50% { opacity: .4; } }
.m-ai-stream {
  max-height: 28dvh; min-height: 120px; overflow: auto; margin: 0; padding: 11px 12px;
  border-radius: 12px; background: #f7f9f5; color: var(--m-text2);
  font-size: 11.5px; line-height: 1.7; white-space: pre-wrap; word-break: break-word;
}
.m-ai-error {
  display: flex; gap: 6px; align-items: flex-start; padding: 10px 12px;
  border-radius: 12px; background: var(--m-red-soft); color: var(--m-red);
  font-size: 12px; line-height: 1.55;
}
.m-ai-versions { display: flex; flex-direction: column; gap: 10px; }
.m-ai-versions-head { display: flex; align-items: baseline; gap: 8px; font-size: 13px; font-weight: 650; }
.m-ai-versions-head span { font-size: 10.5px; font-weight: 400; color: var(--m-text3); }
.m-ai-version {
  padding: 11px 12px; border: 1px solid var(--m-line); border-radius: 14px;
  display: flex; flex-direction: column; gap: 7px;
}
.m-ai-version-head { display: flex; align-items: center; gap: 7px; }
.m-ai-version-head b { font-size: 12.5px; }
.m-ai-version-note { font-size: 11px; color: var(--m-text3); }
.m-ai-version-text {
  max-height: 22dvh; overflow: auto; margin: 0; padding: 9px 10px;
  background: #f7f9f5; border-radius: 9px; color: var(--m-text2);
  font-size: 11px; line-height: 1.65; white-space: pre-wrap; word-break: break-word;
}
</style>
