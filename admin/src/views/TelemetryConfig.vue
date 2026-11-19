<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api, errorMessage } from '../api'
import { can } from '../roles'
import { getRole } from '../session'
import { pushToast } from '../toast'
import type { TelemetryConfig } from '../types'
import { formatTime } from '../ui'
import Icon from '../components/Icon.vue'
import PageHeader from '../components/PageHeader.vue'
import StateBlock from '../components/StateBlock.vue'
import UiSelect from '../components/UiSelect.vue'

const canWrite = computed(() => can(getRole(), 'telemetry:write'))
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const config = ref<TelemetryConfig | null>(null)
const form = reactive({ sample_rate: 1, dedupe_window_seconds: 60, dedupe_max_entries: 64 })
// 灰度档：enabled 控制是否提交 canary；三项留空表示回退基线值
const canary = reactive({
  enabled: false,
  percent: 10,
  sample_rate: '' as number | '',
  dedupe_window_seconds: '' as number | '',
  dedupe_max_entries: '' as number | '',
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await api.telemetryConfig()
    config.value = data
    form.sample_rate = data.sample_rate
    form.dedupe_window_seconds = data.dedupe_window_seconds
    form.dedupe_max_entries = data.dedupe_max_entries
    const hasCanary = (data.canary_percent || 0) > 0
    canary.enabled = hasCanary
    canary.percent = data.canary_percent || 10
    canary.sample_rate = data.canary?.sample_rate ?? ''
    canary.dedupe_window_seconds = data.canary?.dedupe_window_seconds ?? ''
    canary.dedupe_max_entries = data.canary?.dedupe_max_entries ?? ''
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const canaryPayload = canary.enabled ? {
      sample_rate: canary.sample_rate === '' ? undefined : Number(canary.sample_rate),
      dedupe_window_seconds: canary.dedupe_window_seconds === '' ? undefined : Number(canary.dedupe_window_seconds),
      dedupe_max_entries: canary.dedupe_max_entries === '' ? undefined : Number(canary.dedupe_max_entries),
    } : {}
    config.value = await api.putTelemetryConfig({
      sample_rate: form.sample_rate,
      dedupe_window_seconds: form.dedupe_window_seconds,
      dedupe_max_entries: form.dedupe_max_entries,
      canary_percent: canary.enabled ? canary.percent : 0,
      canary: canaryPayload,
    })
    pushToast('上报策略已生效')
  } catch (e) {
    pushToast(errorMessage(e), 'error')
  } finally {
    saving.value = false
  }
}

function applyPreset(rate: number, windowSeconds: number, maxEntries?: number) {
  form.sample_rate = rate
  form.dedupe_window_seconds = windowSeconds
  if (maxEntries != null) form.dedupe_max_entries = maxEntries
}

onMounted(load)
</script>

