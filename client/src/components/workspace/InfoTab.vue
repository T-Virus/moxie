<template>
  <div class="info">
    <div class="info__cover" :class="{ 'info__cover--empty': !coverUrl }">
      <img v-if="coverUrl" :src="coverUrl" :alt="`${run.title} 封面`" />
      <span v-else class="info__cover-char" aria-hidden="true">{{ coverChar }}</span>
      <span v-if="!coverUrl && !coverBusy" class="info__cover-hint">暂无封面图</span>
      <p v-if="coverError" class="info__cover-error" role="alert">{{ coverError }}</p>
      <button
        v-if="coverUrl"
        type="button"
        class="info__cover-delete"
        :disabled="coverBusy || coverUploading || coverDeleting"
        :title="coverDeleting ? '正在删除…' : '删除封面'"
        aria-label="删除封面"
        @click="openDeleteCoverDialog"
      >
        <span v-if="coverDeleting" class="info__cover-spinner" aria-hidden="true" />
        <svg
          v-else
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
      <div v-if="coverUrl" class="info__cover-actions">
        <div class="info__cover-icon-group">
          <button
            type="button"
            class="info__cover-icon"
            :disabled="coverBusy || coverUploading || coverDeleting"
            :title="coverBusy ? '正在生成…' : `${coverHint}（重新生成）`"
            aria-label="重新生成封面"
            @click="onGenerateCover"
          >
            <span v-if="coverBusy" class="info__cover-spinner" aria-hidden="true" />
            <svg
              v-else
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            >
              <path d="M21 12a9 9 0 1 1-2.64-6.36" />
              <path d="M21 3v6h-6" />
            </svg>
          </button>
          <button
            type="button"
            class="info__cover-icon"
            :disabled="coverBusy || coverUploading || coverDeleting"
            :title="coverUploading ? '正在上传…' : '上传封面'"
            aria-label="上传封面"
            @click="openCoverPicker"
          >
            <span v-if="coverUploading" class="info__cover-spinner" aria-hidden="true" />
            <svg
              v-else
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            >
              <path d="M12 16V4" />
              <path d="M7 9l5-5 5 5" />
              <path d="M4 20h16" />
            </svg>
          </button>
        </div>
        <button
          type="button"
          class="info__cover-icon"
          :disabled="coverBusy || coverUploading || coverDeleting"
          title="下载封面"
          aria-label="下载封面"
          @click="onDownloadCover"
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
            <path d="M12 3v12" />
            <path d="M7 10l5 5 5-5" />
            <path d="M4 21h16" />
          </svg>
        </button>
      </div>
      <div v-else class="info__cover-actions">
        <button
          type="button"
          class="info__cover-icon"
          :disabled="coverBusy || coverUploading"
          :title="coverBusy ? '正在生成…' : 'AI 生成封面'"
          aria-label="AI 生成封面"
          @click="onGenerateCover"
        >
          <span v-if="coverBusy" class="info__cover-spinner" aria-hidden="true" />
          <svg
            v-else
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path d="M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8L12 3Z" />
            <path d="M19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9L19 15Z" />
          </svg>
        </button>
        <button
          type="button"
          class="info__cover-icon"
          :disabled="coverBusy || coverUploading"
          :title="coverUploading ? '正在上传…' : '上传封面'"
          aria-label="上传封面"
          @click="openCoverPicker"
        >
          <span v-if="coverUploading" class="info__cover-spinner" aria-hidden="true" />
          <svg
            v-else
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path d="M12 16V4" />
            <path d="M7 9l5-5 5 5" />
            <path d="M4 20h16" />
          </svg>
        </button>
      </div>
      <input
        ref="coverInput"
        class="sr-only"
        type="file"
        accept="image/jpeg,image/png,image/webp"
        @change="onCoverFileChange"
      />
    </div>

    <div class="info__body">
      <header class="info__hero">
        <div class="info__hero-main">
          <h2 class="info__title">{{ editing ? '编辑作品信息' : (run.title || '未命名作品') }}</h2>
          <div v-if="!editing" class="info__chips">
            <span class="info__chip">{{ audienceText }}</span>
            <span class="info__chip">{{ lengthText }}</span>
            <span class="info__chip">{{ run.genre?.name || '未分类' }}</span>
            <span class="info__chip info__chip--mode">{{ MODE_LABEL[run.mode] }}</span>
          </div>
        </div>
        <div class="info__hero-side">
          <template v-if="!editing">
            <span class="info__updated" :title="`${latestChapterText} · ${updateTimeText}`">
              最近更新：{{ updateShortText }}
            </span>
            <button
              type="button"
              class="info__edit-icon"
              :disabled="!canEdit"
              :title="canEdit ? '编辑作品信息' : '运行中的作品暂不可编辑'"
              aria-label="编辑作品信息"
              @click="startEdit"
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
          </template>
          <template v-else>
            <button type="button" class="btn btn--sm" :disabled="saving" @click="cancelEdit">
              取消
            </button>
            <button type="button" class="btn btn--sm btn--brand" :disabled="saving" @click="submitEdit">
              {{ saving ? '保存中…' : '保存' }}
            </button>
          </template>
        </div>
      </header>

      <form v-if="editing" class="info__form" novalidate @submit.prevent>
        <section class="info__form-section">
          <div class="info__form-head">
            <span class="info__form-title">必填信息</span>
            <span class="info__form-hint">带 * 为必填</span>
          </div>

          <div class="info__form-grid">
            <label class="info__form-field">
              <span class="info__form-label">书名 <i>*</i></span>
              <input v-model="form.title" class="input" maxlength="120" placeholder="请输入书名" />
              <span v-if="errors.title" class="info__form-error">{{ errors.title }}</span>
            </label>
            <label class="info__form-field">
              <span class="info__form-label">作者</span>
              <input v-model="form.author" class="input" maxlength="60" placeholder="请输入作者（可留空）" />
            </label>
          </div>

          <div class="info__form-field">
            <span class="info__form-label">作品状态 <i>*</i></span>
            <div class="info__choices" role="group" aria-label="作品状态">
              <button
                v-for="option in STATUS_OPTIONS"
                :key="option"
                type="button"
                class="info__pill"
                :class="{ 'is-active': form.status === option }"
                :aria-pressed="form.status === option"
                @click="form.status = option"
              >
                {{ option }}
              </button>
            </div>
          </div>

          <div class="info__form-grid">
            <div class="info__form-field">
              <span class="info__form-label">频道 <i>*</i></span>
              <div class="info__choices" role="group" aria-label="频道">
                <button
                  type="button"
                  class="info__pill"
                  :class="{ 'is-active': form.audience === 'male' }"
                  @click="form.audience = 'male'"
                >
                  男频
                </button>
                <button
                  type="button"
                  class="info__pill"
                  :class="{ 'is-active': form.audience === 'female' }"
                  @click="form.audience = 'female'"
                >
                  女频
                </button>
              </div>
            </div>
            <div class="info__form-field">
              <span class="info__form-label">篇幅 <i>*</i></span>
              <div class="info__choices" role="group" aria-label="篇幅">
                <button
                  type="button"
                  class="info__pill"
                  :class="{ 'is-active': form.length === 'long' }"
                  @click="form.length = 'long'"
                >
                  长篇
                </button>
                <button
                  type="button"
                  class="info__pill"
                  :class="{ 'is-active': form.length === 'short' }"
                  @click="form.length = 'short'"
                >
                  短篇
                </button>
              </div>
            </div>
          </div>

          <div class="info__form-field">
            <span class="info__form-label">题材 <i>*</i></span>
            <GenrePicker
              v-model="form.genre"
              :options="genres"
              :audience="form.audience"
              :custom-allowed="customAllowed"
            />
            <span v-if="errors.genre" class="info__form-error">{{ errors.genre }}</span>
          </div>
        </section>

        <section class="info__form-section">
          <button
            type="button"
            class="info__optional-toggle"
            :aria-expanded="optionalOpen"
            @click="optionalOpen = !optionalOpen"
          >
            <span>更多信息（选填）</span>
            <span class="info__optional-caret" :class="{ 'is-open': optionalOpen }" aria-hidden="true" />
          </button>

          <div v-if="optionalOpen" class="info__form-grid">
            <label class="info__form-field info__form-field--full">
              <span class="info__form-label">一句话梗概</span>
              <input v-model="form.logline" class="input" maxlength="300" placeholder="一句话讲清故事" />
            </label>
            <label class="info__form-field info__form-field--full">
              <span class="info__form-label">作品简介</span>
              <textarea v-model="form.synopsis" class="input" rows="4" maxlength="2000" />
            </label>
            <div class="info__form-field">
              <span class="info__form-label">主题标签</span>
              <TagInput v-model="themeTags" :presets="THEME_PRESETS" placeholder="输入后回车添加" />
            </div>
            <div class="info__form-field">
              <span class="info__form-label">叙事人称</span>
              <input v-model="form.person" class="input" maxlength="60" />
              <div class="info__preset-list" role="group" aria-label="叙事人称预设">
                <button
                  v-for="preset in PERSON_PRESETS"
                  :key="preset"
                  type="button"
                  class="info__pill"
                  :class="{ 'is-active': form.person === preset }"
                  @click="toggleTextPreset('person', preset)"
                >
                  {{ preset }}
                </button>
              </div>
            </div>
            <div class="info__form-field">
              <span class="info__form-label">文风与语言</span>
              <TagInput v-model="styleTags" :presets="VOICE_PRESETS" placeholder="输入后回车添加" />
            </div>
            <div class="info__form-field">
              <span class="info__form-label">目标平台</span>
              <TagInput
                v-model="platformTags"
                :presets="PLATFORM_PRESETS"
                placeholder="输入后回车添加"
              />
            </div>
            <div
              v-for="field in SELECT_FIELDS"
              :key="field.key"
              class="info__form-field"
            >
              <span class="info__form-label">{{ field.label }}</span>
              <input v-model="form[field.key]" class="input" :placeholder="field.placeholder" />
              <div class="info__preset-list" role="group" :aria-label="`${field.label}预设`">
                <button
                  v-for="preset in field.presets"
                  :key="preset"
                  type="button"
                  class="info__pill"
                  :class="{ 'is-active': form[field.key] === preset }"
                  @click="toggleTextPreset(field.key, preset)"
                >
                  {{ preset }}
                </button>
              </div>
            </div>
            <label class="info__form-field info__form-field--full">
              <span class="info__form-label">世界观</span>
              <textarea v-model="form.world" class="input" rows="3" maxlength="1200" />
            </label>
            <label class="info__form-field">
              <span class="info__form-label">核心冲突</span>
              <input v-model="form.conflict" class="input" maxlength="1200" />
            </label>
            <label class="info__form-field">
              <span class="info__form-label">核心钩子</span>
              <input v-model="form.coreHook" class="input" maxlength="500" />
            </label>
            <label class="info__form-field info__form-field--full">
              <span class="info__form-label">全书主线</span>
              <textarea v-model="form.mainline" class="input" rows="3" maxlength="1200" />
            </label>
            <div class="info__form-field info__form-field--full">
              <span class="info__form-label">核心卖点</span>
              <TagInput v-model="sellingTags" placeholder="输入后回车添加" />
            </div>
          </div>
        </section>

        <div v-if="formError" class="alert" role="alert">{{ formError }}</div>
      </form>

      <p v-if="editing" class="info__readonly-note">以下为作品统计与生成结果，只读展示</p>

      <div v-if="!editing" class="info__row">
        <div class="info__field info__field--author">
          <span class="info__label">作者</span>
          <span class="info__author">{{ authorText }}</span>
        </div>
        <div class="info__field info__field--status">
          <span class="info__label">作品状态</span>
          <div class="info__status" role="group" aria-label="作品状态">
            <span
              v-for="option in STATUS_OPTIONS"
              :key="option"
              class="info__pill"
              :class="{ 'is-active': status === option }"
            >
              {{ option }}
            </span>
          </div>
        </div>
      </div>

      <!-- 核心统计：只保留数量类指标，频道/篇幅/题材/模式已上移到标题下方 -->
      <div class="info__stats">
        <div v-for="stat in statItems" :key="stat.label" class="info__stat">
          <b>{{ stat.value }}</b>
          <span>{{ stat.label }}</span>
        </div>
      </div>

      <blockquote v-if="!editing && logline" class="info__quote">
        <span class="info__quote-label">一句话梗概</span>
        <p>{{ logline }}</p>
      </blockquote>

      <div v-if="!editing && themes.length" class="info__themes">
        <span class="info__label">主题标签</span>
        <div class="info__theme-list">
          <span v-for="theme in themes" :key="theme" class="info__theme">{{ theme }}</span>
        </div>
      </div>

      <!-- 大纲基础信息：简介/题材与基调/叙事人称/文风等（story_bible 组1） -->
      <section v-if="!editing && bibleBlocks.length" class="info__section">
        <div class="info__section-head">
          <span class="info__section-title">基础信息</span>
          <span class="info__section-count">{{ bibleBlocks.length }} 项</span>
        </div>
        <div class="info__props">
          <div v-for="block in bibleBlocks" :key="block.label" class="info__prop">
            <span class="info__prop-label">{{ block.label }}</span>
            <p class="info__prop-text">{{ block.text }}</p>
          </div>
        </div>
      </section>

      <!-- 定位与出版：只展示已生成字段，未生成字段统一在页尾提示 -->
      <section v-if="shownPositioningItems.length" class="info__section">
        <div class="info__section-head">
          <span class="info__section-title">定位与出版</span>
          <span class="info__section-count">{{ shownPositioningItems.length }} 项</span>
        </div>
        <div class="info__props">
          <div v-for="item in shownPositioningItems" :key="item.label" class="info__prop">
            <span class="info__prop-label">{{ item.label }}</span>
            <span v-if="item.value" class="info__prop-value">{{ item.value }}</span>
            <span v-else class="info__tags">
              <span v-for="tag in item.tags" :key="tag" class="info__tag">{{ tag }}</span>
            </span>
          </div>
        </div>
      </section>

      <!-- 开篇设计：离线 chapters.json opening 与 docs 的 opening.* -->
      <section v-if="openingItems.length" class="info__section">
        <div class="info__section-head">
          <span class="info__section-title">开篇设计</span>
          <span class="info__section-count">{{ openingItems.length }} 项</span>
        </div>
        <div class="info__props">
          <div v-for="item in openingItems" :key="item.label" class="info__prop">
            <span class="info__prop-label">{{ item.label }}</span>
            <span class="info__prop-value">{{ item.value }}</span>
          </div>
        </div>
      </section>

      <!-- 作品档案：docs 组0 的工程与合规字段 -->
      <section v-if="archiveItems.length" class="info__section">
        <div class="info__section-head">
          <span class="info__section-title">作品档案</span>
          <span class="info__section-count">{{ archiveItems.length }} 项</span>
        </div>
        <div class="info__props">
          <div v-for="item in archiveItems" :key="item.label" class="info__prop">
            <span class="info__prop-label">{{ item.label }}</span>
            <span class="info__prop-value">{{ item.value }}</span>
          </div>
        </div>
      </section>

      <p v-if="hiddenFieldCount" class="info__hint">
        另有 {{ hiddenFieldCount }} 个字段尚未生成，已自动隐藏
      </p>
    </div>

    <AppDialog :open="deleteCoverOpen" title="删除封面" @close="deleteCoverOpen = false">
      <p class="info__dialog-text">
        删除后封面将被清除且不可恢复，可以重新生成或上传。确定删除当前封面吗？
      </p>
      <div v-if="deleteCoverError" class="alert" role="alert">{{ deleteCoverError }}</div>
      <template #footer>
        <button type="button" class="btn" :disabled="coverDeleting" @click="deleteCoverOpen = false">
          取消
        </button>
        <button type="button" class="btn btn--danger" :disabled="coverDeleting" @click="confirmDeleteCover">
          {{ coverDeleting ? '删除中…' : '确认删除' }}
        </button>
      </template>
    </AppDialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import AppDialog from '@/components/AppDialog.vue'
