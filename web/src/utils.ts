/** 任意值 → 去空白字符串（cardMeta / factionMeta 等元数据匹配共用） */
export const norm = (v: any): string => String(v ?? '').trim()

export function fmtNum(n: number): string {
  n = Number(n) || 0
  if (n >= 10000) return (n / 10000).toFixed(n % 10000 ? 1 : 0) + ' 万'
  return String(n)
}
export function fmtSize(n: number): string {
  n = Number(n) || 0
  if (n >= 1048576) return (n / 1048576).toFixed(1) + ' MB'
  if (n >= 1024) return Math.floor(n / 1024) + ' KB'
  return n + ' B'
}

const pad2 = (n: number) => String(n).padStart(2, '0')

/** 秒级时间戳 → 「今天 09:41」/「10-29 21:30」（任务队列用） */
export function fmtTime(ts: number): string {
  if (!ts) return '—'
  const d = new Date(ts * 1000)
  const hm = `${pad2(d.getHours())}:${pad2(d.getMinutes())}`
  const sameDay = new Date().toDateString() === d.toDateString()
  return sameDay ? hm : `${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ${hm}`
}

/** 秒级时间戳 → HH:MM:SS（日志面板用） */
export function fmtClock(ts: number): string {
  if (!ts) return '--:--:--'
  const d = new Date(ts * 1000)
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`
}

/** 秒 → 12s / 3m05s / 1h02m */
export function fmtDur(sec: number): string {
  sec = Math.max(0, Math.round(Number(sec) || 0))
  if (sec < 60) return sec + 's'
  const m = Math.floor(sec / 60)
  if (m < 60) return `${m}m${pad2(sec % 60)}s`
  return `${Math.floor(m / 60)}h${pad2(m % 60)}m`
}

/** 性别标签配色：含「女」红、含「男」蓝、其余灰（章节表 / 角色卡 / 作品详情共用） */
export function genderTag(v: string): string {
  const s = String(v || '')
  return s.includes('女') ? 'red' : s.includes('男') ? 'blue' : 'gray'
}

/** 名称清洗：折叠模型复读出来的「孟孟孟皇后」「慈懿慈懿慈懿太后」等（与后端 entities.clean_name 同规则） */
export function cleanName(v: any, limit = 24): string {
  let s = String(v ?? '').replace(/\s+/g, '')
  s = s.replace(/^[：:·•\-—_、，,。.；;"'“”‘’《》〈〉()（）[\]【】{}]+|[：:·•\-—_、，,。.；;"'“”‘’《》〈〉()（）[\]【】{}]+$/g, '')
  let changed = true
  while (changed && s) {
    changed = false
    const n = s.length
    if (n % 2 === 0 && n / 2 >= 2 && s === s.slice(0, n / 2).repeat(2)) {
      s = s.slice(0, n / 2)
      changed = true
      continue
    }
    for (let unit = Math.floor(n / 2); unit >= 1 && !changed; unit--) {
      for (let i = 0; i + 2 * unit <= n; i++) {
        if (s.slice(i, i + unit) !== s.slice(i + unit, i + 2 * unit)) continue
        if (unit === 1) {
          const triple = i + 2 < n && s[i + 2] === s[i]
          const atHead = i === 0 && n > 2
          if (!triple && !atHead) continue
        }
        s = s.slice(0, i + unit) + s.slice(i + 2 * unit)
        changed = true
        break
      }
    }
  }
  return s.slice(0, limit)
}

/** 强度值归一：0.8 / 8 / 80 都收成 0~1 的两位小数（角色卡 / 势力表共用） */
export function normUnit(v: any): string {
  const s = String(v ?? '').trim()
  if (!s) return ''
  const m = s.match(/-?\d+(?:\.\d+)?/)
  if (!m) return s
  let x = Number(m[0])
  if (Number.isNaN(x)) return s
  if (x > 1 && x <= 10) x /= 10
  else if (x > 10 && x <= 100) x /= 100
  x = Math.max(0, Math.min(1, x))
  return String(Math.round(x * 100) / 100)
}
