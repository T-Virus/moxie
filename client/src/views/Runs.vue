<template>
  <main class="page runs">
    <div class="page-head runs__head">
      <div>
        <h1 class="page-title">我的作品</h1>
        <p v-if="session.account" class="page-sub">
          历史运行记录，点击进入工作台查看进度与结果。
        </p>
      </div>
      <RouterLink v-if="session.account" to="/" class="btn btn--brand">新建创作</RouterLink>
    </div>

    <section v-if="!session.account" class="card runs__guest">
      <h2 class="runs__guest-title">作品与账号绑定，登录后查看</h2>
      <p class="runs__guest-text">
        本页不会展示本机历史或演示数据；登录后可查看属于你的运行记录与中断任务。
      </p>
      <div class="runs__guest-actions">
        <RouterLink :to="{ name: 'login', query: { next: '/runs' } }" class="btn">登录</RouterLink>
        <RouterLink
          :to="{ name: 'login', query: { next: '/runs', tab: 'register' } }"
          class="btn btn--brand"
        >
          注册
        </RouterLink>
      </div>
    </section>

    <template v-else>
      <section class="card filters" aria-label="作品筛选">
        <div class="filters__row" role="group" aria-label="频道">
          <span class="filters__label">频道</span>
          <button
            v-for="option in AUDIENCE_FILTERS"
            :key="option.value"
            type="button"
            class="filters__chip"
            :class="{ 'is-active': filters.audience === option.value }"
            :aria-pressed="filters.audience === option.value"
            @click="setFilter({ audience: option.value })"
          >
            {{ option.label }}
          </button>
        </div>

        <div class="filters__row" role="group" aria-label="篇幅">
          <span class="filters__label">篇幅</span>
          <button
            v-for="option in LENGTH_FILTERS"
            :key="option.value"
            type="button"
            class="filters__chip"
            :class="{ 'is-active': filters.length === option.value }"
            :aria-pressed="filters.length === option.value"
            @click="setFilter({ length: option.value })"
          >
            {{ option.label }}
          </button>
        </div>

        <div class="filters__row" role="group" aria-label="题材">
          <span class="filters__label">题材</span>
          <div ref="genreBox" class="filters__genre">
            <button
              type="button"
              class="filters__trigger"
              :class="{ 'is-active': filters.genre }"
              aria-haspopup="listbox"
              :aria-expanded="genreOpen"
              @click="genreOpen = !genreOpen"
            >
              <span class="filters__trigger-text">{{ genreLabel }}</span>
              <i class="filters__caret" aria-hidden="true" />
            </button>
            <div v-if="genreOpen" class="filters__menu" role="listbox" aria-label="选择题材">
              <button
                type="button"
                role="option"
                class="filters__option"
                :class="{ 'is-selected': filters.genre === '' }"
                :aria-selected="filters.genre === ''"
                @click="pickGenre('')"
              >
                全部题材
                <span v-if="filters.genre === ''" class="filters__check">✓</span>
              </button>
              <button
                v-for="genre in genreOptions"
                :key="genre.id"
                type="button"
                role="option"
                class="filters__option"
                :class="{ 'is-selected': filters.genre === genre.id }"
                :aria-selected="filters.genre === genre.id"
                @click="pickGenre(genre.id)"
              >
                {{ genre.name }}
                <span v-if="filters.genre === genre.id" class="filters__check">✓</span>
              </button>
            </div>
          </div>
          <button v-if="hasFilters" type="button" class="filters__clear" @click="clearFilters">
            清除筛选
          </button>
        </div>
      </section>

      <div v-if="loading" class="empty">正在加载作品…</div>

      <div v-else-if="error" class="alert" role="alert">
        <span>{{ error }}</span>
        <button type="button" class="runs__retry" @click="load">重试</button>
      </div>

      <template v-else>
        <div v-if="degraded" class="alert alert--warn runs__notice" role="status">
          {{ degraded }}
        </div>

        <div class="runs__toolbar">
          <input
            v-model="searchInput"
            class="runs__search"
            type="search"
            placeholder="按书名搜索"
            aria-label="按书名搜索"
            @input="onSearchInput"
          />
          <div class="runs__tools">
            <span class="runs__count" role="status">共 {{ total }} 部</span>
            <template v-if="runs.length">
              <button
                type="button"
                class="runs__page-btn"
                :disabled="page <= 1"
                aria-label="上一页"
                @click="goPage(page - 1)"
              >
                上一页
              </button>
              <span class="runs__page-info">第 {{ page }} / {{ pageCount }} 页</span>
              <button
                type="button"
                class="runs__page-btn"
                :disabled="page >= pageCount"
                aria-label="下一页"
                @click="goPage(page + 1)"
              >
                下一页
              </button>
            </template>
          </div>
        </div>

        <div class="runs__scroll">
          <div v-if="runs.length" class="runs__grid">
          <RouterLink
            v-for="item in pagedRuns"
            :key="item.run_id"
            :to="{ name: 'workspace', params: { id: item.run_id } }"
            class="run-card"
            :aria-label="`进入《${item.title}》工作台`"
          >
            <span class="run-card__cover" :class="`is-${item.mode}`" aria-hidden="true">
              {{ titleInitial(item.title) }}
            </span>

            <div class="run-card__body">
              <div class="run-card__head">
                <h2 class="run-card__title">{{ item.title }}</h2>
                <span class="run-card__go" aria-hidden="true">→</span>
              </div>

              <div class="run-card__tags">
                <span
                  class="run-card__tag run-card__tag--mode"
                  :class="`is-${item.mode}`"
                >
                  {{ MODE_LABEL[item.mode] }}
                </span>
                <span class="run-card__tag">{{ item.audience === 'male' ? '男频' : '女频' }}</span>
                <span class="run-card__tag">{{ item.length === 'long' ? '长篇' : '短篇' }}</span>
                <span class="run-card__tag">{{ item.genre?.name || '未限定题材' }}</span>
              </div>

              <p class="run-card__logline">
                {{ item.summary?.logline || '任务尚未生成摘要' }}
              </p>

              <div class="run-card__foot">
                <span class="run-card__stat"><b>{{ item.summary?.chapters_count ?? 0 }}</b> 章</span>
                <span class="run-card__stat">{{ wordCountText(item) }}</span>
                <span class="run-card__updated">{{ updatedAtText(item) }} 更新</span>
              </div>
            </div>
          </RouterLink>
          </div>

          <div v-if="!runs.length" class="empty runs__empty">
        <p class="empty__title">{{ hasFilters ? '没有符合条件的作品' : '还没有作品记录' }}</p>
        <p v-if="hasFilters">当前筛选组合没有命中，试试放宽条件或清除筛选。</p>
        <p v-else>从首页输入书名开始第一次创作，完成或中断的任务都会出现在这里。</p>
        <button v-if="hasFilters" type="button" class="btn btn--brand runs__cta" @click="clearFilters">
          清除筛选
        </button>
        <RouterLink v-else to="/" class="btn btn--brand runs__cta">去创作</RouterLink>
          </div>
        </div>
      </template>
    </template>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { Audience, RunDetail, RunLength } from '@/types'