import GenrePicker from '@/components/GenrePicker.vue'
import TagInput from '@/components/TagInput.vue'
import type { Audience, GenreItem, GenreSelection, RunDetail, RunLength } from '@/types'
import { ApiError } from '@/services/http'
import {
  deleteRunCover,
  fetchGenres,
  fetchRunCover,
  generateRunCover,
  updateRunInfo,
  uploadRunCover,
} from '@/services/agentApi'
import { MODE_LABEL, formatDateTime, relativeTime } from '@/utils/format'

const props = defineProps<{ run: RunDetail }>()
const emit = defineEmits<{ (event: 'updated'): void }>()

const STATUS_OPTIONS = ['连载中', '已签约', '已完结'] as const
type PublishStatus = (typeof STATUS_OPTIONS)[number]

/** 与离线客户端 storyPresets 保持一致的常用预设 */
const THEME_PRESETS = [
  '成长',
  '复仇',
  '逆袭',
  '守护',
  '权谋',
  '救赎',
  '热血',
  '悬疑',
  '群像',
  '打脸',
  '甜宠',
  '虐恋',
  '家国',
  '探索',
  '宿命',
]
const PERSON_PRESETS = ['第一人称', '第三人称限知', '第三人称全知', '双视角交替']
const VOICE_PRESETS = [
  '快节奏爽文',
  '慢热细腻',
  '文艺青年',
  '网络梗幽默',
  '古典半文半白',
  '简洁硬朗',
  '华丽唯美',
  '幽默讽刺',
  '悬念铺垫',
  '电影画面感',
]
const TONE_PRESETS = ['热血', '轻松', '黑暗', '治愈', '悬疑', '虐心', '温馨', '史诗']
const PLATFORM_PRESETS = ['番茄', '起点', '晋江', '七猫', '飞卢', 'QQ阅读', '纵横', '17K']
const AGE_PRESETS = ['学生党', '18-24', '25-34', '35+', '全年龄']
const UPDATE_PRESETS = ['日更', '双更', '三日一更', '周更', '不定期']
const PACE_PRESETS = ['快节奏', '稳节奏', '慢热']
const RATING_PRESETS = ['全年龄', '16+', '18+']

