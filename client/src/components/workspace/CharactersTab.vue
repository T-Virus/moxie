<template>
  <div class="chars">
    <section class="chars__panel" aria-label="筛选与分页">
      <div class="chars__toolbar">
        <input
          v-model="keyword"
          class="chars__search"
          type="search"
          placeholder="搜索姓名 / 别名"
          aria-label="搜索角色姓名或别名"
          @input="page = 1"
        />
        <button
          type="button"
          class="btn btn--sm btn--brand chars__add"
          :disabled="!canEdit"
          :title="canEdit ? '新增角色' : '运行中的作品暂不可编辑'"
          @click="openCreate"
        >
          + 新增角色
        </button>
        <div class="chars__meta">
          <span class="chars__count">共 <b>{{ filtered.length }}</b> 位</span>
          <div class="chars__pager">
            <button
              type="button"
              class="chars__page-btn"
              :disabled="page <= 1"
              aria-label="上一页"
              @click="page -= 1"
            >
              ‹
            </button>
            <span class="chars__page-info">{{ page }} / {{ pageCount }}</span>
            <button
              type="button"
              class="chars__page-btn"
              :disabled="page >= pageCount"
              aria-label="下一页"
              @click="page += 1"
            >
              ›
            </button>
          </div>
        </div>
      </div>

      <div class="chars__row">
        <span class="chars__row-label">性别</span>
        <div class="chars__chips" role="group" aria-label="按性别筛选">
          <button
            v-for="option in GENDER_FILTERS"
            :key="option.value"
            type="button"
            class="chars__chip"
            :class="{ 'is-active': genderFilter === option.value, 'is-gender': !!option.value }"
            @click="genderFilter = option.value; page = 1"
          >
            <i v-if="option.icon" class="chars__icon" :class="`is-${option.value}`" aria-hidden="true">
              {{ option.icon }}
            </i>
            {{ option.label }}
          </button>
        </div>
      </div>

      <div v-if="tagOptions.length" class="chars__row">
        <span class="chars__row-label">标签</span>
        <div class="chars__chips">
          <button
            v-for="tag in tagOptions"
            :key="tag"
            type="button"
            class="chars__chip"
            :class="{ 'is-active': tagFilter === tag }"
            @click="toggleTag(tag)"
          >
            {{ tag }}
          </button>
        </div>
      </div>
    </section>

    <div v-if="!characters.length" class="chars__empty">
      <p class="empty__title">暂无角色数据</p>
      <p>角色卡信息会随生成进度补齐，稍后刷新即可。</p>
    </div>

    <div v-else-if="!filtered.length" class="chars__empty">
      <p class="empty__title">没有匹配的角色</p>
      <p>试试更换性别 / 标签，或清空搜索关键词。</p>
      <button type="button" class="btn btn--sm chars__reset" @click="resetFilters">清除筛选</button>
    </div>

    <div v-else class="chars__list">
      <div class="chars__grid">
      <article
        v-for="character in paged"
        :key="character.name"
        class="char-card"
        role="button"
        tabindex="0"
        @click="open(character)"
        @keydown.enter.prevent="open(character)"
        @keydown.space.prevent="open(character)"
      >
        <span class="char-card__avatar" :class="`is-${genderKey(character.gender)}`" aria-hidden="true">
          {{ firstChar(character.name) }}
        </span>

        <div class="char-card__main">
          <div class="char-card__title">
            <h3 class="char-card__name">{{ character.name }}</h3>
            <i class="chars__icon" :class="`is-${genderKey(character.gender)}`" :title="genderText(character.gender)">
              {{ genderIcon(character.gender) }}
            </i>
            <span v-if="character.age" class="char-card__age">{{ character.age }} 岁</span>
            <span v-if="character.type" class="char-card__type">{{ character.type }}</span>
            <div class="char-card__actions">
              <button
                type="button"
                class="char-card__action"
                :disabled="!canEdit"
                :title="canEdit ? '编辑角色' : '运行中的作品暂不可编辑'"
                aria-label="编辑角色"
                @click.stop="openEdit(character)"
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
                class="char-card__action char-card__action--danger"
                :disabled="!canEdit"
                :title="canEdit ? '删除角色' : '运行中的作品暂不可编辑'"
                aria-label="删除角色"
                @click.stop="openDelete(character)"
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

          <p v-if="character.alias" class="char-card__alias">别名 · {{ character.alias }}</p>

          <div v-if="characterFacts(character).length" class="char-card__facts">
            <span v-for="fact in characterFacts(character)" :key="fact.label">
              <i>{{ fact.label }}</i>{{ fact.value }}
            </span>
          </div>

          <p v-if="character.description" class="char-card__desc">{{ character.description }}</p>

          <div v-if="cardTags(character).length" class="char-card__tags">
            <span v-for="tag in cardTags(character)" :key="tag" class="char-card__tag">{{ tag }}</span>
          </div>
        </div>
      </article>
      </div>
    </div>

    <Teleport to="body">
      <div
        v-if="selected"
        class="drawer"
        role="dialog"
        aria-modal="true"
        :aria-label="`${selected.name} 角色详情`"
      >
        <div class="drawer__mask" @click="close" />
        <aside class="drawer__panel">
          <header class="drawer__head">
            <div class="drawer__head-main">
              <h2 class="drawer__name">
                {{ selected.name }}
                <i class="chars__icon" :class="`is-${genderKey(selected.gender)}`" :title="genderText(selected.gender)">
                  {{ genderIcon(selected.gender) }}
                </i>
              </h2>
              <p class="drawer__sub">
                <span v-if="selected.alias">{{ selected.alias }}</span>
                <span v-if="selected.type">{{ selected.type }}</span>
                <span v-if="selected.age">{{ selected.age }} 岁</span>
              </p>
            </div>
            <button type="button" class="drawer__close" aria-label="关闭" @click="close">×</button>
          </header>

          <div class="drawer__body">
            <section v-for="section in detailSections" :key="section.title" class="drawer__section">
              <h3 class="drawer__section-title">{{ section.title }}</h3>
              <div v-for="row in section.rows" :key="row.label" class="drawer__row">
                <span class="drawer__label">{{ row.label }}</span>
                <span v-if="row.items?.length" class="drawer__value">
                  <span v-for="item in row.items" :key="item" class="drawer__tag">{{ item }}</span>
                </span>
                <span v-else class="drawer__value">{{ row.text }}</span>
              </div>
            </section>
          </div>
        </aside>
      </div>
    </Teleport>

    <CollectionDialog
      :open="dialogOpen"
      :title="dialogTitle"
      :fields="characterFields"
      :value="dialogValue"
      :saving="saving"
      :error="dialogError"
      @close="dialogOpen = false"
      @save="saveCharacter"
    />

    <AppDialog :open="deleteOpen" title="删除角色" @close="deleteOpen = false">
      <p class="chars__dialog-text">
        删除后该角色将从人物角色列表中移除，且不可恢复。确定删除「{{ deleteTarget?.name }}」吗？
      </p>
      <div v-if="deleteError" class="alert" role="alert">{{ deleteError }}</div>
      <template #footer>
        <button type="button" class="btn" :disabled="deleting" @click="deleteOpen = false">
          取消
        </button>
        <button type="button" class="btn btn--danger" :disabled="deleting" @click="confirmDelete">
          {{ deleting ? '删除中…' : '确认删除' }}
        </button>
      </template>
    </AppDialog>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { usePresets } from '@/composables/usePresets'
