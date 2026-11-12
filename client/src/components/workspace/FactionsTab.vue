<template>
  <div class="factions">
    <section class="factions__panel" aria-label="筛选与分页">
      <div class="factions__toolbar">
        <input
          v-model="keyword"
          class="factions__search"
          type="search"
          placeholder="搜索势力 / 首领 / 地盘"
          aria-label="搜索势力、首领或地盘"
          @input="page = 1"
        />
        <button
          type="button"
          class="btn btn--sm btn--brand factions__add"
          :disabled="!canEdit"
          :title="canEdit ? '新增势力' : '运行中的作品暂不可编辑'"
          @click="openCreate"
        >
          + 新增势力
        </button>
        <div class="factions__meta">
          <span class="factions__count">共 <b>{{ filtered.length }}</b> 个</span>
          <div class="factions__pager">
            <button
              type="button"
              class="factions__page-btn"
              :disabled="page <= 1"
              aria-label="上一页"
              @click="page -= 1"
            >
              ‹
            </button>
            <span class="factions__page-info">{{ page }} / {{ pageCount }}</span>
            <button
              type="button"
              class="factions__page-btn"
              :disabled="page >= pageCount"
              aria-label="下一页"
              @click="page += 1"
            >
              ›
            </button>
          </div>
        </div>
      </div>

      <div class="factions__row">
        <span class="factions__row-label">立场</span>
        <div class="factions__chips" role="group" aria-label="按立场筛选">
          <button
            v-for="option in stanceFilters"
            :key="option"
            type="button"
            class="factions__chip"
            :class="{ 'is-active': stanceFilter === option }"
            @click="stanceFilter = option; page = 1"
          >
            {{ option || '全部' }}
          </button>
        </div>
      </div>
    </section>

    <div v-if="!factions.length" class="factions__empty">
      <p class="empty__title">暂无势力数据</p>
      <p>势力信息会随生成进度补齐，稍后刷新即可。</p>
    </div>

    <div v-else-if="!filtered.length" class="factions__empty">
      <p class="empty__title">没有匹配的势力</p>
      <p>试试更换立场，或清空搜索关键词。</p>
      <button type="button" class="btn btn--sm factions__reset" @click="resetFilters">清除筛选</button>
    </div>

    <template v-else>
      <div class="factions__list">
      <div class="factions__table-wrap">
        <table class="factions__table">
          <colgroup>
            <col style="width: 19%" />
            <col style="width: 12%" />
            <col style="width: 9%" />
            <col style="width: 11%" />
            <col style="width: 13%" />
            <col style="width: 17%" />
            <col style="width: 8%" />
            <col style="width: 9%" />
            <col style="width: 64px" />
            <col style="width: 75px" />
          </colgroup>
          <thead>
            <tr>
              <th>势力名称</th>
              <th>势力大类</th>
              <th>类型</th>
              <th>首领</th>
              <th>立场</th>
              <th>地盘</th>
              <th class="factions__center">成员数</th>
              <th class="factions__center">首次登场</th>
              <th class="factions__center">详情</th>
              <th class="factions__center">操作</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="faction in paged" :key="faction.name">
              <tr>
                <td>
                  <span class="factions__name">{{ faction.name }}</span>
                </td>
                <td>{{ faction.category || '' }}</td>
                <td>{{ faction.type || '' }}</td>
                <td>{{ faction.leader || '' }}</td>
                <td>
                  <span v-if="faction.stance" class="badge" :class="stanceTone(faction.stance)">{{ faction.stance }}</span>
                </td>
                <td :title="faction.territory || ''">{{ faction.territory || '' }}</td>
                <td class="factions__center">{{ membersCount(faction) }}</td>
                <td class="factions__center">{{ firstChapter(faction) }}</td>
                <td class="factions__center">
                  <button
                    type="button"
                    class="factions__toggle"
                    :aria-expanded="isOpen(faction.name)"
                    @click="toggle(faction.name)"
                  >
                    {{ isOpen(faction.name) ? '收起' : '展开' }}
                  </button>
                </td>
                <td class="factions__center">
                  <div class="factions__acts">
                    <button
                      type="button"
                      class="factions__act"
                      :disabled="!canEdit"
                      :title="canEdit ? '编辑势力' : '运行中的作品暂不可编辑'"
                      aria-label="编辑势力"
                      @click="openEdit(faction)"
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
                      class="factions__act factions__act--danger"
                      :disabled="!canEdit"
                      :title="canEdit ? '删除势力' : '运行中的作品暂不可编辑'"
                      aria-label="删除势力"
                      @click="openDelete(faction)"
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
                </td>
              </tr>
              <tr v-if="isOpen(faction.name)" class="factions__detail-row">
                <td colspan="10">
                  <div class="factions__detail">
                    <div v-if="factionFacts(faction).length" class="factions__fields">
                      <span v-for="fact in factionFacts(faction)" :key="fact.label">
                        <i>{{ fact.label }}</i>{{ fact.value }}
                      </span>
                    </div>

                    <div v-if="faction.relations?.length" class="factions__block">
                      <span class="factions__block-label">其他势力关系</span>
                      <div class="factions__tags">
                        <span v-for="relation in faction.relations" :key="relation" class="factions__tag">
                          {{ relation }}
                        </span>
                      </div>
                    </div>

                    <div v-if="faction.description" class="factions__block">
                      <span class="factions__block-label">势力简介</span>
                      <p class="factions__desc">{{ faction.description }}</p>
                    </div>

                    <div class="factions__block">
                      <span class="factions__block-label">成员明细</span>
                      <div v-if="faction.members?.length" class="factions__members">
                        <span v-for="member in faction.members" :key="member.name" class="factions__member">
                          <b>{{ member.name }}</b>
                          <span v-if="member.role">{{ member.role }}</span>
                          <i v-if="member.relation">{{ member.relation }}</i>
                        </span>
                      </div>
                      <p v-else class="factions__none">暂无成员明细</p>
                    </div>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>

      <div class="factions__cards">
        <article v-for="faction in paged" :key="faction.name" class="faction-card">
          <header class="faction-card__head">
            <h3>{{ faction.name }}</h3>
            <span v-if="faction.stance" class="badge" :class="stanceTone(faction.stance)">{{ faction.stance }}</span>
            <div class="factions__acts">
              <button
                type="button"
                class="factions__act"
                :disabled="!canEdit"
                aria-label="编辑势力"
                title="编辑势力"
                @click="openEdit(faction)"
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
                class="factions__act factions__act--danger"
                :disabled="!canEdit"
                aria-label="删除势力"
                title="删除势力"
                @click="openDelete(faction)"
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
          <div v-if="factionFacts(faction).length" class="faction-card__facts">
            <span v-for="fact in factionFacts(faction)" :key="fact.label">
              <i>{{ fact.label }}</i>{{ fact.value }}
            </span>
          </div>
          <p v-if="faction.description" class="faction-card__desc">{{ faction.description }}</p>
          <div v-if="faction.relations?.length" class="factions__tags">
            <span v-for="relation in faction.relations" :key="relation" class="factions__tag">{{ relation }}</span>
          </div>
          <button
            type="button"
            class="btn btn--ghost btn--sm"
            :aria-expanded="isOpen(faction.name)"
            @click="toggle(faction.name)"
          >
            {{ isOpen(faction.name) ? '收起成员' : '查看成员' }}
          </button>
          <div v-if="isOpen(faction.name) && faction.members?.length" class="factions__members">
            <span v-for="member in faction.members" :key="member.name" class="factions__member">
              <b>{{ member.name }}</b>
              <span v-if="member.role">{{ member.role }}</span>
              <i v-if="member.relation">{{ member.relation }}</i>
            </span>
          </div>
        </article>
      </div>
      </div>
    </template>

    <CollectionDialog
      :open="dialogOpen"
      :title="dialogTitle"
      :fields="factionFields"
      :value="dialogValue"
      :saving="saving"
      :error="dialogError"
      @close="dialogOpen = false"
      @save="saveFaction"
    />

    <AppDialog :open="deleteOpen" title="删除势力" @close="deleteOpen = false">
      <p class="factions__dialog-text">
        删除后该势力将从势力阵营列表中移除，且不可恢复。确定删除「{{ deleteTarget?.name }}」吗？
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
import AppDialog from '@/components/AppDialog.vue'
import CollectionDialog from '@/components/CollectionDialog.vue'
import type { CollectionField, FactionContent, RunDetail } from '@/types'
import { updateRunCollections } from '@/services/agentApi'
import { ApiError } from '@/services/http'