const SELECT_FIELDS: Array<{ key: string; label: string; placeholder: string; presets: string[] }> = [
  { key: 'tone', label: '基调', placeholder: '如 热血 / 黑暗 / 治愈', presets: TONE_PRESETS },
  {
    key: 'target_reader_age',
    label: '读者年龄段',
    placeholder: '如 18-24',
    presets: AGE_PRESETS,
  },
  {
    key: 'update_frequency',
    label: '更新频率',
    placeholder: '如 日更 / 周更',
    presets: UPDATE_PRESETS,
  },
  {
    key: 'serialization_pace',
    label: '连载节奏',
    placeholder: '如 快节奏 / 慢热',
    presets: PACE_PRESETS,
  },
  {
    key: 'content_rating',
    label: '内容分级',
    placeholder: '如 全年龄 / 16+',
    presets: RATING_PRESETS,
  },
]

const MAX_COVER_MB = 10

const status = computed<PublishStatus>(() => {
  const value = props.run.status_label
  return STATUS_OPTIONS.includes(value as PublishStatus) ? (value as PublishStatus) : '连载中'
})
const coverUrl = ref('')
const coverExt = ref('jpg')
const coverBusy = ref(false)
const coverUploading = ref(false)
const coverDeleting = ref(false)
const coverError = ref('')
const coverInput = ref<HTMLInputElement | null>(null)
const deleteCoverOpen = ref(false)
const deleteCoverError = ref('')
const coverHint = computed(() => {
  const meta = props.run.cover
  if (!meta) return '根据作品题材与梗概自动生成封面'
  const source =
    meta.source === 'ai'
      ? `模型 ${meta.model || ''}`.trim()
      : meta.source === 'pollinations'
        ? '免费出图'
        : '本地绘制'
  return `来源：${source}${meta.notice ? `；${meta.notice}` : ''}`
})