import AppDialog from '@/components/AppDialog.vue'
import CollectionDialog from '@/components/CollectionDialog.vue'
import type { CharacterContent, CollectionField, RunDetail } from '@/types'
import { updateRunCollections } from '@/services/agentApi'
import { ApiError } from '@/services/http'

const props = defineProps<{ run: RunDetail }>()
const emit = defineEmits<{ (event: 'updated'): void }>()

const CHARACTER_FIELDS: CollectionField[] = [
  { key: 'name', label: '姓名', required: true, placeholder: '角色姓名' },
  { key: 'alias', label: '别名', placeholder: '如 外号 / 化名' },
  {
    key: 'gender',
    label: '性别',
    type: 'select',
    presetType: 'character_gender',
    presets: ['男', '女', '双性', '无性别', '非二元', '变性', '其他', '未知'],
    placeholder: '选择或输入',
  },
  { key: 'age', label: '年龄', type: 'number', min: 0 },
  {
    key: 'race',
    label: '种族',
    type: 'select',
    presetType: 'character_race',
    presets: [
      '人族',
      '妖族',
      '魔族',
      '灵族',
      '神族',
      '仙族',
      '兽族',
      '鬼族',
      '龙族',
      '巫族',
      '机械族',
      '异族',
      '混血',
      '半妖',
      '半人',
      '精灵',
      '矮人',
      '血族',
      '鲛人',
      '巨人',
      '树人',
      '翼族',
      '修罗',
      '佛门',
      '天族',
      '未知',
    ],
    placeholder: '选择或输入，如 人族 / 妖族',
  },
  { key: 'identity', label: '身份背景', placeholder: '如 照夜司巡夜人' },
  {
    key: 'type',
    label: '剧情功能',
    type: 'select',
    presetType: 'character_role',
    presets: ['主角', '男主', '女主', '配角', '男配', '女配', '反派', '正派', '群像', '工具人', '导师', '挚友', '宿敌', '卧底', '旁观者', '路人'],
    placeholder: '角色在剧情中的功能',
  },
  {
    key: 'camp',
    label: '阵营',
    type: 'select',
    presetType: 'character_camp',
    presets: ['正道', '魔道', '邪道', '正派', '反派', '中立', '亦正亦邪', '隐世', '散修', '朝廷', '江湖', '妖界', '仙门', '佛门', '混沌', '蛮族', '外域', '未知'],
    placeholder: '选择或输入，如 正道 / 中立',
  },
  { key: 'faction', label: '所属势力', placeholder: '势力名称' },
  { key: 'first_chapter', label: '首次登场章号', type: 'number', min: 1 },
  { key: 'personality', label: '性格', type: 'textarea', rows: 2 },
  { key: 'goal', label: '动机目标', type: 'textarea', rows: 2 },
  { key: 'core_desire', label: '核心欲望', placeholder: '最想得到什么' },
  { key: 'core_fear', label: '核心恐惧', placeholder: '最害怕失去什么' },
  { key: 'speech', label: '说话风格', placeholder: '如 简短、冷峻' },
  { key: 'catchwords', label: '口头禅', placeholder: '常用台词' },
  { key: 'appearance', label: '外貌', type: 'textarea', rows: 2 },
  { key: 'backstory', label: '前史', type: 'textarea', rows: 2 },
  { key: 'secret', label: '隐藏秘密', type: 'textarea', rows: 2 },
  { key: 'description', label: '简介', type: 'textarea', rows: 3 },
  { key: 'tags', label: '标签', type: 'tags' },
  { key: 'strengths', label: '优点', type: 'tags' },
  { key: 'flaws', label: '缺点', type: 'tags' },
  { key: 'quirks', label: '怪癖', type: 'tags' },
]

