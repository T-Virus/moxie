<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import Icon from '../components/Icon.vue'
import Modal from '../components/Modal.vue'
import SearchMultiSelect from '../components/SearchMultiSelect.vue'
import { state, store } from '../store'
import { useBookDoc } from '../composables/useBookDoc'
import { confirmBox, toast } from '../ui'
import { genderTag } from '../utils'
import { stanceMeta, stanceTag } from '../factionMeta'

const { raw, chapters, cards, factions, items, saving, load, save } = useBookDoc()
const kw = ref('')
const filter = ref<'all' | 'done' | 'todo'>('all')
const visible = ref(40)
const dirty = ref(false)
const detail = ref<number | null>(null)

onMounted(() => { store.loadBooks().catch(() => {}); load() })
watch(() => store.curBook(), () => {
  dirty.value = false; detail.value = null; kw.value = ''; filter.value = 'all'
})
onBeforeRouteLeave(async () => {
  if (dirty.value) { const ok = await save(true); if (ok) dirty.value = false }
  return true
})

const meta = computed(() => state.books.find(b => b.name === store.curBook()) || null)
const msMap = computed<Record<string, any>>(() => meta.value?.ms_by_no || {})
const HOOK_TYPES = ['悬念', '危机', '反转', '期待', '信息差', '情感']

function noOf(c: any, i = 0): number {
  for (const k of ['no', 'chapter_id', 'id', 'title']) {
    const m = String(c?.[k] ?? '').match(/\d+/)
    if (m) return Number(m[0])
  }
  return i + 1
}
const doneCount = computed(() =>
  chapters.value.filter((c, i) => !!msMap.value[String(noOf(c, i))]).length)

const charOpts = computed<string[]>(() => {
  const set = new Set<string>()
  for (const c of cards.value) if (c.name) set.add(c.name)
  for (const ch of chapters.value) for (const r of ch.roles || []) if (r) set.add(r)
  return [...set]
})
const facOpts = computed<string[]>(() => {
  const set = new Set<string>()
  for (const f of factions.value) if (f.name) set.add(f.name)
  for (const ch of chapters.value) for (const x of ch.factions || []) if (x) set.add(x)
  return [...set]
})
/* 道具功法选项 = 道具卡 ∪ 章节里已标注过的名字 */
const itemOpts = computed<string[]>(() => {
  const set = new Set<string>()
  for (const it of items.value) if (it.name) set.add(String(it.name))
  for (const ch of chapters.value) for (const x of ch.items || []) if (x) set.add(x)
  return [...set]
})
const genderMap = computed<Record<string, string>>(() => {
  const m: Record<string, string> = {}
  for (const c of cards.value) if (c.name) m[c.name] = c.gender || ''
  return m
})
const stanceMap = computed<Record<string, string>>(() => {
  const m: Record<string, string> = {}
  for (const f of factions.value) if (f.name) m[f.name] = f.stance || ''
  return m
})

const rows = computed(() => {
  const k = kw.value.trim().toLowerCase()
  return chapters.value.map((c, i) => ({ c, i, no: noOf(c, i) }))
    .filter(r => {
      if (filter.value === 'done' && !msMap.value[String(r.no)]) return false
      if (filter.value === 'todo' && msMap.value[String(r.no)]) return false
      return true
    })
    .filter(r => {
      if (!k) return true
      return String(r.c.title || '').toLowerCase().includes(k) || String(r.no).includes(k)
    })
})
const shown = computed(() => rows.value.slice(0, visible.value))
const hasMore = computed(() => rows.value.length > visible.value)
watch([kw, filter], () => { visible.value = 40 })

const cur = computed(() => (detail.value !== null ? chapters.value[detail.value] : null))
const curNo = computed(() => (cur.value && detail.value !== null ? noOf(cur.value, detail.value) : 0))

function touch() { dirty.value = true }
function open(i: number) { detail.value = i }
/* 关闭抽屉即保存：单个章节的增删改都是一次整包写回 */
async function close() {
  if (detail.value === null) return
  if (dirty.value) {
    const ok = await save(true)
    if (!ok) return
    dirty.value = false
  }
  detail.value = null
}
async function addChapter() {
  const maxNo = chapters.value.reduce((m, c, i) => Math.max(m, noOf(c, i)), 0)
  chapters.value.push({
    no: maxNo + 1, title: '', scene: '', summary: '', points: [], roles: [], factions: [],
    conflict: '', hook: '', hook_type: '', emotion: '', tension: '', payoff: '', setup: '',
  })
  const ok = await save(true)
  if (!ok) { chapters.value.pop(); return }
  dirty.value = false
  kw.value = ''
  filter.value = 'all'
  visible.value = 40
  detail.value = chapters.value.length - 1
  toast('已新增章节', 'ok')
}
async function delChapter() {
  if (detail.value === null) return
  if (!await confirmBox('删除这一章？', { danger: true, ok: '删除' })) return
  chapters.value.splice(detail.value, 1)
  detail.value = null
  const ok = await save(true)
  dirty.value = false
  if (!ok) { load(); return }
  toast('已删除', 'ok')
}
function splitLines(v: string): string[] {
  return v.split('\n').map(s => s.trim()).filter(Boolean)
}
const pointsText = computed({
  get: () => ((cur.value?.points || []) as string[]).join('\n'),
  set: (v: string) => { if (cur.value) cur.value.points = splitLines(v) },
})
</script>

