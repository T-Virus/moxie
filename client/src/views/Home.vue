<template>
  <main class="page home">
    <div class="home__stage">
      <div class="home__tabs">
        <SegmentedTabs v-model="mode" :tabs="tabs" />
      </div>

      <form class="composer" :aria-busy="submitting" @submit.prevent="submit">
        <div class="composer__title-row">
          <input
            ref="titleInput"
            v-model="title"
            class="composer__input"
            type="text"
            maxlength="60"
            placeholder="写入书名，一起创作"
            aria-label="书名"
            :aria-invalid="showInvalidTitle"
            @blur="touched = true"
            @input="touched = true"
          />
        </div>

        <div class="composer__options">
          <div class="opt-group" role="group" aria-label="频向">
            <button
              v-for="item in audienceOptions"
              :key="item.value"
              type="button"
              class="chip"
              :class="{ 'is-on': audience === item.value }"
              :aria-pressed="audience === item.value"
              @click="audience = item.value"
            >
              {{ item.label }}
            </button>
          </div>

          <span class="composer__divider" aria-hidden="true" />

          <div class="opt-group" role="group" aria-label="篇幅">
            <button
              v-for="item in lengthOptions"
              :key="item.value"
              type="button"
              class="chip"
              :class="{ 'is-on': length === item.value }"
              :aria-pressed="length === item.value"
              @click="length = item.value"
            >
              {{ item.label }}
            </button>
          </div>

          <span class="composer__divider" aria-hidden="true" />

          <GenrePicker
            v-model="genre"
            :options="genres"
            :audience="audience"
            :custom-allowed="customAllowed"
          />

          <FileUploadChip
            v-if="mode === 'reference'"
            :file="file"
            @update:file="onFileChange"
            @error="onFileError"
          />
        </div>

        <div class="composer__actions">
          <button
            class="send"
            type="submit"
            title="开始创作"
            :disabled="invalid || submitting"
            :aria-label="submitting ? '正在创建任务' : '开始创作'"
          >
            <span v-if="submitting" class="send__spinner" aria-hidden="true" />
            <svg v-else viewBox="0 0 24 24" aria-hidden="true">
              <path d="M12 19V6M6 12l6-6 6 6" fill="none" stroke="currentColor" stroke-width="2" />
            </svg>
          </button>
        </div>

        <Transition name="fade">
          <div v-if="submitting" class="composer__overlay">
            <span class="composer__spinner" aria-hidden="true" />
            <span>{{ mode === 'reference' ? '正在上传参考文件并创建任务…' : '正在创建任务…' }}</span>
          </div>
        </Transition>
      </form>

      <div class="home__foot">
        <div class="home__meta">
          <p class="home__desc">{{ modeDesc }}</p>
        </div>
        <div class="byok">
          <button
            type="button"
            class="byok__toggle"
            :aria-expanded="byokOpen"
            @click="byokOpen = !byokOpen"
          >
            {{ byokKey ? '自带密钥（BYOK）已设置' : '使用自带密钥（BYOK）' }}
          </button>
          <div v-if="byokOpen" class="byok__box">
            <input
              v-model="byokKey"
              class="byok__input"
              type="password"
              autocomplete="off"
              placeholder="粘贴模型 API Key，仅本次会话内存保存"
              @input="onByokInput"
            />
            <button v-if="byokKey" type="button" class="byok__clear" @click="clearByok">
              清除
            </button>
          </div>
        </div>
      </div>
    </div>

    <Teleport to="body">
      <Transition name="toast">
        <div v-if="toastText" class="toast" role="alert">
          <span class="toast__text">{{ toastText }}</span>
          <button type="button" class="toast__close" aria-label="关闭提示" @click="closeToast">
            <svg viewBox="0 0 12 12" aria-hidden="true">
              <path d="M3 3l6 6M9 3l-6 6" fill="none" stroke="currentColor" stroke-width="1.4" />
            </svg>
          </button>
        </div>
      </Transition>
    </Teleport>
  </main>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import SegmentedTabs, { type SegmentedTab } from '@/components/SegmentedTabs.vue'
