<template>
  <main class="page page--wide ws">
    <div v-if="loading && !run" class="empty">正在加载任务详情…</div>

    <div v-else-if="loadError" class="card ws__error" role="alert">
      <div>
        <h2 class="ws__error-title">任务加载失败</h2>
        <p class="ws__error-text">{{ loadError }}</p>
      </div>
      <div class="ws__error-actions">
        <button type="button" class="btn" @click="retryLoad">重试</button>
        <RouterLink to="/runs" class="btn btn--ghost">返回我的作品</RouterLink>
      </div>
    </div>

    <template v-else-if="run">
      <header class="ws__head">
        <div class="ws__head-main">
          <div class="ws__crumb">
            <RouterLink to="/runs">我的作品</RouterLink>
            <span aria-hidden="true">/</span>
            <span class="ws__crumb-title">{{ run.title || '未命名作品' }}</span>
          </div>
        </div>

        <button
          type="button"
          class="btn btn--ghost ws__export"
          :disabled="exportBusy"
          :title="exportBusy ? '正在打包交付物…' : '下载正文、章纲、设定、体检与 AIGC 声明'"
          @click="downloadBundle"
        >
          {{ exportBusy ? '打包中…' : '下载整本交付包' }}
        </button>
      </header>
      <p v-if="downloadError" class="ws__export-error" role="alert">{{ downloadError }}</p>

      <nav class="ws__tabs" role="tablist" aria-label="工作台分区" @keydown="onTabKeydown">
        <button
          v-for="tab in WORKSPACE_TABS"
          :id="`ws-tab-${tab.id}`"
          :key="tab.id"
          :ref="(el) => setTabRef(tab.id, el)"
          type="button"
          role="tab"
          class="ws__tab"
          :class="{ 'is-active': activeTab === tab.id }"
          :aria-selected="activeTab === tab.id"
          :tabindex="activeTab === tab.id ? 0 : -1"
          @click="switchTab(tab.id)"
        >
          {{ tab.label }}
        </button>
        <button
          type="button"
          class="ws__tab-delete"
          :disabled="deleteBusy || !canDelete"
          :title="canDelete ? '删除作品' : '运行中的作品不能删除，请先停止'"
          aria-label="删除作品"
          @click="openDeleteDialog"
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path d="M3 6h18" />
            <path d="M8 6V4h8v2" />
            <path d="M6 6l1 15h10l1-15" />
            <path d="M10 11v6" />
            <path d="M14 11v6" />
          </svg>
        </button>
      </nav>

      <div class="ws__layout">
        <section
          class="card panel panel--full"
          :class="{ 'panel--compact': activeTab === 'info' }"
          aria-label="任务内容"
        >
          <div v-if="showGenerating" class="ws__generating" role="status">
            <div class="ws__skeleton" aria-hidden="true">
              <span /><span /><span />
            </div>
            <p class="ws__generating-text">正在生成…</p>
          </div>
          <div v-else class="panel__body panel__body--tab">
            <InfoTab v-if="activeTab === 'info'" :run="run" @updated="loadRun(true)" />
            <OutlineTab v-else-if="activeTab === 'outline'" :run="run" @updated="loadRun(true)" />
            <CharactersTab v-else-if="activeTab === 'characters'" :run="run" @updated="loadRun(true)" />
            <FactionsTab v-else-if="activeTab === 'factions'" :run="run" @updated="loadRun(true)" />
            <ItemsTab v-else-if="activeTab === 'items'" :run="run" @updated="loadRun(true)" />
            <SummariesTab
              v-else-if="activeTab === 'summaries'"
              :run="run"
              @jump="jumpToChapter"
              @updated="loadRun(true)"
            />
            <BodyTab v-else :run="run" :chapter="selectedChapter" @select="selectChapter" />
          </div>
        </section>

        <TaskCenter :current-id="run.run_id" :status="run.status" />
      </div>

      <AppDialog :open="deleteOpen" title="删除作品" @close="deleteOpen = false">
        <p class="ws__dialog-text">
          删除后无法恢复，作品正文、大纲、角色、封面等数据都会被清除。确定删除《{{
            run.title || '未命名作品'
          }}》吗？
        </p>
        <div v-if="deleteError" class="alert" role="alert">{{ deleteError }}</div>
        <template #footer>
          <button type="button" class="btn" :disabled="deleteBusy" @click="deleteOpen = false">
            取消
          </button>
          <button type="button" class="btn btn--danger" :disabled="deleteBusy" @click="confirmDeleteRun">
            {{ deleteBusy ? '删除中…' : '确认删除' }}
          </button>
        </template>
      </AppDialog>

    </template>
  </main>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import AppDialog from '@/components/AppDialog.vue'
