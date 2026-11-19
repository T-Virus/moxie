<template>
  <div class="byok">
    <div class="byok__head">
      <div>
        <h3 class="byok__title">自有模型 Key（BYOK）</h3>
        <p class="byok__hint">
          填写你自己的模型服务，创建/续跑任务时使用它替换平台模型，不占用平台额度。
          配置仅保存在当前浏览器会话，服务端只做短期内存缓存，不落库、不写日志。
        </p>
      </div>
      <span class="badge" :class="byokEnabled ? 'badge--success' : ''">
        {{ byokEnabled ? '已启用' : '未启用' }}
      </span>
    </div>

    <div class="byok__presets">
      <span class="byok__presets-label">快捷选择</span>
      <button
        v-for="preset in BYOK_PRESETS"
        :key="preset.label"
        type="button"
        class="byok__preset"
        :class="{ 'is-active': byokPreset === preset.label }"
        @click="applyPreset(preset)"
      >
        {{ preset.label }}
      </button>
    </div>

    <div class="field byok__field">
      <label class="field__label" for="byok-key">API Key</label>
      <input
        id="byok-key"
        v-model="byokInput"
        class="byok__input"
        type="password"
        autocomplete="off"
        spellcheck="false"
        placeholder="粘贴你的模型 API Key（仅本次会话）"
        @keyup.enter="saveByok"
      />
    </div>
    <div class="byok__grid">
      <div class="field byok__field">
        <label class="field__label" for="byok-model">模型名 <span class="byok__hint-inline">（留空用服务端默认）</span></label>
        <input
          id="byok-model"
          v-model="byokModel"
          class="byok__input"
          type="text"
          autocomplete="off"
          spellcheck="false"
          placeholder="例如 gpt-4o / deepseek-chat"
        />
      </div>
      <div class="field byok__field">
        <label class="field__label" for="byok-base-url">接口地址 <span class="byok__hint-inline">（OpenAI 兼容，留空用默认）</span></label>
        <input
          id="byok-base-url"
          v-model="byokBaseUrl"
          class="byok__input"
          type="text"
          autocomplete="off"
          spellcheck="false"
          placeholder="例如 https://api.openai.com/v1"
        />
      </div>
    </div>
    <p class="byok__note">模型名与接口地址必须是 OpenAI Chat Completions 兼容格式；接口地址仅允许 HTTPS 公网地址。</p>
    <div class="byok__row">
      <button type="button" class="btn btn--brand btn--sm" :disabled="!byokInput" @click="saveByok">保存</button>
      <button type="button" class="btn btn--ghost btn--sm" :disabled="!byokEnabled" @click="clearByok">清除</button>
    </div>
    <p v-if="byokError" class="account__error" role="alert">{{ byokError }}</p>
    <p v-if="byokInfo" class="byok__status" role="status">{{ byokInfo }}</p>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { clearByokKey, getByokConfig, hasByokKey, setByokConfig, type ByokConfig } from '@/services/byok'

interface ByokPreset {
  label: string
  model: string
  baseUrl: string
}

// 常见 OpenAI 兼容服务；仅为便捷填充，用户仍可修改模型名与地址
const BYOK_PRESETS: ByokPreset[] = [
  { label: 'OpenAI', model: 'gpt-4o-mini', baseUrl: 'https://api.openai.com/v1' },
  { label: 'DeepSeek', model: 'deepseek-chat', baseUrl: 'https://api.deepseek.com' },
  { label: '通义千问', model: 'qwen-plus', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
  { label: '自定义', model: '', baseUrl: '' },
]

const byokInput = ref('')
const byokModel = ref('')
const byokBaseUrl = ref('')
const byokPreset = ref('')
const byokEnabled = ref(false)
const byokInfo = ref('')
const byokError = ref('')

function loadByok(): void {
  const cfg: ByokConfig = getByokConfig()
  byokEnabled.value = hasByokKey()
  byokInput.value = ''
  byokModel.value = cfg.model
  byokBaseUrl.value = cfg.baseUrl
  const matched = BYOK_PRESETS.find((p) => p.label !== '自定义' && p.baseUrl === cfg.baseUrl)
  byokPreset.value = matched?.label || (cfg.baseUrl ? '自定义' : '')
  if (byokEnabled.value) {
    const detail = [cfg.model && `模型 ${cfg.model}`, cfg.baseUrl && `网关 ${cfg.baseUrl}`]
      .filter(Boolean)
      .join('，')
    byokInfo.value = detail
      ? `当前会话已启用 BYOK（${detail}），不占用平台模型账单。`
      : '当前会话已启用 BYOK：任务使用你的模型 Key，不占用平台模型账单。'
  } else {
    byokInfo.value = '未配置自有 Key，任务将使用平台额度与平台模型。'
  }
}

function applyPreset(preset: ByokPreset): void {
  byokPreset.value = preset.label
  byokModel.value = preset.model
  byokBaseUrl.value = preset.baseUrl
}

function saveByok(): void {
  const key = byokInput.value.trim()
  if (!key) return
  setByokConfig({ key, model: byokModel.value.trim(), baseUrl: byokBaseUrl.value.trim() })
  byokInput.value = ''
  byokError.value = ''
  loadByok()
}

function clearByok(): void {
  clearByokKey()
  byokModel.value = ''
  byokBaseUrl.value = ''
  byokPreset.value = ''
  byokError.value = ''
  loadByok()
}

onMounted(() => {
  loadByok()
})
</script>

<style scoped>
.byok {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.byok__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--color-border, var(--border, #e5e7eb));
}

.byok__title {
  font-size: 17px;
  font-weight: 600;
  color: var(--color-text);
  margin: 0 0 6px;
}

.byok__hint,
.byok__note,
.byok__status {
  font-size: var(--text-sm);
  color: var(--color-text-2);
  line-height: 1.7;
  margin: 0;
}
.byok__hint {
  max-width: 640px;
}

.byok__presets {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.byok__presets-label,
.byok__hint-inline {
  font-size: var(--text-xs);
  color: var(--color-text-3);
}

.byok__preset {
  padding: 5px 12px;
  border: 1px solid var(--color-border, var(--border));
  border-radius: var(--radius-pill, 999px);
  background: var(--color-bg-soft, var(--surface-2));
  color: var(--color-text-2);
  font-size: var(--text-xs);
  cursor: pointer;
}
.byok__preset:hover {
  border-color: var(--color-brand);
  color: var(--color-brand);
}
.byok__preset.is-active {
  border-color: var(--color-brand);
  background: var(--color-brand);
  color: #fff;
}

.byok__field {
  margin: 0;
}

.byok__input {
  width: 100%;
  padding: 9px 12px;
  border: 1px solid var(--color-border, var(--border));
  border-radius: var(--radius-md, 8px);
  background: var(--color-bg-soft, var(--surface-2));
  color: var(--color-text);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: var(--text-sm);
}

.byok__grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr);
  gap: 16px;
}

.byok__row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.account__error {
  font-size: var(--text-xs);
  color: var(--color-danger);
  margin: 0;
}

@media (max-width: 640px) {
  .byok__grid {
    grid-template-columns: 1fr;
  }
  .byok__head {
    flex-direction: column;
  }
}
</style>
