/* 角色卡「人设分析 / 势力归属 / 关系」的规范取值。
   与后端 src/story_bible.py 的 ALIGNMENTS / ROLE_FUNCS / RELATION_KINDS /
   FACTION_CATEGORIES / FACTION_REL_TYPES 一一对应：
   下拉选项、3×3 九宫格、图谱配色与分组、右侧名词注释都从这里取，避免各处颜色与用词不一致。 */

import { norm } from './utils'

export interface AlignMeta {
  key: string
  label: string      /* 守序善良…混乱邪恶 */
  note: string       /* 名词注释：这一格的行为准则 */
  color: string
  bg: string
  row: number        /* 0 善良 / 1 中立 / 2 邪恶 */
  col: number        /* 0 守序 / 1 中立 / 2 混乱 */
}

export interface RoleMeta {
  key: string
  label: string
  note: string
  color: string
  bg: string
}

export interface RelationMeta {
  key: string
  label: string
  note: string
  example: string
  color: string
  bg: string
  /* 这类关系天然的方向：单向的（暗恋/监视/利用/救命）默认填「单向」 */
  oneWay?: boolean
}

export interface FactionCategoryMeta {
  key: string
  label: string
  example: string
  color: string
  bg: string
}

/* 九宫格：行＝善良/中立/邪恶，列＝守序/中立/混乱（经典 D&D 排布） */
export const ALIGNMENTS: AlignMeta[] = [
  { key: 'lg', label: '守序善良', note: '守规矩、有底线，以正当手段护弱济困', color: '#2b8a3e', bg: '#e6f6ea', row: 0, col: 0 },
  { key: 'ng', label: '中立善良', note: '本能地帮人，不被规矩绑住，也不刻意越界', color: '#37b24d', bg: '#ebfbee', row: 0, col: 1 },
  { key: 'cg', label: '混乱善良', note: '重情义轻规则，为善可以抗命、越界、惹祸', color: '#74b816', bg: '#f4fce3', row: 0, col: 2 },
  { key: 'ln', label: '守序中立', note: '守规则、尽本分，不主动行善也不作恶', color: '#1c7ed6', bg: '#e7f5ff', row: 1, col: 0 },
  { key: 'nn', label: '绝对中立', note: '随局势而动，不持立场、不轻易选边', color: '#868e96', bg: '#f1f3f5', row: 1, col: 1 },
  { key: 'cn', label: '混乱中立', note: '我行我素，行事全凭当下兴致', color: '#f59f00', bg: '#fff9db', row: 1, col: 2 },
  { key: 'le', label: '守序邪恶', note: '借规则与权威压榨他人，恶得有条理、有野心', color: '#c92a2a', bg: '#fff5f5', row: 2, col: 0 },
  { key: 'ne', label: '中立邪恶', note: '只为自己，损人利己，谁挡路就除谁', color: '#a61e4d', bg: '#fff0f6', row: 2, col: 1 },
  { key: 'ce', label: '混乱邪恶', note: '以破坏与折磨为乐，不计后果', color: '#5f3dc4', bg: '#f3f0ff', row: 2, col: 2 },
]

export const ALIGN_AXES = { rows: ['善良', '中立', '邪恶'], cols: ['守序', '中立', '混乱'] }

/* 种族 / 物种：只给常见预设，允许直接写自定义值（自造种族是网文常态） */
export const RACES = ['人族', '妖族', '魔族', '神族', '仙族', '精灵', '兽人', '亡灵',
  '吸血鬼', '龙族', '机械', '异形', '混血', '其他']

/* 剧情功能：这个人在故事里起什么作用（与好坏、与主角关系都无关） */
export const ROLES: RoleMeta[] = [
  { key: 'protagonist', label: '主角', note: '全书视角中心，推动主线的人', color: '#2f6bff', bg: '#eef3ff' },
  { key: 'heroine', label: '女主', note: '情感线核心，与主角关系最深', color: '#d6336c', bg: '#fff0f6' },
  { key: 'deuteragonist', label: '重要配角', note: '戏份仅次于主角的同盟或对手', color: '#4c6ef5', bg: '#edf2ff' },
  { key: 'antagonist', label: '主要反派', note: '与主角正面抗衡的最终对手', color: '#e03131', bg: '#feeceb' },
  { key: 'agent', label: '反派代理人', note: '替反派出手的马前卒、爪牙、走狗', color: '#f76707', bg: '#fff2e8' },
  { key: 'mentor', label: '导师', note: '给主角资源、指点、传承的人', color: '#0ca678', bg: '#e6f7f0' },
  { key: 'ally', label: '助力者', note: '阶段性提供帮助的同伴', color: '#12b886', bg: '#e6fcf5' },
  { key: 'obstacle', label: '阻力者', note: '制造麻烦，但不构成主线威胁', color: '#b8860b', bg: '#fff8e1' },
  { key: 'foil', label: '对照角色', note: '与主角价值观相反，用于映衬', color: '#7b61ff', bg: '#f1edff' },
  { key: 'cameo', label: '背景板', note: '有名有姓，只推动场面', color: '#868e96', bg: '#f2f3f5' },
]

