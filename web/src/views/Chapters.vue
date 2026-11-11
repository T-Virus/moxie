<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import Icon from '../components/Icon.vue'
import BackLink from '../components/BackLink.vue'
import Collapse from '../components/Collapse.vue'
import EmptyBox from '../components/EmptyBox.vue'
import SearchMultiSelect from '../components/SearchMultiSelect.vue'
import SelectBox from '../components/SelectBox.vue'
import { store, state } from '../store'
import { useBookDoc } from '../composables/useBookDoc'
import { confirmBox, toast } from '../ui'
import { genderTag } from '../utils'
import { stanceMeta, stanceTag as stanceTagOf } from '../factionMeta'

const { raw, chapters, cards, factions, items, saving, load, save } = useBookDoc()

onMounted(() => { store.loadBooks().catch(() => {}); load() })

function splitLines(v: string): string[] {
  return v.split('\n').map(s => s.trim()).filter(Boolean)
}

/* 章末钩子类型：与后端 HOOK_TYPES 同一套词，只允许这六种 */
const HOOK_TYPES = ['悬念', '危机', '反转', '期待', '信息差', '情感']
/* 下拉选项：候选项 + 旧值（显示标注，保存原值） */
function hookOptions(cur: string) {
  const out: { label: string; value: string }[] = []
  if (cur && !HOOK_TYPES.includes(cur)) out.push({ label: cur + '（旧值）', value: cur })
  for (const h of HOOK_TYPES) out.push({ label: h, value: h })
  return out
}

/* ---- 角色 / 势力选项与标签色 ---- */
/* 势力标签按 9 类立场配色，与势力表一致（颜色定义见 factionMeta.ts / base.css） */
const stanceTag = (v: string) => stanceTagOf(v)
/* 阵营 / 立场：章节头部标签用立场色，鼠标悬停可看阵营释义 */
const stanceNote = (v: string) => stanceMeta(v)?.note || ''
/* 势力大类直接取卡片上的 category（已与「阵营」合并） */
const factionCamp = (v: string) => String(factionMap.value[v]?.category || '')
/* 姓名索引：性别 / 阵营 */
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
/* 阵营索引：用于标签悬停提示与「涉及势力」选项的说明 */
const factionMap = computed<Record<string, Record<string, string>>>(() => {
  const m: Record<string, Record<string, string>> = {}
  for (const f of factions.value) if (f.name) m[f.name] = f
  return m
})
/* 选项 = 已有角色/势力 ∪ 章节里已标注的名字（保留手工输入过的值） */
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
/* 章号：优先 no 字段，其次从 chapter_id / id / title 提取数字（如 "第1章"），最后用序号兜底 */
function noOf(c: any, i = 0): number {
  for (const k of ['no', 'chapter_id', 'id', 'title']) {
    const m = String(c?.[k] ?? '').match(/\d+/)
    if (m) return Number(m[0])
  }
  return i + 1
}
const scrollEl = ref<HTMLElement | null>(null)

/* ---- 搜索 + 分页：按章节号或标题过滤，每页只渲染 PAGE_SIZE 章；编辑仍针对全量数组 ---- */
const PAGE_SIZE = 50
const kw = ref('')
const page = ref(1)
/* 命中规则：标题包含关键词；关键词里带数字时，同时按章号精确匹配（支持「3」「第3章」「03」） */
function hitChapter(c: any, i: number, k: string): boolean {
  if (String(c?.title ?? '').toLowerCase().includes(k)) return true
  const m = k.match(/\d+/)
  return !!m && noOf(c, i) === Number(m[0])
}
/* 过滤结果保留原始下标：搜索态下编辑 / 删除都落在真实章节上 */
const rows = computed(() => {
  const k = kw.value.trim().toLowerCase()
  return chapters.value.map((c, i) => ({ c, i })).filter(r => !k || hitChapter(r.c, r.i, k))
})
const pageCount = computed(() => Math.max(1, Math.ceil(rows.value.length / PAGE_SIZE)))
const pageStart = computed(() => (Math.min(page.value, pageCount.value) - 1) * PAGE_SIZE)
const pageRows = computed(() => rows.value.slice(pageStart.value, pageStart.value + PAGE_SIZE))

/* 页码越界自动回退：过滤后章数变少 / 删除末页章节时不会出现「3 / 2 页」 */
watch(pageCount, n => { if (page.value > n) page.value = n })
/* 搜索词变化回到第一页并回顶 */
watch(kw, () => {
  page.value = 1
  nextTick(() => { if (scrollEl.value) scrollEl.value.scrollTop = 0 })
})
/* 切换作品清空搜索、回到第一页并回到顶部 */
watch(() => store.curBook(), () => {
  kw.value = ''
  page.value = 1
  if (scrollEl.value) scrollEl.value.scrollTop = 0
})
function goPage(p: number) {
  const n = Math.min(Math.max(1, Math.round(p) || 1), pageCount.value)
  if (n === page.value) return
  page.value = n
  nextTick(() => { if (scrollEl.value) scrollEl.value.scrollTop = 0 })
}

