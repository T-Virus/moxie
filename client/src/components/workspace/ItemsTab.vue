<template>
  <div class="items">
    <section class="items__panel" aria-label="筛选与分页">
      <div class="items__toolbar">
        <input
          v-model="keyword"
          class="items__search"
          type="search"
          placeholder="搜索名称 / 持有者 / 势力"
          aria-label="搜索道具功法名称、持有者或势力"
          @input="page = 1"
        />
        <button
          type="button"
          class="btn btn--sm btn--brand items__add"
          :disabled="!canEdit"
          :title="canEdit ? '新增道具功法' : '运行中的作品暂不可编辑'"
          @click="openCreate"
        >
          + 新增道具
        </button>
        <div class="items__meta">
          <span class="items__count">共 <b>{{ filtered.length }}</b> 项</span>
          <div class="items__pager">
            <button
              type="button"
              class="items__page-btn"
              :disabled="page <= 1"
              aria-label="上一页"
              @click="page -= 1"
            >
              ‹
            </button>
            <span class="items__page-info">{{ page }} / {{ pageCount }}</span>
            <button
              type="button"
              class="items__page-btn"
              :disabled="page >= pageCount"
              aria-label="下一页"
              @click="page += 1"
            >
              ›
            </button>
          </div>
        </div>
      </div>

      <div class="items__row">
        <span class="items__row-label">类别</span>
        <div class="items__chips" role="group" aria-label="按类别筛选">
          <button
            v-for="option in categoryFilters"
            :key="option"
            type="button"
            class="items__chip"
            :class="{ 'is-active': categoryFilter === option }"
            @click="categoryFilter = option; page = 1"
          >
            {{ option || '全部' }}
          </button>
        </div>
      </div>

      <div class="items__row">
        <span class="items__row-label">品阶</span>
        <div class="items__chips" role="group" aria-label="按品阶筛选">
          <button
            v-for="option in gradeFilters"
            :key="option"
            type="button"
            class="items__chip"
            :class="{ 'is-active': gradeFilter === option }"
            @click="gradeFilter = option; page = 1"
          >
            {{ option || '全部' }}
          </button>
        </div>
      </div>
    </section>

    <div v-if="!items.length" class="items__empty">
      <p class="empty__title">暂无道具功法数据</p>
      <p>道具功法信息会随生成进度补齐，稍后刷新即可。</p>
    </div>

    <div v-else-if="!filtered.length" class="items__empty">
      <p class="empty__title">没有匹配的道具功法</p>
      <p>试试更换类别 / 品阶，或清空搜索关键词。</p>
      <button type="button" class="btn btn--sm items__reset" @click="resetFilters">清除筛选</button>
    </div>

    <div v-else class="items__list">
      <div class="items__grid">
      <article v-for="item in paged" :key="item.name" class="item-card">
        <header class="item-card__head">
          <div class="item-card__title">
            <h3 class="item-card__name">{{ item.name }}</h3>
            <span v-if="item.grade" class="item-card__grade">{{ item.grade }}</span>
            <span v-if="item.category" class="item-card__cat">{{ item.category }}</span>
          </div>
          <div class="item-card__actions">
            <button
              type="button"
              class="item-card__action"
              :disabled="!canEdit"
              :title="canEdit ? '编辑道具' : '运行中的作品暂不可编辑'"
              aria-label="编辑道具"
              @click="openEdit(item)"
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
              class="item-card__action item-card__action--danger"
              :disabled="!canEdit"
              :title="canEdit ? '删除道具' : '运行中的作品暂不可编辑'"
              aria-label="删除道具"
              @click="openDelete(item)"
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
        </header>

        <div v-if="itemFacts(item).length" class="item-card__facts">
          <span v-for="fact in itemFacts(item)" :key="fact.label">
            <i>{{ fact.label }}</i>{{ fact.value }}
          </span>
        </div>

        <div v-if="item.effect" class="item-card__section">
          <span class="item-card__label">效果</span>
          <p class="item-card__text">{{ item.effect }}</p>
        </div>

        <div v-if="item.cost" class="item-card__section">
          <span class="item-card__label">代价</span>
          <p class="item-card__text">{{ item.cost }}</p>
        </div>

        <div v-if="item.origin" class="item-card__section">
          <span class="item-card__label">来历</span>
          <p class="item-card__text">{{ item.origin }}</p>
        </div>

        <div v-if="item.note" class="item-card__section">
          <span class="item-card__label">数量 / 限制</span>
          <p class="item-card__text">{{ item.note }}</p>
        </div>

        <div v-if="item.description" class="item-card__section">
          <span class="item-card__label">简介</span>
          <p class="item-card__text">{{ item.description }}</p>
        </div>

        <div v-if="item.payoff" class="item-card__section">
          <span class="item-card__label">后期作用</span>
          <p class="item-card__text">{{ item.payoff }}</p>
        </div>
      </article>
      </div>
    </div>

    <CollectionDialog
      :open="dialogOpen"
      :title="dialogTitle"
      :fields="itemFields"
      :value="dialogValue"
      :saving="saving"
      :error="dialogError"
      @close="dialogOpen = false"
      @save="saveItem"
    />

    <AppDialog :open="deleteOpen" title="删除道具功法" @close="deleteOpen = false">
      <p class="items__dialog-text">
        删除后该道具功法将从列表中移除，且不可恢复。确定删除「{{ deleteTarget?.name }}」吗？
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
import type { CollectionField, ItemContent, RunDetail } from '@/types'
import { updateRunCollections } from '@/services/agentApi'
import { ApiError } from '@/services/http'