/* 关系类型 18 类：描述「这两个人之间是什么关系」，图谱边标签与配色都用它 */
export const RELATIONS: RelationMeta[] = [
  { key: 'kin', label: '亲属', note: '血缘或家族关系', example: '父子、兄弟、母女、叔侄', color: '#c2255c', bg: '#fff0f6' },
  { key: 'spouse', label: '夫妻', note: '婚姻或伴侣关系', example: '正妻、妾室、道侣、未婚夫妻', color: '#d6336c', bg: '#fff0f6' },
  { key: 'mentor', label: '师徒', note: '传授能力或知识', example: '师父、弟子、传功、引路人', color: '#0b7285', bg: '#e3fafc' },
  { key: 'sect', label: '同门', note: '同一师门或学派', example: '师兄妹、同宗弟子', color: '#1098ad', bg: '#e3fafc' },
  { key: 'lord', label: '君臣', note: '上下级统治关系', example: '主公、臣子、领主、部将', color: '#1864ab', bg: '#e7f5ff' },
  { key: 'superior', label: '上下属', note: '组织内部层级', example: '队长、队员、掌柜、伙计', color: '#1c7ed6', bg: '#e7f5ff' },
  { key: 'sworn', label: '结拜', note: '非血缘兄弟/姐妹', example: '结义兄弟、义兄妹', color: '#5f3dc4', bg: '#f3f0ff' },
  { key: 'ally', label: '盟友', note: '利益合作', example: '联合出兵、共同守城', color: '#2b8a3e', bg: '#ebfbee' },
  { key: 'benefactor', label: '恩人', note: '曾经救过对方', example: '救命之恩、资助之恩', color: '#0ca678', bg: '#e6fcf5', oneWay: true },
  { key: 'enemy', label: '仇敌', note: '有旧怨', example: '杀亲、夺权、灭门', color: '#c92a2a', bg: '#fff5f5' },
  { key: 'rival', label: '竞争', note: '争夺资源或地位', example: '争嫡、争地盘、争机缘', color: '#e8590c', bg: '#fff4e6' },
  { key: 'use', label: '利用', note: '单向利用关系', example: '棋子、工具人、挡箭牌', color: '#a61e4d', bg: '#fff0f6', oneWay: true },
  { key: 'crush', label: '暗恋', note: '单向情感', example: '单恋、旧情未了', color: '#f06595', bg: '#fff0f6', oneWay: true },
  { key: 'oldfriend', label: '旧友', note: '曾经关系好', example: '童年玩伴、旧部、故人', color: '#868e96', bg: '#f8f9fa' },
  { key: 'betray', label: '背叛', note: '关系反转', example: '叛徒、内奸、反水', color: '#8b0000', bg: '#fff5f5' },
  { key: 'secret', label: '秘密合作', note: '表面敌对，暗地合作', example: '暗中交易、卧底联络', color: '#6741d9', bg: '#f3f0ff' },
  { key: 'watch', label: '监视', note: '单向关注', example: '探子、眼线、暗卫', color: '#495057', bg: '#f1f3f5', oneWay: true },
  { key: 'rescue', label: '救命', note: '单向救助', example: '救过命、替死、挡刀', color: '#087f5b', bg: '#e6fcf5', oneWay: true },
]