function addChapter() {
  const maxNo = chapters.value.reduce((m, c, i) => Math.max(m, noOf(c, i)), 0)
  chapters.value.push({
    no: maxNo + 1, title: '', scene: '', summary: '', points: [], roles: [], factions: [],
    conflict: '', hook: '', hook_type: '', emotion: '', tension: '', payoff: '', setup: '',
  })
  kw.value = ''   // 清空搜索，保证新章节可见
  /* 页码在 nextTick 里设：kw 的 watcher 会先把页码拉回第 1 页，这里再覆盖到末页 */
  nextTick(() => {
    page.value = pageCount.value
    nextTick(() => { if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight })
  })
}
async function delChapter(i: number) {
  if (!await confirmBox('删除这一章？', { danger: true, ok: '删除' })) return
  chapters.value.splice(i, 1)
  /* 页码回退交给 watch(pageCount)，这里不再做易错的边界判断 */
}
async function copyChapter(i: number) {
  const c = chapters.value[i]
  const lines: string[] = []
  lines.push('第' + (c.no || noOf(c, i)) + '章 ' + (c.title || ''))
  if (c.scene) lines.push('场景地点：' + c.scene)
  if (c.summary) lines.push('本章摘要：\n' + c.summary)
  if ((c.points || []).length) lines.push('关键事件：\n' + c.points.join('\n'))
  if ((c.roles || []).length) lines.push('出场角色：' + c.roles.join('、'))
  if ((c.factions || []).length) lines.push('涉及势力：' + c.factions.join('、'))
  if ((c.items || []).length) lines.push('涉及道具功法：' + c.items.join('、'))
  try {
    await navigator.clipboard.writeText(lines.join('\n\n'))
    c.copiedAt = new Date().toLocaleString('zh-CN', { hour12: false })
    toast('已复制到剪贴板', 'ok')
  } catch (e) {
    toast('复制失败，请检查浏览器权限', 'err')
  }
}
</script>

