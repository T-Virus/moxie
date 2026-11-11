<template>
  <div class="outline-tab">
    <header class="outline-tab__head">
      <h2 class="outline-tab__title">作品大纲</h2>
      <div class="outline-tab__actions">
        <button
          v-if="!editing"
          type="button"
          class="outline-tab__edit"
          :disabled="!canEdit"
          :title="canEdit ? '编辑作品大纲' : '运行中的作品暂不可编辑'"
          aria-label="编辑作品大纲"
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
        <template v-else>
          <button type="button" class="btn btn--sm" :disabled="saving" @click="cancelEdit">
            取消
          </button>
          <button type="button" class="btn btn--sm btn--brand" :disabled="saving" @click="saveEdit">
            {{ saving ? '保存中…' : '保存' }}
          </button>
        </template>
      </div>
    </header>

    <form v-if="editing" class="outline-form" @submit.prevent>
      <section v-for="group in FORM_GROUPS" :key="group.title" class="outline-form__section">
        <h3 class="outline-form__title">{{ group.title }}</h3>
        <div class="outline-form__grid">
          <label
            v-for="field in group.fields"
            :key="field.key"
            class="outline-form__field"
            :class="{ 'outline-form__field--full': field.rows }"
          >
            <span class="outline-form__label">{{ field.label }}</span>
            <ListInput
              v-if="LIST_KEYS.has(field.key)"
              v-model="listValues[field.key]"
              :placeholder="field.key === 'beats' ? '描述一个关键转折' : '输入一条内容'"
              :add-label="field.key === 'beats' ? '添加节拍' : '添加一条'"
              :hint="field.key === 'beats' ? '阶段节拍只需记录关键转折，不是逐章细纲' : ''"
            />
            <div v-else-if="field.key === 'ending_type'" class="outline-form__ending">
              <input
                v-model="form.ending_type"
                class="input"
                placeholder="如 HE 圆满 / BE 悲剧 / 开放式"
              />
              <div class="outline-form__choices" role="group" aria-label="结局类型预设">
                <button
                  v-for="preset in ENDING_PRESETS"
                  :key="preset"
                  type="button"
                  class="outline-form__choice"
                  :class="{ 'is-active': form.ending_type === preset }"
                  @click="form.ending_type = form.ending_type === preset ? '' : preset"
                >
                  {{ preset }}
                </button>
              </div>
            </div>
            <textarea
              v-else-if="field.rows"
              v-model="form[field.key]"
              class="input"
              :rows="field.rows"
            />
            <input v-else v-model="form[field.key]" class="input" />
          </label>
        </div>
      </section>
      <div v-if="formError" class="alert" role="alert">{{ formError }}</div>
    </form>

    <p v-if="editing" class="outline-tab__readonly">以下为结构化生成结果，只读展示</p>

    <!-- 只展示已生成字段；分组编号 + 双列布局，长文本与列表自动占整行 -->
    <section v-for="(group, index) in groups" :key="group.title" class="outline-group">
      <header class="outline-group__head">
        <span class="outline-group__index">{{ String(index + 1).padStart(2, '0') }}</span>
        <h3 class="outline-group__title">{{ group.title }}</h3>
        <span class="outline-group__count">{{ group.blocks.length }} 项</span>
      </header>
      <div class="outline-group__grid">
        <article
          v-for="block in group.blocks"
          :key="block.label"
          class="outline-block"
          :class="{ 'outline-block--wide': block.wide }"
        >
          <span class="outline-block__label">{{ block.label }}</span>
          <ul v-if="block.items && block.items.length" class="outline-block__list">
            <li v-for="(item, i) in block.items" :key="i">{{ item }}</li>
          </ul>
          <p v-else class="outline-block__text">{{ block.text }}</p>
        </article>
      </div>
    </section>

    <div v-if="!groups.length" class="outline-tab__empty">
      <p class="empty__title">暂无大纲内容</p>
      <p>大纲字段尚未返回，可稍后刷新页面重试。</p>
    </div>
    <p v-else-if="hiddenCount" class="outline-tab__hint">
      另有 {{ hiddenCount }} 个字段尚未生成，已自动隐藏
    </p>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import ListInput from '@/components/ListInput.vue'
import type { RunDetail } from '@/types'
import { updateRunInfo, type RunInfoUpdatePayload } from '@/services/agentApi'
import { ApiError } from '@/services/http'

const props = defineProps<{ run: RunDetail }>()
const emit = defineEmits<{ (event: 'updated'): void }>()

interface FormField {
  key: string
  label: string
  rows?: number
}

