<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api, errorMessage, normalizeList } from '../api'
import { can } from '../roles'
import { getRole } from '../session'
import { pushToast } from '../toast'
import Icon from '../components/Icon.vue'
import Modal from '../components/Modal.vue'
import PageHeader from '../components/PageHeader.vue'
import StateBlock from '../components/StateBlock.vue'
import StatusBadge from '../components/StatusBadge.vue'

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
  if (!confirm(`确认删除「${row.label}」的模型配置？删除后将回退到 default/环境变量。`)) return
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
                <div>{{ row.label }}</div>
                <div class="muted" style="font-size: 11.5px">{{ row.step_key }}</div>
              </td>
              <td>
                <span class="badge" :class="row.source === 'env' ? 'muted' : (row.source === 'default' ? 'purple' : '')">
                  {{ row.source === 'env' ? '环境变量' : row.source === 'default' ? 'default 兜底' : '专用配置' }}
                </span>
              </td>
              <td>{{ providerLabel[row.provider] || row.provider }}</td>
              <td class="mono">{{ row.model || '—' }}</td>
              <td>
                <template v-if="row.recommendation">
                  <div
                    v-if="row.recommendation.primary"
                    class="mono"
                    style="font-size: 12px"
                    :title="row.recommendation.reason"
                  >
                    {{ row.recommendation.primary.model }}
                  </div>
                  <div v-else class="muted" style="font-size: 12px" :title="row.recommendation.reason">
                    图片接口
                  </div>
                  <span class="badge" :class="recBadge(row).cls">{{ recBadge(row).text }}</span>
                </template>
                <span v-else class="muted">—</span>
              </td>
              <td class="mono" style="font-size: 12px">{{ row.base_url }}</td>
              <td>{{ row.key_set ? '已填' : '—' }}</td>
              <td>
                <StatusBadge :value="row.enabled ? 'active' : 'disabled'" dot />
              </td>
              <td>
                <div class="actions">
                  <button v-if="canWrite" class="btn ghost sm" @click="openEdit(row)">编辑</button>
                  <button v-if="canWrite && row.step_key !== 'default'" class="btn danger-ghost sm" @click="remove(row)">删除</button>
                </div>
              </td>
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

  <Modal v-if="editOpen" title="编辑模型配置" :subtitle="editing ? editing.label : ''" size="narrow" @close="editOpen = false">
    <div v-if="editing && editing.recommendation" class="field">
      <label>按工序推荐</label>
      <template v-if="editing.recommendation.primary">
        <div class="rec-list">
          <button type="button" class="rec-chip primary" @click="applyRec(editing.recommendation.primary)">
            <span class="rec-tag">首选</span>{{ editing.recommendation.primary.model }}
          </button>
          <button
            v-for="alt in editing.recommendation.alternatives"
            :key="alt.model"
            type="button"
            class="rec-chip"
            @click="applyRec(alt)"
          >
            {{ alt.model }}
          </button>
        </div>
        <div class="rec-traits">
          <span v-for="t in editing.recommendation.primary.traits" :key="t" class="badge muted">{{ t }}</span>
        </div>
      </template>
      <span class="hint">{{ editing.recommendation.reason }}</span>
    </div>
    <div class="field">
      <label>供应商</label>
      <select v-model="form.provider" class="select">
        <option value="edgeone">EdgeOne 网关（推荐，OpenAI 兼容）</option>
        <option value="openai">OpenAI</option>
        <option value="deepseek">DeepSeek</option>
        <option value="zhipu">智谱 BigModel</option>
        <option value="custom">自定义</option>
      </select>
    </div>
    <div class="field">
      <label>模型名称<span class="required">*</span></label>
      <input v-model="form.model" class="input" placeholder="@makers/deepseek-v4-flash 或 gpt-4o 等" />
    </div>
    <div class="field">
      <label>网关地址（base_url）</label>
      <input v-model="form.base_url" class="input mono" placeholder="https://ai-gateway.edgeone.link/v1" />
      <span class="hint">留空则按供应商默认：EdgeOne 用 ai-gateway.edgeone.link/v1，其余用服务端 llm_base_url。</span>
    </div>
    <div class="field">
      <label>API Key</label>
      <input v-model="form.api_key" type="password" class="input mono" autocomplete="off" placeholder="留空 = 不改动已存 Key" />
      <span class="hint">当前已存 Key：{{ editing && editing.key_set ? '已填写（输入新值将覆盖）' : '未填写' }}。落库前加密存储。</span>
    </div>
    <div class="field row">
      <label class="checkbox">
        <input type="checkbox" v-model="form.enabled" /> 启用该工序配置
      </label>
    </div>
    <div v-if="saveError" class="notice error" style="margin: 8px 0 0">{{ saveError }}</div>
    <div v-if="testResult" class="notice" :class="testResult.startsWith('调用成功') ? 'ok' : 'error'" style="margin: 8px 0 0">{{ testResult }}</div>
    <div v-if="isCoverStep" class="hint" style="margin-top: 8px">
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
.field { margin-bottom: 14px; }
.field.row { margin-bottom: 6px; }
.field > label { display: block; font-size: 12.5px; margin-bottom: 6px; color: var(--text-2); }
.required { color: var(--red); }
.hint { display: block; font-size: 11.5px; color: var(--text-3); margin-top: 4px; }
.checkbox { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; }
.rec-list { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 6px; }
.rec-chip {
  display: inline-flex; align-items: center; gap: 6px; padding: 5px 10px;
  border-radius: var(--radius-sm); border: 1px solid var(--border); background: var(--card);
  color: var(--text-2); font-size: 12.5px; cursor: pointer;
}
.rec-chip:hover { border-color: var(--primary); color: var(--text); }
.rec-chip.primary { border-color: var(--primary); background: var(--primary-bg); color: var(--text); }
.rec-tag { font-size: 10.5px; padding: 1px 5px; border-radius: 4px; background: var(--primary); color: #fff; }
.rec-traits { display: flex; flex-wrap: wrap; gap: 6px; margin: 2px 0 4px; }
</style>
