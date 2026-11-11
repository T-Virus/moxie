# -*- coding: utf-8 -*-
"""
在线拆解（DeepSeek 1M 上下文）
=========================================
把长文交给 DeepSeek，产出两样东西：

  decomposed.json   全书梗概 / 分章摘要 / 人物卡片（通用结构）
  chapters.json     结构化数据（故事设定 + 逐章任务），供页面编辑与后续生成使用

支持两种模式（--mode）：

  1) reference  参考生成：源 = 全本小说正文 txt
                通读全文，从原始正文里提炼结构，后续由本地 14B 参考重写。
  2) outline    已有大纲：源 = 已经写好的大纲 / 分章概括（Markdown）
                忠实整理成规定结构，不新增不篡改情节。

两种模式输出完全相同的 schema，下游（页面编辑、后续生成）可无差别消费。

用法：
  setx DEEPSEEK_API_KEY "sk-你的真实key"     # 一次性写入环境变量，需重开终端

  # 模式一：参考生成（全本 txt）
  python decompose.py --mode reference --source source_novel.txt

  # 模式二：已有大纲 md（不传 --source 时自动取工作区里唯一的 .md）
  python decompose.py --mode outline --source "《黑夜前的黎明》目录·分章概括·大纲（魂穿设定版）.md"

  python decompose.py --mode outline --limit 5     # 只拆前 5 章，方便先试跑
  python decompose.py --mode reference --dry-run   # 只打印将要发送的 prompt，不调 API

  # reference（全本）模式拆完默认接着改编成新书（等价于再跑一次 adapt.py）：
  python decompose.py --mode reference --source source_novel.txt \
         --out-decomposed data/某书·源/decomposed.json \
         --out-chapters data/某书·源/chapters.json --out-book 新书名 --style "改为科幻题材"

  # 只要拆解、不要改编时加 --no-adapt；outline 模式默认不改编（要改编加 --adapt）。

注意：本脚本不保存任何 API Key，只从环境变量或 --api-key 读取。
"""

import argparse
import difflib
import glob
import json
import os
import re
import subprocess
import sys
from collections import Counter

from deepseek_common import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    JsonParseError,
    OutputTruncated,
    chat_json,
    key_or_empty,
    resolve_base_url,
)
from story_bible import (ALIGNMENTS, CARD_FIELDS, EMOTIONS, EMOTION_LABELS,
                         FACTION_CATEGORIES, FACTION_FIELDS,
                         FACTION_REL_TYPES, FACTION_STANCES, HOOK_TYPES,
                         HOOK_TYPE_LABELS, RELATION_KINDS,
                         ROLE_FUNCS, SB_FIELDS, SB_LABEL,
                         TENSION_HINT, compose as compose_story_bible,
                         normalize_card, normalize_faction)
from entities import (ITEM_FIELDS, ITEM_KINDS, clean_name, clean_names,
                      normalize_item, sync_document)
from paths import DATA_DIR, FROZEN, INPUT_DIR, SRC_DIR, resolve

# 单次请求的源文本上限（0 = 不限制）。超过 --chunk-chars 会自动分段分析再合并。
DEFAULT_MAX_CHARS = 0
# 分段阈值：源文本超过这个字数就分多段分析。
# 注意它约束的是模型的**输出**：一段要吐出「每章概要 + 人物卡 + 势力卡」，
# 中文小说万字大章时，两三章就能把 8k tokens 的输出顶满（表现为 JSON 写到一半被截断）。
# 取值策略：默认先按较大段跑（调用次数少、快）；真被截断时下面的 OutputTruncated
# 会把该段二分重试，用「少数慢段」换「大多数快段」，而不是一上来就切成很多小段。
DEFAULT_CHUNK_CHARS = 120_000
# 每段章数区间：同样是为了压住单次输出规模；下限避免碎段（上下文不足也会跑偏）
DEFAULT_CHUNK_CH_MIN = 10
DEFAULT_CHUNK_CHAPTERS = 16
DEFAULT_CHUNK_CHAPTER_RANGE = f"{DEFAULT_CHUNK_CH_MIN}-{DEFAULT_CHUNK_CHAPTERS}"
REFERENCE_DEFAULT_SOURCE = "source_novel.txt"

# 章回标题（用于优先按章切分）。允许行首有空白/markdown 符号（如 **第一章、…**、- 第二章）
CHAP_RE = re.compile(r"^[ \t　>*#\-•]*(第\s*[0-9一二三四五六七八九十百千零两]+\s*[章回节])", re.MULTILINE)

SYSTEM_PROMPT = "你是一个小说结构分析专家。只输出 JSON，不要任何额外解释、不要 Markdown 代码块。"


def _schema_json():
    """输出结构直接从 story_bible / entities 模块的字段表生成，避免两处字段不一致。"""
    sb = ",\n".join(f'    "{k}": "{lb}"' for k, lb, _ in SB_FIELDS)
    card = ", ".join(f'"{k}": "{lb}"' for k, lb, _ in CARD_FIELDS)
    fac = ", ".join(f'"{k}": "{lb}"' for k, lb, _ in FACTION_FIELDS)
    item = ", ".join(f'"{k}": "{lb}"' for k, lb, _ in ITEM_FIELDS)
    return f"""{{
  "book_summary": "全书梗概，300~500 字",
  "opening": {{
    "strategy": "开篇切入点策略，只能取：受辱反击 / 高能开场 / 反差日常 / 悬念倒叙",
    "first_image": "第一章开篇第一个画面：一句话写清读者第一眼看到谁、在什么处境、正在做什么",
    "golden_finger_demo": "金手指第一次被实际使用（演示出效果，不是口头介绍或觉醒）的章号，如 3"
  }},
  "story_bible": {{
{sb}
  }},
  "characters": [
    {{{card}}}
  ],
  "factions": [
    {{{fac}}}
  ],
  "items": [
    {{{item}}}
  ],
  "chapters": [
    {{
      "chapter": 1,
      "title": "本章标题",
      "summary": "本章摘要，200~260 字，写清关键事件与人物状态变化",
      "key_events": ["事件1", "事件2", "事件3"],
      "roles": ["本章出场的主要角色姓名"],
      "factions": ["本章涉及的势力名称"],
      "items": ["本章出现 / 使用的道具或功法名称"],
      "scene": "本章主要发生地点",
      "conflict": "本章核心冲突点：主角与谁/什么对抗，矛盾因何激化",
      "hook": "章末情绪钩子 / 悬念，一句话勾住读者追读",
      "hook_type": "章末钩子的类型，只能取：悬念 / 危机 / 反转 / 期待 / 信息差 / 情感",
      "emotion": "本章情绪主线，从 憋屈/爽/燃/甜/虐/悬/恐/暖/怒/悲 里取 2~3 个词，用 → 连起来，如 憋屈→怒→爽",
      "tension": 8,
      "payoff": "本章兑现的爽点 / 情绪释放（打脸、翻盘、获得、相认），一句话，没有就空字符串",
      "setup": "本章为后文埋下的铺垫 / 伏笔（哪件东西、哪句话、哪个人），一句话，没有就空字符串"
    }}
  ]
}}"""


def _sb_schema_json():
    """只含 story_bible 的结构（合并多段结果时使用）。"""
    sb = ",\n".join(f'    "{k}": "{lb}"' for k, lb, _ in SB_FIELDS)
    return "{\n" + sb + "\n  }"


# 两种模式共用的输出结构
SCHEMA_JSON = _schema_json()


def _faction_guide():
    """势力卡的取值规范：大类 / 立场 / 势力之间关系 都要从固定词表里选。"""
    cats = "\n".join(f"     · {lb}：{eg}" for _, lb, eg in FACTION_CATEGORIES)
    stances = "\n".join(f"     · {lb}：{note}" for _, lb, note in FACTION_STANCES)
    rels = "\n".join(f"     · {lb}（{note}）：{eg}" for _, lb, note, eg in FACTION_REL_TYPES)
    stance_list = "、".join(lb for _, lb, _ in FACTION_STANCES)
    return f"""势力卡填写规范（factions 数组）：
1. category（势力大类）只能从这 {len(FACTION_CATEGORIES)} 类里选一个，说明「它属于哪一类组织」：
{cats}
2. stance（立场）只能从这 {len(FACTION_STANCES)} 个词里选一个：{stance_list}。说明「此刻对主角的态度」。
3. category / stance 必须严格照抄上面的词，不要自创「亦敌亦友」「暗中支持」「暂时友好」这类说法；
   细微差别写进 desc（例：category=「隐藏势力」、stance=「潜伏」，desc 说明它明面是盟友、实为反派内应）。
4. 势力之间的关系（明暗两层）——relTo / relType / relStrength / relPublic：
   relType 只能从这 {len(FACTION_REL_TYPES)} 类里选一个：
{rels}
   relTo 填另一个势力的名称（必须是 factions 数组里已有的名字）；relStrength 填 0~1 的小数（0.9 表示生死同盟或血仇）；
   relPublic 填「是」或「否」——表面敌对、暗地交易的填 relType＝「暗中往来」或「渗透」且 relPublic＝「否」。
   没有明确的势力对就四个字段都填空字符串。
5. relations（其他势力关系）：除了上面那条主关系，还明确知道的势力对写在这里，一行一条
   「对象｜类型｜强度」，类型同样只能取上面 {len(FACTION_REL_TYPES)} 类之一，强度可省。没有就留空。
6. desc 60~120 字：它是什么、盘踞何处、代表人物、与主角合作或冲突的具体由头。
7. 一个势力只输出一张卡；同名势力不要重复。全书势力 3~12 个为宜，主角阵营至少要有一个「己方」。"""


FACTION_GUIDE = _faction_guide()


