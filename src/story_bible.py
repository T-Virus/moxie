# -*- coding: utf-8 -*-
"""
故事设定（story_bible）与角色卡的「字段 <-> 单条字符串」转换
==============================================================
磁盘上 story_bible 仍是一条拼接字符串（供后续生成管线直接读取），
但界面录入与 AI 拆解都按字段进行；本模块是唯一格式来源，
供 webapp.py（可视化编辑）与 decompose.py（DeepSeek 拆解）共用。

字段分三类：
  · 全书要素   SB_FIELDS     —— 作品简介/题材/世界观/力量体系/人称/文风/主线/冲突/悬念/伏笔…
  · 角色卡     CARD_FIELDS   —— 每个角色一张卡：姓名/性别/种族/剧情功能/人设倾向/对主角态度/
                                  势力大类+势力名称+下属分支/关系对象+关系类型+方向+强度+公开+章节/
                                  身份背景/性格/说话风格/常用词/动机目标/与主角关系
  · 势力卡     FACTION_FIELDS —— 每个势力一张卡：名称/势力大类/类型/阵营/立场/
                                  关联势力+势力关系+强度+是否公开/与主角关系/简介

规范取值全部在下面几张表里：
  · 人设倾向 ALIGNMENTS（九宫格 9）
  · 剧情功能 ROLE_FUNCS（10）
  · 关系类型 RELATION_KINDS（18，图谱边标签用）
  · 对主角态度 FACTION_STANCES（9，与势力共用）
  · 势力大类 FACTION_CATEGORIES（10，图谱 Combo 分组用）
  · 势力关系 FACTION_REL_TYPES（10，势力之间的明暗关系）
"""

import re

SB_FIELDS = [
    ("synopsis", "作品简介", ["作品简介", "内容简介", "梗概", "简介"]),
    ("genre", "题材与基调", ["题材", "基调"]),
    ("world", "世界观与时代背景", ["世界观", "时代背景", "背景设定"]),
    ("power", "力量体系与金手指", ["力量体系", "金手指", "体系设定"]),
    ("person", "叙事人称", ["人称"]),
    ("style", "文风与语言", ["文风", "语言风格"]),
    ("audience", "目标读者与卖点", ["目标读者", "读者定位", "卖点"]),
    ("mainline", "全书主线", ["主线"]),
    ("conflict", "核心冲突", []),
    ("suspense", "核心悬念", []),
    ("subplots", "支线与情感线", ["支线", "情感线"]),
    ("protagonist", "主角设定", ["主角"]),
    ("supporting", "主要配角", ["配角"]),
    ("antagonist", "主要反派", ["反派"]),
    ("places", "重要地点", ["地点", "主要场景"]),
    ("items", "关键道具", ["道具", "物品"]),
    ("terms", "专有名词表", ["名词表", "专有名词"]),
    ("timeline", "时间线", ["时间线", "编年史", "年表"]),
    ("map", "地图设定", ["地图", "地理", "疆域"]),
    ("foreshadow", "伏笔与回收", ["伏笔"]),
    ("taboos", "写作禁忌与铁律", ["禁忌", "铁律"]),
]

CARD_FIELDS = [
    ("name", "姓名", ["名字"]),
    ("gender", "性别", ["性别"]),
    # 种族/物种：拆解与改编都要产出，前端给常见种族预设，也允许直接写自定义值
    ("race", "种族", ["种族类型", "族属", "物种", "种族身份"]),
    ("role", "剧情功能", ["定位", "角色"]),
    ("alignment", "人设倾向", ["九宫格", "性格阵营", "道德倾向"]),
    ("stance", "对主角态度", ["立场", "态度"]),
    # 势力归属拆两层：大类（10 类规范词）+ 具体势力名（对上势力表）+ 下属分支
    ("factionCategory", "势力大类", ["势力分类", "势力类别"]),
    ("factionName", "势力名称", ["势力归属", "所属势力", "归属", "所属"]),
    ("subFaction", "下属分支", ["分支", "下属"]),
    ("loyalty", "忠诚度", ["忠心", "忠诚"]),
    ("joinChapter", "加入章节", ["入伙章节"]),
    ("leaveChapter", "脱离章节", ["离开章节", "叛出章节"]),
    # 一条主关系 + 其余关系（其余关系一行一条，供图谱连边）
    ("relationTo", "关系对象", ["关系目标", "关系人物"]),
    ("relationType", "关系类型", ["关系性质", "关键关系"]),
    ("relationDirection", "关系方向", ["方向"]),
    ("relationStrength", "关系强度", ["强度"]),
    ("isPublic", "是否公开", ["公开"]),
    ("chapter", "关系确立章节", ["确立章节", "关系章节"]),
    ("relations", "其他关系", ["其余关系", "其他人物关系"]),
    ("identity", "身份背景", ["身份", "背景"]),
    ("personality", "性格", ["性格特点"]),
    ("speech", "说话风格", ["口吻"]),
    ("catchwords", "口头禅与常用词", ["口头禅", "常用语", "惯用语", "名台词", "经典台词", "招牌台词"]),
    ("weakness", "弱点", ["弱点", "软肋", "破绽"]),
    ("goal", "动机目标", ["动机", "目标"]),
]

CARD_LABEL = "人物卡片"

# 角色「人设倾向」：经典九宫格（守序/中立/混乱 × 善良/中立/邪恶）。
# 判的是人物本身的道德与行事方式，**不是**他与主角的关系——关系看 stance / relationType。
ALIGNMENTS = [
    ("lg", "守序善良", "守规矩、有底线，以正当手段护弱济困"),
    ("ng", "中立善良", "本能地帮人，不被规矩绑住，也不刻意越界"),
    ("cg", "混乱善良", "重情义轻规则，为善可以抗命、越界、惹祸"),
    ("ln", "守序中立", "守规则、尽本分，不主动行善也不作恶"),
    ("nn", "绝对中立", "随局势而动，不持立场、不轻易选边"),
    ("cn", "混乱中立", "我行我素，行事全凭当下兴致"),
    ("le", "守序邪恶", "借规则与权威压榨他人，恶得有条理、有野心"),
    ("ne", "中立邪恶", "只为自己，损人利己，谁挡路就除谁"),
    ("ce", "混乱邪恶", "以破坏与折磨为乐，不计后果"),
]
# 九宫格的行列轴（前端画 3×3 选择器用）：row = 善良/中立/邪恶，col = 守序/中立/混乱
ALIGNMENT_AXES = {"rows": ["善良", "中立", "邪恶"], "cols": ["守序", "中立", "混乱"]}