/* 势力大类 10 类：势力表的分类，也是人物关系图谱的 Combo 分组 */
export const FACTION_CATEGORIES: FactionCategoryMeta[] = [
  { key: 'hero', label: '主角势力', example: '山贼军、主角团、封地、家族', color: '#2f6bff', bg: '#eef3ff' },
  { key: 'court', label: '朝廷势力', example: '皇室、禁军、地方官府、锦衣卫', color: '#c92a2a', bg: '#fff5f5' },
  { key: 'warlord', label: '诸侯势力', example: '各路诸侯、割据军阀、藩镇', color: '#e8590c', bg: '#fff4e6' },
  { key: 'clan', label: '世家势力', example: '门阀、宗族、地方豪强', color: '#b8860b', bg: '#fff8e1' },
  { key: 'sect', label: '宗门势力', example: '门派、宗门、书院、教派', color: '#0b7285', bg: '#e3fafc' },
  { key: 'jianghu', label: '江湖势力', example: '帮派、镖局、杀手组织、商会', color: '#5f3dc4', bg: '#f3f0ff' },
  { key: 'alien', label: '异族势力', example: '北狄、西戎、蛮族、海族', color: '#a61e4d', bg: '#fff0f6' },
  { key: 'outer', label: '外部势力', example: '异界来客、系统相关、幕后组织', color: '#7048e8', bg: '#f3f0ff' },
  { key: 'neutral', label: '中立势力', example: '商团、散修、流民、路人', color: '#868e96', bg: '#f1f3f5' },
  { key: 'hidden', label: '隐藏势力', example: '卧底组织、暗网、幕后黑手', color: '#212529', bg: '#f1f3f5' },
]

/* 势力之间的明暗关系 10 类 */
export const FACTION_RELATIONS = [
  { key: 'ally', label: '结盟', note: '公开约定共同进退', example: '联合出兵、互通有无', color: '#2b8a3e', bg: '#ebfbee', hostile: false },
  { key: 'hostile', label: '敌对', note: '公开冲突、互相攻伐', example: '开战、封锁、掠夺', color: '#c92a2a', bg: '#fff5f5', hostile: true },
  { key: 'vassal', label: '附庸', note: '一方从属另一方', example: '纳贡、称臣、受封', color: '#1864ab', bg: '#e7f5ff', hostile: false },
  { key: 'trade', label: '贸易', note: '以物易物的往来', example: '商路、互市、采买', color: '#0ca678', bg: '#e6fcf5', hostile: false },
  { key: 'truce', label: '停战', note: '暂时不打，但未和解', example: '议和、休战、划界', color: '#868e96', bg: '#f1f3f5', hostile: false },
  { key: 'secret', label: '暗中往来', note: '表面敌对，暗地交易', example: '密信、私通、暗中输送', color: '#6741d9', bg: '#f3f0ff', hostile: false },
  { key: 'infiltrate', label: '渗透', note: '派人打入对方内部', example: '卧底、内应、耳目', color: '#5f3dc4', bg: '#f3f0ff', hostile: false },
  { key: 'marriage', label: '联姻', note: '以婚约结好', example: '和亲、政治婚配', color: '#d6336c', bg: '#fff0f6', hostile: false },
  { key: 'feud', label: '血仇', note: '不死不休的旧怨', example: '灭门、杀亲、世仇', color: '#8b0000', bg: '#fff5f5', hostile: true },
  { key: 'compete', label: '争夺', note: '抢地盘、抢资源', example: '争矿脉、争水道、抢商路', color: '#e8590c', bg: '#fff4e6', hostile: true },
]

export const RELATION_DIRECTIONS = [
  { key: 'both', label: '双向', note: '彼此都有这份关系：君臣/夫妻/师徒/亲属/结拜/同门' },
  { key: 'one', label: '单向', note: '只有一方：暗恋/监视/利用/救命' },
]

const REL_ALIAS: [string, string[]][] = [
  ['同门', ['同门', '师兄弟', '师兄', '师妹', '师姐', '师弟', '同宗', '同派']],
  ['结拜', ['结拜', '结义', '义兄', '义妹', '义弟', '义姐', '把兄弟', '异姓兄弟', '义兄妹']],
  ['师徒', ['师徒', '师父', '弟子', '传功', '引路人', '师尊', '拜师', '收徒']],
  ['亲属', ['亲属', '父子', '母子', '父女', '母女', '兄弟', '姐妹', '兄妹', '叔侄', '血缘', '亲族']],
  ['夫妻', ['夫妻', '道侣', '恋人', '正妻', '妾室', '伴侣', '未婚夫妻', '婚约', '情侣']],
  ['君臣', ['君臣', '主公', '臣子', '领主', '部将', '君主', '效忠']],
  ['上下属', ['上下属', '上级', '下属', '主仆', '队长', '队员', '掌柜', '伙计', '麾下', '部下', '手下', '属下', '同僚', '同事']],
  ['盟友', ['盟友', '同盟', '结盟', '联合', '合作', '伙伴', '战友', '同伴', '队友', '袍泽']],
  ['恩人', ['恩人', '恩情', '资助', '提携', '救命之恩', '知遇']],
  ['仇敌', ['仇敌', '宿敌', '死敌', '仇家', '世仇', '血仇', '旧怨', '不共戴天']],
  ['竞争', ['竞争', '竞争者', '对手', '争嫡', '争地盘', '争夺']],
  ['利用', ['利用', '棋子', '工具人', '挡箭牌', '被利用']],
  ['暗恋', ['暗恋', '单恋', '倾心', '旧情未了', '爱慕']],
  ['旧友', ['旧友', '挚友', '故人', '旧部', '童年玩伴', '青梅竹马', '好友', '旧识', '旧友反目']],
  ['背叛', ['背叛', '叛徒', '内奸', '反水', '叛变', '倒戈', '出卖', '反目']],
  ['秘密合作', ['秘密合作', '暗中', '暗通', '私通', '卧底联络', '秘密往来']],
  ['监视', ['监视', '探子', '眼线', '暗卫', '盯梢', '监视者']],
  ['救命', ['救命', '救过命', '替死', '挡刀', '相救']],
]