import GenrePicker from '@/components/GenrePicker.vue'
import FileUploadChip from '@/components/FileUploadChip.vue'
import type {
  Audience,
  GenreItem,
  GenreSelection,
  RunLength,
  RunMode,
  CreateRunPayload,
} from '@/types'
import { fetchGenres, createRun, uploadSource, getByokKey, setByokKey } from '@/services/agentApi'
import { ApiError } from '@/services/http'
import { session } from '@/stores/session'

const router = useRouter()

const tabs: SegmentedTab[] = [
  { id: 'hot', label: '热门写作' },
  { id: 'reference', label: '参考写作' },
  { id: 'custom', label: '大神写作' },
]

const MODE_DESC: Record<RunMode, string> = {
  hot: '参考同题材热门写法，生成前三章并自动换名换设定。',
  reference: '上传大纲或小说，全量改编为新书，自动换名换设定。',
  custom: '从书名开始，世界观、角色与章节全部由你定义。',
}

const audienceOptions: Array<{ value: Audience; label: string }> = [
  { value: 'male', label: '男频' },
  { value: 'female', label: '女频' },
]

const lengthOptions: Array<{ value: RunLength; label: string }> = [
  { value: 'long', label: '长篇' },
  { value: 'short', label: '短篇' },
]

const DRAFT_KEY = 'mx_composer_draft'
/* 默认题材：题材库缺失时也补一项，保证初始化即有可用选题 */
const DEFAULT_GENRE_NAME = '无脑爽文'
const DEFAULT_GENRE_ID = 'shuangwen'

const mode = ref<RunMode>('hot')
const title = ref('')
const audience = ref<Audience>('male')
const length = ref<RunLength>('long')
const genre = ref<GenreSelection>({ id: DEFAULT_GENRE_ID, name: DEFAULT_GENRE_NAME })
const file = ref<File | null>(null)
const genres = ref<GenreItem[]>([])
const customAllowed = ref(true)
const touched = ref(false)
const submitting = ref(false)
const titleInput = ref<HTMLInputElement | null>(null)
/* BYOK：仅会话内存保存，创建/续跑时透传 X-BYOK-Key；服务端只存 Redis TTL 1h */
const byokKey = ref(getByokKey())
const byokOpen = ref(false)

function onByokInput(): void {
  setByokKey(byokKey.value)
}

function clearByok(): void {
  byokKey.value = ''
  setByokKey('')
}
/* 页面级提示：同一时间只显示一条，可关闭，不遮挡创作面板 */
const toastText = ref('')
let toastTimer: ReturnType<typeof setTimeout> | null = null

function showToast(message: string): void {
  if (!message) return
  toastText.value = message
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => {
    toastText.value = ''
    toastTimer = null
  }, 6000)
}

function closeToast(): void {
  toastText.value = ''
  if (toastTimer) {
    clearTimeout(toastTimer)
    toastTimer = null
  }
}

const modeDesc = computed(() => MODE_DESC[mode.value])
const titleMissing = computed(() => !title.value.trim())
// 服务端 AgentGenre.name 必填（min_length=1），客户端必须同步拦截，否则会直接吃 422。
const genreMissing = computed(() => !genre.value.name.trim())
const fileMissing = computed(() => mode.value === 'reference' && !file.value)
const invalid = computed(() => titleMissing.value || genreMissing.value || fileMissing.value)
const showInvalidTitle = computed(() => titleMissing.value && touched.value)

function onFileChange(value: File | null): void {
  file.value = value
  touched.value = true
}

function onFileError(message: string): void {
  file.value = null
  showToast(message)
}

watch(audience, () => {
  if (!genre.value.id) return
  const item = genres.value.find((genreItem) => genreItem.id === genre.value.id)
  if (item && !(item.audience.includes(audience.value) || item.audience.includes('all'))) {
    genre.value = { id: null, name: '' }
  }
})