const props = defineProps<{ run: RunDetail }>()
const emit = defineEmits<{ (event: 'updated'): void }>()

const FACTION_FIELDS: CollectionField[] = [
  { key: 'name', label: '势力名称', required: true, placeholder: '势力名称' },
  { key: 'category', label: '势力大类', placeholder: '如 宗门 / 家族 / 商会' },
  {
    key: 'type',
    label: '类型',
    type: 'select',
    presets: ['宗门', '家族', '朝廷', '商会', '帮派', '军队', '组织'],
    placeholder: '选择或输入',
  },
  { key: 'leader', label: '首领', placeholder: '首领姓名' },
  { key: 'members', label: '势力成员', type: 'tags', placeholder: '从已有角色中选择' },
  {
    key: 'stance',
    label: '立场',
    type: 'select',
    presets: ['正派', '反派', '中立', '亦正亦邪'],
    placeholder: '选择或输入',
  },
  { key: 'territory', label: '地盘', placeholder: '势力范围' },
  { key: 'goal', label: '势力诉求', type: 'textarea', rows: 2 },
  { key: 'first_chapter', label: '首次登场章号', type: 'number', min: 1 },
  { key: 'relations', label: '其他势力关系', type: 'tags', placeholder: '如 青云宗（敌对）' },
  { key: 'description', label: '势力简介', type: 'textarea', rows: 3 },
]

