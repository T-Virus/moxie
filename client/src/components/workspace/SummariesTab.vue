<template>
  <div class="summaries">
    <section class="summaries__panel" aria-label="筛选与分页">
      <div class="summaries__toolbar">
        <input
          v-model="keyword"
          class="summaries__search"
          type="search"
          placeholder="搜索章节名称 / 概括"
          aria-label="搜索章节名称、概括、冲突或钩子"
          @input="page = 1"
        />
        <button
          type="button"
          class="btn btn--sm btn--brand summaries__add"
          :disabled="!canEdit"
          :title="canEdit ? '新增卷' : '运行中的作品暂不可编辑'"
          @click="openCreateVolume"
        >
          + 新增卷
        </button>
        <button
          type="button"
          class="btn btn--sm btn--brand summaries__add"
          :disabled="!canEdit"
          :title="canEdit ? '新增章节概览' : '运行中的作品暂不可编辑'"
          @click="openCreateChapter"
        >
          + 新增章节
        </button>
        <div class="summaries__meta">
          <span class="summaries__count">共 <b>{{ filtered.length }}</b> 章</span>
          <div class="summaries__pager">
            <button
              type="button"
              class="summaries__page-btn"
              :disabled="page <= 1"
              aria-label="上一页"
              @click="page -= 1"
            >
              ‹
            </button>
            <span class="summaries__page-info">{{ page }} / {{ pageCount }}</span>
            <button
              type="button"
              class="summaries__page-btn"
              :disabled="page >= pageCount"
              aria-label="下一页"
              @click="page += 1"
            >
              ›
            </button>
          </div>
        </div>
      </div>

      <div v-if="volumes.length" class="summaries__row">
        <span class="summaries__row-label">卷</span>
        <div class="summaries__chips" role="group" aria-label="按卷筛选">
          <button
            v-for="volume in volumes"
            :key="volume.key"
            type="button"
            class="summaries__chip"
            :class="{ 'is-active': selectedKey === volume.key }"
            @click="pickVolume(volume.key)"
          >
            {{ volume.title }}
            <span class="summaries__chip-count">{{ volume.chapters.length }} 章</span>
          </button>
        </div>
      </div>
    </section>

    <section v-if="currentVolume" class="vol-card" aria-label="卷概括信息">
      <div class="vol-card__head">
        <h3 class="vol-card__title">{{ currentVolume.title }}</h3>
        <span v-if="rangeText" class="vol-card__range">{{ rangeText }}</span>
        <div class="vol-card__stats">
          <span>章节 <b>{{ currentVolume.chapters.length }}</b> 章</span>
          <span v-if="volumeWordsText">合计 <b>{{ volumeWordsText }}</b></span>
        </div>
        <div v-if="currentVolume.key !== 'unassigned'" class="summaries__acts">
          <button
            type="button"
            class="summaries__act"
            :disabled="!canEdit"
            :title="canEdit ? '编辑当前卷' : '运行中的作品暂不可编辑'"
            aria-label="编辑当前卷"
            @click="openEditVolume"
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
              <path d="M12 20h9" />
              <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
            </svg>
          </button>
          <button
            type="button"
            class="summaries__act summaries__act--danger"
            :disabled="!canEdit"
            :title="canEdit ? '删除当前卷' : '运行中的作品暂不可编辑'"
            aria-label="删除当前卷"
            @click="openDeleteVolume"
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
        </div>
      </div>
      <div v-if="currentVolume.summary || currentVolume.conflict" class="vol-card__grid">
        <div v-if="currentVolume.summary" class="vol-card__block">
          <span class="vol-card__label">卷概括</span>
          <p class="vol-card__text">{{ currentVolume.summary }}</p>
        </div>
        <div v-if="currentVolume.conflict" class="vol-card__block">
          <span class="vol-card__label">冲突主线</span>
          <p class="vol-card__text">{{ currentVolume.conflict }}</p>
        </div>
      </div>
      <!-- 卷规划字段：只渲染服务端实际下发的字段 -->
      <div v-if="volumeExtraFields.length" class="vol-card__grid vol-card__grid--extra">
        <div v-for="item in volumeExtraFields" :key="item.label" class="vol-card__block">
          <span class="vol-card__label">{{ item.label }}</span>
          <p class="vol-card__text">{{ item.value }}</p>
        </div>
      </div>
    </section>

    <div v-if="!currentVolume?.chapters.length" class="summaries__empty">
      <p class="empty__title">本卷暂无章节概括</p>
      <p>章节概括服务端正在补齐，正文生成后可在此查看每章概览、核心冲突与章末钩子。</p>
    </div>

    <div v-else-if="!filtered.length" class="summaries__empty">
      <p class="empty__title">没有匹配的章节</p>
      <p>试试其他关键词，或清空搜索。</p>
      <button type="button" class="btn btn--sm summaries__reset" @click="keyword = ''">
        清空搜索
      </button>
    </div>

    <div v-else class="summaries__list">
      <article
        v-for="chapter in paged"
        :key="chapter.no"
        class="chapter-card is-clickable"
        role="button"
        tabindex="0"
        :title="`查看第 ${chapter.no} 章详细字段`"
        @click="openDetail(chapter)"
        @keydown.enter="openDetail(chapter)"
        @keydown.space.prevent="openDetail(chapter)"
      >
        <div class="summaries__acts chapter-card__acts">
          <button
            type="button"
            class="summaries__act"
            :disabled="!canEdit"
            :title="canEdit ? '编辑章节概览' : '运行中的作品暂不可编辑'"
            aria-label="编辑章节概览"
            @click.stop="openEditChapter(chapter)"
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
              <path d="M12 20h9" />
              <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
            </svg>
          </button>
          <button
            type="button"
            class="summaries__act summaries__act--danger"
            :disabled="!canEdit"
            :title="canEdit ? '删除章节概览' : '运行中的作品暂不可编辑'"
            aria-label="删除章节概览"
            @click.stop="openDeleteChapter(chapter)"
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
        </div>
        <header class="chapter-card__head">
          <span class="chapter-card__no">第 {{ chapter.no }} 章</span>
          <h3 class="chapter-card__title">{{ chapter.title || '未命名章节' }}</h3>
          <span v-if="wordsText(chapter)" class="chapter-card__words">{{ wordsText(chapter) }}</span>
        </header>

        <div v-if="chapter.summary" class="chapter-card__section">
          <span class="chapter-card__label">概括</span>
          <p class="chapter-card__text">{{ chapter.summary }}</p>
        </div>
      </article>
    </div>

    <Teleport to="body">
      <div
        v-if="detailChapter"
        class="detail-drawer"
        role="dialog"
        aria-modal="true"
        :aria-label="`第 ${detailChapter.no} 章详细字段`"
      >
        <div class="detail-drawer__mask" @click="closeDetail" />
        <aside class="detail-drawer__panel">
          <header class="detail-drawer__head">
            <div class="detail-drawer__head-main">
              <span class="detail-drawer__no">第 {{ detailChapter.no }} 章</span>
              <h2 class="detail-drawer__title">{{ detailChapter.title || '未命名章节' }}</h2>
              <p class="detail-drawer__sub">
                <span v-if="wordsText(detailChapter)">{{ wordsText(detailChapter) }}</span>
                <span v-if="detailChapter.scene">{{ detailChapter.scene }}</span>
                <span v-if="detailChapter.emotion">{{ detailChapter.emotion }}</span>
                <span v-if="tensionText(detailChapter.tension)">张力 {{ tensionText(detailChapter.tension) }}</span>
              </p>
            </div>
            <button type="button" class="detail-drawer__close" aria-label="关闭" @click="closeDetail">×</button>
          </header>

          <div class="detail-drawer__body">
            <section
              v-for="group in detailGroups"
              :key="group.title"
              class="detail-drawer__section"
            >
              <h3 class="detail-drawer__section-title">{{ group.title }}</h3>
              <div v-for="row in group.rows" :key="row.label" class="detail-drawer__row">
                <span class="detail-drawer__label">{{ row.label }}</span>
                <span class="detail-drawer__value">{{ row.value }}</span>
              </div>
            </section>
          </div>

          <footer class="detail-drawer__foot">
            <button type="button" class="btn btn--ghost btn--sm" @click="closeDetail">关闭</button>
            <button type="button" class="btn btn--brand btn--sm" @click="readInBody(detailChapter.no)">
              去正文阅读
            </button>
          </footer>
        </aside>
      </div>
    </Teleport>

    <CollectionDialog
      :open="volumeDialogOpen"
      :title="volumeDialogTitle"
      :fields="VOLUME_FIELDS"
      :value="volumeValue"
      :saving="volumeSaving"
      :error="volumeError"
      @close="volumeDialogOpen = false"
      @save="saveVolume"
    />

    <CollectionDialog
      :open="chapterDialogOpen"
      :title="chapterDialogTitle"
      :fields="chapterFields"
      :value="chapterValue"
      :saving="chapterSaving"
      :error="chapterError"
      @close="chapterDialogOpen = false"
      @save="saveChapter"
    />

    <AppDialog :open="deleteVolumeOpen" title="删除卷" @close="deleteVolumeOpen = false">
      <p class="summaries__dialog-text">
        删除后该卷将从卷章概览中移除，卷内章节仍保留在正文与章节列表中。确定删除「{{
          deleteVolumeTarget?.title
        }}」吗？
      </p>
      <div v-if="volumeDeleteError" class="alert" role="alert">{{ volumeDeleteError }}</div>
      <template #footer>
        <button type="button" class="btn" :disabled="volumeDeleting" @click="deleteVolumeOpen = false">
          取消
        </button>
        <button type="button" class="btn btn--danger" :disabled="volumeDeleting" @click="confirmDeleteVolume">
          {{ volumeDeleting ? '删除中…' : '确认删除' }}
        </button>
      </template>
    </AppDialog>

    <AppDialog :open="deleteChapterOpen" title="删除章节概览" @close="deleteChapterOpen = false">
      <p class="summaries__dialog-text">
        删除后只移除本章的概览记录，不会删除正文。确定删除第
        {{ deleteChapterTarget?.no }} 章「{{ deleteChapterTarget?.title }}」吗？
      </p>
      <div v-if="chapterDeleteError" class="alert" role="alert">{{ chapterDeleteError }}</div>
      <template #footer>
        <button type="button" class="btn" :disabled="chapterDeleting" @click="deleteChapterOpen = false">
          取消
        </button>
        <button type="button" class="btn btn--danger" :disabled="chapterDeleting" @click="confirmDeleteChapter">
          {{ chapterDeleting ? '删除中…' : '确认删除' }}
        </button>
      </template>
    </AppDialog>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import AppDialog from '@/components/AppDialog.vue'
