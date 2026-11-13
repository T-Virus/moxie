<template>
  <div class="reader">
    <aside class="reader__toc" aria-label="章节目录">
      <div v-for="volume in volumes" :key="volume.key" class="toc-volume">
        <button
          type="button"
          class="toc-volume__head"
          :aria-expanded="!collapsed.includes(volume.key)"
          @click="toggleVolume(volume.key)"
        >
          <span class="toc-volume__caret" :class="{ 'is-open': !collapsed.includes(volume.key) }">▸</span>
          <span class="toc-volume__title">{{ volume.title }}</span>
          <span class="toc-volume__count">{{ volume.chapters.length }}</span>
        </button>

        <div v-if="!collapsed.includes(volume.key)" class="toc-volume__chapters">
          <button
            v-for="chapter in volume.chapters"
            :key="chapter.no"
            type="button"
            class="toc-chapter"
            :class="{ 'is-active': chapter.no === currentNo }"
            :aria-current="chapter.no === currentNo ? 'true' : undefined"
            :title="chapter.title || '未命名'"
            @click="select(chapter.no)"
          >
            <span class="toc-chapter__no">第 {{ chapter.no }} 章</span>
            <span class="toc-chapter__title">{{ chapter.title || '未命名' }}</span>
          </button>
        </div>
      </div>

      <p v-if="!volumes.length" class="reader__toc-empty">暂无章节</p>
    </aside>

    <section class="reader__main">
      <div v-if="!chapters.length" class="reader__empty">
        <p class="empty__title">正文尚未生成</p>
        <p>任务完成后可在此阅读全文；也可以先到「章节概括」查看每章梗概。</p>
      </div>

      <template v-else-if="current">
        <header class="reader__head">
          <div class="reader__controls">
            <div class="reader__group" role="group" aria-label="字号">
              <span class="reader__group-label">字号</span>
              <button
                v-for="option in FONT_OPTIONS"
                :key="option.value"
                type="button"
                class="reader__chip"
                :class="{ 'is-active': fontKey === option.value }"
                @click="fontKey = option.value"
              >
                {{ option.label }}
              </button>
            </div>
            <div class="reader__group" role="group" aria-label="间距">
              <span class="reader__group-label">间距</span>
              <button
                v-for="option in LINE_OPTIONS"
                :key="option.value"
                type="button"
                class="reader__chip"
                :class="{ 'is-active': lineKey === option.value }"
                @click="lineKey = option.value"
              >
                {{ option.label }}
              </button>
            </div>
            <div class="reader__group" role="group" aria-label="主题">
              <span class="reader__group-label">主题</span>
              <button
                v-for="option in THEME_OPTIONS"
                :key="option.value"
                type="button"
                class="reader__chip"
                :class="{ 'is-active': themeKey === option.value }"
                @click="themeKey = option.value"
              >
                {{ option.label }}
              </button>
            </div>
          </div>

          <button type="button" class="reader__copy" @click="copyChapter">
            {{ copied ? '已复制' : '复制正文' }}
          </button>
        </header>

        <div ref="paneRef" class="reader__pane" :class="`is-${themeKey}`">
          <article
            class="reader__body markdown"
            :style="{ fontSize: `${fontSize}px`, lineHeight }"
            v-html="rendered"
          />
        </div>

        <footer class="reader__foot">
          <button
            type="button"
            class="reader__nav"
            :disabled="!prevChapter"
            @click="prevChapter && select(prevChapter.no)"
          >
            ‹ 上一章
          </button>
          <span class="reader__stat">本章字数：{{ currentWords.toLocaleString('zh-CN') }} 字</span>
          <button
            type="button"
            class="reader__nav"
            :disabled="!nextChapter"
            @click="nextChapter && select(nextChapter.no)"
          >
            下一章 ›
          </button>
        </footer>
      </template>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import type { ChapterContent, ChapterSummary, RunDetail } from '@/types'
import { renderMarkdown } from '@/utils/markdown'

const props = defineProps<{ run: RunDetail; chapter: number }>()
const emit = defineEmits<{ (event: 'select', chapter: number): void }>()

const FONT_OPTIONS = [
  { value: 'small', label: '小', size: 14 },
  { value: 'medium', label: '中', size: 16 },
  { value: 'large', label: '大', size: 18 },
] as const
const LINE_OPTIONS = [
  { value: 'compact', label: '紧凑', height: 1.7 },
  { value: 'normal', label: '标准', height: 1.95 },
  { value: 'loose', label: '宽松', height: 2.2 },
] as const
const THEME_OPTIONS = [
  { value: 'light', label: '浅色' },
  { value: 'dark', label: '深色' },
  { value: 'sepia', label: '护眼' },
] as const

