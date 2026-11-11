<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import Icon from '../components/Icon.vue'
import Modal from '../components/Modal.vue'
import { api, pollReview } from '../api'
import { store } from '../store'
import { toast } from '../ui'

const props = defineProps<{
  open: boolean
  book: string
  chapterNo: number
  text: string
}>()
const emit = defineEmits<{
  (e: 'update:open', v: boolean): void
  (e: 'fix'): void
  /* 定位原文：把引文 / 行号交回正文页，由它选中并滚到对应位置 */
  (e: 'locate', p: { quote?: string; line?: number }): void
}>()

const opts = ref<any>(null)
const running = ref(false)
const jobId = ref('')
const lines = ref<string[]>([])
const result = ref<any>(null)
const error = ref('')
const since = ref(0)
let timer: any = null

const issues = computed<any[]>(() => result.value?.issues || [])
const highCount = computed(() => issues.value.filter((x: any) => x.severity === '高').length)
const stale = computed(() => typeof result.value?.text === 'string'
  && !!result.value.text && result.value.text !== props.text)
const modeText = computed(() => {
  if (running.value) return '审查中'
  if (result.value) return '审查完成'
  if (error.value) return '审查失败'
  return '等待审查'
})
const sevCls = (s: string) => s === '高' ? 'red' : s === '中' ? 'gold' : 'gray'

async function loadOpts() {
  try { opts.value = await api.reviewOptions() } catch { opts.value = null }
}
function reset() {
  if (timer) { clearInterval(timer); timer = null }
  running.value = false
  jobId.value = ''
  lines.value = []
  result.value = null
  error.value = ''
  since.value = 0
  loadOpts()
}
watch(() => props.open, v => { if (v) reset() })

function close() {
  if (running.value && jobId.value) {
    api.stopReview(jobId.value).catch(() => {})
    running.value = false
  }
  if (timer) { clearInterval(timer); timer = null }
  emit('update:open', false)
}

async function start() {
  if (!props.text.trim()) return toast('本章还没有正文，无法审查', 'err')
  if (running.value) return
  const rc = store.callCreds('review')
  if (!rc.api_key) toast('未配置 API Key：只跑程序体检（统计 + 错别字初筛）', 'ok')
  const checks = (opts.value?.checks as string[]) || []
  const body: any = {
    book: props.book,
    chapter_no: props.chapterNo,
    chapter_text: props.text,
    checks,
    top_n: 99,
    advice_scope: 'all',
    api_key: rc.api_key,
  }
  if (rc.model) body.model = rc.model
  if (rc.base_url) body.base_url = rc.base_url
  error.value = ''
  result.value = null
  lines.value = []
  since.value = 0
  try {
    const started = await api.reviewRun(body)
    jobId.value = started.id
    running.value = true
    if (timer) clearInterval(timer)
    timer = setInterval(poll, 900)
    toast('正文审查已启动', 'ok')
  } catch (e: any) {
    error.value = e.message || '启动失败'
  }
}
async function poll() {
  if (!jobId.value) return
  try {
    const j: any = await pollReview(since.value, jobId.value, props.book, props.chapterNo)
    since.value = j.total || since.value
    if (j.lines?.length) {
      lines.value.push(...j.lines)
      if (lines.value.length > 2000) lines.value.splice(0, lines.value.length - 2000)
    }
    if (!j.running) {
      if (timer) { clearInterval(timer); timer = null }
      running.value = false
      if (j.error) { error.value = j.error; toast('审查失败：' + j.error, 'err') }
      else if (j.stopped) toast('审查已停止', 'ok')
      else { result.value = j.result; toast('审查完成', 'ok') }
    }
  } catch { /* 下一轮再试 */ }
}
async function stop() {
  if (!jobId.value) return
  try { await api.stopReview(jobId.value); toast('已请求停止', 'ok') }
  catch (e: any) { toast(e.message, 'err') }
}
function applyFix() {
  emit('fix')
}
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  if (running.value && jobId.value) api.stopReview(jobId.value).catch(() => {})
})
</script>