import { listRuns } from '@/services/agentApi'
import { ApiError } from '@/services/http'
import { resetSession, session } from '@/stores/session'
import { MODE_LABEL, relativeTime } from '@/utils/format'

interface Filters {
  audience: Audience | ''
  length: RunLength | ''
  genre: string
  q: string
}

const FILTER_CACHE_KEY = 'mx_runs_filters'
const AUDIENCE_VALUES: Audience[] = ['male', 'female']
const LENGTH_VALUES: RunLength[] = ['long', 'short']

const AUDIENCE_FILTERS: Array<{ value: Audience | ''; label: string }> = [
  { value: '', label: '全部' },
  { value: 'male', label: '男频' },
  { value: 'female', label: '女频' },
]
const LENGTH_FILTERS: Array<{ value: RunLength | ''; label: string }> = [
  { value: '', label: '全部' },
  { value: 'long', label: '长篇' },
  { value: 'short', label: '短篇' },
]

const route = useRoute()
const router = useRouter()

const filters = reactive<Filters>({ audience: '', length: '', genre: '', q: '' })
const hasFilters = computed(() =>
  Boolean(filters.audience || filters.length || filters.genre || filters.q),
)

const runs = ref<RunDetail[]>([])
/** 服务端筛选命中总数（未翻页），用于「共 N 部」 */
const total = ref(0)
const loading = ref(false)
const error = ref('')
const degraded = ref('')
let loadSeq = 0