const CAT_ALIAS: [string, string[]][] = [
  ['隐藏势力', ['隐藏', '卧底', '暗网', '幕后', '黑手', '密探']],
  ['外部势力', ['外部', '异界', '系统', '域外', '天外']],
  ['异族势力', ['异族', '北狄', '西戎', '蛮族', '海族', '胡人', '蛮夷', '妖族']],
  ['宗门势力', ['宗门', '门派', '书院', '教派', '寺院', '道观', '仙门']],
  ['世家势力', ['世家', '门阀', '宗族', '豪强', '士族', '家族']],
  ['诸侯势力', ['诸侯', '军阀', '藩镇', '割据', '州牧', '太守']],
  ['朝廷势力', ['朝廷', '皇室', '禁军', '官府', '锦衣卫', '官军', '王国', '王朝', '帝国']],
  ['主角势力', ['主角', '山贼', '主角团', '封地', '本部', '根据地']],
  ['江湖势力', ['江湖', '帮派', '镖局', '杀手', '商会', '武林', '绿林', '山寨']],
  ['中立势力', ['中立', '商团', '散修', '流民', '路人', '第三方']],
]

export function relationMeta(v: any): RelationMeta | null {
  const s = norm(v)
  if (!s) return null
  const hit = RELATIONS.find(m => m.label === s || m.key === s)
  if (hit) return hit
  for (const [label, kws] of REL_ALIAS) {
    if (kws.some(k => s.includes(k))) return RELATIONS.find(m => m.label === label) || null
  }
  return null
}

export function factionCategoryMeta(v: any): FactionCategoryMeta | null {
  const s = norm(v)
  if (!s) return null
  const hit = FACTION_CATEGORIES.find(m => m.label === s || m.key === s)
  if (hit) return hit
  for (const [label, kws] of CAT_ALIAS) {
    if (kws.some(k => s.includes(k))) return FACTION_CATEGORIES.find(m => m.label === label) || null
  }
  return null
}

export function factionRelationMeta(v: any): (typeof FACTION_RELATIONS)[number] | null {
  const s = norm(v)
  if (!s) return null
  const hit = FACTION_RELATIONS.find(m => m.label === s || m.key === s)
  if (hit) return hit
  const alias: [string, string[]][] = [
    ['暗中往来', ['暗中', '暗通', '私通', '密信', '秘密']],
    ['渗透', ['渗透', '卧底', '内应', '耳目', '打探']],
    ['附庸', ['附庸', '从属', '纳贡', '称臣', '受封', '藩属']],
    ['联姻', ['联姻', '和亲', '婚约', '婚配']],
    ['血仇', ['血仇', '世仇', '灭门', '杀亲', '不死不休']],
    ['停战', ['停战', '议和', '休战', '划界']],
    ['贸易', ['贸易', '互市', '商路', '买卖', '采买']],
    ['争夺', ['争夺', '抢地盘', '抢资源', '争矿', '争商路']],
    ['结盟', ['结盟', '同盟', '联盟', '联合', '盟约', '共同进退']],
    ['敌对', ['敌对', '开战', '攻伐', '入侵', '封锁', '掠夺', '仇视']],
  ]
  for (const [label, kws] of alias) {
    if (kws.some(k => s.includes(k))) return FACTION_RELATIONS.find(m => m.label === label) || null
  }
  return null
}

/* 九宫格兜底：旧数据 / AI 自由表述，词素推断（与后端 normalize_alignment 同规则） */
const LAW = ['守序', '秩序', '规矩', '规则', '法度', '刻板', '教条', '遵纪']
const CHAOS = ['混乱', '随性', '不羁', '我行我素', '无法无天', '任性', '狂放', '不按常理']
const GOOD = ['善良', '仁慈', '正义', '侠义', '仁义', '护弱', '舍己']
const EVIL = ['邪恶', '残忍', '狠辣', '阴狠', '嗜血', '自私', '毒辣', '不择手段']

