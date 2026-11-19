<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errorMessage } from '../api'
import { can } from '../roles'
import { getRole } from '../session'
import { pushToast } from '../toast'
import type { BackupConfig, BackupConfigInput, BackupRow } from '../types'
import { formatNumber, formatTime } from '../ui'
import Icon from '../components/Icon.vue'
import Modal from '../components/Modal.vue'
import PageHeader from '../components/PageHeader.vue'
import StateBlock from '../components/StateBlock.vue'

const canWrite = computed(() => can(getRole(), 'backup:write'))
const loading = ref(true)
const busy = ref('')
const error = ref('')
const items = ref<BackupRow[]>([])
const restoreTarget = ref<BackupRow | null>(null)
const restoreApply = ref(false)
const restoreConfirm = ref('')

// 定时备份策略配置
const cfgLoading = ref(true)
const cfgSaving = ref(false)
const cfg = ref<BackupConfig | null>(null)
const cfgForm = ref<BackupConfigInput>({
  schedule_enabled: false,
  interval_minutes: 720,
  email_enabled: false,
  notify_emails: '',
  retention_count: 14,
})
// 间隔预设：值(分钟) → 文案；0 表示自定义
const intervalPresets = [
  { value: 360, label: '每 6 小时' },
  { value: 720, label: '每 12 小时' },
  { value: 1440, label: '每天' },
  { value: 10080, label: '每周' },
]
const intervalChoice = computed(() => {
  const m = cfgForm.value.interval_minutes
  return intervalPresets.some((p) => p.value === m) ? m : 0
})
function onIntervalChoice(value: number): void {
  if (value > 0) cfgForm.value.interval_minutes = value
}

async function loadConfig(): Promise<void> {
  cfgLoading.value = true
  try {
    const data = await api.backupConfig()
    cfg.value = data
    cfgForm.value = {
      schedule_enabled: data.schedule_enabled,
      interval_minutes: data.interval_minutes,
      email_enabled: data.email_enabled,
      notify_emails: data.notify_emails,
      retention_count: data.retention_count,
    }
  } catch (e) {
    pushToast(errorMessage(e), 'error')
  } finally {
    cfgLoading.value = false
  }
}

async function saveConfig(): Promise<void> {
  cfgSaving.value = true
  try {
    const saved = await api.updateBackupConfig({ ...cfgForm.value })
    cfg.value = saved
    cfgForm.value.notify_emails = saved.notify_emails
    pushToast('定时备份配置已保存并生效')
  } catch (e) {
    pushToast(errorMessage(e), 'error')
  } finally {
    cfgSaving.value = false
  }
}