const FORM_GROUPS: Array<{ title: string; fields: FormField[] }> = [
  {
    title: '故事主线',
    fields: [
      { key: 'mainline', label: '全书主线', rows: 3 },
      { key: 'conflict', label: '核心冲突', rows: 3 },
      { key: 'suspense', label: '核心悬念', rows: 3 },
      { key: 'subplots', label: '支线与情感线', rows: 3 },
    ],
  },
  {
    title: '剧情节拍',
    fields: [{ key: 'beats', label: '阶段节拍（每行一条）', rows: 4 }],
  },
  {
    title: '人物与伏笔',
    fields: [{ key: 'foreshadow_text', label: '伏笔与回收', rows: 3 }],
  },
  {
    title: '世界观设定',
    fields: [
      { key: 'world', label: '世界观与时代背景', rows: 3 },
      { key: 'power', label: '力量体系与金手指', rows: 3 },
      { key: 'places', label: '重要地点', rows: 3 },
      { key: 'items_text', label: '关键道具', rows: 3 },
      { key: 'terms', label: '专有名词表', rows: 3 },
      { key: 'timeline', label: '时间线', rows: 3 },
      { key: 'map_text', label: '地图设定', rows: 3 },
    ],
  },
  {
    title: '卖点与主题',
    fields: [
      { key: 'theme_core', label: '核心主题' },
      { key: 'theme_statement', label: '主题命题' },
      { key: 'ending_type', label: '结局类型' },
      { key: 'selling_points', label: '卖点三句话', rows: 3 },
      { key: 'innovation_points', label: '创新点', rows: 3 },
      { key: 'ending_state', label: '结局后的世界', rows: 3 },
      { key: 'protagonist_final_fate', label: '主角最终命运', rows: 3 },
      { key: 'comparative_titles', label: '对标作品', rows: 3 },
    ],
  },
  {
    title: '创作约束',
    fields: [{ key: 'taboos', label: '写作禁忌与铁律', rows: 3 }],
  },
]

const LIST_KEYS = new Set(['beats', 'selling_points', 'innovation_points', 'comparative_titles'])
const ENDING_PRESETS = ['HE 圆满', 'BE 悲剧', '开放式', '反转结局', '双结局']
const EDITABLE_LABELS = new Set([
  '全书主线',
  '核心冲突',
  '核心悬念',
  '支线与情感线',
  '阶段节拍',
  '伏笔与回收',
  '世界观与时代背景',
  '力量体系与金手指',
  '重要地点',
  '关键道具（文本）',
  '专有名词表',
  '时间线',
  '地图设定',
  '核心主题',
  '主题命题',
  '卖点三句话',
  '创新点',
  '结局类型',
  '结局后的世界',
  '主角最终命运',
  '对标作品',
  '写作禁忌与铁律',
])

const editing = ref(false)
const saving = ref(false)
const formError = ref('')
const canEdit = computed(
  () => props.run.status !== 'running' && props.run.status !== 'queued',
)
const form = reactive<Record<string, string>>({})
for (const group of FORM_GROUPS) {
  for (const field of group.fields) form[field.key] = ''
}
const listValues = reactive<Record<string, string[]>>({
  beats: [],
  selling_points: [],
  innovation_points: [],
  comparative_titles: [],
})

function startEdit(): void {
  if (!canEdit.value) return
  const outline = (props.run.outline || {}) as Record<string, unknown>
  for (const group of FORM_GROUPS) {
    for (const field of group.fields) {
      const value = outline[field.key]
      form[field.key] = Array.isArray(value)
        ? value.map((item) => String(item)).join('\n')
        : value === null || value === undefined
          ? ''
          : String(value)
    }
  }
  for (const key of LIST_KEYS) {
    const value = outline[key]
    listValues[key] = Array.isArray(value) ? value.map((item) => String(item)) : []
  }
  formError.value = ''
  editing.value = true
}

function cancelEdit(): void {
  if (saving.value) return
  editing.value = false
  formError.value = ''
}

async function saveEdit(): Promise<void> {
  if (saving.value) return
  saving.value = true
  formError.value = ''
  try {
    const payload: Record<string, unknown> = {}
    for (const group of FORM_GROUPS) {
      for (const field of group.fields) {
        if (LIST_KEYS.has(field.key)) {
          payload[field.key] = listValues[field.key]
            .map((item) => item.trim())
            .filter(Boolean)
          continue
        }
        payload[field.key] = form[field.key].trim()
      }
    }
    await updateRunInfo(props.run.run_id, payload as RunInfoUpdatePayload)
    editing.value = false
    emit('updated')
  } catch (err) {
    formError.value = err instanceof ApiError ? err.message : '保存失败，请稍后重试'
  } finally {
    saving.value = false
  }
}

