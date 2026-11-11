<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import Icon from '../components/Icon.vue'
import Modal from '../components/Modal.vue'
import MobilePicker from './MobilePicker.vue'
import { api, pollExpand } from '../api'
import { VOICE_PRESETS } from '../storyPresets'
import { store } from '../store'
import { toast } from '../ui'

const props = defineProps<{
  open: boolean
  book: string
  chapterNo: number
  text: string
  start: number
  end: number
  selected: string
}>()
const emit = defineEmits<{
  (e: 'update:open', v: boolean): void
  /* 采纳后带出改动区间，正文页可以直接定位到写入位置 */
  (e: 'adopt', text: string, start?: number, end?: number): void
  /* 回到正文查看原选区 */
  (e: 'locate'): void
}>()

type SelMode = 'continue' | 'expand' | 'rewrite' | 'polish'
const MODES: { key: SelMode; name: string; hint: string }[] = [
  { key: 'continue', name: '续写', hint: '接在选区之后继续写' },
  { key: 'expand', name: '扩写', hint: '把选区写得更丰满' },
  { key: 'rewrite', name: '改写', hint: '换节奏与文风重写' },
  { key: 'polish', name: '润色', hint: '只打磨文字，不改情节' },
]
const STYLES = ['沿用设定', ...VOICE_PRESETS]
type Version = { text: string; note: string; chars: number }
const mode = ref<SelMode>('expand')
const style = ref('沿用设定')
const running = ref(false)
const status = ref('')
const error = ref('')
const versions = ref<Version[]>([])
const recommended = ref(0)
const jobId = ref('')
let timer: any = null
const modeMeta = computed(() => MODES.find(m => m.key === mode.value) || MODES[0])
const preview = computed(() => props.selected.length > 200 ? props.selected.slice(0, 200) + '…' : props.selected)

function close() {
  if (running.value && jobId.value) {
    api.stopExpand(jobId.value).catch(() => {})
    running.value = false
  }
  if (timer) { clearInterval(timer); timer = null }
  emit('update:open', false)
}
function reset() {
  if (timer) { clearInterval(timer); timer = null }
  running.value = false
  status.value = ''
  error.value = ''
  versions.value = []
  recommended.value = 0
  jobId.value = ''
}
watch(() => props.open, v => { if (v) reset() })

async function start() {
  if (!props.selected.trim()) return toast('请先在正文里选中一段文字', 'err')
  if (props.text.slice(props.start, props.end) !== props.selected) {
    return toast('选区已变化，请重新选择后再生成', 'err')
  }
  const creds = store.callCreds('expand_selection')
  running.value = true
  status.value = '正在生成候选…'
  error.value = ''
  versions.value = []
  try {
    const started = await api.expandChapter({
      book: props.book,
      chapter_no: props.chapterNo,
      api_key: creds.api_key || undefined,
      model: creds.model || undefined,
      base_url: creds.base_url || undefined,
      mode: mode.value,
      text: props.selected,
      scope: 'selection',
      sel_start: props.start,
      sel_end: props.end,
      before: props.text.slice(Math.max(0, props.start - 800), props.start),
      after: props.text.slice(props.end, props.end + 800),
      style: style.value,
      count: 3,
    })
    jobId.value = started.id
    if (timer) clearInterval(timer)
    timer = setInterval(poll, 900)
  } catch (e: any) {
    running.value = false
    status.value = ''
    error.value = e.message || '启动失败'
  }
}
async function poll() {
  if (!jobId.value) return
  try {
    const j = await pollExpand(0, props.book, jobId.value, props.chapterNo)
    if (j.running) { status.value = j.text || '正在生成候选…'; return }
    if (timer) { clearInterval(timer); timer = null }
    running.value = false
    if (j.stopped) { status.value = '已停止'; return }
    if (j.code === 0 && j.versions?.length) {
      versions.value = j.versions
      recommended.value = j.recommended || 0
      status.value = ''
      toast(`已生成 ${j.versions.length} 个候选`, 'ok')
    } else if (j.code === 0) {
      status.value = '生成完成'
    } else {
      error.value = j.error || '生成失败'
      status.value = ''
    }
  } catch { /* 下一轮再试 */ }
}
async function stop() {
  if (!jobId.value) return
  try { await api.stopExpand(jobId.value); toast('已请求停止', 'ok') }
  catch (e: any) { toast(e.message, 'err') }
}
function adopt(i: number) {
  const v = versions.value[i]
  if (!v) return
  if (props.text.slice(props.start, props.end) !== props.selected) {
    return toast('正文已变化，选区失效，请重新选择', 'err')
  }
  let next = ''
  let start = props.start
  if (mode.value === 'continue') {
    const after = props.text.slice(props.end)
    const sep = after.startsWith('\n') ? '' : '\n\n'
    next = props.text.slice(0, props.end) + sep + v.text + after
    start = props.end + sep.length
  } else {
    next = props.text.slice(0, props.start) + v.text + props.text.slice(props.end)
  }
  emit('adopt', next, start, start + v.text.length)
  close()
  toast('已采纳候选，请保存正文', 'ok')
}
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  if (running.value && jobId.value) api.stopExpand(jobId.value).catch(() => {})
})
</script>

