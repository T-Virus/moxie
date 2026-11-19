<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errorMessage } from '../api'
import { can } from '../roles'
import { getRole } from '../session'
import { pushToast } from '../toast'
import type { BackupConfig, BackupConfigInput, BackupRow } from '../types'
import { formatNumber, formatTime } from '../ui'
import { confirm } from '../dialog'
import Icon from '../components/Icon.vue'
import Modal from '../components/Modal.vue'
import PageHeader from '../components/PageHeader.vue'
import RowActions, { type RowAction } from '../components/RowActions.vue'
import StateBlock from '../components/StateBlock.vue'
import UiSelect from '../components/UiSelect.vue'

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

const intervalLabel = computed(() =>
  intervalPresets.find((p) => p.value === (cfg.value?.interval_minutes ?? 0))?.label ||
  `每 ${cfg.value?.interval_minutes ?? '—'} 分钟`,
)
const notifyCount = computed(() =>
  (cfg.value?.notify_emails || '').split(',').map((s) => s.trim()).filter(Boolean).length,
)

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
  return `${cfg.value.schedule_enabled ? '已开启' : '已关闭'} · ${intervalLabel.value} · 保留 ${cfg.value.retention_count} 份`
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
  if (!await confirm({ title: '删除备份', message: `确认删除备份 ${row.id}？该操作不可恢复，备份文件将被永久移除。`, danger: true, confirmText: '确认删除' })) return
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

function backupActions(row: BackupRow): RowAction[] {
  return [
    { label: '下载', disabled: busy.value === row.id, run: () => download(row) },
    { label: '恢复', disabled: !canWrite.value || busy.value === row.id, run: () => openRestore(row) },
    { label: '删除', tone: 'danger', disabled: !canWrite.value || busy.value === row.id, run: () => remove(row) },
  ]
}
</script>

