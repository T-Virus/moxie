<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import Icon from './Icon.vue'
import Modal from './Modal.vue'
import { api } from '../api'
import { store } from '../store'
import { toast } from '../ui'
import { cleanName } from '../utils'

/* 批量改名：只负责收集「旧名 → 新名」映射并回传，真正落盘与关联同步由 useBookDoc.batchRename 完成 */
const props = withDefaults(defineProps<{
  open: boolean
  kind: 'characters' | 'factions' | 'items'
  title: string
  entities: Record<string, any>[]
  descKey?: string
  mobile?: boolean
}>(), { descKey: '', mobile: false })

const emit = defineEmits<{
  (e: 'update:open', v: boolean): void
  (e: 'apply', mapping: Record<string, string>): void
}>()

const kw = ref('')
const busy = ref(false)
const aiBusy = ref(false)
const draft = reactive<Record<string, string>>({})

const rows = computed(() => {
  const k = kw.value.trim().toLowerCase()
  return props.entities
    .map(e => ({
      name: String(e.name || '').trim(),
      desc: props.descKey ? String(e[props.descKey] || '').trim().slice(0, 46) : '',
    }))
    .filter(r => r.name)
    .filter(r => !k || r.name.toLowerCase().includes(k) || r.desc.toLowerCase().includes(k))
})

const changedCount = computed(() =>
  rows.value.filter(r => (draft[r.name] ?? '').trim() && (draft[r.name] || '').trim() !== r.name).length)

watch(() => props.open, v => {
  if (!v) return
  kw.value = ''
  busy.value = false
  aiBusy.value = false
  for (const k of Object.keys(draft)) delete draft[k]
})

function close() { emit('update:open', false) }

/* 本地清理：把「孟孟孟皇后」「慈懿慈懿慈懿太后」这类复读名折叠掉，先填进草稿 */
function autoClean() {
  let n = 0
  for (const r of rows.value) {
    const clean = cleanName(r.name)
    if (clean && clean !== r.name) { draft[r.name] = clean; n += 1 }
  }
  toast(n ? `已清理 ${n} 个复读名，确认后应用` : '没有发现复读名', n ? 'ok' : '')
}

/* 一键 AI 改名：只生成建议，仍可逐条修改 */
async function aiRename() {
  if (aiBusy.value) return
  const book = store.curBook()
  if (!book) return toast('请先选择作品', 'err')
  const creds = store.callCreds('adapt')
  if (!creds.api_key) return toast('未配置 API Key：请先在设置里绑定「改编」工序的模型档案', 'err')
  aiBusy.value = true
  try {
    const r = await api.renameEntities({
      book, kind: props.kind,
      api_key: creds.api_key, model: creds.model, base_url: creds.base_url,
    })
    let n = 0
    for (const m of r.name_map || []) {
      if (!m?.old) continue
      draft[m.old] = m.new
      n += 1
    }
    toast(n ? `已生成 ${n} 个新名字，可继续修改后应用` : '没有可用的新名字', n ? 'ok' : 'err')
  } catch (e: any) {
    toast(e.message || 'AI 改名失败', 'err')
  } finally { aiBusy.value = false }
}

function apply() {
  const mapping: Record<string, string> = {}
  const used = new Map<string, string>()
  for (const r of rows.value) {
    const nv = (draft[r.name] ?? '').trim()
    if (!nv || nv === r.name) continue
    if (used.has(nv)) {
      toast(`新名字「${nv}」重复（${used.get(nv)} 与 ${r.name}）`, 'err')
      return
    }
    used.set(nv, r.name)
    mapping[r.name] = nv
  }
  if (!Object.keys(mapping).length) return toast('还没有修改任何名字', 'err')
  busy.value = true
  emit('apply', mapping)
  /* 父组件保存成功后关闭；失败时由父组件把 busy 复位 */
}

defineExpose({ resetBusy: () => { busy.value = false } })
</script>

<template>
  <Modal :open="open" :title="title" @update:open="v => { if (!v) close() }">
    <div class="br" :class="{ mobile }">
      <div class="br-tip">
        <Icon name="shield" :size="14" />
        <span>改名后，章节引用、角色关系、势力归属、道具持有者会一起同步更新。</span>
      </div>
      <div class="br-tools">
        <div class="br-search">
          <Icon name="search" :size="14" />
          <input v-model="kw" placeholder="搜索旧名称" />
          <button v-if="kw" class="br-clear" @click="kw = ''"><Icon name="close" :size="12" /></button>
        </div>
        <button class="btn ghost" :disabled="aiBusy" @click="aiRename">
          <Icon name="pen" :size="14" /> {{ aiBusy ? '正在起名…' : 'AI 一键改名' }}
        </button>
        <button class="btn ghost" @click="autoClean">
          <Icon name="refresh" :size="14" /> 清理复读名
        </button>
      </div>

      <div class="br-list">
        <div v-for="r in rows" :key="r.name" class="br-row">
          <div class="br-old">
            <b>{{ r.name }}</b>
            <small v-if="r.desc">{{ r.desc }}</small>
          </div>
          <Icon name="right" :size="12" class="br-arrow" />
          <input v-model="draft[r.name]" class="input br-new"
                 :placeholder="r.name" />
        </div>
        <div v-if="!rows.length" class="br-empty">没有可改名的条目</div>
      </div>

      <div class="br-count">已修改 {{ changedCount }} / {{ rows.length }} 个名称</div>
    </div>

    <template #footer>
      <button class="btn ghost" @click="close">取消</button>
      <button class="btn" :disabled="busy" @click="apply">
        <Icon name="check" :size="15" /> {{ busy ? '正在保存…' : `应用改名（${changedCount}）` }}
      </button>
    </template>
  </Modal>
</template>

<style scoped>
.br { display: flex; flex-direction: column; gap: 10px; min-height: 0; }
.br-tip {
  display: flex; align-items: flex-start; gap: 6px; padding: 8px 10px; border-radius: 10px;
  background: #f6f8fb; color: var(--text2); font-size: 12px; line-height: 1.55;
}
.br-tip svg { flex: none; margin-top: 1px; color: var(--primary); }
.br-tools { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.br-search {
  flex: 1 1 180px; display: flex; align-items: center; gap: 6px; padding: 0 10px;
  height: 34px; border: 1px solid var(--line); border-radius: 9px; background: #fff; color: var(--text3);
}
.br-search input { flex: 1; border: 0; outline: none; background: transparent; font-size: 13px; color: var(--text); }
.br-clear { display: flex; color: var(--text3); }
.br-list {
  display: flex; flex-direction: column; gap: 6px; max-height: min(52vh, 460px); overflow-y: auto;
  padding-right: 2px;
}
.br-row {
  display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-radius: 10px;
  background: #fafbfc; border: 1px solid #eef0f3;
}
.br-old { flex: 1 1 46%; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.br-old b { font-size: 13px; color: var(--text); word-break: break-all; }
.br-old small { font-size: 11.5px; color: var(--text3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.br-arrow { flex: none; color: #c3c9d1; }
.br-new { flex: 1 1 46%; min-width: 0; height: 32px; }
.br-empty { padding: 26px 0; text-align: center; color: var(--text3); font-size: 13px; }
.br-count { font-size: 12px; color: var(--text3); text-align: right; }
.br.mobile .br-list { max-height: 48dvh; }
.br.mobile .br-row { flex-wrap: wrap; }
.br.mobile .br-old { flex-basis: 100%; }
.br.mobile .br-arrow { display: none; }
.br.mobile .br-new { flex-basis: 100%; }
</style>
