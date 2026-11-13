<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api, downloadBlob, errorMessage, normalizeList } from '../api'
import { can } from '../roles'
import { getRole } from '../session'
import { pushToast } from '../toast'
import Icon from '../components/Icon.vue'
import PageHeader from '../components/PageHeader.vue'
import StateBlock from '../components/StateBlock.vue'

const role = getRole()
const canWrite = computed(() => can(role, 'offline_package:write'))

const rows = ref<any[]>([])
const loading = ref(false)
const error = ref('')

const maxBytes = ref(0)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await api.offlinePackages()
    rows.value = normalizeList<any>({ items: Array.isArray(data) ? data : [] }).items
  } catch (e) {
    rows.value = []
    error.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

async function loadLimits() {
  try {
    const data = await api.offlinePackageLimits()
    maxBytes.value = Number(data?.max_bytes) || 0
  } catch {
    maxBytes.value = 0 // 取不到上限不影响上传，仅少一层前置校验
  }
}

onMounted(() => {
  void load()
  void loadLimits()
})

const PLATFORM_LABEL: Record<string, string> = { windows: 'Windows', android: 'Android' }

function formatBytes(n: number): string {
  if (!n) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(n) / Math.log(1024))
  return `${(n / 1024 ** i).toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

const form = reactive({ platform: 'windows', version: '', release_notes: '' })
const file = ref<File | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false)
const uploadError = ref('')

function onFileChange(e: Event) {
  const target = e.target as HTMLInputElement
  file.value = target.files?.[0] ?? null
  uploadError.value = ''
  const picked = file.value
  if (picked && maxBytes.value && picked.size > maxBytes.value) {
    uploadError.value = `文件 ${formatBytes(picked.size)} 超过服务端上限 ${formatBytes(maxBytes.value)}，请先调大 offline_package_max_bytes`
  }
}

async function submitUpload() {
  if (!file.value) {
    uploadError.value = '请选择安装包文件'
    return
  }
  if (maxBytes.value && file.value.size > maxBytes.value) {
    uploadError.value = `文件 ${formatBytes(file.value.size)} 超过服务端上限 ${formatBytes(maxBytes.value)}，未发起上传`
    return
  }
  const fd = new FormData()
  fd.append('platform', form.platform)
  if (form.version.trim()) fd.append('version', form.version.trim())
  if (form.release_notes.trim()) fd.append('release_notes', form.release_notes.trim())
  fd.append('file', file.value)
  uploading.value = true
  uploadError.value = ''
  try {
    await api.uploadOfflinePackage(fd)
    pushToast('安装包已上传，并已设为该平台当前版本')
    form.version = ''
    form.release_notes = ''
    file.value = null
    if (fileInput.value) fileInput.value.value = ''
    await load()
  } catch (e) {
    const msg = errorMessage(e)
    uploadError.value =
      msg.includes('无法连接') && file.value
        ? `${msg}。已选文件 ${formatBytes(file.value.size)}：若上传中途断开，多为体积超过上限或代理/网关超时（开发代理需重启才生效）。`
        : msg
  } finally {
    uploading.value = false
  }
}

async function onDownload(row: any) {
  try {
    await downloadBlob(`/v1/admin/offline-packages/${row.id}/download`, row.filename)
  } catch (e) {
    pushToast(errorMessage(e))
  }
}

const deleting = ref(false)
async function remove(row: any) {
  if (!confirm(`确认删除「${PLATFORM_LABEL[row.platform] || row.platform} ${row.version}」安装包？`)) return
  deleting.value = true
  try {
    await api.deleteOfflinePackage(row.id)
    pushToast('已删除该安装包')
    await load()
  } catch (e) {
    pushToast(errorMessage(e))
  } finally {
    deleting.value = false
  }
}
</script>

<template>
  <PageHeader title="离线安装包" desc="由后台上传纳管 Windows / Android 安装包，自动设为当前下载版本；用户端 /downloads 优先取此处配置。">
    <span v-if="!canWrite" class="badge muted">只读</span>
    <button class="btn ghost sm" :disabled="loading" @click="load">
      <Icon name="refresh" :size="14" />刷新
    </button>
  </PageHeader>

  <div v-if="canWrite" class="card upload-card">
    <h3 class="upload-card__title">上传新版本</h3>
    <div class="upload-grid">
      <div class="field">
        <label>平台</label>
        <select v-model="form.platform" class="select">
          <option value="windows">Windows（.exe）</option>
          <option value="android">Android（.apk）</option>
        </select>
      </div>
      <div class="field">
        <label>版本号</label>
        <input v-model="form.version" class="input" placeholder="留空则从文件名解析，如 v1.2.3" />
      </div>
      <div class="field">
        <label>安装包文件</label>
        <input ref="fileInput" type="file" class="input" accept=".exe,.apk" @change="onFileChange" />
        <span class="hint" style="font-size: 12px">
          {{ file ? `已选 ${formatBytes(file.size)}` : '可上传 .exe / .apk' }}
          <template v-if="maxBytes">· 单文件上限 {{ formatBytes(maxBytes) }}</template>
        </span>
      </div>
    </div>
    <div class="field">
      <label>更新说明（可选）</label>
      <textarea v-model="form.release_notes" class="input" rows="2" placeholder="本次安装包更新内容"></textarea>
    </div>
    <div v-if="uploadError" class="notice error" style="margin: 10px 0 0">{{ uploadError }}</div>
    <div class="upload-card__actions">
      <button class="btn" :disabled="uploading" @click="submitUpload">
        {{ uploading ? '上传中…' : '上传并发布' }}
      </button>
    </div>
  </div>

  <div class="card">
    <div v-if="loading && !rows.length" class="state-loading">
      <StateBlock kind="loading" title="正在加载安装包…" />
    </div>
    <div v-else-if="error">
      <StateBlock kind="error" :title="error" retry-label="重试" @retry="load" />
    </div>
    <div v-else-if="!rows.length">
      <StateBlock kind="empty" title="尚未上传任何安装包" />
    </div>
    <template v-else>
      <div class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th>平台</th>
              <th>版本</th>
              <th>文件名</th>
              <th>大小</th>
              <th style="width: 80px">当前</th>
              <th>更新说明</th>
              <th>上传时间</th>
              <th style="width: 150px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.id">
              <td>{{ PLATFORM_LABEL[row.platform] || row.platform }}</td>
              <td class="mono">{{ row.version }}</td>
              <td class="mono" style="font-size: 12px">{{ row.filename }}</td>
              <td>{{ formatBytes(row.size) }}</td>
              <td>
                <StatusBadge v-if="row.is_active" value="active" dot />
                <span v-else class="badge muted">历史</span>
              </td>
              <td class="notes">{{ row.release_notes || '—' }}</td>
              <td class="muted">{{ row.created_at ? row.created_at.replace('T', ' ').slice(0, 19) : '—' }}</td>
              <td>
                <div class="actions">
                  <button class="btn ghost sm" @click="onDownload(row)">下载</button>
                  <button v-if="canWrite" class="btn danger-ghost sm" :disabled="deleting" @click="remove(row)">删除</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="muted" style="font-size: 12px; margin: 12px 2px 0">
        上传后该平台历史版本自动置为「历史」；删除当前版本会自动把该平台最新剩余记录提升为当前。用户端工具下载页读取 /downloads，优先返回此处当前版本。
      </p>
    </template>
  </div>
</template>

<style scoped>
.state-loading { padding: 10px 0; }
.upload-card { margin-bottom: 16px; }
.upload-card__title { margin: 0 0 14px; font-size: 15px; }
.upload-grid { display: grid; grid-template-columns: 1fr 1fr 1.4fr; gap: 14px; }
.upload-card__actions { margin-top: 14px; display: flex; justify-content: flex-end; }
.field { margin-bottom: 12px; }
.field > label { display: block; font-size: 12.5px; margin-bottom: 6px; color: #c7d0e0; }
.notes { max-width: 240px; font-size: 12.5px; color: #c7d0e0; }
@media (max-width: 720px) {
  .upload-grid { grid-template-columns: 1fr; }
}
</style>