const canEdit = computed(
  () => props.run.status !== 'running' && props.run.status !== 'queued',
)

/** 首领与成员都从已有角色中选择，也可继续手输 */
const characterOptions = computed(() =>
  (props.run.characters || []).map((item) => item.name).filter(Boolean),
)
const factionFields = computed<CollectionField[]>(() =>
  FACTION_FIELDS.map((field) => {
    if (field.key === 'leader') {
      return { ...field, type: 'select', presets: characterOptions.value }
    }
    if (field.key === 'members') {
      return { ...field, presets: characterOptions.value }
    }
    return field
  }),
)
const dialogOpen = ref(false)
const editingIndex = ref(-1)
const dialogValue = ref<Record<string, any>>({})
const dialogError = ref('')
const saving = ref(false)
const deleteOpen = ref(false)
const deleteTarget = ref<FactionContent | null>(null)
const deleteError = ref('')
const deleting = ref(false)

const dialogTitle = computed(() => (editingIndex.value >= 0 ? '编辑势力' : '新增势力'))

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function openCreate(): void {
  if (!canEdit.value) return
  const blank: Record<string, any> = {}
  for (const field of FACTION_FIELDS) {
    blank[field.key] = field.type === 'tags' ? [] : field.type === 'number' ? undefined : ''
  }
  editingIndex.value = -1
  dialogValue.value = blank
  dialogError.value = ''
  dialogOpen.value = true
}