import CollectionDialog from '@/components/CollectionDialog.vue'
import type {
  ChapterContent,
  ChapterSummary,
  CollectionField,
  OutlineChapter,
  RunDetail,
  VolumeContent,
} from '@/types'
import { updateRunCollections } from '@/services/agentApi'
import { ApiError } from '@/services/http'

const props = defineProps<{ run: RunDetail }>()
const emit = defineEmits<{
  (event: 'jump', chapter: number): void
  (event: 'updated'): void
}>()

const VOLUME_FIELDS: CollectionField[] = [
  { key: 'no', label: '卷序号', type: 'number', required: true, min: 1 },
  { key: 'title', label: '卷标题', placeholder: '如 第一卷 山雨欲来' },
  { key: 'chapter_from', label: '起始章号', type: 'number', min: 1 },
  { key: 'chapter_to', label: '结束章号', type: 'number', min: 1 },
  { key: 'summary', label: '卷概括', type: 'textarea', rows: 3 },
  { key: 'conflict', label: '冲突主线', type: 'textarea', rows: 2 },
  { key: 'theme', label: '卷主题', placeholder: '本卷核心主题' },
  { key: 'core_event', label: '卷核心事件', placeholder: '本卷最重要的转折' },
  { key: 'conflict_axis', label: '卷矛盾轴', placeholder: '贯穿本卷的矛盾' },
  { key: 'end_hook', label: '卷末钩子', placeholder: '卷末留下的悬念' },
  { key: 'arc', label: '卷内人物弧光', type: 'textarea', rows: 2 },
  { key: 'tension_profile', label: '卷节奏曲线', placeholder: '如 慢热 → 高潮 → 收束' },
]