const canEdit = computed(
  () => props.run.status !== 'running' && props.run.status !== 'queued',
)

/** 所属势力从已有势力中选择，也可继续手输 */
const factionOptions = computed(() =>
  (props.run.factions || []).map((item) => item.name).filter(Boolean),
)
const { presetValues } = usePresets(['character_gender', 'character_race', 'character_role', 'character_camp'])
const characterPresetTypes: Record<string, string> = {
  gender: 'character_gender',
  race: 'character_race',
  type: 'character_role',
  camp: 'character_camp',
}
const characterFields = computed<CollectionField[]>(() =>
  CHARACTER_FIELDS.map((field) => {
    if (field.key === 'faction') {
      return { ...field, type: 'select', presets: factionOptions.value, allowCreate: false, placeholder: '只能从已有势力中选择' }
    }
    const t = characterPresetTypes[field.key]
    if (t) return { ...field, presets: presetValues(t, (field.presets as string[]) || []) }
    return field
  }),
)
const dialogOpen = ref(false)
const editingIndex = ref(-1)
const dialogValue = ref<Record<string, any>>({})
const dialogError = ref('')
const saving = ref(false)
const deleteOpen = ref(false)
const deleteTarget = ref<CharacterContent | null>(null)
const deleteError = ref('')
const deleting = ref(false)

