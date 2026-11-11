<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import Icon from '../components/Icon.vue'
import EmptyBox from '../components/EmptyBox.vue'
import SelectBox from '../components/SelectBox.vue'
import { api } from '../api'
import { toast, openFilePreview, confirmBox } from '../ui'
import { fmtSize } from '../utils'
import type { OutputFile } from '../types'

/* 服务端分页：只把当前页的 50~500 条给浏览器，几万个产出文件也不会一次渲染成 DOM */
const files = ref<OutputFile[]>([])
const groups = ref<string[]>([])
const total = ref(0)
const page = ref(1)
const pageCount = ref(1)
const pageSize = ref(50)
const q = ref('')            // 输入框里的原始文字
const kw = ref('')           // 防抖后真正发出去的搜索词
const group = ref('')
const loading = ref(false)
const scrollEl = ref<HTMLElement | null>(null)

let reqId = 0               // 连点分页/边打字边搜时，只认最后一次请求的响应
async function refresh() {
  const my = ++reqId
  loading.value = true
  try {
    const r = await api.getOutputs({ q: kw.value, group: group.value, page: page.value, pageSize: pageSize.value })
    if (my !== reqId) return
    files.value = r.files || []
    total.value = r.total || 0
    groups.value = r.groups || []
    pageCount.value = r.page_count || 1
    page.value = r.page || 1      // 后端会把越界页码回退到末页，这里跟着同步
  } catch (e: any) {
    if (my !== reqId) return
    files.value = []
    total.value = 0
    toast(e.message, 'err')
  } finally {
    if (my === reqId) loading.value = false
  }
}

/* 搜索防抖：边打字边发请求会在几万文件上把后端扫成筛子 */
let timer: any
watch(q, v => {
  clearTimeout(timer)
  timer = setTimeout(() => {
    kw.value = String(v || '').trim()
    page.value = 1
    refresh()
  }, 300)
})
watch(group, () => { page.value = 1; refresh() })
watch(pageSize, () => { page.value = 1; refresh() })

function goPage(p: number) {
  const n = Math.min(Math.max(1, Math.round(p) || 1), pageCount.value)
  if (n === page.value) return
  page.value = n
  refresh()
  if (scrollEl.value) scrollEl.value.scrollTop = 0
}

/* 类别标签配色：拆解数据/设定=蓝，审查报告=紫，正文=绿，历史批次=灰 */
function tagCls(kind?: string) {
  if (kind === 'review') return 'purple'
  if (kind === 'manuscript') return 'green'
  if (kind === 'batch') return 'gray'
  return 'blue'
}

async function del(p: string) {
  if (!await confirmBox('删除「' + p + '」？', { danger: true, ok: '删除' })) return
  try {
    await api.deleteOutput(p)
    toast('已删除', 'ok')
    // 删光当页时后端会把 page 回退到末页，refresh 里同步 page.value
    if (files.value.length === 1 && page.value > 1) page.value -= 1
    refresh()
  } catch (e: any) { toast(e.message, 'err') }
}
async function clearAll() {
  try {
    const s = await api.clearOutputs(true)
    if (!await confirmBox(`将删除 ${s.books} 本书目录与 ${s.batches} 个历史批次的全部产出，不可恢复。确定？`, { danger: true, ok: '全部清空' })) return
    await api.clearOutputs(false)
    toast('已清空全部产出', 'ok')
    page.value = 1
    refresh()
  } catch (e: any) { toast(e.message, 'err') }
}

onMounted(refresh)
</script>