def _item_guide():
    """道具 / 功法卡规范：类别固定词表，归属只引用已有角色与势力。"""
    kinds = "\n".join(f"     · {lb}：{note}" for _, lb, note in ITEM_KINDS)
    kind_list = "、".join(lb for _, lb, _ in ITEM_KINDS)
    return f"""道具功法规范（items 数组，与角色卡 / 势力卡同级）：
1. 只提取对剧情有实际作用的物件：推动情节的道具、线索、信物，以及会反复使用的武学功法、战技、兵器、丹药、法宝。
   一次性的背景摆设不要收；全书 3~20 条为宜。
2. kind（类别）只能从这 {len(ITEM_KINDS)} 类里选一个：
{kinds}
3. grade（品阶）只有原文明确写了等级才填（如「地阶上品」「三品丹药」），没有就留空字符串，不要自己编等级。
4. owner（持有者 / 习得者）与 faction（所属势力）只能填 characters / factions 里已有的名字；无归属就留空。
5. chapter（首次出现）填第一次出现或第一次被使用的章号（数字）。
6. effect 一句话写清它能做什么 / 练成后有什么效果；origin 写来历（谁所创、从何处得来）；
   desc 40~80 字，补充外形、限制、代价；没有原文依据的不要编造。
7. 同名只输出一张卡；name 要具体可辨识（如「玄铁令」「九转养魂诀」），
   不要用「神秘物品」「强大功法」「祖传宝物」这类空泛词，也不要把角色名当道具名。
8. chapters[].items 只能填 items 里出现过的名称；本章没有就填空数组。"""


ITEM_GUIDE = _item_guide()


def _card_guide():
    """角色卡的人设分析规范：剧情功能 / 九宫格 / 对主角态度 / 势力两层 / 关系类型与属性。"""
    aligns = "\n".join(f"     · {lb}：{note}" for _, lb, note in ALIGNMENTS)
    roles = "\n".join(f"     · {lb}：{note}" for _, lb, note in ROLE_FUNCS)
    cats = "\n".join(f"     · {lb}：{eg}" for _, lb, eg in FACTION_CATEGORIES)
    rels = "\n".join(f"     · {lb}（{note}）：{eg}" for _, lb, note, eg in RELATION_KINDS)
    stance_list = "、".join(lb for _, lb, _ in FACTION_STANCES)
    align_list = "、".join(lb for _, lb, _ in ALIGNMENTS)
    role_list = "、".join(lb for _, lb, _ in ROLE_FUNCS)
    cat_list = "、".join(lb for _, lb, _ in FACTION_CATEGORIES)
    rel_list = "、".join(lb for _, lb, _, _ in RELATION_KINDS)
    return f"""角色卡的人设分析规范（characters 数组）：
1. role（剧情功能）只能从这 {len(ROLE_FUNCS)} 个词里选一个，说明「这个人在故事里起什么作用」，不是好坏、也不是关系：
{roles}
2. alignment（人设倾向）只能从九宫格这 {len(ALIGNMENTS)} 个词里选一个，判断的是**人物本身的道德与行事方式**：
{aligns}
   判断方法：先看他受不受规则约束（守序 / 中立 / 混乱），再看他利他还是损人（善良 / 中立 / 邪恶）。
   例：为救人可以抗命的侠客＝混乱善良；照章办事、不放水的酷吏＝守序中立；披着清官皮贪墨弄权的权臣＝守序邪恶。
3. stance（对主角态度）只能从这 {len(FACTION_STANCES)} 个词里选一个：{stance_list}。
   这是「这个人此刻对主角的态度」，与 alignment 无关：主角的师父可以是「己方」，朝廷忠臣对主角「敌对」也很正常；
   明面交好、暗中捅刀的选「潜伏」，曾经亲近后翻脸的选「背叛」，不要一律填「敌对」。
4. 势力归属拆成两层，只填已有的势力，不要自造势力名：
   factionCategory 只能从这 {len(FACTION_CATEGORIES)} 类里选一个：
{cats}
   factionName 填 factions 数组里的势力名称（如山贼军、青州军、锦衣卫）；subFaction 填他在这势力里的下属分支（如先锋营、暗卫队、东厂），没有就空着。
   无依无靠的散人：factionCategory 与 factionName 都填空字符串，subFaction 也空着。
5. 势力内的位置（可选，填数字信息）：
   loyalty 忠诚度 0~1 的小数（0.9 忠心不二，0.3 随时想跳船）；joinChapter 加入章节号；leaveChapter 脱离章节号（仍在势力里就填空字符串）。
   这几个字段是给「势力图 / 时间线」用的，宁缺毋滥：没有明确章节就空着，不要编。
6. 关系写这个角色与**另一个角色**之间的关系（主关系一条 + 其他关系至多 3 条）：
   · relationTo＝对方姓名，必须是 characters 里的姓名；没有明确对象就整组留空。
   · relationType 只能从这 {len(RELATION_KINDS)} 类里选一个：
{rels}
   · relationDirection 填「双向」或「单向」：君臣 / 夫妻 / 师徒 / 亲属 / 结拜 / 同门 / 盟友 一般是双向；
     暗恋 / 监视 / 利用 / 救命 是单向（只有一方付出或主导）。
   · relationStrength 填 0~1 的小数，表示这条关系有多重（0.95 生死之交，0.2 点头之交）。
   · isPublic 填「是」或「否」：表面一套背后一套的填「否」。
   · chapter 填这条关系确立的章节号（如 120），不确定就空着。
   · relations 写其余关系，一行一条，格式「对象｜类型｜强度」，例：袁绍｜旧友｜0.6。
7. 关系类型描述「两人之间是什么关系」，不是立场：不要用 alignment 替代 relationType，也不要把「敌对」当关系类型
   （敌对属于 stance）。同一个人可以「守序善良」却「敌对」主角——立场冲突源于立场不同，不是因为他坏。
8. personality 写具体的性格细节（多疑、护短、贪财但有底线），不要只把 alignment 的四个字重复一遍；
   relation 写与主角的具体关系（「主角的授业恩师，视若亲子」），一句话说清，别只写「师父」。
9. 一个人物只输出一张卡；同名不要重复。主角必须有卡且 role＝「主角」、stance＝「己方」。"""


CARD_GUIDE = _card_guide()

def _emotion_guide():
    """情绪流与钩子的填写规范：词表固定，避免模型把「情绪」写成「节奏紧凑」这类空话。"""
    emos = "\n".join(f"     · {lb}：{desc}" for lb, desc in EMOTIONS)
    hooks = "\n".join(f"     · {lb}：{desc}" for lb, desc in HOOK_TYPES)
    return f"""情绪流与钩子（chapters 每章必填）：
A. 爆款被抄的从来不是「情节」，而是「情绪怎么被压、怎么被放」。所以每章除了剧情，还要把情绪标出来：
   · emotion（情绪主线）只能从下面 {len(EMOTIONS)} 个词里取 2~3 个，用 → 连起来，顺序＝本章情绪的走向：
{emos}
     例：憋屈→怒→爽（先被压、再憋火、最后打脸）；悬→恐→悬（一路吊着不给答案）也合法。
     不许写「紧张刺激」「节奏紧凑」「引人入胜」这种非情绪词，也不许自造词。
   · tension（情绪峰值）{TENSION_HINT}。填的是这一章的峰值而不是平均值：铺垫章 2~4，摩擦章 4~6，爆发章 7~9。
   · payoff（本章兑现的爽点）一句话说清「谁得到了什么 / 谁被打了脸 / 什么真相被揭开」；
     纯过渡章可以留空字符串，不要拿「推进剧情」「加深矛盾」凑数。
   · setup（本章埋的铺垫）一句话说清埋了什么（哪件东西、哪句话、哪个人），便于后文回收；没有就空字符串。
B. hook_type（章末钩子类型）只填类型，内容写在 hook 里：
{hooks}
   例：hook＝「他推开门，屋里坐着本该已死的人」，hook_type＝「反转」；
       hook＝「刀已经架在他脖子上」，hook_type＝「危机」。
   写不出类型说明这一章其实没有钩子，此时 hook 与 hook_type 都留空字符串，不要硬编。"""


EMOTION_GUIDE = _emotion_guide()


# ---------------------------------------------------------------- 签约开篇强化
# 平台签约审核只看前 2 万字（≈前 10 章，每章约 2000 字），窗口内的骨架按更严的标准生成与校验。
# 依据：两本被毙书（双界燃灯 / 躺平即超神）尸检结论——前 3 章零爽点兑现、同一爽点连用 2~3 章、
# 金手指只口述不实演、情节要点全是「叫醒 / 叮嘱 / 前往」这类过渡拍。
SIGNING_WINDOW = 10
ENTRY_STRATEGIES = ("受辱反击", "高能开场", "反差日常", "悬念倒叙")
# 过渡拍动词：情节要点里只有这类「纯流程」动作＝这一拍没戏（尸检案例：「沈岳叫醒沈闲并叮嘱礼数」）
TRANSIT_VERBS = ("叫醒", "叮嘱", "前往", "出发", "赶路", "回到", "走进", "来到", "起床",
                 "洗漱", "用饭", "吃饭", "更衣", "送别", "等待", "路过", "寒暄", "拜见")
# 冲突词：要点里只要出现这些，就不再算过渡拍（「回到牢房发现牢门被锁」是真事件，不能误报）
POINT_CONFLICT_WORDS = ("打", "杀", "夺", "抢", "逼", "威胁", "羞辱", "拒绝", "质问", "揭穿",
                        "发现", "反击", "嘲", "骂", "冲突", "争执", "翻脸", "背叛", "受伤",
                        "陷阱", "争", "逃", "救", "赌", "跪", "怒", "冷笑", "刀", "血")


