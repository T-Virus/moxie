<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api, downloadBlob, errorMessage, normalizeList } from '../api'
import { can } from '../roles'
import { getRole } from '../session'
import { pushToast } from '../toast'
import { confirm } from '../dialog'
import { formatTime } from '../ui'
import Icon from '../components/Icon.vue'
import PageHeader from '../components/PageHeader.vue'
import RowActions, { type RowAction } from '../components/RowActions.vue'
import StateBlock from '../components/StateBlock.vue'
import StatusBadge from '../components/StatusBadge.vue'
import UiSelect from '../components/UiSelect.vue'

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
    rows.value = normalizeList<any>(data).items
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
    maxBytes.value = 0
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

/** 清空已选文件，同步重置原生 input，避免再次选同一文件不触发 change */
function clearFile() {
  file.value = null
  uploadError.value = ''
  if (fileInput.value) fileInput.value.value = ''
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
  if (!await confirm({ title: '删除安装包', message: `确认删除「${PLATFORM_LABEL[row.platform] || row.platform} ${row.version}」安装包？客户端将无法再下载该版本。`, danger: true, confirmText: '确认删除' })) return
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

function packageActions(row: any): RowAction[] {
  const actions: RowAction[] = [{ label: '下载', tone: 'primary', run: () => onDownload(row) }]
  if (canWrite.value) actions.push({ label: '删除', tone: 'danger', disabled: deleting.value, run: () => remove(row) })
  return actions
}
</script>

<template>
  <div class="packages-page">
    <PageHeader title="离线安装包" desc="由后台上传纳管 Windows / Android 安装包，自动设为当前下载版本；用户端 /downloads 优先取此处配置。">
      <span v-if="!canWrite" class="badge muted">只读</span>
      <button class="btn ghost" :disabled="loading" @click="load">
        <Icon name="refresh" :size="14" />{{ loading ? '加载中…' : '刷新' }}
      </button>
    </PageHeader>

    <div v-if="canWrite" class="card upload-card">
      <div class="card-head">
        <div class="card-title">上传新版本<span class="sub">上传后自动设为该平台当前版本</span></div>
        <div class="spacer"></div>
        <span v-if="maxBytes" class="muted small">单文件上限 {{ formatBytes(maxBytes) }}</span>
      </div>
      <div class="form-grid">
        <div class="field">
          <label>平台</label>
          <UiSelect
            v-model="form.platform"
            :options="[
              { value: 'windows', label: 'Windows（.exe）' },
              { value: 'android', label: 'Android（.apk）' },
            ]"
          />
        </div>
        <div class="field">
          <label>版本号</label>
          <input v-model="form.version" class="input" type="text" placeholder="留空则从文件名解析，如 v1.2.3" />
        </div>
      </div>

      <div class="field upload-field">
        <label>安装包文件</label>
        <div class="dropzone" :class="{ filled: !!file }" role="button" tabindex="0"
          @click="fileInput?.click()" @keydown.enter.prevent="fileInput?.click()">
          <template v-if="!file">
            <Icon name="plus" :size="15" />
            <span>点击选择文件，支持 .exe / .apk{{ maxBytes ? `，不超过 ${formatBytes(maxBytes)}` : '' }}</span>
          </template>
          <template v-else>
            <Icon name="download" :size="15" class="dz-icon" />
            <span class="dz-name" :title="file.name">{{ file.name }}</span>
            <span class="dz-size">{{ formatBytes(file.size) }}</span>
            <button type="button" class="file-clear" title="移除" @click.stop="clearFile">
              <Icon name="close" :size="12" />
            </button>
          </template>
        </div>
        <input ref="fileInput" type="file" class="file-hidden" accept=".exe,.apk" @change="onFileChange" />
      </div>

      <div class="field upload-field">
        <label>更新说明（可选）</label>
        <textarea v-model="form.release_notes" class="textarea" rows="2" placeholder="本次安装包更新内容"></textarea>
      </div>

      <div v-if="uploadError" class="notice error">{{ uploadError }}</div>
      <div class="upload-actions">
        <button class="btn" :disabled="uploading" @click="submitUpload">
          <Icon name="plus" :size="14" />{{ uploading ? '上传中…' : '上传并发布' }}
        </button>
      </div>
    </div>

    <div class="card table-card">
      <div class="card-head">
        <div class="card-title">版本列表<span class="sub">共 {{ rows.length }} 个安装包</span></div>
        <div class="spacer"></div>
        <span class="muted small">历史版本自动置为「历史」，删除当前版本将自动提升最新记录</span>
      </div>
      <div v-if="loading && !rows.length" class="state-wrap"><StateBlock kind="loading" title="正在加载安装包…" /></div>
      <div v-else-if="error" class="state-wrap">
        <StateBlock kind="error" :message="error" retry-label="重新加载" @retry="load" />
      </div>
      <div v-else-if="!rows.length" class="state-wrap"><StateBlock kind="empty" title="尚未上传任何安装包" /></div>
      <div v-else class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th>平台</th>
              <th>版本</th>
              <th>文件名</th>
              <th class="num">大小</th>
              <th>当前</th>
              <th>更新说明</th>
              <th>上传时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.id">
              <td>{{ PLATFORM_LABEL[row.platform] || row.platform }}</td>
              <td class="mono">{{ row.version }}</td>
              <td class="mono small filename">{{ row.filename }}</td>
              <td class="num">{{ formatBytes(row.size) }}</td>
              <td>
                <StatusBadge v-if="row.is_active" value="active" dot />
                <span v-else class="badge muted">历史</span>
              </td>
              <td class="notes">{{ row.release_notes || '—' }}</td>
              <td class="muted small cell-time">{{ formatTime(row.created_at) }}</td>
              <td><RowActions :actions="packageActions(row)" /></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.packages-page { display: flex; flex-direction: column; gap: 14px; flex: 1; min-height: 0; }
