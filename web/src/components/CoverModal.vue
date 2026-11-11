<script setup lang="ts">
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import Modal from './Modal.vue'
import SelectBox from './SelectBox.vue'
import { api } from '../api'
import { state, store } from '../store'
import { toast } from '../ui'
import type { CoverPresets } from '../types'

const props = defineProps<{ open: boolean; book: string; title: string; author?: string }>()
const emit = defineEmits<{ (e: 'update:open', v: boolean): void; (e: 'done'): void }>()

const presets = ref<CoverPresets | null>(null)
const presetsError = ref('')
const busy = ref(false)
const elapsed = ref(0)
const coverTick = ref(Date.now())
const en = ref('')
const theme = ref('')
let timer: ReturnType<typeof setInterval> | null = null

/* localStorage 在隐私模式 / 配额满时会抛错：记住作者名只是便利功能，丢了不阻塞流程 */
function safeGetAuthor(): string {
  try { return localStorage.getItem('wf-cover-author') || '' } catch { return '' }
}
function safeSetAuthor(v: string) {
  try { localStorage.setItem('wf-cover-author', v) } catch { /* ignore */ }
}

onUnmounted(() => { if (timer) { clearInterval(timer); timer = null } })

const form = reactive({
  platform: 'fanqie', width: 1400, height: 2100, fmt: 'jpg',
  title: '', author: '', prompt: '', model: 'flux', style: 'gold', layout: 'top',
  seed: '', reuse_base: false,
  /* 出图用的模型档案 id：空 = 走默认出图（Pollinations / 本地绘制） */
  pid: '',
})

/* 出图模型：设置页里的模型档案。选中后优先用该模型走 images/generations，
   模型不支持出图时后端自动回退，前端照常拿到封面。 */
const coverProfiles = computed(() => Object.entries(state.studio?.profiles || {}).map(([pid, p]) => ({
  pid,
  label: `${p.name || p.model || '未命名档案'} · ${p.model || '未设模型'}`,
})).filter(p => !!p.label))
const aiOptions = computed(() => [
  { label: '默认出图（不占用模型额度）', value: '' },
  ...coverProfiles.value.map(p => ({ label: p.label, value: p.pid })),
])
function setAiProfile(v: string) { form.pid = v }
const coverCreds = computed(() => {
  const pid = form.pid
  if (!pid) return null
  const profile = state.studio?.profiles?.[pid]
  if (!profile) return null
  return { api_key: store.profileKey(pid), base_url: profile.base_url, ai_model: profile.model }
})

/* 中文题材模板：点一下填进提示词，生成时后端自动转英文 */
const THEMES = [
  { t: '玄幻仙侠', p: '云雾缭绕的仙山，古风楼阁，御剑飞行的背影，金色晨光，电影感构图' },
  { t: '都市异能', p: '夜晚的城市，霓虹灯，雨后的街道，一个背影，蓝紫色光影，电影感' },
  { t: '悬疑推理', p: '雨夜的小巷，孤零零的路灯，浓雾，神秘的剪影，冷色调' },
  { t: '古言宫斗', p: '古代宫廷庭院，汉服女子侧脸，红灯笼，落花，柔和的光' },
  { t: '青春言情', p: '盛夏黄昏，樱花，远处的两人剪影，温暖的逆光，梦幻色调' },
  { t: '科幻末世', p: '未来废墟城市，天空中的巨大星球，孤独的幸存者剪影，青橙色调' },
  { t: '惊悚怪谈', p: '废弃的走廊，闪烁的灯，阴森的雾气，深重的阴影' },
  { t: '历史战争', p: '古代战场，铁骑剪影，残破的旗帜，烽火与尘烟，史诗般的逆光' },
]

const cur = computed(() => presets.value?.platforms.find(p => p.key === form.platform))
const isCustom = computed(() => form.platform === 'custom')