const dialogTitle = computed(() => (editingIndex.value >= 0 ? '编辑角色' : '新增角色'))

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function openCreate(): void {
  if (!canEdit.value) return
  const blank: Record<string, any> = {}
  for (const field of CHARACTER_FIELDS) {
    blank[field.key] = field.type === 'tags' ? [] : field.type === 'number' ? undefined : ''
  }
  editingIndex.value = -1
  dialogValue.value = blank
  dialogError.value = ''
  dialogOpen.value = true
}

function openEdit(character: CharacterContent): void {
  if (!canEdit.value) return
  editingIndex.value = characters.value.findIndex((item) => item.name === character.name)
  dialogValue.value = {
    ...clone(character),
    tags: [...(character.tags || [])],
    strengths: [...(character.strengths || [])],
    flaws: [...(character.flaws || [])],
    quirks: [...(character.quirks || [])],
  }
  dialogError.value = ''
  dialogOpen.value = true
}

async function saveCharacter(values: Record<string, any>): Promise<void> {
  if (!canEdit.value) return
  const name = String(values.name || '').trim()
  const duplicated = characters.value.some(
    (item, index) => item.name === name && index !== editingIndex.value,
  )
  if (duplicated) {
    dialogError.value = '角色姓名已存在，请换一个名称'
    return
  }
  saving.value = true
  dialogError.value = ''
  try {
    const list = characters.value.map((item) => clone(item)) as Array<Record<string, any>>
    const merged = {
      ...values,
      name,
      faction_name: values.faction || undefined,
      role: values.identity || values.type || undefined,
    }
    if (editingIndex.value >= 0) {
      list[editingIndex.value] = { ...list[editingIndex.value], ...merged }
    } else {
      list.push({ ...merged, relations: [], members: [] })
    }
    await updateRunCollections(props.run.run_id, {
      characters: list as unknown as CharacterContent[],
    })
    dialogOpen.value = false
    emit('updated')
  } catch (err) {
    dialogError.value = err instanceof ApiError ? err.message : '保存失败，请稍后重试'
  } finally {
    saving.value = false
  }
}

function openDelete(character: CharacterContent): void {
  if (!canEdit.value) return
  deleteTarget.value = character
  deleteError.value = ''
  deleteOpen.value = true
}

async function confirmDelete(): Promise<void> {
  const target = deleteTarget.value
  if (!target || deleting.value) return
  deleting.value = true
  deleteError.value = ''
  try {
    const list = characters.value
      .filter((item) => item.name !== target.name)
      .map((item) => clone(item))
    await updateRunCollections(props.run.run_id, {
      characters: list as unknown as CharacterContent[],
    })
    deleteOpen.value = false
    deleteTarget.value = null
    if (selected.value?.name === target.name) selected.value = null
    emit('updated')
  } catch (err) {
    deleteError.value = err instanceof ApiError ? err.message : '删除失败，请稍后重试'
  } finally {
    deleting.value = false
  }
}


const PAGE_SIZE = 6
const GENDER_FILTERS = [
  { value: '', label: '全部', icon: '' },
  { value: 'male', label: '男', icon: '♂' },
  { value: 'female', label: '女', icon: '♀' },
  { value: 'other', label: '其他', icon: '⚲' },
]