const props = defineProps<{ run: RunDetail }>()
const emit = defineEmits<{ (event: 'updated'): void }>()

const ITEM_FIELDS: CollectionField[] = [
  { key: 'name', label: '名称', required: true, placeholder: '道具 / 功法名称' },
  {
    key: 'category',
    label: '类别',
    type: 'select',
    presetType: 'item_category',
    presets: ['法宝', '法器', '功法', '丹药', '材料', '信物', '武器', '防具', '符箓', '阵法', '灵宠', '宝物', '秘籍', '灵草', '矿石', '机关', '毒药', '药方', '神兵', '其他'],
    placeholder: '选择或输入',
  },
  {
    key: 'grade',
    label: '品阶',
    type: 'select',
    presetType: 'item_grade',
    presets: ['凡品', '黄阶', '玄阶', '地阶', '天阶', '灵品', '玄品', '地品', '天品', '仙品', '神品', '圣品', '道器', '王品', '帝品', '超品', '禁忌', '未知'],
    placeholder: '选择或输入',
  },
  { key: 'holder', label: '持有者', placeholder: '当前持有者' },
  { key: 'faction', label: '所属势力', placeholder: '势力名称' },
  { key: 'first_chapter', label: '首次出现章号', type: 'number', min: 1 },
  { key: 'effect', label: '效果', type: 'textarea', rows: 2 },
  { key: 'cost', label: '代价', type: 'textarea', rows: 2 },
  { key: 'origin', label: '来历', type: 'textarea', rows: 2 },
  { key: 'note', label: '数量 / 限制', type: 'textarea', rows: 2 },
  { key: 'description', label: '简介', type: 'textarea', rows: 3 },
  { key: 'payoff', label: '后期作用', type: 'textarea', rows: 2 },
]

const canEdit = computed(
  () => props.run.status !== 'running' && props.run.status !== 'queued',
)

