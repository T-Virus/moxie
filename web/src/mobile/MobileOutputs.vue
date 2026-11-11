<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import Icon from '../components/Icon.vue'
import MobilePicker from './MobilePicker.vue'
import { api } from '../api'
import { confirmBox, openFilePreview, toast } from '../ui'
import { fmtSize } from '../utils'
import type { OutputFile } from '../types'

const files = ref<OutputFile[]>([])
const groups = ref<string[]>([])
const total = ref(0)
const page = ref(1)
const pageCount = ref(1)
const pageSize = 50
const q = ref('')
const kw = ref('')
const group = ref('')
const loading = ref(false)
const loadingMore = ref(false)

let reqId = 0
let timer: any = null

async function load(append = false) {
  const my = ++reqId
  if (append) loadingMore.value = true
  else loading.value = true
  try {
    const target = append ? page.value + 1 : 1
    const r = await api.getOutputs({ q: kw.value, group: group.value, page: target, pageSize })
    if (my !== reqId) return
    const list = r.files || []
    files.value = append ? [...files.value, ...list] : list
    total.value = r.total || 0
    groups.value = r.groups || []
    pageCount.value = r.page_count || 1
    page.value = r.page || target
  } catch (e: any) {
    if (my !== reqId) return
    if (!append) { files.value = []; total.value = 0 }
    toast(e.message, 'err')
  } finally {
    if (my === reqId) { loading.value = false; loadingMore.value = false }
  }
}

watch(q, v => {
  clearTimeout(timer)
  timer = setTimeout(() => {
    kw.value = String(v || '').trim()
    load()
  }, 300)
})
watch(group, () => load())

function loadMore() {
  if (loadingMore.value || page.value >= pageCount.value) return
  load(true)
}

function tagCls(kind?: string) {
  if (kind === 'review') return 'purple'
  if (kind === 'manuscript') return 'green'
  if (kind === 'batch') return 'gray'
  return 'blue'
}
function tagText(f: OutputFile) {
  return f.label || '数据文件'
}
function bookOf(f: OutputFile) {
  return f.group || f.book || '本机数据'
}
async function del(f: OutputFile) {
  if (!await confirmBox('删除「' + f.name + '」？', { danger: true, ok: '删除' })) return
  try {
    await api.deleteOutput(f.path)
    toast('已删除', 'ok')
    await load()
  } catch (e: any) { toast(e.message, 'err') }
}
async function clearAll() {
  try {
    const s = await api.clearOutputs(true)
    if (!await confirmBox(`将删除 ${s.books} 本书与 ${s.batches} 个历史批次的全部产出，不可恢复。确定？`,
      { danger: true, ok: '全部清空' })) return
    await api.clearOutputs(false)
    toast('已清空全部产出', 'ok')
    await load()
  } catch (e: any) { toast(e.message, 'err') }
}

onMounted(() => load())
</script>