def _signing_guide():
    """签约开篇强化规范：写进拆解 prompt（两种模式共用），窗口内章节从严要求。"""
    strategies = "\n".join(f"     · {s}" for s in ENTRY_STRATEGIES)
    return f"""签约开篇强化（平台签约审核只看前 {SIGNING_WINDOW} 章 ≈ 前 2 万字，窗口内一律从严）：
A. opening（开篇诊断）必填三项：
   · strategy：本书切入点四选一，不要自创词：
{strategies}
     受辱反击＝开场主角被踩到底、当场或当章反打；高能开场＝直接进大事件大场面；
     反差日常＝平凡日常里埋一个反常细节；悬念倒叙＝先给结果或危机片段、再回头讲来路。
   · first_image：第一章第一段第一个画面，一句话（谁在什么处境下做什么），要能直接当正文第一句用；
     「主角醒来发现自己穿越了」不算画面。
   · golden_finger_demo：金手指第一次「实演」的章号——真的用了、读者看到效果才算；
     只被提到 / 介绍 / 觉醒不算。前 3 章内必须实演。
B. 前 {SIGNING_WINDOW} 章每章：payoff 与 hook / hook_type 一律不许为空。
   爽点＝打脸、翻盘、获得、相认、真相揭开、地位跃升，一章至少一个；
   「推进剧情」「加深矛盾」「埋下伏笔」不算爽点。
C. 爽点节奏：前 {SIGNING_WINDOW} 章每章兑现一次；第 {SIGNING_WINDOW} 章之后每 3 章至少兑现一次（payoff 非空）。
   同一爽点不许连用两章——同一反派被同一方式连打两章脸＝水。
D. key_events 每拍必须有「冲突 / 选择 / 反转」之一：
   「叫醒主角」「叮嘱礼数」「前往某地」这类纯流程过渡不是一拍，不许单独成条；
   原文确有这类过程，就与它引发的冲突合并成一条（如「被叫醒→当场被刁难」）。
E. 第 1 章三件套：summary 与 key_events 必须让读者看得出 ①主角是谁 ②他与谁冲突 ③金手指是什么 / 怎么用；
   整章只铺垫世界观、章末才「异象初现」的写法，签约审核必毙。
F. 源文本本身不满足以上标准的（如纯过渡章、爽点空缺），如实留空、不要编造——
   落盘前的校验会把缺口逐条列出，便于回去补原文 / 补大纲。"""


SIGNING_GUIDE = _signing_guide()


def _craft_guide():
    """写作公式视角的提炼要求（craft.py，源自用户写作设定；可在提示词模板库覆盖 craft.*）。
    craft 模块缺失时静默降级为空——主流程（结构提炼）不受影响。"""
    try:
        import craft
        return craft.decompose_guide()
    except Exception:  # noqa
        return ""


COMMON_RULES = """通用要求：
1. chapters 必须覆盖下面文本里的全部章节，按出现顺序排列，不得跳号、重复；章数不确定时按原文实际章标题为准。
2. roles 只能填全书 characters 里出现过的姓名；scene 填本章主要发生地点（一个地点，不要罗列）。
3. chapters 里的 factions 只能填全书 factions 里出现过的势力名称；本章没有势力参与就填空数组。
4. chapters 里的 items 只能填全书 items 里出现过的道具 / 功法名称；本章没有就填空数组。
5. key_events 3~5 条，按时间顺序，每条一句话说清「谁做了什么、结果如何」，便于后续铺成 3~5 拍正文；原文要点不足时按实际条数写，不要编造。
6. 字段值写内容本身：没写到的填空字符串 / 空数组，不要编造；不要把字段说明文字（如「题材类型」「本章摘要」）或「未提及」这类占位词当成值输出。
7. 每章必须填 conflict（核心冲突点：主角与谁/什么对抗、矛盾因何激化）与 hook（章末情绪钩子 / 悬念，一句话勾住读者追读）；summary 与 key_events 要体现爽点节奏（压抑到释放）与冲突密度，开篇前几章尤其要点出抓人钩子。
8. 每章还要填 emotion / tension / payoff / setup / hook_type 五项（情绪流），取值规范见下。
9. 所有姓名 / 名称必须像真实的中文专名：
   · 角色名 2~4 字、以常见姓氏开头（如沈砚、周小满、苏晚），不要用身份称呼代替姓名（「孟皇后」可以，「皇后娘娘」不行）；
   · 禁止任何复读：同一字连写三次（孟孟孟皇后）、同一词连写两次（慈懿慈懿慈懿太后、盘发传话传话嬷嬷）一律不许出现；
   · 禁止谐音梗 / 网络梗 / 搞笑名（如邵刻薄、费纸鸢、郝浪、罗密），也不要生造生僻字堆砌；
   · 势力名 2~10 字、道具功法名 2~10 字，同一批里不得重名，也不得只差一个字。
10. 只输出 JSON，不要解释，不要代码块围栏。"""

REFERENCE_PROMPT = """下面是一部完整的长篇小说正文。请通读全文、做结构与内容分析，只输出一个 JSON 对象，结构严格如下：

__SCHEMA__

本模式：【参考生成】——从原始正文里提炼结构。
要求：
1. 全书梗概、故事设定、人物卡片、逐章摘要与关键事件，全部从下面的正文中读出来。
2. title 优先用原文的章标题；原文若没有章标题，再根据情节自拟简短标题。
3. 每章 summary 以「本章钩子：…」收尾，一句话点出开篇抓人点与章末悬念（情绪钩子），用于控制追读节奏；同时把该章末悬念写入 hook 字段、把本章核心对抗写入 conflict 字段。

__RULES__

__EMOTION_GUIDE__

__SIGNING_GUIDE__

__CARD_GUIDE__

__FACTION_GUIDE__

__ITEM_GUIDE__

__CRAFT_GUIDE__

__LIMIT_NOTE__
__CHUNK_NOTE__
小说全文：
__SOURCE_TEXT__"""

OUTLINE_PROMPT = """下面是一份已经写好的小说大纲 / 分章概括（可能是 Markdown 表格或列表）。请把它整理成结构化 JSON，只输出一个 JSON 对象，结构严格如下：

__SCHEMA__

本模式：【已有大纲】——忠实整理，不创作。
要求：
1. 严格忠实于原文，不要新增、删改或发挥情节。
2. 章标题照抄原有章名，一字不差；章节顺序与编号保持不变。
3. 每章 summary：原文已有概括就压缩到 200~260 字；原文只有章名，就依据全书大纲合理补足，并与前后章自洽；以「本章钩子：…」收尾，一句话点出开篇抓人点与章末悬念（情绪钩子）；同时把章末悬念写入 hook 字段、核心对抗写入 conflict 字段。

__RULES__

__EMOTION_GUIDE__

__SIGNING_GUIDE__

__CARD_GUIDE__

__FACTION_GUIDE__

__ITEM_GUIDE__

__CRAFT_GUIDE__

__LIMIT_NOTE__
__CHUNK_NOTE__
大纲内容：
__SOURCE_TEXT__"""

# 分段分析后的「合并」提示词：把各片段的设定归并成一套书级设定
MERGE_PROMPT = """下面是同一部书**分段分析**得到的若干片段结果（按时间顺序）。请把它们合并成**一套统一的书级设定**，只输出一个 JSON 对象，结构严格如下：

{
  "book_summary": "全书梗概，300~500 字",
  "story_bible": __SB_SCHEMA__
}

合并要求：
1. 去重归纳：同一地点 / 名词 / 伏笔只保留一次，不要重复罗列。
2. 全书主线、核心冲突、核心悬念要覆盖整本书的走向，而不只是某一段。
3. 各片段说法冲突时，取信息更完整、更具体的一方。
4. 人物详细设定不要写进 story_bible（角色卡另有字段）。
5. 只输出 JSON，不要解释，不要代码块围栏。

各片段的书级设定：
__PARTS__

各片段章节摘要串联（用于归纳全书梗概）：
__SUMMARIES__

已识别角色（仅供人名 / 定位对齐，不必复述）：
__CAST__"""


def _prompt(key, default):
    """读取提示词模板库里的覆盖值；导入失败时退回内置默认。"""
    try:
        import prompts
        return prompts.effective(key, default)
    except Exception:  # noqa
        return default


def build_prompt(mode, text, limit=None, chunk_note=""):
    tmpl = (_prompt("decompose.reference", REFERENCE_PROMPT) if mode == "reference"
            else _prompt("decompose.outline", OUTLINE_PROMPT))
    limit_note = ""
    if limit:
        limit_note = (f"\n本次范围限制：尽管上面要求覆盖全部章节，本次**只处理前 {limit} 章**"
                      f"（第 1 章至第 {limit} 章）。chapters 数组只输出这 {limit} 章，其余章节一律不要输出。\n")
    return (tmpl
            .replace("__SCHEMA__", SCHEMA_JSON)
            .replace("__RULES__", COMMON_RULES)
            .replace("__EMOTION_GUIDE__", EMOTION_GUIDE)
            .replace("__SIGNING_GUIDE__", SIGNING_GUIDE)
            .replace("__CARD_GUIDE__", CARD_GUIDE)
            .replace("__FACTION_GUIDE__", FACTION_GUIDE)
            .replace("__ITEM_GUIDE__", ITEM_GUIDE)
            .replace("__CRAFT_GUIDE__", _craft_guide())
            .replace("__LIMIT_NOTE__", limit_note)
            .replace("__CHUNK_NOTE__", chunk_note or "")
            .replace("__SOURCE_TEXT__", text))


def build_merge_prompt(parts, summaries, cast):
    return (_prompt("decompose.merge", MERGE_PROMPT)
            .replace("__SB_SCHEMA__", _sb_schema_json())
            .replace("__PARTS__", parts)
            .replace("__SUMMARIES__", summaries)
            .replace("__CAST__", cast))