interface OutlineBlock {
  label: string
  text?: string
  items?: string[]
  wide?: boolean
}

interface OutlineGroup {
  title: string
  blocks: OutlineBlock[]
}

/**
 * 分组回显大纲字段。作品信息页已展示：题材与基调 / 叙事人称 / 文风与语言 / 作品简介 /
 * 一句话梗概 / 主题标签 / 基础信息（频道、篇幅、题材、写作模式、字数章节统计等），此处不重复。
 * 空字段不渲染，避免整页都是「—」。
 */
const view = computed<{ groups: OutlineGroup[]; hidden: number }>(() => {
  const outline = props.run.outline || {}
  const groups: OutlineGroup[] = []
  let hidden = 0

  const cleanItems = (items?: string[]): string[] =>
    (items || []).map((item) => (item || '').trim()).filter(Boolean)

  const add = (title: string, blocks: OutlineBlock[]): void => {
    const filled: OutlineBlock[] = []
    for (const block of blocks) {
      if (editing.value && EDITABLE_LABELS.has(block.label)) continue
      const items = cleanItems(block.items)
      const text = (block.text || '').trim()
      if (!items.length && !text) {
        hidden += 1
        continue
      }
      filled.push({
        label: block.label,
        text: text || undefined,
        items: items.length ? items : undefined,
        wide: text.length > 60 || items.length > 2,
      })
    }
    if (filled.length) groups.push({ title, blocks: filled })
  }

  add('故事主线', [
    { label: '全书主线', text: outline.mainline },
    { label: '核心冲突', text: outline.conflict },
    { label: '核心悬念', text: outline.suspense },
    { label: '支线与情感线', text: outline.subplots },
    { label: '剧情时间轴', items: outline.plot?.timeline },
    { label: '主线节点', items: outline.plot?.mainline },
    { label: '支线清单', items: outline.plot?.subplots },
    { label: '冲突清单', items: outline.plot?.conflict },
    { label: '悬念清单', items: outline.plot?.suspense },
    { label: '伏笔清单', items: outline.plot?.foreshadow },
  ])
  add('剧情节拍', [{ label: '阶段节拍', items: outline.beats }])
  add('人物与伏笔', [
    { label: '主角设定', text: outline.protagonist },
    { label: '主要配角', text: outline.supporting },
    { label: '主要反派', text: outline.antagonist },
    { label: '伏笔与回收', text: outline.foreshadow_text },
  ])
  add('世界观设定', [
    { label: '世界观与时代背景', text: outline.world },
    { label: '力量体系与金手指', text: outline.power },
    { label: '重要地点', text: outline.places },
    { label: '关键道具（文本）', text: outline.items_text },
    { label: '专有名词表', text: outline.terms },
    { label: '时间线', text: outline.timeline },
    { label: '地图设定', text: outline.map_text },
  ])
  add('卖点与主题', [
    { label: '核心主题', text: outline.theme_core },
    { label: '主题命题', text: outline.theme_statement },
    { label: '卖点三句话', items: outline.selling_points },
    { label: '创新点', items: outline.innovation_points },
    { label: '结局类型', text: outline.ending_type },
    { label: '结局后的世界', text: outline.ending_state },
    { label: '主角最终命运', text: outline.protagonist_final_fate },
    { label: '对标作品', items: outline.comparative_titles },
  ])
  add('创作约束', [{ label: '写作禁忌与铁律', text: outline.taboos }])

  // 以下为离线 storymap / docs 组2/4/5/7 的结构化字段：同样只展示有值项
  if (outline && Object.keys(outline).length) {
    const worldviewItems =
      outline.worldview
        ?.map((group) => {
          const points = group.points
            ?.map((point) => {
              const chapters = point.chapters?.length
                ? `（第 ${point.chapters.join('、')} 章）`
                : ''
              return `${point.text || ''}${chapters}`
            })
            .filter(Boolean)
            .join('；')
          return [group.group || '', points || ''].filter(Boolean).join('：')
        })
        .filter(Boolean) || []
    const regionItems =
      outline.map_regions
        ?.map((region) => {
          const kind = region.kind ? `〔${region.kind}〕` : ''
          const chapters = region.chapters?.length
            ? `（第 ${region.chapters.join('、')} 章）`
            : ''
          return `${region.name || ''}${kind}${region.parent ? ` · 上级 ${region.parent}` : ''}${region.desc ? ` · ${region.desc}` : ''}${chapters}`
        })
        .filter(Boolean) || []
    const sceneItems =
      outline.map_scenes
        ?.map((scene) => {
          const parts = [
            scene.chapter ? `第 ${scene.chapter} 章` : '',
            scene.region || '',
            scene.event || '',
            scene.characters?.length ? `角色：${scene.characters.join('、')}` : '',
            scene.factions?.length ? `势力：${scene.factions.join('、')}` : '',
            scene.items?.length ? `道具：${scene.items.join('、')}` : '',
          ].filter(Boolean)
          return parts.join(' · ')
        })
        .filter(Boolean) || []
    const volumeItems =
      outline.volumes
        ?.map((volume) => {
          const range =
            volume.chapter_from || volume.chapter_to
              ? `第 ${volume.chapter_from ?? ''}–${volume.chapter_to ?? ''} 章`
              : ''
          const extra = [
            volume.theme ? `主题：${volume.theme}` : '',
            volume.core_event ? `核心事件：${volume.core_event}` : '',
            volume.summary ? `概括：${volume.summary}` : '',
          ].filter(Boolean)
          return [
            volume.no ? `第 ${volume.no} 卷` : '',
            volume.title || '',
            range,
            extra.join(' · '),
          ]
            .filter(Boolean)
            .join(' · ')
        })
        .filter(Boolean) || []
    const emotionItems =
      outline.emotion_curve
        ?.map((point) => {
          const parts = [
            point.chapter ? `第 ${point.chapter} 章` : '',
            point.emotion || '',
            typeof point.tension === 'number' ? `张力 ${point.tension}` : '',
            point.hook ? `钩子：${point.hook}` : '',
          ].filter(Boolean)
          return parts.join(' · ')
        })
        .filter(Boolean) || []
    const timeItems =
      outline.time_events
        ?.map((event) => {
          const chapter = event.is_volume
            ? `卷节点${event.chapter ? ` ${event.chapter}` : ''}`
            : event.chapter
              ? `第 ${event.chapter} 章`
              : ''
          return [chapter, event.text || ''].filter(Boolean).join(' · ')
        })
        .filter(Boolean) || []
    const indexItems = (entries?: typeof outline.hooks): string[] =>
      entries
        ?.map((entry) => {
          const chapter = entry.chapter ? `第 ${entry.chapter} 章` : ''
          const type = entry.type ? `（${entry.type}）` : ''
          return `${[chapter, entry.text || ''].filter(Boolean).join(' · ')}${type}`
        })
        .filter(Boolean) || []
    const foreshadowItems =
      outline.foreshadows
        ?.map((item) => {
          const parts = [
            item.chapter ? `第 ${item.chapter} 章` : '',
            item.text || '',
            item.seed ? `埋设：${item.seed}` : '',
            item.payoff ? `兑现：${item.payoff}` : '',
            item.status ? `状态：${item.status}` : '',
          ].filter(Boolean)
          return parts.join(' · ')
        })
        .filter(Boolean) || []
    const itemLinkItems =
      outline.item_links
        ?.map((link) => {
          const chapter = link.chapter ? `第 ${link.chapter} 章 · ` : ''
          const flow =
            link.from || link.to ? `${link.from || ''} → ${link.to || ''}` : ''
          return `${chapter}${link.item || ''}${flow ? `：${flow}` : ''}${link.note ? `（${link.note}）` : ''}`
        })
        .filter(Boolean) || []

    add('规则分组与地图', [
      { label: '规则分组', items: worldviewItems },
      { label: '地图层级', items: outline.map_levels },
      { label: '区域结构', items: regionItems },
      { label: '章节场景映射', items: sceneItems },
    ])
    add('卷章节奏与索引', [
      { label: '卷划分', items: volumeItems },
      { label: '情绪与张力曲线', items: emotionItems },
      { label: '时间轴事件', items: timeItems },
      { label: '钩子索引', items: indexItems(outline.hooks) },
      { label: '铺垫索引', items: indexItems(outline.setups) },
      { label: '兑现索引', items: indexItems(outline.payoffs) },
      { label: '连续性冲突', items: indexItems(outline.conflicts) },
      { label: '伏笔台账', items: foreshadowItems },
      { label: '道具流向', items: itemLinkItems },
    ])

    const signing = outline.signing_check
    const signingParts: string[] = []
    if (typeof signing?.score === 'number') signingParts.push(`${signing.score} 分`)
    if (signing?.risk) signingParts.push(`风险 ${signing.risk}`)
    add('签约体检', [
      { label: '体检结果', text: signingParts.join(' · ') },
      { label: '问题清单', items: signing?.issues },
      { label: '改写建议', items: signing?.suggestions },
    ])

    add('完整性校验', [
      {
        label: '大纲完整度评分',
        text:
          typeof outline.qa_score === 'number'
            ? `${outline.qa_score.toLocaleString('zh-CN')} 分`
            : undefined,
      },
      { label: '缺失字段', items: outline.completeness_check?.missing_fields },
      { label: '未填兑现章节', items: outline.completeness_check?.unfilled_payoff },
      { label: '未回收伏笔', items: outline.completeness_check?.unrecovered },
      { label: '缺人物弧光', items: outline.completeness_check?.arc_missing },
      { label: '无钩子章节', items: outline.completeness_check?.no_hook },
    ])
  }

  return { groups, hidden }
})

