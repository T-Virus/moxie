<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import Icon from '../components/Icon.vue'
import Modal from '../components/Modal.vue'
import BatchRename from '../components/BatchRename.vue'
import MobilePicker from './MobilePicker.vue'
import { api } from '../api'
import { state, store } from '../store'
import { useBookDoc } from '../composables/useBookDoc'
import { confirmBox, toast } from '../ui'
import type { SbSchema } from '../types'

/* 道具 / 功法：与角色卡、势力表同级的世界观实体 */
const { raw, cards, factions, items, saving, load, save, batchRename } = useBookDoc()
const schema = ref<SbSchema | null>(null)
const kw = ref('')
const kindFilter = ref('')
const visible = ref(36)
const dirty = ref(false)
const detail = ref<number | null>(null)
/* 新增卡先本地挂着，填好名称点「完成」才写盘（无名卡会被服务端过滤掉） */
const newIdx = ref(-1)
const nameInput = ref<HTMLInputElement | null>(null)
const renameOpen = ref(false)
const renameRef = ref<any>(null)

onMounted(async () => {
  store.loadBooks().catch(() => {})
  load()
  try { schema.value = await api.getSchema() } catch { /* 忽略 */ }
})
watch(() => store.curBook(), () => {
  dirty.value = false; detail.value = null; newIdx.value = -1
  kw.value = ''; kindFilter.value = ''
})
onBeforeRouteLeave(async () => {
  if (dirty.value) {
    const ok = await save(true)
    if (!ok) return false
    dirty.value = false
  }
  return true
})

const FALLBACK = ['name', 'kind', 'grade', 'owner', 'faction', 'chapter', 'effect', 'origin', 'desc']
const fieldKeys = computed(() => (schema.value?.item_fields || FALLBACK.map(k => [k, k] as [string, string])).map(([k]) => k))
const kindOptions = computed(() => (schema.value?.item_kinds || []).map(([, lb]) => lb))
const charNames = computed(() => cards.value.map(c => String(c.name || '')).filter(Boolean))
const factionNames = computed(() => factions.value.map(f => String(f.name || '')).filter(Boolean))

const KIND_COLOR: Record<string, string> = {
  剧情道具: '#4d7ee8', 武学功法: '#0ca678', 战技: '#e8590c', 兵器: '#868e96',
  丹药: '#d6336c', 法宝: '#7048e8', 线索: '#f08c00', 其他: '#adb5bd',
}
const kindColor = (v: string) => KIND_COLOR[v] || '#adb5bd'

const filters = computed(() => {
  const all = [{ label: '', name: '全部', n: items.value.length }]
  const rest = kindOptions.value.map(k => ({
    label: k, name: k,
    n: items.value.filter(x => String(x.kind || '') === k).length,
  })).filter(x => x.n > 0)
  return [...all, ...rest]
})

const rows = computed(() => {
  const k = kw.value.trim().toLowerCase()
  return items.value.map((c, i) => ({ c, i }))
    .filter(r => !kindFilter.value || String(r.c.kind || '') === kindFilter.value)
    .filter(r => !k || ['name', 'effect', 'origin', 'desc', 'owner', 'faction']
      .some(f => String(r.c[f] || '').toLowerCase().includes(k)))
})
const shown = computed(() => rows.value.slice(0, visible.value))
const hasMore = computed(() => rows.value.length > visible.value)
watch([kw, kindFilter], () => { visible.value = 36 })

const cur = computed(() => (detail.value !== null ? items.value[detail.value] : null))