def resolve_source(mode, source):
    if source:
        if os.path.isabs(source):
            return source
        p = os.path.join(INPUT_DIR, source)   # 相对名默认到 input/ 找
        return p if os.path.exists(p) else resolve(source)
    if mode == "outline":
        skip = ("readme", "changelog", "license", "contributing", "贡献")
        mds = [p for p in glob.glob(os.path.join(INPUT_DIR, "*.md"))
               if not os.path.basename(p).lower().startswith(skip)]
        if len(mds) == 1:
            return mds[0]
        if len(mds) > 1:                       # 多个候选 → 取最大的那个，并提示
            mds.sort(key=os.path.getsize, reverse=True)
            print(f"[i] 找到 {len(mds)} 个候选大纲，自动选最大的：{os.path.basename(mds[0])}")
            print(f"    其余：{'、'.join(os.path.basename(p) for p in mds[1:])}（要指定请用 --source）")
            return mds[0]
        sys.exit("[x] input/ 里没有可用的 .md，请用 --source 指定大纲文件。")
    return os.path.join(INPUT_DIR, REFERENCE_DEFAULT_SOURCE)


def read_source(path, max_chars):
    if not os.path.exists(path):
        sys.exit(f"[x] 找不到源文件：{path}")
    # 源文件编码不确定（中文小说常见 GBK/GB18030），按 utf-8 → gb18030 依次尝试
    raw = open(path, "rb").read()
    text, enc = None, None
    for e in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            text, enc = raw.decode(e), e
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text, enc = raw.decode("utf-8", errors="replace"), "utf-8(errors=replace)"
    print(f"[i] 源文件编码：{enc}")
    if max_chars and len(text) > max_chars:
        print(f"[!] 源文本 {len(text)} 字，超过你设定的 {max_chars} 上限，只取前 {max_chars} 字。")
        print("    （这是你主动设的上限；不设上限时会自动分段分析，不会丢内容）")
        text = text[:max_chars]
    return text


def _hard_split(text, limit):
    """无章回标记时的兜底切分：按行（段落）贪心装箱。"""
    if len(text) <= limit:
        return [text]
    chunks, cur, size = [], [], 0
    for line in text.splitlines(keepends=True):
        if size + len(line) > limit and cur:
            chunks.append("".join(cur))
            cur, size = [], 0
        cur.append(line)
        size += len(line)
    if cur:
        chunks.append("".join(cur))
    return chunks