# 角色「剧情功能」：这个人在故事里承担什么作用（不是好坏，也不是关系）
ROLE_FUNCS = [
    ("protagonist", "主角", "全书视角中心，推动主线的人"),
    ("heroine", "女主", "情感线核心，与主角关系最深"),
    ("deuteragonist", "重要配角", "戏份仅次于主角的同盟或对手"),
    ("antagonist", "主要反派", "与主角正面抗衡的最终对手"),
    ("agent", "反派代理人", "替反派出手的马前卒、爪牙、走狗"),
    ("mentor", "导师", "给主角资源、指点、传承的人"),
    ("ally", "助力者", "阶段性提供帮助的同伴"),
    ("obstacle", "阻力者", "制造麻烦，但不构成主线威胁"),
    ("foil", "对照角色", "与主角价值观相反，用于映衬"),
    ("cameo", "背景板", "有名有姓，只推动场面"),
]

# 角色之间的关系类型（18 类）：描述「这两个人之间是什么关系」，图谱边标签用
# (key, 中文, 释义, 典型例子)。释义与例子同时给前端做名词注释、给 AI 做判定依据。
RELATION_KINDS = [
    ("kin", "亲属", "血缘或家族关系", "父子、兄弟、母女、叔侄"),
    ("spouse", "夫妻", "婚姻或伴侣关系", "正妻、妾室、道侣、未婚夫妻"),
    ("mentor", "师徒", "传授能力或知识", "师父、弟子、传功、引路人"),
    ("sect", "同门", "同一师门或学派", "师兄妹、同宗弟子"),
    ("lord", "君臣", "上下级统治关系", "主公、臣子、领主、部将"),
    ("superior", "上下属", "组织内部层级", "队长、队员、掌柜、伙计"),
    ("sworn", "结拜", "非血缘兄弟/姐妹", "结义兄弟、义兄妹"),
    ("ally", "盟友", "利益合作", "联合出兵、共同守城"),
    ("benefactor", "恩人", "曾经救过对方", "救命之恩、资助之恩"),
    ("enemy", "仇敌", "有旧怨", "杀亲、夺权、灭门"),
    ("rival", "竞争", "争夺资源或地位", "争嫡、争地盘、争机缘"),
    ("use", "利用", "单向利用关系", "棋子、工具人、挡箭牌"),
    ("crush", "暗恋", "单向情感", "单恋、旧情未了"),
    ("oldfriend", "旧友", "曾经关系好", "童年玩伴、旧部、故人"),
    ("betray", "背叛", "关系反转", "叛徒、内奸、反水"),
    ("secret", "秘密合作", "表面敌对，暗地合作", "暗中交易、卧底联络"),
    ("watch", "监视", "单向关注", "探子、眼线、暗卫"),
    ("rescue", "救命", "单向救助", "救过命、替死、挡刀"),
]
# 兼容旧调用：只要中文词的列表
RELATION_TYPES = [lb for _, lb, _, _ in RELATION_KINDS]

# 关系方向：双向＝彼此都有这份关系（君臣/夫妻/师徒）；单向＝只有一方（暗恋/监视/利用）
RELATION_DIRECTIONS = [("both", "双向"), ("one", "单向")]

# 其余关系字段的书写格式：一行一条「对象｜类型｜强度」，强度可省
RELATIONS_HINT = "对象｜类型｜强度，一行一条"

# ---------------------------------------------------------------- 情绪流
# 爆款拆的从来不是「情节」，而是「情绪怎么被压、怎么被放」。
# 这两组词表同时供拆解（写）、图谱（画曲线）、正文生成（照着写）、审查（查有没有兑现）使用，
# 保证同一条情绪/钩子在整条链路里叫同一个名字，不被模型随手改写成同义词。
EMOTIONS = [
    ("憋屈", "被压制、被误解、被夺走，读者替他窝火"),
    ("爽", "打脸、翻盘、碾压、扬眉吐气"),
    ("燃", "热血、孤身赴险、誓不低头"),
    ("甜", "暧昧互动、被偏宠、温情相待"),
    ("虐", "误会、错过、牺牲、求而不得"),
    ("悬", "疑点悬置、真相未明、局势不明"),
    ("恐", "威胁逼近、未知恐惧、生理性紧张"),
    ("暖", "日常温情、救赎、被接纳"),
    ("怒", "被羞辱、被欺压之后的愤怒"),
    ("悲", "失去、诀别、宿命不可逆"),
]
EMOTION_LABELS = [lb for lb, _ in EMOTIONS]

# 章末钩子：读者点「下一章」的直接理由，必须是这六种之一，不能写成「引人入胜」这种空话
HOOK_TYPES = [
    ("悬念", "抛出一个未解答的问题或疑点"),
    ("危机", "危险已经贴脸，动作停在临界点"),
    ("反转", "最后一句推翻前面的判断"),
    ("期待", "目标将成、好事将近，读者等着兑现"),
    ("信息差", "读者知道而当事人不知道，或反之"),
    ("情感", "关系发生变化：告白、决裂、相认"),
]
HOOK_TYPE_LABELS = [lb for lb, _ in HOOK_TYPES]
TENSION_HINT = "1~10 的整数：1~3 平缓铺垫，4~6 摩擦升级，7~9 冲突正面爆发，10 生死/命运级"

