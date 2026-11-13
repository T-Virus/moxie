<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api, errorMessage } from '../api'
import { can } from '../roles'
import { getRole } from '../session'
import { pushToast } from '../toast'
import Icon from '../components/Icon.vue'
import Modal from '../components/Modal.vue'
import PageHeader from '../components/PageHeader.vue'
import StateBlock from '../components/StateBlock.vue'

const role = getRole()
const canWrite = computed(() => can(role, 'presets:write'))

const TYPE_LABEL: Record<string, string> = {
  genre: '题材',
  character_gender: '角色·性别',
  character_race: '角色·种族',
  character_role: '角色·剧情功能',
  character_camp: '角色·阵营',
  faction_category: '势力·大类',
  faction_type: '势力·类型',
  faction_stance: '势力·立场',
  item_category: '道具·类别',
  item_grade: '道具·品阶',
  info_theme: '作品·主题',
  info_person: '作品·叙事人称',
  info_voice: '作品·文风',
  info_tone: '作品·基调',
  info_age: '作品·读者年龄',
  info_update: '作品·更新频率',
  info_pace: '作品·连载节奏',
  info_rating: '作品·内容分级',
  info_platform: '作品·目标平台',
  info_selling_point: '作品·核心卖点',
  outline_ending: '大纲·结局类型',
  chapter_status: '章节·状态',
  chapter_hook_type: '章节·钩子类型',
}

function typeLabel(type: string): string {
  return TYPE_LABEL[type] || type
}