const VOLUME_NUMBERS = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十']
/** 服务端未下发分卷时，按约 4 章一卷平均分配，保证目录始终是「卷 → 章」两层结构 */
const FALLBACK_VOLUME_TARGET = 4

const fontKey = ref<(typeof FONT_OPTIONS)[number]['value']>('medium')
const lineKey = ref<(typeof LINE_OPTIONS)[number]['value']>('normal')
const themeKey = ref<(typeof THEME_OPTIONS)[number]['value']>('light')
const copied = ref(false)
const collapsed = ref<string[]>([])
/** 右侧正文滚动容器：切换章节时重置到顶部 */
const paneRef = ref<HTMLElement | null>(null)

/** 合并 正文(chapters) / 大纲(outline.chapters) / 逐章概括(chapter_summaries)，
 *  与「卷章概览」保持一致的完整章节列表，避免正文目录与概览不同步 */
interface ReaderChapter {
  no: number
  title: string
  content: string
  words?: number
  /** 是否有正文内容（否则仅概括占位） */
  hasContent: boolean
}

const contentMap = computed(() => {
  const map = new Map<number, ChapterContent>()
  for (const chapter of props.run.chapters || []) map.set(chapter.no, chapter)
  return map
})
const summaryMap = computed(() => {
  const map = new Map<number, ChapterSummary>()
  for (const summary of props.run.chapter_summaries || []) map.set(summary.no, summary)
  return map
})
const outlineChapters = computed(() => props.run.outline?.chapters || [])
/** 概览中隐藏/删除的章号：正文也一并隐藏，保证与卷章概览完全一致 */
const hiddenNos = computed(() => new Set(props.run.chapter_hidden || []))

const chapters = computed<ReaderChapter[]>(() => {
  const nos = new Set<number>([
    ...contentMap.value.keys(),
    ...summaryMap.value.keys(),
    ...outlineChapters.value.map((chapter) => chapter.no),
  ])
  return [...nos]
    .filter((no) => !hiddenNos.value.has(no))
    .sort((a, b) => a - b)
    .map((no) => {
      const content = contentMap.value.get(no)
      const summary = summaryMap.value.get(no)
      const outline = outlineChapters.value.find((chapter) => chapter.no === no)
      // 标题/字数优先级与「卷章概览」保持一致：概括优先于正文、正文优先于大纲
      const title = summary?.title || content?.title || outline?.title || `第 ${no} 章`
      return {
        no,
        title,
        content: content?.content || '',
        words: summary?.words ?? content?.words,
        hasContent: Boolean(content?.content),
      }
    })
})

const volumes = computed(() => {
  const all = chapters.value
  const raw = props.run.volumes
  if (Array.isArray(raw) && raw.length) {
    const mapped = raw.map((volume, index) => {
      const no = typeof volume.no === 'number' && volume.no > 0 ? volume.no : index + 1
      const from = volume.chapter_from ?? null
      const to = volume.chapter_to ?? null
      const own = volume.chapters?.length
        ? all.filter((chapter) => volume.chapters!.some((item) => item.no === chapter.no))
        : all.filter(
            (chapter) =>
              (from === null || chapter.no >= from) && (to === null || chapter.no <= to),
          )
      const title =
        volume.title?.trim() ||
        (no <= VOLUME_NUMBERS.length ? `第${VOLUME_NUMBERS[no - 1]}卷` : `第 ${no} 卷`)
      return { key: String(no), title, chapters: own }
    })
    if (mapped.some((volume) => volume.chapters.length)) return mapped.filter((v) => v.chapters.length)
  }
  const result: Array<{ key: string; title: string; chapters: ReaderChapter[] }> = []
  const volumeCount = Math.max(1, Math.round(all.length / FALLBACK_VOLUME_TARGET))
  const base = Math.floor(all.length / volumeCount)
  const extra = all.length % volumeCount
  let cursor = 0
  for (let index = 1; index <= volumeCount; index += 1) {
    const size = base + (index <= extra ? 1 : 0)
    result.push({
      key: String(index),
      title: index <= VOLUME_NUMBERS.length ? `第${VOLUME_NUMBERS[index - 1]}卷` : `第 ${index} 卷`,
      chapters: all.slice(cursor, cursor + size),
    })
    cursor += size
  }
  return result
})

