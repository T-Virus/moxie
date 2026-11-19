<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api, errorMessage, normalizeList } from '../api'
import { can } from '../roles'
import { getRole } from '../session'
import { pushToast } from '../toast'
import { confirm } from '../dialog'
import Icon from '../components/Icon.vue'
import Modal from '../components/Modal.vue'
import PageHeader from '../components/PageHeader.vue'
import RowActions, { type RowAction } from '../components/RowActions.vue'
import StateBlock from '../components/StateBlock.vue'
import StatusBadge from '../components/StatusBadge.vue'
import UiSelect from '../components/UiSelect.vue'

const role = getRole()
const canWrite = computed(() => can(role, 'model_config:write'))

const rows = ref<any[]>([])
const loading = ref(false)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await api.modelConfigs()
    rows.value = normalizeList<any>({ items: Array.isArray(data) ? data : [] }).items
  } catch (e) {
    rows.value = []
    error.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)

const editOpen = ref(false)
const editing = ref<any>(null)
const form = reactive({
  label: '',
  provider: 'edgeone',
  model: '',
  base_url: '',
  api_key: '',
  enabled: true,
})
const saving = ref(false)
const saveError = ref('')
const testing = ref(false)
const testResult = ref<string>('')

const KNOWN_PROVIDERS = ['edgeone', 'openai', 'deepseek', 'zhipu', 'custom']

function openEdit(row: any) {
  editing.value = row
  form.label = row.label || ''
  // 未配置工序的兜底来源可能是 env，不在下拉选项内，编辑时归一到默认供应商，避免把非法值写回库
  form.provider = KNOWN_PROVIDERS.includes(row.provider) ? row.provider : 'edgeone'
  form.model = row.model || ''
  form.base_url = row.base_url || ''
  form.api_key = '' // 留空 = 不改动已存 Key
  form.enabled = row.enabled !== false
  saveError.value = ''
  testResult.value = ''
  editOpen.value = true
}

async function save() {
  if (!editing.value) return
  if (form.model.trim().length < 1) {
    saveError.value = '请填写模型名称（如 @makers/deepseek-v4-flash）'
    return
  }
  saving.value = true
  saveError.value = ''
  try {
    await api.putModelConfig(editing.value.step_key, {
      label: form.label || undefined,
      provider: form.provider,
      model: form.model.trim(),
      base_url: form.base_url.trim() || undefined,
      api_key: form.api_key || null, // null = 保留原 Key
      enabled: form.enabled,
    })
    pushToast('模型配置已保存')
    editOpen.value = false
    await load()
  } catch (e) {
    saveError.value = errorMessage(e)
  } finally {
    saving.value = false
  }
}

async function test() {
  if (!editing.value) return
  testing.value = true
  testResult.value = ''
  try {
    const res = await api.testModelConfig(editing.value.step_key, {
      provider: form.provider,
      model: form.model.trim(),
      base_url: form.base_url.trim() || undefined,
      api_key: form.api_key || null,
    })
    testResult.value = `调用成功：模型 ${res.model}，消耗 token ${res.tokens}`
  } catch (e) {
    testResult.value = '调用失败：' + errorMessage(e)
  } finally {
    testing.value = false
  }
}

const deleting = ref(false)
async function remove(row: any) {
  if (row.step_key === 'default') {
    pushToast('default 兜底配置不可删除，可清空 Key 并停用')
    return
  }
  if (!await confirm({ title: '删除模型配置', message: `确认删除「${row.label}」的模型配置？删除后将回退到 default / 环境变量。`, danger: true, confirmText: '确认删除' })) return
  deleting.value = true
  try {
    await api.deleteModelConfig(row.step_key)
    pushToast('已删除该工序模型配置')
    await load()
  } catch (e) {
    pushToast(errorMessage(e))
  } finally {
    deleting.value = false
  }
}

const providerLabel: Record<string, string> = {
  edgeone: 'EdgeOne 网关',
  openai: 'OpenAI',
  deepseek: 'DeepSeek',
  zhipu: '智谱 BigModel',
  custom: '自定义',
  env: '环境变量兜底',
}

const isCoverStep = computed(() => editing.value?.step_key === 'cover')

/** 一键套用推荐模型：同时填好供应商、模型名与网关地址 */
function applyRec(item: any) {
  if (!item) return
  form.provider = KNOWN_PROVIDERS.includes(item.provider) ? item.provider : 'edgeone'
  form.model = item.model || ''
  form.base_url = item.base_url || ''
  saveError.value = ''
  testResult.value = ''
}