function openEdit(faction: FactionContent): void {
  if (!canEdit.value) return
  editingIndex.value = factions.value.findIndex((item) => item.name === faction.name)
  dialogValue.value = {
    ...clone(faction),
    relations: [...(faction.relations || [])],
    // 成员在表单里只维护姓名，保存时再与原有 role/relation 合并
    members: (faction.members || []).map((member) => member.name),
  }
  dialogError.value = ''
  dialogOpen.value = true
}

async function saveFaction(values: Record<string, any>): Promise<void> {
  if (!canEdit.value) return
  const name = String(values.name || '').trim()
  const duplicated = factions.value.some(
    (item, index) => item.name === name && index !== editingIndex.value,
  )
  if (duplicated) {
    dialogError.value = '势力名称已存在，请换一个名称'
    return
  }
  saving.value = true
  dialogError.value = ''
  try {
    const list = factions.value.map((item) => clone(item)) as Array<Record<string, any>>
    const existingMembers =
      editingIndex.value >= 0 ? list[editingIndex.value].members || [] : []
    const memberMap = new Map<string, Record<string, any>>(
      existingMembers.map((member: Record<string, any>) => [member.name, member]),
    )
    const memberNames: string[] = Array.isArray(values.members)
      ? values.members.map((item: unknown) => String(item)).filter(Boolean)
      : []
    const members = memberNames.map((memberName) => {
      const existed = memberMap.get(memberName)
      return existed ? { ...existed } : { name: memberName }
    })
    const { members: _ignored, ...rest } = values
    const merged = {
      ...rest,
      name,
      members,
      // 成员数直接由所选成员推导，避免与成员明细不一致
      members_count: members.length || undefined,
    }
    if (editingIndex.value >= 0) {
      list[editingIndex.value] = { ...list[editingIndex.value], ...merged }
    } else {
      list.push(merged)
    }
    await updateRunCollections(props.run.run_id, {
      factions: list as unknown as FactionContent[],
    })
    dialogOpen.value = false
    emit('updated')
  } catch (err) {
    dialogError.value = err instanceof ApiError ? err.message : '保存失败，请稍后重试'
  } finally {
    saving.value = false
  }
}

function openDelete(faction: FactionContent): void {
  if (!canEdit.value) return
  deleteTarget.value = faction
  deleteError.value = ''
  deleteOpen.value = true
}