/* 选择器：显示名 ↔ 内部 key 两张表，统一走 SelectBox（与其它表单同一套下拉） */
const platLabel = (p: { name: string; width: number; height: number }) => `${p.name} · ${p.width}×${p.height}`
const platformText = computed(() => cur.value ? platLabel(cur.value) : '自定义尺寸')
const platformOptions = computed(() => [
  ...(presets.value?.platforms || []).map(platLabel),
  '自定义尺寸',
])
function setPlatform(label: string) {
  const hit = presets.value?.platforms.find(p => platLabel(p) === label)
  applyPlatform(hit ? hit.key : 'custom')
}
const FMT_OPTIONS = ['JPG（推荐，体积小）', 'PNG（超 5MB 自动转 JPG）']
const fmtText = computed(() => form.fmt === 'png' ? FMT_OPTIONS[1] : FMT_OPTIONS[0])
function setFmt(v: string) { form.fmt = v === FMT_OPTIONS[1] ? 'png' : 'jpg' }
const optLabel = (o: { name: string; note?: string }) => o.note ? `${o.name} — ${o.note}` : o.name
const modelOptions = computed(() => (presets.value?.models || []).map(optLabel))
const modelText = computed(() => {
  const m = presets.value?.models.find(x => x.key === form.model)
  return m ? optLabel(m) : ''
})
function setModel(label: string) {
  const hit = presets.value?.models.find(m => optLabel(m) === label)
  if (hit) form.model = hit.key
}
const styleOptions = computed(() => (presets.value?.styles || []).map(optLabel))
const styleText = computed(() => {
  const s = presets.value?.styles.find(x => x.key === form.style)
  return s ? optLabel(s) : ''
})
function setStyle(label: string) {
  const hit = presets.value?.styles.find(s => optLabel(s) === label)
  if (hit) form.style = hit.key
}
const layoutOptions = computed(() => (presets.value?.layouts || []).map(optLabel))
const layoutText = computed(() => {
  const l = presets.value?.layouts.find(x => x.key === form.layout)
  return l ? optLabel(l) : ''
})
function setLayout(label: string) {
  const hit = presets.value?.layouts.find(l => optLabel(l) === label)
  if (hit) form.layout = hit.key
}

function applyPlatform(key: string) {
  form.platform = key
  const p = presets.value?.platforms.find(x => x.key === key)
  if (p) {
    form.width = p.width
    form.height = p.height
    form.fmt = p.fmt
  }
}

async function translate() {
  const text = form.prompt.trim()
  if (!text) { en.value = ''; theme.value = ''; return }
  try {
    const r = await api.coverTranslate(text)
    en.value = r.prompt_en
    theme.value = r.theme
  } catch (e: any) { toast(e.message, 'err') }
}

function useTheme(p: string) {
  form.prompt = p
  translate()
}

async function loadPresets(force = false) {
  if (presets.value && !force) return
  presetsError.value = ''
  try {
    presets.value = await api.coverPresets()
    if (!presets.value?.platforms?.length) throw new Error('接口返回的平台列表为空')
    applyPlatform(form.platform)
  } catch (e: any) {
    presets.value = null
    presetsError.value = e?.message || '封面选项加载失败，请完全退出应用后重新启动'
    toast('封面选项加载失败', 'err')
  }
}

async function initForm() {
  coverTick.value = Date.now()
  form.title = props.title || props.book || ''
  form.author = props.author || safeGetAuthor()
  en.value = ''
  theme.value = ''
  /* 默认跟随「设置 → 工序绑定 → AI 封面底图」，也可以在弹窗里临时换一个档案 */
  form.pid = store.profileFor('cover')?.pid || ''
  await loadPresets()
}

watch(() => props.open, v => { if (v) initForm() })