const keyword = ref('')
const genderFilter = ref('')
const tagFilter = ref('')
const page = ref(1)
const selected = ref<CharacterContent | null>(null)

const characters = computed(() => props.run.characters || [])

const tagOptions = computed(() => {
  const counts = new Map<string, number>()
  characters.value.forEach((item) => {
    ;(item.tags || []).forEach((tag) => counts.set(tag, (counts.get(tag) || 0) + 1))
  })
  return Array.from(counts.entries())
    .sort((a, b) => b[1] - a[1])
    .map(([tag]) => tag)
    .slice(0, 12)
})

const filtered = computed(() => {
  const text = keyword.value.trim().toLowerCase()
  return characters.value.filter((item) => {
    if (genderFilter.value && genderKey(item.gender) !== genderFilter.value) return false
    if (tagFilter.value && !(item.tags || []).includes(tagFilter.value)) return false
    if (!text) return true
    return (
      item.name.toLowerCase().includes(text) ||
      (item.alias || '').toLowerCase().includes(text)
    )
  })
})

const pageCount = computed(() => Math.max(1, Math.ceil(filtered.value.length / PAGE_SIZE)))
const paged = computed(() =>
  filtered.value.slice((page.value - 1) * PAGE_SIZE, page.value * PAGE_SIZE),
)

watch([keyword, genderFilter, tagFilter], () => {
  if (page.value > pageCount.value) page.value = pageCount.value
})

const detailSections = computed(() => {
  const c = selected.value
  if (!c) return []
  const sections: Array<{ title: string; rows: Array<{ label: string; text?: string; items?: string[] }> }> = []
  const push = (title: string, rows: Array<{ label: string; text?: string; items?: string[] }>) => {
    const filled = rows.filter((row) => row.items?.length || row.text)
    if (filled.length) sections.push({ title, rows: filled })
  }
  const percent = (value?: number): string | undefined =>
    typeof value === 'number' ? `${Math.round(value * 100)}%` : undefined
  const chapter = (value?: number): string | undefined => (value ? `第 ${value} 章` : undefined)
  const flag = (value?: boolean): string | undefined =>
    value === undefined ? undefined : value ? '公开' : '保密'

  push('基础信息', [
    { label: '姓名', text: c.name },
    { label: '别名', text: c.alias },
    { label: '性别', text: genderText(c.gender) },
    { label: '种族', text: c.race },
    { label: '年龄', text: c.age ? `${c.age} 岁` : undefined },
    { label: '身份背景', text: c.identity || c.role },
    { label: '剧情功能', text: c.type },
    { label: '阵营', text: c.camp },
    { label: '首次登场', text: chapter(c.first_chapter) },
  ])
  push('势力与立场', [
    { label: '势力名称', text: c.faction },
    { label: '势力大类', text: c.faction_category },
    { label: '下属分支', text: c.sub_faction },
    { label: '忠诚度', text: percent(c.loyalty) },
    { label: '对主角态度', text: c.stance },
    { label: '人设倾向', text: c.alignment },
    { label: '加入章节', text: chapter(c.join_chapter) },
    { label: '脱离章节', text: chapter(c.leave_chapter) },
    { label: '退场原因', text: c.exit_reason },
  ])
  push('人物关系', [
    { label: '关系对象', text: c.relation_to },
    { label: '关系类型', text: c.relation_type },
    { label: '关系方向', text: c.relation_direction },
    { label: '关系强度', text: percent(c.relation_strength) },
    { label: '是否公开', text: flag(c.relation_public) },
    { label: '确立章节', text: chapter(c.relation_chapter) },
    { label: '其他关系', items: c.relations },
  ])
  push('性格与动机', [
    { label: '性格', text: c.personality },
    { label: '优点', items: c.strengths },
    { label: '缺点', items: c.flaws },
    { label: '弱点', text: c.weakness },
    { label: '怪癖', items: c.quirks },
    { label: '说话风格', text: c.speech },
    { label: '口头禅', text: c.catchwords },
    { label: '动机目标', text: c.goal },
    { label: '核心欲望', text: c.core_desire },
    { label: '核心恐惧', text: c.core_fear },
  ])
  push('背景与弧光', [
    { label: '外貌', text: c.appearance },
    { label: '前史', text: c.backstory },
    { label: '隐藏秘密', text: c.secret },
    { label: '人物弧光', text: c.arc },
    { label: '弧光类型', text: c.arc_detail?.type },
    { label: '起点状态', text: c.arc_detail?.start_state },
    {
      label: '转折事件',
      items: c.arc_detail?.turning_points?.length ? c.arc_detail.turning_points : undefined,
    },
    { label: '终点状态', text: c.arc_detail?.end_state },
    { label: '最终结局', text: c.arc_detail?.final_fate },
    {
      label: '视角章节',
      text: c.pov_chapters?.length
        ? `第 ${c.pov_chapters.join('、')} 章`
        : undefined,
    },
    { label: '阻碍方式', items: c.obstacle_methods },
    { label: '对白样例', items: c.voice_sample },
  ])
  push('简介', [{ label: '简介', text: c.description }])
  return sections
})