/* ---- 题材下拉：选项完全来自已创建书籍中实际用到的题材（随数据同步），不展示全量预设 ---- */
const genreBox = ref<HTMLElement | null>(null)
const genreOpen = ref(false)
const dataGenres = ref(new Map<string, string>())
const genreOptions = computed<Array<{ id: string; name: string }>>(() =>
  [...dataGenres.value].map(([id, name]) => ({ id, name })),
)
const genreLabel = computed(() => {
  if (!filters.genre) return '全部题材'
  const hit = genreOptions.value.find(g => g.id === filters.genre || g.name === filters.genre)
  return hit?.name || filters.genre
})

function pickGenre(id: string): void {
  genreOpen.value = false
  if (filters.genre !== id) setFilter({ genre: id })
}

function onDocPointerDown(event: PointerEvent): void {
  if (genreOpen.value && genreBox.value && !genreBox.value.contains(event.target as Node)) {
    genreOpen.value = false
  }
}

/* ---- 书名搜索：输入防抖 300ms 后并入筛选 ---- */
const searchInput = ref('')
let searchTimer: number | undefined

function onSearchInput(): void {
  window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => {
    const q = searchInput.value.trim()
    if (q === filters.q) return
    filters.q = q
    void commitFilters()
  }, 300)
}

/* ---- 分页：接口无服务端分页，按当前命中列表做客户端分页 ---- */
const PAGE_SIZE = 12
const page = ref(1)
const pageCount = computed(() => Math.max(1, Math.ceil(runs.value.length / PAGE_SIZE)))
const pagedRuns = computed(() =>
  runs.value.slice((page.value - 1) * PAGE_SIZE, page.value * PAGE_SIZE),
)

function goPage(next: number): void {
  page.value = Math.min(Math.max(1, next), pageCount.value)
}

function readFiltersFromQuery(): void {
  const query = route.query
  filters.audience =
    typeof query.audience === 'string' && AUDIENCE_VALUES.includes(query.audience as Audience)
      ? (query.audience as Audience)
      : ''
  filters.length =
    typeof query.length === 'string' && LENGTH_VALUES.includes(query.length as RunLength)
      ? (query.length as RunLength)
      : ''
  filters.genre = typeof query.genre === 'string' ? query.genre : ''
  filters.q = typeof query.q === 'string' ? query.q : ''
}

function restoreCachedFilters(): void {
  try {
    const raw = sessionStorage.getItem(FILTER_CACHE_KEY)
    if (!raw) return
    const cached = JSON.parse(raw) as Partial<Filters>
    if (cached.audience && AUDIENCE_VALUES.includes(cached.audience)) {
      filters.audience = cached.audience
    }
    if (cached.length && LENGTH_VALUES.includes(cached.length)) filters.length = cached.length
    if (typeof cached.genre === 'string') filters.genre = cached.genre
    if (typeof cached.q === 'string') filters.q = cached.q
  } catch {
    // 忽略损坏的本地缓存
  }
}

function currentQuery(): Record<string, string> {
  const query: Record<string, string> = {}
  if (filters.audience) query.audience = filters.audience
  if (filters.length) query.length = filters.length
  if (filters.genre) query.genre = filters.genre
  if (filters.q) query.q = filters.q
  return query
}

function cacheFilters(): void {
  sessionStorage.setItem(FILTER_CACHE_KEY, JSON.stringify(currentQuery()))
}

/** 刷新后没有 query 时恢复上一次筛选，并把状态写回 URL */
async function prepareFilters(): Promise<void> {
  if (hasFilters.value) return
  restoreCachedFilters()
  if (hasFilters.value) await router.replace({ query: currentQuery() })
}

function setFilter(patch: Partial<Filters>): void {
  Object.assign(filters, patch)
  void commitFilters()
}

function clearFilters(): void {
  filters.audience = ''
  filters.length = ''
  filters.genre = ''
  filters.q = ''
  searchInput.value = ''
  void commitFilters()
}