.upload-card { flex: none; }
/* 上传卡片内各段之间的纵向间距（表单栅格之外的直接子项） */
.upload-card > .field,
.upload-card > .notice,
.upload-card > .upload-actions { margin-top: 14px; }
/* 安装包选择区：整块可点，虚线表示"待放置文件"，选中后转为实线并在同一行显示文件名 */
.dropzone {
  display: flex; align-items: center; gap: 8px;
  min-height: 60px; padding: 0 12px;
  border: 1px dashed var(--border-strong); border-radius: 10px;
  background: #fbfdfd; color: var(--text-3);
  font-size: 12px; cursor: pointer;
  transition: border-color .12s, background .12s, color .12s;
}
.dropzone:hover,
.dropzone:focus-visible { border-color: var(--primary); background: var(--primary-soft); color: var(--primary); }
.dropzone.filled {
  border-style: solid; background: #fff; color: var(--text);
}
.dz-icon { flex: none; color: var(--primary); }
.dz-name {
  flex: 1 1 auto; min-width: 0;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-family: var(--mono); font-size: 12px;
}
.dz-size { flex: none; font-size: 12px; color: var(--text-3); font-family: var(--mono); }
.file-clear {
  flex: none; width: 20px; height: 20px; display: inline-flex; align-items: center; justify-content: center;
  border: none; border-radius: 5px; background: none; color: var(--text-3); cursor: pointer;
}
.file-clear:hover { background: #f1f5f4; color: var(--text); }
.file-hidden { display: none; }
.upload-actions { display: flex; justify-content: flex-end; }
.table-card { flex: 1 1 auto; display: flex; flex-direction: column; min-height: 0; }
.table-card .state-wrap { flex: 1 1 auto; min-height: 0; display: flex; align-items: center; justify-content: center; }
.table-card .table-wrap { flex: 1 1 auto; min-height: 0; }
.filename { max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.notes { max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-2); }
</style>