<template>
  <div class="backup-page">
    <PageHeader
      title="备份管理"
      desc="数据库全量备份、下载与恢复。定时备份策略保存后由独立 scheduler 服务自动执行，并将结果通知到指定邮箱。"
    >
      <button class="btn" :disabled="!canWrite || busy === 'create'" @click="createBackup">
        <Icon name="plus" :size="14" />{{ busy === 'create' ? '备份中…' : '立即备份' }}
      </button>
      <button class="btn ghost" :disabled="loading || cfgLoading" @click="load(); loadConfig()">
        <Icon name="refresh" :size="14" />刷新
      </button>
    </PageHeader>

    <div class="stat-grid backup-stats">
      <div class="stat-card teal">
        <div class="stat-top"><span class="stat-label">备份总数</span><span class="stat-ico"><Icon name="backups" :size="16" /></span></div>
        <div class="stat-value">{{ loading ? '—' : items.length }}</div>
        <div class="stat-desc">当前保留的全量快照</div>
      </div>
      <div class="stat-card purple">
        <div class="stat-top"><span class="stat-label">最近备份</span><span class="stat-ico"><Icon name="tasks" :size="16" /></span></div>
        <div class="stat-value stat-time">{{ items[0] ? formatTime(items[0].created_at) : '—' }}</div>
        <div class="stat-desc">{{ items[0] ? (items[0].trigger === 'scheduled' ? '由定时任务生成' : '手动触发') : '暂无备份记录' }}</div>
      </div>
      <div class="stat-card orange">
        <div class="stat-top"><span class="stat-label">定时策略</span><span class="stat-ico"><Icon name="retry" :size="16" /></span></div>
        <div class="stat-value">{{ cfgLoading ? '—' : (cfg?.schedule_enabled ? '运行中' : '已关闭') }}</div>
        <div class="stat-desc">{{ cfgLoading ? '读取配置中…' : intervalLabel }}</div>
      </div>
      <div class="stat-card red">
        <div class="stat-top"><span class="stat-label">邮件通知</span><span class="stat-ico"><Icon name="users" :size="16" /></span></div>
        <div class="stat-value">{{ cfgLoading ? '—' : (cfg?.email_enabled ? `${notifyCount} 人` : '未启用') }}</div>
        <div class="stat-desc">{{ cfgLoading ? '读取配置中…' : (cfg?.source === 'database' ? '后台配置已生效' : '环境变量默认值') }}</div>
      </div>
    </div>

    <div class="card config-card">
      <div class="card-head">
        <div class="card-title">定时备份策略<span class="sub">{{ cfgLoading ? '' : configSummary() }}</span></div>
        <div class="spacer"></div>
        <span v-if="cfg && !cfgLoading" class="badge" :class="cfg.source === 'database' ? 'info' : 'muted'">
          {{ cfg.source === 'database' ? '后台配置' : '环境变量默认' }}
        </span>
        <button class="btn sm" :disabled="!canWrite || cfgSaving || cfgLoading" @click="saveConfig">
          {{ cfgSaving ? '保存中…' : '保存配置' }}
        </button>
      </div>

      <div v-if="cfgLoading" class="config-loading"><span class="spinner"></span>正在读取配置…</div>
      <div v-else class="config-body">
        <div class="section-title"><Icon name="retry" :size="14" />执行计划</div>
        <div class="field">
          <label>定时备份</label>
          <UiSelect
            v-model="cfgForm.schedule_enabled"
            :disabled="!canWrite"
            :options="[
              { value: true, label: '开启' },
              { value: false, label: '关闭' },
            ]"
          />
        </div>
        <div class="field">
          <label>备份间隔</label>
          <UiSelect
            :model-value="intervalChoice"
            :disabled="!canWrite || !cfgForm.schedule_enabled"
            :options="[
              ...intervalPresets.map(p => ({ value: p.value, label: p.label })),
              { value: 0, label: '自定义（分钟）' },
            ]"
            @change="onIntervalChoice(Number($event))"
          />
        </div>
        <div class="field">
          <label>保留份数（1–90）</label>
          <input v-model.number="cfgForm.retention_count" class="input" type="number" min="1" max="90" :disabled="!canWrite" />
        </div>
        <div v-if="intervalChoice === 0" class="field span-all">
          <label>自定义间隔（分钟，5–10080）</label>
          <input
            v-model.number="cfgForm.interval_minutes"
            class="input"
            type="number"
            min="5"
            max="10080"
            :disabled="!canWrite || !cfgForm.schedule_enabled"
          />
        </div>

        <div class="section-title"><Icon name="users" :size="14" />邮件通知</div>
        <div class="field">
          <label>备份完成后发送通知邮件</label>
          <UiSelect
            v-model="cfgForm.email_enabled"
            :disabled="!canWrite"
            :options="[
              { value: true, label: '开启' },
              { value: false, label: '关闭' },
            ]"
          />
        </div>
        <div class="field span-2">
          <label>通知邮箱（逗号分隔，最多 20 个）</label>
          <input
            v-model="cfgForm.notify_emails"
            class="input"
            type="text"
            placeholder="ops@example.com, admin@example.com"
            :disabled="!canWrite || !cfgForm.email_enabled"
          />
          <span class="hint">复用服务端 SMTP 配置发送；留空则只落盘不发邮件。</span>
        </div>
      </div>

      <div class="config-note">
        <Icon name="warning" :size="14" />
        <span><strong>恢复边界</strong> 「暂存恢复」只生成校验后的副本与切换指引，不触碰当前库；「覆盖恢复」会中断连接并覆盖现有数据库，必须输入 <code>RESTORE</code> 二次确认。恢复前请先手动备份，并尽量在停机窗口执行。</span>
      </div>
    </div>

    <div class="card table-card">
      <div class="card-head">
        <div class="card-title">备份记录<span class="sub">共 {{ items.length }} 份</span></div>
        <div class="spacer"></div>
        <span class="muted small">按创建时间倒序 · 超过保留份数的备份会自动清理</span>
      </div>
      <div v-if="loading" class="state-wrap"><StateBlock kind="loading" title="加载备份列表…" /></div>
      <div v-else-if="error" class="state-wrap">
        <StateBlock kind="error" :message="error" retry-label="重新加载" @retry="load" />
      </div>
      <div v-else-if="!items.length" class="state-wrap">
        <StateBlock kind="empty" title="暂无备份">
          <button class="btn sm" :disabled="!canWrite" @click="createBackup">创建第一份备份</button>
        </StateBlock>
      </div>
      <div v-else class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th>备份 ID / 时间</th>
              <th>来源</th>
              <th>引擎</th>
              <th class="num">大小</th>
              <th>通知邮件</th>
              <th>校验值</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in items" :key="row.id">
              <td>
                <div class="mono id-cell truncate" :title="`${row.id} · ${formatTime(row.created_at)}`">{{ row.id }}</div>
              </td>
              <td><span class="badge" :class="row.trigger === 'scheduled' ? 'info' : 'muted'">{{ row.trigger === 'scheduled' ? '定时' : '手动' }}</span></td>
              <td><span class="badge muted">{{ row.engine }}</span></td>
              <td class="num"><span class="size-value">{{ sizeText(row.size_bytes) }}</span><span class="muted small size-bytes">{{ formatNumber(row.size_bytes) }} B</span></td>
              <td>
                <div class="truncate" :title="`${emailText(row)}${row.email?.error ? ` · ${row.email.error}` : ''}`">
                  <span class="badge" :class="row.email?.status === 'sent' ? 'success' : 'muted'">{{ emailText(row) }}</span>
                  <span v-if="row.email?.error" class="muted small"> · {{ row.email.error }}</span>
                </div>
              </td>
              <td class="mono small checksum" :title="row.checksum">{{ row.checksum.slice(0, 12) }}…</td>
              <td><RowActions :actions="backupActions(row)" /></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <Modal v-if="restoreTarget" title="恢复数据库" :subtitle="restoreTarget.id" @close="closeRestore">
      <div class="form-grid single-col">
        <div class="field">
          <label>恢复方式</label>
          <UiSelect
            v-model="restoreApply"
            :disabled="!canWrite"
            :options="[
              { value: false, label: '暂存恢复（推荐，不覆盖当前库）' },
              { value: true, label: '覆盖恢复（破坏性）' },
            ]"
          />
        </div>
        <div v-if="restoreApply" class="field">
          <label>输入 RESTORE 确认覆盖</label>
          <input v-model="restoreConfirm" class="input" type="text" autocomplete="off" />
          <span class="hint">覆盖后当前数据将被替换，且操作会写入审计日志。</span>
        </div>
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
.backup-page { display: flex; flex-direction: column; gap: 14px; flex: 1; min-height: 0; }