import BodyTab from '@/components/workspace/BodyTab.vue'
import CharactersTab from '@/components/workspace/CharactersTab.vue'
import FactionsTab from '@/components/workspace/FactionsTab.vue'
import InfoTab from '@/components/workspace/InfoTab.vue'
import ItemsTab from '@/components/workspace/ItemsTab.vue'
import OutlineTab from '@/components/workspace/OutlineTab.vue'
import SummariesTab from '@/components/workspace/SummariesTab.vue'
import TaskCenter from '@/components/workspace/TaskCenter.vue'
import type { RunDetail, RunStatus } from '@/types'
import { deleteRun, downloadExportBundle, getRun } from '@/services/agentApi'
import { ApiError } from '@/services/http'
import { saveFile } from '@/utils/download'

const props = defineProps<{ id: string }>()

const run = ref<RunDetail | null>(null)
const loading = ref(false)
const loadError = ref('')
type WorkspaceTab =
  | 'info'
  | 'outline'
  | 'characters'
  | 'factions'
  | 'items'
  | 'summaries'
  | 'body'

const WORKSPACE_TABS: Array<{ id: WorkspaceTab; label: string }> = [
  { id: 'info', label: '作品信息' },
  { id: 'outline', label: '作品大纲' },
  { id: 'characters', label: '人物角色' },
  { id: 'factions', label: '势力阵营' },
  { id: 'items', label: '道具功法' },
  { id: 'summaries', label: '卷章概览' },
  { id: 'body', label: '作品正文' },
]
const route = useRoute()
const router = useRouter()
const activeTab = ref<WorkspaceTab>('info')
const selectedChapter = ref(1)
const tabRefs: Partial<Record<WorkspaceTab, HTMLButtonElement>> = {}

const deleteOpen = ref(false)
const deleteBusy = ref(false)
const deleteError = ref('')

const exportBusy = ref(false)
const downloadError = ref('')

let pollTimer: number | null = null

const TERMINAL: RunStatus[] = ['succeeded', 'failed', 'canceled']

/** 运行中且当前 Tab 还没有数据时，用「正在生成…」骨架替代空白 */
const isRunning = computed(
  () => run.value?.status === 'running' || run.value?.status === 'queued',
)
/** 运行中的作品禁止删除，避免与 worker 抢写 */
const canDelete = computed(
  () => !!run.value && run.value.status !== 'running' && run.value.status !== 'queued',
)

function tabHasData(tab: WorkspaceTab): boolean {
  const detail = run.value
  if (!detail) return false
  if (tab === 'info') return true
  if (tab === 'outline') return !!detail.outline || !!detail.chapters?.length
  if (tab === 'characters') return !!detail.characters?.length
  if (tab === 'factions') return !!detail.factions?.length
  if (tab === 'items') return !!detail.items?.length
  if (tab === 'summaries') return !!detail.chapters?.length
  return !!detail.chapters?.some((chapter) => chapter.content)
}

const showGenerating = computed(() => isRunning.value && !tabHasData(activeTab.value))

function errorText(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.status === 0) return '无法连接服务端，请检查网络后重试'
    if (err.status === 404) return '任务或资源不存在，可能已被清理'
    if (err.status === 409) return err.message || '任务当前状态不允许该操作'
    return err.message || fallback
  }
  return fallback
}

async function downloadBundle(): Promise<void> {
  if (exportBusy.value) return
  exportBusy.value = true
  downloadError.value = ''
  try {
    const file = await downloadExportBundle(props.id, run.value?.title)
    saveFile(file)
  } catch (err) {
    downloadError.value = errorText(err, '交付包下载失败，请稍后重试')
  } finally {
    exportBusy.value = false
  }
}