async function run() {
  if (busy.value) return
  if (!form.title.trim()) return toast('请填写书名', 'err')
  if (!form.author.trim()) return toast('请填写作者名：封面必须显示「书名 + 作者 + 著」', 'err')
  if (!form.prompt.trim() && !form.reuse_base) return toast('请填写底图提示词（可写中文），或勾选复用上次底图', 'err')
  if (form.width < 64 || form.height < 64) return toast('尺寸不能小于 64 像素', 'err')
  const w = Math.min(form.width, presets.value?.max_side || 4096)
  const h = Math.min(form.height, presets.value?.max_side || 4096)
  safeSetAuthor(form.author.trim())
  busy.value = true
  elapsed.value = 0
  timer = setInterval(() => { elapsed.value += 1 }, 1000)
  try {
    const ai = coverCreds.value
    const r = await api.coverGenerate({
      book: props.book, title: form.title.trim(), author: form.author.trim(),
      prompt: form.prompt.trim(), width: w, height: h, fmt: form.fmt,
      model: form.model, style: form.style, layout: form.layout,
      seed: form.seed.trim(), reuse_base: form.reuse_base,
      api_key: ai?.api_key || '', base_url: ai?.base_url || '', ai_model: ai?.ai_model || '',
    })
    en.value = r.prompt_en
    theme.value = r.theme
    const kb = r.bytes > 1024 * 1024
      ? (r.bytes / 1024 / 1024).toFixed(1) + ' MB'
      : Math.round(r.bytes / 1024) + ' KB'
    const sizeTxt = `${r.width}×${r.height} ${r.fmt.toUpperCase()} · ${kb}`
    if (r.fallback) {
      toast(`出图接口不可用，已用本地代码绘制底图 · 封面已生成：${sizeTxt}`, 'ok')
    } else if (r.source === 'ai') {
      toast(`封面已生成：${sizeTxt} · 底图由 ${r.ai_model || 'AI 模型'} 绘制`, 'ok')
    } else {
      toast(`封面已生成：${sizeTxt}` +
            (r.ai_note ? ' · AI 模型不支持出图，已回退默认出图' : '') +
            (r.translated ? ' · 提示词已自动转英文' : ''), 'ok')
    }
    emit('done')
    emit('update:open', false)
  } catch (e: any) {
    toast(e.message, 'err')
  } finally {
    busy.value = false
    if (timer) clearInterval(timer)
    timer = null
  }
}
</script>