function genderKey(gender?: string): 'male' | 'female' | 'other' {
  if (gender === 'male' || gender === '男') return 'male'
  if (gender === 'female' || gender === '女') return 'female'
  return 'other'
}

function genderIcon(gender?: string): string {
  const key = genderKey(gender)
  return key === 'male' ? '♂' : key === 'female' ? '♀' : '⚲'
}

function genderText(gender?: string): string {
  if (!gender) return '未知'
  if (gender === 'male' || gender === '男') return '男'
  if (gender === 'female' || gender === '女') return '女'
  return gender
}

function firstChar(name: string): string {
  return Array.from(name || '角')[0]
}

function cardTags(character: CharacterContent): string[] {
  const tags = character.tags || []
  if (tags.length) return tags.slice(0, 3)
  return [character.role, character.type, character.faction].filter(Boolean).slice(0, 3) as string[]
}

/** 卡片事实行：只展示有值字段，避免整片「—」 */
function characterFacts(character: CharacterContent): Array<{ label: string; value: string }> {
  return [
    { label: '身份背景', value: character.identity || character.role || '' },
    { label: '种族', value: character.race || '' },
    { label: '势力名称', value: character.faction || '' },
    {
      label: '首现',
      value: character.first_chapter ? `第 ${character.first_chapter} 章` : '',
    },
  ].filter((fact) => fact.value)
}

function toggleTag(tag: string): void {
  tagFilter.value = tagFilter.value === tag ? '' : tag
  page.value = 1
}

function open(character: CharacterContent): void {
  selected.value = character
}

function close(): void {
  selected.value = null
}

function resetFilters(): void {
  keyword.value = ''
  genderFilter.value = ''
  tagFilter.value = ''
  page.value = 1
}
</script>

<style scoped>
.chars {
  padding: var(--space-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  height: 100%;
  min-height: 0;
}

/* 列表区独立滚动，筛选面板固定 */
.chars__list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding-right: 4px;
  scrollbar-width: thin;
}

.chars__list::-webkit-scrollbar {
  width: 8px;
}

.chars__list::-webkit-scrollbar-thumb {
  background: #d7dde5;
  border-radius: 8px;
}

/* ---------- 筛选面板 ---------- */
.chars__panel {
  flex: none;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-md);
  background: #fff;
}

.chars__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.chars__meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-left: auto;
  min-width: 0;
}

.chars__count {
  font-size: 14px;
  color: var(--color-text-3);
  white-space: nowrap;
}

.chars__count b {
  color: var(--color-text);
  font-weight: 600;
}

.chars__pager {
  display: flex;
  align-items: center;
  gap: 4px;
}