# 九宫格别名：先精确词，再按「守序/混乱 + 善良/邪恶」词素组合推断
_ALIGN_ALIAS = [
    ("守序善良", ("守序善良", "守序善", "lawful good")),
    ("中立善良", ("中立善良", "善良中立", "neutral good")),
    ("混乱善良", ("混乱善良", "chaotic good")),
    ("守序中立", ("守序中立", "lawful neutral")),
    ("绝对中立", ("绝对中立", "完全中立", "中立中立", "true neutral", "随机应变", "见风使舵", "明哲保身")),
    ("混乱中立", ("混乱中立", "chaotic neutral")),
    ("守序邪恶", ("守序邪恶", "lawful evil")),
    ("中立邪恶", ("中立邪恶", "邪恶中立", "neutral evil")),
    ("混乱邪恶", ("混乱邪恶", "chaotic evil", "混世魔王", "嗜杀成性")),
]
_LAW_WORDS = ("守序", "秩序", "规矩", "规则", "法度", "刻板", "教条", "遵纪")
_CHAOS_WORDS = ("混乱", "随性", "不羁", "我行我素", "无法无天", "任性", "狂放", "不按常理")
_GOOD_WORDS = ("善良", "仁慈", "正义", "侠义", "仁义", "护弱", "舍己")
_EVIL_WORDS = ("邪恶", "残忍", "狠辣", "阴狠", "嗜血", "自私", "毒辣", "不择手段")

# 剧情功能别名：旧数据里的自定义定位（「配角」「反派将领」…）尽量落到 10 类里
# 关系类型别名：旧数据「旧友反目」「宿敌」「主仆」「师兄弟」等落到 18 类
# 顺序很关键：先匹配更具体的词（「师兄弟」→同门 而非 亲属；「结义兄弟」→结拜 而非 亲属）
_RELATION_ALIAS = [
    ("同门", ("同门", "师兄弟", "师兄", "师妹", "师姐", "师弟", "同宗", "同派")),
    ("结拜", ("结拜", "结义", "义兄", "义妹", "义弟", "义姐", "把兄弟", "异姓兄弟", "义兄妹")),
    ("师徒", ("师徒", "师父", "弟子", "传功", "引路人", "师尊", "拜师", "收徒")),
    ("亲属", ("亲属", "父子", "母子", "父女", "母女", "兄弟", "姐妹", "兄妹", "叔侄", "血缘", "亲族")),
    ("夫妻", ("夫妻", "道侣", "恋人", "正妻", "妾室", "伴侣", "未婚夫妻", "婚约", "情侣")),
    ("君臣", ("君臣", "主公", "臣子", "领主", "部将", "君主", "效忠")),
    ("上下属", ("上下属", "上级", "下属", "主仆", "队长", "队员", "掌柜", "伙计", "麾下", "部下", "手下", "属下", "同僚", "同事")),
    ("盟友", ("盟友", "同盟", "结盟", "联合", "合作", "伙伴", "战友", "同伴", "队友", "袍泽")),
    ("恩人", ("恩人", "恩情", "资助", "提携", "救命之恩", "知遇")),
    ("仇敌", ("仇敌", "宿敌", "死敌", "仇家", "世仇", "血仇", "旧怨", "不共戴天")),
    ("竞争", ("竞争", "竞争者", "对手", "争嫡", "争地盘", "争夺")),
    ("利用", ("利用", "棋子", "工具人", "挡箭牌", "被利用")),
    ("暗恋", ("暗恋", "单恋", "倾心", "旧情未了", "爱慕")),
    ("旧友", ("旧友", "挚友", "故人", "旧部", "童年玩伴", "青梅竹马", "好友", "旧识", "旧友反目")),
    ("背叛", ("背叛", "叛徒", "内奸", "反水", "叛变", "倒戈", "出卖", "反目")),
    ("秘密合作", ("秘密合作", "暗中", "暗通", "私通", "卧底联络", "秘密往来")),
    ("监视", ("监视", "探子", "眼线", "暗卫", "盯梢", "监视者")),
    ("救命", ("救命", "救过命", "替死", "挡刀", "相救")),
]

_ROLE_ALIAS = [
    ("反派代理人", ("反派代理", "代理人", "爪牙", "打手", "走狗", "马前卒", "反派将领", "反派部下", "反派手下")),
    ("主要反派", ("主要反派", "最终反派", "大反派", "终极反派", "反派", "BOSS", "boss", "魔王")),
    ("重要配角", ("重要配角", "配角", "男二", "女二", "副主角", "主要配角")),
    ("主角", ("主角", "男主", "主人公", "主角团")),
    ("女主", ("女主", "女一", "女主角")),
    ("导师", ("导师", "师父", "师尊", "引路人", "长者", "前辈")),
    ("助力者", ("助力", "帮手", "助手", "同伴", "队友", "追随者")),
    ("阻力者", ("阻力", "麻烦制造", "绊脚石", "捣乱")),
    ("对照角色", ("对照", "映衬", "镜像")),
    ("背景板", ("背景板", "龙套", "路人", "过场")),
]

# 势力卡：与主角阵营发生关系的世界观实体（宗门 / 家族 / 国家 / 组织…）
FACTION_FIELDS = [
    ("name", "名称", ["名字"]),
    ("category", "势力大类", ["大类", "势力类别", "类型", "种类"]),
    ("stance", "立场", []),
    ("relTo", "关联势力", ["关联的势力"]),
    ("relType", "势力关系", ["势力之间关系"]),
    ("relStrength", "关系强度", ["强度"]),
    ("relPublic", "关系公开", ["是否公开"]),
    ("relations", "其他势力关系", ["其余势力关系"]),
    ("desc", "简介", ["描述", "介绍"]),
]

# 势力大类（10 类）：势力表的分类维度，也用作人物关系图谱的 Combo 分组
FACTION_CATEGORIES = [
    ("hero", "主角势力", "山贼军、主角团、封地、家族"),
    ("court", "朝廷势力", "皇室、禁军、地方官府、锦衣卫"),
    ("warlord", "诸侯势力", "各路诸侯、割据军阀、藩镇"),
    ("clan", "世家势力", "门阀、宗族、地方豪强"),
    ("sect", "宗门势力", "门派、宗门、书院、教派"),
    ("jianghu", "江湖势力", "帮派、镖局、杀手组织、商会"),
    ("alien", "异族势力", "北狄、西戎、蛮族、海族"),
    ("outer", "外部势力", "异界来客、系统相关、幕后组织"),
    ("neutral", "中立势力", "商团、散修、流民、路人"),
    ("hidden", "隐藏势力", "卧底组织、暗网、幕后黑手"),
]