const currentNo = computed(() => {
  if (chapters.value.some((chapter) => chapter.no === props.chapter)) return props.chapter
  return chapters.value[0]?.no || 0
})
const current = computed(
  () => chapters.value.find((chapter) => chapter.no === currentNo.value) || null,
)
const currentIndex = computed(() =>
  chapters.value.findIndex((chapter) => chapter.no === currentNo.value),
)
const prevChapter = computed(() =>
  currentIndex.value > 0 ? chapters.value[currentIndex.value - 1] : null,
)
const nextChapter = computed(() =>
  currentIndex.value >= 0 && currentIndex.value < chapters.value.length - 1
    ? chapters.value[currentIndex.value + 1]
    : null,
)

/** 当前章的正文字数（与目录/信息页同口径：概括字数优先，其次正文字符数） */
const currentWords = computed(
  () => current.value?.words || current.value?.content?.length || 0,
)

const fontSize = computed(
  () => FONT_OPTIONS.find((option) => option.value === fontKey.value)?.size || 16,
)
const lineHeight = computed(
  () => LINE_OPTIONS.find((option) => option.value === lineKey.value)?.height || 1.95,
)

const rendered = computed(() => {
  const chapter = current.value
  if (!chapter) return ''
  const heading = `# 第${chapter.no}章 ${chapter.title || ''}`.trim()
  const content = chapter.content || ''
  if (content) {
    const text = /^#\s*第\s*\d+\s*章/m.test(content) ? content : `${heading}\n\n${content}`
    return renderMarkdown(text)
  }
  // 仅有概括、无正文：展示概括并提示正文尚未生成
  const summary = summaryMap.value.get(chapter.no)?.summary
  const body = summary ? `> ${summary}` : '_正文尚未生成，可前往「卷章概览」补全概括。_'
  return renderMarkdown(`${heading}\n\n${body}`)
})

function select(no: number): void {
  copied.value = false
  emit('select', no)
}

function toggleVolume(key: string): void {
  const index = collapsed.value.indexOf(key)
  if (index >= 0) collapsed.value.splice(index, 1)
  else collapsed.value.push(key)
}

function chapterText(chapter: ReaderChapter | null): string {
  if (!chapter) return ''
  const content = chapter.content || ''
  if (/^#\s*第\s*\d+\s*章/m.test(content)) return content
  return `# 第${chapter.no}章 ${chapter.title || ''}\n\n${content}`
}

async function copyChapter(): Promise<void> {
  if (!current.value) return
  try {
    await navigator.clipboard.writeText(chapterText(current.value))
    copied.value = true
    window.setTimeout(() => (copied.value = false), 1600)
  } catch {
    copied.value = false
  }
}

watch(currentNo, onChapterChange, { flush: 'post' })

/** 切换章节：正文滚动回顶部，并让目录中当前章滚动到可见处 */
function onChapterChange(): void {
  if (paneRef.value) paneRef.value.scrollTop = 0
  scrollActiveIntoView()
}

function scrollActiveIntoView(): void {
  document
    .querySelector('.toc-chapter.is-active')
    ?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
}

onMounted(scrollActiveIntoView)
</script>

<style scoped>
.reader {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  height: 100%;
  min-height: 0;
}

/* ---------- 左侧目录（卷 → 章） ---------- */
.reader__toc {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 12px 10px;
  border-right: 1px solid var(--color-line);
  background: var(--color-bg-softer);
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-width: thin;
}

.reader__toc::-webkit-scrollbar {
  width: 8px;
}

.reader__toc::-webkit-scrollbar-thumb {
  background: #d7dde5;
  border-radius: 8px;
}

.toc-volume__head {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 6px 8px;
  border-radius: var(--radius-sm);
  text-align: left;
  color: var(--color-text);
  font-size: 14px;
  font-weight: 600;
}

.toc-volume__head:hover {
  background: var(--color-bg-soft);
}

.toc-volume__caret {
  flex: none;
  display: inline-block;
  color: var(--color-text-3);
  font-size: 14px;
  transition: transform var(--dur-fast) var(--ease);
}

.toc-volume__caret.is-open {
  transform: rotate(90deg);
}

.toc-volume__title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.toc-volume__count {
  flex: none;
  font-size: 14px;
  font-weight: 500;
  color: var(--color-text-3);
  font-variant-numeric: tabular-nums;
}

.toc-volume__chapters {
  display: flex;
  flex-direction: column;
  gap: 1px;
  margin: 2px 0 6px 15px;
  padding-left: 8px;
  border-left: 1px solid var(--color-line);
}

.toc-chapter {
  display: flex;
  align-items: baseline;
  gap: 6px;
  width: 100%;
  padding: 5px 8px;
  border-radius: var(--radius-sm);
  text-align: left;
  color: var(--color-text-2);
  font-size: 14px;
  min-width: 0;
}

.toc-chapter:hover {
  background: var(--color-bg-soft);
  color: var(--color-text);
}

.toc-chapter.is-active {
  background: rgba(13, 148, 136, 0.1);
  color: var(--color-brand);
  font-weight: 600;
}

.toc-chapter__no {
  flex: none;
  font-size: 14px;
  color: var(--color-text-3);
  font-variant-numeric: tabular-nums;
}

.toc-chapter.is-active .toc-chapter__no {
  color: var(--color-brand);
}

.toc-chapter__title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.reader__toc-empty {
  padding: 12px;
  font-size: 14px;
  color: var(--color-text-3);
  text-align: center;
}

/* ---------- 右侧正文 ---------- */
.reader__main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}