.chars__page-btn {
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

.chars__page-btn:hover:not(:disabled) {
  border-color: var(--color-brand);
  color: var(--color-brand);
}

.chars__page-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.chars__page-info {
  font-size: 14px;
  color: var(--color-text-3);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.chars__search {
  flex: none;
  width: 200px;
  height: 30px;
  padding: 0 12px;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-pill);
  background: var(--color-bg-softer);
  font-size: 14px;
  font-family: inherit;
  color: var(--color-text);
}

.chars__search:focus {
  outline: none;
  border-color: var(--color-brand);
  background: #fff;
}

.chars__row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.chars__row-label {
  flex: none;
  width: 32px;
  padding-top: 5px;
  font-size: 14px;
  color: var(--color-text-3);
}

.chars__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
}

.chars__chip {
  height: 26px;
  padding: 0 11px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 1px solid transparent;
  border-radius: var(--radius-pill);
  background: var(--color-bg-soft);
  color: var(--color-text-2);
  font-size: 14px;
  font-family: inherit;
  white-space: nowrap;
}

.chars__chip:hover {
  color: var(--color-brand);
}

.chars__chip.is-active {
  border-color: var(--color-brand);
  background: rgba(13, 148, 136, 0.1);
  color: var(--color-brand);
  font-weight: 600;
}

/* 性别图标：♂ 蓝 / ♀ 粉 / ⚲ 灰 */
.chars__icon {
  font-style: normal;
  font-size: 14px;
  line-height: 1;
}

.chars__icon.is-male {
  color: #3b82f6;
}

.chars__icon.is-female {
  color: #ec4899;
}

.chars__icon.is-other {
  color: #94a3b8;
}

/* ---------- 卡片 ---------- */
.chars__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 12px;
}

.char-card {
  position: relative;
  display: flex;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-md);
  background: #fff;
  cursor: pointer;
  min-width: 0;
  transition: border-color var(--dur-fast) var(--ease), box-shadow var(--dur-fast) var(--ease);
}

.char-card__actions {
  flex: none;
  margin-left: auto;
  display: flex;
  gap: 2px;
  opacity: 0;
  transition: opacity var(--dur-fast) var(--ease);
}

.char-card:hover .char-card__actions,
.char-card:focus-within .char-card__actions {
  opacity: 1;
}

.char-card__action {
  width: 24px;
  height: 24px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  color: var(--color-text-3);
  background: rgba(255, 255, 255, 0.9);
}

.char-card__action:hover:not(:disabled) {
  background: var(--color-bg-soft);
  color: var(--color-brand);
}

.char-card__action--danger:hover:not(:disabled) {
  background: var(--color-danger-soft);
  color: var(--color-danger);
}

.char-card__action:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.char-card__action svg {
  width: 14px;
  height: 14px;
}

.char-card:hover {
  border-color: var(--color-line-strong);
  box-shadow: 0 2px 10px rgba(15, 35, 55, 0.06);
}

.char-card__avatar {
  flex: none;
  width: 40px;
  height: 40px;
  display: grid;
  place-items: center;
  border-radius: 12px;
  font-size: 16px;
  font-weight: 700;
  background: rgba(148, 163, 184, 0.14);
  color: #64748b;
}

.char-card__avatar.is-male {
  background: rgba(59, 130, 246, 0.12);
  color: #2563eb;
}

.char-card__avatar.is-female {
  background: rgba(236, 72, 153, 0.12);
  color: #db2777;
}