watch(mode, (_next, prev) => {
  if (prev === 'reference') file.value = null
  closeToast()
})

/* ---------------- 草稿：登录拦截或刷新后回来，表单内容不丢 ---------------- */
interface ComposerDraft {
  mode: RunMode
  title: string
  audience: Audience
  length: RunLength
  genre: GenreSelection
}

function readDraft(): ComposerDraft | null {
  try {
    const raw = sessionStorage.getItem(DRAFT_KEY)
    return raw ? (JSON.parse(raw) as ComposerDraft) : null
  } catch {
    return null
  }
}

function saveDraft(): void {
  const draft: ComposerDraft = {
    mode: mode.value,
    title: title.value,
    audience: audience.value,
    length: length.value,
    genre: genre.value,
  }
  sessionStorage.setItem(DRAFT_KEY, JSON.stringify(draft))
}

function clearDraft(): void {
  sessionStorage.removeItem(DRAFT_KEY)
}

watch([mode, title, audience, length, genre], saveDraft, { deep: true })

function errorText(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 0) return '无法连接服务端，请检查网络与后端地址后重试'
    if (err.status === 401) return '登录状态已失效，请重新登录后重试'
    if (err.status === 403 && err.code === 'subscription_required') {
      return '当前账号没有可用订阅：请先在「套餐」页开通，或联系管理员分配套餐额度。'
    }
    if (err.status === 402 && err.code === 'quota_exceeded') {
      return '本月书籍额度已用尽：可在「套餐」页购买额度包，或等下个账期重置。'
    }
    if (err.status === 413) return '大纲文件超过服务端大小限制（默认 30 MB）'
    if (err.status === 415) return '文件格式不被支持，请上传 .txt / .md 文件'
    if (err.status === 429) return '创建任务过于频繁，请稍后再试'
    if (err.code === 'rights_confirmation_required') {
      return '参考写作需要先确认你拥有上传作品的改编权。'
    }
    if (err.code === 'source_not_found') return '上传的源文件已失效，请重新选择文件后再试。'
    return err.message || `请求失败（${err.code}）`
  }
  return '创建任务失败，请稍后重试'
}

async function submit(): Promise<void> {
  touched.value = true
  if (submitting.value) return
  if (invalid.value) {
    if (titleMissing.value) titleInput.value?.focus()
    return
  }
  if (!session.account) {
    saveDraft()
    router.push({ name: 'login', query: { next: '/' } })
    return
  }

  submitting.value = true
  try {
    let sourceKey: string | null = null
    if (mode.value === 'reference' && file.value) {
      const uploaded = await uploadSource(file.value)
      sourceKey = uploaded.source_key
    }
    const payload: CreateRunPayload = {
      mode: mode.value,
      title: title.value.trim(),
      audience: audience.value,
      length: length.value,
      genre: genre.value,
      source_key: sourceKey,
    }
    const created = await createRun(payload)
    clearDraft()
    await router.push({ name: 'workspace', params: { id: created.run_id } })
  } catch (err) {
    showToast(errorText(err))
  } finally {
    submitting.value = false
  }
}

onBeforeUnmount(() => {
  if (toastTimer) clearTimeout(toastTimer)
})

onMounted(async () => {
  const draft = readDraft()
  if (draft) {
    mode.value = draft.mode
    title.value = draft.title
    audience.value = draft.audience
    length.value = draft.length
    // 旧草稿里可能存着空题材，此时保留默认题材
    if (draft.genre?.name) genre.value = draft.genre
  }
  try {
    const data = await fetchGenres()
    const items = data.items.slice()
    if (!items.some((item) => item.name === DEFAULT_GENRE_NAME)) {
      items.push({
        id: DEFAULT_GENRE_ID,
        name: DEFAULT_GENRE_NAME,
        audience: ['all'],
        tags: [],
      })
    }
    genres.value = items
    const matched = items.find((item) => item.name === genre.value.name)
    if (matched) genre.value = { id: matched.id, name: matched.name }
    customAllowed.value = data.custom_allowed
    if (data.degraded) showToast(data.degraded)
  } catch (err) {
    genres.value = []
    showToast(err instanceof ApiError ? err.message : '题材列表加载失败')
  }
})
</script>