<template>
  <Modal :open="open" title="AI 生成封面" wide @update:open="emit('update:open', $event)">
    <div class="cover-gen">
      <div class="cg-left">
        <div class="cg-preview">
          <img v-if="book" :src="api.coverUrl(book, coverTick)" alt="当前封面" />
          <span v-else class="cg-empty">还没有封面</span>
        </div>
        <div class="hint">
          生成后直接替换当前封面，可反复重生成；也可点封面手动上传。
        </div>
        <div class="hint" v-if="presets?.font">字体：{{ presets.font }}（免费商用）</div>
      </div>

      <div class="cg-form">
        <div v-if="presetsError" class="cg-err">
          <span>{{ presetsError }}</span>
          <button class="btn sm ghost" @click="loadPresets(true)">重试</button>
        </div>
        <div class="form-grid">
          <div class="field full">
            <label>发布平台</label>
            <SelectBox :model-value="platformText" :options="platformOptions"
                       @update:model-value="setPlatform" />
            <div class="hint" v-if="cur?.note">{{ cur.note }}</div>
          </div>

          <div class="field">
            <label>输出尺寸</label>
            <div v-if="isCustom" class="form-row">
              <input v-model.number="form.width" class="input" type="number" min="64" :max="presets?.max_side || 4096" />
              <input v-model.number="form.height" class="input" type="number" min="64" :max="presets?.max_side || 4096" />
            </div>
            <div v-else class="cg-size">{{ form.width }} × {{ form.height }} 像素</div>
            <div class="hint">标题/作者离边 7% 以上，避免平台裁剪；体积自动压到 5MB 内</div>
          </div>

          <div class="field">
            <label>图片格式</label>
            <SelectBox :model-value="fmtText" :options="FMT_OPTIONS" @update:model-value="setFmt" />
          </div>

          <div class="field">
            <label>书名 <span class="req">*</span></label>
            <input v-model="form.title" class="input" maxlength="60" placeholder="显示在封面上的书名" />
          </div>

          <div class="field">
            <label>作者名 <span class="req">*</span></label>
            <input v-model="form.author" class="input" maxlength="40" placeholder="封面自动补「著」" />
          </div>

          <div class="field full">
            <label>底图提示词（中文会自动转英文）</label>
            <div class="chip-row">
              <button v-for="t in THEMES" :key="t.t" class="btn sm ghost" @click="useTheme(t.p)">
                {{ t.t }}
              </button>
            </div>
            <textarea v-model="form.prompt" class="textarea" rows="3"
                      placeholder="例如：云雾缭绕的仙山，御剑飞行的背影，金色晨光，电影感"
                      @blur="translate" />
            <div class="cg-en-row">
              <button class="btn sm ghost" :disabled="!form.prompt.trim()" @click="translate">
                转成英文预览
              </button>
              <span v-if="theme" class="tag blue">{{ theme }}</span>
              <span class="hint" v-if="en">实际提交给模型的英文提示词</span>
            </div>
            <div v-if="en" class="cg-en">{{ en }}</div>
          </div>

          <div class="field full">
            <label>AI 出图模型（可选）</label>
            <SelectBox :model-value="form.pid" :options="aiOptions" @update:model-value="setAiProfile" />
            <div class="hint">
              「设置 → 工序绑定 → AI 封面底图」里可以预设档案；选中后优先用该模型出图，
              模型不支持出图时会自动回退到默认出图，不会卡住生成。
            </div>
            <div class="hint" v-if="form.pid && !coverCreds?.api_key" style="color:var(--orange)">
              该档案还没填 API Key，本次会直接走默认出图。
            </div>
          </div>

          <div class="field">
            <label>底图模型</label>
            <SelectBox :model-value="modelText" :options="modelOptions" @update:model-value="setModel" />
            <div class="hint">默认出图用的免费模型；选了上面的 AI 档案时以档案模型为准。</div>
          </div>

          <div class="field">
            <label>随机种子（可留空）</label>
            <input v-model="form.seed" class="input" type="number" placeholder="固定种子可复现同一张底图" />
          </div>

          <div class="field">
            <label>文字风格</label>
            <SelectBox :model-value="styleText" :options="styleOptions" @update:model-value="setStyle" />
          </div>

          <div class="field">
            <label>书名版式</label>
            <SelectBox :model-value="layoutText" :options="layoutOptions" @update:model-value="setLayout" />
          </div>

          <div class="field full">
            <label class="cg-check">
              <input v-model="form.reuse_base" type="checkbox" />
              只换文字，复用上次底图（改书名/字体时更快，不重新出图）
            </label>
            <div class="hint">
              底图由 Pollinations 免费生成（flux 系列，无水印）；中文提示词在本地词表翻译，
              无法逐词翻译时按题材模板兜底，不会把中文丢给模型。
            </div>
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <button class="btn ghost" :disabled="busy" @click="emit('update:open', false)">取消</button>
      <button class="btn" :disabled="busy" @click="run">
        {{ busy ? `正在出图与排版… ${elapsed}s` : '生成并应用封面' }}
      </button>
    </template>
  </Modal>
</template>

<style scoped>
.cover-gen { display: grid; grid-template-columns: 210px minmax(0, 1fr); gap: 20px; }
.cg-preview {
  width: 210px; aspect-ratio: 2 / 3; border-radius: 10px; overflow: hidden;
  background: #f2f3f5; border: 1px solid var(--border);
  display: flex; align-items: center; justify-content: center;
}
.cg-preview img { width: 100%; height: 100%; object-fit: cover; display: block; }
.cg-empty { font-size: 12px; color: var(--text-3); }
.cg-left .hint { margin-top: 10px; }
.cg-size { font-size: 13px; padding: 8px 0; color: var(--text); }
.chip-row { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.cg-en-row { display: flex; align-items: center; gap: 8px; margin-top: 8px; }
.cg-en {
  margin-top: 6px; padding: 8px 10px; border-radius: 6px; background: #f7f8fa;
  border: 1px solid var(--border); font-size: 12px; color: var(--text-2);
  line-height: 1.6; max-height: 96px; overflow: auto; word-break: break-word;
}
.cg-check { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-2); }
.cg-err {
  display: flex; align-items: center; gap: 10px; margin-bottom: 12px;
  padding: 8px 10px; border-radius: 6px; font-size: 12px; line-height: 1.6;
  background: #fff4f4; border: 1px solid #f3c9c9; color: #b42318;
}
</style>
