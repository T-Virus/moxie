/** 轻量 Markdown 渲染：覆盖工作台产物常见的标题 / 列表 / 段落 / 强调，先转义再排版。 */
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function inline(text: string): string {
  return escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
}

// 安全边界：本渲染器只输出白名单标签，且所有文本都先经 escapeHtml 转义。
// 切勿新增任何「先替换后转义」或允许原始 HTML 透传的分支，否则配合 BodyTab.vue 的 v-html 会导致存储型 XSS。
// 若未来切换到 marked / markdown-it 等通用库，必须对其输出再用 DOMPurify 净化后再交给 v-html。
export function renderMarkdown(markdown: string): string {
  const lines = markdown.replace(/\r\n/g, '\n').split('\n')
  const out: string[] = []
  let list: { type: 'ul' | 'ol'; items: string[] } | null = null

  const flush = (): void => {
    if (!list) return
    const tag = list.type
    out.push(`<${tag}>${list.items.map((item) => `<li>${inline(item)}</li>`).join('')}</${tag}>`)
    list = null
  }

  for (const raw of lines) {
    const line = raw.trimEnd()
    if (!line.trim()) {
      flush()
      continue
    }
    if (/^(---+|___+|\*\*\*+)$/.test(line.trim())) {
      flush()
      out.push('<hr />')
      continue
    }
    const heading = /^(#{1,4})\s+(.*)$/.exec(line)
    if (heading) {
      flush()
      const level = heading[1].length
      out.push(`<h${level}>${inline(heading[2])}</h${level}>`)
      continue
    }
    const bullet = /^[-*•]\s+(.*)$/.exec(line)
    if (bullet) {
      if (list?.type !== 'ul') {
        flush()
        list = { type: 'ul', items: [] }
      }
      list.items.push(bullet[1])
      continue
    }
    const ordered = /^\d+\.\s+(.*)$/.exec(line)
    if (ordered) {
      if (list?.type !== 'ol') {
        flush()
        list = { type: 'ol', items: [] }
      }
      list.items.push(ordered[1])
      continue
    }
    flush()
    out.push(`<p>${inline(line.trim())}</p>`)
  }
  flush()
  return out.join('\n')
}

export interface OutlineChapter {
  no: number
  title: string
  summary: string
}

/**
 * 从 outline.md 提取章节大纲。
 * 兼容 `### 第 N 章 标题` 小标题与 `1. 第 N 章 标题` 列表两种写法。
 */
export function parseOutlineChapters(markdown: string): OutlineChapter[] {
  const lines = markdown.replace(/\r\n/g, '\n').split('\n')
  const chapters: OutlineChapter[] = []
  let current: OutlineChapter | null = null

  const push = (): void => {
    if (current) chapters.push(current)
    current = null
  }

  for (const raw of lines) {
    const line = raw.trim()
    const heading = /^(#{2,4})\s*(?:第\s*)?(\d+)\s*章\s*(?:[·：:—]\s*)?(.*)$/.exec(line)
    if (heading) {
      push()
      current = { no: Number(heading[2]), title: heading[3].trim(), summary: '' }
      continue
    }
    if (/^#{1,4}\s/.test(line)) {
      push()
      continue
    }
    if (!current || !line) continue
    current.summary = current.summary ? `${current.summary} ${line}` : line
  }
  push()

  if (chapters.length) return chapters

  // 列表写法回退
  for (const raw of lines) {
    const line = raw.trim()
    const item = /^(?:\d+\.|[-*])\s*(?:第\s*)?(\d+)\s*章\s*(?:[·：:—]\s*)?(.*)$/.exec(line)
    if (!item) continue
    chapters.push({ no: Number(item[1]), title: item[2].trim(), summary: '' })
  }
  return chapters
}