<template>
  <div v-if="!state.books.length" class="card"><EmptyBox title="还没有作品" desc="先「新建作品」并完成拆解" /></div>
  <div v-else-if="!raw" class="card"><EmptyBox title="请选择作品" desc="在左侧作品集合中选择一本书" /></div>
  <template v-else>
    <div class="page-head"><div><h1>章节概括</h1>
      <p>逐章摘要、关键事件与出场角色——正文生成按这里的任务逐章扩写。</p></div>
    </div>
    <div class="card page-card">
      <div class="toolbar">
        <BackLink class="m-back" />
        <span class="hint">
          {{ kw ? `匹配 ${rows.length} / 共 ${chapters.length} 章` : `共 ${chapters.length} 章` }}</span>
        <div class="tb-right">
          <div class="tb-search">
            <input class="input" v-model="kw" placeholder="搜索章节号或标题" />
            <button v-if="kw" class="link-btn" @click="kw = ''">清除</button>
          </div>
          <div class="tb-pager" :title="`每页 ${PAGE_SIZE} 章`">
            <button class="btn ghost icon-only" :disabled="page <= 1" title="上一页" @click="goPage(page - 1)">
              <Icon name="left" :size="14" /></button>
            <span class="hint">{{ page }} / {{ pageCount }}</span>
            <button class="btn ghost icon-only" :disabled="page >= pageCount" title="下一页" @click="goPage(page + 1)">
              <Icon name="right" :size="14" /></button>
          </div>
          <div class="tb-acts">
            <button class="btn ghost" @click="addChapter"><Icon name="plus" :size="14" /> 加章节</button>
            <button class="btn m-save-hide" :disabled="saving" @click="save()"><Icon name="check" :size="15" /> 保存</button>
          </div>
        </div>
      </div>
      <div class="form-scroll" ref="scrollEl">
        <EmptyBox v-if="!chapters.length" title="暂无章节" desc="完成拆解后自动生成，也可以手动添加" />
        <EmptyBox v-else-if="!rows.length" title="没有匹配的章节" desc="换个章号或标题关键词试试，或点击「清除」查看全部" />
        <Collapse v-for="r in pageRows" :key="r.i" class="ch-item">
        <template #head>
          <span class="no">{{ r.c.no || noOf(r.c, r.i) }}</span>
          <span class="t">{{ r.c.title || '未命名' }}</span>
          <span v-for="x in (r.c.roles || [])" :key="'r' + x" class="tag" :class="genderTag(genderMap[x])"
                title="出场角色"><Icon name="user" :size="11" />{{ x }}</span>
          <span v-for="f in (r.c.factions || [])" :key="'f' + f" class="tag" :class="stanceTag(stanceMap[f])"
                :title="'涉及势力｜大类：' + (factionCamp(f) || '未标注') + '｜立场：' + (stanceNote(stanceMap[f]) || '未标注')"><Icon name="flag" :size="11" />{{ f }}</span>
          <span v-for="x in (r.c.items || [])" :key="'i' + x" class="tag" style="color:#0f8a7a;background:#e6f6f2"
                title="涉及道具 / 功法"><Icon name="shield" :size="11" />{{ x }}</span>
          <span class="head-acts">
            <span v-if="r.c.copiedAt" class="tag green" :title="'复制于 ' + r.c.copiedAt">已复制 · {{ r.c.copiedAt }}</span>
            <button class="icon-btn" title="复制本章" @click.stop="copyChapter(r.i)"><Icon name="copy" :size="14" /></button>
            <button class="icon-btn red" title="删除本章" @click.stop="delChapter(r.i)"><Icon name="trash" :size="14" /></button>
          </span>
        </template>
        <div class="form-grid">
          <div class="field"><label>章节序号</label><input class="input" v-model="r.c.no" /></div>
          <div class="field"><label>章节标题</label><input class="input" v-model="r.c.title" /></div>
          <div class="field full"><label>场景地点</label><input class="input" v-model="r.c.scene" /></div>
          <div class="field full"><label>核心冲突点</label><textarea class="textarea" v-model="r.c.conflict" style="min-height:56px"></textarea></div>
          <div class="field full"><label>章末情绪钩子</label><textarea class="textarea" v-model="r.c.hook" style="min-height:48px"></textarea></div>
          <div class="field"><label>章末钩子类型</label>
            <SelectBox allow-empty :model-value="r.c.hook_type" :options="hookOptions(r.c.hook_type)"
                       @update:model-value="v => r.c.hook_type = v" /></div>
          <div class="field"><label>情绪峰值（1~10）</label>
            <input class="input" type="number" min="1" max="10" v-model.number="r.c.tension" placeholder="1~10" /></div>
          <div class="field full"><label>情绪主线（2~3 个词，用 → 连接）</label>
            <input class="input" v-model="r.c.emotion" placeholder="憋屈→怒→爽" /></div>
          <div class="field full"><label>本章兑现（爽点 / 情绪释放）</label>
            <textarea class="textarea" v-model="r.c.payoff" style="min-height:48px"></textarea></div>
          <div class="field full"><label>本章铺垫（伏笔）</label>
            <textarea class="textarea" v-model="r.c.setup" style="min-height:48px"></textarea></div>
          <div class="field full"><label>本章摘要</label>
            <textarea class="textarea" v-model="r.c.summary" style="min-height:80px"></textarea></div>
          <div class="field full"><label>关键事件（每行一条）</label>
            <textarea class="textarea" :value="(r.c.points || []).join('\n')"
                      @input="e => r.c.points = splitLines((e.target as HTMLTextAreaElement).value)"
                      style="min-height:130px"></textarea></div>
          <div class="field full"><label>出场角色（从角色池选择，可搜索）</label>
            <SearchMultiSelect :model-value="r.c.roles || []" :options="charOpts"
                               tone="user" placeholder="点击选择角色，支持搜索"
                               @update:model-value="v => r.c.roles = v" /></div>
          <div class="field full"><label>涉及势力（从势力表选择，可搜索）</label>
            <SearchMultiSelect :model-value="r.c.factions || []" :options="facOpts"
                               tone="flag" placeholder="点击选择势力，支持搜索"
                               @update:model-value="v => r.c.factions = v" /></div>
          <div class="field full"><label>涉及道具功法（从道具功法表选择，可搜索）</label>
            <SearchMultiSelect :model-value="r.c.items || []" :options="itemOpts"
                               tone="item" placeholder="点击选择道具 / 功法，支持搜索"
                               @update:model-value="v => r.c.items = v" /></div>
        </div>
      </Collapse>
      </div>
      <!-- 手机：保存常驻底部 -->
      <div class="m-save-bar">
        <button class="btn lg" :disabled="saving" @click="save()">
          <Icon name="check" :size="16" /> 保存章节</button>
      </div>
    </div>
  </template>
</template>

<style scoped>
/* 手机：工具条收敛成两行（搜索一行、翻页 + 加章节一行），保存固定在底部 */
@media (max-width: 760px) {
  .toolbar { gap: 8px; padding-bottom: 10px; }
  /* 只隐藏「共 N 章」计数，保留「1/1 页 · 每页 50 章」的页码信息 */
  .toolbar > .hint:first-of-type { display: none; }
  .toolbar .input { flex: 1 1 100%; width: 100%; }
  .toolbar .btn.ghost { height: 36px; }
  /* 章节头不换行：标题占满剩余宽度，复制 / 删除保持在右侧同一行 */
  .ch-item :deep(.collapse-head) { flex-wrap: nowrap; }
  .ch-item :deep(.collapse-head .t) { flex: 1 1 auto; min-width: 0; }
  .ch-item :deep(.collapse-head .head-acts) { margin-left: auto; }
}
</style>