const CHAPTER_FIELDS: CollectionField[] = [
  { key: 'no', label: '章号', type: 'number', required: true, min: 1 },
  { key: 'title', label: '章节标题', required: true, placeholder: '章节名称' },
  { key: 'words', label: '字数', type: 'number', min: 0 },
  { key: 'summary', label: '章节概括', type: 'textarea', rows: 3 },
  { key: 'conflict', label: '核心冲突', type: 'textarea', rows: 2 },
  { key: 'hook', label: '章末钩子', type: 'textarea', rows: 2 },
  { key: 'scene', label: '场景', placeholder: '本章主要场景' },
  { key: 'hook_type', label: '钩子类型', placeholder: '如 悬念 / 反转 / 危机' },
  { key: 'emotion', label: '情绪主线', placeholder: '如 压抑 → 爆发' },
  { key: 'tension', label: '张力值（0-10）', type: 'number', min: 0 },
  { key: 'chapter_status', label: '章节状态', placeholder: '如 已生成 / 待修订' },
  { key: 'key_events', label: '关键事件', type: 'tags' },
  { key: 'roles', label: '出场角色', type: 'tags' },
  { key: 'factions', label: '涉及势力', type: 'tags' },
  { key: 'items', label: '涉及道具', type: 'tags' },
]

const canEdit = computed(
  () => props.run.status !== 'running' && props.run.status !== 'queued',
)

const characterOptions = computed(() =>
  (props.run.characters || []).map((item) => item.name).filter(Boolean),
)
const factionOptions = computed(() =>
  (props.run.factions || []).map((item) => item.name).filter(Boolean),
)
const itemOptions = computed(() =>
  (props.run.items || []).map((item) => item.name).filter(Boolean),
)

/** 章节里的角色/势力/道具从已有资料中选择，减少手输不一致 */
const chapterFields = computed<CollectionField[]>(() =>
  CHAPTER_FIELDS.map((field) => {
    if (field.key === 'roles') return { ...field, presets: characterOptions.value }
    if (field.key === 'factions') return { ...field, presets: factionOptions.value }
    if (field.key === 'items') return { ...field, presets: itemOptions.value }
    return field
  }),
)

const volumeDialogOpen = ref(false)
const volumeEditingNo = ref(-1)
const volumeValue = ref<Record<string, any>>({})
const volumeError = ref('')
const volumeSaving = ref(false)
const deleteVolumeOpen = ref(false)
const deleteVolumeTarget = ref<VolumeView | null>(null)
const volumeDeleting = ref(false)
const volumeDeleteError = ref('')

const chapterDialogOpen = ref(false)
const chapterEditingNo = ref(-1)
const chapterValue = ref<Record<string, any>>({})
const chapterError = ref('')
const chapterSaving = ref(false)
const deleteChapterOpen = ref(false)
const deleteChapterTarget = ref<ChapterSummary | null>(null)
const chapterDeleting = ref(false)
const chapterDeleteError = ref('')

const volumeDialogTitle = computed(() =>
  volumeEditingNo.value > 0 ? '编辑卷' : '新增卷',
)
const chapterDialogTitle = computed(() =>
  chapterEditingNo.value > 0 ? '编辑章节概览' : '新增章节概览',
)

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function blankValue(fields: CollectionField[]): Record<string, any> {
  const blank: Record<string, any> = {}
  for (const field of fields) {
    blank[field.key] = field.type === 'tags' ? [] : field.type === 'number' ? undefined : ''
  }
  return blank
}

/** 卷写入时不携带 chapters，靠章号区间关联，避免把整本章节复制进 meta */
function volumesPayload(list: VolumeContent[]): VolumeContent[] {
  return list.map((volume) => {
    const copy = clone(volume) as Record<string, any>
    delete copy.chapters
    return copy as unknown as VolumeContent
  })
}

function openCreateVolume(): void {
  if (!canEdit.value) return
  const nextNo =
    Math.max(0, ...volumes.value.map((volume) => Number(volume.key) || 0)) + 1
  volumeEditingNo.value = -1
  volumeValue.value = { ...blankValue(VOLUME_FIELDS), no: nextNo }
  volumeError.value = ''
  volumeDialogOpen.value = true
}

function openEditVolume(): void {
  const volume = currentVolume.value
  if (!canEdit.value || !volume) return
  volumeEditingNo.value = Number(volume.key) || volume.from || 1
  volumeValue.value = {
    ...blankValue(VOLUME_FIELDS),
    no: volumeEditingNo.value,
    title: volume.title,
    chapter_from: volume.from ?? undefined,
    chapter_to: volume.to ?? undefined,
    summary: volume.summary,
    conflict: volume.conflict,
    theme: volume.theme,
    core_event: volume.coreEvent,
    conflict_axis: volume.conflictAxis,
    end_hook: volume.endHook,
    arc: volume.arc,
    tension_profile: volume.tensionProfile,
  }
  volumeError.value = ''
  volumeDialogOpen.value = true
}

