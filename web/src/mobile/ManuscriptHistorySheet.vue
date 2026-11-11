<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import Icon from '../components/Icon.vue'
import Modal from '../components/Modal.vue'
import { api } from '../api'
import type { HistoryVersion } from '../api'
import { confirmBox, toast } from '../ui'
import { fmtNum } from '../utils'

/**
 * 正文历史版本：列出每章的自动快照，支持预览 / 与当前正文对比 / 回滚。
 * 快照由后端在「正文被覆盖前」自动留存（保存正文、AI 生成、回滚都会留档）。
 */
const props = defineProps<{
  open: boolean
  book: string
  chapterNo: number
}>()
const emit = defineEmits<{
  (e: 'update:open', v: boolean): void
  (e: 'restored'): void
}>()

const loading = ref(false)
const busy = ref(false)
const versions = ref<HistoryVersion[]>([])
const current = ref<{ chars: number; preview: string } | null>(null)
const mode = ref<'' | 'text' | 'diff'>('')
const pick = ref<HistoryVersion | null>(null)
const body = ref('')
const bodyTitle = ref('')

const diffLines = computed(() => {
  if (mode.value !== 'diff') return []
  return body.value.split('\n').map(line => {
    let cls = ''
    if (line.startsWith('+++') || line.startsWith('---')) cls = 'meta'
    else if (line.startsWith('@@')) cls = 'hunk'
    else if (line.startsWith('+')) cls = 'add'
    else if (line.startsWith('-')) cls = 'del'
    return { line, cls }
  }).filter(x => x.line !== '')
})

watch(() => props.open, v => { if (v) load() })

async function load() {
  if (!props.book || !props.chapterNo) return
  loading.value = true
  mode.value = ''
  pick.value = null
  body.value = ''
  try {
    const r = await api.getHistory(props.book, props.chapterNo)
    versions.value = r.versions || []
    current.value = r.current || null
  } catch (e: any) {
    toast(e.message, 'err')
  } finally {
    loading.value = false
  }
}

function close() { emit('update:open', false) }
function back() { mode.value = ''; pick.value = null; body.value = '' }

async function viewText(v: HistoryVersion) {
  pick.value = v
  mode.value = 'text'
  bodyTitle.value = `${v.mtime_text} · ${fmtNum(v.chars)} 字${v.note ? ' · ' + v.note : ''}`
  body.value = ''
  busy.value = true
  try {
    const r = await api.getHistoryText(props.book, props.chapterNo, v.file)
    body.value = r.text || ''
  } catch (e: any) {
    toast(e.message, 'err')
    back()
  } finally {
    busy.value = false
  }
}

async function viewDiff(v: HistoryVersion) {
  pick.value = v
  mode.value = 'diff'
  bodyTitle.value = `${v.mtime_text} → 当前正文`
  body.value = ''
  busy.value = true
  try {
    const r = await api.getHistoryDiff(props.book, props.chapterNo, v.file)
    body.value = r.diff || ''
  } catch (e: any) {
    toast(e.message, 'err')
    back()
  } finally {
    busy.value = false
  }
}