let coverObjectUrl = ''
let coverRequest = 0

async function loadCover(path?: string | null): Promise<void> {
  const request = ++coverRequest
  coverError.value = ''
  if (!path) {
    if (coverObjectUrl) {
      URL.revokeObjectURL(coverObjectUrl)
      coverObjectUrl = ''
    }
    coverUrl.value = ''
    return
  }
  try {
    const file = await fetchRunCover(path)
    if (request !== coverRequest) return
    if (coverObjectUrl) URL.revokeObjectURL(coverObjectUrl)
    coverObjectUrl = URL.createObjectURL(file)
    coverUrl.value = coverObjectUrl
  } catch (err) {
    if (request !== coverRequest) return
    coverError.value = err instanceof ApiError ? err.message : '封面加载失败'
  }
}

function openCoverPicker(): void {
  if (coverBusy.value || coverUploading.value || coverDeleting.value) return
  coverInput.value?.click()
}

async function onCoverFileChange(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (!file.type.startsWith('image/')) {
    coverError.value = '请选择 JPG / PNG / WebP 图片'
    return
  }
  if (file.size > MAX_COVER_MB * 1024 * 1024) {
    coverError.value = `封面文件不能超过 ${MAX_COVER_MB}MB`
    return
  }
  coverUploading.value = true
  coverError.value = ''
  try {
    const result = await uploadRunCover(props.run.run_id, file)
    coverExt.value = result.cover?.fmt || 'jpg'
    await loadCover(result.cover_url)
  } catch (err) {
    coverError.value = err instanceof ApiError ? err.message : '封面上传失败，请稍后重试'
  } finally {
    coverUploading.value = false
  }
}

async function onGenerateCover(): Promise<void> {
  if (coverBusy.value || coverUploading.value || coverDeleting.value) return
  coverBusy.value = true
  coverError.value = ''
  try {
    const result = await generateRunCover(props.run.run_id)
    coverExt.value = result.cover?.fmt || 'jpg'
    await loadCover(result.cover_url)
  } catch (err) {
    coverError.value = err instanceof ApiError ? err.message : '封面生成失败，请稍后重试'
  } finally {
    coverBusy.value = false
  }
}

function clearCover(): void {
  coverRequest += 1
  if (coverObjectUrl) {
    URL.revokeObjectURL(coverObjectUrl)
    coverObjectUrl = ''
  }
  coverUrl.value = ''
  coverExt.value = 'jpg'
}

function openDeleteCoverDialog(): void {
  if (!coverUrl.value || coverBusy.value || coverUploading.value || coverDeleting.value) return
  deleteCoverError.value = ''
  deleteCoverOpen.value = true
}

async function confirmDeleteCover(): Promise<void> {
  if (!coverUrl.value || coverDeleting.value) return
  coverDeleting.value = true
  deleteCoverError.value = ''
  try {
    await deleteRunCover(props.run.run_id)
    deleteCoverOpen.value = false
    clearCover()
  } catch (err) {
    deleteCoverError.value = err instanceof ApiError ? err.message : '删除封面失败，请稍后重试'
  } finally {
    coverDeleting.value = false
  }
}

/** 运行中的作品不允许编辑，避免与 worker 抢写 */
const canEdit = computed(
  () => props.run.status !== 'running' && props.run.status !== 'queued',
)

const editing = ref(false)
const saving = ref(false)
const optionalOpen = ref(false)
const formError = ref('')
const errors = reactive({ title: '', genre: '' })
const genres = ref<GenreItem[]>([])
const customAllowed = ref(true)
const genresLoaded = ref(false)

const themeTags = ref<string[]>([])
const sellingTags = ref<string[]>([])
const styleTags = ref<string[]>([])
const platformTags = ref<string[]>([])

const form = reactive<Record<string, any>>({
  title: '',
  author: '',
  status: '连载中' as PublishStatus,
  audience: 'male' as Audience,
  length: 'long' as RunLength,
  genre: { id: null, name: '' } as GenreSelection,
  logline: '',
  synopsis: '',
  person: '',
  world: '',
  conflict: '',
  mainline: '',
  coreHook: '',
  tone: '',
  target_reader_age: '',
  update_frequency: '',
  serialization_pace: '',
  content_rating: '',
})

watch(
  () => form.title,
  (value) => {
    if (value.trim()) errors.title = ''
  },
)
watch(
  () => form.genre.name,
  (value) => {
    if (value.trim()) errors.genre = ''
  },
)
watch(
  () => [errors.title, errors.genre],
  () => {
    if (!errors.title && !errors.genre) formError.value = ''
  },
)