# 势力之间的关系：公开往来之外还有「明面敌对、暗地合作」，所以多一个 是否公开 维度
FACTION_REL_TYPES = [
    ("ally", "结盟", "公开约定共同进退", "联合出兵、互通有无"),
    ("hostile", "敌对", "公开冲突、互相攻伐", "开战、封锁、掠夺"),
    ("vassal", "附庸", "一方从属另一方", "纳贡、称臣、受封"),
    ("trade", "贸易", "以物易物的往来", "商路、互市、采买"),
    ("truce", "停战", "暂时不打，但未和解", "议和、休战、划界"),
    ("secret", "暗中往来", "表面敌对，暗地交易", "密信、私通、暗中输送"),
    ("infiltrate", "渗透", "派人打入对方内部", "卧底、内应、耳目"),
    ("marriage", "联姻", "以婚约结好", "和亲、政治婚配"),
    ("feud", "血仇", "不死不休的旧怨", "灭门、杀亲、世仇"),
    ("compete", "争夺", "抢地盘、抢资源", "争矿脉、争水道、抢商路"),
]

_FACTION_CAT_ALIAS = [
    ("隐藏势力", ("隐藏", "卧底", "暗网", "幕后", "黑手", "密探")),
    ("外部势力", ("外部", "异界", "系统", "域外", "天外", "外星")),
    ("异族势力", ("异族", "北狄", "西戎", "蛮族", "海族", "胡人", "蛮夷", "妖族")),
    ("宗门势力", ("宗门", "门派", "书院", "教派", "寺院", "道观", "仙门")),
    ("世家势力", ("世家", "门阀", "宗族", "豪强", "士族", "家族")),
    ("诸侯势力", ("诸侯", "军阀", "藩镇", "割据", "州牧", "太守")),
    ("朝廷势力", ("朝廷", "皇室", "禁军", "官府", "锦衣卫", "官军", "王国", "王朝", "帝国")),
    ("主角势力", ("主角", "山贼", "主角团", "封地", "本部", "根据地")),
    ("江湖势力", ("江湖", "帮派", "镖局", "杀手", "商会", "武林", "绿林", "山寨")),
    ("中立势力", ("中立", "商团", "散修", "流民", "路人", "第三方")),
]

_FACTION_REL_ALIAS = [
    ("暗中往来", ("暗中往来", "暗通", "私通", "密信", "秘密交易", "暗地")),
    ("渗透", ("渗透", "卧底", "内应", "耳目", "打探")),
    ("附庸", ("附庸", "从属", "纳贡", "称臣", "受封", "藩属")),
    ("联姻", ("联姻", "和亲", "婚约", "婚配")),
    ("血仇", ("血仇", "世仇", "灭门", "杀亲", "不死不休")),
    ("停战", ("停战", "议和", "休战", "划界")),
    ("贸易", ("贸易", "互市", "商路", "买卖", "采买")),
    ("争夺", ("争夺", "抢地盘", "抢资源", "争矿", "争商路")),
    ("结盟", ("结盟", "同盟", "联盟", "联合", "盟约", "共同进退")),
    ("敌对", ("敌对", "开战", "攻伐", "入侵", "封锁", "掠夺", "仇视")),
]

# 「阵营」已并入 FACTION_CATEGORIES（势力大类）+ STANCES（对主角态度）：
# 一个势力「属于什么组织」看 category，「此刻站哪边」看 stance，不再单设 camp，避免两套近义词打架。

# 势力「立场」：此刻对主角的态度（9 类，决定卡片标签色）
FACTION_STANCES = [
    ("own", "己方", "主角阵营核心成员"),
    ("ally", "盟友", "暂时合作、利益一致"),
    ("neutral", "中立", "不站队，无明显敌友"),
    ("watch", "观望", "暂时不动，可能倒向任一方"),
    ("rival", "竞争", "目标冲突，但未必生死相向"),
    ("hostile", "敌对", "明确对立，会制造冲突"),
    ("nemesis", "死敌", "深仇大恨，不可调和"),
    ("betray", "背叛", "曾经友善或中立，后来反水"),
    ("hidden", "潜伏", "表面中立或己方，实际另有目的"),
]

# 旧数据 / AI 自由表述 → 规范值。顺序即匹配优先级：
# 更具体的词排前面（「死敌」先于「敌对」、「潜伏」先于「中立」），避免被宽泛词吃掉。
_STANCE_ALIAS = [
    ("己方", ("己方", "我方", "自己人", "主角方", "主角阵营", "同门", "麾下", "嫡系",
             "属下", "部属", "亲信", "归附", "归降", "效忠主角")),
    ("潜伏", ("潜伏", "卧底", "内应", "暗桩", "伪装", "暗中支持", "暗助", "幕后", "另有目的")),
    ("背叛", ("背叛", "反水", "叛变", "倒戈", "叛出", "反目")),
    ("死敌", ("死敌", "宿敌", "世仇", "血仇", "不共戴天", "势不两立", "复仇灭")),
    ("观望", ("观望", "犹豫", "按兵不动", "随时倒向", "摇摆", "墙头", "骑墙", "逐利",
             "趋利", "自保", "待价", "保存实力")),
    ("竞争", ("竞争", "竞逐", "争夺", "抢生意", "同赛道", "扩张", "自立", "争霸", "挑战", "比武")),
    ("盟友", ("盟友", "同盟", "联盟", "友方", "友军", "友好", "友善", "合作", "利益一致",
             "互通", "互市", "贸易", "交易", "援助", "援军", "唇亡齿寒")),
    ("敌对", ("敌对", "敌方", "对抗", "仇视", "对立", "冲突", "入侵", "吞并", "敌视",
             "围剿", "清剿", "剿灭", "镇压", "讨伐", "讨平", "攻打", "攻击", "掠夺",
             "劫掠", "打压", "施压", "封锁", "威胁", "反抗", "反对")),
    ("中立", ("中立", "不站队", "无明显敌友", "两不相帮", "各自为战", "利益优先",
             "未知", "内斗", "倾轧", "松散", "未出场", "未直接出场")),
]