<template>
  <Modal :open="open" title="正文审查" @update:open="v => { if (!v) close() }">
    <div class="m-rv-form">
      <div class="m-rv-head">
        <span class="m-rv-ico"><Icon name="shield" :size="18" /></span>
        <div>
          <b>第 {{ chapterNo }} 章</b>
          <p>只诊断不改写，问题按严重程度列出。</p>
        </div>
        <span class="m-tag" :class="running ? 'blue' : result ? 'green' : error ? 'red' : 'gray'">{{ modeText }}</span>
      </div>

      <div v-if="running" class="m-rv-progress">
        <div class="m-rv-status"><span class="m-rv-pulse"></span>正在审查 {{ lines.length }} 行日志</div>
        <div class="m-rv-log">
          <div v-if="!lines.length" class="m-rv-log-empty">正在准备审查…</div>
          <div v-for="(l, i) in lines.slice(-60)" :key="i">{{ l }}</div>
        </div>
        <button class="m-btn sm danger" style="align-self:flex-start" @click="stop">
          <Icon name="stop" :size="13" /> 停止审查
        </button>
      </div>

      <div v-if="error" class="m-rv-error"><Icon name="shield" :size="14" /> {{ error }}</div>

      <template v-if="result">
        <div class="m-rv-stats">
          <div><b>{{ issues.length }}</b><span>问题总数</span></div>
          <div><b :class="{ bad: highCount }">{{ highCount }}</b><span>高危</span></div>
          <div><b>{{ result.theme?.level || '—' }}</b><span>整体评价</span></div>
        </div>
        <p v-if="result.theme?.summary" class="m-rv-summary">{{ result.theme.summary }}</p>
        <p v-if="stale" class="m-rv-stale">审查后正文有改动，引文位置可能已变化，建议重新审查。</p>

        <div v-if="issues.length" class="m-rv-issues">
          <div v-for="(it, i) in issues" :key="i" class="m-rv-issue">
            <div class="m-rv-issue-head">
              <span class="m-tag" :class="sevCls(it.severity)">{{ it.severity || '低' }}</span>
              <span class="m-tag gray">{{ it.type_label || it.type || it.category || '问题' }}</span>
              <span v-if="it.line" class="m-rv-line">第 {{ it.line }} 行</span>
            </div>
            <blockquote v-if="it.quote" class="m-rv-quote">{{ it.quote }}</blockquote>
            <button class="m-rv-locate" @click="emit('locate', { quote: it.quote, line: it.line })">
              <Icon name="search" :size="12" /> 定位原文
            </button>
            <p v-if="it.reason" class="m-rv-reason">{{ it.reason }}</p>
            <p v-if="it.suggest" class="m-rv-fix"><b>建议</b>{{ it.suggest }}</p>
          </div>
        </div>
        <div v-else class="m-rv-ok"><Icon name="check" :size="16" /> 本章未发现问题</div>
      </template>

      <div v-else-if="!running && !error" class="m-rv-empty">
        <Icon name="shield" :size="38" />
        <b>还没有审查结果</b>
        <p>对当前正文跑一次审查，定位逻辑、文风、错别字等问题。</p>
      </div>
    </div>

    <template #footer>
      <div class="m-modal-foot">
        <button class="m-btn ghost" @click="close">{{ running ? '停止并关闭' : '关闭' }}</button>
        <button v-if="result && !running" class="m-btn ghost" @click="applyFix">
          <Icon name="pen" :size="14" /> 按意见改写
        </button>
        <button v-if="!running" class="m-btn" @click="start">
          <Icon name="play" :size="14" /> {{ result ? '重新审查' : '开始审查' }}
        </button>
      </div>
    </template>
  </Modal>
</template>