async function rollback(v: HistoryVersion) {
  if (!await confirmBox(
    `回滚到 ${v.mtime_text} 的版本？当前正文会先自动留一份快照，回滚本身也能再撤销。`,
    { ok: '回滚', danger: true })) return
  busy.value = true
  try {
    await api.rollbackHistory(props.book, props.chapterNo, v.file)
    toast('已回滚到该版本', 'ok')
    emit('restored')
    await load()
  } catch (e: any) {
    toast(e.message, 'err')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <Modal :open="open" :title="mode ? '历史版本' : '历史版本'" @update:open="v => { if (!v) close() }">
    <div class="m-hs">
      <!-- 列表 -->
      <template v-if="!mode">
        <div class="m-hs-head">
          <span class="m-hs-ico"><Icon name="refresh" :size="18" /></span>
          <div>
            <b>第 {{ chapterNo }} 章</b>
            <p>当前正文 {{ current ? fmtNum(current.chars) + ' 字' : '未成稿' }} · 共 {{ versions.length }} 份快照</p>
          </div>
          <span v-if="loading" class="m-tag gray">读取中</span>
        </div>

        <div v-if="versions.length" class="m-hs-list">
          <div v-for="(v, i) in versions" :key="v.file" class="m-hs-item">
            <div class="m-hs-item-head">
              <b>{{ v.mtime_text }}</b>
              <span v-if="i === 0" class="m-tag gray">最近</span>
              <span class="m-hint" style="margin-left:auto">{{ fmtNum(v.chars) }} 字</span>
            </div>
            <p v-if="v.note" class="m-hs-note">{{ v.note }}</p>
            <p v-if="v.preview" class="m-hs-preview">{{ v.preview }}</p>
            <div class="m-hs-acts">
              <button class="m-btn sm ghost" :disabled="busy" @click="viewText(v)">
                <Icon name="eye" :size="13" /> 预览
              </button>
              <button class="m-btn sm ghost" :disabled="busy" @click="viewDiff(v)">
                <Icon name="list" :size="13" /> 对比
              </button>
              <button class="m-btn sm soft" :disabled="busy" @click="rollback(v)">
                <Icon name="refresh" :size="13" /> 回滚
              </button>
            </div>
          </div>
        </div>

        <div v-else-if="!loading" class="m-hs-empty">
          <Icon name="file" :size="34" />
          <b>还没有历史版本</b>
          <p>正文被覆盖前会自动留档：保存、AI 生成或回滚之后就能在这里找到旧稿。</p>
        </div>
      </template>

      <!-- 预览 / 对比 -->
      <template v-else>
        <button class="m-link m-hs-back" @click="back">
          <Icon name="left" :size="12" /> 返回版本列表
        </button>
        <p class="m-hs-title">{{ bodyTitle }}</p>
        <div v-if="busy" class="m-hint" style="padding:16px 2px">正在读取…</div>
        <template v-else-if="mode === 'text'">
          <pre class="m-hs-text">{{ body || '（该版本内容为空）' }}</pre>
        </template>
        <template v-else>
          <pre v-if="diffLines.length" class="m-hs-diff"><span
            v-for="(l, i) in diffLines" :key="i" :class="'dl ' + l.cls">{{ l.line }}</span></pre>
          <p v-else class="m-hint" style="padding:16px 2px">与当前正文完全一致，没有差异。</p>
          <p class="m-hint" style="margin-top:8px">
            <span class="m-hs-legend add">+ 新增</span>
            <span class="m-hs-legend del">− 删除</span>
          </p>
        </template>
        <button v-if="pick && mode === 'text'" class="m-btn block" style="margin-top:12px"
                :disabled="busy" @click="rollback(pick)">
          <Icon name="refresh" :size="14" /> 回滚到这一版
        </button>
      </template>
    </div>

    <template #footer>
      <div class="m-modal-foot">
        <button class="m-btn ghost" @click="close">关闭</button>
      </div>
    </template>
  </Modal>
</template>

<style scoped>
.m-hs { display: flex; flex-direction: column; gap: 11px; }
.m-hs-head { display: flex; align-items: center; gap: 10px; }
.m-hs-ico {
  width: 38px; height: 38px; flex: none; border-radius: 12px;
  display: grid; place-items: center;
  background: var(--m-primary-soft); color: var(--m-primary);
}
.m-hs-head > div { flex: 1; min-width: 0; }
.m-hs-head b { font-size: 14px; font-weight: 650; }
.m-hs-head p { margin-top: 2px; font-size: 10.5px; color: var(--m-text3); }
.m-hs-list { display: flex; flex-direction: column; gap: 9px; }
.m-hs-item { padding: 11px 12px; border: 1px solid var(--m-line); border-radius: 14px; }
.m-hs-item-head { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.m-hs-item-head b { font-size: 12.5px; font-weight: 650; }
.m-hs-note { margin-top: 5px; font-size: 11px; color: var(--m-text3); }
.m-hs-preview {
  margin-top: 6px; font-size: 11.5px; line-height: 1.65; color: var(--m-text2);
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.m-hs-acts { display: flex; gap: 7px; margin-top: 9px; }
.m-hs-acts .m-btn { flex: 1; height: 34px; font-size: 12px; }
.m-hs-empty {
  display: flex; flex-direction: column; align-items: center; gap: 6px;
  padding: 30px 16px; text-align: center; color: var(--m-text3);
}
.m-hs-empty b { margin-top: 4px; font-size: 14px; color: var(--m-text); }
.m-hs-empty p { font-size: 11.5px; line-height: 1.6; max-width: 270px; }
.m-hs-back { display: inline-flex; align-items: center; gap: 3px; margin-bottom: 8px; }
.m-hs-title { font-size: 11.5px; color: var(--m-text3); margin-bottom: 8px; }
.m-hs-text, .m-hs-diff {
  max-height: 52dvh; overflow: auto; margin: 0; padding: 11px 12px;
  border-radius: 12px; background: #f7f9f5; color: var(--m-text2);
  font-size: 11.5px; line-height: 1.75; white-space: pre-wrap; word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
.m-hs-diff .dl { display: block; }
.m-hs-diff .dl.add { color: #13845f; background: #e7f6ef; }
.m-hs-diff .dl.del { color: #b93a36; background: #fdeceb; }
.m-hs-diff .dl.hunk { color: #4a6fa5; }
.m-hs-diff .dl.meta { color: var(--m-text3); }
.m-hs-legend { margin-right: 10px; font-size: 11px; }
.m-hs-legend.add { color: #13845f; }
.m-hs-legend.del { color: #b93a36; }
</style>