<template>
  <div class="telemetry-page">
    <PageHeader
      title="可观测配置"
      desc="前端错误上报的采样率与去重窗口，修改后立即影响 Sentry 转发；结构化日志始终全量记录。"
    >
      <button class="btn ghost" :disabled="loading" @click="load">
        <Icon name="refresh" :size="14" />{{ loading ? '加载中…' : '刷新' }}
      </button>
    </PageHeader>

    <div v-if="loading" class="card state-card"><StateBlock kind="loading" title="加载上报策略…" /></div>
    <div v-else-if="error" class="card state-card">
      <StateBlock kind="error" :message="error" retry-label="重新加载" @retry="load" />
    </div>
    <div v-else class="card config-card">
      <div class="config-head">
        <div class="config-heading">
          <div class="card-title">错误上报转发策略<span class="sub">{{ config?.source === 'database' ? '后台配置' : '环境变量默认' }}</span></div>
          <p>仅控制转发到 Sentry 的比例与频率；DSN 由服务端环境变量配置。</p>
        </div>
        <span class="badge" :class="config?.source === 'database' ? 'info' : 'muted'">
          {{ config?.source === 'database' ? '后台配置' : '环境变量' }}
        </span>
        <div class="spacer"></div>
        <button class="btn" :disabled="!canWrite || saving" @click="save">
          {{ saving ? '保存中…' : '保存并生效' }}
        </button>
      </div>

      <div class="config-body">
        <section class="config-section">
          <div class="section-title"><Icon name="telemetry-config" :size="14" />基础策略</div>
          <div class="form-grid cols-3">
            <label class="field">
              <span>采样率</span>
              <input v-model.number="form.sample_rate" class="input" type="number" min="0" max="1" step="0.05" :disabled="!canWrite" />
              <small>0 = 不转发，1 = 全量；按错误指纹稳定抽样。</small>
            </label>
            <label class="field">
              <span>去重窗口（秒）</span>
              <input v-model.number="form.dedupe_window_seconds" class="input" type="number" min="0" max="86400" step="10" :disabled="!canWrite" />
              <small>0 = 关闭去重；窗口内同一错误只转发一次。</small>
            </label>
            <label class="field">
              <span>去重容量上限（条）</span>
              <input v-model.number="form.dedupe_max_entries" class="input" type="number" min="1" max="1024" step="1" :disabled="!canWrite" />
              <small>单个指纹在 Redis 去重 zset 中保留的时间戳数。</small>
            </label>
          </div>
          <div class="preset-row">
            <span class="preset-label">快捷设置</span>
            <button v-if="canWrite" class="btn sm ghost" @click="applyPreset(1, 60)">全量</button>
            <button v-if="canWrite" class="btn sm ghost" @click="applyPreset(0.5, 60)">50%</button>
            <button v-if="canWrite" class="btn sm ghost" @click="applyPreset(0.1, 120)">10% 保守</button>
            <button v-if="canWrite" class="btn sm ghost" @click="applyPreset(0, 60, 16)">关闭转发</button>
          </div>
        </section>

        <section class="config-section">
          <div class="section-title">
            <Icon name="audit" :size="14" />灰度发布
            <span class="section-desc">按错误指纹稳定分桶，留空字段回退基线值</span>
            <span class="title-spacer"></span>
            <UiSelect
              v-model="canary.enabled"
              :disabled="!canWrite"
              :options="[
                { value: true, label: '开启' },
                { value: false, label: '关闭' },
              ]"
            />
          </div>
          <div v-if="canary.enabled" class="form-grid cols-4">
            <label class="field">
              <span>灰度流量比例（%）</span>
              <input v-model.number="canary.percent" class="input" type="number" min="0" max="100" step="5" :disabled="!canWrite" />
              <small>按 sha256 稳定分桶，100 = 全量灰度。</small>
            </label>
            <label class="field">
              <span>灰度采样率</span>
              <input v-model.number="canary.sample_rate" class="input" type="number" min="0" max="1" step="0.05" :disabled="!canWrite" placeholder="回退基线" />
              <small>留空使用基础策略值。</small>
            </label>
            <label class="field">
              <span>灰度去重窗口（秒）</span>
              <input v-model.number="canary.dedupe_window_seconds" class="input" type="number" min="0" max="86400" step="10" :disabled="!canWrite" placeholder="回退基线" />
              <small>留空使用基础策略值。</small>
            </label>
            <label class="field">
              <span>灰度去重容量</span>
              <input v-model.number="canary.dedupe_max_entries" class="input" type="number" min="1" max="1024" step="1" :disabled="!canWrite" placeholder="回退基线" />
              <small>留空使用基础策略值。</small>
            </label>
          </div>
          <div v-else class="canary-off">
            <div class="muted small">灰度发布已关闭，当前全部错误按基础策略转发。</div>
            <div class="canary-summary">
              <div><span>采样率</span><strong>{{ form.sample_rate }}</strong></div>
              <div><span>去重窗口</span><strong>{{ form.dedupe_window_seconds }} 秒</strong></div>
              <div><span>去重容量</span><strong>{{ form.dedupe_max_entries }} 条</strong></div>
            </div>
          </div>
        </section>
      </div>

      <div class="config-note">
        <Icon name="info" :size="14" />
        <span>多 worker 部署时，写入后本进程立即生效，其它进程最多 60 秒内收敛。<template v-if="config?.updated_at">最近更新：{{ formatTime(config.updated_at) }}</template></span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.telemetry-page { display: flex; flex-direction: column; gap: 14px; flex: 1; min-height: 0; }
.state-card { display: flex; align-items: center; justify-content: center; min-height: 220px; }
.config-card { flex: none; }
.config-head { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; flex-wrap: wrap; }
.config-heading .card-title { font-size: 14px; }
.config-heading p { font-size: 12px; color: var(--text-3); margin-top: 3px; line-height: 1.6; }
.config-body { display: grid; grid-template-columns: 1.25fr .75fr; gap: 12px; }
@media (max-width: 1000px) { .config-body { grid-template-columns: 1fr; } }
.config-section { background: var(--bg); border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px 14px; min-width: 0; }
.section-title { display: flex; align-items: center; gap: 6px; font-size: 12.5px; font-weight: 600; color: var(--text); margin-bottom: 10px; }
.section-title > svg { color: var(--primary); flex: none; }
.section-desc { font-size: 12px; font-weight: 400; color: var(--text-3); }
.title-spacer { flex: 1; }
.section-title .ui-select { width: 92px; flex: none; }
.preset-row { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; margin-top: 12px; }
.preset-label { font-size: 12px; color: var(--text-3); }
.canary-off { padding: 12px 0 4px; }
.canary-summary { display: grid; gap: 8px; margin-top: 12px; }
.canary-summary > div { display: flex; align-items: center; justify-content: space-between; padding: 8px 10px; border: 1px solid var(--border); border-radius: 8px; background: #fff; font-size: 12px; }
.canary-summary span { color: var(--text-3); }
.canary-summary strong { color: var(--text); font-variant-numeric: tabular-nums; }
.config-note {
  display: flex; align-items: flex-start; gap: 8px; margin-top: 12px; padding: 9px 12px;
  border-radius: 9px; background: var(--primary-bg); color: #0b6b62; font-size: 12px; line-height: 1.6;
}
.config-note svg { flex: none; margin-top: 1px; }
</style>