const groups = computed(() => view.value.groups)
const hiddenCount = computed(() => view.value.hidden)
</script>

<style scoped>
.outline-tab {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: var(--space-5);
}

.outline-tab__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.outline-tab__title {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
}

.outline-tab__actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.outline-tab__edit {
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

.outline-tab__edit:hover:not(:disabled) {
  color: var(--color-brand);
}

.outline-tab__edit:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.outline-tab__edit svg {
  width: 16px;
  height: 16px;
}

.outline-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.outline-form__section {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px 18px;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-md);
  background: #fff;
}

.outline-form__title {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
}

.outline-form__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 18px;
}

.outline-form__field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.outline-form__field--full {
  grid-column: 1 / -1;
}

.outline-form__label {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-2);
}

.outline-form__ending {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.outline-form__choices {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.outline-form__choice {
  height: 28px;
  padding: 0 11px;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-pill);
  background: var(--color-bg-soft);
  color: var(--color-text-2);
  font-size: 13px;
}

.outline-form__choice:hover:not(.is-active) {
  border-color: var(--color-line-strong);
  color: var(--color-text);
}

.outline-form__choice.is-active {
  border-color: var(--color-brand);
  background: rgba(13, 148, 136, 0.12);
  color: var(--color-brand);
  font-weight: 600;
}

.outline-form textarea.input {
  min-height: 72px;
}

.outline-tab__readonly {
  margin: 0;
  padding-top: 12px;
  border-top: 1px solid var(--color-line);
  font-size: 13px;
  color: var(--color-text-3);
}

/* 分组：编号 + 标题 + 字段数，内容用双列网格，短字段并排 */
.outline-group {
  padding: 16px 18px 18px;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-md);
  background: #fff;
}

