<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import Icon from '../components/Icon.vue'
import BookArt from './BookArt.vue'
import MobilePicker from './MobilePicker.vue'
import { api } from '../api'
import type { CoverPresets } from '../types'
import { state, store } from '../store'
import { toast } from '../ui'

const router = useRouter()
const meta = computed(() => state.books.find(b => b.name === store.curBook()) || null)
const presets = ref<CoverPresets | null>(null)
const loadError = ref('')
const loading = ref(true)
const busy = ref(false)
const elapsed = ref(0)
const tick = ref(Date.now())
const generated = ref(false)
const notice = ref('')
const theme = ref('')
let timer: ReturnType<typeof setInterval> | null = null

const form = reactive({
  platform: 'fanqie', width: 1400, height: 2100, fmt: 'jpg',
  title: '', author: '', prompt: '', model: 'flux', style: 'gold', layout: 'top',
  seed: '', reuse_base: false,
  /* 出图用的模型档案 id：空 = 默认出图；与桌面端同一套「AI 封面底图」绑定 */
  aiPid: '',
})

const coverProfiles = computed(() => Object.entries(state.studio?.profiles || {}).map(([pid, p]) => ({
  pid,
  label: `${p.name || p.model || '未命名档案'} · ${p.model || '未设模型'}`,
})))
const aiOptions = computed(() => [
  { label: '默认出图（不占用模型额度）', value: '' },
  ...coverProfiles.value.map(p => ({ label: p.label, value: p.pid })),
])
const coverCreds = computed(() => {
  const pid = form.aiPid
  if (!pid) return null
  const profile = state.studio?.profiles?.[pid]
  if (!profile) return null
  return { api_key: store.profileKey(pid), base_url: profile.base_url, ai_model: profile.model }
})
const curPlatform = computed(() => presets.value?.platforms.find(p => p.key === form.platform))
const isCustom = computed(() => form.platform === 'custom')

/* 选择器用「显示名 ↔ 内部 key」两张表：底部弹层只认字符串，避免再落回原生 select */
const platformLabel = (p: { name: string; width: number; height: number }) => `${p.name} · ${p.width}×${p.height}`
const platformText = computed(() => {
  const p = curPlatform.value
  return p ? platformLabel(p) : '自定义尺寸'
})
const platformOptions = computed(() => [
  ...(presets.value?.platforms || []).map(platformLabel),
  '自定义尺寸',
])
function setPlatform(label: string) {
  const hit = presets.value?.platforms.find(p => platformLabel(p) === label)
  applyPlatform(hit ? hit.key : 'custom')
}
const modelOptions = computed(() => (presets.value?.models || []).map(m => m.name))
const modelText = computed(() => presets.value?.models.find(m => m.key === form.model)?.name || '')
function setModel(name: string) {
  const hit = presets.value?.models.find(m => m.name === name)
  if (hit) form.model = hit.key
}
const styleOptions = computed(() => (presets.value?.styles || []).map(s => s.name))
const styleText = computed(() => presets.value?.styles.find(s => s.key === form.style)?.name || '')
function setStyle(name: string) {
  const hit = presets.value?.styles.find(s => s.name === name)
  if (hit) form.style = hit.key
}
const layoutOptions = computed(() => (presets.value?.layouts || []).map(l => l.name))
const layoutText = computed(() => presets.value?.layouts.find(l => l.key === form.layout)?.name || '')
function setLayout(name: string) {
  const hit = presets.value?.layouts.find(l => l.name === name)
  if (hit) form.layout = hit.key
}
const FMT_OPTIONS = ['JPG（体积小）', 'PNG']
const fmtText = computed(() => form.fmt === 'png' ? 'PNG' : 'JPG（体积小）')
function setFmt(v: string) { form.fmt = v === 'PNG' ? 'png' : 'jpg' }

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

