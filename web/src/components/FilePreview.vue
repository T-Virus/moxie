<script setup lang="ts">
import Modal from './Modal.vue'
import { previewState } from '../ui'
import { fmtSize } from '../utils'

/* 大文件下载：内容和预览解耦，避免为了看一眼开头就把几十 MB 拉进浏览器 */
function download() {
  location.href = '/api/output?dl=1&path=' + encodeURIComponent(previewState.path)
}
</script>

<template>
  <Modal :open="previewState.open" :title="previewState.name" wide layer="confirm"
         @update:open="v => (previewState.open = v)">
    <div v-if="previewState.loading" class="hint">读取中…</div>
    <template v-else>
      <div v-if="previewState.truncated" class="trunc-warn">
        文件较大（{{ fmtSize(previewState.size) }}），预览只显示开头部分，完整内容请
        <button class="link-btn" @click="download">下载查看</button>
      </div>
      <iframe v-if="previewState.html" :srcdoc="previewState.content"
              style="width:100%;height:64vh;border:1px solid var(--border);border-radius:8px"></iframe>
      <pre v-else class="prose"
           style="max-height:64vh;overflow:auto;white-space:pre-wrap;margin:0">{{ previewState.content }}</pre>
    </template>
  </Modal>
</template>

<style scoped>
.trunc-warn {
  display: flex; align-items: center; gap: 4px; flex-wrap: wrap;
  padding: 8px 10px; margin-bottom: 10px; font-size: 12px;
  color: var(--orange); background: rgba(255, 145, 0, .1);
  border: 1px solid rgba(255, 145, 0, .35); border-radius: 8px;
}
.trunc-warn .link-btn { font-size: 12px; }
</style>