.reader__head {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px 12px;
  padding: 10px 20px;
  border-bottom: 1px solid var(--color-line);
}

.reader__copy {
  flex: none;
  margin-left: auto;
  height: 26px;
  padding: 0 12px;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-pill);
  background: #fff;
  color: var(--color-text-2);
  font-size: 14px;
  font-family: inherit;
}

.reader__copy:hover {
  border-color: var(--color-brand);
  color: var(--color-brand);
}

.reader__controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 18px;
}

.reader__group {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.reader__group-label {
  margin-right: 2px;
  font-size: 14px;
  color: var(--color-text-3);
}

.reader__chip {
  height: 24px;
  min-width: 30px;
  padding: 0 9px;
  border: 1px solid transparent;
  border-radius: var(--radius-pill);
  background: var(--color-bg-soft);
  color: var(--color-text-2);
  font-size: 14px;
  font-family: inherit;
}

.reader__chip:hover {
  color: var(--color-brand);
}

.reader__chip.is-active {
  border-color: var(--color-brand);
  background: rgba(13, 148, 136, 0.1);
  color: var(--color-brand);
  font-weight: 600;
}

/* 阅读区主题 */
.reader__pane {
  flex: 1;
  min-height: 0;
  margin: 12px 20px 0;
  padding: 18px 22px;
  overflow-y: auto;
  overscroll-behavior: contain;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-md);
  background: #fff;
  scrollbar-width: thin;
}

.reader__pane::-webkit-scrollbar {
  width: 8px;
}

.reader__pane::-webkit-scrollbar-thumb {
  background: #d7dde5;
  border-radius: 8px;
}

.reader__pane.is-dark {
  border-color: #2b333d;
  background: #1e242b;
  --reader-text: #d5dce5;
}

.reader__pane.is-sepia {
  border-color: #e6dcc3;
  background: #f7f2e4;
  --reader-text: #4b4234;
}

.reader__body {
  color: var(--reader-text, var(--color-text-2));
  overflow-wrap: anywhere;
}

.reader__body :deep(h1) {
  font-size: 1.15em;
  font-weight: 700;
  color: inherit;
  margin: 0 0 16px;
  text-align: center;
}

.reader__body :deep(p) {
  margin: 0 0 14px;
  text-indent: 2em;
}

.reader__body :deep(strong) {
  color: inherit;
  font-weight: 700;
}

.reader__foot {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 12px 20px;
}

.reader__nav {
  height: 28px;
  padding: 0 12px;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-pill);
  background: #fff;
  color: var(--color-text-2);
  font-size: 14px;
  font-family: inherit;
}

.reader__nav:hover:not(:disabled) {
  border-color: var(--color-brand);
  color: var(--color-brand);
}

.reader__nav:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.reader__stat {
  font-size: 14px;
  color: var(--color-text-3);
  font-variant-numeric: tabular-nums;
}

.reader__empty {
  padding: var(--space-10) var(--space-6);
  text-align: center;
  font-size: var(--text-sm);
  color: var(--color-text-2);
}

.reader__empty p + p {
  margin-top: 6px;
  font-size: var(--text-xs);
  color: var(--color-text-3);
}

@media (max-width: 860px) {
  .reader {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: minmax(0, 200px) minmax(0, 1fr);
  }

  .reader__toc {
    border-right: none;
    border-bottom: 1px solid var(--color-line);
  }

  .reader__head {
    padding: 12px 16px;
  }

  .reader__pane {
    margin: 10px 16px 0;
    padding: 16px;
  }

  .reader__foot {
    padding: 10px 16px;
  }
}
</style>