function splitList(value: string): string[] {
  return value
    .split(/[、,，;；\n]/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function toggleTextPreset(field: string, value: string): void {
  form[field] = String(form[field] || '').trim() === value ? '' : value
}

async function ensureGenres(): Promise<void> {
  if (genresLoaded.value) return
  try {
    const data = await fetchGenres()
    genres.value = data.items.slice()
    customAllowed.value = data.custom_allowed
  } catch {
    genres.value = []
    customAllowed.value = true
  } finally {
    if (form.genre.name && !genres.value.some((item) => item.name === form.genre.name)) {
      genres.value.push({
        id: form.genre.id || '',
        name: form.genre.name,
        audience: ['all'],
        tags: [],
      })
    }
    genresLoaded.value = true
  }
}

function startEdit(): void {
  if (!canEdit.value) return
  const outline = props.run.outline || {}
  form.title = props.run.title || ''
  form.author = outline.author || ''
  form.status = status.value
  form.audience = props.run.audience
  form.length = props.run.length
  form.genre = { id: props.run.genre?.id || null, name: props.run.genre?.name || '' }
  form.logline = outline.logline || ''
  form.synopsis = outline.synopsis || ''
  form.person = outline.person || ''
  form.world = outline.world || ''
  form.conflict = outline.conflict || ''
  form.mainline = outline.mainline || ''
  form.coreHook = outline.core_hook || ''
  form.tone = outline.tone || ''
  form.target_reader_age = outline.target_reader_age || ''
  form.update_frequency = outline.update_frequency || ''
  form.serialization_pace = outline.serialization_pace || ''
  form.content_rating = outline.content_rating || ''
  themeTags.value = (outline.themes || []).slice()
  sellingTags.value = (outline.selling_points || []).slice()
  styleTags.value = splitList(outline.style || '')
  platformTags.value = (outline.target_platform || []).slice()
  errors.title = ''
  errors.genre = ''
  formError.value = ''
  optionalOpen.value = false
  editing.value = true
  void ensureGenres()
}

function cancelEdit(): void {
  if (saving.value) return
  editing.value = false
  formError.value = ''
}

async function submitEdit(): Promise<void> {
  if (saving.value) return
  errors.title = form.title.trim() ? '' : '请填写书名'
  errors.genre = form.genre.name.trim() ? '' : '请选择题材'
  if (errors.title || errors.genre) {
    formError.value = '请先完善必填信息'
    return
  }
  saving.value = true
  formError.value = ''
  try {
    await updateRunInfo(props.run.run_id, {
      title: form.title.trim(),
      author: form.author.trim(),
      status_label: form.status,
      audience: form.audience,
      length: form.length,
      genre: { id: form.genre.id, name: form.genre.name.trim() },
      logline: form.logline.trim(),
      synopsis: form.synopsis.trim(),
      themes: themeTags.value,
      person: form.person.trim(),
      style: styleTags.value.join('、'),
      world: form.world.trim(),
      conflict: form.conflict.trim(),
      mainline: form.mainline.trim(),
      selling_points: sellingTags.value,
      core_hook: form.coreHook.trim(),
      tone: form.tone.trim(),
      target_platform: platformTags.value,
      target_reader_age: form.target_reader_age.trim(),
      update_frequency: form.update_frequency.trim(),
      serialization_pace: form.serialization_pace.trim(),
      content_rating: form.content_rating.trim(),
    })
    editing.value = false
    emit('updated')
  } catch (err) {
    formError.value = err instanceof ApiError ? err.message : '保存失败，请稍后重试'
  } finally {
    saving.value = false
  }
}

/** 作者只读回显：AI 生成的作品默认未署名 */
const authorText = computed(() => props.run.outline?.author?.trim() || '未署名')

const coverChar = computed(() => {
  const source = props.run.title?.trim() || ''
  const first = Array.from(source)[0] || '墨'
  return first
})

const audienceText = computed(() => {
  if (props.run.audience === 'male') return '男频'
  if (props.run.audience === 'female') return '女频'
  return '—'
})

const lengthText = computed(() => {
  if (props.run.length === 'long') return '长篇'
  if (props.run.length === 'short') return '短篇'
  return '—'
})

const chapterCount = computed(() => {
  const count = props.run.summary?.chapters_count
  if (count === null || count === undefined) return '—'
  return count.toLocaleString('zh-CN')
})

const totalWords = computed(() => {
  // 服务端 summary.word_count 是正文全量字数；旧数据没有时用章节字数求和
  const summaryWords = props.run.summary?.word_count
  if (typeof summaryWords === 'number' && summaryWords > 0) {
    return `${summaryWords.toLocaleString('zh-CN')} 字`
  }
  const chapters = props.run.chapters
  if (!chapters || !chapters.length) return '—'
  const words = chapters.reduce((sum, chapter) => sum + (chapter.words || 0), 0)
  return words > 0 ? `${words.toLocaleString('zh-CN')} 字` : '—'
})

const characterCount = computed(() => {
  const count = props.run.summary?.characters_count ?? props.run.characters?.length
  if (count === null || count === undefined) return '—'
  return count.toLocaleString('zh-CN')
})

const factionCount = computed(() => {
  const count = props.run.factions?.length
  if (!count) return '—'
  return count.toLocaleString('zh-CN')
})

const itemCount = computed(() => {
  const count = props.run.summary?.items_count ?? props.run.items?.length
  if (count === null || count === undefined) return '—'
  return count.toLocaleString('zh-CN')
})

const segmentsCount = computed(() => {
  const count = props.run.summary?.segments_count
  if (count === null || count === undefined) return '—'
  return count.toLocaleString('zh-CN')
})

const previewChapters = computed(() => {
  const count = props.run.summary?.preview_chapters_count
  if (count === null || count === undefined) return '—'
  return count.toLocaleString('zh-CN')
})

const logline = computed(() => props.run.summary?.logline || props.run.outline?.logline || '')

const themes = computed(() => props.run.outline?.themes || [])

/** 大纲基础信息（story_bible）：有值才展示，长文本占整行 */
const bibleBlocks = computed(() => {
  const outline = props.run.outline || {}
  const blocks: Array<{ label: string; text: string; full: boolean }> = []
  const push = (label: string, text?: string, full = false): void => {
    if (text && text.trim()) blocks.push({ label, text: text.trim(), full })
  }
  push('基调', outline.tone)
  push('叙事人称', outline.person)
  push('文风与语言', outline.style)
  push('作品简介', outline.synopsis, true)
  return blocks
})

/** 未生成的值返回空串，由外层过滤掉，避免页面出现整片「—」 */
function textOf(value?: string | null): string {
  return value && value.trim() ? value.trim() : ''
}

function numOf(value?: number | null): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return ''
  return value.toLocaleString('zh-CN')
}

function tagsOf(values?: string[]): string[] {
  return (values || []).map((item) => (item || '').trim()).filter(Boolean)
}

interface InfoItem {
  label: string
  value: string
  tags?: string[]
}

function hasContent(item: InfoItem): boolean {
  return !!item.value || !!item.tags?.length
}

/** 核心统计条：只保留数量类指标 */
const statItems = computed<InfoItem[]>(() => {
  const items: InfoItem[] = [
    { label: '章节', value: chapterCount.value },
    { label: '总字数', value: totalWords.value },
    { label: '角色', value: characterCount.value },
    { label: '势力', value: factionCount.value },
    { label: '道具', value: itemCount.value },
  ]
  if (props.run.mode === 'reference') {
    items.push({ label: '参考分段', value: segmentsCount.value })
  }
  if (props.run.mode === 'hot') {
    items.push({ label: '预览章数', value: previewChapters.value })
  }
  return items
})

const estimatedWordsText = computed(() => {
  const planned = props.run.outline?.total_chapters_planned
  const perChapter = props.run.outline?.chapter_words_target
  if (
    typeof planned === 'number' &&
    planned > 0 &&
    typeof perChapter === 'number' &&
    perChapter > 0
  ) {
    return (planned * perChapter).toLocaleString('zh-CN')
  }
  return numOf(props.run.outline?.estimated_words)
})

const positioningRaw = computed<InfoItem[]>(() => {
  const outline = props.run.outline || {}
  return [
    { label: '主类型', value: textOf(outline.type_primary) },
    { label: '子类型', value: '', tags: tagsOf(outline.type_secondary) },
    { label: '核心钩子', value: textOf(outline.core_hook) },
    { label: '核心卖点', value: '', tags: tagsOf(outline.selling_points) },
    { label: '目标平台', value: '', tags: tagsOf(outline.target_platform) },
    { label: '读者年龄段', value: textOf(outline.target_reader_age) },
    { label: '预估字数', value: estimatedWordsText.value ? `${estimatedWordsText.value} 字` : '' },
    { label: '计划章数', value: numOf(outline.total_chapters_planned) },
    { label: '单章目标字数', value: numOf(outline.chapter_words_target) },
    { label: '连载节奏', value: textOf(outline.serialization_pace) },
    { label: '更新频率', value: textOf(outline.update_frequency) },
    { label: '内容分级', value: textOf(outline.content_rating) },
    { label: '结局类型', value: textOf(outline.ending_type) },
    { label: '系列化规划', value: textOf(outline.series_plan) },
    { label: '投稿关键词', value: '', tags: tagsOf(outline.keywords) },
    { label: 'AIGC 说明', value: textOf(outline.aigc_disclosure) },
  ]
})

const positioningItems = computed(() => positioningRaw.value.filter(hasContent))
/** 编辑态中已在表单里出现的字段不再重复展示 */
const shownPositioningItems = computed(() =>
  editing.value
    ? positioningItems.value.filter(
        (item) =>
          ![
            '核心钩子',
            '核心卖点',
            '目标平台',
            '读者年龄段',
            '更新频率',
            '连载节奏',
            '内容分级',
          ].includes(item.label),
      )
    : positioningItems.value,
)

const openingRaw = computed<InfoItem[]>(() => {
  const opening = props.run.outline?.opening
  return [
    { label: '开篇策略', value: textOf(opening?.strategy) },
    { label: '第一个画面', value: textOf(opening?.first_image) },
    {
      label: '金手指首演章号',
      value:
        typeof opening?.golden_finger_demo === 'number'
          ? `第 ${opening.golden_finger_demo} 章`
          : '',
    },
  ]
})

const openingItems = computed(() => openingRaw.value.filter(hasContent))

const archiveRaw = computed<InfoItem[]>(() => {
  const outline = props.run.outline || {}
  return [
    { label: '创作模式', value: MODE_LABEL[props.run.mode] },
    { label: '时代背景', value: textOf(outline.era) },
    {
      label: '生成时间',
      value: outline.generated_at ? formatDateTime(outline.generated_at) : '',
    },
    {
      label: '是否 AI 生成',
      value: typeof outline.ai === 'boolean' ? (outline.ai ? '是' : '否') : '',
    },
    { label: '来源类型', value: textOf(outline.source_type) },
    { label: '语言与地区', value: textOf(outline.language) },
    { label: '数据结构版本', value: textOf(outline.schema_version) },
    { label: '版权状态', value: textOf(outline.rights_status) },
  ]
})

const archiveItems = computed(() => archiveRaw.value.filter(hasContent))

const hiddenFieldCount = computed(
  () =>
    positioningRaw.value.length +
    openingRaw.value.length +
    archiveRaw.value.length -
    positioningItems.value.length -
    openingItems.value.length -
    archiveItems.value.length,
)

const latestChapter = computed(() => {
  const chapters = props.run.chapters
  if (!chapters || !chapters.length) return null
  return chapters.reduce((latest, chapter) => (chapter.no > latest.no ? chapter : latest))
})

const latestChapterText = computed(() => {
  const chapter = latestChapter.value
  if (!chapter) return '暂无章节'
  return `第 ${chapter.no} 章 · ${chapter.title || '未命名章节'}`
})

const latestStamp = computed<string | null>(() => {
  const stamps: string[] = []
  // 服务端把最近章节完成时间放在 summary.updated_at
  if (props.run.summary?.updated_at) stamps.push(props.run.summary.updated_at)
  if (props.run.updated_at) stamps.push(props.run.updated_at)
  if (props.run.created_at) stamps.push(props.run.created_at)
  for (const stage of props.run.stages || []) {
    if (stage.finished_at) stamps.push(stage.finished_at)
    if (stage.started_at) stamps.push(stage.started_at)
  }
  const latest = stamps
    .map((iso) => ({ iso, at: new Date(iso).getTime() }))
    .filter((item) => Number.isFinite(item.at))
    .sort((a, b) => b.at - a.at)[0]
  return latest ? latest.iso : null
})

/** 标题右侧只用相对时间，完整时间放 title 提示 */
const updateShortText = computed(() =>
  latestStamp.value ? relativeTime(latestStamp.value) : '—',
)

const updateTimeText = computed(() => {
  const iso = latestStamp.value
  if (!iso) return '—'
  return `${relativeTime(iso)} · ${formatDateTime(iso)}`
})

function onDownloadCover(): void {
  if (!coverUrl.value) return
  const title = (props.run.title || '作品').replace(/[\\/:*?"<>|]/g, '_')
  const anchor = document.createElement('a')
  anchor.href = coverUrl.value
  anchor.download = `${title}-封面.${coverExt.value || 'jpg'}`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
}

onMounted(() => {
  coverExt.value = props.run.cover?.fmt || 'jpg'
  void loadCover(props.run.cover_url)
})

watch(
  () => props.run.cover_url,
  (path) => {
    coverExt.value = props.run.cover?.fmt || 'jpg'
    void loadCover(path)
  },
)

onBeforeUnmount(() => {
  coverRequest += 1
  if (coverObjectUrl) URL.revokeObjectURL(coverObjectUrl)
})
</script>

<style scoped>
.info {
  display: grid;
  grid-template-columns: 188px minmax(0, 1fr);
  grid-template-rows: minmax(0, 1fr);
  gap: 22px;
  padding: var(--space-5);
  height: 100%;
  min-height: 0;
}

/* 封面固定不动，只有右侧信息列滚动 */
.info__cover {
  align-self: start;
  position: sticky;
  top: 0;
  aspect-ratio: 3 / 4;
  border-radius: var(--radius-md);
  overflow: hidden;
  background: linear-gradient(160deg, #0f766e, #134e4a 55%, #0b1a2a);
  display: grid;
  place-items: center;
  color: #d8f3ee;
  box-shadow:
    0 12px 28px rgba(15, 23, 42, 0.16),
    inset 0 0 0 1px rgba(255, 255, 255, 0.12);
}

.info__cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.info__cover-char {
  font-size: 46px;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.info__cover-hint {
  position: absolute;
  bottom: 50px;
  font-size: 14px;
  color: rgba(216, 243, 238, 0.7);
}

.info__cover-icon-group {
  display: flex;
  align-items: center;
  gap: 6px;
}

.info__cover-actions {
  position: absolute;
  left: 10px;
  right: 10px;
  bottom: 10px;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.info__cover-icon {
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: rgba(8, 18, 28, 0.62);
  color: #fff;
  backdrop-filter: blur(8px);
  transition: background var(--dur-fast) var(--ease), transform var(--dur-fast) var(--ease);
}

.info__cover-icon:hover:not(:disabled) {
  background: rgba(13, 148, 136, 0.92);
  transform: translateY(-1px);
}

.info__cover-icon:disabled {
  cursor: wait;
  opacity: 0.8;
}

.info__cover-icon svg {
  width: 16px;
  height: 16px;
}

.info__cover-delete {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 2;
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: rgba(8, 18, 28, 0.62);
  color: #fff;
  backdrop-filter: blur(8px);
  transition: background var(--dur-fast) var(--ease), transform var(--dur-fast) var(--ease);
}

.info__cover-delete:hover:not(:disabled) {
  background: rgba(185, 28, 28, 0.92);
  transform: translateY(-1px);
}

.info__cover-delete:disabled {
  cursor: wait;
  opacity: 0.8;
}

.info__cover-delete svg {
  width: 15px;
  height: 15px;
}

.info__cover-spinner {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  border: 2px solid rgba(255, 255, 255, 0.4);
  border-top-color: #fff;
  animation: cover-spin 0.8s linear infinite;
}

.info__dialog-text {
  color: var(--color-text-2);
  font-size: 14px;
  line-height: 1.7;
}

.info__cover-error {
  position: absolute;
  left: 8px;
  right: 8px;
  top: 44px;
  z-index: 2;
  padding: 5px 8px;
  border-radius: 8px;
  background: rgba(120, 20, 20, 0.86);
  color: #fff;
  font-size: 12px;
  line-height: 1.45;
}

@keyframes cover-spin {
  to {
    transform: rotate(360deg);
  }
}

.info__body {
  display: flex;
  flex-direction: column;
  gap: 18px;
  min-width: 0;
  min-height: 0;
  max-height: 100%;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding-right: 8px;
  scrollbar-width: thin;
}

/* 信息列内部滚动，子项不参与 flex 压缩，避免统计条被挤成 0 高 */
.info__body > * {
  flex: none;
}

.info__body::-webkit-scrollbar {
  width: 8px;
}

.info__body::-webkit-scrollbar-thumb {
  background: #d7dde5;
  border-radius: 8px;
}

/* ---------- 标题与标签 ---------- */
.info__hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.info__hero-main {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}

.info__title {
  margin: 0;
  font-size: 15px;
  line-height: 1.35;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.info__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.info__chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 4px 10px;
  border-radius: var(--radius-pill);
  background: var(--color-bg-soft);
  color: var(--color-text-2);
  font-size: 14px;
  line-height: 1.4;
}

.info__chip--mode {
  background: rgba(13, 148, 136, 0.1);
  color: var(--color-brand);
}

.info__updated {
  flex: none;
  padding-top: 4px;
  font-size: 14px;
  color: var(--color-text-3);
  white-space: nowrap;
}

.info__hero-side {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: none;
}

.info__edit-icon {
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  padding: 0;
  border: none;
  border-radius: 0;
  background: transparent;
  color: var(--color-text-3);
  transition: color var(--dur-fast) var(--ease);
}

.info__edit-icon:hover:not(:disabled) {
  background: transparent;
  color: var(--color-brand);
}

.info__edit-icon:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.info__edit-icon svg {
  width: 16px;
  height: 16px;
}

/* ---------- 编辑表单 ---------- */
.info__form {
  display: flex;
  flex-direction: column;
  gap: 18px;
  max-width: 720px;
  padding-bottom: 8px;
}

.info__form-section {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding-bottom: 18px;
  border-bottom: 1px solid var(--color-line);
}

.info__form-section:last-of-type {
  padding-bottom: 0;
  border-bottom: none;
}

.info__form-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.info__form-title {
  font-size: 15px;
  font-weight: 700;
}

.info__form-hint {
  font-size: 13px;
  color: var(--color-text-3);
}

.info__form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 16px;
}

.info__form-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.info__form-field--full {
  grid-column: 1 / -1;
}

.info__form-label {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-2);
}

.info__form-label i {
  font-style: normal;
  color: var(--color-danger);
}

.info__form-error {
  font-size: 13px;
  color: var(--color-danger);
}

.info__form .input {
  height: 40px;
}

.info__form textarea.input {
  min-height: 88px;
}

.info__choices {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.info__preset-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 2px;
}

.info__preset-list .info__pill {
  height: 28px;
  padding: 0 11px;
  font-size: 13px;
}

button.info__pill {
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease);
}

button.info__pill:hover:not(.is-active) {
  background: var(--color-line);
  color: var(--color-text);
}

.info__optional-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  height: 42px;
  padding: 0 14px;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-md);
  background: var(--color-bg-softer);
  color: var(--color-text-2);
  font-size: 14px;
  font-weight: 600;
}

.info__optional-toggle:hover {
  background: var(--color-bg-soft);
}

.info__optional-caret {
  width: 8px;
  height: 8px;
  border-right: 1.5px solid currentColor;
  border-bottom: 1.5px solid currentColor;
  transform: rotate(45deg);
  transition: transform var(--dur-fast) var(--ease);
}

.info__optional-caret.is-open {
  transform: rotate(-135deg);
}

/* 题材选择与普通输入框保持同一视觉规格 */
.info__form :deep(.genre) {
  width: 100%;
}

.info__form :deep(.genre__trigger) {
  width: 100%;
  height: 40px;
  justify-content: space-between;
  padding: 0 12px;
  border-radius: var(--radius-md);
  border: 1px solid var(--color-line-strong);
  background: var(--color-surface);
  color: var(--color-text);
}

.info__form :deep(.genre__trigger:hover),
.info__form :deep(.genre__trigger.is-active) {
  background: var(--color-surface);
  border-color: var(--color-line-strong);
  color: var(--color-text);
}

.info__form :deep(.genre__label) {
  max-width: none;
}

/* ---------- 作者与状态 ---------- */
.info__row {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 16px;
}

.info__field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 180px;
}

