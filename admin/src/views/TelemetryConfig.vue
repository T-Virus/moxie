<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api, errorMessage } from '../api'
import { can } from '../roles'
import { getRole } from '../session'
import { pushToast } from '../toast'
import type { TelemetryConfig } from '../types'
import PageHeader from '../components/PageHeader.vue'
import StateBlock from '../components/StateBlock.vue'

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
  <div>
    <PageHeader
      title="可观测配置"
      desc="前端错误上报的采样率与去重窗口，修改后立即影响 Sentry 转发。"
    />

    <div v-if="loading" class="card">
      <StateBlock kind="loading" title="加载上报策略…" />
    </div>
    <div v-else-if="error" class="card">
      <StateBlock kind="error" :message="error" />
    </div>
    <div v-else class="card cfg">
      <div class="cfg__head">
        <div>
          <h2>错误上报转发策略</h2>
          <p class="muted">
            仅控制转发到 Sentry 的比例与频率；结构化日志始终全量记录。DSN 由服务端环境变量配置。
          </p>
        </div>
        <span class="badge" :class="config?.source === 'database' ? 'info' : 'muted'">
          生效来源：{{ config?.source === 'database' ? '后台配置' : '环境变量' }}
        </span>
      </div>

      <div class="cfg__grid">
        <label class="field">
          <span>采样率</span>
          <input
            v-model.number="form.sample_rate"
            type="number"
            min="0"
            max="1"
            step="0.05"
            :disabled="!canWrite"
          />
          <small>0 = 不转发，1 = 全量；按错误指纹稳定抽样，同一错误结果一致。</small>
        </label>
        <label class="field">
          <span>去重窗口（秒）</span>
          <input
            v-model.number="form.dedupe_window_seconds"
            type="number"
            min="0"
            max="86400"
            step="10"
            :disabled="!canWrite"
          />
          <small>0 = 关闭去重；窗口内同一错误只转发一次，Redis 可用时跨 worker 共享。</small>
        </label>
        <label class="field">
          <span>去重容量上限（条）</span>
          <input
            v-model.number="form.dedupe_max_entries"
            type="number"
            min="1"
            max="1024"
            step="1"
            :disabled="!canWrite"
          />
          <small>单个错误指纹在 Redis 去重 zset 中最多保留的时间戳数；防御时钟回拨导致的旧点堆积。</small>
        </label>
      </div>

      <div class="cfg__presets">
        <span class="muted">快捷设置：</span>
        <button v-if="canWrite" class="btn ghost sm" @click="applyPreset(1, 60)">全量</button>
        <button v-if="canWrite" class="btn ghost sm" @click="applyPreset(0.5, 60)">50%</button>
        <button v-if="canWrite" class="btn ghost sm" @click="applyPreset(0.1, 120)">10% 保守</button>
        <button v-if="canWrite" class="btn ghost sm" @click="applyPreset(0, 60, 16)">关闭转发</button>
      </div>

      <!-- 灰度发布：按错误指纹稳定分桶，同一错误永远走基线或灰度档中的同一档 -->
      <div class="cfg__canary">
        <div class="cfg__head" style="margin-bottom: 10px">
          <div>
            <h3>灰度发布</h3>
            <p class="muted">
              先让部分错误指纹走灰度档，观察 Sentry 用量与日志无异常后再全量。留空的字段回退基线值。
            </p>
          </div>
          <label class="badge" :class="canary.enabled ? 'info' : 'muted'" style="cursor: pointer">
            <input v-model="canary.enabled" type="checkbox" :disabled="!canWrite" />
            {{ canary.enabled ? '灰度开启' : '灰度关闭' }}
          </label>
        </div>
        <div v-if="canary.enabled" class="cfg__grid">
          <label class="field">
            <span>灰度流量比例（%）</span>
            <input v-model.number="canary.percent" type="number" min="0" max="100" step="5" :disabled="!canWrite" />
            <small>按错误指纹 sha256 稳定分桶；100 = 全量走灰度档。</small>
          </label>
          <label class="field">
            <span>灰度采样率（留空=基线）</span>
            <input v-model.number="canary.sample_rate" type="number" min="0" max="1" step="0.05" :disabled="!canWrite" placeholder="回退基线" />
          </label>
          <label class="field">
            <span>灰度去重窗口（秒，留空=基线）</span>
            <input v-model.number="canary.dedupe_window_seconds" type="number" min="0" max="86400" step="10" :disabled="!canWrite" placeholder="回退基线" />
          </label>
          <label class="field">
            <span>灰度去重容量（留空=基线）</span>
            <input v-model.number="canary.dedupe_max_entries" type="number" min="1" max="1024" step="1" :disabled="!canWrite" placeholder="回退基线" />
          </label>
        </div>
      </div>

      <p class="cfg__hint muted">
        多 worker 部署时，写入后本进程立即生效，其它进程最多 60 秒内收敛。
        <template v-if="config?.updated_at">最近更新：{{ config.updated_at }}</template>
      </p>

      <div v-if="canWrite" class="cfg__actions">
        <button class="btn primary" :disabled="saving" @click="save">
          {{ saving ? '保存中…' : '保存并生效' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cfg__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}
.cfg__head h2 { font-size: 16px; margin-bottom: 4px; }
.cfg__head p { font-size: 12px; max-width: 720px; line-height: 1.6; }
.cfg__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
}
.field { display: flex; flex-direction: column; gap: 6px; font-size: 13px; }
.field input {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--line, #d9e0ea);
  border-radius: 6px;
  background: var(--surface-2, #fff);
  color: inherit;
}
.field small { color: var(--muted, #6c7c93); font-size: 11px; line-height: 1.5; }
.cfg__presets { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 20px; font-size: 12px; }
.cfg__canary { margin-top: 24px; padding-top: 20px; border-top: 1px solid var(--line, #d9e0ea); }
.cfg__canary h3 { font-size: 14px; margin-bottom: 4px; }
.cfg__head h3 { font-size: 14px; margin-bottom: 4px; }
.cfg__hint { margin-top: 16px; font-size: 11px; line-height: 1.6; }
.cfg__actions { margin-top: 20px; display: flex; justify-content: flex-end; }
@media (max-width: 760px) { .cfg__grid { grid-template-columns: 1fr; } }
</style>