<style scoped>
/* 首屏：按「顶栏以下可视高度」居中；内容超高时由 .shell__content 滚动 */
.home {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  min-height: calc(100dvh - var(--topbar-h));
  padding-block: var(--space-6);
}

.home__tabs {
  grid-row: 1;
  align-self: end;
  display: flex;
  justify-content: center;
  margin-bottom: var(--space-6);
}

/* ---------- 创作面板（参考图的深色发光容器） ---------- */
/* 1fr / auto / 1fr：整块创作模块在顶栏以下可视区居中后再整体上移 */
.home__stage {
  flex: 1;
  display: grid;
  grid-template-rows: 1fr auto 1fr;
  width: 100%;
  max-width: 960px;
  margin-inline: auto;
  /* 整块创作模块略高于几何中心，矮屏用 clamp 限制位移 */
  transform: translateY(calc(-1 * clamp(16px, 6vh, 72px)));
}

.composer {
  grid-row: 2;
  position: relative;
  display: flex;
  flex-direction: column;
  /* 顶部不再保留镜像占位行 */
  padding: 20px 24px;
  border-radius: var(--radius-xl);
  color: var(--panel-text);
  background:
    radial-gradient(120% 130% at 88% 100%, rgba(34, 211, 238, 0.16), transparent 58%),
    radial-gradient(90% 120% at 6% 0%, rgba(124, 58, 237, 0.12), transparent 52%),
    linear-gradient(128deg, var(--panel-bg-1) 0%, var(--panel-bg-2) 62%, #050e17 100%);
  box-shadow: var(--shadow-lg);
  isolation: isolate;
}

.composer::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  padding: 1px;
  background: linear-gradient(
    118deg,
    rgba(56, 189, 248, 0.55),
    rgba(124, 58, 237, 0.22) 42%,
    rgba(34, 211, 238, 0) 68%
  );
  -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
  -webkit-mask-composite: xor;
  mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
  mask-composite: exclude;
  pointer-events: none;
}

.composer::after {
  content: '';
  position: absolute;
  right: 12%;
  bottom: -1px;
  width: 42%;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(34, 211, 238, 0.75), transparent);
  filter: blur(0.5px);
  pointer-events: none;
}

.composer__title-row {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 64px;
}

/* 单行输入：固定 64px 高，line-height 与 height 同值，占位与正文同字号 */
.composer__input {
  flex: 1;
  min-width: 0;
  height: 38px;
  padding: 0 20px;
  border: none;
  background: transparent;
  color: #fff;
  font-family: inherit;
  font-size: 15px;
  line-height: 38px;
  letter-spacing: 0.01em;
}

.composer__input::placeholder {
  color: rgba(226, 235, 245, 0.5);
  /* 字号继承输入框自身，桌面 18px、移动端 16px，与正文一致 */
}

.composer__input:focus {
  outline: none;
}

.composer__options {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  padding-top: 12px;
  padding-right: 150px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.opt-group {
  display: inline-flex;
  gap: 4px;
  padding: 2px;
  border-radius: var(--radius-pill);
  background: rgba(255, 255, 255, 0.04);
}

.chip {
  height: 32px;
  padding: 0 14px;
  border-radius: var(--radius-pill);
  border: 1px solid transparent;
  color: rgba(214, 226, 238, 0.78);
  font-size: var(--text-sm);
  transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
}

.chip:hover {
  background: var(--panel-chip-hover);
  color: #fff;
}

.chip.is-on {
  background: #fff;
  border-color: #fff;
  color: #0b1220;
  font-weight: 600;
}

.composer__divider {
  width: 1px;
  height: 18px;
  margin: 0 2px;
  background: rgba(255, 255, 255, 0.14);
}

.composer__actions {
  position: absolute;
  right: 20px;
  bottom: 16px;
  display: flex;
  align-items: center;
}

/* 直径与选项胶囊（男频/长篇/题材，36px）一致，避免视觉上压过选项行 */
.send {
  flex: none;
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--color-brand);
  color: #fff;
  box-shadow: 0 10px 24px -14px rgba(13, 148, 136, 0.95);
  transition: transform var(--dur-fast) var(--ease), background var(--dur-fast) var(--ease),
    opacity var(--dur-fast) var(--ease);
}