async function saveVolume(values: Record<string, any>): Promise<void> {
  if (!canEdit.value) return
  const no = Number(values.no)
  const duplicated = volumes.value.some(
    (volume) => Number(volume.key) === no && no !== volumeEditingNo.value,
  )
  if (duplicated) {
    volumeError.value = '卷序号已存在，请换一个序号'
    return
  }
  if (
    typeof values.chapter_from === 'number' &&
    typeof values.chapter_to === 'number' &&
    values.chapter_from > values.chapter_to
  ) {
    volumeError.value = '起始章号不能大于结束章号'
    return
  }
  volumeSaving.value = true
  volumeError.value = ''
  try {
    const raw = (props.run.volumes || []).map((volume) => clone(volume)) as VolumeContent[]
    const next: VolumeContent = {
      no,
      title: String(values.title || '').trim() || undefined,
      summary: String(values.summary || '').trim() || undefined,
      conflict: String(values.conflict || '').trim() || undefined,
      chapter_from: typeof values.chapter_from === 'number' ? values.chapter_from : undefined,
      chapter_to: typeof values.chapter_to === 'number' ? values.chapter_to : undefined,
      theme: String(values.theme || '').trim() || undefined,
      core_event: String(values.core_event || '').trim() || undefined,
      conflict_axis: String(values.conflict_axis || '').trim() || undefined,
      end_hook: String(values.end_hook || '').trim() || undefined,
      arc: String(values.arc || '').trim() || undefined,
      tension_profile: String(values.tension_profile || '').trim() || undefined,
    }
    const index = raw.findIndex((volume) => volume.no === volumeEditingNo.value)
    let list: VolumeContent[]
    if (index >= 0) {
      list = raw.map((volume, i) => (i === index ? { ...volume, ...next } : volume))
    } else {
      list = [...raw, next]
    }
    list.sort((a, b) => (a.no || 0) - (b.no || 0))
    await updateRunCollections(props.run.run_id, { volumes: volumesPayload(list) })
    volumeDialogOpen.value = false
    emit('updated')
  } catch (err) {
    volumeError.value = err instanceof ApiError ? err.message : '保存失败，请稍后重试'
  } finally {
    volumeSaving.value = false
  }
}

function openDeleteVolume(): void {
  if (!canEdit.value || !currentVolume.value) return
  deleteVolumeTarget.value = currentVolume.value
  volumeDeleteError.value = ''
  deleteVolumeOpen.value = true
}

async function confirmDeleteVolume(): Promise<void> {
  const target = deleteVolumeTarget.value
  if (!target || volumeDeleting.value) return
  volumeDeleting.value = true
  volumeDeleteError.value = ''
  try {
    const no = Number(target.key)
    const list = (props.run.volumes || [])
      .filter((volume) => volume.no !== no)
      .map((volume) => clone(volume))
    await updateRunCollections(props.run.run_id, { volumes: volumesPayload(list) })
    deleteVolumeOpen.value = false
    deleteVolumeTarget.value = null
    emit('updated')
  } catch (err) {
    volumeDeleteError.value =
      err instanceof ApiError ? err.message : '删除失败，请稍后重试'
  } finally {
    volumeDeleting.value = false
  }
}

function openCreateChapter(): void {
  if (!canEdit.value) return
  const nextNo = Math.max(0, ...allChapters.value.map((chapter) => chapter.no)) + 1
  chapterEditingNo.value = -1
  chapterValue.value = { ...blankValue(CHAPTER_FIELDS), no: nextNo }
  chapterError.value = ''
  chapterDialogOpen.value = true
}

function openEditChapter(chapter: ChapterSummary): void {
  if (!canEdit.value) return
  chapterEditingNo.value = chapter.no
  chapterValue.value = {
    ...clone(chapter),
    key_events: [...(chapter.key_events || [])],
    roles: [...(chapter.roles || [])],
    factions: [...(chapter.factions || [])],
    items: [...(chapter.items || [])],
  }
  chapterError.value = ''
  chapterDialogOpen.value = true
}

async function saveChapter(values: Record<string, any>): Promise<void> {
  if (!canEdit.value) return
  const no = Number(values.no)
  const duplicated = allChapters.value.some(
    (chapter) => chapter.no === no && no !== chapterEditingNo.value,
  )
  if (duplicated) {
    chapterError.value = '章号已存在，请换一个章号'
    return
  }
  chapterSaving.value = true
  chapterError.value = ''
  try {
    const next = {
      ...values,
      no,
      title: String(values.title || '').trim() || `第 ${no} 章`,
    }
    // 按章号去重：避免连续保存或历史数据产生同一章的多条记录
    const chapterMap = new Map<number, ChapterSummary>()
    for (const chapter of props.run.chapter_summaries || []) {
      chapterMap.set(chapter.no, clone(chapter))
    }
    if (chapterEditingNo.value > 0) chapterMap.delete(chapterEditingNo.value)
    chapterMap.set(no, next as unknown as ChapterSummary)
    const list = [...chapterMap.values()].sort((a, b) => a.no - b.no)
    // 新增/改章号时同时解除隐藏，保证重新添加曾删除的章号能立即显示
    const hidden = (props.run.chapter_hidden || []).filter((item) => item !== no)
    await updateRunCollections(props.run.run_id, {
      chapter_summaries: list,
      chapter_hidden: hidden,
    })
    chapterDialogOpen.value = false
    selectedKey.value = volumeKeyForChapter(no)
    page.value = 1
    emit('updated')
  } catch (err) {
    chapterError.value = err instanceof ApiError ? err.message : '保存失败，请稍后重试'
  } finally {
    chapterSaving.value = false
  }
}

function openDeleteChapter(chapter: ChapterSummary): void {
  if (!canEdit.value) return
  deleteChapterTarget.value = chapter
  chapterDeleteError.value = ''
  deleteChapterOpen.value = true
}