async function commitFilters(): Promise<void> {
  cacheFilters()
  if (
    route.query.audience !== (filters.audience || undefined) ||
    route.query.length !== (filters.length || undefined) ||
    route.query.genre !== (filters.genre || undefined) ||
    route.query.q !== (filters.q || undefined)
  ) {
    await router.replace({ query: currentQuery() })
  }
  await load()
}

/* ---- 卡片统计：总字数 / 更新章节 / 更新时间，列表按更新时间倒序 ---- */
/** 更新时间取运行级 updated_at，缺省回退章节完成时间、创建时间 */
function runUpdatedAtMs(item: RunDetail): number {
  const raw = item.updated_at || item.summary?.updated_at || item.created_at
  if (!raw) return 0
  const ms = Date.parse(raw)
  return Number.isNaN(ms) ? 0 : ms
}

function updatedAtText(item: RunDetail): string {
  const ms = runUpdatedAtMs(item)
  if (!ms) return '—'
  return relativeTime(new Date(ms).toISOString()) || '—'
}

function wordCountText(item: RunDetail): string {
  const n = item.summary?.word_count
  if (typeof n !== 'number' || n <= 0) return '—'
  if (n >= 10000) {
    const w = n / 10000
    return `${w >= 100 ? Math.round(w) : Math.round(w * 10) / 10} 万字`
  }
  return `${n} 字`
}

/** 无封面时用书名首字做封面色块 */
function titleInitial(title: string): string {
  return title.trim().charAt(0) || '书'
}

async function load(): Promise<void> {
  // 未登录不读取任何本机/演示记录，只展示账号引导
  if (!session.account) {
    runs.value = []
    total.value = 0
    error.value = ''
    loading.value = false
    return
  }
  const seq = ++loadSeq
  loading.value = true
  error.value = ''
  try {
    const result = await listRuns({
      audience: filters.audience,
      length: filters.length,
      genre: filters.genre,
      q: filters.q,
    })
    if (seq !== loadSeq) return
    // 最近更新的排最前（更新时间缺失的排末尾）
    runs.value = [...result.items].sort((a, b) => runUpdatedAtMs(b) - runUpdatedAtMs(a))
    // 有书名搜索时 total 以客户端过滤命中为准（服务端 total 不含 q）
    total.value = filters.q ? result.items.length : (result.total ?? result.items.length)
    degraded.value = result.degraded || ''
    // 记录作品里实际出现过的题材，供题材筛选项与数据保持同步
    for (const item of result.items) {
      if (item.genre?.id && item.genre.name) dataGenres.value.set(item.genre.id, item.genre.name)
    }
    page.value = 1
  } catch (err) {
    if (seq !== loadSeq) return
    // 会话过期：清空列表与账号态，回落到引导页
    if (err instanceof ApiError && err.status === 401) {
      runs.value = []
      total.value = 0
      degraded.value = ''
      error.value = ''
      resetSession()
      return
    }
    runs.value = []
    total.value = 0
    error.value =
      err instanceof ApiError ? err.message : '作品列表加载失败，请检查网络后重试'
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

watch(
  () => session.account,
  (account) => {
    // 账号态变化时先清空旧列表，避免未登录或切换账号后残留
    loadSeq += 1
    runs.value = []
    degraded.value = ''
    error.value = ''
    if (account) {
      cacheFilters()
      void load()
    } else {
      loading.value = false
    }
  },
)

onMounted(() => {
  readFiltersFromQuery()
  searchInput.value = filters.q
  document.addEventListener('pointerdown', onDocPointerDown)
  if (session.account) {
    void prepareFilters().then(() => load())
  }
})

onUnmounted(() => {
  window.clearTimeout(searchTimer)
  document.removeEventListener('pointerdown', onDocPointerDown)
})
</script>

<style scoped>
/* 整页占满视口内容区：头部/筛选/工具栏固定，仅书籍列表内部滚动 */
.runs {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding-top: var(--space-6);
  padding-bottom: var(--space-4);
}

.runs__head {
  flex: none;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
}

.runs__retry {
  margin-left: auto;
  color: var(--color-danger);
  font-size: var(--text-xs);
  text-decoration: underline;
}

.runs__notice {
  margin-bottom: var(--space-4);
}

.filters {
  flex: none;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px 16px;
  margin-bottom: var(--space-4);
  min-width: 0;
}

.filters__row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  min-width: 0;
}

.filters__group {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  min-width: 0;
}

.filters__genre {
  position: relative;
  display: inline-flex;
  align-items: center;
  min-width: 0;
}

.filters__label {
  font-size: 14px;
  color: var(--color-text-3);
  letter-spacing: 0.04em;
}

.filters__chip {
  flex: none;
  height: 30px;
  padding: 0 12px;
  border: 1px solid transparent;
  border-radius: var(--radius-pill);
  background: var(--color-bg-soft);
  color: var(--color-text-2);
  font-size: 14px;
  line-height: 28px;
  white-space: nowrap;
  transition: border-color var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease),
    background var(--dur-fast) var(--ease);
}