async function loadPresets(force = false) {
  if (presets.value && !force) return
  loading.value = true
  loadError.value = ''
  try {
    const p = await api.coverPresets()
    if (!p?.platforms?.length) throw new Error('封面平台列表为空')
    presets.value = p
    if (!p.platforms.some(x => x.key === form.platform)) form.platform = p.platforms[0]?.key || 'custom'
    form.model = p.models?.[0]?.key || 'flux'
    form.style = p.styles?.[0]?.key || 'gold'
    form.layout = p.layouts?.[0]?.key || 'top'
    applyPlatform(form.platform)
  } catch (e: any) {
    presets.value = null
    loadError.value = e?.message || '封面选项加载失败'
  } finally {
    loading.value = false
  }
}
function applyPlatform(key: string) {
  form.platform = key
  const p = presets.value?.platforms.find(x => x.key === key)
  if (p) { form.width = p.width; form.height = p.height; form.fmt = p.fmt }
}
function useTheme(p: string) {
  form.prompt = p
  theme.value = ''
}
async function translate() {
  const t = form.prompt.trim()
  if (!t) { theme.value = ''; return }
  try { theme.value = (await api.coverTranslate(t)).theme }
  catch { /* 预览失败不阻塞生成 */ }
}
async function generate() {
  if (!meta.value || busy.value) return
  const title = form.title.trim() || meta.value.title || meta.value.name
  if (!title) return toast('请填写书名', 'err')
  const author = form.author.trim() || meta.value.author || '佚名'
  busy.value = true
  elapsed.value = 0
  notice.value = ''
  if (timer) clearInterval(timer)
  timer = setInterval(() => { elapsed.value++ }, 1000)
  try {
    const ai = coverCreds.value
    const r = await api.coverGenerate({
      book: meta.value.name,
      title,
      author,
      prompt: form.prompt.trim(),
      width: Number(form.width) || 1400,
      height: Number(form.height) || 2100,
      fmt: form.fmt,
      model: form.model,
      style: form.style,
      layout: form.layout,
      seed: form.seed || undefined,
      reuse_base: form.reuse_base,
      api_key: ai?.api_key || '', base_url: ai?.base_url || '', ai_model: ai?.ai_model || '',
    })
    tick.value = Date.now()
    generated.value = true
    notice.value = r.fallback
      ? (r.notice || '出图接口不可用，已用本地底图完成排版')
      : r.source === 'ai'
        ? `已生成 ${r.width}×${r.height} · 底图由 ${r.ai_model || 'AI 模型'} 绘制`
        : `已生成 ${r.width}×${r.height} · ${r.model}` +
          (r.ai_note ? '（AI 模型不支持出图，已回退默认出图）' : '')
    theme.value = r.theme || theme.value
    store.loadStats().catch(() => {})
    toast('封面已生成并应用', 'ok')
  } catch (e: any) {
    toast(e.message || '生成失败', 'err')
  } finally {
    busy.value = false
    if (timer) { clearInterval(timer); timer = null }
  }
}

/* 下载当前封面：App 内由原生桥存到「下载 / 墨写」，浏览器里走普通下载 */
async function downloadCover() {
  if (!meta.value) return
  try {
    const r = await fetch(api.coverUrl(meta.value.name, tick.value || Date.now()), { cache: 'no-store' })
    if (!r.ok) throw new Error('封面读取失败')
    const blob = await r.blob()
    const ext = /png/i.test(blob.type) ? 'png' : /webp/i.test(blob.type) ? 'webp' : 'jpg'
    const a = document.createElement('a')
    const url = URL.createObjectURL(blob)
    a.href = url
    a.download = `${meta.value.title || meta.value.name}-封面.${ext}`
    document.body.appendChild(a)
    a.click()
    a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 2000)
    toast('已开始下载封面', 'ok')
  } catch (e: any) {
    toast(e.message || '下载失败', 'err')
  }
}

onMounted(async () => {
  const m = meta.value
  if (m) {
    form.title = m.title || m.name
    form.author = m.author || ''
  }
  form.aiPid = store.profileFor('cover')?.pid || ''
  await loadPresets()
})
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>