async function retryLoad(): Promise<void> {
  await loadRun()
  if (loadError.value) return
  startPolling()
}

async function loadRun(silent = false): Promise<void> {
  if (!silent) loading.value = true
  try {
    const detail = await getRun(props.id)
    run.value = detail
    loadError.value = ''
  } catch (err) {
    const message = errorText(err, '任务加载失败，请稍后重试')
    if (!run.value) loadError.value = message
  } finally {
    if (!silent) loading.value = false
  }
}

function startPolling(): void {
  stopPolling()
  pollTimer = window.setInterval(() => {
    if (!run.value) return
    // 热门写作即使异常返回 paused 也继续轮询，等待服务端自动完成
    const blocked = run.value.status === 'paused' && run.value.mode !== 'hot'
    if (TERMINAL.includes(run.value.status) || blocked) return
    void loadRun(true)
  }, 1800)
}

function stopPolling(): void {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

function openDeleteDialog(): void {
  if (!canDelete.value) return
  deleteError.value = ''
  deleteOpen.value = true
}

async function confirmDeleteRun(): Promise<void> {
  if (!run.value || deleteBusy.value) return
  deleteBusy.value = true
  deleteError.value = ''
  try {
    await deleteRun(run.value.run_id)
    deleteOpen.value = false
    stopPolling()
    await router.push('/runs')
  } catch (err) {
    deleteError.value = errorText(err, '删除作品失败，请稍后重试')
  } finally {
    deleteBusy.value = false
  }
}

function readWorkspaceQuery(): void {
  const tab = route.query.tab
  if (typeof tab === 'string' && WORKSPACE_TABS.some((item) => item.id === tab)) {
    activeTab.value = tab as WorkspaceTab
  }
  const chapter = Number(route.query.chapter)
  if (Number.isFinite(chapter) && chapter > 0) selectedChapter.value = chapter
}

function setTabRef(id: WorkspaceTab, el: unknown): void {
  if (el instanceof HTMLButtonElement) tabRefs[id] = el
}

function switchTab(tab: WorkspaceTab): void {
  if (activeTab.value === tab) return
  activeTab.value = tab
  void syncQuery()
}

function onTabKeydown(event: KeyboardEvent): void {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
  event.preventDefault()
  const index = WORKSPACE_TABS.findIndex((item) => item.id === activeTab.value)
  const delta = event.key === 'ArrowRight' ? 1 : -1
  const next = WORKSPACE_TABS[(index + delta + WORKSPACE_TABS.length) % WORKSPACE_TABS.length]
  switchTab(next.id)
  tabRefs[next.id]?.focus()
}

async function syncQuery(): Promise<void> {
  const next: Record<string, string> = {}
  for (const [key, value] of Object.entries(route.query)) {
    if (key !== 'tab' && key !== 'chapter' && typeof value === 'string') next[key] = value
  }
  next.tab = activeTab.value
  if (activeTab.value === 'body') next.chapter = String(selectedChapter.value)
  const changed =
    route.query.tab !== next.tab || String(route.query.chapter ?? '') !== (next.chapter ?? '')
  if (changed) await router.replace({ query: next })
}

function selectChapter(no: number): void {
  selectedChapter.value = no
  if (activeTab.value !== 'body') activeTab.value = 'body'
  void syncQuery()
}

function jumpToChapter(no: number): void {
  selectChapter(no)
}

onMounted(async () => {
  readWorkspaceQuery()
  await loadRun()
  const chapters = run.value?.chapters
  if (chapters?.length && !chapters.some((chapter) => chapter.no === selectedChapter.value)) {
    selectedChapter.value = chapters[0].no
  }
  if (!loadError.value) startPolling()
})

/** 任务中心切换任务时复用同一路由组件，需要手动重新拉取详情 */
watch(
  () => props.id,
  async () => {
    stopPolling()
    readWorkspaceQuery()
    selectedChapter.value = 1
    await loadRun()
    if (!loadError.value) startPolling()
  },
)

watch(
  () => run.value?.status,
  (status) => {
    if (!status) return
    // hot 之外 paused 不会自行恢复，停止轮询；恢复后由 startPolling 重新启动。
    if (TERMINAL.includes(status) || (status === 'paused' && run.value?.mode !== 'hot')) stopPolling()
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  stopPolling()
})
</script>

<style scoped>
.ws__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  margin-bottom: var(--space-4);
}