/** 持有者与所属势力从已有角色/势力中选择，也可继续手输 */
const characterOptions = computed(() =>
  (props.run.characters || []).map((item) => item.name).filter(Boolean),
)
const factionOptions = computed(() =>
  (props.run.factions || []).map((item) => item.name).filter(Boolean),
)
const { presetValues } = usePresets(['item_category', 'item_grade'])
const itemPresetTypes: Record<string, string> = {
  category: 'item_category',
  grade: 'item_grade',
}
const itemFields = computed<CollectionField[]>(() =>
  ITEM_FIELDS.map((field) => {
    if (field.key === 'holder') {
      return { ...field, type: 'select', presets: characterOptions.value, allowCreate: false, placeholder: '只能从已有角色中选择' }
    }
    if (field.key === 'faction') {
      return { ...field, type: 'select', presets: factionOptions.value, allowCreate: false, placeholder: '只能从已有势力中选择' }
    }
    const t = itemPresetTypes[field.key]
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
const deleteTarget = ref<ItemContent | null>(null)
const deleteError = ref('')
const deleting = ref(false)

const dialogTitle = computed(() => (editingIndex.value >= 0 ? '编辑道具功法' : '新增道具功法'))

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function openCreate(): void {
  if (!canEdit.value) return
  const blank: Record<string, any> = {}
  for (const field of ITEM_FIELDS) {
    blank[field.key] = field.type === 'tags' ? [] : field.type === 'number' ? undefined : ''
  }
  editingIndex.value = -1
  dialogValue.value = blank
  dialogError.value = ''
  dialogOpen.value = true
}

function openEdit(item: ItemContent): void {
  if (!canEdit.value) return
  editingIndex.value = items.value.findIndex((entry) => entry.name === item.name)
  dialogValue.value = clone(item)
  dialogError.value = ''
  dialogOpen.value = true
}

async function saveItem(values: Record<string, any>): Promise<void> {
  if (!canEdit.value) return
  const name = String(values.name || '').trim()
  const duplicated = items.value.some(
    (item, index) => item.name === name && index !== editingIndex.value,
  )
  if (duplicated) {
    dialogError.value = '道具名称已存在，请换一个名称'
    return
  }
  saving.value = true
  dialogError.value = ''
  try {
    const list = items.value.map((item) => clone(item)) as Array<Record<string, any>>
    const merged = { ...values, name }
    if (editingIndex.value >= 0) {
      list[editingIndex.value] = { ...list[editingIndex.value], ...merged }
    } else {
      list.push(merged)
    }
    await updateRunCollections(props.run.run_id, {
      items: list as unknown as ItemContent[],
    })
    dialogOpen.value = false
    emit('updated')
  } catch (err) {
    dialogError.value = err instanceof ApiError ? err.message : '保存失败，请稍后重试'
  } finally {
    saving.value = false
  }
}

function openDelete(item: ItemContent): void {
  if (!canEdit.value) return
  deleteTarget.value = item
  deleteError.value = ''
  deleteOpen.value = true
}

async function confirmDelete(): Promise<void> {
  const target = deleteTarget.value
  if (!target || deleting.value) return
  deleting.value = true
  deleteError.value = ''
  try {
    const list = items.value
      .filter((item) => item.name !== target.name)
      .map((item) => clone(item))
    await updateRunCollections(props.run.run_id, {
      items: list as unknown as ItemContent[],
    })
    deleteOpen.value = false
    deleteTarget.value = null
    emit('updated')
  } catch (err) {
    deleteError.value = err instanceof ApiError ? err.message : '删除失败，请稍后重试'
  } finally {
    deleting.value = false
  }
}

const PAGE_SIZE = 6

const keyword = ref('')
const categoryFilter = ref('')
const gradeFilter = ref('')
const page = ref(1)

const items = computed(() => props.run.items || [])

const categoryFilters = computed(() => {
  const values = Array.from(new Set(items.value.map((item) => item.category).filter(Boolean))) as string[]
  return ['', ...values]
})

const gradeFilters = computed(() => {
  const values = Array.from(new Set(items.value.map((item) => item.grade).filter(Boolean))) as string[]
  return ['', ...values]
})

const filtered = computed(() => {
  const text = keyword.value.trim().toLowerCase()
  return items.value.filter((item) => {
    if (categoryFilter.value && item.category !== categoryFilter.value) return false
    if (gradeFilter.value && item.grade !== gradeFilter.value) return false
    if (!text) return true
    return [item.name, item.holder, item.owner, item.faction, item.effect]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(text))
  })
})

const pageCount = computed(() => Math.max(1, Math.ceil(filtered.value.length / PAGE_SIZE)))
const paged = computed(() =>
  filtered.value.slice((page.value - 1) * PAGE_SIZE, page.value * PAGE_SIZE),
)

watch([keyword, categoryFilter, gradeFilter], () => {
  if (page.value > pageCount.value) page.value = pageCount.value
})

function chapterText(no?: number): string {
  return no ? `第 ${no} 章` : ''
}

function chaptersText(chapters?: number[]): string {
  if (!chapters || !chapters.length) return ''
  return chapters.map((no) => `第 ${no} 章`).join('、')
}

/** 卡片事实行：只保留有值的字段 */
function itemFacts(item: ItemContent): Array<{ label: string; value: string }> {
  return [
    { label: '持有者', value: item.holder || item.owner || '' },
    { label: '所属势力', value: item.faction || '' },
    { label: '首次出现', value: chapterText(item.first_chapter) },
    { label: '出现章节', value: chaptersText(item.chapters) },
  ].filter((fact) => fact.value)
}

function resetFilters(): void {
  keyword.value = ''
  categoryFilter.value = ''
  gradeFilter.value = ''
  page.value = 1
}
</script>

<style scoped>
.items {
  padding: var(--space-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  height: 100%;
  min-height: 0;
}

/* 列表区独立滚动，筛选面板固定 */
.items__list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding-right: 4px;
  scrollbar-width: thin;
}

.items__list::-webkit-scrollbar {
  width: 8px;
}

.items__list::-webkit-scrollbar-thumb {
  background: #d7dde5;
  border-radius: 8px;
}

/* ---------- 筛选面板 ---------- */
.items__panel {
  flex: none;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-md);
  background: #fff;
}

.items__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.items__search {
  flex: none;
  width: 220px;
  height: 30px;
  padding: 0 12px;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-pill);
  background: var(--color-bg-softer);
  font-size: 14px;
  font-family: inherit;
  color: var(--color-text);
}