async function confirmDelete(): Promise<void> {
  const target = deleteTarget.value
  if (!target || deleting.value) return
  deleting.value = true
  deleteError.value = ''
  try {
    const list = factions.value
      .filter((item) => item.name !== target.name)
      .map((item) => clone(item))
    await updateRunCollections(props.run.run_id, {
      factions: list as unknown as FactionContent[],
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
const stanceFilter = ref('')
const page = ref(1)
const openNames = ref<string[]>([])

const factions = computed(() => props.run.factions || [])

const stanceFilters = computed(() => {
  const values = Array.from(
    new Set(factions.value.map((item) => item.stance).filter(Boolean)),
  ) as string[]
  return ['', ...values]
})

const filtered = computed(() => {
  const text = keyword.value.trim().toLowerCase()
  return factions.value.filter((item) => {
    if (stanceFilter.value && item.stance !== stanceFilter.value) return false
    if (!text) return true
    return [item.name, item.leader, item.territory, item.type, item.category]
      .concat((item.members || []).map((member) => member.name))
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(text))
  })
})

const pageCount = computed(() => Math.max(1, Math.ceil(filtered.value.length / PAGE_SIZE)))
const paged = computed(() =>
  filtered.value.slice((page.value - 1) * PAGE_SIZE, page.value * PAGE_SIZE),
)

watch([keyword, stanceFilter], () => {
  if (page.value > pageCount.value) page.value = pageCount.value
})

function isOpen(name: string): boolean {
  return openNames.value.includes(name)
}

function toggle(name: string): void {
  const index = openNames.value.indexOf(name)
  if (index >= 0) openNames.value.splice(index, 1)
  else openNames.value.push(name)
}

function membersCount(faction: FactionContent): string {
  if (faction.members_count === null || faction.members_count === undefined) {
    return faction.members?.length ? `${faction.members.length}（明细）` : ''
  }
  return `${faction.members_count}`
}

function firstChapter(faction: FactionContent): string {
  return faction.first_chapter ? `第 ${faction.first_chapter} 章` : ''
}

function percent(value?: number): string {
  return typeof value === 'number' ? `${Math.round(value * 100)}%` : ''
}

function flag(value?: boolean): string {
  if (value === undefined) return ''
  return value ? '公开' : '保密'
}

/** 卡片/详情只渲染有值的字段，避免整片「—」 */
function factionFacts(faction: FactionContent): Array<{ label: string; value: string }> {
  return [
    { label: '大类', value: faction.category || '' },
    { label: '类型', value: faction.type || '' },
    { label: '首领', value: faction.leader || '' },
    { label: '势力诉求', value: faction.goal || '' },
    { label: '地盘', value: faction.territory || '' },
    { label: '成员数', value: membersCount(faction) },
    { label: '首现', value: firstChapter(faction) },
    { label: '关联势力', value: faction.rel_to || '' },
    { label: '势力关系', value: faction.rel_type || '' },
    { label: '关系强度', value: percent(faction.rel_strength) },
    { label: '关系公开', value: flag(faction.rel_public) },
  ].filter((fact) => fact.value)
}

function stanceTone(stance?: string): string {
  if (stance === '正面' || stance === '正' || stance === '正派' || stance === '己方') {
    return 'badge--success'
  }
  if (stance === '反派' || stance === '邪' || stance === '敌方') return 'badge--danger'
  if (stance === '亦正亦邪' || stance === '中立') return 'badge--warn'
  return ''
}

function resetFilters(): void {
  keyword.value = ''
  stanceFilter.value = ''
  page.value = 1
}
</script>

<style scoped>
.factions {
  padding: var(--space-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  height: 100%;
  min-height: 0;
}

/* 列表区独立滚动，筛选面板固定 */
.factions__list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding-right: 4px;
  scrollbar-width: thin;
}

.factions__list::-webkit-scrollbar {
  width: 8px;
}

.factions__list::-webkit-scrollbar-thumb {
  background: #d7dde5;
  border-radius: 8px;
}

/* ---------- 筛选面板 ---------- */
.factions__panel {
  flex: none;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-md);
  background: #fff;
}

.factions__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.factions__search {
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

.factions__search:focus {
  outline: none;
  border-color: var(--color-brand);
  background: #fff;
}

.factions__meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-left: auto;
}

.factions__count {
  font-size: 14px;
  color: var(--color-text-3);
  white-space: nowrap;
}

.factions__count b {
  color: var(--color-text);
  font-weight: 600;
}

.factions__pager {
  display: flex;
  align-items: center;
  gap: 4px;
}

.factions__page-btn {
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

.factions__page-btn:hover:not(:disabled) {
  border-color: var(--color-brand);
  color: var(--color-brand);
}

.factions__page-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.factions__page-info {
  font-size: 14px;
  color: var(--color-text-3);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.factions__row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.factions__row-label {
  flex: none;
  width: 32px;
  padding-top: 5px;
  font-size: 14px;
  color: var(--color-text-3);
}

.factions__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.factions__chip {
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

.factions__chip:hover {
  color: var(--color-brand);
}

.factions__chip.is-active {
  border-color: var(--color-brand);
  background: rgba(13, 148, 136, 0.1);
  color: var(--color-brand);
  font-weight: 600;
}

/* ---------- 表格 ---------- */
.factions__table-wrap {
  max-width: 100%;
  overflow-x: auto;
}

.factions__table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
  font-size: var(--text-xs);
  min-width: 720px;
}

.factions__table th {
  text-align: left;
  padding: 9px 12px;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-3);
  border-bottom: 1px solid var(--color-line);
  white-space: nowrap;
}

.factions__table td {
  padding: 11px 12px;
  border-bottom: 1px solid var(--color-line);
  color: var(--color-text-2);
  vertical-align: middle;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.factions__name {
  font-size: var(--text-md);
  font-weight: 700;
  color: var(--color-text);
}

/* 需覆盖 .factions__table th 的左对齐，故提高选择器权重 */
.factions__table th.factions__center,
.factions__table td.factions__center {
  text-align: center;
  font-variant-numeric: tabular-nums;
}

.factions__toggle {
  font-size: 14px;
  color: var(--color-brand);
  font-family: inherit;
}

.factions__acts {
  display: inline-flex;
  align-items: center;
  gap: 2px;
}

.faction-card__head .factions__acts {
  margin-left: auto;
}

.factions__act {
  width: 24px;
  height: 24px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  color: var(--color-text-3);
}

.factions__act:hover:not(:disabled) {
  background: var(--color-bg-soft);
  color: var(--color-brand);
}

.factions__act--danger:hover:not(:disabled) {
  background: var(--color-danger-soft);
  color: var(--color-danger);
}

.factions__act:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.factions__act svg {
  width: 14px;
  height: 14px;
}

.factions__dialog-text {
  font-size: var(--text-sm);
  line-height: 1.7;
  color: var(--color-text-2);
}

.factions__detail-row td {
  border-bottom: 1px solid var(--color-line);
  background: var(--color-bg-softer);
  white-space: normal;
  overflow: visible;
}

.factions__detail {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 4px 2px;
}

.factions__fields {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 6px 18px;
  font-size: 14px;
  color: var(--color-text-2);
}

.factions__fields i {
  font-style: normal;
  color: var(--color-text-3);
  margin-right: 6px;
}

.factions__block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.factions__block-label {
  font-size: 14px;
  color: var(--color-text-3);
}

.factions__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.factions__tag {
  padding: 1px 8px;
  border-radius: var(--radius-pill);
  background: var(--color-bg-soft);
  font-size: 14px;
  color: var(--color-text-2);
}

.factions__desc {
  margin: 0;
  line-height: 1.7;
  font-size: var(--text-xs);
  color: var(--color-text-2);
}

.factions__members {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.factions__member {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  padding: 4px 10px;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-pill);
  background: var(--color-bg);
  font-size: 14px;
  color: var(--color-text-2);
}

.factions__member b {
  color: var(--color-text);
}

.factions__member i {
  font-style: normal;
  color: var(--color-text-3);
}

.factions__none {
  font-size: 14px;
  color: var(--color-text-3);
}

.factions__empty {
  padding: var(--space-8) var(--space-4);
  text-align: center;
  font-size: var(--text-sm);
  color: var(--color-text-2);
}

.factions__empty p + p {
  margin-top: 6px;
  font-size: var(--text-xs);
  color: var(--color-text-3);
}

.factions__reset {
  margin-top: var(--space-3);
}

.factions__cards {
  display: none;
}

@media (max-width: 720px) {
  .factions {
    padding: var(--space-4);
  }

  .factions__table {
    display: none;
  }

  .factions__cards {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .factions__toolbar {
    flex-wrap: wrap;
  }

  .factions__search {
    width: 100%;
  }
}

.faction-card {
  padding: 12px 14px;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-md);
  background: var(--color-bg-softer);
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.faction-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.faction-card__head h3 {
  font-size: var(--text-sm);
  font-weight: 700;
}

.faction-card__facts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px 12px;
  font-size: 14px;
  color: var(--color-text-2);
}

.faction-card__facts i {
  font-style: normal;
  color: var(--color-text-3);
  margin-right: 6px;
}

.faction-card__desc {
  font-size: var(--text-xs);
  line-height: 1.7;
  color: var(--color-text-2);
}

.faction-card .btn {
  align-self: flex-start;
}
</style>