/** 推荐命中状态：可选项（封面）未配置时视为「免费兜底」 */
function recBadge(row: any): { text: string; cls: string } {
  const rec = row.recommendation
  if (!rec) return { text: '—', cls: 'muted' }
  if (rec.optional && !row.configured) return { text: '免费兜底', cls: 'muted' }
  return row.recommended_match ? { text: '已采用', cls: 'ok' } : { text: '可优化', cls: 'muted' }
}

interface CommonModel {
  label: string
  provider: string
  model: string
  base_url: string
}

/** 市场通用模型：不走工序推荐，作为可选的通用候选（OpenAI 兼容端点） */
const COMMON_MODELS: CommonModel[] = [
  { label: 'GPT-4o', provider: 'openai', model: 'gpt-4o', base_url: '' },
  { label: 'GPT-4o mini', provider: 'openai', model: 'gpt-4o-mini', base_url: '' },
  { label: 'GPT-4.1', provider: 'openai', model: 'gpt-4.1', base_url: '' },
  { label: 'o3-mini', provider: 'openai', model: 'o3-mini', base_url: '' },
  { label: 'DeepSeek Chat', provider: 'deepseek', model: 'deepseek-chat', base_url: '' },
  { label: 'DeepSeek Reasoner', provider: 'deepseek', model: 'deepseek-reasoner', base_url: '' },
  { label: '智谱 GLM-4-Plus', provider: 'zhipu', model: 'glm-4-plus', base_url: '' },
  { label: '智谱 GLM-4-Flash', provider: 'zhipu', model: 'glm-4-flash', base_url: '' },
  { label: '智谱 GLM-4-Air', provider: 'zhipu', model: 'glm-4-air', base_url: '' },
  { label: '通义千问 Max', provider: 'custom', model: 'qwen-max', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
  { label: '通义千问 Plus', provider: 'custom', model: 'qwen-plus', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
  { label: '通义千问 Turbo', provider: 'custom', model: 'qwen-turbo', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
  { label: 'Kimi (Moonshot 8K)', provider: 'custom', model: 'moonshot-v1-8k', base_url: 'https://api.moonshot.cn/v1' },
  { label: 'Kimi (Moonshot 32K)', provider: 'custom', model: 'moonshot-v1-32k', base_url: 'https://api.moonshot.cn/v1' },
  { label: '豆包 (Ark 32K)', provider: 'custom', model: 'doubao-pro-32k', base_url: 'https://ark.cn-beijing.volces.com/api/v3' },
]

/** 本工序推荐：首选 + 备选（来自服务端按工序特征给出的推荐表） */
const recOptions = computed(() => {
  const rec = editing.value?.recommendation
  if (!rec) return []
  const options: { value: string; label: string }[] = []
  if (rec.primary) options.push({ value: String(rec.primary.model), label: `${rec.primary.model}（首选）` })
  for (const alt of rec.alternatives || []) {
    options.push({ value: String(alt.model), label: `${alt.model}（备选）` })
  }
  return options
})

const recReason = computed(() => editing.value?.recommendation?.reason || '')

/**
 * 通用模型里同样标出「推荐」：
 * 依据本工序推荐表的模型特征（快/省 vs 强推理/长上下文）映射到对应的市场模型，
 * 让通用清单也带上下文字，而不是一堆平铺选项。
 */
const recommendedCommonModels = computed(() => {
  const rec = editing.value?.recommendation
  if (!rec) return new Set<string>()
  const names = [rec.primary?.model, ...(rec.alternatives || []).map((alt: any) => alt?.model)]
    .filter(Boolean)
    .map((name: unknown) => String(name))
  const cheap = names.some(name => /flash|zhuque|mini|turbo/i.test(name))
  const strong = names.some(name => /pro|-m3|kimi|max|reasoner/i.test(name))
  const picked = new Set<string>()
  if (cheap) ['gpt-4o-mini', 'deepseek-chat', 'glm-4-flash', 'qwen-turbo'].forEach(model => picked.add(model))
  if (strong) ['gpt-4o', 'deepseek-reasoner', 'glm-4-plus', 'qwen-max', 'moonshot-v1-32k'].forEach(model => picked.add(model))
  return picked
})

/** 市场通用模型：与工序无关的可选清单，命中工序特征的排到最前并标注「推荐」 */
const commonOptions = computed(() => {
  const list = COMMON_MODELS.map(item => {
    const recommended = recommendedCommonModels.value.has(item.model)
    return {
      value: `common:${item.provider}:${item.model}`,
      recommended,
      label: `${providerLabel[item.provider] || item.provider} · ${item.model}${recommended ? '（推荐）' : ''}`,
    }
  })
  return list.sort((a, b) => Number(b.recommended) - Number(a.recommended))
})

/** 合并下拉：按工序推荐 + 通用模型（通用里命中工序特征的标「推荐」并排在最前） */
const modelOptions = computed(() => {
  const options: { value: string; label: string; disabled?: boolean }[] = []
  if (recOptions.value.length) {
    options.push({ value: '__rec_head', label: '按工序推荐', disabled: true })
    options.push(...recOptions.value)
  }
  if (!isCoverStep.value) {
    options.push({ value: '__common_head', label: '通用模型', disabled: true })
    options.push(...commonOptions.value)
  }
  return options
})

function applyModelChoice(value: string) {
  if (!value || value.startsWith('__')) return
  if (value.startsWith('common:')) applyCommon(value)
  else applyRecommended(value)
}

/** 选中按工序推荐的模型 */
function applyRecommended(value: string) {
  const rec = editing.value?.recommendation
  if (!rec || !value) return
  const hit = [rec.primary, ...(rec.alternatives || [])].find((entry: any) => entry && entry.model === value)
  if (hit) applyRec(hit)
}

/** 选中市场通用模型 */
function applyCommon(value: string) {
  const hit = COMMON_MODELS.find(item => `common:${item.provider}:${item.model}` === value)
  if (!hit) return
  form.provider = KNOWN_PROVIDERS.includes(hit.provider) ? hit.provider : 'custom'
  form.model = hit.model
  form.base_url = hit.base_url
  saveError.value = ''
  testResult.value = ''
}

function configActions(row: any): RowAction[] {
  const actions: RowAction[] = []
  if (canWrite.value) {
    actions.push({ label: '编辑', run: () => openEdit(row) })
    if (row.step_key !== 'default') actions.push({ label: '删除', tone: 'danger', run: () => remove(row) })
  }
  return actions
}
</script>

<template>
  <PageHeader title="模型配置" desc="按工序模块独立选择模型与 Key，统一接入 EdgeOne 网关。配置入库纳管，无需改环境变量或重启。">
    <span v-if="!canWrite" class="badge muted">只读</span>
    <button class="btn ghost sm" :disabled="loading" @click="load">
      <Icon name="refresh" :size="14" />刷新
    </button>
  </PageHeader>

  <div class="card">
    <div v-if="loading && !rows.length" class="state-loading">
      <StateBlock kind="loading" title="正在加载配置…" />
    </div>
    <div v-else-if="error">
      <StateBlock kind="error" :title="error" retry-label="重试" @retry="load" />
    </div>
    <div v-else-if="!rows.length">
      <StateBlock kind="empty" title="暂无配置" />
    </div>
    <template v-else>
      <div class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th>工序模块</th>
              <th>来源</th>
              <th>供应商</th>
              <th>模型</th>
              <th>推荐模型</th>
              <th>网关地址</th>
              <th style="width: 80px">Key</th>
              <th style="width: 80px">启用</th>
              <th style="width: 150px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.step_key">
              <td>
                <div class="cell-ellipsis" :title="`${row.label} · ${row.step_key}`">{{ row.label }}</div>
              </td>
              <td>
                <span class="badge" :class="row.source === 'env' ? 'muted' : (row.source === 'default' ? 'purple' : '')">
                  {{ row.source === 'env' ? '环境变量' : row.source === 'default' ? 'default 兜底' : '专用配置' }}
                </span>
              </td>
              <td>{{ providerLabel[row.provider] || row.provider }}</td>
              <td class="mono"><span class="cell-ellipsis" :title="row.model || ''">{{ row.model || '—' }}</span></td>
              <td>
                <div v-if="row.recommendation" class="rec-line">
                  <span
                    v-if="row.recommendation.primary"
                    class="mono rec-model"
                    :title="row.recommendation.primary.model"
                  >{{ row.recommendation.primary.model }}</span>
                  <span v-else class="muted rec-model" :title="row.recommendation.reason">图片接口</span>
                  <span class="badge" :class="recBadge(row).cls">{{ recBadge(row).text }}</span>
                </div>
                <span v-else class="muted">—</span>
              </td>
              <td class="mono"><span class="cell-ellipsis" :title="row.base_url">{{ row.base_url }}</span></td>
              <td>{{ row.key_set ? '已填' : '—' }}</td>
              <td>
                <StatusBadge :value="row.enabled ? 'active' : 'disabled'" dot />
              </td>
              <td><RowActions v-if="canWrite" :actions="configActions(row)" /></td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="muted" style="font-size: 12px; margin: 12px 2px 0">
        解析优先级：专用配置 → default 兜底 → 环境变量。请求态 BYOK Key 始终优先于后台配置。
      </p>
      <p class="muted" style="font-size: 12px; margin: 6px 2px 0">
        推荐依据模型特点：正文/概括/抽取/改名等高频短任务选低延迟低成本模型；体检/拆解/大纲/改编等推理密集型选思考型或长文强模型；封面走独立图片接口，留空即免费 flux 兜底。
      </p>
    </template>
  </div>

  <Modal v-if="editOpen" title="编辑模型配置" :subtitle="editing ? editing.label : ''" @close="editOpen = false">
    <div class="form-grid">
      <div v-if="modelOptions.length" class="field span-2">
        <label>推荐 / 通用模型</label>
        <UiSelect
          :model-value="''"
          placeholder="选择按工序推荐的模型，或市场通用模型"
          :options="modelOptions"
          @change="applyModelChoice(String($event))"
        />
      </div>
      <div v-if="recReason" class="span-2 rec-reason">
        <span class="hint">{{ recReason }}</span>
      </div>
      <div class="field">
        <label>供应商</label>
        <UiSelect
          v-model="form.provider"
          :options="[
            { value: 'edgeone', label: 'EdgeOne 网关（推荐，OpenAI 兼容）' },
            { value: 'openai', label: 'OpenAI' },
            { value: 'deepseek', label: 'DeepSeek' },
            { value: 'zhipu', label: '智谱 BigModel' },
            { value: 'custom', label: '自定义' },
          ]"
        />
      </div>
      <div class="field">
        <label>模型名称<span class="required">*</span></label>
        <input v-model="form.model" class="input mono" placeholder="@makers/deepseek-v4-flash" />
      </div>
      <div class="field span-2">
        <label>网关地址（base_url）</label>
        <input v-model="form.base_url" class="input mono" placeholder="https://ai-gateway.edgeone.link/v1" />
        <span class="hint">留空则按供应商默认：EdgeOne 用 ai-gateway.edgeone.link/v1，其余用服务端 llm_base_url。</span>
      </div>
      <div class="field span-2">
        <label>API Key</label>
        <input v-model="form.api_key" type="password" class="input mono" autocomplete="off" placeholder="留空 = 不改动已存 Key" />
        <span class="hint">当前已存 Key：{{ editing && editing.key_set ? '已填写（输入新值将覆盖）' : '未填写' }}。落库前加密存储。</span>
      </div>
      <div class="field span-2">
        <label class="checkbox">
          <input type="checkbox" v-model="form.enabled" /> 启用该工序配置
        </label>
      </div>
    </div>

    <div v-if="saveError" class="notice error">{{ saveError }}</div>
    <div v-if="testResult" class="notice" :class="testResult.startsWith('调用成功') ? 'info' : 'error'">{{ testResult }}</div>
    <div v-if="isCoverStep" class="notice info">
      封面走图片生成接口（images/generations），「测试连接」不适用。填入国内图片模型（如智谱 CogView，自带免费额度）与该平台 Key 后才会走该接口；Key 留空则自动回退 Pollinations 免费 flux。
    </div>
    <template #footer>
      <button v-if="!isCoverStep" class="btn ghost sm" :disabled="saving || testing" @click="test">测试连接</button>
      <button class="btn ghost sm" :disabled="saving || testing" @click="editOpen = false">取消</button>
      <button class="btn" :disabled="saving || testing" @click="save">
        {{ saving ? '保存中…' : '保存' }}
      </button>
    </template>
  </Modal>
</template>

<style scoped>
.state-loading { padding: 10px 0; }
.checkbox { display: inline-flex !important; flex-direction: row !important; align-items: center; gap: 6px; font-size: 12px; color: var(--text-2); }
/* 表格：列宽足够时单行展示，超出部分省略，不换行撑高行 */
.cell-ellipsis { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rec-line { display: flex; align-items: center; gap: 6px; min-width: 0; }
.rec-model { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.rec-line .badge { flex: none; }
.rec-reason .hint { display: block; margin-top: -6px; }
</style>