def _normalize(v, table, alias):
    """把自由表述收敛成规范标签；认不出时原样保留（前端会兜底显示灰色）。"""
    s = str(v or "").strip()
    if not s:
        return ""
    for key, lb, _ in table:                 # 1) 规范值 / 英文 key 精确命中
        if s == key or s == lb:
            return lb
    for lb, kws in alias:                    # 2) 关键词（已按具体度排序）
        if any(k in s for k in kws):
            return lb
    return s


def normalize_stance(v):
    return _normalize(v, FACTION_STANCES, _STANCE_ALIAS)


def normalize_faction(f):
    """就地规范化一张势力卡：大类 / 立场 / 势力关系 / 强度 / 公开，返回同一对象。"""
    if isinstance(f, dict):
        for k, fn in (("category", normalize_faction_category),
                      ("stance", normalize_stance), ("relType", normalize_faction_rel_type),
                      ("relStrength", norm_unit), ("relPublic", norm_bool)):
            if k in f:
                f[k] = fn(f.get(k))
        if "relations" in f:
            f["relations"] = _norm_rel_rows(f.get("relations"), normalize_faction_rel_type)
        # 旧卡没有大类：按已废弃的「类型」字段（宗门/家族/朝廷…）推断，推断后不再保留该字段
        if not str(f.get("category") or "").strip():
            guess = normalize_faction_category(f.get("kind") or f.get("camp"))
            if guess in {lb for _, lb, _ in FACTION_CATEGORIES}:
                f["category"] = guess
    return f


_ALIGN_LABEL = {key: lb for key, lb, _ in ALIGNMENTS}


def normalize_alignment(v):
    """自由表述 → 九宫格之一。
    「守规矩但手段狠辣」这类描述按「守序/混乱 + 善良/邪恶」词素组合推断；
    完全认不出时原样保留，前端显示灰色标签，不猜。"""
    s = str(v or "").strip()
    if not s:
        return ""
    low = s.lower()
    for key, lb, _ in ALIGNMENTS:                    # 1) 规范值 / 英文 key（大小写不敏感）
        if low == key or s == lb:
            return lb
    for lb, kws in _ALIGN_ALIAS:                     # 2) 常见写法
        if any(k.lower() in low for k in kws):
            return lb
    axis = "n"                                       # 3) 词素组合兜底
    if any(w in s for w in _LAW_WORDS):
        axis = "l"
    elif any(w in s for w in _CHAOS_WORDS):
        axis = "c"
    moral = "n"
    if any(w in s for w in _GOOD_WORDS):
        moral = "g"
    elif any(w in s for w in _EVIL_WORDS):
        moral = "e"
    if axis == "n" and moral == "n":
        return s                                     # 认不出，原样保留
    return _ALIGN_LABEL.get(axis + moral, s)


def normalize_role(v):
    """自由表述 → 10 种剧情功能之一（认不出原样保留）。"""
    s = str(v or "").strip()
    if not s:
        return ""
    for key, lb, _ in ROLE_FUNCS:
        if s == key or s == lb:
            return lb
    for lb, kws in _ROLE_ALIAS:
        if any(k in s for k in kws):
            return lb
    return s


def normalize_relation_type(v):
    """自由表述 → 18 类关系之一（「旧友反目」「主仆」「师兄弟」都能落位）。"""
    s = str(v or "").strip()
    if not s:
        return ""
    for key, lb, _, _ in RELATION_KINDS:
        if s == key or s == lb:
            return lb
    for lb, kws in _RELATION_ALIAS:
        if any(k in s for k in kws):
            return lb
    return s


def normalize_relation_direction(v):
    """关系方向 → 双向 / 单向（默认双向）。"""
    s = str(v or "").strip()
    if not s:
        return ""
    if s in ("双向", "both", "相互", "互相", "彼此"):
        return "双向"
    if s in ("单向", "one", "单方面", "一方"):
        return "单向"
    return s


def normalize_faction_category(v):
    """势力自由描述 → 10 类势力大类（「山贼势力」「诸侯割据」「宗门」都能落位）。"""
    s = str(v or "").strip()
    if not s:
        return ""
    for key, lb, _ in FACTION_CATEGORIES:
        if s == key or s == lb:
            return lb
    for lb, kws in _FACTION_CAT_ALIAS:
        if any(k in s for k in kws):
            return lb
    return s


def normalize_faction_rel_type(v):
    """势力之间的明暗关系 → 10 类之一（结盟/敌对/渗透/暗中往来…）。"""
    s = str(v or "").strip()
    if not s:
        return ""
    for key, lb, _, _ in FACTION_REL_TYPES:
        if s == key or s == lb:
            return lb
    for lb, kws in _FACTION_REL_ALIAS:
        if any(k in s for k in kws):
            return lb
    return s


# 中文强弱描述 → 0~1（AI 常把强度写成「强」「中等」，不折算会丢掉整条关系）
# 注意顺序：被包含的词（强/弱/一般）必须排在包含它们的词（极强/极弱/一般偏上）之后
_UNIT_TEXT = (("极强", "1"), ("很强", "0.9"), ("较强", "0.8"), ("强", "0.75"),
              ("一般偏上", "0.6"), ("中等", "0.6"), ("一般", "0.5"),
              ("较弱", "0.35"), ("极弱", "0.15"), ("弱", "0.3"), ("亲密", "0.9"))


def norm_unit(v):
    """0~1 的强度 / 忠诚度：数字夹到区间内，中文强弱折算，认不出原样保留。"""
    s = str(v or "").strip()
    if not s:
        return ""
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        for word, val in _UNIT_TEXT:
            if word in s:
                return val
        return s
    try:
        x = float(m.group(0))
    except ValueError:
        return s
    if x > 1 and x <= 10:          # 「8」这种十分制写法顺带折算
        x = x / 10.0
    elif x > 10 and x <= 100:
        x = x / 100.0
    x = max(0.0, min(1.0, x))
    return f"{x:.2f}".rstrip("0").rstrip(".") or "0"