async function confirmDeleteChapter(): Promise<void> {
  const target = deleteChapterTarget.value
  if (!target || chapterDeleting.value) return
  chapterDeleting.value = true
  chapterDeleteError.value = ''
  try {
    const list = (props.run.chapter_summaries || [])
      .filter((chapter) => chapter.no !== target.no)
      .map((chapter) => clone(chapter)) as Array<Record<string, any>>
    const hidden = new Set<number>(props.run.chapter_hidden || [])
    hidden.add(target.no)
    await updateRunCollections(props.run.run_id, {
      chapter_summaries: list as unknown as ChapterSummary[],
      chapter_hidden: [...hidden].sort((a, b) => a - b),
    })
    deleteChapterOpen.value = false
    deleteChapterTarget.value = null
    if (detailChapter.value?.no === target.no) detailChapter.value = null
    emit('updated')
  } catch (err) {
    chapterDeleteError.value =
      err instanceof ApiError ? err.message : '删除失败，请稍后重试'
  } finally {
    chapterDeleting.value = false
  }
}

const PAGE_SIZE = 6
const VOLUME_NUMBERS = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十']

const keyword = ref('')
const page = ref(1)
const selectedKey = ref('1')
const detailChapter = ref<ChapterSummary | null>(null)

function openDetail(chapter: ChapterSummary): void {
  detailChapter.value = chapter
}

function closeDetail(): void {
  detailChapter.value = null
}

function readInBody(no: number): void {
  detailChapter.value = null
  jump(no)
}

interface VolumeView {
  key: string
  title: string
  from: number | null
  to: number | null
  summary: string
  conflict: string
  theme: string
  coreEvent: string
  conflictAxis: string
  endHook: string
  arc: string
  tensionProfile: string
  chapters: ChapterSummary[]
}

// 以 chapter_summaries 为主，按章号合并 chapters 的扩展字段与 outline.chapters 的节拍/钩子，
// 保证「概括」不丢「场景/事件/角色」等离线字段。
const allChapters = computed<ChapterSummary[]>(() => {
  const contentMap = new Map<number, ChapterContent>()
  for (const chapter of props.run.chapters || []) contentMap.set(chapter.no, chapter)
  const outlineMap = new Map<number, OutlineChapter>()
  for (const chapter of props.run.outline?.chapters || []) {
    outlineMap.set(chapter.no, chapter)
  }
  const summaryMap = new Map<number, ChapterSummary>()
  for (const chapter of props.run.chapter_summaries || []) {
    summaryMap.set(chapter.no, chapter)
  }

  const nos = new Set<number>([
    ...summaryMap.keys(),
    ...contentMap.keys(),
    ...outlineMap.keys(),
  ])
  const hidden = new Set(props.run.chapter_hidden || [])
  return [...nos]
    .filter((no) => !hidden.has(no))
    .sort((a, b) => a - b)
    .map((no) => {
      const summary = summaryMap.get(no)
      const content = contentMap.get(no)
      const outline = outlineMap.get(no)
      const merged = {
        ...(content || {}),
        ...(summary || {}),
        no,
        title:
          summary?.title || content?.title || outline?.title || `第 ${no} 章`,
        summary: summary?.summary ?? content?.summary ?? outline?.summary,
        conflict: summary?.conflict ?? content?.conflict,
        hook: summary?.hook ?? content?.hook ?? outline?.hook,
        words: summary?.words ?? content?.words,
      } as ChapterSummary
      if (!merged.key_events?.length) merged.key_events = outline?.key_events
      if (!merged.arc) merged.arc = outline?.arc
      return merged
    })
})

function volumeTitle(no: number, title?: string): string {
  const text = title?.trim()
  if (text) return text
  return no <= VOLUME_NUMBERS.length ? `第${VOLUME_NUMBERS[no - 1]}卷` : `第 ${no} 卷`
}

function normalizeVolume(raw: VolumeContent, index: number, all: ChapterSummary[]): VolumeView {
  const no = typeof raw.no === 'number' && raw.no > 0 ? raw.no : index + 1
  const own = raw.chapters?.length ? [...raw.chapters].sort((a, b) => a.no - b.no) : []
  const from = raw.chapter_from ?? own[0]?.no ?? null
  const to = raw.chapter_to ?? own[own.length - 1]?.no ?? null
  // 卷内未下发章节时按章号区间从全书章节里取，避免重复挂载同一批章节
  const chapters = own.length
    ? own
    : from !== null || to !== null
      ? all.filter(
          (chapter) =>
            (from === null || chapter.no >= from) && (to === null || chapter.no <= to),
        )
      : []
  return {
    key: String(no),
    title: volumeTitle(no, raw.title),
    from: from ?? chapters[0]?.no ?? null,
    to: to ?? chapters[chapters.length - 1]?.no ?? null,
    summary: raw.summary?.trim() || '',
    conflict: raw.conflict?.trim() || '',
    theme: raw.theme?.trim() || '',
    coreEvent: raw.core_event?.trim() || '',
    conflictAxis: raw.conflict_axis?.trim() || '',
    endHook: raw.end_hook?.trim() || '',
    arc: raw.arc?.trim() || '',
    tensionProfile: raw.tension_profile?.trim() || '',
    chapters,
  }
}

/** 未落在任何卷区间内的章节兜底展示，避免手工新增的章节不可见 */
function unassignedVolume(chapters: ChapterSummary[]): VolumeView {
  return {
    key: 'unassigned',
    title: '未分卷',
    from: null,
    to: null,
    summary: '',
    conflict: '',
    theme: '',
    coreEvent: '',
    conflictAxis: '',
    endHook: '',
    arc: '',
    tensionProfile: '',
    chapters,
  }
}

/** 有卷字段直接用；没有则按章节聚合为单卷，下拉永远是单选项而不是空下拉 */
const volumes = computed<VolumeView[]>(() => {
  const all = allChapters.value
  const raw = props.run.volumes
  if (Array.isArray(raw) && raw.length) {
    const mapped = raw.map((volume, index) => normalizeVolume(volume, index, all))
    const covered = new Set<number>()
    mapped.forEach((volume) => volume.chapters.forEach((chapter) => covered.add(chapter.no)))
    const uncovered = all.filter((chapter) => !covered.has(chapter.no))
    if (uncovered.length) mapped.push(unassignedVolume(uncovered))
    if (mapped.some((volume) => volume.chapters.length)) return mapped
  }
  const outline = props.run.outline
  return [
    {
      key: '1',
      title: '第一卷',
      from: all[0]?.no ?? null,
      to: all[all.length - 1]?.no ?? null,
      summary: outline?.synopsis || outline?.logline || '',
      conflict: outline?.conflict || outline?.mainline || '',
      theme: outline?.theme_core || '',
      coreEvent: '',
      conflictAxis: '',
      endHook: '',
      arc: '',
      tensionProfile: '',
      chapters: all,
    },
  ]
})

