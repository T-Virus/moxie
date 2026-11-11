import { onScopeDispose, ref, watch } from 'vue'
import { api } from '../api'
import { store } from '../store'
import { toast } from '../ui'
import type { ChaptersData } from '../types'

type Ent = Record<string, string>
type Track = { ref: Ent; name: string }

/**
 * 当前作品的 chapters.json 文档（全书要素 / 角色卡 / 势力表 / 逐章任务共用）。
 * 各模块视图只修改自己关心的切片，save() 统一整包写回。
 */
export function useBookDoc() {
  const raw = ref<ChaptersData | null>(null)
  const fields = ref<Record<string, string>>({})
  const cards = ref<Record<string, string>[]>([])
  const factions = ref<Record<string, string>[]>([])
  const items = ref<Record<string, string>[]>([])
  const chapters = ref<any[]>([])
  const loading = ref(false)
  const saving = ref(false)

  let seq = 0

  /* 改名追踪：以「加载 / 上次保存」时的对象引用 + 名称为基线。
     同一个卡片对象（引用不变）名字变了才算改名；删卡后新增的卡是新对象，不会被误判成改名，
     所以直接编辑名称、批量改名两条路都能把章节引用、关系对象、道具持有者一起同步。 */
  let base: { characters: Track[]; factions: Track[]; items: Track[] } =
    { characters: [], factions: [], items: [] }

  const nameOf = (e: Ent) => String(e?.name ?? '').trim()

  function snapshotBase() {
    base = {
      characters: cards.value.map(c => ({ ref: c, name: nameOf(c) })),
      factions: factions.value.map(f => ({ ref: f, name: nameOf(f) })),
      items: items.value.map(it => ({ ref: it, name: nameOf(it) })),
    }
  }

  /** 把当前数组与基线对比，得出「旧名 → 新名」；只认还在数组里的同一对象 */
  function diffNames(list: Track[], cur: Ent[]): Record<string, string> {
    const alive = new Set<Ent>(cur)
    const map: Record<string, string> = {}
    for (const t of list) {
      if (!alive.has(t.ref)) continue
      const now = nameOf(t.ref)
      if (t.name && now && now !== t.name && !map[t.name]) map[t.name] = now
    }
    return map
  }

  /** 服务端返回的整份视图原地回显（GET 与 PUT 同一口径），并把基线重置到新数据 */
  function applyDoc(ch: ChaptersData) {
    raw.value = ch
    fields.value = ch.story_bible_fields || {}
    cards.value = (ch.story_bible_cards || []) as Ent[]
    factions.value = (ch.story_bible_factions || []) as Ent[]
    items.value = (ch.items || []) as Ent[]
    chapters.value = ch.chapters || []
    snapshotBase()
  }

  async function load() {
    const book = store.curBook()
    if (!book) { raw.value = null; return }
    const my = ++seq
    loading.value = true
    /* 先清空上一本的文档：切书瞬间回显立即跟随 stats（与侧栏一致），而不是短暂残留旧书数据 */
    raw.value = null
    fields.value = {}
    cards.value = []
    factions.value = []
    items.value = []
    chapters.value = []
    base = { characters: [], factions: [], items: [] }
    try {
      const ch = await api.getChapters(book)
      if (my !== seq) return   // 期间又发起了更新的加载，丢弃旧结果
      applyDoc(ch)
    } catch (e: any) {
      if (my === seq) toast('载入失败：' + e.message, 'err')
    }
    if (my === seq) loading.value = false
  }

  /* renames：批量改名 / 删卡时显式给出的映射；直接改卡片名称的映射由 diffNames 自动补上，
     服务端会在同一遍里同步章节引用与关系对象，并把保存后的完整数据返回，页面直接用它回显。 */
  async function save(silent = false,
                      renames?: Record<string, Record<string, string>>): Promise<boolean> {
    if (!raw.value || !store.curBook()) return false
    saving.value = true
    try {
      const payload: Record<string, Record<string, string>> = {}
      const auto = {
        characters: diffNames(base.characters, cards.value),
        factions: diffNames(base.factions, factions.value),
        items: diffNames(base.items, items.value),
      }
      for (const kind of ['characters', 'factions', 'items'] as const) {
        const m = { ...(auto[kind] || {}), ...(renames?.[kind] || {}) }
        if (Object.keys(m).length) payload[kind] = m
      }
      const ch = await api.putChapters(store.curBook(), {
        ...raw.value,
        chapters: chapters.value,
        story_bible_fields: fields.value,
        story_bible_cards: cards.value,
        story_bible_factions: factions.value,
        items: items.value,
        ...(Object.keys(payload).length ? { renames: payload } : {}),
      })
      if (ch) applyDoc(ch)
      else await load()
      if (!silent) toast('已保存', 'ok')
      store.loadStats().catch(() => {})
      return true
    } catch (e: any) {
      toast(e.message, 'err')
      return false
    }
    finally { saving.value = false }
  }

  /** 批量改名：旧名→新名一次提交，服务端同步全部引用后本页直接回显新数据 */
  async function batchRename(kind: 'characters' | 'factions' | 'items',
                             mapping: Record<string, string>): Promise<boolean> {
    if (!Object.keys(mapping).length) return false
    return save(true, { [kind]: mapping })
  }

  // 挂载立即加载 + 切换作品自动重载（immediate 保证懒加载组件晚于 loadStats 挂载时也能取到数据）
  watch(() => store.curBook(), load, { immediate: true })

  /* 设置里导入数据 zip 之后，正在打开的书内页面要跟着刷新回显 */
  const onDataChanged = () => { store.loadBooks().catch(() => {}); load() }
  if (typeof window !== 'undefined') {
    window.addEventListener('mowrite:data-changed', onDataChanged)
    onScopeDispose(() => window.removeEventListener('mowrite:data-changed', onDataChanged))
  }

  return { raw, fields, cards, factions, items, chapters, loading, saving, load, save, batchRename }
}