<template>
  <div class="m-page m-secondary-page m-cover-page">
    <div v-if="!meta" class="m-empty" style="padding-top:60px">
      <span class="m-empty-ico"><Icon name="book" :size="28" /></span>
      <b>还没有选择作品</b>
      <p>先在左侧抽屉选择一部作品，再来生成封面。</p>
      <button class="m-btn" @click="router.push('/overview')">返回作品</button>
    </div>

    <template v-else>
      <div class="m-sec-head">
        <div class="m-sec-head-txt">出图后自动排版书名与作者，并按平台尺寸输出</div>
      </div>

      <!-- 预览 -->
      <div class="m-cover-preview">
        <div class="m-cover-preview-art">
          <BookArt :name="meta.name" :title="form.title || meta.title" :author="form.author || meta.author"
                   :has-cover="meta.has_cover || generated" size="lg" :tick="tick" />
        </div>
        <div class="m-cover-preview-meta">
          <b>{{ form.title || meta.title || meta.name }}</b>
          <span>{{ form.author || meta.author || '佚名' }} 著</span>
          <span>{{ form.width }} × {{ form.height }} · {{ form.fmt.toUpperCase() }}</span>
          <span class="m-tag" :class="busy ? 'gold' : 'green'">{{ busy ? '生成中' : '当前封面' }}</span>
          <button v-if="meta.has_cover || generated" class="m-btn sm ghost"
                  style="align-self:flex-start;margin-top:6px" @click="downloadCover">
            <Icon name="download" :size="13" /> 下载封面
          </button>
        </div>
      </div>

      <div v-if="loading" class="m-empty" style="padding-top:30px">
        <span class="m-empty-ico"><Icon name="refresh" :size="26" /></span>
        <b>正在载入封面选项</b>
      </div>

      <div v-else-if="loadError" class="m-card" style="margin-top:12px">
        <p class="m-hint" style="color:var(--m-red)">{{ loadError }}</p>
        <button class="m-btn ghost block" style="margin-top:10px" @click="loadPresets(true)">重新加载</button>
      </div>

      <template v-else>
        <div class="m-card" style="margin-top:12px">
          <div class="m-card-head"><b>基本信息</b></div>
          <div class="m-form">
            <div class="m-field">
              <label>发布平台</label>
              <MobilePicker :model-value="platformText" :options="platformOptions" title="选择发布平台"
                            :allow-empty="false" @update:model-value="setPlatform" />
              <p v-if="curPlatform?.note" class="m-hint">{{ curPlatform.note }}</p>
            </div>
            <div v-if="isCustom" class="m-form-2">
              <div class="m-field">
                <label>宽度<em>px</em></label>
                <input class="m-input" type="number" v-model.number="form.width" min="64" :max="presets?.max_side || 4096" />
              </div>
              <div class="m-field">
                <label>高度<em>px</em></label>
                <input class="m-input" type="number" v-model.number="form.height" min="64" :max="presets?.max_side || 4096" />
              </div>
            </div>
            <div class="m-form-2">
              <div class="m-field">
                <label>书名</label>
                <input class="m-input" v-model="form.title" maxlength="60" placeholder="封面上的书名" />
              </div>
              <div class="m-field">
                <label>作者</label>
                <input class="m-input" v-model="form.author" maxlength="40" placeholder="自动补「著」" />
              </div>
            </div>
            <div class="m-field">
              <label>底图提示词<em>中文会自动转英文</em></label>
              <textarea class="m-textarea" v-model="form.prompt" style="min-height:88px"
                        placeholder="如：云雾缭绕的仙山，御剑飞行的背影，金色晨光，电影感"
                        @blur="translate"></textarea>
              <div class="m-chips">
                <button v-for="x in THEMES" :key="x.t" class="m-chip"
                        :class="{ on: form.prompt === x.p }" @click="useTheme(x.p)">{{ x.t }}</button>
              </div>
            </div>
          </div>
        </div>

        <div class="m-card" style="margin-top:12px">
          <div class="m-card-head"><b>画面与版式</b></div>
          <div class="m-form">
            <div class="m-field">
              <label>AI 出图模型<em>可选，不支持时自动回退</em></label>
              <MobilePicker :model-value="form.aiPid" :options="aiOptions" title="选择 AI 出图模型"
                            empty-label="默认出图（不占用模型额度）"
                            @update:model-value="v => form.aiPid = v" />
              <p class="m-hint">在「设置 → 工序绑定 → AI 封面底图」里预设；选中后优先用该模型出图。</p>
              <p v-if="form.aiPid && !coverCreds?.api_key" class="m-hint" style="color:var(--m-red)">
                该档案还没填 API Key，本次会走默认出图。
              </p>
            </div>
            <div class="m-form-2">
              <div class="m-field">
                <label>底图模型</label>
                <MobilePicker :model-value="modelText" :options="modelOptions" title="选择底图模型"
                              :allow-empty="false" @update:model-value="setModel" />
              </div>
              <div class="m-field">
                <label>文字风格</label>
                <MobilePicker :model-value="styleText" :options="styleOptions" title="选择文字风格"
                              :allow-empty="false" @update:model-value="setStyle" />
              </div>
            </div>
            <div class="m-field">
              <label>书名版式</label>
              <MobilePicker :model-value="layoutText" :options="layoutOptions" title="选择书名版式"
                            :allow-empty="false" @update:model-value="setLayout" />
            </div>
            <div class="m-form-2">
              <div class="m-field">
                <label>随机种子<em>可留空</em></label>
                <input class="m-input" v-model="form.seed" inputmode="numeric" placeholder="固定可复现" />
              </div>
              <div class="m-field">
                <label>图片格式</label>
                <MobilePicker :model-value="fmtText" :options="FMT_OPTIONS" title="选择图片格式"
                              :allow-empty="false" @update:model-value="setFmt" />
              </div>
            </div>
            <button class="m-toggle-row" @click="form.reuse_base = !form.reuse_base">
              <span><b>复用上次底图</b><small>只换书名 / 字体，不重新出图</small></span>
              <i class="m-toggle" :class="{ on: form.reuse_base }"><em></em></i>
            </button>
          </div>
        </div>

        <div v-if="notice" class="m-cover-notice">
          <Icon name="check" :size="14" /> {{ notice }}
        </div>

        <div class="m-cover-savebar">
          <span v-if="busy" class="m-hint">正在出图与排版… {{ elapsed }}s</span>
          <span v-else class="m-hint">生成后会直接应用到封面页</span>
          <span class="m-spacer"></span>
          <button class="m-btn" :disabled="busy" @click="generate">
            <Icon name="edit" :size="15" /> {{ busy ? '生成中…' : '生成封面' }}
          </button>
        </div>
      </template>
    </template>
  </div>
