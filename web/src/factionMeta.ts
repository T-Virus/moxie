/* 势力「立场」的规范取值、释义与配色。
   与后端 src/story_bible.py 的 FACTION_STANCES 一一对应；
   势力的「组织性质」用 cardMeta.ts 的 FACTION_CATEGORIES（势力大类），两套词不再重复。
   前端所有势力标签（势力表、章节概括、章节工作台）都从这里取色，避免各页颜色不一致。 */

import { norm } from './utils'

export interface FactionMeta {
  key: string          /* 规范 key，与后端一致 */
  label: string        /* 展示用中文词，也是写回数据的值 */
  note: string         /* 名词注释：这一类的判定含义 */
  color: string        /* 文字 / 色点色 */
  bg: string           /* 标签底色 */
}

/* 立场：此刻对主角的态度（9 类） */
export const STANCES: FactionMeta[] = [
  { key: 'own', label: '己方', note: '主角阵营核心成员', color: '#2f6bff', bg: '#eef3ff' },
  { key: 'ally', label: '盟友', note: '暂时合作、利益一致', color: '#0ca678', bg: '#e6f7f0' },
  { key: 'neutral', label: '中立', note: '不站队，无明显敌友', color: '#6b7280', bg: '#f2f3f5' },
  { key: 'watch', label: '观望', note: '暂时不动，可能倒向任一方', color: '#b8860b', bg: '#fff8e1' },
  { key: 'rival', label: '竞争', note: '目标冲突，但未必生死相向', color: '#7b61ff', bg: '#f1edff' },
  { key: 'hostile', label: '敌对', note: '明确对立，会制造冲突', color: '#f76707', bg: '#fff2e8' },
  { key: 'nemesis', label: '死敌', note: '深仇大恨，不可调和', color: '#e03131', bg: '#feeceb' },
  { key: 'betray', label: '背叛', note: '曾经友善或中立，后来反水', color: '#d6336c', bg: '#fff0f6' },
  { key: 'hidden', label: '潜伏', note: '表面中立或己方，实际另有目的', color: '#5f3dc4', bg: '#f3f0ff' },
]

/* 关键词兜底：旧数据 / AI 自由表述（如「暗中支持主角」「世仇」）也能着色。
   顺序与后端一致，更具体的词在前，避免被宽泛词吃掉。 */
const STANCE_HINTS: [string, string[]][] = [
  ['own', ['己方', '我方', '自己人', '主角方', '主角阵营', '同门', '麾下', '嫡系',
    '属下', '部属', '亲信', '归附', '归降', '效忠主角']],
  ['hidden', ['潜伏', '卧底', '内应', '暗桩', '伪装', '暗中支持', '暗助', '幕后', '另有目的']],
  ['betray', ['背叛', '反水', '叛变', '倒戈', '叛出', '反目']],
  ['nemesis', ['死敌', '宿敌', '世仇', '血仇', '不共戴天', '势不两立', '复仇灭']],
  ['watch', ['观望', '犹豫', '按兵不动', '随时倒向', '摇摆', '墙头', '骑墙', '逐利',
    '趋利', '自保', '待价', '保存实力']],
  ['rival', ['竞争', '竞逐', '争夺', '抢生意', '同赛道', '扩张', '自立', '争霸', '挑战', '比武']],
  ['ally', ['盟友', '同盟', '联盟', '友方', '友军', '友好', '友善', '合作', '利益一致',
    '互通', '互市', '贸易', '交易', '援助', '援军', '唇亡齿寒']],
  ['hostile', ['敌对', '敌方', '对抗', '仇视', '对立', '冲突', '入侵', '吞并', '敌视',
    '围剿', '清剿', '剿灭', '镇压', '讨伐', '讨平', '攻打', '攻击', '掠夺',
    '劫掠', '打压', '施压', '封锁', '威胁', '反抗']],
  ['neutral', ['中立', '不站队', '无明显敌友', '两不相帮', '各自为战', '利益优先',
    '未知', '内斗', '倾轧', '松散']],
]

function resolve(v: any, table: FactionMeta[], hints: [string, string[]][]): FactionMeta | null {
  const s = norm(v)
  if (!s) return null
  const exact = table.find(m => m.label === s || m.key === s)
  if (exact) return exact
  for (const [key, kws] of hints) {
    if (kws.some(k => s.includes(k))) return table.find(m => m.key === key) || null
  }
  return null
}

export const stanceMeta = (v: any) => resolve(v, STANCES, STANCE_HINTS)

/* 标签 CSS 类（配色定义在 assets/base.css）：
   认不出时退回 gray，保证有底色可读，原文仍照常显示 */
export const stanceTag = (v: any) => {
  const m = stanceMeta(v)
  return m ? `st-${m.key}` : 'gray'
}
