<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errorMessage } from '../api'
import { can } from '../roles'
import { getRole } from '../session'
import { pushToast } from '../toast'
import type { BackupRow } from '../types'
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

onMounted(load)
</script>

<template>
  <div>
    <PageHeader
      title="备份管理"
      desc="数据库全量备份、下载与恢复。定时备份由服务端 SCHEDULER + BACKUP_* 环境变量控制；备份完成后自动发送通知邮件。"
    >
      <button class="btn" :disabled="!canWrite || busy === 'create'" @click="createBackup">
        <Icon name="refresh" :size="14" />{{ busy === 'create' ? '备份中…' : '立即备份' }}
      </button>
      <button class="btn ghost" :disabled="loading" @click="load">刷新</button>
    </PageHeader>

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
