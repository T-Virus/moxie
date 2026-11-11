import { reactive } from 'vue'
import { api } from './api'
import type { StudioData, ModelProfile } from './api'
import type { BookSummary, Stats } from './types'

const KEY = 'mb_settings'
/* 多模型档案的 API Key：只存浏览器 localStorage，绝不写服务端（服务端 studio.json 也只存模型/端点/单价） */
const PROFILE_KEYS = 'mb_profile_keys'
const saved = (() => { try { return JSON.parse(localStorage.getItem(KEY) || '{}') } catch { return {} } })()

interface State {
  books: BookSummary[]
  stats: Stats | null
  book: string
  key: string
  model: string
  baseUrl: string
  /* 本次任务的目标产出书名：任务跑完后自动选中它，避免停在上一本书 */
  outputBook: string
  /* 多模型工作台：档案库 + 工序绑定 + 服务商预设（GET /api/studio 载入） */
  studio: StudioData | null
}

export const state = reactive<State>({
  books: [],
  stats: null,
  book: saved.book || '',
  key: saved.key || '',
  model: saved.model || '',
  baseUrl: saved.baseUrl || '',
  outputBook: saved.outputBook || '',
  studio: null,
})

function persist() {
  // 隐私模式 / 存储配额满时 setItem 会抛错，设置丢失可接受，但不能把页面搞崩
  try {
    localStorage.setItem(KEY, JSON.stringify({
      book: state.book, key: state.key, model: state.model, baseUrl: state.baseUrl,
      outputBook: state.outputBook,
    }))
  } catch { /* ignore */ }
}

/* 任务目标书是否处于「文件还没落盘」的待生成状态（拆解/改编要跑完才写出 JSON） */
function isPending(): boolean {
  return !!state.book && state.book === state.outputBook &&
    !state.books.some(b => b.name === state.book)
}

/* 列表刷新后校准选中：
   · 选中的书存在 → 保持；
   · 选中的是任务目标书但还没落盘 → 保持（不能被列表刷新改成第一本）；
   · 选中的书确实不存在了（删除/改名）→ 回退到列表第一本 */
function reconcile() {
  const exists = state.books.some(b => b.name === state.book)
  if (exists) {
    if (state.outputBook && state.outputBook === state.book) { state.outputBook = ''; persist() }
    return
  }
  if (isPending()) return
  state.book = state.books[0]?.name || ''   // 书单为空（最后一本被删）时清空选中
  persist()
}

export const store = {
  async loadBooks() {
    const r = await api.getBooks()
    state.books = r.books || []
    reconcile()
    return state.books
  },
  async loadStats() {
    const r = await api.getStats()
    state.stats = r
    state.books = r.books || []
    reconcile()
    return r
  },
  /* 手动切换作品：放弃自动选中旧目标，用户当前选择优先 */
  setBook(n: string) {
    state.book = n
    if (state.outputBook && state.outputBook !== n) state.outputBook = ''
    persist()
  },
  /* 任务开始前登记最终产出书名（留空表示由后端自动命名、无法预知） */
  setOutputBook(n: string) { state.outputBook = (n || '').trim(); persist() },
  /* 任务失败/放弃：清掉目标书；若选中正指向这本不存在的书，回退到第一本 */
  clearOutputBook() {
    if (!state.outputBook) return
    state.outputBook = ''
    persist()
    reconcile()
  },
  /* 任务跑完后调用：刷新书列表并选中产出书；书还没出现就先留着，等下一次完成事件再选。
     无论是否登记了目标书都先刷新列表，调用方不必再自己 loadBooks */
  async selectOutputBook(): Promise<boolean> {
    await store.loadBooks().catch(() => [])
    const name = state.outputBook
    if (!name) return false
    if (state.books.some(b => b.name === name)) {
      state.book = name
      state.outputBook = ''
      persist()
      return true
    }
    return false
  },
  curBook(): string {
    // 只读，不做副作用：选中的书存在、或是任务目标书（尚未落盘）都优先；
    // 其余情况才回退到第一本，且不改写 state，避免 watch 依赖收集期间清空当前书
    if (state.book && (state.books.some(b => b.name === state.book) || isPending())) return state.book
    return state.books[0]?.name || state.book || ''
  },
  saveSettings() { persist() },

  /* ---------------- 多模型档案 ---------------- */
  async loadStudio(): Promise<StudioData> {
    const d = await api.getStudio()
    state.studio = d
    return d
  },
  async saveStudio(d: StudioData): Promise<StudioData> {
    const r = await api.putStudio(d)
    state.studio = { ...r, stage_label: d.stage_label, provider_presets: d.provider_presets }
    return r
  },
  /* 档案 Key：只进不出（读给请求用，永不发给 PUT /api/studio） */
  profileKeys(): Record<string, string> {
    try { return JSON.parse(localStorage.getItem(PROFILE_KEYS) || '{}') } catch { return {} }
  },
  profileKey(pid: string): string {
    return (store.profileKeys()[pid] || '').trim()
  },
  setProfileKey(pid: string, key: string) {
    try {
      const all = store.profileKeys()
      if (key && key.trim()) all[pid] = key.trim()
      else delete all[pid]
      localStorage.setItem(PROFILE_KEYS, JSON.stringify(all))
    } catch { /* ignore */ }
  },
  /* 某道工序当前绑定的档案 + 它的 Key（没绑定 / 档案被删返回 null） */
  profileFor(stageKey: string): { pid: string; profile: ModelProfile; api_key: string } | null {
    const s = state.studio
    if (!s) return null
    const pid = (s.bindings || {})[stageKey] || ''
    const profile = pid && (s.profiles || {})[pid]
    if (!profile) return null
    return { pid, profile, api_key: store.profileKey(pid) }
  },
  /* 页面发请求用的凭据：档案绑定优先，其次页面临时输入（state.key/model/baseUrl 老逻辑兜底） */
  callCreds(stageKey: string): { api_key: string; model: string; base_url: string } {
    const hit = store.profileFor(stageKey)
    return {
      api_key: hit?.api_key || state.key || '',
      model: hit?.profile.model || state.model || '',
      base_url: hit?.profile.base_url || state.baseUrl || '',
    }
  },
}