/** 章节应归属的卷：优先区间命中的卷，否则落到「未分卷」 */
function volumeKeyForChapter(no: number): string {
  const hit = volumes.value.find(
    (volume) =>
      volume.key !== 'unassigned' &&
      (volume.from === null || no >= volume.from) &&
      (volume.to === null || no <= volume.to),
  )
  return hit?.key ?? 'unassigned'
}

const currentVolume = computed(
  () => volumes.value.find((volume) => volume.key === selectedKey.value) || volumes.value[0],
)

/** 卷规划字段：只保留实际有值的项，避免整片「—」 */
const volumeExtraFields = computed(() => {
  const volume = currentVolume.value
  if (!volume) return []
  return [
    { label: '卷主题', value: volume.theme },
    { label: '卷核心事件', value: volume.coreEvent },
    { label: '卷矛盾轴', value: volume.conflictAxis },
    { label: '卷末钩子', value: volume.endHook },
    { label: '卷内人物弧光', value: volume.arc },
    { label: '卷节奏曲线', value: volume.tensionProfile },
  ].filter((item) => item.value)
})

watch(
  volumes,
  (list) => {
    if (!list.length) return
    if (!list.some((volume) => volume.key === selectedKey.value)) {
      selectedKey.value = list[0].key
      page.value = 1
    }
  },
  { immediate: true },
)

watch(selectedKey, () => {
  page.value = 1
})

watch(keyword, () => {
  page.value = 1
})

const filtered = computed<ChapterSummary[]>(() => {
  const list = currentVolume.value?.chapters || []
  const text = keyword.value.trim().toLowerCase()
  if (!text) return list
  return list.filter((chapter) =>
    [
      chapter.title,
      chapter.summary,
      chapter.conflict,
      chapter.hook,
      chapter.scene,
      chapter.hook_type,
      chapter.emotion,
      chapter.chapter_id,
      ...(chapter.key_events || []),
      ...(chapter.roles || []),
      ...(chapter.factions || []),
      ...(chapter.items || []),
      String(chapter.no),
    ]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(text)),
  )
})

const pageCount = computed(() => Math.max(1, Math.ceil(filtered.value.length / PAGE_SIZE)))
const paged = computed(() =>
  filtered.value.slice((page.value - 1) * PAGE_SIZE, page.value * PAGE_SIZE),
)

watch(pageCount, (count) => {
  if (page.value > count) page.value = count
})

// 切换任务时回到第一卷第 1 页并清空搜索
watch(
  () => props.run.run_id,
  () => {
    keyword.value = ''
    page.value = 1
    selectedKey.value = volumes.value[0]?.key || '1'
    detailChapter.value = null
  },
)

const rangeText = computed(() => {
  const volume = currentVolume.value
  if (!volume) return ''
  if (volume.from === null && volume.to === null) return ''
  if (volume.from !== null && volume.to !== null) return `第 ${volume.from}–${volume.to} 章`
  return volume.from !== null ? `第 ${volume.from} 章起` : `至第 ${volume.to} 章`
})

const volumeWordsText = computed(() => {
  const total = (currentVolume.value?.chapters || []).reduce(
    (sum, chapter) => sum + (typeof chapter.words === 'number' ? chapter.words : 0),
    0,
  )
  return total > 0 ? `${total.toLocaleString('zh-CN')} 字` : ''
})

function wordsText(chapter: ChapterSummary): string {
  if (typeof chapter.words !== 'number' || chapter.words <= 0) return ''
  return `${chapter.words.toLocaleString('zh-CN')} 字`
}

function tensionText(value?: number): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return ''
  return `${value} / 10`
}

function listValue(values?: string[]): string {
  const list = values?.filter((item) => item && item.trim())
  return list && list.length ? list.join('、') : ''
}

function numValue(value?: number): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return ''
  return value.toLocaleString('zh-CN')
}

/** 章节详细字段：只保留有值项，按分组展示 */
const detailGroups = computed(() => {
  const c = detailChapter.value
  if (!c) return []
  const groups = [
    {
      title: '基础信息',
      rows: [
        { label: '章节标识', value: c.chapter_id || '' },
        { label: '字数', value: wordsText(c) },
        { label: '场景', value: c.scene || '' },
        { label: '钩子类型', value: c.hook_type || '' },
        { label: '情绪主线', value: c.emotion || '' },
        { label: '张力值', value: tensionText(c.tension) },
        { label: '章节状态', value: c.chapter_status || '' },
      ],
    },
    {
      title: '剧情结构',
      rows: [
        { label: '概括', value: c.summary || '' },
        { label: '核心冲突', value: c.conflict || '' },
        { label: '章末钩子', value: c.hook || '' },
        { label: '关键事件', value: listValue(c.key_events) },
        { label: '情节要点', value: listValue(c.points) },
        { label: '本章铺垫', value: c.setup || '' },
        { label: '本章兑现', value: c.payoff || '' },
        { label: '章节阶段', value: c.arc || '' },
        { label: '节拍类型', value: c.beat_type || '' },
        { label: '本章功能', value: c.chapter_function || '' },
        { label: '本章目的', value: c.chapter_goal || '' },
      ],
    },
    {
      title: '人物与设定',
      rows: [
        { label: '出场角色', value: listValue(c.roles) },
        { label: '涉及势力', value: listValue(c.factions) },
        { label: '涉及道具', value: listValue(c.items) },
        { label: '新登场角色', value: listValue(c.new_characters) },
        { label: '新道具', value: listValue(c.new_items) },
        { label: '新设定', value: listValue(c.new_settings) },
        { label: '关联伏笔', value: listValue(c.foreshadow_ids) },
      ],
    },
    {
      title: '写作数据',
      rows: [
        { label: '叙事视角', value: c.pov || '' },
        { label: '时间跨度', value: c.time_span || '' },
        { label: '目标字数', value: numValue(c.word_target) },
        { label: '实际字数', value: numValue(c.word_actual) },
        { label: '爽点类型', value: c.payoff_type || '' },
        { label: '爽点归属', value: c.payoff_owner || '' },
        { label: '爽点强度', value: numValue(c.payoff_intensity) },
        { label: '泪点', value: c.tear_point || '' },
        { label: '甜点', value: c.sweet_point || '' },
        { label: '反转', value: c.twist || '' },
        { label: '连续性校验', value: c.continuity_check || '' },
        { label: '修订说明', value: c.revision_note || '' },
      ],
    },
  ]
  return groups
    .map((group) => ({ title: group.title, rows: group.rows.filter((row) => row.value) }))
    .filter((group) => group.rows.length)
})