<style scoped>
.m-rv-form { display: flex; flex-direction: column; gap: 13px; }
.m-rv-head { display: flex; align-items: center; gap: 10px; }
.m-rv-ico {
  width: 38px; height: 38px; flex: none; border-radius: 12px;
  display: grid; place-items: center;
  background: var(--m-primary-soft); color: var(--m-primary);
}
.m-rv-head > div { flex: 1; min-width: 0; }
.m-rv-head b { font-size: 14px; font-weight: 650; }
.m-rv-head p { margin-top: 2px; font-size: 10.5px; color: var(--m-text3); }
.m-rv-progress { display: flex; flex-direction: column; gap: 9px; }
.m-rv-status { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--m-primary); }
.m-rv-pulse {
  width: 8px; height: 8px; border-radius: 50%; flex: none;
  background: var(--m-primary); box-shadow: 0 0 0 4px var(--m-primary-soft);
  animation: mPulse 1.2s infinite;
}
@keyframes mPulse { 50% { opacity: .4; } }
.m-rv-log {
  max-height: 22dvh; min-height: 150px; overflow: auto; padding: 9px 10px; border-radius: 10px;
  background: #101a17; color: #b9cdc6;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 10px; line-height: 1.6; white-space: pre-wrap;
}
.m-rv-log-empty { color: #6c827b; }
.m-rv-error {
  display: flex; gap: 6px; padding: 10px 12px; border-radius: 12px;
  background: var(--m-red-soft); color: var(--m-red); font-size: 12px; line-height: 1.55;
}
.m-rv-stats {
  display: grid; grid-template-columns: repeat(3, 1fr);
  padding: 12px 4px; border-radius: 15px; background: #f7f9f5;
}
.m-rv-stats div { text-align: center; display: flex; flex-direction: column; gap: 3px; }
.m-rv-stats div + div { border-left: 1px solid var(--m-line); }
.m-rv-stats b { font-size: 20px; font-weight: 750; }
.m-rv-stats b.bad { color: var(--m-red); }
.m-rv-stats span { font-size: 9.5px; color: var(--m-text3); }
.m-rv-summary { font-size: 12px; line-height: 1.7; color: var(--m-text2); }
.m-rv-stale {
  padding: 9px 11px; border-radius: 11px; background: var(--m-gold-soft);
  color: #93682f; font-size: 11.5px; line-height: 1.55;
}
.m-rv-issues { display: flex; flex-direction: column; gap: 9px; }
.m-rv-issue { padding: 11px 12px; border: 1px solid var(--m-line); border-radius: 14px; }
.m-rv-issue-head { display: flex; gap: 6px; flex-wrap: wrap; }
.m-rv-quote {
  margin: 8px 0 0; padding: 7px 10px; border-left: 3px solid var(--m-line-strong);
  background: #fafbf8; border-radius: 0 8px 8px 0;
  font-size: 11.5px; line-height: 1.6; color: var(--m-text2);
}
.m-rv-line { margin-left: auto; font-size: 10px; color: var(--m-text3); }
.m-rv-locate {
  display: inline-flex; align-items: center; gap: 4px;
  margin-top: 8px; padding: 5px 10px; border-radius: 9px;
  border: 1px solid var(--m-line); background: #fff;
  color: var(--m-primary); font-size: 11.5px; font-weight: 600;
}
.m-rv-locate:active { background: var(--m-primary-soft); }
.m-rv-reason { margin-top: 7px; font-size: 11.5px; line-height: 1.65; color: var(--m-text2); }
.m-rv-fix { margin-top: 6px; font-size: 11.5px; line-height: 1.65; color: var(--m-green); }
.m-rv-fix b { margin-right: 5px; font-weight: 600; }
.m-rv-ok {
  display: flex; align-items: center; gap: 7px;
  padding: 12px; border-radius: 12px;
  background: #e7f6ef; color: #13845f; font-size: 12.5px;
}
.m-rv-empty {
  display: flex; flex-direction: column; align-items: center; gap: 6px;
  padding: 26px 16px; text-align: center; color: var(--m-text3);
}
.m-rv-empty b { margin-top: 4px; font-size: 14px; color: var(--m-text); }
.m-rv-empty p { font-size: 11.5px; line-height: 1.6; max-width: 260px; }
</style>