.ws__head-main {
  min-width: 0;
}

.ws__export {
  flex: none;
}

.ws__export-error {
  margin: -8px 0 var(--space-3);
  color: var(--color-danger, #f87171);
  font-size: var(--text-xs);
}

.ws__crumb {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--text-xs);
  color: var(--color-text-3);
}

.ws__crumb a:hover {
  color: var(--color-brand);
}

.ws__crumb-title {
  max-width: 60vw;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--color-text-2);
  font-weight: 600;
}

/* ---------- 内容 + 任务中心 ---------- */
/* 工作台整体占满视口内容区：头部/标签固定，滚动发生在左侧内容卡内部 */
.ws {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding-top: var(--space-6);
  padding-bottom: var(--space-4);
}

.ws__head {
  flex: none;
}

.ws__tabs {
  flex: none;
}

.ws__layout {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 260px;
  grid-template-rows: minmax(0, 1fr);
  gap: var(--space-4);
}

/* ---------- 内容区 ---------- */
/* 左侧内容卡撑满可视区，滚动条出现在卡片内部 */
.panel--full {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 作品信息内容较短，去掉固定最小高度，避免说明文字删除后留下大片空白 */
.panel--compact .panel__body--tab {
  min-height: 0;
}

.ws__generating {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: var(--space-6) var(--space-5);
  flex: 1;
  min-height: 0;
}

.ws__skeleton {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.ws__skeleton span {
  display: block;
  height: 14px;
  border-radius: var(--radius-sm);
  background: linear-gradient(90deg, var(--color-bg-soft), var(--color-bg-softer), var(--color-bg-soft));
  background-size: 200% 100%;
  animation: ws-skeleton 1.4s ease-in-out infinite;
}

.ws__skeleton span:nth-child(1) {
  width: 62%;
}

.ws__skeleton span:nth-child(2) {
  width: 84%;
}

.ws__skeleton span:nth-child(3) {
  width: 48%;
}

@keyframes ws-skeleton {
  0% {
    background-position: 100% 0;
  }
  100% {
    background-position: -100% 0;
  }
}

.ws__generating-text {
  font-size: var(--text-sm);
  color: var(--color-text-3);
}

.ws__tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: var(--space-4);
  padding: 6px;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-md);
  background: var(--color-bg-softer);
  overflow-x: auto;
  scrollbar-width: thin;
}

.ws__tab {
  flex: none;
  height: 32px;
  padding: 0 14px;
  border-radius: var(--radius-sm);
  border: 1px solid transparent;
  background: transparent;
  color: var(--color-text-2);
  font-size: 14px;
  font-weight: 500;
  white-space: nowrap;
  transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
}

.ws__tab:hover {
  background: var(--color-bg-soft);
  color: var(--color-text);
}

.ws__tab.is-active {
  background: var(--color-bg);
  border-color: var(--color-line-strong);
  color: var(--color-brand);
  font-weight: 600;
  box-shadow: var(--shadow-sm);
}

.ws__tab:focus-visible {
  outline: 2px solid var(--color-brand);
  outline-offset: 1px;
}

.ws__tab-delete {
  flex: none;
  margin-left: auto;
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border-radius: var(--radius-sm);
  color: var(--color-text-3);
  transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
}

.ws__tab-delete:hover:not(:disabled) {
  background: var(--color-danger-soft);
  color: var(--color-danger);
}

.ws__tab-delete:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.ws__tab-delete svg {
  width: 16px;
  height: 16px;
}

/* 双类选择器：覆盖 .panel__body 的 min-height，保证在各标签页都能内部滚动 */
.panel__body.panel__body--tab {
  padding: 0;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-width: thin;
}

.panel__body.panel__body--tab::-webkit-scrollbar {
  width: 8px;
}

.panel__body.panel__body--tab::-webkit-scrollbar-thumb {
  background: #d7dde5;
  border-radius: 8px;
}

/* ---------- 内容面板 ---------- */
.panel__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--color-line);
}

.panel__tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.panel__tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 12px;
  border-radius: var(--radius-pill);
  font-size: var(--text-sm);
  color: var(--color-text-2);
}