const rows = ref<any[]>([])
const types = ref<string[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 50
const loading = ref(false)
const error = ref('')
const filterType = ref('')
const keyword = ref('')
/** all=系统预设+用户自定义；system=仅系统级；custom=仅用户自定义 */
const scope = ref<'all' | 'system' | 'custom'>('all')

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

async function load() {
  loading.value = true
  error.value = ''
  try {
    const query: Record<string, unknown> = { page: page.value, page_size: pageSize, scope: scope.value }
    if (filterType.value.trim()) query.type = filterType.value.trim()
    if (keyword.value.trim()) query.q = keyword.value.trim()
    const data = await api.presets(query)
    rows.value = Array.isArray(data.items) ? data.items : []
    total.value = Number(data.total) || 0
    types.value = Array.isArray(data.types) ? data.types : []
  } catch (e) {
    rows.value = []
    error.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)

function applyFilter() {
  page.value = 1
  load()
}

function changeScope() {
  page.value = 1
  filterType.value = ''
  load()
}

function goPage(delta: number) {
  const next = page.value + delta
  if (next < 1 || next > totalPages.value) return
  page.value = next
  load()
}

const editOpen = ref(false)
const editing = ref<any>(null)
const form = reactive({
  type: '',
  value: '',
  label: '',
  audience: 'all',
  sort: 0,
})
const saving = ref(false)
const saveError = ref('')

function openCreate() {
  editing.value = null
  form.type = filterType.value.trim() || types.value[0] || ''
  form.value = ''
  form.label = ''
  form.audience = 'all'
  form.sort = 0
  saveError.value = ''
  editOpen.value = true
}

function openEdit(row: any) {
  editing.value = row
  form.type = row.type || ''
  form.value = row.value || ''
  form.label = row.label || ''
  form.audience = row.audience || 'all'
  form.sort = Number(row.sort) || 0
  saveError.value = ''
  editOpen.value = true
}

async function save() {
  const payload = {
    type: form.type.trim(),
    value: form.value.trim(),
    label: form.label.trim() || undefined,
    audience: form.audience.trim() || 'all',
    sort: Number(form.sort) || 0,
  }
  if (!payload.type || !payload.value) {
    saveError.value = '请填写类型与预设值'
    return
  }
  if (!/^[a-z][a-z0-9_]*$/.test(payload.type)) {
    saveError.value = '类型只能用小写字母、数字和下划线，且以字母开头'
    return
  }
  if (!/^[a-z]+(,[a-z]+)*$/.test(payload.audience)) {
    saveError.value = '受众请填 all / male / female，多个用逗号分隔'
    return
  }
  saving.value = true
  saveError.value = ''
  try {
    if (editing.value) {
      await api.updatePreset(editing.value.id, payload)
      pushToast('预设值已更新')
    } else {
      await api.createPreset(payload)
      pushToast('预设值已新增')
    }
    editOpen.value = false
    await load()
  } catch (e) {
    saveError.value = errorMessage(e)
  } finally {
    saving.value = false
  }
}

async function remove(row: any) {
  if (!confirm(`确认删除「${row.value}」（${typeLabel(row.type)}）？删除后前端下拉将不再出现该选项。`)) return
  try {
    await api.deletePreset(row.id)
    pushToast('预设值已删除')
    await load()
  } catch (e) {
    pushToast(errorMessage(e))
  }
}

const syncing = ref(false)
async function syncSeeds() {
  if (!confirm('从程序内置清单补齐缺失的预设值？只新增缺失项，不会覆盖或删除已有数据。')) return
  syncing.value = true
  try {
    const result = await api.syncPresetSeeds()
    pushToast(`同步完成：新增 ${result.inserted ?? 0} 项`)
    await load()
  } catch (e) {
    pushToast(errorMessage(e))
  } finally {
    syncing.value = false
  }
}
</script>

<template>
  <PageHeader title="预设值维护" desc="统一管理题材、角色/势力/道具枚举、作品信息标签与章节状态等下拉选项，包含用户自定义预设。修改后前端各页面实时生效，无需发版。">
    <span v-if="!canWrite" class="badge muted">只读</span>
    <button class="btn ghost sm" :disabled="loading" @click="load">
      <Icon name="refresh" :size="14" />刷新
    </button>
  </PageHeader>

  <div class="card">
    <div class="toolbar">
      <select v-model="scope" class="select" @change="changeScope">
        <option value="all">全部数据</option>
        <option value="system">仅系统预设</option>
        <option value="custom">仅用户自定义</option>
      </select>
      <select v-model="filterType" class="select" @change="applyFilter">
        <option value="">全部类型</option>
        <option v-for="t in types" :key="t" :value="t">{{ typeLabel(t) }}（{{ t }}）</option>
      </select>
      <input
        v-model="keyword"
        class="input"
        type="search"
        placeholder="搜索预设值 / 标签"
        @keyup.enter="applyFilter"
      />
      <button class="btn ghost sm" @click="applyFilter">筛选</button>
      <span class="spacer" />
      <button v-if="canWrite" class="btn ghost sm" :disabled="syncing" @click="syncSeeds">
        {{ syncing ? '同步中…' : '同步内置预设' }}
      </button>
      <button v-if="canWrite" class="btn sm" @click="openCreate">新增预设值</button>
    </div>

    <div v-if="loading && !rows.length" class="state-loading">
      <StateBlock kind="loading" title="正在加载预设值…" />
    </div>
    <div v-else-if="error">
      <StateBlock kind="error" :title="error" retry-label="重试" @retry="load" />
    </div>
    <div v-else-if="!rows.length">
      <StateBlock kind="empty" title="没有匹配的预设值" />
    </div>
    <template v-else>
      <div class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th style="width: 180px">类型</th>
              <th>预设值</th>
              <th>显示标签</th>
              <th style="width: 130px">受众</th>
              <th style="width: 80px">排序</th>
              <th style="width: 150px">来源 / 归属</th>
              <th style="width: 140px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.id">
              <td>
                <div>{{ typeLabel(row.type) }}</div>
                <div class="muted mono" style="font-size: 11.5px">{{ row.type }}</div>
              </td>
              <td><span class="mono">{{ row.value }}</span></td>
              <td>{{ row.label || '—' }}</td>
              <td class="muted">{{ row.audience }}</td>
              <td class="muted">{{ row.sort }}</td>
              <td>
                <span v-if="row.custom" class="badge purple">
                  用户自定义 · #{{ row.account_id }}
                </span>
                <span v-else class="badge" :class="row.builtin ? 'muted' : 'purple'">
                  {{ row.builtin ? '内置' : '后台新增' }}
                </span>
              </td>
              <td>
                <div class="actions">
                  <button v-if="canWrite" class="btn ghost sm" @click="openEdit(row)">编辑</button>
                  <button v-if="canWrite" class="btn danger-ghost sm" @click="remove(row)">删除</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="pager">
        <span class="muted">共 {{ total }} 项 · 第 {{ page }} / {{ totalPages }} 页</span>
        <span class="spacer" />
        <button class="btn ghost sm" :disabled="page <= 1" @click="goPage(-1)">上一页</button>
        <button class="btn ghost sm" :disabled="page >= totalPages" @click="goPage(1)">下一页</button>
      </div>
      <p class="muted" style="font-size: 12px; margin: 10px 2px 0">
        内置项由程序清单首次初始化；删除或修改后不会被重启覆盖。升级后如需补新预设，点「同步内置预设」即可（只补缺失，不覆盖现有数据）。
      </p>
    </template>
  </div>

  <Modal
    v-if="editOpen"
    :title="editing ? '编辑预设值' : '新增预设值'"
    :subtitle="editing ? `${typeLabel(editing.type)} · ${editing.value}` : ''"
    size="narrow"
    @close="editOpen = false"
  >
    <div class="field">
      <label>预设类型<span class="required">*</span></label>
      <input v-model="form.type" class="input mono" list="preset-types" placeholder="如 info_theme、character_race" />
      <datalist id="preset-types">
        <option v-for="t in types" :key="t" :value="t">{{ typeLabel(t) }}</option>
      </datalist>
      <span class="hint">选择已有类型，或输入新的小写下划线标识；新类型需前端同步接入后才会展示。</span>
    </div>
    <div class="field">
      <label>预设值<span class="required">*</span></label>
      <input v-model="form.value" class="input" placeholder="下拉中实际显示与保存的值" />
    </div>
    <div class="field">
      <label>显示标签</label>
      <input v-model="form.label" class="input" placeholder="留空则与预设值一致" />
    </div>
    <div class="field">
      <label>受众</label>
      <input v-model="form.audience" class="input mono" placeholder="all / male,female" />
      <span class="hint">仅题材用于按男频/女频过滤，其它类型填 all 即可；多个值用英文逗号分隔。</span>
    </div>
    <div class="field">
      <label>排序</label>
      <input v-model.number="form.sort" class="input" type="number" />
      <span class="hint">数值越小越靠前。</span>
    </div>
    <div v-if="saveError" class="notice error" style="margin: 8px 0 0">{{ saveError }}</div>
    <template #footer>
      <button class="btn ghost sm" :disabled="saving" @click="editOpen = false">取消</button>
      <button class="btn" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
    </template>
  </Modal>
</template>

<style scoped>
.state-loading { padding: 10px 0; }
.toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 14px; flex-wrap: wrap; }
.toolbar .select { width: 210px; }
.toolbar .input { width: 220px; }
.spacer { flex: 1; }
.pager { display: flex; align-items: center; gap: 8px; margin-top: 12px; font-size: 12.5px; }
.field { margin-bottom: 14px; }
.field > label { display: block; font-size: 12.5px; margin-bottom: 6px; color: var(--text-2); }
.required { color: var(--red); }
.hint { display: block; font-size: 11.5px; color: var(--text-3); margin-top: 4px; }
</style>