.filters__chip:hover {
  border-color: var(--color-line-strong);
  color: var(--color-text);
}

.filters__chip.is-active {
  border-color: var(--color-brand);
  background: rgba(13, 148, 136, 0.12);
  color: var(--color-brand);
  font-weight: 600;
}

/* 题材下拉触发器：与筛选 chip 同规格（30px 圆角胶囊），选中态同高亮 */
.filters__trigger {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 30px;
  max-width: 200px;
  padding: 0 12px;
  border: 1px solid transparent;
  border-radius: var(--radius-pill);
  background: var(--color-bg-soft);
  color: var(--color-text-2);
  font-size: 14px;
  transition: border-color var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease),
    background var(--dur-fast) var(--ease);
}

.filters__trigger-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.filters__trigger:hover {
  border-color: var(--color-line-strong);
  color: var(--color-text);
}

.filters__trigger.is-active {
  border-color: var(--color-brand);
  background: rgba(13, 148, 136, 0.12);
  color: var(--color-brand);
  font-weight: 600;
}

.filters__caret {
  flex: none;
  width: 0;
  height: 0;
  border-left: 4px solid transparent;
  border-right: 4px solid transparent;
  border-top: 5px solid currentColor;
}

/* 下拉面板：与首页题材选择器同款菜单视觉（白卡片 / 圆角 / 大阴影） */
.filters__menu {
  position: absolute;
  left: 0;
  top: calc(100% + 8px);
  z-index: 30;
  width: 224px;
  max-height: 288px;
  overflow-y: auto;
  overscroll-behavior: contain;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px;
  border-radius: var(--radius-md);
  background: #fff;
  border: 1px solid var(--color-line);
  box-shadow: var(--shadow-lg);
}

.filters__option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  padding: 7px 9px;
  border-radius: 8px;
  font-size: var(--text-sm);
  text-align: left;
  color: var(--color-text-2);
}

.filters__option:hover {
  background: var(--color-bg-soft);
  color: var(--color-text);
}

.filters__option.is-selected {
  background: #eef7f6;
  color: var(--color-brand);
  font-weight: 600;
}

.filters__check {
  font-size: var(--text-xs);
}

.filters__clear {
  flex: none;
  margin-left: auto;
  font-size: 14px;
  color: var(--color-text-3);
  text-decoration: underline;
  white-space: nowrap;
}

.filters__clear:hover {
  color: var(--color-text);
}

/* 筛选与书籍列表之间的工具栏：书名搜索 + 命中数 */
.runs__toolbar {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--space-4);
  margin-bottom: var(--space-3);
}

.runs__search {
  flex: 1;
  max-width: 320px;
  height: 34px;
  padding: 0 12px;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-pill);
  background: #fff;
  font-size: var(--text-sm);
}

.runs__search:focus {
  outline: none;
  border-color: var(--color-brand);
  box-shadow: 0 0 0 3px rgba(13, 148, 136, 0.12);
}

/* 搜索栏右侧：命中数 + 分页（常驻显示，单页时按钮置灰） */
.runs__tools {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.runs__count {
  font-size: var(--text-xs);
  color: var(--color-text-3);
}

.runs__page-btn {
  height: 30px;
  padding: 0 12px;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-pill);
  background: #fff;
  font-size: var(--text-xs);
  color: var(--color-text-2);
  transition: border-color var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
}

.runs__page-btn:hover:not(:disabled) {
  border-color: var(--color-brand);
  color: var(--color-brand);
}

.runs__page-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.runs__page-info {
  font-size: var(--text-xs);
  color: var(--color-text-3);
}