.outline-group__head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}

.outline-group__index {
  flex: none;
  padding: 2px 6px;
  border-radius: 6px;
  background: rgba(13, 148, 136, 0.1);
  color: var(--color-brand);
  font-family: var(--font-mono);
  font-size: 14px;
  font-weight: 600;
  line-height: 1.4;
}

.outline-group__title {
  margin: 0;
  font-size: var(--text-md);
  font-weight: 700;
  color: var(--color-text);
}

.outline-group__count {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 14px;
  color: var(--color-text-3);
}

.outline-group__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 22px;
}

.outline-block {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
}

.outline-block--wide {
  grid-column: 1 / -1;
}

.outline-block__label {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-3);
  letter-spacing: 0.04em;
}

.outline-block__text {
  margin: 0;
  font-size: var(--text-sm);
  line-height: 1.8;
  color: var(--color-text-2);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.outline-block__list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.outline-block__list li {
  position: relative;
  padding-left: 14px;
  font-size: var(--text-sm);
  line-height: 1.75;
  color: var(--color-text-2);
  overflow-wrap: anywhere;
}

.outline-block__list li::before {
  content: '';
  position: absolute;
  top: 0.68em;
  left: 2px;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--color-brand);
  opacity: 0.45;
}

.outline-tab__empty {
  padding: var(--space-8) var(--space-5);
  text-align: center;
  color: var(--color-text-3);
  font-size: var(--text-sm);
}

.outline-tab__hint {
  margin: 0;
  text-align: center;
  font-size: 14px;
  color: var(--color-text-3);
}

@media (max-width: 760px) {
  .outline-tab {
    padding: var(--space-4);
  }

  .outline-group {
    padding: 14px;
  }

  .outline-group__grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .outline-form__grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .outline-form__field--full {
    grid-column: auto;
  }
}
</style>