def norm_bool(v):
    """是 / 否：仅这两个值，认不出留空（由前端显示为未填）。"""
    s = str(v or "").strip().lower()
    if not s:
        return ""
    if s in ("是", "公开", "true", "1", "yes", "y", "公开关系"):
        return "是"
    if s in ("否", "秘密", "false", "0", "no", "n", "不公开", "暗中"):
        return "否"
    return s


def norm_chapter(v):
    """章节号：只保留阿拉伯数字，认不出原样保留。"""
    s = str(v or "").strip()
    if not s:
        return ""
    m = re.search(r"\d+", s)
    return m.group(0) if m else s


# 「其他关系」一行一条：对象｜类型｜强度。
# 分隔符容忍 ｜ | ， , ： :；强度段不限数字（「强」「85%」也能收，交给 norm_unit 折算）。
# 注意：斜杠不参与主分隔——「陆海空/主角｜君臣」这类目标名本身带斜杠，
# 只有整行完全不用 ｜/，/： 时才退回斜杠切分。
_REL_ROW_RE = re.compile(
    r"^\s*([^｜|，,：:]+?)\s*[｜|，,：:]\s*([^｜|，,：:]+?)\s*(?:[｜|，,：:]\s*([^｜|，,：:]*))?\s*$")
_REL_ROW_SLASH_RE = re.compile(
    r"^\s*([^｜|，,：:/]+?)\s*/\s*([^｜|，,：:/]+?)\s*(?:/\s*([^｜|，,：:/]*))?\s*$")


def _match_rel_row(line):
    """先按标准分隔符切；切不出来再试斜杠写法。"""
    return _REL_ROW_RE.match(line) or _REL_ROW_SLASH_RE.match(line)


# 第三段误写公开性时的兜底：「李四｜仇敌｜不公开」应落到 isPublic，而不是被当成强度
_REL_PUBLIC_WORDS = (("不公开", "否"), ("秘密", "否"), ("暗中", "否"), ("公开", "是"))


def _rel_public(v, default):
    """返回 (isPublic, 剩余强度文本)。公开性词只摘除自身，同段的数字强度要保留。"""
    s = str(v or "").strip()
    if not s:
        return default, ""
    for word, val in _REL_PUBLIC_WORDS:
        if word in s:
            return val, s.replace(word, "").strip(" ｜|,，:：")
    return default, s


def _norm_rel_rows(text, fn):
    """把「对象｜类型｜强度」多行文本逐行规范化（类型按传入词表归并），认不出的行丢弃。"""
    rows = []
    for line in re.split(r"[\n;；]+", str(text or "")):
        line = line.strip()
        if not line:
            continue
        m = _match_rel_row(line)
        if not m:
            continue
        target, kind = m.group(1).strip(), fn(m.group(2).strip())
        if not target or not kind:
            continue
        s = norm_unit(_rel_public(m.group(3), "")[1])
        rows.append(f"{target}｜{kind}" + (f"｜{s}" if s else ""))
    return "；".join(rows)


def parse_faction_relations(text, public="是"):
    """势力「其他势力关系」→ [{target, type, strength, isPublic}]，与角色卡共用行格式。"""
    out = []
    for line in re.split(r"[\n;；]+", str(text or "")):
        line = line.strip()
        if not line:
            continue
        m = _match_rel_row(line)
        if not m:
            continue
        target, kind = m.group(1).strip(), normalize_faction_rel_type(m.group(2).strip())
        if not target or not kind:
            continue
        pub, raw = _rel_public(m.group(3), public)
        out.append({"target": target, "type": kind, "strength": norm_unit(raw),
                    "isPublic": pub})
    return out


def all_faction_relations(f):
    """势力的主关系 + 其他关系，统一供图谱 / 势力关系图连边。"""
    out = []
    target = str(f.get("relTo") or "").strip()
    kind = normalize_faction_rel_type(f.get("relType"))
    if target and kind:
        out.append({"target": target, "type": kind, "strength": norm_unit(f.get("relStrength")),
                    "isPublic": norm_bool(f.get("relPublic")) or "是"})
    out.extend(parse_faction_relations(f.get("relations"), norm_bool(f.get("relPublic")) or "是"))
    return out


def parse_relations(text, default_direction="双向", public="是"):
    """把「其他关系」拆成 [{target, type, strength, direction, isPublic}]，供图谱连边。
    认不出的行直接跳过（不猜），空行忽略。"""
    out = []
    # 换行与「；」都算一条关系的分隔：compose 时多行会被压成单行，两种写法都要认
    for line in re.split(r"[\n;；]+", str(text or "")):
        line = line.strip()
        if not line:
            continue
        m = _match_rel_row(line)
        if not m:
            continue
        target, kind = m.group(1).strip(), normalize_relation_type(m.group(2).strip())
        if not target or not kind:
            continue
        pub, raw = _rel_public(m.group(3), public)
        strength = norm_unit(raw)
        out.append({"target": target, "type": kind, "strength": strength,
                    "direction": default_direction, "isPublic": pub})
    return out


def all_relations(card, public="是"):
    """主关系 + 其他关系，统一成 [{target, type, strength, direction, isPublic}]。"""
    out = []
    target = str(card.get("relationTo") or "").strip()
    kind = normalize_relation_type(card.get("relationType"))
    if target and kind:
        out.append({"target": target, "type": kind,
                    "strength": norm_unit(card.get("relationStrength")),
                    "direction": normalize_relation_direction(card.get("relationDirection")) or "双向",
                    "isPublic": norm_bool(card.get("isPublic")) or public})
    out.extend(parse_relations(card.get("relations"),
                               normalize_relation_direction(card.get("relationDirection")) or "双向",
                               norm_bool(card.get("isPublic")) or public))
    return out