.info__field--status {
  flex: 1;
}

.info__field--author {
  min-width: 140px;
}

.info__author {
  display: flex;
  align-items: center;
  height: 30px;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
}

.info__label {
  font-size: 14px;
  color: var(--color-text-3);
  letter-spacing: 0.04em;
}

.info__status {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.info__pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 30px;
  padding: 0 14px;
  border-radius: var(--radius-pill);
  border: 1px solid transparent;
  background: var(--color-bg-soft);
  color: var(--color-text-2);
  font-size: 14px;
  line-height: 1;
  white-space: nowrap;
}

.info__pill.is-active {
  border-color: var(--color-brand);
  background: rgba(13, 148, 136, 0.12);
  color: var(--color-brand);
  font-weight: 600;
}

/* ---------- 核心统计：单条数据带，不再是一排独立小卡 ---------- */
.info__stats {
  display: flex;
  border-radius: var(--radius-md);
  background: #fff;
  overflow: hidden;
}

.info__stat {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 14px 16px;
}

.info__stat b {
  font-size: 18px;
  line-height: 1.25;
  font-weight: 700;
  color: var(--color-text);
  white-space: nowrap;
}

.info__stat span {
  font-size: 14px;
  color: var(--color-text-3);
}

/* ---------- 梗概与主题 ---------- */
.info__quote {
  margin: 0;
  padding: 14px 16px;
  border-left: 3px solid var(--color-brand);
  border-radius: var(--radius-sm);
  background: rgba(13, 148, 136, 0.06);
}