function pickVolume(key: string): void {
  if (selectedKey.value === key) return
  selectedKey.value = key
}

function jump(no: number): void {
  emit('jump', no)
}
</script>

<style scoped>
.summaries {
  padding: var(--space-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  height: 100%;
  min-height: 0;
}

/* 章节列表独立滚动，筛选面板与卷概括固定 */
.summaries__list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding-right: 4px;
  scrollbar-width: thin;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.summaries__list::-webkit-scrollbar {
  width: 8px;
}

.summaries__list::-webkit-scrollbar-thumb {
  background: #d7dde5;
  border-radius: 8px;
}

/* ---------- 筛选面板 ---------- */
.summaries__panel {
  flex: none;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-md);
  background: #fff;
}

.summaries__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.summaries__search {
  flex: none;
  width: 240px;
  height: 30px;
  padding: 0 12px;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-pill);
  background: var(--color-bg-softer);
  font-size: 14px;
  font-family: inherit;
  color: var(--color-text);
}

.summaries__search:focus {
  outline: none;
  border-color: var(--color-brand);
  background: #fff;
}

.summaries__meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-left: auto;
}

.summaries__count {
  font-size: 14px;
  color: var(--color-text-3);
  white-space: nowrap;
}

.summaries__count b {
  color: var(--color-text);
  font-weight: 600;
}

.summaries__pager {
  display: flex;
  align-items: center;
  gap: 4px;
}

.summaries__page-btn {
  width: 24px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-sm);
  background: #fff;
  color: var(--color-text-2);
  font-size: 14px;
  line-height: 1;
  font-family: inherit;
}

.summaries__page-btn:hover:not(:disabled) {
  border-color: var(--color-brand);
  color: var(--color-brand);
}

.summaries__page-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.summaries__page-info {
  font-size: 14px;
  color: var(--color-text-3);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.summaries__row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.summaries__row-label {
  flex: none;
  width: 32px;
  padding-top: 5px;
  font-size: 14px;
  color: var(--color-text-3);
}

.summaries__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.summaries__chip {
  height: 26px;
  padding: 0 11px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid transparent;
  border-radius: var(--radius-pill);
  background: var(--color-bg-soft);
  color: var(--color-text-2);
  font-size: 14px;
  font-family: inherit;
  white-space: nowrap;
}

.summaries__chip:hover {
  color: var(--color-brand);
}

.summaries__acts {
  display: inline-flex;
  align-items: center;
  gap: 2px;
}

.vol-card__head .summaries__acts {
  margin-left: auto;
}

.summaries__act {
  width: 24px;
  height: 24px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  color: var(--color-text-3);
}

.summaries__act:hover:not(:disabled) {
  background: var(--color-bg-soft);
  color: var(--color-brand);
}

.summaries__act--danger:hover:not(:disabled) {
  background: var(--color-danger-soft);
  color: var(--color-danger);
}

.summaries__act:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.summaries__act svg {
  width: 14px;
  height: 14px;
}

.summaries__dialog-text {
  font-size: var(--text-sm);
  line-height: 1.7;
  color: var(--color-text-2);
}

.summaries__chip.is-active {
  border-color: var(--color-brand);
  background: rgba(13, 148, 136, 0.1);
  color: var(--color-brand);
  font-weight: 600;
}

.summaries__chip-count {
  font-size: 14px;
  font-weight: 400;
  color: var(--color-text-3);
}

.summaries__chip.is-active .summaries__chip-count {
  color: var(--color-brand);
  opacity: 0.75;
}

/* ---------- 卷概括 ---------- */
.vol-card {
  flex: none;
  position: relative;
  padding: 12px 14px 12px 17px;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-md);
  background: #fff;
}

.vol-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 12px;
  bottom: 12px;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: var(--color-brand);
  opacity: 0.55;
}

.vol-card__head {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 10px;
}

.vol-card__title {
  font-size: var(--text-md);
  font-weight: 700;
  color: var(--color-text);
}

.vol-card__range {
  font-size: 14px;
  font-family: var(--font-mono);
  color: var(--color-text-3);
  white-space: nowrap;
}

.vol-card__stats {
  display: flex;
  align-items: baseline;
  gap: 14px;
  margin-left: auto;
  font-size: 14px;
  color: var(--color-text-3);
  white-space: nowrap;
}

.vol-card__stats b {
  color: var(--color-text-2);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.vol-card__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 20px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--color-line);
}

.vol-card__block {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.vol-card__label {
  font-size: 14px;
  letter-spacing: 0.06em;
  color: var(--color-text-3);
}

.vol-card__text {
  margin: 0;
  font-size: var(--text-xs);
  line-height: 1.75;
  color: var(--color-text-2);
  overflow-wrap: anywhere;
}

/* ---------- 章节卡片 ---------- */
.chapter-card {
  position: relative;
  flex: none;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 14px;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-md);
  background: #fff;
  min-width: 0;
}