</template>

<style scoped>
.m-cover-page { padding-bottom: calc(96px + env(safe-area-inset-bottom)) !important; }
.m-spacer { flex: 1; }
.m-cover-preview {
  display: flex; align-items: center; gap: 15px;
  padding: 16px; border-radius: 20px;
  background: linear-gradient(150deg, #173a35, #0c2421 62%, #14302b);
  color: #fff; overflow: hidden;
}
.m-cover-preview-art { flex: none; }
.m-cover-preview-art :deep(.m-book-art) { box-shadow: 0 16px 34px rgba(0, 0, 0, .45); }
.m-cover-preview-meta { min-width: 0; display: flex; flex-direction: column; gap: 5px; }
.m-cover-preview-meta b {
  font-family: "Songti SC", "Noto Serif SC", serif;
  font-size: 20px; font-weight: 700; line-height: 1.3;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.m-cover-preview-meta > span:not(.m-tag) { font-size: 11px; color: rgba(255, 255, 255, .65); }
.m-cover-preview-meta .m-tag { align-self: flex-start; margin-top: 2px; }
.m-cover-notice {
  display: flex; gap: 6px; align-items: flex-start;
  margin-top: 12px; padding: 10px 12px; border-radius: 12px;
  background: var(--m-primary-soft); color: var(--m-primary); font-size: 12px; line-height: 1.55;
}
.m-cover-savebar {
  position: fixed; left: 0; right: 0; bottom: 0; z-index: 46;
  display: flex; align-items: center; gap: 10px;
  padding: 10px 16px calc(10px + env(safe-area-inset-bottom));
  background: rgba(255, 255, 255, .96);
  -webkit-backdrop-filter: blur(16px); backdrop-filter: blur(16px);
  border-top: 1px solid var(--m-line);
  box-shadow: 0 -10px 28px rgba(20, 30, 27, .06);
}
</style>