<template>
  <div class="m-page m-secondary-page">
    <div class="m-sec-head">
      <div class="m-sec-head-txt">拆解数据、成稿正文、审查报告与历史批次</div>
      <div class="m-sec-head-act">
        <button class="m-icon-btn" title="清空全部产出" @click="clearAll">
          <Icon name="trash" :size="18" />
        </button>
      </div>
    </div>

    <div class="m-output-count">
      <span class="m-output-count-n">{{ total }}</span>
      <span>个文件</span>
      <span class="m-spacer"></span>
      <span v-if="group" class="m-tag blue">{{ group }}</span>
    </div>

    <div class="m-searchbar">
      <Icon name="search" :size="16" />
      <input v-model="q" placeholder="搜索文件名或路径" />
      <button v-if="q" class="m-clear" @click="q = ''"><Icon name="close" :size="13" /></button>
    </div>

    <div class="m-output-filter">
      <Icon name="folder" :size="15" />
      <div style="flex:1;min-width:0">
        <MobilePicker :model-value="group" title="按来源筛选"
                      :options="[{ label: '全部来源', value: '' }, ...groups.map(g => ({ label: g, value: g }))]"
                      @update:model-value="v => group = v" />
      </div>
    </div>

    <div v-if="loading" class="m-empty" style="padding-top:50px">
      <span class="m-empty-ico"><Icon name="refresh" :size="26" /></span>
      <b>正在载入文件</b>
      <p>扫描本地产出目录…</p>
    </div>

    <div v-else-if="files.length" class="m-rows" style="margin-top:11px">
      <div v-for="f in files" :key="f.path" class="m-file-card">
        <div class="m-file-top">
          <span class="m-tag" :class="tagCls(f.kind)">{{ tagText(f) }}</span>
          <span class="m-file-book">{{ bookOf(f) }}</span>
        </div>
        <button class="m-file-name" @click="openFilePreview(f.path, f.name)">{{ f.name }}</button>
        <div class="m-file-path">{{ f.path }}</div>
        <div class="m-file-foot">
          <span class="m-file-size">{{ fmtSize(f.size) }}</span>
          <span class="m-spacer"></span>
          <button class="m-file-act" @click="openFilePreview(f.path, f.name)">
            <Icon name="eye" :size="14" /> 预览
          </button>
          <button class="m-file-act danger" @click="del(f)">
            <Icon name="trash" :size="14" /> 删除
          </button>
        </div>
      </div>

      <button v-if="page < pageCount" class="m-load-more" :disabled="loadingMore" @click="loadMore">
        {{ loadingMore ? '载入中…' : `加载更多（${files.length} / ${total}）` }}
      </button>
    </div>

    <div v-else class="m-empty" style="padding-top:50px">
      <span class="m-empty-ico"><Icon name="folder" :size="28" /></span>
      <b>{{ kw || group ? '没有匹配的文件' : '还没有产出文件' }}</b>
      <p>{{ kw || group ? '换个关键词，或把来源切回「全部来源」。' : '运行拆解、扩写或审查后，文件会出现在这里。' }}</p>
    </div>
  </div>
</template>

<style scoped>
.m-spacer { flex: 1; }
.m-output-count {
  display: flex; align-items: baseline; gap: 5px;
  padding: 2px 4px 12px; font-size: 11px; color: var(--m-text3);
}
.m-output-count-n { font-size: 24px; font-weight: 750; color: var(--m-text); letter-spacing: -.5px; }
.m-output-filter {
  display: flex; align-items: center; gap: 8px;
  height: 42px; padding: 0 13px; margin-bottom: 2px;
  border: 1px solid var(--m-line); border-radius: 13px; background: #fff;
  color: var(--m-text3);
}
.m-output-filter select {
  flex: 1; min-width: 0; border: 0; outline: 0; background: none;
  appearance: none; -webkit-appearance: none;
  font-size: 13px; color: var(--m-text2);
}
/* 行内选择器：去掉触发器自己的边框，保持整行一个输入框的外观 */
.m-output-filter :deep(.mp-trigger) {
  border: 0; background: transparent; min-height: 0; height: 28px; padding: 0;
  font-size: 13px; color: var(--m-text2);
}
.m-file-card {
  padding: 13px 14px; background: #fff;
  border: 1px solid var(--m-line); border-radius: 17px;
  box-shadow: 0 1px 2px rgba(20, 30, 27, .03);
}
.m-file-top { display: flex; align-items: center; gap: 8px; }
.m-file-book {
  margin-left: auto; max-width: 56%; font-size: 10.5px; color: var(--m-text3);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.m-tag.purple { background: #f0edff; color: #6a54e0; }
.m-file-name {
  display: block; width: 100%; margin-top: 8px; padding: 0;
  border: 0; background: none; text-align: left;
  font-size: 14px; font-weight: 600; color: var(--m-text);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.m-file-path {
  margin-top: 4px; font-size: 10.5px; line-height: 1.5; color: var(--m-text3);
  word-break: break-all; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.m-file-foot {
  display: flex; align-items: center; gap: 8px; margin-top: 10px;
  padding-top: 10px; border-top: 1px solid #f2f4f0;
}
.m-file-size { font-size: 10.5px; color: var(--m-text3); }
.m-file-act {
  display: inline-flex; align-items: center; gap: 4px;
  height: 30px; padding: 0 10px; border: 0; border-radius: 9px;
  background: #f4f6f2; color: var(--m-text2); font-size: 11.5px;
}
.m-file-act.danger { background: var(--m-red-soft); color: var(--m-red); }
</style>