def normalize_card(c):
    """就地规范化一张角色卡：剧情功能 / 人设倾向 / 对主角态度 / 势力大类 / 关系类型与属性。"""
    if isinstance(c, dict):
        for k, fn in (("role", normalize_role), ("alignment", normalize_alignment),
                      ("stance", normalize_stance), ("factionCategory", normalize_faction_category),
                      ("relationType", normalize_relation_type),
                      ("relationDirection", normalize_relation_direction),
                      ("relationStrength", norm_unit), ("loyalty", norm_unit),
                      ("isPublic", norm_bool),
                      ("chapter", norm_chapter), ("joinChapter", norm_chapter),
                      ("leaveChapter", norm_chapter)):
            if k in c:
                c[k] = fn(c.get(k))
        if "relations" in c:
            c["relations"] = _norm_rel_rows(c.get("relations"), normalize_relation_type)
        # 旧字段 catchphrase（整句台词）与 catchwords（常用词）同义，合并去重后只留 catchwords，
        # 直接丢弃会让 243 张卡丢掉台词原文
        cp = str(c.get("catchphrase") or "").strip()
        if cp:
            cw = str(c.get("catchwords") or "").strip()
            c["catchwords"] = cp if not cw else (cw if cp in cw else f"{cw}；{cp}")
        # 旧格式只有「势力归属」一栏：先迁到势力名称，再按名称推断大类
        if not str(c.get("factionName") or "").strip() and str(c.get("faction") or "").strip():
            c["factionName"] = str(c.get("faction")).strip()
        if not str(c.get("factionCategory") or "").strip():
            guess = normalize_faction_category(c.get("factionName") or c.get("faction"))
            if guess in {lb for _, lb, _ in FACTION_CATEGORIES}:
                c["factionCategory"] = guess
    return c


FACTION_LABEL = "势力卡片"

# 表单分组：前端按组渲染，字段增减只改这里（组内顺序即展示顺序）
CARD_GROUPS = [
    ["人设分析", ["role", "alignment", "stance", "gender", "race"]],
    ["势力归属", ["factionCategory", "factionName", "subFaction", "loyalty", "joinChapter", "leaveChapter"]],
    ["关键关系", ["relationTo", "relationType", "relationDirection", "relationStrength",
                  "isPublic", "chapter", "relations"]],
    ["基础资料", ["identity", "personality", "speech", "catchwords", "weakness", "goal"]],
]
FACTION_GROUPS = [
    ["基本", ["category", "stance"]],
    ["势力关系", ["relTo", "relType", "relStrength", "relPublic", "relations"]],
    ["其他", ["desc"]],
]

# (标签, key) 按标签长度倒序，避免「角色」抢先匹配「身份背景」里的子串
_SB_ALIAS = sorted(((lb, k) for k, lb, al in SB_FIELDS for lb in [lb] + al), key=lambda x: -len(x[0]))
_CARD_ALIAS = sorted(((lb, k) for k, lb, al in CARD_FIELDS for lb in [lb] + al), key=lambda x: -len(x[0]))
_FACTION_ALIAS = sorted(((lb, k) for k, lb, al in FACTION_FIELDS for lb in [lb] + al), key=lambda x: -len(x[0]))

SB_LABEL = {k: lb for k, lb, _ in SB_FIELDS}
CARD_LINE_RE = re.compile(r"^\s*[-·•*]\s*")


def schema():
    """给前端用的字段定义（顺序即展示与拼接顺序）。
    card_alignments / card_roles / card_relation_kinds / faction_categories /
    faction_stances / faction_rel_types
    同时用于下拉选项与列表旁的「名词注释」——标签类字段一律从这几张表取值，前端不提供自由输入。"""
    return {"sb_fields": [[k, lb] for k, lb, _ in SB_FIELDS],
            "card_fields": [[k, lb] for k, lb, _ in CARD_FIELDS],
            "card_label": CARD_LABEL,
            "card_groups": CARD_GROUPS,
            "card_alignments": [[k, lb, note] for k, lb, note in ALIGNMENTS],
            "card_roles": [[k, lb, note] for k, lb, note in ROLE_FUNCS],
            "card_relation_kinds": [[k, lb, note, eg] for k, lb, note, eg in RELATION_KINDS],
            # 兼容旧前端：只要中文词的列表
            "relation_types": list(RELATION_TYPES),
            "relation_directions": [[k, lb] for k, lb in RELATION_DIRECTIONS],
            "relations_hint": RELATIONS_HINT,
            "alignment_axes": ALIGNMENT_AXES,
            "faction_fields": [[k, lb] for k, lb, _ in FACTION_FIELDS],
            "faction_label": FACTION_LABEL,
            "faction_groups": FACTION_GROUPS,
            "faction_categories": [[k, lb, note] for k, lb, note in FACTION_CATEGORIES],
            "faction_stances": [[k, lb, note] for k, lb, note in FACTION_STANCES],
            "faction_rel_types": [[k, lb, note, eg] for k, lb, note, eg in FACTION_REL_TYPES],
            "faction_relations_hint": RELATIONS_HINT}


def _cut(part, aliases):
    """从 '性格：xxx' / '性格 xxx' 里切出 (key, 'xxx')。"""
    for lb, k in aliases:
        if part.startswith(lb):
            return k, part[len(lb):].lstrip("：: 　\t").strip()
    return None, None


def _parse_entity_line(line, fields, aliases, legacy_role=None):
    """把一行「- 姓名：沈砚；性别：男…」切成 {key: 值}。
    legacy_role：旧格式「沈砚：主角」时冒号右侧落到哪个 key（角色卡用 role，势力卡不启用）。"""
    line = CARD_LINE_RE.sub("", line).strip()
    # 只含标点/空白的行（如「人物卡片：」后残留的冒号）直接忽略
    if not re.search(r"[0-9A-Za-z\u4e00-\u9fff]", line):
        return None
    ent = {k: "" for k, _, _ in fields}
    parts = [p.strip() for p in re.split(r"[；;]", line) if p.strip()]
    if not parts:
        return None
    head, rest = parts[0], parts[1:]
    m = re.match(r"^(.+?)\s*[：:]\s*(.+)$", head)
    k, _ = _cut(head, aliases)
    if k:                      # 「姓名：沈砚」
        ent[k] = (m.group(2).strip() if m else "")
    elif m and legacy_role:    # 旧格式「沈砚：主角」= 姓名 + 定位
        ent["name"], ent[legacy_role] = m.group(1).strip(), m.group(2).strip()
    else:
        ent["name"] = (m.group(1).strip() if m else head)
    last = k or "name"
    for p in rest:
        k2, v2 = _cut(p, aliases)
        # 只有「标签 + 值」才算新字段：值里恰好出现别名词（「口头禅：下来吧；破绽」）
        # 时不能当字段标签，否则后半句会被吞掉（真实数据里踩到过）。
        if k2 and v2:
            ent[k2] = v2
            last = k2
        else:
            # 没有标签的段续接回上一个字段：compose 会把字段值里的换行压成「；」，
            # 这里按同一分隔符还原，否则「口头禅：A；B」会被截成 A。
            ent[last] = (ent[last] + "；" + p).strip("；")
    return ent