.send svg {
  width: 20px;
  height: 20px;
}

.send:hover:not(:disabled) {
  transform: translateY(-1px);
  background: var(--color-brand-hover);
}

/* 未填书名 / 未选完时禁用：灰色 */
.send:disabled {
  background: rgba(255, 255, 255, 0.16);
  color: rgba(255, 255, 255, 0.45);
  box-shadow: none;
  cursor: not-allowed;
}

.send__spinner,
.composer__spinner {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: 2px solid rgba(255, 255, 255, 0.35);
  border-top-color: #fff;
  animation: spin 0.7s linear infinite;
}

.send__spinner {
  border-color: rgba(255, 255, 255, 0.35);
  border-top-color: #fff;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.composer__overlay {
  position: absolute;
  inset: 0;
  z-index: 5;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  border-radius: inherit;
  background: rgba(5, 14, 23, 0.72);
  backdrop-filter: blur(3px);
  font-size: var(--text-sm);
  color: #dbe7f1;
}

.home__foot {
  grid-row: 3;
  align-self: start;
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 14px;
}

.home__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.home__desc {
  color: var(--color-text-2);
  font-size: var(--text-sm);
}

/* ---------- BYOK：默认收起的次级入口，不干扰一键创作 ---------- */
.byok__toggle {
  font-size: var(--text-xs);
  color: var(--color-text-3);
  background: none;
  padding: 0;
  cursor: pointer;
}

.byok__toggle:hover {
  color: var(--color-brand);
}

.byok__box {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
}

.byok__input {
  flex: 1;
  max-width: 360px;
  height: 34px;
  padding: 0 10px;
  font-size: var(--text-sm);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-bg);
  color: var(--color-text-1);
}

.byok__clear {
  font-size: var(--text-xs);
  color: var(--color-text-3);
  background: none;
  padding: 0;
  cursor: pointer;
}

.byok__clear:hover {
  color: var(--color-danger);
}

/* ---------- 页面级 toast：底部居中、可关闭、不遮挡创作面板 ---------- */
.toast {
  position: fixed;
  left: 50%;
  bottom: 24px;
  z-index: 100;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  width: max-content;
  max-width: min(440px, calc(100vw - 32px));
  padding: 12px 12px 12px 16px;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  background: rgba(13, 24, 35, 0.96);
  color: #e8f1f8;
  font-size: var(--text-sm);
  line-height: 1.6;
  box-shadow: var(--shadow-lg);
  transform: translateX(-50%);
}

.toast__text {
  flex: 1;
  min-width: 0;
}

.toast__close {
  flex: none;
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  margin-top: 1px;
  border-radius: 50%;
  color: rgba(232, 241, 248, 0.7);
}

.toast__close:hover {
  background: rgba(255, 255, 255, 0.14);
  color: #fff;
}

.toast__close svg {
  width: 10px;
  height: 10px;
}

.toast-enter-active,
.toast-leave-active {
  transition: opacity var(--dur-fast) var(--ease), transform var(--dur-fast) var(--ease);
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translate(-50%, 8px);
}

@media (max-width: 640px) {
  .composer {
    padding: 20px 16px;
    border-radius: 20px;
  }

  .composer__input {
    font-size: var(--text-md);
  }

  .composer__divider {
    display: none;
  }

  .composer__options {
    padding-right: 64px;
  }

  .home__tabs {
    margin-bottom: var(--space-4);
  }
}
</style>