.panel__tab:hover {
  background: var(--color-bg-soft);
}

.panel__tab.is-active {
  background: #eef7f6;
  color: var(--color-brand);
  font-weight: 600;
}

.panel__count {
  font-size: 14px;
  color: var(--color-text-3);
  font-family: var(--font-mono);
}

.panel__tab.is-active .panel__count {
  color: var(--color-brand);
}

.panel__updated {
  font-size: 14px;
  color: var(--color-text-3);
}

.panel__body {
  padding: var(--space-5);
  min-height: 420px;
}

.chapters {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.chapter {
  border: 1px solid var(--color-line);
  border-radius: var(--radius-md);
  padding: 14px 16px;
  background: var(--color-bg-softer);
}

.chapter__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.chapter__title {
  font-size: var(--text-md);
  font-weight: 700;
}

.chapter__summary {
  margin-top: 4px;
  font-size: var(--text-xs);
  color: var(--color-text-2);
  line-height: 1.7;
}

.chapter__words {
  flex: none;
  font-size: 14px;
  color: var(--color-text-3);
  font-family: var(--font-mono);
}

.chapter__content {
  margin-top: 12px;
  padding: 12px 14px;
  border-radius: var(--radius-sm);
  background: #fff;
  border: 1px solid var(--color-line);
  font-size: var(--text-sm);
  line-height: 1.9;
  white-space: pre-wrap;
  color: var(--color-text-2);
  max-height: 420px;
  overflow: auto;
}

.chapter__actions {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}

.cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}

.mini-card {
  border: 1px solid var(--color-line);
  border-radius: var(--radius-md);
  padding: 14px 16px;
}

.mini-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.mini-card__title {
  font-size: var(--text-sm);
  font-weight: 600;
}

.mini-card__meta {
  margin-top: 4px;
  font-size: 14px;
  color: var(--color-text-3);
}

.mini-card__text {
  margin-top: 8px;
  font-size: var(--text-xs);
  color: var(--color-text-2);
  line-height: 1.7;
}

.outline {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.preview {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.preview__source {
  font-size: var(--text-xs);
  color: var(--color-text-3);
}

.preview__body {
  margin: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-size: var(--text-sm);
  line-height: 1.8;
  color: var(--color-text-2);
}

.outline__label {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--color-text-3);
  letter-spacing: 0.06em;
  margin-bottom: 8px;
}

.outline__logline {
  font-size: var(--text-sm);
  line-height: 1.8;
  color: var(--color-text-2);
}

.outline__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.outline__beats {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.outline__beats li {
  display: flex;
  align-items: baseline;
  gap: 10px;
  font-size: var(--text-sm);
  color: var(--color-text-2);
}

.outline__beat-no {
  font-family: var(--font-mono);
  font-size: 14px;
  color: var(--color-brand);
}

.ws__empty-btn {
  margin-top: var(--space-3);
}

.ws__dialog-text {
  font-size: var(--text-sm);
  color: var(--color-text-2);
  line-height: 1.7;
}

.ws__error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-6);
  padding: var(--space-6);
}

.ws__error-title {
  font-size: var(--text-md);
  font-weight: 700;
}

.ws__error-text {
  margin-top: 4px;
  color: var(--color-text-2);
  font-size: var(--text-sm);
}

.ws__error-actions {
  display: flex;
  gap: 8px;
}

@media (max-width: 980px) {
  /* 窄屏任务中心换到下方：改为纵向流，内容按自身高度铺开，交给外层容器滚动 */
  .ws__layout {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    flex: none;
    overflow: visible;
  }

  .panel--full {
    min-height: 0;
    overflow: visible;
  }

  .panel__body.panel__body--tab {
    flex: none;
    overflow: visible;
  }
}

@media (max-width: 860px) {
  .ws__tabs {
    margin-left: calc(-1 * var(--space-2));
    margin-right: calc(-1 * var(--space-2));
  }

  .ws__head {
    align-items: flex-start;
  }

  .ws__crumb-title {
    max-width: 52vw;
  }

  .ws__generating {
    min-height: 320px;
  }

  .panel__body {
    min-height: 320px;
  }

  .ws__error {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