/* 状态总览 */
.backup-stats { flex: none; }
.stat-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.stat-ico { width: 28px; height: 28px; border-radius: 8px; display: inline-flex; align-items: center; justify-content: center; background: rgba(0,0,0,.04); }
.stat-card.teal .stat-ico { color: var(--primary); background: var(--primary-bg); }
.stat-card.purple .stat-ico { color: var(--purple); background: var(--purple-bg); }
.stat-card.orange .stat-ico { color: var(--orange); background: var(--orange-bg); }
.stat-card.red .stat-ico { color: var(--red); background: var(--red-bg); }
/* 四张卡的数值统一字号与颜色，避免数字 / 时间 / 状态大小参差 */
.backup-stats .stat-value {
  color: var(--text); line-height: 1.4;
  font-variant-numeric: tabular-nums; letter-spacing: 0;
}

/* 策略配置 */
.config-card { flex: none; }
.config-loading { display: flex; align-items: center; gap: 9px; color: var(--text-3); font-size: 12px; padding: 12px 0; }
.config-body { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px 14px; }
.config-body .span-2 { grid-column: span 2; }
.config-body .span-all { grid-column: 1 / -1; }
@media (max-width: 1000px) {
  .config-body { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 700px) {
  .config-body { grid-template-columns: 1fr; }
  .config-body .span-2, .config-body .span-all { grid-column: 1 / -1; }
}
.section-title {
  grid-column: 1 / -1;
  display: flex; align-items: center; gap: 6px;
  font-size: 12.5px; font-weight: 600; color: var(--text);
  padding-bottom: 7px; border-bottom: 1px dashed var(--border);
}
.section-title svg { color: var(--primary); }
.config-note {
  display: flex; align-items: flex-start; gap: 8px; margin-top: 14px; padding: 9px 12px;
  border-radius: 9px; background: var(--orange-bg); color: var(--orange); font-size: 12px; line-height: 1.6;
}
.config-note svg { flex: none; margin-top: 1px; }
.config-note strong { font-weight: 600; }
.config-note code { font-family: var(--mono); padding: 1px 5px; border-radius: 4px; background: rgba(255,255,255,.7); }

/* 备份列表 */
.table-card { flex: 1 1 auto; display: flex; flex-direction: column; min-height: 0; }
.table-card > .state-wrap { flex: 1 1 auto; min-height: 0; display: flex; align-items: center; justify-content: center; }
.table-card > .table-wrap { flex: 1 1 auto; min-height: 0; }
.id-cell { font-weight: 600; color: var(--text); }
.size-value { font-weight: 600; font-variant-numeric: tabular-nums; }
.size-bytes { margin-left: 5px; }
.checksum { color: var(--text-2); white-space: nowrap; }
</style>