/* 列表滚动容器：滚动条出现在书籍列表内部 */
.runs__scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-width: thin;
  padding: 2px var(--space-2) var(--space-4) 2px;
}

.runs__scroll::-webkit-scrollbar {
  width: 8px;
}

.runs__scroll::-webkit-scrollbar-thumb {
  background: #d7dde5;
  border-radius: 8px;
}

.runs__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: var(--space-4);
}

/* ---------- 作品卡片：封面色块 + 信息区 ---------- */
.run-card {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 16px;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-md);
  background: #fff;
  min-width: 0;
  transition: border-color var(--dur-fast) var(--ease), box-shadow var(--dur-fast) var(--ease),
    transform var(--dur-fast) var(--ease);
}

.run-card:hover {
  border-color: rgba(13, 148, 136, 0.35);
  box-shadow: 0 8px 22px rgba(15, 23, 42, 0.07);
  transform: translateY(-2px);
}

.run-card:focus-visible {
  outline: 2px solid var(--color-brand);
  outline-offset: 2px;
}

/* 无封面数据时，用书名首字 + 模式色生成封面块 */
.run-card__cover {
  flex: none;
  width: 52px;
  height: 68px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: linear-gradient(140deg, #0f766e, #2dd4bf);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.16);
  color: #fff;
  font-size: 22px;
  font-weight: 700;
  line-height: 1;
  user-select: none;
}

.run-card__cover.is-hot {
  background: linear-gradient(140deg, #ea580c, #fb923c);
}

.run-card__cover.is-reference {
  background: linear-gradient(140deg, #1d4ed8, #60a5fa);
}

.run-card__cover.is-custom {
  background: linear-gradient(140deg, #0f766e, #2dd4bf);
}

.run-card__body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.run-card__head {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.run-card__title {
  font-size: var(--text-md);
  font-weight: 700;
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.run-card__go {
  flex: none;
  margin-left: auto;
  color: var(--color-text-3);
  font-size: 14px;
  line-height: 1;
  opacity: 0.6;
  transition: color var(--dur-fast) var(--ease), opacity var(--dur-fast) var(--ease),
    transform var(--dur-fast) var(--ease);
}

.run-card:hover .run-card__go {
  color: var(--color-brand);
  opacity: 1;
  transform: translateX(2px);
}

.run-card__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.run-card__tag {
  padding: 1px 8px;
  border-radius: var(--radius-pill);
  background: var(--color-bg-soft);
  color: var(--color-text-2);
  font-size: 14px;
  line-height: 17px;
  white-space: nowrap;
}

.run-card__tag--mode.is-hot {
  background: #fff1e7;
  color: #c2410c;
}

.run-card__tag--mode.is-reference {
  background: #e9f0ff;
  color: #1d4ed8;
}

.run-card__tag--mode.is-custom {
  background: rgba(13, 148, 136, 0.1);
  color: var(--color-brand);
}

.run-card__logline {
  font-size: var(--text-xs);
  line-height: 1.65;
  color: var(--color-text-2);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.run-card__foot {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-top: auto;
  padding-top: 7px;
  border-top: 1px dashed var(--color-line);
  font-size: 14px;
  color: var(--color-text-3);
  white-space: nowrap;
}

.run-card__stat b {
  color: var(--color-text-2);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.run-card__updated {
  margin-left: auto;
}

.runs__empty {
  padding: var(--space-10) var(--space-6);
}

.runs__cta {
  margin-top: var(--space-4);
}

.runs__guest {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  padding: var(--space-8) var(--space-6);
}

.runs__guest-title {
  font-size: var(--text-md);
}

.runs__guest-text {
  max-width: 560px;
  font-size: var(--text-sm);
  color: var(--color-text-2);
  line-height: 1.7;
}

.runs__guest-actions {
  display: flex;
  gap: 8px;
  margin-top: var(--space-3);
}

@media (max-width: 640px) {
  .runs__head {
    flex-direction: column;
  }

  .filters__clear {
    margin-left: 0;
  }

  .runs__toolbar {
    flex-wrap: wrap;
  }

  .runs__search {
    max-width: 100%;
  }

  .runs__tools {
    margin-left: 0;
  }

  .runs__grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