def _merge_tiny(chunks, limit):
    """把硬切出来的极短尾巴并回上一段：几十字的段不值得单独调一次模型，也不该占一个章号。"""
    tiny = max(500, limit // 20) if limit > 0 else 500
    out = []
    for c in chunks:
        if out and len(c.strip()) < tiny:
            out[-1] += c
        else:
            out.append(c)
    return [c for c in out if c.strip()]


def parse_chapter_range(s):
    """把 '25' 或 '10-25' 解析成 (下限, 上限)。单值 = 只设上限（下限 0）。"""
    s = str(s or "").strip()
    m = re.fullmatch(r"(\d+)\s*[-~～]\s*(\d+)", s)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        return (hi, lo) if lo > hi else (lo, hi)
    m = re.fullmatch(r"(\d+)", s)
    if m:
        return 0, int(m.group(1))
    raise ValueError(f"chunk-chapters 格式应为 N 或 MIN-MAX，收到：{s!r}")


def _split_by_chapters(text, k):
    """把一段文本按章回标题均分成 k 份（每份章数尽量相等）。"""
    marks = [m.start() for m in CHAP_RE.finditer(text)]
    n = len(marks)
    if k <= 1 or n < 2:
        return [text]
    k = min(k, n)                             # 段数不可能多于章数，否则下面取 marks 会越界
    base, rem = divmod(n, k)
    out, idx, cur = [], 0, 0
    for i in range(k - 1):
        idx += base + (1 if i < rem else 0)
        cut = marks[idx]                      # 第 idx+1 章的起始位置
        out.append(text[cur:cut])
        cur = cut
    out.append(text[cur:])
    return [c for c in out if c.strip()]


def split_text(text, limit=0, max_chapters=0, min_chapters=0):
    """按章回标题切分，同时受三个约束：
       limit         每段最大字数（0 = 不限）
       max_chapters  每段最多章数（0 = 不限）——硬上限，约束模型单次输出规模
       min_chapters  每段最少章数（0 = 不限）——限制段数上限，避免把少章书切成碎段
    切点全部落在章首（三者的取舍是先满足章数，再在段内按章细分），
    硬切出的几十字尾巴会并回上一段。返回的各段按顺序拼起来等于原文（不丢内容）。"""
    marks = [m.start() for m in CHAP_RE.finditer(text)]
    if len(marks) < 2:                                  # 没有章标 → 只能按段落兜底
        raw_cuts = _hard_split(text, limit) if (limit > 0 and len(text) > limit) else [text]
        return _merge_tiny(raw_cuts, limit)

    # 先算「至少要分几段」：字数阈值与章数上限各给一个下限，取大者；
    # 再用 min_chapters 限制上限，避免把 10 章硬分成 5 段、每段只剩 2 章。
    # 这样切点全部落在章首，各段章数接近，不会出现「0 章的碎段」。
    nmarks = len(marks)
    k = 1
    if limit > 0:
        k = max(k, -(-len(text) // limit))
    if max_chapters > 0:
        k = max(k, -(-nmarks // max_chapters))
    if min_chapters > 0:
        k = min(k, max(1, nmarks // min_chapters))
    cuts = _split_by_chapters(text, k) if k > 1 else [text]

    # 章长不均时某段可能仍超字数阈值 → 优先在该段内部按章再分（切点仍在章首），
    # 只有「单章自己就超限」才按行硬切：宁可切断章，也不要让模型输出写断。
    out = []
    for c in cuts:
        subs = [c]
        if limit > 0 and len(c) > limit:
            sub_k = -(-len(c) // limit)
            if sub_k > 1:
                subs = _split_by_chapters(c, sub_k)
        for s2 in subs:
            out.extend(_hard_split(s2, limit) if limit > 0 else [s2])

    return _merge_tiny(out, limit)


def slice_first_chapters(text, n):
    """只取前 n 章的文本（试跑用，避免为了 3 章去分析整本书）。"""
    marks = [m.start() for m in CHAP_RE.finditer(text)]
    if n <= 0 or len(marks) <= n:
        return text
    return text[0:marks[n]]


def norm_list(v):
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str):
        return [x.strip() for x in re.split(r"[、,，;；]", v) if x.strip()]
    return []


def _chapter_num(v, default):
    """章号归一：模型偶尔写「第3章」「3-5」，取第一段数字，失败回退顺序号。"""
    m = re.search(r"\d+", str(v if v is not None else ""))
    if m:
        try:
            n = int(m.group(0))
            if n > 0:
                return n
        except ValueError:
            pass
    return default


def norm_emotion(v):
    """情绪主线归一：只留词表内的词，最多 3 个，用 → 连接。

    模型会写成「憋屈-爆发」「憋屈/爽」「先憋屈后打脸」各种花样，统一收成「憋屈→爽」，
    否则下游画曲线、做统计时同一情绪会裂成十几个词。
    """
    # 模型有时给数组（["憋屈", "怒"] 或 ["憋屈→怒"]）：先拼成一条再统一切分，
    # 否则元素里自带的箭头不会被拆开，最后会整段塞进「一个情绪」
    if isinstance(v, list):
        v = "→".join(str(x) for x in v)
    raw = re.split(r"[→>\-—~,，、/|；;]+", str(v or ""))
    picked = []
    for piece in raw:
        piece = str(piece).strip()
        if not piece:
            continue
        hit = next((lb for lb in EMOTION_LABELS if lb in piece), "")
        if hit and hit not in picked:
            picked.append(hit)
        if len(picked) >= 3:
            break
    return "→".join(picked)


def norm_tension(v):
    """情绪峰值归一：1~10 的整数；「8（爆发）」「7/10」「80」都能救回成整数，认不出返回 0。"""
    if isinstance(v, bool):
        return 0
    for n in re.findall(r"\d+", str(v if v is not None else "")):
        try:
            k = int(n)
        except ValueError:
            continue
        if 1 <= k <= 10:
            return k
        if 11 <= k <= 20:                   # 略微超上限，按顶格算
            return 10
        if 20 < k <= 100:                   # 模型偶尔按百分制给（80 → 8）
            return max(1, min(10, int(round(k / 10.0))))
    return 0


def norm_hook_type(v):
    """章末钩子类型归一：只接受六类之一，认不出返回空（空比错好，前端据此判断「这章没钩子」）。"""
    s = str(v or "").strip()
    if not s:
        return ""
    return next((lb for lb in HOOK_TYPE_LABELS if lb in s), "")


def norm_opening(v):
    """开篇诊断归一：strategy 收敛到四选一；其余两项只取字符串（认不出就留空，交给校验报警）。"""
    v = v if isinstance(v, dict) else {}
    raw = str(v.get("strategy") or "").strip()
    strategy = next((s for s in ENTRY_STRATEGIES if s in raw), "")
    return {"strategy": strategy,
            "first_image": str(v.get("first_image") or "").strip(),
            "golden_finger_demo": str(v.get("golden_finger_demo") or "").strip()}


def _similar(a, b):
    """两条文案的相似度（0~1）：用于「同一爽点连用两章」检测。"""
    a, b = re.sub(r"\s+", "", str(a or "")), re.sub(r"\s+", "", str(b or ""))
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def signing_check(chapters, opening=None):
    """签约窗口（前 2 万字 ≈ 前 10 章）骨架体检：只诊断、不修改。

    返回 [{sev, chapter, msg}]，随 chapters.json 落盘——「章节数据」页能直接看到缺口，
    拆解日志里也会逐条打印，避免「骨架看着挺全、签约又被毙」。
    """
    issues = []

    def add(sev, no, msg):
        issues.append({"sev": sev, "chapter": no, "msg": msg})

    opening = opening if isinstance(opening, dict) else {}
    if not opening.get("strategy"):
        add("中", 1, "opening.strategy 为空：未识别切入点策略"
                    "（受辱反击 / 高能开场 / 反差日常 / 悬念倒叙）")
    if not opening.get("first_image"):
        add("中", 1, "opening.first_image 为空：缺少「第一章第一个画面」，开篇切入点存疑")
    demo_no = _chapter_num(opening.get("golden_finger_demo"), 0)
    if not demo_no:
        add("高", 1, "金手指全书未见实演章号：只口述不实演是签约被毙的典型原因")
    elif demo_no > 3:
        add("高", demo_no, f"金手指第 {demo_no} 章才第一次实演：签约窗口（前 3 章）内必须看到效果")

    win = chapters[:SIGNING_WINDOW]
    for i, c in enumerate(win, 1):
        n = c.get("no") or _chapter_num(c.get("chapter_id"), i)
        if not c.get("payoff"):
            add("高", n, "本章爽点（payoff）为空：签约窗口内每章必须兑现一个爽点")
        if not c.get("hook"):
            add("高", n, "章末钩子为空：签约窗口内每章必须有钩子勾住追读")
        elif not c.get("hook_type"):
            add("中", n, "hook 有内容但 hook_type 为空：钩子类型认不出，强度存疑")
        for p in c.get("points") or []:
            if (len(p) <= 26 and any(v in p for v in TRANSIT_VERBS)
                    and not any(w in p for w in POINT_CONFLICT_WORDS)):
                add("中", n, f"情节要点「{p}」疑似过渡拍（纯流程无冲突），建议并入冲突或删去")
    # 同一爽点连用：相邻章 payoff 高度相似（同一反派被同一方式连打两章＝水）。
    # 连续多章雷同时只报一条区间，避免「连用 8 章」刷出 8 条一模一样的告警。
    def _no(c, fallback):
        return c.get("no") or _chapter_num(c.get("chapter_id"), fallback)

    group = []
    for i, c in enumerate(win):
        if group and _similar(group[0].get("payoff"), c.get("payoff")) >= 0.6:
            group.append(c)
            continue
        if len(group) >= 2:
            n1, n2 = _no(group[0], i - len(group) + 1), _no(group[-1], i)
            add("高", n2, f"第 {n1}~{n2} 章爽点雷同：「{group[0].get('payoff')}」"
                          f"同一爽点连用 {len(group)} 章")
        group = [c]
    if len(group) >= 2:
        add("高", _no(group[-1], len(win)),
            f"第 {_no(group[0], 1)}~{_no(group[-1], len(win))} 章爽点雷同："
            f"「{group[0].get('payoff')}」同一爽点连用 {len(group)} 章")
    # 第 1 章三件套（骨架级近似检查）：核心冲突必须能在第 1 章看出来
    if win and not win[0].get("conflict"):
        add("高", win[0].get("no") or 1, "第 1 章核心冲突为空：签约三件套（主角 / 冲突 / 金手指）缺「冲突」")
    # 窗口之后：每 3 章至少一次爽点兑现
    rest = chapters[SIGNING_WINDOW:]
    for i in range(0, len(rest) - 2, 3):
        grp = rest[i:i + 3]
        if not any(c.get("payoff") for c in grp):
            n1 = grp[0].get("no") or _chapter_num(grp[0].get("chapter_id"), SIGNING_WINDOW + i + 1)
            n2 = grp[-1].get("no") or _chapter_num(grp[-1].get("chapter_id"), SIGNING_WINDOW + i + 3)
            add("中", n1, f"第 {n1}~{n2} 章连续 3 章无爽点兑现")
    return issues


def to_chapters_json(decomposed, limit=None):
    """把拆解结果转换成 chapters.json 结构（页面与后续生成可直接消费）。"""
    # 模型偶尔不按 schema 出（story_bible 给成字符串、数组里混进字符串），先归一再用
    sb = decomposed.get("story_bible")
    if not isinstance(sb, dict):
        sb = {}
    cards = [c for c in (decomposed.get("characters") or []) if isinstance(c, dict)]
    facs = [f for f in (decomposed.get("factions") or []) if isinstance(f, dict)]
    items = [it for it in (decomposed.get("items") or []) if isinstance(it, dict)]
    # 交由 story_bible / entities 模块统一拼装，保证与界面录入、后端保存的格式完全一致
    card_dicts = [normalize_card({k: c.get(k, "") for k, _, _ in CARD_FIELDS}) for c in cards]
    faction_dicts = [normalize_faction({k: f.get(k, "") for k, _, _ in FACTION_FIELDS}) for f in facs]
    item_dicts = [normalize_item({k: it.get(k, "") for k, _, _ in ITEM_FIELDS}) for it in items]

    chapters, used = [], set()
    raw_chapters = [c for c in (decomposed.get("chapters") or []) if isinstance(c, dict)]
    for idx, ch in enumerate(raw_chapters, 1):
        if limit and idx > limit:
            break
        num = _chapter_num(ch.get("chapter"), idx)
        if num in used:                     # 「3-5」和「3」都会被归成 3：避免章号撞车、正文互相覆盖
            num = max(used) + 1
        used.add(num)
        chapters.append({
            "no": num,
            "chapter_id": f"第{num}章",
            "title": ch.get("title") or f"第{num}章",
            "roles": norm_list(ch.get("roles")),
            "factions": norm_list(ch.get("factions")),
            "items": norm_list(ch.get("items")),
            "scene": ch.get("scene", ""),
            "summary": ch.get("summary", ""),
            "points": norm_list(ch.get("key_events")),
            "conflict": ch.get("conflict", ""),
            "hook": ch.get("hook", ""),
            "hook_type": norm_hook_type(ch.get("hook_type")),
            "emotion": norm_emotion(ch.get("emotion")),
            "tension": norm_tension(ch.get("tension")),
            "payoff": _one_line(ch.get("payoff"), 80),
            "setup": _one_line(ch.get("setup"), 80),
        })
    # 统一清洗复读名 / 合并重复卡 / 去掉重复引用，再拼设定库，保证卡片与章节引用一致
    tmp = {"chapters": chapters, "items": item_dicts,
           "story_bible_cards": card_dicts, "story_bible_factions": faction_dicts}
    sync_document(tmp)
    story_bible = compose_story_bible(sb, tmp["story_bible_cards"], tmp["story_bible_factions"])
    return {"story_bible": story_bible,
            "opening": norm_opening(decomposed.get("opening")),
            "chapters": chapters,
            "items": tmp["items"]}


def call_json(prompt, api_key, base_url, model, tag="", allow_truncated=False, hint="", system=None):
    """调用 DeepSeek 并解析 JSON；连续失败时落盘原始输出并退出。

    allow_truncated=True 时把 OutputTruncated 原样抛给调用方——
    分段循环会据此把该段再切小重跑，而不是直接失败。
    """
    try:
        system_prompt = system or _prompt("decompose.system", SYSTEM_PROMPT)
        return chat_json(api_key, base_url, model, system_prompt, prompt, retries=2)
    except OutputTruncated as e:
        if allow_truncated:
            raise
        bad = os.path.join(DATA_DIR, "decomposed.raw.txt")
        with open(bad, "w", encoding="utf-8") as f:
            f.write(e.raw)
        sys.exit(f"[x] {tag}{e}\n    {hint or '单次输出装不下，请用 --chunk-chars 调小重试'}"
                 f"（原始输出已存到 {bad}）")
    except JsonParseError as e:
        bad = os.path.join(DATA_DIR, "decomposed.raw.txt")
        with open(bad, "w", encoding="utf-8") as f:
            f.write(e.raw)
        sys.exit(f"[x] {tag}{e}\n    连续重试仍失败，原始输出已存到 {bad}")
    except Exception as e:                       # noqa: 网络 / 鉴权 / 额度错误统一转成可读提示
        sys.exit(f"[x] {tag}调用 AI 失败：{e}")


# ---------------------------------------------------------------- 本地模式（无 API Key）
# 没有 Key 时不能凭空生成剧情，但可以用确定性规则先把「结构」立起来：
# 按章回标题切章、首尾摘录当摘要、按对话引导词统计人名、按地点后缀抓场景。
# 产出与 AI 版同一套 schema，页面能直接编辑，storymap / expand 也能接着跑。

_LOCAL_VERBS = (r"(?:说道|问道|笑道|喝道|叫道|怒道|叹道|应道|答道|回答|开口道|开口|"
                r"沉声道|低声道|冷声道|淡淡道|轻声道|大喝道|大喝|吩咐|嘀咕|自语|"
                r"点头|摇头|冷笑|苦笑|正色道|急道|忙道|接口道|接着道)")
_LOCAL_NAME_RE = re.compile(r"([\u4e00-\u9fa5]{2,3})" + _LOCAL_VERBS)
_LOCAL_PLACE_RE = re.compile(
    r"(?:在|来到|走进|回到|赶到|抵达|进了|出了|穿过|登上|前往|沿着|走上|经过|路过)"
    r"(?:([\u4e00-\u9fa5]{1,5}(?:城|镇|村|山|谷|寺|庙|楼|阁|府|宫|殿|院|庄|寨|关|渡|"
    r"巷|街|林|湖|河|江|岛|堂|桥|塔|亭|栈|店|坊|堡|屯|营|岭|坡|洞|崖|泉|溪|潭|庵|祠|"
    r"陵|墓|狱|仓|库))|(山道|官道|驿道|小道|大道))")
_LOCAL_CHAPTER_RE = re.compile(
    r"^[ \t　>*#\-•]*(第\s*[0-9一二三四五六七八九十百千零两]+\s*[章回节])([^\n]{0,40})$",
    re.MULTILINE)

# 常见姓氏：给「像人名」的词加权，避免把普通两字词当角色
_LOCAL_SURNAMES = set(
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜戚谢邹喻柏水窦章"
    "云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳酆鲍史唐费廉岑薛雷贺倪汤滕殷罗毕郝邬安常"
    "乐于时傅皮卞齐康伍余元卜顾孟平黄和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞"
    "熊纪舒屈项祝董梁杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍"
    "虞万支柯管卢莫房裘解应宗丁宣邓郁单杭洪包诸左石崔吉龚程邢裴陆荣翁荀羊惠甄曲家封芮"
    "储靳松井段富巫乌焦巴牧山谷车侯全班秋仲伊宫宁仇栾暴甘厉戎祖武符刘景詹束龙叶幸司韶"
    "黎薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池乔阴胥能苍双闻莘党翟谭贡劳姬申扶堵冉宰郦雍"
    "桑桂濮牛寿通边扈燕冀浦尚农温别庄晏柴瞿阎慕连茹习艾鱼容向古易慎戈廖庾终居衡步都耿"
    "满弘匡国文寇广禄阙东欧沃利蔚越隆师巩聂晁融冷辛简饶曾沙养鞠丰巢关蒯相查后荆红游竺"
    "权盖益桓公")
# 不是人名的两/三字词：对话引导词前面常出现「他们／众人／声音」这类主语
_LOCAL_NAME_STOP = set("""他们 我们 你们 咱们 自己 众人 大家 有人 那人 这人 旁人 对方 二人 三人
    一人 两人 几人 声音 心中 眼里 口中 脸上 身上 手中 脚下 门外 身后 面前 眼前 半晌 片刻
    此时 此刻 当下 忽然 突然 顿时 当即 随即 于是 因此 然而 但是 可是 所以 如果 虽然 只是
    不过 已经 将军 大人 公子 姑娘 夫人 老爷 少爷 小姐 师父 师兄 师弟 师姐 师妹 掌柜 小二
    官人 老汉 老妇 少年 少女 男人 女人 孩子 众将 众兵 众僧 百姓 对方 其他 别人""".split())
_LOCAL_EVENT_KW = ("死", "杀", "逃", "追", "打", "战", "夺", "救", "发现", "突然", "竟然", "原来",
                   "决定", "答应", "背叛", "受伤", "消失", "出现", "醒来", "离开", "遇见", "跪下",
                   "拔刀", "发誓", "成亲", "决裂", "告密", "落泪", "颤抖", "怒吼", "求")
_LOCAL_TURN_KW = ("但", "却", "然而", "反而", "不料", "谁知", "偏偏", "竟然")


def _local_sentences(text):
    """按中英文句末标点切句（保留标点），用于摘录与要点筛选。"""
    parts = re.split(r"(?<=[。！？…!?；\n])", text)
    return [p.strip() for p in parts if p.strip()]


def _one_line(s, limit=60):
    return re.sub(r"\s+", " ", str(s or "")).strip()[:limit]


def _local_summary(text, n=220):
    """首尾摘录：本地模式没有模型概括，就用开头与结尾的句子代表「起」与「收」。

    首尾覆盖到同一句时（说明整段本来就短），直接给前 n 字，避免摘要里出现两遍原文。
    """
    sents = _local_sentences(text)
    if not sents:
        return ""
    half = max(30, n // 2)
    hi_end, cnt = 0, 0
    for i, s in enumerate(sents):
        if cnt >= half:
            break
        hi_end = i + 1
        cnt += len(s)
    lo_start, cnt = len(sents), 0
    for i in range(len(sents) - 1, -1, -1):
        if cnt >= half:
            break
        lo_start = i
        cnt += len(sents[i])
    if lo_start <= hi_end:
        return _one_line("".join(sents), n)
    h = _one_line("".join(sents[:hi_end]), half)
    t = _one_line("".join(sents[lo_start:]), half)
    return f"{h} …… {t}"


def _local_events(text, k=3):
    """按「动作/转折」关键词给句子打分，挑出最像事件的三句。"""
    sents = _local_sentences(text)
    if not sents:
        return []
    scored = []
    for i, s in enumerate(sents):
        score = sum(1 for w in _LOCAL_EVENT_KW if w in s)
        if score:
            scored.append((score, i, s))
    scored.sort(key=lambda x: (-x[0], x[1]))
    picked = sorted(scored[:k], key=lambda x: x[1])
    out = [_one_line(s, 60) for _, _, s in picked]
    return out or [_one_line(s, 60) for s in sents[:k]]


def _local_hook(text):
    sents = _local_sentences(text)
    return _one_line(sents[-1], 50) if sents else ""


def _local_conflict(text):
    for s in _local_sentences(text):
        if any(w in s for w in _LOCAL_TURN_KW):
            return _one_line(s, 60)
    return ""


def _local_places(text):
    """取出正文里出现过的场所名（前缀是「在／来到／走进…」，后缀是城／镇／客栈／山道…）。"""
    out = []
    for m in _LOCAL_PLACE_RE.finditer(text):
        name = m.group(1) or m.group(2)
        if name:
            out.append(name)
    return out


def _local_scene(text):
    hits = Counter(_local_places(text))
    return hits.most_common(1)[0][0] if hits else ""


# 人名里不该出现的虚词：命中即判定不是人名（如「李慕白没有回答」里的「白没有」）
_LOCAL_NAME_BAD = "没有不在是就都也还又却已把被让给对从向和与或则而但才只更最太很到过着得了吗呢吧啊"


def _local_names(parts, top=12):
    """从「XX道／说／问」这类对话引导里统计人名：姓氏开头的词加权，过滤代词与泛称。"""
    cnt = Counter()
    for seg in parts:
        for m in _LOCAL_NAME_RE.finditer(seg):
            name = m.group(1)
            if len(name) < 2 or name in _LOCAL_NAME_STOP:
                continue
            if name[0] in "他她我你它咱您":
                continue
            if any(ch in _LOCAL_NAME_BAD for ch in name[1:]):
                continue
            if name[0] in _LOCAL_NAME_BAD:
                continue
            cnt[name] += 1
    # 没有姓氏打头的词必须出现两次以上才算人名，避免把「白没有」这类跨词片段收进来
    items = [(n, c) for n, c in cnt.items() if n[0] in _LOCAL_SURNAMES or c >= 2]

    def score(item):
        name, c = item
        return c * (3 if name[0] in _LOCAL_SURNAMES else 1), c

    return [n for n, _ in sorted(items, key=score, reverse=True)[:top]]


def _local_chapter_spans(text):
    """按章回标题切章；没有章标时按段落每 3000 字左右切块，保证一定有章节产出。"""
    marks = [m.start() for m in _LOCAL_CHAPTER_RE.finditer(text)]
    if len(marks) >= 2:
        return list(zip(marks, marks[1:] + [len(text)]))
    chunks = split_text(text, 3000, 0, 0) if len(text) > 3000 else [text]
    spans, pos = [], 0
    for c in chunks:
        spans.append((pos, pos + len(c)))
        pos += len(c)
    return spans


def local_decompose(text, limit=None):
    """无 Key 时的本地拆解：只做结构，不编造剧情。

    产出与 AI 版同一个 schema（book_summary / story_bible / characters / factions / chapters），
    摘要与要点都是原文摘录，页面能编辑、storymap 能消费；质量有限但流程不会卡住。
    """
    spans = _local_chapter_spans(text)
    chapters, segs = [], []
    for idx, (s, e) in enumerate(spans, 1):
        if limit and idx > limit:
            break
        seg = text[s:e]
        segs.append(seg)
        m = _LOCAL_CHAPTER_RE.search(seg)
        raw_title = (m.group(1) + (m.group(2) or "")) if m else ""
        chapters.append({
            "chapter": idx,
            "title": _one_line(raw_title, 40) or f"第{idx}章",
            "summary": _local_summary(seg),
            "key_events": _local_events(seg),
            "roles": _local_names([seg], 5),
            "factions": [],
            "scene": _local_scene(seg),
            "conflict": _local_conflict(seg),
            "hook": _local_hook(seg),
            # 本地模式只做句子摘录，评不出情绪走向，四项留空（不编）
            "hook_type": "",
            "emotion": "",
            "tension": 0,
            "payoff": "",
            "setup": "",
            "_chars": len(seg),
        })
    names = _local_names(segs, 12)
    places = [p for p, _ in Counter(_local_places(text)).most_common(6)]
    total_chars = sum(c["_chars"] for c in chapters)
    sents = _local_sentences(text)
    dialog = sum(1 for s in sents if re.search(r"[“「].{0,80}[”」]", s))
    ratio = dialog / max(1, len(sents))
    first_person = text.count("我") > max(20, text.count("他") * 0.8)
    supporting = "、".join(names[1:6])
    mainline = "；".join(x for c in chapters[:3] for x in c["key_events"][:2])[:300]
    story_bible = {
        "synopsis": _local_summary(text, 300),
        "genre": "",
        "world": "",
        "power": "",
        "person": "第一人称" if first_person else "第三人称",
        "style": ("对话驱动，节奏偏快" if ratio > 0.35 else
                  "叙述为主，铺垫较多" if ratio < 0.15 else "对话与叙述均衡"),
        "audience": "",
        "mainline": mainline,
        "conflict": next((c["conflict"] for c in chapters if c["conflict"]), ""),
        "suspense": next((c["hook"] for c in chapters if c["hook"]), ""),
        "subplots": "",
        "protagonist": names[0] if names else "",
        "supporting": supporting,
        "antagonist": "",
        "places": "、".join(places),
        "items": "",
        "terms": "",
        "timeline": f"共 {len(chapters)} 章，约 {total_chars} 字，按章回顺序推进",
        "map": "",
        "foreshadow": "",
        "taboos": "",
    }
    characters = []
    for i, n in enumerate(names):
        characters.append({
            "name": n,
            "role": "主角" if i == 0 else "配角",
            "stance": "己方" if i < 3 else "",
            "personality": "", "identity": "", "gender": "",
            "factionCategory": "", "factionName": "",
        })
    lead = "、".join(names[:6]) if names else "（未识别）"
    book_summary = (f"全书 {len(chapters)} 章，约 {total_chars} 字。主要人物：{lead}。"
                    f"开篇：{_local_summary(text, 200)}")
    for c in chapters:
        c.pop("_chars", None)
    return {
        "book_summary": book_summary,
        "story_bible": story_bible,
        "characters": characters,
        "factions": [],
        "items": [],
        "chapters": chapters,
        "mode": "local",
    }


def merge_local(parts):
    """本地合并各片段的章节、角色与势力；书级设定由模型另跑一次合并。"""
    chapters = [ch for p in parts for ch in (p.get("chapters") or [])
                if isinstance(ch, dict)]
    nums = [c.get("chapter") for c in chapters]
    ok = (bool(nums) and all(isinstance(n, int) and n > 0 for n in nums)
          and len(set(nums)) == len(nums)
          and all(nums[i] < nums[i + 1] for i in range(len(nums) - 1)))
    if not ok:                                  # 章号不可靠 → 按出现顺序重排
        for i, c in enumerate(chapters, 1):
            c["chapter"] = i
    byname = {}
    for p in parts:
        for c in (p.get("characters") or []):
            if not isinstance(c, dict):
                continue
            name = str(c.get("name") or "").strip()
            if not name:
                continue
            # 规范化做 key："护院（新招）" 与 "护院"、"主角（未具名）" 与 "主角" 视为同一角色
            key = re.sub(r"[（(][^）)]*[）)]", "", name).strip() or name
            cur = byname.setdefault(key, {"name": key})
            for k, v in c.items():
                if k != "name" and str(v or "").strip() and not str(cur.get(k) or "").strip():
                    cur[k] = v
    fac_byname = {}
    for p in parts:
        for f in (p.get("factions") or []):
            if not isinstance(f, dict):
                continue
            name = str(f.get("name") or "").strip()
            if not name:
                continue
            key = re.sub(r"[（(][^）)]*[）)]", "", name).strip() or name
            cur = fac_byname.setdefault(key, {"name": key})
            for k, v in f.items():
                if k != "name" and str(v or "").strip() and not str(cur.get(k) or "").strip():
                    cur[k] = v
    item_byname = {}
    for p in parts:
        for it in (p.get("items") or []):
            if not isinstance(it, dict):
                continue
            name = clean_name(it.get("name"), 24)
            if not name:
                continue
            cur = item_byname.setdefault(name, {"name": name})
            for k, v in it.items():
                if k != "name" and str(v or "").strip() and not str(cur.get(k) or "").strip():
                    cur[k] = v
    return (chapters, list(byname.values()), list(fac_byname.values()),
            list(item_byname.values()))


def build_merge_inputs(parts, characters):
    part_txt, summ = [], []
    for i, p in enumerate(parts, 1):
        sb = p.get("story_bible") or {}
        lines = [f"{SB_LABEL.get(k, k)}：{str(v)[:140]}" for k, v in sb.items() if str(v or "").strip()]
        part_txt.append(f"[片段{i}]\n" + ("\n".join(lines) if lines else "（无）"))
        ss = [f"{c.get('title', '')}：{str(c.get('summary', ''))[:60]}" for c in (p.get("chapters") or [])]
        summ.append(f"[片段{i}] " + (" ｜ ".join(ss) if ss else "（无）"))
    cast = "、".join(f"{c['name']}（{c.get('role', '')}）" for c in characters[:40]) or "（无）"
    return "\n\n".join(part_txt), "\n".join(summ), cast


def main():
    ap = argparse.ArgumentParser(description="DeepSeek 在线拆解（超长文本自动分段再合并）")
    ap.add_argument("--mode", choices=["reference", "outline"], default="reference",
                    help="reference=全本txt参考生成；outline=已有大纲md整理")
    ap.add_argument("--source", default=None, help="源文本路径（outline 模式不传则自动取工作区唯一的 .md）")
    ap.add_argument("--out-decomposed", default=None, help="默认 data/decomposed.json")
    ap.add_argument("--out-chapters", default=None,
                    help="chapters.json 输出路径，默认 data/chapters.json（会覆盖同名文件）")
    ap.add_argument("--limit", type=int, default=None,
                    help="只处理前 N 章（试跑用；会先把源文本裁到前 N 章再分析）")
    ap.add_argument("--chunk-chars", type=int, default=DEFAULT_CHUNK_CHARS,
                    help=f"分段阈值：源文本超过该字数就分段分析再合并（默认 {DEFAULT_CHUNK_CHARS}）")
    ap.add_argument("--chunk-chapters", default=DEFAULT_CHUNK_CHAPTER_RANGE,
                    help=f"每段章数区间 'MIN-MAX'（或单值=仅上限），如 10-25："
                         f"下限避免出碎段、上限约束单次输出规模（默认 {DEFAULT_CHUNK_CHAPTER_RANGE}）")
    ap.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                    help="总字数上限，0=不限制（默认；超长会自动分段而不是截断）")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--base-url", default=None, help=f"默认 {DEFAULT_BASE_URL}（或环境变量 DEEPSEEK_BASE_URL）")
    ap.add_argument("--api-key", default=None, help="默认读环境变量 DEEPSEEK_API_KEY")
    ap.add_argument("--dry-run", action="store_true", help="只打印分段与 prompt，不调用 API")
    ap.add_argument("--local", action="store_true",
                    help="强制本地规则拆解（不调用模型）；未配置 Key 时自动启用")
    ap.add_argument("--no-adapt", action="store_true",
                    help="只拆解不改编（reference 模式默认拆完接着改编；页面任务用它自行串联两阶段）")
    ap.add_argument("--adapt", action="store_true",
                    help="拆解完接着改编（outline 模式默认不改编，需显式加本参数）")
    ap.add_argument("--out-book", default="", help="改编后的新书名（留空 = 由模型生成书名）")
    ap.add_argument("--style", default="", help="改编要求：题材/文风/基调/命名风格")
    ap.add_argument("--target-chapters", type=int, default=0,
                    help="改编目标章数（0 = 与源书一致；大于源书 = 扩写，小于源书 = 压缩合并）")
    ap.add_argument("--sequel-chapters", type=int, default=0,
                    help="在原著结局后续写的章数（0 = 不续写），章号接在目标章数之后")
    args = ap.parse_args()

    if args.limit is not None and args.limit <= 0:
        sys.exit("[x] --limit 必须是正整数（只处理前 N 章）")
    if args.target_chapters < 0 or args.sequel_chapters < 0:
        sys.exit("[x] --target-chapters / --sequel-chapters 不能为负数（0 = 不启用）")
    if args.out_book and args.out_book == _book_dir_name(args):
        sys.exit("[x] 新书名不能与源书名相同（会覆盖拆解产出）")
    source = resolve_source(args.mode, args.source)
    text = read_source(source, args.max_chars)
    base_url = resolve_base_url(args.base_url)

    if args.limit:
        before = len(text)
        text = slice_first_chapters(text, args.limit)
        if len(text) != before:
            print(f"[i] 只取前 {args.limit} 章：{before} → {len(text)} 字")
    ch_min, ch_max = parse_chapter_range(args.chunk_chapters)
    chunks = split_text(text, args.chunk_chars, ch_max, ch_min)
    total = len(chunks)

    if args.dry_run:
        p1 = build_prompt(args.mode, chunks[0], None,
                          f"\n【分段提示】下面只是全书的第 1/{total} 段。\n" if total > 1 else "")
        print(f"[dry-run] mode={args.mode} model={args.model} base_url={base_url}")
        rng = f"{ch_min}-{ch_max} 章" if ch_min else f"最多 {ch_max} 章"
        print(f"[dry-run] source={source}｜有效文本 {len(text)} 字 → {total} 段"
              f"（字数阈值 {args.chunk_chars}，每段 {rng}）")
        print(f"[dry-run] 第 1 段 {len(chunks[0])} 字，prompt {len(p1)} 字")
        if total > 1:
            nch = [len(CHAP_RE.findall(c)) for c in chunks]
            print(f"[dry-run] 各段字数：{[len(c) for c in chunks]}")
            print(f"[dry-run] 各段章数：{nch}")
        print("-" * 60)
        print(p1[:900] + "\n...(略)")
        return

    api_key = key_or_empty(args.api_key)
    if args.local or not api_key:
        if not args.local:
            print("[!] 未配置 API Key：改用本地规则拆解"
                  "（按章回切分 + 首尾摘录 + 人物/地点统计，产出为可编辑骨架）")
        decomposed = local_decompose(text, args.limit)
        _write_outputs(decomposed, args, note="，本地模式")
        return

    parts = []
    queue = list(chunks)
    multi = len(queue) > 1
    idx = 0
    # 截断后二分是「把输入切小再试」，但每轮都会把子段插回队首：
    # 若每段都截断，段数会指数增长、任务永不结束。这两道闸门保证一定收尾。
    MIN_SPLIT_CHARS = 500
    max_steps = max(40, len(queue) * 12)
    skipped = []
    while queue:
        if idx >= max_steps:
            print(f"[!] 已分析 {idx} 段，达到步数上限 {max_steps}："
                  f"剩余 {len(queue)} 段不再拆分，直接跳过")
            skipped.extend(queue)
            break
        ck = queue.pop(0)
        idx += 1
        note = ""
        if multi:
            note = ("\n【分段提示】下面只是全书的**其中一段**（不是整本）。chapters 只需覆盖本段内的章节；"
                    "chapter 请尽量填该章在原书中的真实章号（读段内章标题即可判断），"
                    "无法判断就按段内顺序从 1 编号，合并时会自动重排。"
                    "story_bible 只填本段能看出的信息，看不出的留空。\n")
        tail = f"（队列还剩 {len(queue)} 段）" if queue else ""
        print(f"[{idx}] 分析 {len(ck)} 字{tail} ...")
        try:
            parts.append(call_json(build_prompt(args.mode, ck, None, note),
                                   api_key, base_url, args.model,
                                   tag=f"[片段{idx}] ", allow_truncated=True))
        except OutputTruncated as e:
            # 这段的输入太大，模型输出装不下 → 就地二分再跑，不改用户的调用方式
            if len(ck) <= MIN_SPLIT_CHARS:
                # 已经切到这么短还装不下，再切只会无限细分：记入缺失清单并跳过
                print(f"    [!] 该段仅 {len(ck)} 字仍被截断，跳过（已记入缺失清单）")
                skipped.append(ck)
                continue
            sub = split_text(ck, max(1, len(ck) // 2), 0, 0)
            if len(sub) < 2:
                bad = os.path.join(DATA_DIR, "decomposed.raw.txt")
                with open(bad, "w", encoding="utf-8") as f:
                    f.write(e.raw)
                print(f"    [!] [片段{idx}] 该段 {len(ck)} 字已无法再切，跳过；"
                      f"原始输出已存到 {bad}")
                skipped.append(ck)
                continue
            print(f"    [截断] {e}")
            print(f"    → 该段 {len(ck)} 字再切成 {len(sub)} 段重试："
                  f"{[len(x) for x in sub]}")
            queue[0:0] = sub                 # 切开的子段插回队首，保持原有顺序
            multi = True
            continue

    if skipped:
        lost = sum(len(s) for s in skipped)
        print(f"[!] 有 {len(skipped)} 段（约 {lost} 字）因模型输出上限被跳过，"
              "成稿可能缺章：建议改用非推理模型（如 deepseek-chat），"
              "或用 --chunk-chars 调小后重跑")
    if not parts:
        sys.exit("[x] 所有分段都被跳过：没有任何可用结果。"
                 "请改用非推理模型，或用 --chunk-chars 调小后重试")

    if len(parts) == 1:
        decomposed = parts[0]
    else:
        chapters, characters, factions, items = merge_local(parts)
        print(f"[合并] 本地汇总 {len(chapters)} 章 / {len(characters)} 个角色 / "
              f"{len(factions)} 个势力 / {len(items)} 件道具功法；再调模型归纳书级设定 ...")
        p_txt, s_txt, cast = build_merge_inputs(parts, characters)
        merged = call_json(build_merge_prompt(p_txt, s_txt, cast),
                           api_key, base_url, args.model, tag="[合并] ")
        decomposed = {"book_summary": merged.get("book_summary", ""),
                      "story_bible": merged.get("story_bible", {}) or {},
                      # opening（开篇诊断）只在含第 1 章的片段里才判得出来：取第一个非空的
                      "opening": next((p.get("opening") for p in parts
                                       if isinstance(p.get("opening"), dict) and p.get("opening")), {}),
                      "characters": characters,
                      "factions": factions,
                      "items": items,
                      "chapters": chapters}

    # 阵营 / 立场收敛到规范词表：模型偶尔写「亦敌亦友」「暗中支持」之类，前端无法着色，
    # 这里统一映射成 9 种立场 / 6 种阵营；确实认不出的原样保留，不丢信息。
    for _f in (decomposed.get("factions") or []):
        normalize_faction(_f)
    # 角色同理：剧情功能 / 九宫格人设倾向 / 对主角态度统一成规范词
    for _c in (decomposed.get("characters") or []):
        normalize_card(_c)
    # 道具功法：类别收敛到固定词表，名称去复读
    for _it in (decomposed.get("items") or []):
        normalize_item(_it)

    _write_outputs(decomposed, args,
                   note=f"，分 {len(parts)} 段分析" + (f"，跳过 {len(skipped)} 段" if skipped else ""))


def _book_dir_name(args):
    """从 --out-decomposed 反推源书名：只有落在 data/<书名>/ 下才能自动改编。"""
    p = os.path.abspath(resolve(args.out_decomposed or os.path.join("data", "decomposed.json")))
    parent = os.path.dirname(p)
    if os.path.normcase(os.path.dirname(parent)) != os.path.normcase(os.path.abspath(DATA_DIR)):
        return ""
    return os.path.basename(parent)


def _maybe_chain_adapt(args):
    """拆解落盘后按需接着跑改编（reference 全本模式默认开启，--no-adapt 可关闭）。

    改编实现独立在 adapt.py / --adapt-child，这里用子进程调用：日志直接输出到当前终端，
    改编失败时把非零退出码带回去，避免「拆解成功 = 全流程成功」的假象。
    """
    if args.no_adapt or args.dry_run or not (args.adapt or args.mode == "reference"):
        return
    book = _book_dir_name(args)
    if not book:
        print("[!] 拆解已完成，但改编阶段跳过：产出需写到 data/<书名>/ 目录下"
              "（如 --out-decomposed data/某书/decomposed.json）")
        return
    out_book = (args.out_book or "").strip()
    argv = ["--book", book]
    if out_book:
        argv += ["--out-book", out_book]
    if args.style:
        argv += ["--style", args.style]
    for flag, val in (("--target-chapters", args.target_chapters),
                      ("--sequel-chapters", args.sequel_chapters)):
        if val:
            argv += [flag, str(val)]
    if args.model:
        argv += ["--model", args.model]
    if args.base_url:
        argv += ["--base-url", args.base_url]
    if args.api_key:
        argv += ["--api-key", args.api_key]
    if args.local:
        argv += ["--local"]
    print(f"\n[改编] 拆解完成，接着改编《{book}》"
          + (f" → 《{out_book}》" if out_book else "（新书名由模型生成）") + " ...")
    import runner
    if runner.IN_PROCESS:
        # 手机端：没有子进程，直接在同一个后台线程里跑改编（日志顺着当前 stdout 进任务日志）
        code = runner.run_module("adapt", argv)
    else:
        # 用管道收集子进程输出并逐行转发：打包态 GUI 子进程不一定继承父进程的 stdout，
        # 直接 subprocess.call 会让改编日志凭空消失（只有「完成」没有过程）。
        cmd = ([sys.executable, "--adapt-child"] if FROZEN
               else [sys.executable, "-u", os.path.join(SRC_DIR, "adapt.py")]) + argv
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", bufsize=1)
        for line in proc.stdout:
            print(line, end="", flush=True)
        code = proc.wait()
    if code not in (0, 130):
        sys.exit(f"[x] 改编阶段失败（退出码 {code}）：拆解产出已保留，"
                 f"修复后可用 `--adapt-child --book {book}` 单独重跑改编")
    print("[改编] 改编阶段完成")


def _write_outputs(decomposed, args, note=""):
    """落盘 decomposed.json 与 chapters.json——AI 与本地两条路径共用，保证产物一致。"""
    # 落盘前统一清洗复读名 / 合并重复卡 / 同步章节引用，decomposed 与 chapters 共用一套名字
    view = {"characters": decomposed.get("characters") or [],
            "factions": decomposed.get("factions") or [],
            "items": decomposed.get("items") or [],
            "chapters": decomposed.get("chapters") or []}
    sync_document(view)
    decomposed.update(view)
    out_dec = resolve(args.out_decomposed or os.path.join("data", "decomposed.json"))
    os.makedirs(os.path.dirname(out_dec), exist_ok=True)
    with open(out_dec, "w", encoding="utf-8") as f:
        json.dump(decomposed, f, ensure_ascii=False, indent=2)
    n_ch = len(decomposed.get("chapters", []) or [])
    n_card = len(decomposed.get("characters", []) or [])
    n_fac = len(decomposed.get("factions", []) or [])
    n_item = len(decomposed.get("items", []) or [])
    print(f"[完成] 已写出 {out_dec}（{n_ch} 章 / {n_card} 个角色 / {n_fac} 个势力 / {n_item} 件道具功法{note}）")

    chapters = to_chapters_json(decomposed, args.limit)
    # 签约窗口骨架体检：问题随 chapters.json 落盘（signing_check 字段），同时逐条打印
    issues = signing_check(chapters["chapters"], chapters.get("opening"))
    chapters["signing_check"] = issues
    if issues:
        hi = sum(1 for x in issues if x["sev"] == "高")
        print(f"[签约体检] 前 {SIGNING_WINDOW} 章窗口共 {len(issues)} 条问题（高危 {hi} 条）：")
        for x in issues[:12]:
            print(f"    · [{x['sev']}] 第{x['chapter']}章 {x['msg']}")
        if len(issues) > 12:
            print(f"    …… 其余 {len(issues) - 12} 条见 chapters.json 的 signing_check")
    else:
        print(f"[签约体检] 前 {SIGNING_WINDOW} 章窗口未发现问题")
    out_ch = resolve(args.out_chapters or os.path.join("data", "chapters.json"))
    os.makedirs(os.path.dirname(out_ch), exist_ok=True)
    with open(out_ch, "w", encoding="utf-8") as f:
        json.dump(chapters, f, ensure_ascii=False, indent=2)
    print(f"      已写出 {out_ch}（{len(chapters['chapters'])} 章，可在「全书设定 / 章节数据」页继续编辑）")
    _maybe_chain_adapt(args)


if __name__ == "__main__":
    main()