function touch() { dirty.value = true }
function open(i: number) { newIdx.value = -1; detail.value = i }
/* 关闭抽屉即保存；新增但没填名称的卡本地丢弃 */
async function close() {
  if (detail.value === null) return
  if (newIdx.value === detail.value) {
    if (!String(cur.value?.name || '').trim()) {
      items.value.splice(detail.value, 1)
      newIdx.value = -1
      detail.value = null
      dirty.value = false
      return
    }
    newIdx.value = -1
  }
  if (dirty.value) {
    const ok = await save(true)
    if (!ok) return
    dirty.value = false
  }
  detail.value = null
}
function addItem() {
  const item: Record<string, string> = {}
  for (const k of fieldKeys.value) item[k] = ''
  items.value.push(item)
  newIdx.value = items.value.length - 1
  dirty.value = true
  kindFilter.value = ''
  kw.value = ''
  visible.value = 36
  detail.value = items.value.length - 1
  nextTick(() => nameInput.value?.focus())
}
async function delItem() {
  if (detail.value === null) return
  if (newIdx.value === detail.value) {
    items.value.splice(detail.value, 1)
    newIdx.value = -1
    detail.value = null
    dirty.value = false
    toast('已取消新增', 'ok')
    return
  }
  if (!await confirmBox('删除这张道具 / 功法卡？章节里的引用也会同步移除。', { danger: true, ok: '删除' })) return
  items.value.splice(detail.value, 1)
  detail.value = null
  const ok = await save(true)
  dirty.value = false
  if (!ok) { load(); return }
  toast('已删除，章节引用已同步', 'ok')
}
async function applyRename(mapping: Record<string, string>) {
  const ok = await batchRename('items', mapping)
  if (ok) {
    renameOpen.value = false
    toast('已改名，章节与关联数据已同步', 'ok')
  } else {
    renameRef.value?.resetBusy()
  }
}
</script>