.chapter-card__acts {
  position: absolute;
  top: 8px;
  right: 8px;
  opacity: 0;
  transition: opacity var(--dur-fast) var(--ease);
}

.chapter-card:hover .chapter-card__acts,
.chapter-card:focus-within .chapter-card__acts {
  opacity: 1;
}

@media (hover: none) {
  .chapter-card__acts {
    opacity: 1;
  }
}

.chapter-card.is-clickable {
  cursor: pointer;
  transition:
    border-color var(--dur-fast) var(--ease),
    box-shadow var(--dur-fast) var(--ease);
}

.chapter-card.is-clickable:hover {
  border-color: rgba(13, 148, 136, 0.45);
  box-shadow: 0 8px 20px -16px rgba(15, 23, 42, 0.45);
}

.chapter-card.is-clickable:focus-visible {
  outline: 2px solid var(--color-brand);
  outline-offset: 2px;
}

.chapter-card__head {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding-right: 52px;
}

.chapter-card__no {
  flex: none;
  padding: 1px 8px;
  border-radius: var(--radius-pill);
  background: rgba(13, 148, 136, 0.09);
  color: var(--color-brand);
  font-family: var(--font-mono);
  font-size: 14px;
  white-space: nowrap;
}

.chapter-card__title {
  flex: 1;
  min-width: 0;
  font-size: var(--text-md);
  font-weight: 700;
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chapter-card__words {
  flex: none;
  font-size: 14px;
  color: var(--color-text-3);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.chapter-card__section {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.chapter-card__label {
  font-size: 14px;
  letter-spacing: 0.06em;
  color: var(--color-text-3);
}

.chapter-card__text {
  margin: 0;
  font-size: var(--text-xs);
  line-height: 1.75;
  color: var(--color-text-2);
  overflow-wrap: anywhere;
}

/* 卷规划字段：窄卡片三列，避免卷概览过高 */
.vol-card__grid--extra {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.summaries__empty {
  padding: var(--space-8) var(--space-4);
  text-align: center;
  font-size: var(--text-sm);
  color: var(--color-text-2);
}

.summaries__empty p + p {
  margin-top: 6px;
  font-size: var(--text-xs);
  color: var(--color-text-3);
}

.summaries__reset {
  margin-top: var(--space-3);
}

/* 视口偏矮时改为整列滚动，避免卷概括卡把章节列表挤成 0 高 */
@media (max-height: 760px) {
  .summaries {
    height: auto;
  }

  .summaries__list {
    flex: none;
    overflow: visible;
    padding-right: 0;
  }
}

@media (max-width: 720px) {
  .summaries {
    padding: var(--space-4);
  }

  .summaries__toolbar {
    flex-wrap: wrap;
  }

  .summaries__search {
    width: 100%;
  }

  .summaries__meta {
    margin-left: 0;
  }

  .summaries__row-label {
    width: 24px;
  }

  .vol-card__stats {
    margin-left: 0;
    width: 100%;
  }

  .vol-card__grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .vol-card__grid--extra {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .chapter-card__head {
    flex-wrap: wrap;
  }

  .chapter-card__title {
    flex: 1 1 100%;
    order: 3;
    white-space: normal;
  }
}

/* ---------- 章节详细字段抽屉 ---------- */
.detail-drawer {
  position: fixed;
  inset: 0;
  z-index: 70;
}

.detail-drawer__mask {
  position: absolute;
  inset: 0;
  background: rgba(8, 20, 32, 0.42);
}

.detail-drawer__panel {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: min(560px, 94vw);
  display: flex;
  flex-direction: column;
  background: var(--color-bg);
  border-left: 1px solid var(--color-line);
  box-shadow: var(--shadow-lg);
}

.detail-drawer__head {
  flex: none;
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 18px 22px 14px;
  border-bottom: 1px solid var(--color-line);
}

.detail-drawer__head-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.detail-drawer__no {
  font-family: var(--font-mono);
  font-size: 14px;
  color: var(--color-brand);
}

.detail-drawer__title {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: var(--color-text);
}

.detail-drawer__sub {
  display: flex;
  flex-wrap: wrap;
  gap: 2px 10px;
  margin: 0;
  font-size: 14px;
  color: var(--color-text-3);
}

.detail-drawer__sub span + span::before {
  content: '·';
  margin-right: 8px;
  color: var(--color-line-strong);
}

.detail-drawer__close {
  flex: none;
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border-radius: var(--radius-sm);
  font-size: 20px;
  line-height: 1;
  color: var(--color-text-3);
}

.detail-drawer__close:hover {
  background: var(--color-bg-soft);
  color: var(--color-text);
}

.detail-drawer__body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 18px 22px 24px;
  overscroll-behavior: contain;
}

.detail-drawer__section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.detail-drawer__section-title {
  margin: 0;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--color-line);
  font-size: 15px;
  font-weight: 700;
  color: var(--color-text);
}

.detail-drawer__row {
  display: grid;
  grid-template-columns: 104px minmax(0, 1fr);
  gap: 12px;
  align-items: start;
  font-size: 14px;
  line-height: 1.65;
}

.detail-drawer__label {
  color: var(--color-text-3);
  white-space: nowrap;
}

.detail-drawer__value {
  color: var(--color-text);
  overflow-wrap: anywhere;
}

.detail-drawer__foot {
  flex: none;
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 22px 16px;
  border-top: 1px solid var(--color-line);
}

@media (max-width: 720px) {
  .detail-drawer__panel {
    width: 100%;
  }

  .detail-drawer__head,
  .detail-drawer__body {
    padding-left: 16px;
    padding-right: 16px;
  }

  .detail-drawer__row {
    grid-template-columns: 92px minmax(0, 1fr);
  }
}
</style>