<template>
  <Modal :open="open" title="选区候选" @update:open="v => { if (!v) close() }">
    <div class="m-sel-form">
      <div class="m-sel-preview">
        <div class="m-sel-preview-head">
          <span>已选 {{ selected.length }} 字 · 第 {{ chapterNo }} 章</span>
          <button class="m-sel-locate" @click="emit('locate')">
            <Icon name="search" :size="12" /> 定位原文
          </button>
        </div>
        <p>{{ preview }}</p>
      </div>

      <div class="m-field">
        <label>处理方式<em>{{ modeMeta.hint }}</em></label>
        <div class="m-pick">
          <button v-for="m in MODES" :key="m.key" :class="{ on: mode === m.key }"
                  :disabled="running" @click="mode = m.key">{{ m.name }}</button>
        </div>
      </div>
      <div class="m-field">
        <label>文风</label>
        <MobilePicker v-model="style" title="选择文风" :options="STYLES"
                      :allow-empty="false" :disabled="running" />
      </div>

      <div v-if="running" class="m-sel-running">
        <div class="m-sel-status"><span class="m-sel-pulse"></span>{{ status || '正在生成候选…' }}</div>
        <button class="m-btn sm danger" style="align-self:flex-start" @click="stop">
          <Icon name="stop" :size="13" /> 停止生成
        </button>
      </div>
      <div v-if="error" class="m-sel-error"><Icon name="shield" :size="14" /> {{ error }}</div>

      <div v-if="versions.length" class="m-sel-versions">
        <div class="m-sel-vhead">选择一个候选采纳<span>共 {{ versions.length }} 版</span></div>
        <div v-for="(v, i) in versions" :key="i" class="m-sel-version">
          <div class="m-sel-vtitle">
            <b>版本 {{ i + 1 }}</b>
            <span v-if="i === recommended" class="m-tag green">推荐</span>
            <span class="m-hint" style="margin-left:auto">{{ v.chars || v.text.length }} 字</span>
          </div>
          <p v-if="v.note" class="m-hint">{{ v.note }}</p>
          <pre class="m-sel-vtext">{{ v.text.slice(0, 360) }}{{ v.text.length > 360 ? '…' : '' }}</pre>
          <button class="m-btn sm soft" @click="adopt(i)"><Icon name="check" :size="13" /> 采纳这一版</button>
        </div>
      </div>
    </div>

    <template #footer>
      <div class="m-modal-foot">
        <button class="m-btn ghost" @click="close">{{ running ? '停止并关闭' : '关闭' }}</button>
        <button v-if="!running" class="m-btn" @click="start">
          <Icon name="play" :size="14" /> {{ versions.length ? '重新生成' : '生成候选' }}
        </button>
      </div>
    </template>
  </Modal>
</template>

<style scoped>
.m-sel-form { display: flex; flex-direction: column; gap: 14px; }
.m-sel-preview {
  padding: 11px 12px; border-radius: 13px;
  background: #f7f9f5; border: 1px solid var(--m-line);
}
.m-sel-preview-head { display: flex; align-items: center; justify-content: space-between; gap: 8px;
  font-size: 10.5px; color: var(--m-text3); }
.m-sel-locate {
  display: inline-flex; align-items: center; gap: 3px; flex: none;
  padding: 3px 8px; border-radius: 8px; border: 1px solid var(--m-line);
  background: #fff; color: var(--m-primary); font-size: 10.5px; font-weight: 600;
}
.m-sel-locate:active { background: var(--m-primary-soft); }
.m-sel-preview p {
  margin-top: 6px; font-size: 12.5px; line-height: 1.7; color: var(--m-text2);
  display: -webkit-box; -webkit-line-clamp: 5; -webkit-box-orient: vertical; overflow: hidden;
}
.m-sel-running { display: flex; flex-direction: column; gap: 9px; }
.m-sel-status { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--m-text2); }
.m-sel-pulse {
  width: 8px; height: 8px; border-radius: 50%; flex: none;
  background: var(--m-primary); box-shadow: 0 0 0 4px var(--m-primary-soft);
  animation: mPulse 1.2s infinite;
}
@keyframes mPulse { 50% { opacity: .4; } }
.m-sel-error {
  display: flex; gap: 6px; padding: 10px 12px; border-radius: 12px;
  background: var(--m-red-soft); color: var(--m-red); font-size: 12px; line-height: 1.55;
}
.m-sel-versions { display: flex; flex-direction: column; gap: 10px; }
.m-sel-vhead { display: flex; align-items: baseline; gap: 8px; font-size: 13px; font-weight: 650; }
.m-sel-vhead span { font-size: 10.5px; color: var(--m-text3); font-weight: 400; }
.m-sel-version {
  padding: 11px 12px; border: 1px solid var(--m-line); border-radius: 14px;
  display: flex; flex-direction: column; gap: 7px;
}
.m-sel-vtitle { display: flex; align-items: center; gap: 7px; }
.m-sel-vtitle b { font-size: 12.5px; }
.m-sel-vtext {
  max-height: 22dvh; min-height: 120px; overflow: auto; margin: 0; padding: 9px 10px;
  border-radius: 9px; background: #f7f9f5; color: var(--m-text2);
  font-size: 11px; line-height: 1.65; white-space: pre-wrap; word-break: break-word;
}
</style>