.info__quote-label {
  display: block;
  margin-bottom: 4px;
  font-size: 14px;
  color: var(--color-brand);
}

.info__quote p {
  margin: 0;
  font-size: var(--text-sm);
  line-height: 1.8;
  color: var(--color-text-2);
}

.info__themes {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.info__theme-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.info__theme {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 4px 10px;
  border-radius: var(--radius-pill);
  background: rgba(13, 148, 136, 0.1);
  color: var(--color-brand);
  font-size: 14px;
  line-height: 1.4;
}

/* ---------- 信息分区 ---------- */
.info__section {
  padding: 16px 18px 18px;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-md);
  background: #fff;
}

.info__section-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--color-line);
}

.info__section-title {
  font-size: var(--text-md);
  font-weight: 700;
  color: var(--color-text);
}

.info__section-count {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 14px;
  color: var(--color-text-3);
}

/* 双列瀑布：字段各自换行，不会因为同行字段长短不一而留出大片空白 */
.info__props {
  columns: 2;
  column-gap: 32px;
  padding-top: 2px;
}

.info__prop {
  break-inside: avoid;
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
  margin-top: 12px;
}

.info__prop-label {
  font-size: 14px;
  color: var(--color-text-3);
  letter-spacing: 0.03em;
}

.info__prop-value {
  font-size: 14px;
  line-height: 1.7;
  font-weight: 500;
  color: var(--color-text);
  overflow-wrap: anywhere;
}

