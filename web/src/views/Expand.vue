<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import Icon from '../components/Icon.vue'
import BackLink from '../components/BackLink.vue'
import JobBar from '../components/JobBar.vue'
import LogBox from '../components/LogBox.vue'
import EmptyBox from '../components/EmptyBox.vue'
import SelectBox from '../components/SelectBox.vue'
import { api, pollJobById } from '../api'
import { adoptJob, stageName } from '../jobs'
import { state, store } from '../store'
import { toast, openFilePreview } from '../ui'
import { fmtSize } from '../utils'
import { modelChoices } from '../modelChoices'
import { VOICE_PRESETS } from '../storyPresets'
import { usePersistedRef } from '../composables/usePersistedRef'

/* 本页自己的任务 id：多任务并发时只回显这一个任务的日志 */
const jid = usePersistedRef('expand.jobId', '')
/* 已完成收尾的任务 id：刷新后会丢内存状态，用 id 记账保证成稿列表 / 提示不丢也不重 */
const handledJid = usePersistedRef('expand.handledJid', '')
const lines = ref<string[]>([])
const job = ref({ running: false, code: null as number | null, stage: '' })
const started = ref(false)
const keyHint = ref(false)

const chRange = usePersistedRef('expand.chRange', '')
const eModel = usePersistedRef('expand.eModel', state.model)
const eTemp = usePersistedRef('expand.eTemp', '')
const eStyle = usePersistedRef('expand.eStyle', '沿用设定')
/* 断点续跑友好：勾选后已有成稿的章节直接跳过（中断恢复 / 分批写长书时省钱省时间） */
const skipExisting = usePersistedRef('expand.skipExisting', false)
const eHint = ref('')
const outputs = ref<any[]>([])
/* 「正文初稿」工序绑定的档案（多模型）：绑了就用它的 Key / 模型 / 端点 */
const bound = computed(() => store.profileFor('expand_outline'))
/* 模型候选：与设置页档案同一套，选中即覆盖绑定，留空则跟随绑定 */
const modelOptions = computed(() => modelChoices('expand_outline'))
/* 温度档位：常用值直接点，特殊值在面板里输入 */
const TEMP_OPTIONS = [
  { label: '0.5 · 收敛', value: '0.5' },
  { label: '0.7 · 稳重', value: '0.7' },
  { label: '0.9 · 标准', value: '0.9' },
  { label: '1.1 · 放开', value: '1.1' },
  { label: '1.3 · 发散', value: '1.3' },
]

async function refreshOutputs() {
  try {
    // 只取本书正文：产出目录可能有几万个文件，不让前端为了筛几行去拉全量清单
    const book = store.curBook()
    outputs.value = book ? (await api.getOutputs({ book, kind: 'manuscript' })).files || [] : []
  } catch { outputs.value = [] }
}
async function loadHint() {
  try {
    const ch = await api.getChapters(store.curBook())
    eHint.value = `本书共 ${(ch.chapters || []).length} 章 · 人物卡 ${(ch.story_bible_cards || []).length} 张 · 势力卡 ${(ch.story_bible_factions || []).length} 张`
  } catch { eHint.value = '本书暂无章节数据，请先拆解。' }
}