def _parse_card_line(line):
    return _parse_entity_line(line, CARD_FIELDS, _CARD_ALIAS, legacy_role="role")


def _parse_faction_line(line):
    return _parse_entity_line(line, FACTION_FIELDS, _FACTION_ALIAS)


def parse(text):
    """单条字符串 → ({字段: 值}, [角色卡, …], [势力卡, …])

    兼容三种历史形态：拼接字符串（当前格式）、结构化 dict（旧版 decomposed.json）、
    空值。旧数据直接取出同名要素字段，避免调用方拿到 dict 后在本函数里崩掉。
    """
    if isinstance(text, dict):
        fields = {k: str(text.get(k) or "").strip() for k, _, _ in SB_FIELDS}
        return fields, [], []
    if not isinstance(text, str):
        text = str(text or "")
    fields = {k: "" for k, _, _ in SB_FIELDS}
    cards, factions, cur = [], [], None
    for block in re.split(r"\n\s*\n", (text or "").strip()):
        b = block.strip()
        if not b:
            continue
        if b.startswith(CARD_LABEL):                 # 「人物卡片：」标题块
            cur = "cards"
            rest = b[len(CARD_LABEL):].lstrip("：: \t　")
            for line in rest.splitlines():
                c = _parse_card_line(line)
                if c:
                    cards.append(c)
            continue
        if b.startswith(FACTION_LABEL):              # 「势力卡片：」标题块
            cur = "factions"
            rest = b[len(FACTION_LABEL):].lstrip("：: \t　")
            for line in rest.splitlines():
                f = _parse_faction_line(line)
                if f:
                    factions.append(f)
            continue
        if CARD_LINE_RE.match(b):                    # 直接以 "- " 开头的卡片行
            c = _parse_card_line(b)
            if c:
                cards.append(c)
                cur = "cards"
            continue
        k, v = _cut(b, _SB_ALIAS)
        if k:
            cur = k
            fields[k] = v
        elif cur == "cards":
            c = _parse_card_line(b)
            if c:
                cards.append(c)
        elif cur == "factions":
            f = _parse_faction_line(b)
            if f:
                factions.append(f)
        elif cur:                                    # 续行，接到上一个字段
            fields[cur] = (fields[cur] + "\n" + b).strip()
    return fields, cards, factions


def compose(fields, cards, factions=None):
    """({字段: 值}, [角色卡, …], [势力卡, …]) → 单条字符串（生成管线消费的格式）"""
    parts = []
    for k, lb, _ in SB_FIELDS:
        v = str((fields or {}).get(k, "") or "").strip()
        if v:
            parts.append(f"{lb}：{v}")

    def _entity_lines(items, fields_def):
        lines = []
        for c in (items or []):
            seg = []
            for k, lb, _ in fields_def:
                # 卡片必须一行一条：字段值里的换行（「其他关系」多行）压成「；」
                v = re.sub(r"\s*\n\s*", "；", str((c or {}).get(k, '') or "")).strip()
                if v:
                    seg.append(f"{lb}：{v}")
            if seg:
                lines.append("- " + "；".join(seg))
        return lines

    lines = _entity_lines(cards, CARD_FIELDS)
    if lines:
        parts.append(f"{CARD_LABEL}：\n" + "\n".join(lines))
    flines = _entity_lines(factions, FACTION_FIELDS)
    if flines:
        parts.append(f"{FACTION_LABEL}：\n" + "\n".join(flines))
    return "\n\n".join(parts)


# 章节没写 roles 时，至少带上这些定位的角色卡
FALLBACK_ROLES = ("主角", "女主", "男一", "男二", "反派")


def _bare(name):
    """去掉括号补充：「张小凡（鬼厉）」→「张小凡」。"""
    return re.sub(r"[（(][^）)]*[）)]", "", str(name or "")).strip()


def name_matches(a, b):
    """角色名是否指同一人：去掉括号后相等，或一方包含另一方。"""
    x, y = _bare(a), _bare(b)
    if not x or not y:
        return False
    return x == y or x in y or y in x


def filter_by_roles(text, roles, factions=None, fallback=True):
    """按本章出场角色 / 入场势力裁剪 story_bible：要素全保留，
    角色卡只留命中 roles 的，势力卡只留命中 factions 的。
    这是控制提示词体积的关键——卡片会随书越长越多，全量注入必然撑爆上下文。"""
    fields, cards, all_facs = parse(text)
    if not cards:
        return text
    roles = [str(r).strip() for r in (roles or []) if str(r).strip()]
    if roles:
        keep = [c for c in cards if any(name_matches(r, c.get("name")) for r in roles)]
    else:
        keep = []
    if not keep and fallback:                      # 章节没写 roles → 至少带上主要角色
        keep = [c for c in cards
                if any(f in str(c.get("role", "")) for f in FALLBACK_ROLES)]
    fac_names = [str(x).strip() for x in (factions or []) if str(x).strip()]
    if fac_names:                                  # 有入场势力 → 只留命中的势力卡
        keep_facs = [f for f in all_facs if any(name_matches(n, f.get("name")) for n in fac_names)]
    else:                                          # 未列入场势力 → 势力是世界级背景，全留
        keep_facs = all_facs
    return compose(fields, keep, keep_facs)