.info__prop-text {
  margin: 0;
  font-size: 14px;
  line-height: 1.75;
  font-weight: 500;
  color: var(--color-text);
  overflow-wrap: anywhere;
}

.info__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.info__tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 3px 9px;
  border-radius: var(--radius-pill);
  background: var(--color-bg-soft);
  color: var(--color-text-2);
  font-size: 14px;
  line-height: 1.4;
}

.info__readonly-note {
  margin: 4px 0 0;
  padding-top: 14px;
  border-top: 1px solid var(--color-line);
  font-size: 13px;
  color: var(--color-text-3);
}

.info__hint {
  margin: 0;
  text-align: center;
  font-size: 14px;
  color: var(--color-text-3);
}

@media (max-width: 760px) {
  /* 窄屏上下排布：封面不再固定，交给外层整列滚动 */
  .info {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: none;
    gap: var(--space-4);
    padding: var(--space-4);
    height: auto;
  }

  .info__cover {
    position: static;
    width: 132px;
  }

  .info__body {
    max-height: none;
    overflow: visible;
    padding-right: 0;
  }

  .info__cover-char {
    font-size: 30px;
  }

  .info__hero {
    flex-direction: column;
    gap: 8px;
  }

  .info__hero-side {
    width: 100%;
    justify-content: space-between;
  }

  .info__form-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .info__form-field--full {
    grid-column: auto;
  }

  .info__title {
    font-size: 15px;
    white-space: normal;
  }

  .info__row {
    gap: var(--space-3);
  }

  .info__field {
    min-width: 0;
    flex: 1 1 160px;
  }

  .info__stats {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .info__props {
    columns: 1;
  }
}
</style>