.items__search:focus {
  outline: none;
  border-color: var(--color-brand);
  background: #fff;
}

.items__meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-left: auto;
}

.items__count {
  font-size: 14px;
  color: var(--color-text-3);
  white-space: nowrap;
}

.items__count b {
  color: var(--color-text);
  font-weight: 600;
}

.items__pager {
  display: flex;
  align-items: center;
  gap: 4px;
}

.items__page-btn {
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

.items__page-btn:hover:not(:disabled) {
  border-color: var(--color-brand);
  color: var(--color-brand);
}

.items__page-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.items__page-info {
  font-size: 14px;
  color: var(--color-text-3);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.items__row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.items__row-label {
  flex: none;
  width: 32px;
  padding-top: 5px;
  font-size: 14px;
  color: var(--color-text-3);
}

.items__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.items__chip {
  height: 26px;
  padding: 0 11px;
  border: 1px solid transparent;
  border-radius: var(--radius-pill);
  background: var(--color-bg-soft);
  color: var(--color-text-2);
  font-size: 14px;
  font-family: inherit;
  white-space: nowrap;
}

.items__chip:hover {
  color: var(--color-brand);
}

.items__chip.is-active {
  border-color: var(--color-brand);
  background: rgba(13, 148, 136, 0.1);
  color: var(--color-brand);
  font-weight: 600;
}

/* ---------- 卡片 ---------- */
.items__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 12px;
}

.item-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px 16px;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-md);
  background: #fff;
  min-width: 0;
}

.item-card__actions {
  flex: none;
  display: flex;
  gap: 2px;
  opacity: 0;
  transition: opacity var(--dur-fast) var(--ease);
}

.item-card:hover .item-card__actions,
.item-card:focus-within .item-card__actions {
  opacity: 1;
}

.item-card__action {
  width: 24px;
  height: 24px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  color: var(--color-text-3);
  background: rgba(255, 255, 255, 0.9);
}

.item-card__action:hover:not(:disabled) {
  background: var(--color-bg-soft);
  color: var(--color-brand);
}

.item-card__action--danger:hover:not(:disabled) {
  background: var(--color-danger-soft);
  color: var(--color-danger);
}

.item-card__action:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.item-card__action svg {
  width: 14px;
  height: 14px;
}

.item-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.item-card__title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.item-card__name {
  font-size: var(--text-md);
  font-weight: 700;
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.item-card__grade {
  flex: none;
  padding: 1px 8px;
  border-radius: var(--radius-pill);
  background: rgba(13, 148, 136, 0.1);
  color: var(--color-brand);
  font-size: 14px;
  font-weight: 600;
}

.item-card__cat {
  flex: none;
  padding: 1px 8px;
  border-radius: var(--radius-pill);
  background: var(--color-bg-soft);
  color: var(--color-text-2);
  font-size: 14px;
}

.item-card__chapter {
  flex: none;
  font-size: 14px;
  color: var(--color-text-3);
}

.item-card__facts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px 12px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--color-bg-softer);
  font-size: 14px;
  color: var(--color-text-2);
}

.item-card__facts span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.item-card__facts i {
  font-style: normal;
  color: var(--color-text-3);
  margin-right: 6px;
}

.item-card__section {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.item-card__label {
  font-size: 14px;
  color: var(--color-text-3);
}

.item-card__text {
  margin: 0;
  font-size: var(--text-xs);
  line-height: 1.7;
  color: var(--color-text-2);
  overflow-wrap: anywhere;
}

.items__empty {
  padding: var(--space-8) var(--space-4);
  text-align: center;
  font-size: var(--text-sm);
  color: var(--color-text-2);
}

.items__empty p + p {
  margin-top: 6px;
  font-size: var(--text-xs);
  color: var(--color-text-3);
}

.items__reset {
  margin-top: var(--space-3);
}

.items__dialog-text {
  font-size: var(--text-sm);
  line-height: 1.7;
  color: var(--color-text-2);
}

@media (hover: none) {
  .item-card__actions {
    opacity: 1;
  }
}

@media (max-width: 640px) {
  .items {
    padding: var(--space-4);
  }

  .items__grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .items__toolbar {
    flex-wrap: wrap;
  }

  .items__search {
    width: 100%;
  }
}
</style>