function run() {
  const creds = store.callCreds('expand_outline')
  if (!creds.api_key) {
    // 没有 Key 也放行：后端输出的是可编辑的章节骨架（写作清单），不是正文
    keyHint.value = true
    toast('未配置 API Key：将生成章节骨架（写作清单），配好 Key 后可重跑补成正文', '')
  }
  const args: any = { book: store.curBook() }
  if (chRange.value.trim()) args.chapters = chRange.value.trim()
  if (eModel.value.trim()) args.model = eModel.value.trim()
  if (eStyle.value && eStyle.value !== '沿用设定') args.style = eStyle.value
  if (skipExisting.value) args.skip_existing = true
  const t = parseFloat(eTemp.value)
  if (!Number.isNaN(t)) args.temperature = t
  api.run(creds.api_key, 'expand', args)
    .then((r) => {
      /* 后端受理后才重置面板：被拒（同书同阶段 409 / 并发超限 429）时保留原日志 */
      lines.value = []
      lastTotal = 0
      jid.value = r.id
      toast('扩写任务已启动', 'ok')
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
    /* 刷新 / 换页回来时 started 会丢，用任务 id 记账：完成的收尾照做一次，已做过的不重复；
       从任务中心看历史任务（jid 仍是 URL 里那个）时不做收尾 */
    const qj = String(route.query.job || '').trim()
    const viewOnly = !!qj && qj === jid.value
    if (!j.running && !viewOnly && j.id && j.id !== handledJid.value) {
      handledJid.value = j.id
      started.value = false
      if (j.code === 0) { store.loadStats(); refreshOutputs(); toast('扩写完成，成稿已更新', 'ok') }
    }
  } catch { /* */ }
}

/* 回到本页时接管仍在后台跑的扩写任务（按任务 id 认领，不会串到别的任务上） */
async function syncTask() {
  const a = await adoptJob(['expand'], store.curBook())
  if (!a || !a.running) return
  jid.value = a.id
  lastTotal = 0
  started.value = true
  toast('已接管进行中的扩写任务', 'ok')
}

const route = useRoute()
watch(() => store.curBook(), () => { loadHint(); refreshOutputs() })
onMounted(async () => {
  await store.loadBooks().catch(() => {})
  const qch = String((route.query.ch as string) || '').trim()
  if (qch) chRange.value = qch
  loadHint(); refreshOutputs()
  /* 任务中心带 ?job= 点进来：直接回显那个任务的日志 */
  const qj = String((route.query.job as string) || '').trim()
  if (qj) {
    jid.value = qj
    lines.value = []
    lastTotal = 0
    started.value = false     // 只是回看日志，别把「已完成」当成刚跑完再弹一次提示
  } else {
    await syncTask()
  }
  poll(); timer = setInterval(poll, 900)
})
onUnmounted(() => clearInterval(timer))

/* 已在本页时从任务中心切任务：换日志面板 */
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
  <div class="page-head"><div><h1>正文生成</h1>
    <p>基于逐章任务与故事设定扩写成稿，产出存入 data/书名/manuscript/。</p></div>
  </div>
  <div class="toolbar"><BackLink /><span class="spacer"></span></div>

  <div class="grid cols-2" style="align-items:start">
    <div class="card">
      <div class="card-head"><div class="card-title">扩写设置</div></div>
      <div class="field">
        <label>章节范围<span class="req">*</span></label>
        <input class="input" v-model="chRange" placeholder="如 1-5，或单章 7；留空 = 全部章节" />
        <div class="hint">章号以「章节概括」页的章节列表为准；已存在成稿的章节会被重新生成覆盖。</div>
      </div>
      <label class="check" style="margin-bottom:10px">
        <input type="checkbox" v-model="skipExisting" /> 跳过已有成稿的章节（断点续跑 / 只补没写的章）
      </label>
      <div class="field" v-if="bound">
        <div class="hint" style="margin-top:0">
          「正文初稿」已绑定档案：<b>{{ bound.profile.name }}</b>（{{ bound.profile.model }}）
          <template v-if="!bound.api_key"> · <span style="color:var(--orange)">该档案还没在设置里填 Key</span></template>
        </div>
      </div>
      <div class="hint" v-else style="margin-top:0">未绑定档案，使用默认 deepseek-v4-flash</div>
      <div class="hint" v-if="eModel.trim()">本次使用：<b>{{ eModel.trim() }}</b>（页面临时指定，优先于工序绑定）</div>
      <div class="form-row">
        <div class="field"><label>模型</label>
          <SelectBox :model-value="eModel" :options="modelOptions" allow-empty allow-custom
                     empty-label="默认（跟随工序绑定）" placeholder="选择或输入模型名"
                     @update:model-value="v => eModel = v" />
        </div>
        <div class="field"><label>创作温度 0.0 ~ 1.5</label>
          <SelectBox :model-value="eTemp" :options="TEMP_OPTIONS" :search-from="99"
                     allow-empty allow-custom empty-label="默认（跟随档案）"
                     placeholder="默认" @update:model-value="v => eTemp = v" />
        </div>
      </div>
      <div class="field">
        <label>文风（默认沿用设定）</label>
        <SelectBox :model-value="eStyle" :search-from="99"
                   :options="['沿用设定', ...VOICE_PRESETS]"
                   @update:model-value="v => eStyle = v" />
        <div class="hint">只影响写作笔触；人物、设定、专有名词仍以设定库为准。</div>
      </div>
      <div class="hint">{{ eHint }}</div>
      <div v-if="keyHint" class="hint">未配置 API Key：将生成可编辑的章节骨架（写作清单，不是正文），配好 Key 后重跑可补成正文。</div>
      <button class="btn lg" style="width:100%;margin-top:10px" @click="run"><Icon name="play" :size="14" /> 开始扩写</button>
    </div>

    <div class="card">
      <div class="card-head"><div class="card-title">本书成稿</div><span class="sub">{{ outputs.length }} 章</span></div>
      <table v-if="outputs.length" class="table">
        <thead><tr><th>文件</th><th>大小</th><th style="text-align:right">操作</th></tr></thead>
        <tbody>
          <tr v-for="f in outputs" :key="f.path">
            <td>{{ f.name.split('/').pop() }}</td>
            <td>{{ fmtSize(f.size) }}</td>
            <td><div class="ops"><button class="link-btn" @click="openFilePreview(f.path, f.name)">预览</button></div></td>
          </tr>
        </tbody>
      </table>
      <EmptyBox v-else title="还没有成稿" desc="运行扩写后，章节正文会出现在这里" />
    </div>
  </div>

  <div class="card" style="margin-top:16px">
    <div class="card-head"><div class="card-title">任务日志</div></div>
    <JobBar :running="job.running" :code="job.code" :label="stageName(job.stage)"
            @stop="() => api.stopJob(jid).then(() => toast('已请求停止')).catch((e:any)=>toast(e.message,'err'))" />
    <LogBox :lines="lines" />
  </div>
</template>