<template>
  <div class="page-head outputs-head">
    <div class="outputs-head-main"><h1>产出文件</h1>
      <p>所有拆解数据、成稿正文、审查报告与历史批次的统一管理入口。</p></div>
    <button class="btn danger-ghost" @click="clearAll"><Icon name="trash" :size="14" /> 清空全部产出</button>
  </div>

  <div class="card outputs-card">
    <div class="card-head">
      <div class="card-title">文件清单</div><span class="sub">{{ total }} 个文件</span>
      <span class="spacer"></span>
      <input class="input" v-model="q" placeholder="搜索文件名或路径" style="width:190px" @keyup.enter="refresh" />
      <button class="btn ghost" v-if="q" @click="q = ''">清除</button>
      <div style="width:200px">
        <SelectBox :model-value="group" title="按来源筛选"
                   :options="[{ label: '全部来源', value: '' }, ...groups.map(g => ({ label: g, value: g }))]"
                   @update:model-value="v => group = v" />
      </div>
    </div>

    <div v-if="files.length" class="table-wrap" ref="scrollEl">
      <table class="table">
        <thead><tr><th>来源</th><th>文件</th><th>大小</th><th style="text-align:right">操作</th></tr></thead>
        <tbody>
          <tr v-for="f in files" :key="f.path">
            <td class="src" :title="f.group">{{ f.group }}</td>
            <td><span v-if="f.label" class="tag" :class="tagCls(f.kind)">{{ f.label }}</span>
              <b style="font-size:13px">{{ f.name }}</b><br><span style="font-size:11px;color:var(--text-3)">{{ f.path }}</span></td>
            <td>{{ fmtSize(f.size) }}</td>
            <td><div class="ops">
              <button class="link-btn" @click="openFilePreview(f.path, f.name)">预览</button>
              <button class="link-btn red" @click="del(f.path)">删除</button>
            </div></td>
          </tr>
        </tbody>
      </table>
    </div>
    <EmptyBox v-else-if="kw || group" title="没有匹配的文件" desc="换个关键词，或把来源切回「全部来源」" />
    <EmptyBox v-else title="没有产出文件" desc="运行拆解 / 扩写 / 审查后生成" />

    <div v-if="total" class="pager">
      <span class="hint">共 {{ total }} 个 · 第 {{ page }} / {{ pageCount }} 页</span>
      <span class="spacer"></span>
      <div style="width:118px">
        <SelectBox :model-value="String(pageSize)" :search-from="99"
                   :options="[50, 100, 200, 500].map(n => ({ label: `每页 ${n}`, value: String(n) }))"
                   @update:model-value="v => pageSize = Number(v) || 50" />
      </div>
      <button class="btn ghost" :disabled="page <= 1" @click="goPage(1)">首页</button>
      <button class="btn ghost" :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
      <button class="btn ghost" :disabled="page >= pageCount" @click="goPage(page + 1)">下一页</button>
      <button class="btn ghost" :disabled="page >= pageCount" @click="goPage(pageCount)">末页</button>
    </div>
  </div>
</template>

<style scoped>
.outputs-head { display: flex; align-items: flex-end; gap: 14px; }
.outputs-head-main { flex: 1; min-width: 0; }
/* 占满视口剩余高度，页面不出滚动条；表格在卡片内部滚动，分页条固定在卡片底部 */
.outputs-card { display: flex; flex-direction: column; flex: 1; min-height: 0; overflow: hidden; }
.table-wrap { flex: 1; min-height: 0; overflow: auto; }
.table-wrap::-webkit-scrollbar { width: 7px; height: 7px; }
.table-wrap::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 4px; }
/* 来源列：书名可能很长，限制宽度并折行，别把表格撑到横向溢出 */
.src { max-width: 170px; word-break: break-all; color: var(--text-3); font-size: 12px; }
.pager { display: flex; align-items: center; gap: 8px; padding: 10px 14px; border-top: 1px solid var(--border); flex-wrap: wrap; }
.pager .hint { font-size: 11px; color: var(--text-3); }
.pager .btn.sm { padding: 0 9px; }

/* 手机：表格改成「一行一文件」的卡片式排布，不再横向挤压 / 需要左右拖动 */
@media (max-width: 760px) {
  .table-wrap .table { min-width: 0; }
  .table thead { display: none; }
  .table tbody tr {
    display: grid; grid-template-columns: 1fr auto; align-items: start; gap: 2px 10px;
    padding: 12px 2px; border-bottom: 1px solid var(--border);
  }
  .table tbody tr:hover { background: none; }
  .table td { display: block; padding: 0; border: none; }
  .table td.src { order: 2; grid-column: 1 / -1; max-width: none; white-space: normal; font-size: 11px; }
  .table td:nth-child(2) { order: 1; grid-column: 1 / -1; }
  .table td:nth-child(3) { order: 3; font-size: 11px; color: var(--text-3); }
  .table td:nth-child(4) { order: 3; }
  .table .ops { justify-content: flex-end; }
  /* 页头与筛选在手机上纵向铺满：标题、说明、清空按钮各占一行 */
  .outputs-head { flex-direction: column; align-items: stretch; gap: 10px; }
  .outputs-head .btn { width: 100%; }
  /* 手机不再做「卡片内固定高度 + 内部滚动」：让整页滚动，列表不会被压成一条缝 */
  .outputs-card { flex: none; min-height: 0; overflow: visible; }
  .table-wrap { flex: none; min-height: 0; overflow: visible; }
  .card-head .input, .card-head .select { width: 100% !important; flex: 1 1 100%; }
  .pager { flex-wrap: wrap; gap: 8px; padding: 10px 0 0; border-top: none; }
  .pager .hint { flex: 1 1 100%; font-size: 12px; }
  .pager .spacer { display: none; }
  .pager .select { width: 104px !important; flex: none; }
  .pager .btn { flex: 1; height: 36px; padding: 0 8px; }
}
</style>