<template>
  <div class="m-page m-page-fixed">
    <div class="m-head">
      <div>
        <h1>章节概括</h1>
        <p>{{ chapters.length }} 章 · 已成稿 {{ doneCount }} 章 · 逐章任务与节奏</p>
      </div>
      <div class="m-head-act">
        <button class="m-btn sm" :disabled="!raw" @click="addChapter">
          <Icon name="plus" :size="14" /> 新增
        </button>
      </div>
    </div>

    <div v-if="!state.books.length" class="m-empty" style="padding-top:70px">
      <span class="m-empty-ico"><Icon name="file" :size="28" /></span>
      <b>还没有作品</b>
      <p>先新建作品并完成拆解，章节概括会自动生成。</p>
    </div>

    <div v-else-if="!raw" class="m-empty" style="padding-top:70px">
      <span class="m-empty-ico"><Icon name="refresh" :size="28" /></span>
      <b>正在载入章节</b>
      <p>从本地作品数据里读取章节任务…</p>
    </div>

    <template v-else>
      <!-- 固定区：搜索 + 成稿筛选，章节列表单独滚动 -->
      <div class="m-head-fixed">
        <div class="m-searchbar">
          <Icon name="search" :size="16" />
          <input v-model="kw" placeholder="搜索章号或标题" />
          <button v-if="kw" class="m-clear" @click="kw = ''"><Icon name="close" :size="13" /></button>
        </div>

        <div class="m-seg" style="margin-bottom:11px">
          <button :class="{ on: filter === 'all' }" @click="filter = 'all'">全部 {{ chapters.length }}</button>
          <button :class="{ on: filter === 'done' }" @click="filter = 'done'">已成稿 {{ doneCount }}</button>
          <button :class="{ on: filter === 'todo' }" @click="filter = 'todo'">未成稿 {{ chapters.length - doneCount }}</button>
        </div>
      </div>

      <div class="m-page-scroll">
      <div v-if="chapters.length" class="m-ms-list">
        <button v-for="r in shown" :key="r.i" class="m-ms-card" @click="open(r.i)">
          <span class="m-ch-no" :class="{ has: !!msMap[String(r.no)] }">
            <template v-if="msMap[String(r.no)]">第<b>{{ r.no }}</b>章</template>
            <template v-else><b>{{ r.no }}</b>章</template>
          </span>
          <span class="m-ms-card-main">
            <b>{{ r.c.title || '未命名章节' }}</b>
            <small>
              <span v-if="msMap[String(r.no)]" style="color:var(--m-green)" class="m-ms-state">已成稿</span>
              <span v-else class="m-ms-state" style="color:var(--m-text3)">未成稿</span>
              <span v-if="msMap[String(r.no)]">· {{ msMap[String(r.no)]?.chars || 0 }} 字</span>
              <span v-else-if="r.c.summary">· {{ r.c.summary.slice(0, 22) }}{{ r.c.summary.length > 22 ? '…' : '' }}</span>
            </small>
            <span v-if="r.c.roles?.length || r.c.factions?.length || r.c.items?.length || r.c.hook_type" class="m-row-tags">
              <span v-for="x in (r.c.roles || []).slice(0, 3)" :key="'r' + x" class="m-tag" :class="genderTag(genderMap[x])">
                <Icon name="user" :size="9" />{{ x }}
              </span>
              <span v-for="f in (r.c.factions || []).slice(0, 2)" :key="'f' + f" class="m-tag" :class="stanceTag(stanceMap[f])">
                <Icon name="flag" :size="9" />{{ f }}
              </span>
              <span v-for="x in (r.c.items || []).slice(0, 2)" :key="'i' + x" class="m-tag"
                    style="color:#0f8a7a;background:#e6f6f2">
                <Icon name="shield" :size="9" />{{ x }}
              </span>
              <span v-if="r.c.hook_type" class="m-tag gold">{{ r.c.hook_type }}</span>
            </span>
          </span>
          <Icon name="right" :size="14" class="m-row-arrow" />
        </button>

        <button v-if="hasMore" class="m-load-more" @click="visible += 50">
          还有 {{ rows.length - visible }} 章，加载更多
        </button>
      </div>

      <div v-else class="m-empty">
        <span class="m-empty-ico"><Icon name="file" :size="28" /></span>
        <b>{{ chapters.length ? '没有匹配的章节' : '暂无章节' }}</b>
        <p>{{ chapters.length ? '换个章号、标题或筛选条件试试。' : '完成拆解后自动生成，也可以点右上角「新增」手动添加。' }}</p>
      </div>
      </div>

      <Modal :open="detail !== null" :title="cur ? `第 ${curNo} 章` : '章节'" @update:open="v => { if (!v) close() }">
        <div v-if="cur && detail !== null" class="m-modal-form" @input="touch" @change="touch">
          <div class="m-form-2">
            <div class="m-field">
              <label>章节序号</label>
              <input class="m-input" v-model="cur.no" inputmode="numeric" />
            </div>
            <div class="m-field">
              <label>章节标题</label>
              <input class="m-input" v-model="cur.title" placeholder="未命名章节" />
            </div>
          </div>
          <div class="m-field">
            <label>场景地点</label>
            <input class="m-input" v-model="cur.scene" placeholder="这一章发生在哪里" />
          </div>

          <div class="m-sec-title">本章任务</div>
          <div class="m-field">
            <label>本章摘要<em>{{ String(cur.summary || '').length }} 字</em></label>
            <textarea class="m-textarea" v-model="cur.summary" style="min-height:96px"
                      placeholder="这一章发生了什么…"></textarea>
          </div>
          <div class="m-field">
            <label>关键事件<em>每行一条</em></label>
            <textarea class="m-textarea" v-model="pointsText" style="min-height:110px"
                      placeholder="1. 主角发现线索&#10;2. 与守卫正面冲突&#10;3. 拿到关键道具"></textarea>
          </div>

          <div class="m-field">
            <label>出场角色<em>{{ (cur.roles || []).length }} 人</em></label>
            <SearchMultiSelect :model-value="cur.roles || []" :options="charOpts" mobile tone="user"
                               placeholder="从角色池选择，可搜索"
                               empty-text="角色池还是空的，先去「角色卡」添加"
                               @update:model-value="v => { cur.roles = v; touch() }" />
          </div>

          <div class="m-field">
            <label>涉及势力<em>{{ (cur.factions || []).length }} 个</em></label>
            <SearchMultiSelect :model-value="cur.factions || []" :options="facOpts" mobile tone="flag"
                               placeholder="从势力表选择，可搜索"
                               empty-text="势力表还是空的，先去「势力表」添加"
                               @update:model-value="v => { cur.factions = v; touch() }" />
          </div>

          <div class="m-field">
            <label>涉及道具功法<em>{{ (cur.items || []).length }} 件</em></label>
            <SearchMultiSelect :model-value="cur.items || []" :options="itemOpts" mobile tone="item"
                               placeholder="从道具功法表选择，可搜索"
                               empty-text="道具功法表还是空的，先去「道具功法」添加"
                               @update:model-value="v => { cur.items = v; touch() }" />
          </div>

          <div class="m-sec-title">节奏设计</div>
          <div class="m-field">
            <label>核心冲突点</label>
            <textarea class="m-textarea" v-model="cur.conflict" style="min-height:70px"
                      placeholder="这一章围绕什么矛盾展开"></textarea>
          </div>
          <div class="m-field">
            <label>情绪主线<em>2~3 个词，用 → 连接</em></label>
            <input class="m-input" v-model="cur.emotion" placeholder="憋屈→怒→爽" />
          </div>
          <div class="m-field">
            <label>情绪峰值<em>{{ cur.tension || '未标注' }} / 10</em></label>
            <input class="m-range" type="range" min="0" max="10" step="1" v-model.number="cur.tension" />
            <div class="m-range-scale"><span>平</span><span>5</span><span>炸</span></div>
          </div>
          <div class="m-field">
            <label>章末钩子类型</label>
            <div class="m-pick">
              <button v-for="h in HOOK_TYPES" :key="h" :class="{ on: cur.hook_type === h }"
                      @click="cur.hook_type = cur.hook_type === h ? '' : h; touch()">{{ h }}</button>
            </div>
          </div>
          <div class="m-field">
            <label>章末情绪钩子</label>
            <textarea class="m-textarea" v-model="cur.hook" style="min-height:64px"
                      placeholder="结尾留下什么悬念 / 情绪"></textarea>
          </div>
          <div class="m-field">
            <label>本章兑现<em>爽点 / 情绪释放</em></label>
            <textarea class="m-textarea" v-model="cur.payoff" style="min-height:64px"
                      placeholder="读者在这一章得到了什么"></textarea>
          </div>
          <div class="m-field">
            <label>本章铺垫<em>伏笔</em></label>
            <textarea class="m-textarea" v-model="cur.setup" style="min-height:64px"
                      placeholder="为后文埋下什么"></textarea>
          </div>
        </div>

        <template #footer>
          <div class="m-modal-foot">
            <button class="m-btn del" title="删除本章" @click="delChapter"><Icon name="trash" :size="16" /></button>
            <button class="m-btn" :disabled="saving" @click="close">
              <Icon name="check" :size="15" /> {{ saving ? '保存中…' : '完成' }}
            </button>
          </div>
        </template>
      </Modal>
    </template>
  </div>
</template>

<style scoped>
.m-range {
  width: 100%; height: 30px; margin: 2px 0 0;
  accent-color: var(--m-primary);
}
.m-range-scale { display: flex; justify-content: space-between; font-size: 10px; color: var(--m-text3); margin-top: -4px; }
</style>