.char-card__main {
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.char-card__title {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.char-card__name {
  font-size: var(--text-md);
  font-weight: 700;
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.char-card__age {
  font-size: 14px;
  color: var(--color-text-3);
}

.char-card__type {
  flex: none;
  padding: 1px 8px;
  border-radius: var(--radius-pill);
  background: var(--color-bg-soft);
  font-size: 14px;
  color: var(--color-text-2);
}

.char-card__alias {
  font-size: 14px;
  color: var(--color-text-3);
}

.char-card__facts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px 12px;
  font-size: 14px;
  color: var(--color-text-2);
}

.char-card__facts span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.char-card__facts i {
  font-style: normal;
  color: var(--color-text-3);
  margin-right: 6px;
}

.char-card__desc {
  font-size: var(--text-xs);
  line-height: 1.7;
  color: var(--color-text-2);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.char-card__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.char-card__tag {
  padding: 1px 8px;
  border-radius: var(--radius-pill);
  background: rgba(13, 148, 136, 0.08);
  font-size: 14px;
  color: var(--color-brand);
}

.chars__empty {
  padding: var(--space-8) var(--space-4);
  text-align: center;
  color: var(--color-text-2);
  font-size: var(--text-sm);
}

.chars__empty p + p {
  margin-top: 6px;
  color: var(--color-text-3);
  font-size: var(--text-xs);
}

.chars__reset {
  margin-top: var(--space-3);
}

.chars__dialog-text {
  font-size: var(--text-sm);
  line-height: 1.7;
  color: var(--color-text-2);
}

@media (hover: none) {
  .char-card__actions {
    opacity: 1;
  }
}

/* ---------- 详情抽屉 ---------- */
.drawer {
  position: fixed;
  inset: 0;
  z-index: 60;
}

.drawer__mask {
  position: absolute;
  inset: 0;
  background: rgba(8, 20, 32, 0.38);
}

.drawer__panel {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: min(420px, 94vw);
  display: flex;
  flex-direction: column;
  background: var(--color-bg);
  border-left: 1px solid var(--color-line);
  box-shadow: var(--shadow-lg);
  animation: drawer-in var(--dur) var(--ease);
}

@keyframes drawer-in {
  from {
    transform: translateX(16px);
    opacity: 0;
  }
}

.drawer__head {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 18px 20px 14px;
  border-bottom: 1px solid var(--color-line);
}

.drawer__head-main {
  flex: 1;
  min-width: 0;
}

.drawer__name {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-md);
  font-weight: 700;
  color: var(--color-text);
}

.drawer__sub {
  display: flex;
  flex-wrap: wrap;
  gap: 2px 10px;
  margin-top: 3px;
  font-size: 14px;
  color: var(--color-text-3);
}

.drawer__sub span + span::before {
  content: '·';
  margin-right: 8px;
  color: var(--color-line-strong);
}

.drawer__close {
  flex: none;
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  border-radius: var(--radius-sm);
  color: var(--color-text-3);
  font-size: 17px;
  line-height: 1;
}

.drawer__close:hover {
  background: var(--color-bg-soft);
  color: var(--color-text);
}

.drawer__body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 16px 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.drawer__section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

/* 段落之间只用一条细线分隔，弱化层级 */
.drawer__section + .drawer__section {
  padding-top: 16px;
  border-top: 1px solid var(--color-line);
}

/* 小标题：左侧色条 + 深色字，与字段内容形成层级 */
.drawer__section-title {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0 0 2px;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
}

.drawer__section-title::before {
  content: '';
  width: 3px;
  height: 12px;
  border-radius: 2px;
  background: var(--color-brand);
}

.drawer__row {
  display: grid;
  grid-template-columns: 88px minmax(0, 1fr);
  gap: 12px;
  align-items: start;
  font-size: var(--text-sm);
  line-height: 1.65;
}

.drawer__label {
  color: var(--color-text-3);
  font-size: 14px;
  padding-top: 1px;
  white-space: nowrap;
}

.drawer__value {
  color: var(--color-text);
  overflow-wrap: anywhere;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.drawer__tag {
  padding: 1px 8px;
  border-radius: var(--radius-pill);
  background: var(--color-bg-soft);
  font-size: 14px;
  color: var(--color-text-2);
}

@media (max-width: 640px) {
  .chars {
    padding: var(--space-4);
  }

  .chars__grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .chars__toolbar {
    flex-wrap: wrap;
  }

  .chars__search {
    width: 100%;
  }
}
</style>