<template>
  <div class="m-page m-page-fixed">
    <div class="m-head">
      <div>
        <h1>道具功法</h1>
        <p>{{ items.length }} 件 · 道具、功法、战技与法宝</p>
      </div>
      <div class="m-head-act">
        <button class="m-btn sm ghost" :disabled="!raw || !items.length" @click="renameOpen = true">
          <Icon name="edit" :size="14" /> 改名
        </button>
        <button class="m-btn sm" :disabled="!raw" @click="addItem">
          <Icon name="plus" :size="14" /> 新增
        </button>
      </div>
    </div>

    <div v-if="!state.books.length" class="m-empty" style="padding-top:70px">
      <span class="m-empty-ico"><Icon name="shield" :size="28" /></span>
      <b>还没有作品</b>
      <p>先新建作品并完成拆解，道具功法会自动提取到这里。</p>
    </div>

    <div v-else-if="!raw" class="m-empty" style="padding-top:70px">
      <span class="m-empty-ico"><Icon name="refresh" :size="28" /></span>
      <b>正在载入道具功法</b>
      <p>从本地作品数据里读取道具与功法设定…</p>
    </div>

    <template v-else>
      <!-- 固定区：搜索 + 分类筛选，列表单独滚动 -->
      <div class="m-head-fixed">
        <div class="m-searchbar">
          <Icon name="search" :size="16" />
          <input v-model="kw" placeholder="搜索名称、效果或持有者" />
          <button v-if="kw" class="m-clear" @click="kw = ''"><Icon name="close" :size="13" /></button>
        </div>

        <div class="m-chips">
          <button v-for="f in filters" :key="f.name" class="m-chip" :class="{ on: kindFilter === f.label }"
                  @click="kindFilter = f.label">
            {{ f.name }}<span class="m-chip-n">{{ f.n }}</span>
          </button>
        </div>
      </div>

      <div class="m-page-scroll">
      <div v-if="items.length" class="m-rows" style="margin-top:9px">
        <button v-for="r in shown" :key="r.i" class="m-row-card" @click="open(r.i)">
          <span class="m-row-accent" :style="{ background: kindColor(String(r.c.kind || '')) }"></span>
          <span class="m-avatar" :style="{ background: kindColor(String(r.c.kind || '')) + '1a', color: kindColor(String(r.c.kind || '')) }">
            <Icon name="shield" :size="20" />
          </span>
          <span class="m-row-main">
            <span class="m-row-title"><b>{{ r.c.name || '未命名道具' }}</b><em v-if="r.c.grade">{{ r.c.grade }}</em></span>
            <span class="m-row-tags">
              <span v-if="r.c.kind" class="m-tag" :style="{ color: kindColor(r.c.kind), background: kindColor(r.c.kind) + '18' }">
                {{ r.c.kind }}</span>
              <span v-if="r.c.owner" class="m-tag" :class="'gray'"><Icon name="user" :size="9" />{{ r.c.owner }}</span>
              <span v-if="r.c.faction" class="m-tag gray"><Icon name="flag" :size="9" />{{ r.c.faction }}</span>
            </span>
            <span v-if="r.c.effect || r.c.desc" class="m-row-desc">{{ r.c.effect || r.c.desc }}</span>
          </span>
          <Icon name="right" :size="14" class="m-row-arrow" style="margin-top:4px" />
        </button>

        <button v-if="hasMore" class="m-load-more" @click="visible += 40">
          还有 {{ rows.length - visible }} 件，加载更多
        </button>
      </div>

      <div v-else class="m-empty">
        <span class="m-empty-ico"><Icon name="shield" :size="28" /></span>
        <b>{{ items.length ? '没有匹配的条目' : '暂无道具功法' }}</b>
        <p>{{ items.length ? '换个关键词或清除筛选试试。' : '拆解 / 改编时会自动提取，也可以点右上角「新增」手动添加。' }}</p>
      </div>
      </div>

      <Modal :open="detail !== null" :title="cur?.name ? '道具 · ' + cur.name : '道具功法'"
             @update:open="v => { if (!v) close() }">
        <div v-if="cur" class="m-modal-form" @input="touch" @change="touch">
          <div class="m-field">
            <label>名称</label>
            <input ref="nameInput" class="m-input" v-model="cur.name" placeholder="如：玄铁令 / 九转养魂诀" />
          </div>

          <div class="m-sec-title" style="margin-top:2px">基本信息</div>
          <div class="m-field">
            <label>类别</label>
            <div class="m-pick">
              <button v-for="k in kindOptions" :key="k" :class="{ on: cur.kind === k }"
                      :style="cur.kind === k ? { color: kindColor(k), background: kindColor(k) + '18' } : undefined"
                      @click="cur.kind = cur.kind === k ? '' : k; touch()">{{ k }}</button>
            </div>
          </div>
          <div class="m-form-2">
            <div class="m-field">
              <label>品阶<em>没有就留空</em></label>
              <input class="m-input" v-model="cur.grade" placeholder="如：地阶上品" />
            </div>
            <div class="m-field">
              <label>首次出现</label>
              <input class="m-input" v-model="cur.chapter" inputmode="numeric" placeholder="章号" />
            </div>
            <div class="m-field">
              <label>持有者 / 习得者</label>
              <MobilePicker v-model="cur.owner" title="选择持有者 / 习得者"
                            :options="charNames" placeholder="— 未填 —"
                            @update:model-value="touch" />
            </div>
            <div class="m-field">
              <label>所属势力</label>
              <MobilePicker v-model="cur.faction" title="选择所属势力"
                            :options="factionNames" placeholder="— 未填 —"
                            @update:model-value="touch" />
            </div>
          </div>

          <div class="m-sec-title">说明</div>
          <div class="m-field">
            <label>效果用途</label>
            <textarea class="m-textarea" v-model="cur.effect" style="min-height:76px"
                      placeholder="能做什么 / 练成后有什么效果"></textarea>
          </div>
          <div class="m-field">
            <label>来历</label>
            <textarea class="m-textarea" v-model="cur.origin" style="min-height:64px"
                      placeholder="谁所创、从何处得来"></textarea>
          </div>
          <div class="m-field">
            <label>简介</label>
            <textarea class="m-textarea" v-model="cur.desc" style="min-height:92px"
                      placeholder="外形、限制、代价…"></textarea>
          </div>
        </div>

        <template #footer>
          <div class="m-modal-foot">
            <button class="m-btn del" title="删除" @click="delItem"><Icon name="trash" :size="16" /></button>
            <button class="m-btn" :disabled="saving" @click="close">
              <Icon name="check" :size="15" /> {{ saving ? '保存中…' : '完成' }}
            </button>
          </div>
        </template>
      </Modal>

      <BatchRename ref="renameRef" :open="renameOpen" kind="items" title="批量修改道具 / 功法名"
                   desc-key="effect" :entities="items" mobile
                   @update:open="v => renameOpen = v" @apply="applyRename" />
    </template>
  </div>
</template>