function configSummary(): string {
  if (!cfg.value) return ''
  const interval =
    intervalPresets.find((p) => p.value === cfg.value!.interval_minutes)?.label ||
    `每 ${cfg.value.interval_minutes} 分钟`
  return `${cfg.value.schedule_enabled ? '已开启' : '已关闭'} · ${interval} · 保留 ${cfg.value.retention_count} 份`
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    items.value = (await api.backups()).items || []
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

async function createBackup(): Promise<void> {
  busy.value = 'create'
  try {
    const result = await api.createBackup()
    pushToast(`备份已创建：${result.item.id}`)
    await load()
  } catch (e) {
    pushToast(errorMessage(e), 'error')
  } finally {
    busy.value = ''
  }
}

async function download(row: BackupRow): Promise<void> {
  busy.value = row.id
  try {
    await api.downloadBackup(row.id)
    pushToast('备份压缩包已开始下载')
  } catch (e) {
    pushToast(errorMessage(e), 'error')
  } finally {
    busy.value = ''
  }
}

function openRestore(row: BackupRow): void {
  restoreTarget.value = row
  restoreApply.value = false
  restoreConfirm.value = ''
}

function closeRestore(): void {
  restoreTarget.value = null
}

async function confirmRestore(): Promise<void> {
  const row = restoreTarget.value
  if (!row) return
  if (restoreApply.value && restoreConfirm.value.trim() !== 'RESTORE') {
    pushToast('请先输入 RESTORE 确认破坏性恢复', 'error')
    return
  }
  busy.value = row.id
  try {
    const result = await api.restoreBackup(row.id, restoreApply.value, restoreConfirm.value.trim())
    pushToast(
      result.mode === 'applied'
        ? '数据库已恢复，请确认服务状态并核对数据'
        : `已生成暂存副本：${result.path || ''}`,
    )
    closeRestore()
    if (result.mode === 'applied') await load()
  } catch (e) {
    pushToast(errorMessage(e), 'error')
  } finally {
    busy.value = ''
  }
}

async function remove(row: BackupRow): Promise<void> {
  if (!window.confirm(`确认删除备份 ${row.id}？该操作不可恢复。`)) return
  busy.value = row.id
  try {
    await api.deleteBackup(row.id)
    pushToast('备份已删除')
    await load()
  } catch (e) {
    pushToast(errorMessage(e), 'error')
  } finally {
    busy.value = ''
  }
}

function sizeText(value: number): string {
  if (!value) return '—'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

function emailText(row: BackupRow): string {
  const status = row.email?.status || 'unknown'
  return { sent: '邮件已发送', fake: '模拟发送', skipped: '未发送', failed: '发送失败', pending: '发送中' }[status] || status
}

onMounted(() => {
  load()
  loadConfig()
})
</script>

<template>
  <div>
    <PageHeader
      title="备份管理"
      desc="数据库全量备份、下载与恢复。定时备份策略可在此配置，由独立 scheduler 服务按间隔自动执行，完成后发送通知邮件。"
    >
      <button class="btn" :disabled="!canWrite || busy === 'create'" @click="createBackup">
        <Icon name="refresh" :size="14" />{{ busy === 'create' ? '备份中…' : '立即备份' }}
      </button>
      <button class="btn ghost" :disabled="loading || cfgLoading" @click="load(); loadConfig()">刷新</button>
    </PageHeader>

    <div class="card config-card">
      <div class="config-head">
        <div>
          <h3>定时备份策略</h3>
          <p class="muted small">
            {{ cfgLoading ? '加载中…' : configSummary() }}
            <span v-if="cfg && cfg.source === 'database'" class="badge info">后台配置</span>
            <span v-else class="badge muted">环境变量默认</span>
          </p>
        </div>
        <button
          class="btn sm"
          :disabled="!canWrite || cfgSaving || cfgLoading"
          @click="saveConfig"
        >
          {{ cfgSaving ? '保存中…' : '保存配置' }}
        </button>
      </div>
      <div v-if="cfgLoading" class="muted small">正在读取配置…</div>
      <div v-else class="config-grid">
        <label class="field">
          <span>启用定时备份</span>
          <select v-model="cfgForm.schedule_enabled" :disabled="!canWrite">
            <option :value="true">开启（scheduler 自动执行）</option>
            <option :value="false">关闭</option>
          </select>
        </label>
        <label class="field">
          <span>备份间隔</span>
          <select
            :value="intervalChoice"
            :disabled="!canWrite || !cfgForm.schedule_enabled"
            @change="onIntervalChoice(+($event.target as HTMLSelectElement).value)"
          >
            <option v-for="p in intervalPresets" :key="p.value" :value="p.value">{{ p.label }}</option>
            <option :value="0">自定义（分钟）</option>
          </select>
        </label>
        <label class="field">
          <span>自定义间隔（分钟，5–10080）</span>
          <input
            v-model.number="cfgForm.interval_minutes"
            type="number"
            min="5"
            max="10080"
            :disabled="!canWrite || !cfgForm.schedule_enabled || intervalChoice > 0"
          />
          <small>留用预设时此项只读；选择「自定义」后可填 5–10080 分钟。</small>
        </label>
        <label class="field">
          <span>保留份数（1–90）</span>
          <input v-model.number="cfgForm.retention_count" type="number" min="1" max="90" :disabled="!canWrite" />
        </label>
        <label class="field config-span">
          <span>通知邮箱（逗号分隔，最多 20 个）</span>
          <input
            v-model="cfgForm.notify_emails"
            type="text"
            placeholder="ops@example.com, admin@example.com"
            :disabled="!canWrite"
          />
          <small>复用服务端 SMTP 配置发送；留空则只落盘不发邮件。</small>
        </label>
        <label class="field config-span inline">
          <input v-model="cfgForm.email_enabled" type="checkbox" :disabled="!canWrite" />
          <span>备份完成后发送通知邮件</span>
        </label>
      </div>
    </div>

    <div class="card notice">
      <strong>恢复边界</strong>
      <p>
        「暂存恢复」只生成校验后的副本与切换指引，不触碰当前库；「覆盖恢复」会中断连接并覆盖现有数据库，
        必须输入 <code>RESTORE</code> 二次确认。恢复前请先手动备份，并尽量在停机窗口执行。
      </p>
    </div>

    <div v-if="loading" class="card"><StateBlock kind="loading" title="加载备份列表…" /></div>
    <div v-else-if="error" class="card"><StateBlock kind="error" :message="error" /></div>
    <div v-else-if="!items.length" class="card"><StateBlock kind="empty" title="暂无备份" /></div>
    <div v-else class="card table-card">
      <table class="table">
        <thead>
          <tr>
            <th>备份 ID / 时间</th>
            <th>来源</th>
            <th>引擎</th>
            <th>大小</th>
            <th>通知邮件</th>
            <th>校验值</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in items" :key="row.id">
            <td>
              <div class="mono">{{ row.id }}</div>
              <div class="muted small">{{ formatTime(row.created_at) }}</div>
            </td>
            <td><span class="badge" :class="row.trigger === 'scheduled' ? 'info' : 'muted'">{{ row.trigger === 'scheduled' ? '定时' : '手动' }}</span></td>
            <td>{{ row.engine }}</td>
            <td>{{ sizeText(row.size_bytes) }} <span class="muted small">/ {{ formatNumber(row.size_bytes) }} B</span></td>
            <td>
              <span class="badge" :class="row.email?.status === 'sent' ? 'success' : 'muted'">{{ emailText(row) }}</span>
              <span v-if="row.email?.error" class="muted small"> · {{ row.email.error }}</span>
            </td>
            <td class="mono small" :title="row.checksum">{{ row.checksum.slice(0, 12) }}…</td>
            <td>
              <div class="actions">
                <button class="btn ghost sm" :disabled="busy === row.id" @click="download(row)">下载</button>
                <button class="btn ghost sm" :disabled="!canWrite || busy === row.id" @click="openRestore(row)">恢复</button>
                <button class="btn danger sm" :disabled="!canWrite || busy === row.id" @click="remove(row)">删除</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <Modal v-if="restoreTarget" title="恢复数据库" :subtitle="restoreTarget.id" @close="closeRestore">
      <div class="restore-form">
        <label class="field">
          <span>恢复方式</span>
          <select v-model="restoreApply" :disabled="!canWrite">
            <option :value="false">暂存恢复（推荐，不覆盖当前库）</option>
            <option :value="true">覆盖恢复（破坏性）</option>
          </select>
        </label>
        <label v-if="restoreApply" class="field">
          <span>输入 RESTORE 确认覆盖</span>
          <input v-model="restoreConfirm" type="text" autocomplete="off" />
          <small>覆盖后当前数据将被替换，且操作会写入审计日志。</small>
        </label>
      </div>
      <template #footer>
        <button class="btn ghost" @click="closeRestore">取消</button>
        <button
          class="btn"
          :class="restoreApply ? 'danger' : ''"
          :disabled="busy === restoreTarget.id || (restoreApply && restoreConfirm.trim() !== 'RESTORE')"
          @click="confirmRestore"
        >
          {{ restoreApply ? '确认覆盖恢复' : '生成暂存副本' }}
        </button>
      </template>
    </Modal>
  </div>
</template>

<style scoped>
.config-card { margin-bottom: 16px; }
.config-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.config-head h3 { margin: 0 0 4px; font-size: 15px; }
.config-head .badge { margin-left: 8px; }
.config-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.config-span { grid-column: 1 / -1; }
.config-grid .field { display: flex; flex-direction: column; gap: 6px; }
.config-grid .field.inline { flex-direction: row; align-items: center; gap: 8px; }
.config-grid input[type='checkbox'] { width: auto; }
@media (max-width: 720px) { .config-grid { grid-template-columns: 1fr; } }
.notice p { margin: 6px 0 0; line-height: 1.6; }
.notice code { color: var(--c-primary, #4f8ef7); }
.table-card { overflow-x: auto; }
.table { width: 100%; border-collapse: collapse; }
.table th, .table td { padding: 10px 12px; border-bottom: 1px solid var(--line, #e5e8ee); text-align: left; vertical-align: middle; }
.table th { font-size: 12px; color: var(--muted, #6b7280); font-weight: 600; }
.actions { display: flex; gap: 6px; flex-wrap: wrap; }
.restore-form { display: grid; gap: 14px; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
.small { font-size: 12px; }
</style>
