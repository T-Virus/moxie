<template>
  <div class="upload">
    <input
      ref="fileInput"
      class="sr-only"
      type="file"
      :accept="accept"
      :aria-describedby="helpId"
      tabindex="-1"
      @change="onChange"
    />

    <button
      v-if="!file"
      type="button"
      class="upload__trigger"
      aria-label="上传大纲或全文小说"
      title="上传大纲或全文小说"
      aria-describedby="upload-help"
      @click="openPicker"
    >
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <path d="M8 3v10M3 8h10" fill="none" stroke="currentColor" stroke-width="1.6" />
      </svg>
    </button>

    <template v-else>
      <div class="upload__chip">
        <svg class="upload__file-icon" viewBox="0 0 16 16" aria-hidden="true">
          <path d="M4 2h5l3 3v9H4z" fill="none" stroke="currentColor" stroke-width="1.2" />
          <path d="M9 2v3h3" fill="none" stroke="currentColor" stroke-width="1.2" />
        </svg>
        <span class="upload__name" :title="file.name">{{ file.name }}</span>
        <span v-if="kind" class="upload__kind">{{ kind === 'novel' ? '全文' : '大纲' }}</span>
        <span class="upload__size">{{ formatBytes(file.size) }}</span>
        <button type="button" class="upload__remove" :aria-label="`移除文件 ${file.name}`" @click="remove">
          <svg viewBox="0 0 12 12" aria-hidden="true">
            <path d="M3 3l6 6M9 3l-6 6" fill="none" stroke="currentColor" stroke-width="1.4" />
          </svg>
        </button>
      </div>
      <button type="button" class="upload__replace" @click="openPicker">替换</button>
    </template>

    <span :id="helpId" class="sr-only">
      支持 .txt / .md / .markdown 的大纲或全文小说，单个文件不超过 {{ MAX_UPLOAD_MB }}MB；
      全文小说将按章节分段拆解全文。
    </span>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ACCEPTED_EXTENSIONS, MAX_UPLOAD_MB } from '@/services/config'
import { formatBytes } from '@/utils/format'

const props = defineProps<{
  file: File | null
}>()

const emit = defineEmits<{
  (event: 'update:file', value: File | null): void
  (event: 'kind', value: 'outline' | 'novel' | null): void
  (event: 'error', message: string): void
}>()

const fileInput = ref<HTMLInputElement | null>(null)
const kind = ref<'outline' | 'novel' | null>(null)
const accept = ACCEPTED_EXTENSIONS.join(',')
const helpId = 'upload-help'

function openPicker(): void {
  fileInput.value?.click()
}

function matchesExtension(name: string): boolean {
  const lower = name.toLowerCase()
  return ACCEPTED_EXTENSIONS.some((ext) => lower.endsWith(ext))
}

function onChange(event: Event): void {
  const input = event.target as HTMLInputElement
  const picked = input.files?.[0]
  input.value = ''
  if (!picked) return
  if (!matchesExtension(picked.name)) {
    emit('error', '仅支持 .txt / .md / .markdown 的大纲或全文小说文件，请重新选择')
    return
  }
  if (picked.size > MAX_UPLOAD_MB * 1024 * 1024) {
    emit('error', `文件超过 ${MAX_UPLOAD_MB}MB 限制，请压缩后重试`)
    return
  }
  if (picked.size === 0) {
    emit('error', '文件内容为空，请重新选择')
    return
  }
  kind.value = null
  emit('update:file', picked)
  void detectKind(picked)
}

/**
 * 轻量识别：先读前 80KB，统计「第X章 / Chapter N」标题数量。
 * 标题密集且文件较大（>120KB）视为全文小说；其余按大纲处理。
 */
async function detectKind(picked: File): Promise<void> {
  try {
    const head = await picked.slice(0, 80 * 1024).text()
    const zh = head.match(/第\s*[\d一二三四五六七八九十百千零两]{1,8}\s*[章节回卷]/g) || []
    const en = head.match(/(?:^|\n)\s*(?:Chapter|CHAPTER)\s+\d+/g) || []
    const markers = zh.length + en.length
    const detected = markers >= 8 || (markers >= 3 && picked.size > 120 * 1024)
    if (props.file !== picked) return
    kind.value = detected ? 'novel' : 'outline'
    emit('kind', kind.value)
  } catch {
    if (props.file !== picked) return
    kind.value = 'outline'
    emit('kind', kind.value)
  }
}

function remove(): void {
  kind.value = null
  emit('kind', null)
  emit('update:file', null)
}
</script>

<style scoped>
.upload {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.upload__trigger {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  border: 1px solid var(--panel-line);
  background: var(--panel-chip);
  color: #cfd8e3;
  transition: background var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease);
}

.upload__trigger:hover {
  background: var(--panel-chip-hover);
  border-color: rgba(255, 255, 255, 0.4);
}

.upload__trigger svg {
  width: 16px;
  height: 16px;
}

.upload__chip {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 36px;
  max-width: 320px;
  padding: 0 8px 0 12px;
  border-radius: var(--radius-pill);
  background: rgba(255, 255, 255, 0.12);
  border: 1px solid rgba(255, 255, 255, 0.22);
  color: #eaf2f8;
  font-size: var(--text-xs);
}

.upload__file-icon {
  width: 14px;
  height: 14px;
  flex: none;
  opacity: 0.85;
}

.upload__name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 170px;
}

.upload__kind {
  flex: none;
  padding: 1px 6px;
  border-radius: 6px;
  font-size: 14px;
  color: #a5f3fc;
  background: rgba(34, 211, 238, 0.16);
}

.upload__size {
  color: var(--panel-text-2);
  flex: none;
}

.upload__remove {
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  color: var(--panel-text-2);
  flex: none;
}

.upload__remove:hover {
  background: rgba(255, 255, 255, 0.16);
  color: #fff;
}

.upload__remove svg {
  width: 10px;
  height: 10px;
}

.upload__replace {
  font-size: var(--text-xs);
  color: var(--panel-text-2);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.upload__replace:hover {
  color: #fff;
}

@media (max-width: 560px) {
  .upload__chip {
    max-width: 100%;
  }

  .upload__name {
    max-width: 120px;
  }
}
</style>