const ALIGN_ALIAS: [string, string[]][] = [
  ['守序善良', ['守序善良', '守序善', 'lawful good', 'lg']],
  ['中立善良', ['中立善良', '善良中立', 'neutral good', 'ng']],
  ['混乱善良', ['混乱善良', 'chaotic good', 'cg']],
  ['守序中立', ['守序中立', 'lawful neutral', 'ln']],
  ['绝对中立', ['绝对中立', '完全中立', 'true neutral', 'nn', '随机应变', '见风使舵', '明哲保身']],
  ['混乱中立', ['混乱中立', 'chaotic neutral', 'cn']],
  ['守序邪恶', ['守序邪恶', 'lawful evil', 'le']],
  ['中立邪恶', ['中立邪恶', '邪恶中立', 'neutral evil', 'ne']],
  ['混乱邪恶', ['混乱邪恶', 'chaotic evil', 'ce', '混世魔王', '嗜杀成性']],
]

export function alignmentMeta(v: any): AlignMeta | null {
  const s = norm(v)
  if (!s) return null
  const low = s.toLowerCase()
  const hit = ALIGNMENTS.find(m => m.label === s || m.key === low)
  if (hit) return hit
  for (const [label, kws] of ALIGN_ALIAS) {
    if (kws.some(k => low.includes(k))) return ALIGNMENTS.find(m => m.label === label) || null
  }
  const has = (arr: string[]) => arr.some(w => s.includes(w))
  const row = has(GOOD) ? 0 : has(EVIL) ? 2 : 1
  const col = has(LAW) ? 0 : has(CHAOS) ? 2 : 1
  if (row === 1 && col === 1) return null        /* 完全认不出就显示灰色原文 */
  return ALIGNMENTS.find(m => m.row === row && m.col === col) || null
}

const ROLE_ALIAS: [string, string[]][] = [
  ['反派代理人', ['反派代理', '代理人', '爪牙', '打手', '走狗', '马前卒', '反派将领', '反派部下', '反派手下']],
  ['主要反派', ['主要反派', '最终反派', '大反派', '终极反派', '反派', 'boss', '魔王']],
  ['重要配角', ['重要配角', '配角', '男二', '女二', '副主角', '主要配角']],
  ['主角', ['主角', '男主', '主人公', '主角团']],
  ['女主', ['女主', '女一', '女主角']],
  ['导师', ['导师', '师父', '师尊', '引路人', '长者', '前辈']],
  ['助力者', ['助力', '帮手', '助手', '同伴', '队友', '追随者']],
  ['阻力者', ['阻力', '麻烦制造', '绊脚石', '捣乱']],
  ['对照角色', ['对照', '映衬', '镜像']],
  ['背景板', ['背景板', '龙套', '路人', '过场']],
]

export function roleMeta(v: any): RoleMeta | null {
  const s = norm(v)
  if (!s) return null
  const hit = ROLES.find(m => m.label === s || m.key === s)
  if (hit) return hit
  const low = s.toLowerCase()
  for (const [label, kws] of ROLE_ALIAS) {
    if (kws.some(k => low.includes(k))) return ROLES.find(m => m.label === label) || null
  }
  return null
}

/* 标签内联样式：颜色来自常量，避免在 CSS 里堆几十条近似规则 */
export function tagStyle(m: { color: string; bg: string } | null) {
  return m ? { color: m.color, background: m.bg } : undefined
}

/* 关系强度 / 忠诚度：0~1 转百分比，空值返回空串 */
export function pct(v: any): string {
  const s = norm(v)
  if (!s) return ''
  const x = Number(s)
  if (Number.isNaN(x)) return s
  return `${Math.round(Math.max(0, Math.min(1, x)) * 100)}%`
}

/* 是否公开 / 关系方向：与后端 norm_bool / normalize_relation_direction 同规则。
   认不出的表述原样保留（下拉里以「旧值」项显示），绝不静默清空 —— 静默清空会在保存时丢数据。 */
export function normPublic(v: any): string {
  const s = norm(v).toLowerCase()
  if (!s) return ''
  if (/^(是|公开|true|1|yes|y|公开关系)$/.test(s)) return '是'
  if (/^(否|秘密|false|0|no|n|不公开|暗中)$/.test(s)) return '否'
  return norm(v)
}

export function normDirection(v: any): string {
  const s = norm(v)
  if (!s) return ''
  if (/^(单向|one|单方面|一方)$/i.test(s)) return '单向'
  if (/^(双向|both|相互|互相|彼此)$/i.test(s)) return '双向'
  return s
}
