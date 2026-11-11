# -*- coding: utf-8 -*-
"""
去抄袭改编
====================
输入：data/<源书>/decomposed.json（拆解产出）
输出：data/<新书>/decomposed.json + chapters.json（与拆解完全同构，页面可直接编辑）

流程（复用拆解同款 OpenAI 兼容 API 通道；Key 只从环境变量/参数读取，不落盘）：
  1) 书级改编：统一命名 1 次；角色卡 / 势力卡按批拆分后 4 路并发；总纲 1 次；可选术语映射 1 次
  2) 章节改编（按段调用，默认 20 章/段）：按映射表与改编要求逐章换新命名与文风
     - 默认与源书章数一比一对应（章号不变）
     - --target-chapters N：先做 1 次「章数规划」调用产出「新章←源章范围」映射表，
       再按映射表分段改编；N 大于源书 = 扩写（拆分扩充），N 小于源书 = 压缩（合并）
     - --sequel-chapters M：改编完成后，在结局之后续写 M 章全新剧情（章号接在最后）

用法（一般由控制台「②拆解与改编」卡片自动调用）：
  python adapt.py --book 原著 [--out-book 新书] --style "改为科幻题材" [--target-chapters 60] [--sequel-chapters 10] [--model m --base-url url] [--dry-run]
  不传 --out-book 时新书名由模型生成（book_title），并打印「[OUTPUT_BOOK] 书名」供页面确认。
"""

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from deepseek_common import DEFAULT_MODEL, OutputTruncated, key_or_empty, resolve_base_url
from decompose import call_json as _base_json_call, SYSTEM_PROMPT as BASE_SYSTEM_PROMPT, to_chapters_json
from story_bible import CARD_FIELDS, FACTION_FIELDS, SB_FIELDS
from entities import ITEM_FIELDS, clean_name
from paths import DATA_DIR, book_chapters, book_decomposed, book_dir

CHAPTERS_PER_CALL = 20
MAP_NEW_PER_CALL = 15      # 映射改编：单次调用最多产出多少新章
SEQUEL_PER_CALL = 10       # 续写：单次调用最多产出多少章
BOOK_CARDS_PER_CALL = 10   # 书级改编：单次最多重写多少张角色卡（一次全写会超出 max_tokens）
BOOK_FACTIONS_PER_CALL = 15  # 书级改编：单次最多重写多少张势力卡
BOOK_ITEMS_PER_CALL = 20   # 书级改编：单次最多重写多少张道具 / 功法卡
BOOK_CALL_CONCURRENCY = 4  # 书级角色卡 / 势力卡分批调用并发数（3-4 路，兼顾速度与限流）
DEFAULT_STYLE = ("换一个完全不同的题材与文风，所有人名、地名、宗门、物品、功法等专有名词全部重命名，"
                 "叙事结构与章数保持不变。")

SYSTEM_PROMPT = BASE_SYSTEM_PROMPT  # 兼容旧引用：改编默认沿用拆解的系统提示词，可在提示词库覆盖 adapt.system


def _prompt(key, default):
    """读取提示词模板库里的覆盖值；导入失败时退回内置默认。"""
    try:
        import prompts
        return prompts.effective(key, default)
    except Exception:  # noqa
        return default


def _call(prompt, api_key, base_url, model, tag="", allow_truncated=False, hint=""):
    """改编统一走这条调用：使用 adapt.system 的生效值。"""
    return _base_json_call(prompt, api_key, base_url, model, tag=tag,
                           allow_truncated=allow_truncated, hint=hint,
                           system=_prompt("adapt.system", BASE_SYSTEM_PROMPT))

def _craft(kind):
    """写作公式追加要求（craft.py，源自用户写作设定；可在提示词模板库覆盖 craft.*）。
    craft 模块缺失时静默降级为空——改编主流程不受影响。"""
    try:
        import craft
        return craft.adapt_guide(kind)
    except Exception:  # noqa
        return ""

# 书级改编被截断时的提示：书级已按卡分批，调 chunk-chars 没用，别把拆解参数的提示误用到这里
_BOOK_TRUNC_HINT = ("单次输出装不下：书级改编已按角色卡 / 势力卡分批，"
                    "如仍被截断请改用非推理模型重试")

# 书级改编拆成「命名 → 角色卡分批 → 势力卡分批 → 总纲 → 术语映射」多次调用：
# 原著动辄上百张卡，单次输出（角色 + 势力 + 映射表）很容易超过 max_tokens 被截断。
NAMING_TMPL = """改编要求：
__STYLE__

原著是一个已有故事。请先为改编后的新书起一套全新的专有名词（人名 / 势力名 / 道具功法名），只输出一个 JSON 对象：
{"name_map": [{"old": "原著名字", "new": "新名字"}]}

原著梗概：
__SUMMARY__

原著角色（旧名｜定位｜背景摘要）：
__CAST__

原著势力（旧名｜类型｜简介摘要）：
__FACTIONS__

原著道具功法（旧名｜类别｜效果摘要）：
__ITEMS__

要求：
1. name_map 必须覆盖上面列出的每一个角色名、势力名与道具功法名，共 __N__ 条；old 必须与列出的旧名逐字一致，不得遗漏或重复。
2. new 必须是贴合新题材、新基调的全新名字，不得与原著相同或近似，彼此不得重名。
3. 名字必须像真实的中文专名，不能是机翻感、字母缩写或生僻字堆砌：
   · 角色名 2~4 字、以常见姓氏开头（沈砚、周小满、苏晚），亲属 / 同阵营的命名风格要协调；
   · 禁止任何复读：同一字连写三次（孟孟孟皇后）、同一词连写两次（慈懿慈懿慈懿太后）一律不许出现；
   · 禁止谐音梗 / 网络梗 / 搞笑名（邵刻薄、费纸鸢、郝浪、罗密），也不要用身份称呼代替姓名；
   · 势力名 2~10 字，道具功法名 2~10 字，各自成体系，不得只差一个字。
4. 只输出 JSON，不要解释，不要代码块围栏。"""

CARDS_TMPL = """改编要求：
__STYLE__

旧名→新名映射表（本批角色名、相关势力名必须从这里取，禁止临时另起名字）：
__MAP__

原著世界观（仅供理解人物功能，具体设定按改编要求重写）：
__BRIEF__

下面是原著角色卡第 __RANGE__ 批（全书共 __TOTAL__ 张，本批 __N__ 张）。请逐张改写为新题材下的角色卡，只输出一个 JSON 对象：
{"characters": [__CARD__]}

要求：
1. 必须输出且只输出 __N__ 张，顺序与输入一一对应；每张卡的字段一个都不能少，取值类型保持不变。
2. name 必须使用映射表中该角色的新名字；factionName / relationTo / relations / identity / personality / goal 等字段里出现的旧名，一律换成映射表里的新名，映射表没有的自创新名。
3. 身份、背景、性格、说话风格、动机按新题材与新基调重写，但该角色的叙事功能、定位、重要性保持不变；不得残留原著专有名词。
4. 只输出 JSON，不要解释，不要代码块围栏。

原著角色卡（JSON，逐条对应）：
__CHARS__"""

FACTIONS_TMPL = """改编要求：
__STYLE__

旧名→新名映射表（势力名、人物名必须从这里取，禁止临时另起名字）：
__MAP__

原著世界观（仅供理解势力功能，具体设定按改编要求重写）：
__BRIEF__

下面是原著势力卡第 __RANGE__ 批（全书共 __TOTAL__ 张，本批 __N__ 张）。请逐张改写为新题材下的势力卡，只输出一个 JSON 对象：
{"factions": [__FAC__]}

要求：
1. 必须输出且只输出 __N__ 张，顺序与输入一一对应；每张卡的字段一个都不能少。
2. name 必须使用映射表中该势力的新名字；relTo / relations / desc 等字段里出现的旧名，一律换成映射表里的新名，映射表没有的自创新名。
3. 性质、立场、与其他势力的关系按新题材与新基调重写，但该势力在故事里的功能、分量保持不变；不得残留原著专有名词。
4. 只输出 JSON，不要解释，不要代码块围栏。

原著势力卡（JSON，逐条对应）：
__FACS__"""

ITEMS_TMPL = """改编要求：
__STYLE__

旧名→新名映射表（道具功法名、人物名、势力名必须从这里取，禁止临时另起名字）：
__MAP__

原著世界观（仅供理解道具功能，具体设定按改编要求重写）：
__BRIEF__

下面是原著道具 / 功法卡第 __RANGE__ 批（全书共 __TOTAL__ 张，本批 __N__ 张）。请逐张改写为新题材下的道具 / 功法卡，只输出一个 JSON 对象：
{"items": [__ITEM__]}

要求：
1. 必须输出且只输出 __N__ 张，顺序与输入一一对应；每张卡的字段一个都不能少。
2. name 必须使用映射表中该道具 / 功法的新名字；owner / faction / effect / origin / desc 里出现的旧名，一律换成映射表里的新名。
3. kind 保持原类别（剧情道具 / 武学功法 / 战技 / 兵器 / 丹药 / 法宝 / 线索 / 其他）；grade 没有明确依据就留空，不要编等级。
4. 效果、来历、代价按新题材重写，但该道具在故事里的功能、出现时机保持不变；不得残留原著专有名词。
5. 名字必须像真实专名，禁止复读与谐音梗（如「孟孟孟令牌」「费纸鸢」）。
6. 只输出 JSON，不要解释，不要代码块围栏。

原著道具功法卡（JSON，逐条对应）：
__ITEM_LIST__"""

META_TMPL = """改编要求：
__STYLE__

新版角色一览（姓名｜定位｜身份摘要）：
__CAST__

新版势力一览（势力名｜类型）：
__FACTIONS__

原著梗概与设定库（结构参考，内容全部按新题材重写）：
梗概：__SUMMARY__

书级设定：
__BIBLE__

请写出新书的总纲，只输出一个 JSON 对象：
{
  "book_title": "新书书名，2~8 个字，贴合新题材、有网文感，不带书名号与标点",
  "book_summary": "新书梗概，300~500 字",
  "story_bible": __SB__,
  "opening": {
    "strategy": "开篇切入点策略，只能取：受辱反击 / 高能开场 / 反差日常 / 悬念倒叙",
    "first_image": "新书第一章开篇的第一个画面：一句话写清读者第一眼看到谁、在什么处境、正在做什么",
    "golden_finger_demo": "金手指第一次被实际使用的章号，如 3"
  }
}

要求：
1. book_title 必须是贴合新世界的全新书名，不得与原著书名相同或近似。
2. book_summary 300~500 字：写清新书主线、核心冲突与卖点，情节骨架与原著对应，但专有名词全部换新。
3. story_bible 字段一个都不能少，内容按新世界观改写；protagonist / supporting / antagonist 等字段必须使用上面给出的新版角色名，势力名同理，不得残留原著专有名词或定义。
4. 设定库要与新版角色卡、势力卡自洽：身份、性格、关系、势力立场保持一致，便于后续续写直接调用设定库、避免人设跑偏。
5. opening 按新书写：first_image 必须是第一章实际的开场画面（不写背景介绍），golden_finger_demo 填新书里金手指第一次实演的章号。
6. 只输出 JSON，不要解释，不要代码块围栏。

__CRAFT_BOOK__"""

TERMS_TMPL = """改编要求：
__STYLE__

新书梗概：
__SUMMARY__

新书已定角色 / 势力名（无需再映射，命名风格要与它们协调）：
__ROSTER__

下面是原著设定库里的地点 / 物品 / 功法 / 术语清单：
__TERMS__

请为这些专有名词起新名字，只输出一个 JSON 对象：
{"name_map": [{"old": "原著名词", "new": "新名字"}]}

要求：
1. 覆盖清单中的每一个独立名词（按 、 / ／ 分隔），同一名词只输出一次，old 与清单写法一致。
2. new 必须是全新名字，不得与原著相同或近似；地名、物品、功法各自成体系，风格统一。
3. 只输出 JSON，不要解释，不要代码块围栏。"""


CHAP_TMPL = """改编要求：
__STYLE__

旧名→新名映射表（JSON）：
__MAP__

新版角色名（roles 只能从这里选）：__CAST__
新版势力名（factions 只能从这里选）：__FACTS__

下面是原著第 __RANGE__ 章（全书共 __TOTAL__ 章）。请把每一章一一改写成新版本，只输出一个 JSON 对象：
{"chapters":[{"chapter":章号,"title":"新章题","summary":"新章摘要200~260字","key_events":["事件1","事件2","事件3","事件4","事件5"],"roles":["新版角色名"],"factions":["新版势力名"],"scene":"新版地点名"}]}
要求：
1. 必须输出且只输出 __N__ 章，chapter 章号与下面原著完全一致，不得增删或跳号。
2. 情节点与原著一一对应，但人名/地名/宗门/术语一律用映射表里的新名；映射表没有的，自创全新名字，禁止沿用原著原名。
3. key_events 3~5 条（只写原文有依据的要点，宁可少写不可编造）；summary 200~260 字，以「本章钩子：…」收尾，点出章末悬念。
4. title 2~12 字，写本章独有的具体事件 / 意象 / 反转；同一批输出里各章标题必须互不相同，
   不得照抄原著章题，也不要用「新的开始」「危机」「冲突」「意外」这类通用词。
5. 只输出 JSON，不要解释，不要代码块围栏。

__CRAFT_CHAPTER__

前面批次已经用过的章题（本次标题不得与它们相同）：
__USED__

原著章节（每行一个 JSON）：
__CHAPS__"""

PLAN_TMPL = """下面是一部已有小说的章节目录（每行：章号|章题|摘要前 80 字）。请为「改编后的新书」规划章节映射：新书共 __N__ 章（原著 __TOTAL__ 章；多于原著 = 拆分扩充原著情节，少于原著 = 合并压缩）。只输出一个 JSON 对象，结构严格如下：
{"plan":[{"new":1,"from":1,"to":1,"note":"该新章覆盖的原著情节范围"}]}
规则：
1. 必须恰好输出 __N__ 条，new 从 1 连续编号到 __N__。
2. from/to 为原著章号（from ≤ to）：压缩 = 一条新章覆盖原著多章（from~to）；扩写 = 多条新章覆盖同一原著章或相邻范围。
3. 原著第 1 到第 __TOTAL__ 章每一章都至少被一条新章覆盖；from 不递减（拆分时相邻新章可覆盖同一章），但不得跳段遗漏原著章节。
4. note 用一句话（≤40 字）说明该新章要写哪段情节。
5. 改编要求（最高优先级，情节取舍须服务于它）：
__STYLE__
6. 只输出 JSON，不要解释，不要代码块围栏。

__CRAFT_PLAN__

章节目录：
__INDEX__"""

MAP_TMPL = """改编要求：
__STYLE__

旧名→新名映射表（JSON）：
__MAP__

新版角色名（roles 只能从这里选）：__CAST__
新版势力名（factions 只能从这里选）：__FACTS__

下面是新书第 __RANGE__ 章的改编规划（每行：新章号 ← 原著章号范围 ｜ 情节说明）：
__PLAN__

对应原著章节（每行一个 JSON）：
__CHAPS__

前面批次已经用过的章题（本次新章标题不得与它们相同，也不得只差一两个字）：
__USED__

请严格按规划把对应原著章节改编成 __K__ 章新版章节，只输出一个 JSON 对象：
{"chapters":[{"chapter":新章号,"title":"新章题","summary":"新章摘要200~260字","key_events":["事件1","事件2","事件3","事件4","事件5"],"roles":["新版角色名"],"factions":["新版势力名"],"scene":"新版地点名"}]}
要求：
1. 必须输出且只输出 __K__ 章，chapter 为规划中的新章号（__NUMS__），不得增删或改号。
2. 覆盖同一原著范围的多条相邻新章：把该段情节合理拆分扩充（每章聚焦一段场景与因果，写细过程），前后衔接，不得重复叙述同一场景。
3. 一条新章合并原著多章：压缩保留主线冲突与结果，情节完整不跳跃。
4. 人名/地名/宗门/术语一律用映射表里的新名；映射表没有的，自创全新名字，禁止沿用原著原名。
5. key_events 3~5 条（只写原文有依据的要点，宁可少写不可编造）；summary 200~260 字，以「本章钩子：…」收尾，点出章末悬念。
6. title 2~12 字，写本章独有的具体事件 / 意象 / 反转；同一批输出里各章标题必须互不相同，
   不得照抄原著章题，也不要用「新的开始」「危机」「冲突」「意外」这类放到哪章都成立的通用词。
7. 只输出 JSON，不要解释，不要代码块围栏。

__CRAFT_MAP__"""

SEQUEL_TMPL = """改编要求：
__STYLE__

新版角色名（roles 只能从这里选）：__CAST__
新版势力名（factions 只能从这里选）：__FACTS__

新书梗概：
__SUMMARY__

下面是新书已改编完成的最后几章（每行一个 JSON），剧情已推进到这里：
__TAIL__

请在此基础上续写 __K__ 章全新剧情（章号 __FROM__~__TO__），只输出一个 JSON 对象：
{"chapters":[{"chapter":章号,"title":"章题","summary":"章摘要200~260字","key_events":["事件1","事件2","事件3","事件4","事件5"],"roles":["新版角色名"],"factions":["新版势力名"],"scene":"新版地点名","conflict":"本章核心冲突点","hook":"章末钩子","hook_type":"悬念/危机/反转/期待/信息差/情感 之一","emotion":"2~3 个情绪词用→连接，如 憋屈→怒→爽","tension":8,"payoff":"本章兑现的爽点，没有就空字符串","setup":"本章埋的铺垫，没有就空字符串"}]}
要求：
1. 必须输出且只输出 __K__ 章，chapter 从 __FROM__ 连续编号到 __TO__。
2. 原著素材已全部用完，剧情必须全部新创：承接上文未解决的悬念与人物状态，展开新的冲突与推进，不得复述已有章节情节。
3. 人名/地名/术语一律用新版名字，禁止沿用原著原名。
4. key_events 3~5 条（只写原文有依据的要点，宁可少写不可编造）；summary 200~260 字，以「本章钩子：…」收尾，点出章末悬念。
5. emotion / tension / payoff / setup 与拆解时的口径一致：情绪词只能取 憋屈/爽/燃/甜/虐/悬/恐/暖/怒/悲，tension 为 1~10 的峰值，
   payoff 写清谁得到了什么 / 谁被打脸，setup 写清埋了什么；纯过渡章可留空字符串，不要硬编。
6. title 2~12 字，写本章独有的具体事件 / 意象；各章标题互不相同，也不得与已用章题重复。
7. 只输出 JSON，不要解释，不要代码块围栏。

__CRAFT_SEQUEL__

已用章题（本次不得重复）：
__USED__"""


def _sb_schema():
    sb = ",\n".join(f'    "{k}": "{lb}"' for k, lb, _ in SB_FIELDS)
    return "{\n" + sb + "\n  }"


def _one(fields):
    return "{" + ", ".join(f'"{k}": "{lb}"' for k, lb, _ in fields) + "}"


def _safe_name(s):
    """书名字面清洗：去非法字符与书名号；空返回空串。"""
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", str(s or ""))
    s = s.strip().strip(".").strip("《》 　")
    return re.sub(r"\s+", "", s)[:30]


def _dedup(name, src_book):
    """新书名碰撞检测：与源书同名或 data/<名>/ 已有产出时加 _2、_3… 后缀。"""
    def taken(n):
        return n == src_book or os.path.isfile(book_decomposed(n)) or os.path.isfile(book_chapters(n))
    cand, i = name, 2
    while taken(cand):
        cand = f"{name}_{i}"
        i += 1
    return cand


def _items_from_bible(data):
    """旧版拆解没有 items 数组时的兜底：把设定库「关键道具」里的名词拆成占位卡，
    交给改编阶段重写成完整道具 / 功法卡（不覆盖已有 items）。"""
    raw = str((data.get("story_bible") or {}).get("items") or "")
    out, seen = [], set()
    for chunk in re.split(r"[、,，;；\n/|]", raw):
        name = clean_name(re.sub(r"[《》【】()（）]", "", chunk))
        if 2 <= len(name) <= 16 and name not in seen:
            seen.add(name)
            out.append({"name": name, "kind": "", "effect": "", "desc": ""})
    return out[:40]


def load_source(book):
    p = book_decomposed(book)
    if not os.path.isfile(p):
        sys.exit(f"[x] 源书「{book}」没有拆解产出（{p}）：请先运行拆解")
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    if not (data.get("chapters") or []):
        sys.exit(f"[x] 源书「{book}」的 decomposed.json 里没有章节数据")
    return data


def _bible_text(data):
    sb = data.get("story_bible") or {}
    return "\n".join(f"{k}：{sb.get(k, '')}" for k, _, _ in SB_FIELDS
                     if str(sb.get(k, "")).strip()) or "（无）"


def _roster_cards(cards, n=50):
    rows = []
    for c in cards:
        name = str(c.get("name") or "").strip()
        if name:
            rows.append(f"{name}｜{c.get('role', '')}｜{str(c.get('identity') or '')[:n]}")
    return "\n".join(rows) or "（无）"


def _roster_factions(facs, n=40):
    rows = []
    for f in facs:
        name = str(f.get("name") or "").strip()
        if name:
            rows.append(f"{name}｜{f.get('category', '')}｜{str(f.get('desc') or '')[:n]}")
    return "\n".join(rows) or "（无）"


def _roster_items(items, n=30):
    rows = []
    for it in items:
        name = str(it.get("name") or "").strip()
        if name:
            rows.append(f"{name}｜{it.get('kind', '')}｜{str(it.get('effect') or it.get('desc') or '')[:n]}")
    return "\n".join(rows) or "（无）"


def build_naming_prompt(chars, facs, items, data, style):
    return (_prompt("adapt.naming", NAMING_TMPL)
            .replace("__STYLE__", style)
            .replace("__SUMMARY__", str(data.get("book_summary") or "（无）"))
            .replace("__CAST__", _roster_cards(chars))
            .replace("__FACTIONS__", _roster_factions(facs))
            .replace("__ITEMS__", _roster_items(items))
            .replace("__N__", str(len(chars) + len(facs) + len(items))))


def build_cards_prompt(batch, data, style, name_map, rng, total):
    return (_prompt("adapt.cards", CARDS_TMPL)
            .replace("__STYLE__", style)
            .replace("__MAP__", json.dumps(name_map, ensure_ascii=False))
            .replace("__BRIEF__", _bible_text(data))
            .replace("__RANGE__", rng)
            .replace("__TOTAL__", str(total))
            .replace("__N__", str(len(batch)))
            .replace("__CARD__", _one(CARD_FIELDS))
            .replace("__CHARS__", json.dumps(batch, ensure_ascii=False)))


def build_factions_prompt(batch, data, style, name_map, rng, total):
    return (_prompt("adapt.factions", FACTIONS_TMPL)
            .replace("__STYLE__", style)
            .replace("__MAP__", json.dumps(name_map, ensure_ascii=False))
            .replace("__BRIEF__", _bible_text(data))
            .replace("__RANGE__", rng)
            .replace("__TOTAL__", str(total))
            .replace("__N__", str(len(batch)))
            .replace("__FAC__", _one(FACTION_FIELDS))
            .replace("__FACS__", json.dumps(batch, ensure_ascii=False)))


def build_items_prompt(batch, data, style, name_map, rng, total):
    return (_prompt("adapt.items", ITEMS_TMPL)
            .replace("__STYLE__", style)
            .replace("__MAP__", json.dumps(name_map, ensure_ascii=False))
            .replace("__BRIEF__", _bible_text(data))
            .replace("__RANGE__", rng)
            .replace("__TOTAL__", str(total))
            .replace("__N__", str(len(batch)))
            .replace("__ITEM__", _one(ITEM_FIELDS))
            .replace("__ITEM_LIST__", json.dumps(batch, ensure_ascii=False)))


def build_meta_prompt(data, style, cards, facs):
    cast = "\n".join(f"{c.get('name', '')}｜{c.get('role', '')}｜{str(c.get('identity') or '')[:40]}"
                     for c in cards if str(c.get("name") or "").strip()) or "（无）"
    facts = "\n".join(f"{f.get('name', '')}｜{f.get('category', '')}"
                      for f in facs if str(f.get("name") or "").strip()) or "（无）"
    return (_prompt("adapt.meta", META_TMPL)
            .replace("__STYLE__", style)
            .replace("__CAST__", cast)
            .replace("__FACTIONS__", facts)
            .replace("__SUMMARY__", str(data.get("book_summary") or "（无）"))
            .replace("__BIBLE__", _bible_text(data))
            .replace("__SB__", _sb_schema())
            .replace("__CRAFT_BOOK__", _craft("book")))


def build_terms_prompt(data, style, summary, cards, facs):
    sb = data.get("story_bible") or {}
    terms = [f"{lb}：{str(sb.get(k) or '').strip()}"
             for k, lb in (("places", "地点"), ("items", "物品 / 功法"), ("terms", "术语 / 制度"))
             if str(sb.get(k) or "").strip()]
    roster = "、".join([str(c.get("name") or "").strip() for c in cards
                       if str(c.get("name") or "").strip()]
                      + [str(f.get("name") or "").strip() for f in facs
                         if str(f.get("name") or "").strip()]) or "（无）"
    return (_prompt("adapt.terms", TERMS_TMPL)
            .replace("__STYLE__", style)
            .replace("__SUMMARY__", summary or "（无）")
            .replace("__ROSTER__", roster)
            .replace("__TERMS__", "\n".join(terms) or "（无）"))


def _map_pairs(name_map):
    pairs = [(str(m.get("old") or "").strip(), str(m.get("new") or "").strip())
             for m in (name_map or []) if isinstance(m, dict)
             and str(m.get("old") or "").strip() and str(m.get("new") or "").strip()]
    pairs.sort(key=lambda p: -len(p[0]))
    return pairs


def merge_name_map(entries):
    """按 old 去重（后出现的覆盖先出现的），返回 [{old,new}]。"""
    out = {}
    for old, new in _map_pairs(entries):
        if old != new:
            out[old] = new
    return [{"old": k, "new": v} for k, v in out.items()]


def _align_rewritten(got, src):
    """模型返回的卡按位置对齐原著：少了用原著条目兜底（后续按映射表改名），多了截断。
    单张卡里漏掉的字段也用原著值补齐——否则该字段会以空值落盘，页面回显就是空白。"""
    got = [g for g in (got or []) if isinstance(g, dict)]
    if len(got) != len(src):
        print(f"    [!] 返回 {len(got)} 条 ≠ 预期 {len(src)} 条，按位置对齐")
    out = []
    for i in range(len(src)):
        card = dict(src[i])
        if i < len(got):
            card.update(got[i])
        out.append(card)
    return out


def apply_name_map_all(items, name_map):
    """把映射表套到卡片的全部字符串字段（姓名 / 势力归属 / 关系对象 / 简介）。
    分批改写时模型看不到其他批次，跨批引用容易残留旧名，这里兜底换掉。"""
    pairs = _map_pairs(name_map)
    if not pairs:
        return
    for it in items:
        for k, v in list(it.items()):
            if not isinstance(v, str):
                continue
            nv = v
            for old, new in pairs:
                if old in nv:
                    nv = nv.replace(old, new)
            if nv != v:
                it[k] = nv


def _cast_facts(book):
    """新版角色名/势力名清单（章节类 prompt 共用）。"""
    cast = "、".join(str(c.get("name") or "").strip() for c in (book.get("characters") or [])
                     if str(c.get("name") or "").strip()) or "（无）"
    facts = "、".join(str(f.get("name") or "").strip() for f in (book.get("factions") or [])
                      if str(f.get("name") or "").strip()) or "（无）"
    return cast, facts


def _compact(ch):
    keys = ("chapter", "title", "summary", "key_events", "roles", "factions", "items", "scene")
    return json.dumps({k: ch.get(k) for k in keys}, ensure_ascii=False)


def proportional_plan(total_src, n):
    """模型规划不合规时的兜底：原著按位置均匀摊到 n 条新章（扩写=重复覆盖，压缩=合并覆盖）。"""
    plan = []
    for i in range(n):
        a = i * total_src // n + 1
        b = min(max((i + 1) * total_src // n, a), total_src)
        plan.append({"new": i + 1, "from": a, "to": b, "note": "按比例映射"})
    return plan


def validate_plan(plan, n, total_src):
    """校验模型章数规划：条数、from≤to、不回跳、完整覆盖原著 1~total_src；返回规范化计划或 None。"""
    if not isinstance(plan, list) or len(plan) != n:
        return None
    norm, covered, prev = [], set(), 0
    for i, p in enumerate(plan, 1):
        if not isinstance(p, dict):
            return None
        try:
            a, b = int(p.get("from")), int(p.get("to"))
        except (TypeError, ValueError):
            return None
        if a < 1 or b > total_src or a > b or a < prev:
            return None
        norm.append({"new": i, "from": a, "to": b, "note": str(p.get("note") or "")[:60]})
        covered.update(range(a, b + 1))
        prev = a
    return norm if covered == set(range(1, total_src + 1)) else None


def build_plan_prompt(chapters, style, target):
    idx = "\n".join(f"{i}|{c.get('title', '')}|{str(c.get('summary') or '')[:80]}"
                    for i, c in enumerate(chapters, 1))
    return (_prompt("adapt.plan", PLAN_TMPL)
            .replace("__N__", str(target))
            .replace("__TOTAL__", str(len(chapters)))
            .replace("__STYLE__", style)
            .replace("__INDEX__", idx)
            .replace("__CRAFT_PLAN__", _craft("plan")))


def plan_batches(plan):
    """映射计划切段：每段新章数 ≤ MAP_NEW_PER_CALL，且覆盖源章总量控制在 CHAPTERS_PER_CALL 上下
    （超限后闭合，避免压缩改编时单段 prompt 吞入过多源章节）。"""
    batches, cur = [], []
    for p in plan:
        if cur and (len(cur) >= MAP_NEW_PER_CALL or
                    cur[-1]["to"] - cur[0]["from"] + 1 > CHAPTERS_PER_CALL):
            batches.append(cur)
            cur = []
        cur.append(p)
    if cur:
        batches.append(cur)
    return batches


def build_map_prompt(batch, chapters, book, style, name_map, used_titles=None):
    """batch：规范化计划的连续切片；chapters：按位置 1..n 的源书章节列表。
    used_titles：前面批次已生成的章题，喂给模型避免撞标题。"""
    cast, facts = _cast_facts(book)
    a = min(p["from"] for p in batch)
    b = max(p["to"] for p in batch)
    seg = chapters[a - 1:b]
    plan_lines = "\n".join(
        f"新第{p['new']}章 ← 原著第{p['from']}~{p['to']}章" + (f" ｜ {p['note']}" if p["note"] else "")
        for p in batch)
    return (_prompt("adapt.map", MAP_TMPL)
            .replace("__RANGE__", f"{batch[0]['new']}~{batch[-1]['new']}")
            .replace("__K__", str(len(batch)))
            .replace("__NUMS__", ",".join(str(p["new"]) for p in batch))
            .replace("__STYLE__", style)
            .replace("__MAP__", json.dumps(name_map, ensure_ascii=False))
            .replace("__CAST__", cast)
            .replace("__FACTS__", facts)
            .replace("__PLAN__", plan_lines)
            .replace("__USED__", _used_block(used_titles))
            .replace("__CHAPS__", "\n".join(_compact(c) for c in seg))
            .replace("__CRAFT_MAP__", _craft("chapter")))


def build_sequel_prompt(tail, book, style, k, start, used_titles=None):
    cast, facts = _cast_facts(book)
    return (_prompt("adapt.sequel", SEQUEL_TMPL)
            .replace("__STYLE__", style)
            .replace("__CAST__", cast)
            .replace("__FACTS__", facts)
            .replace("__SUMMARY__", str(book.get("book_summary") or "（无）"))
            .replace("__TAIL__", "\n".join(_compact(c) for c in tail))
            .replace("__USED__", _used_block(used_titles))
            .replace("__K__", str(k))
            .replace("__FROM__", str(start))
            .replace("__TO__", str(start + k - 1))
            .replace("__CRAFT_SEQUEL__", _craft("sequel")))


def fix_by_position(got, expect_n, nums):
    """章数/章号对齐：数量不符时截断并告警，章号按位置重编。"""
    if len(got) != expect_n:
        print(f"    [!] 返回 {len(got)} 章 ≠ 预期 {expect_n} 章，按位置对齐")
    out = got[:expect_n]
    for i, c in enumerate(out):
        c["chapter"] = nums[i]
    return out


def build_chap_prompt(seg, book, style, name_map, rng, total, used_titles=None):
    cast, facts = _cast_facts(book)
    lines = [_compact(c) for c in seg]
    return (_prompt("adapt.chapters", CHAP_TMPL)
            .replace("__RANGE__", rng)
            .replace("__TOTAL__", str(total))
            .replace("__N__", str(len(seg)))
            .replace("__STYLE__", style)
            .replace("__MAP__", json.dumps(name_map, ensure_ascii=False))
            .replace("__CAST__", cast)
            .replace("__FACTS__", facts)
            .replace("__USED__", _used_block(used_titles))
            .replace("__CHAPS__", "\n".join(lines))
            .replace("__CRAFT_CHAPTER__", _craft("chapter")))


def fix_chapters(got, seg):
    """章数/章号对齐：按位置重编为原著章号；数量不符时截断并告警。"""
    nums = [c.get("chapter", i) for i, c in enumerate(seg, 1)]
    return fix_by_position(got, len(seg), nums)


def _die_truncated(e):
    """单章都写不完时的统一退出：落盘原始输出 + 给出可执行的出路（别再提示 --chunk-chars，那是拆解参数）。"""
    bad = os.path.join(DATA_DIR, "decomposed.raw.txt")
    try:
        with open(bad, "w", encoding="utf-8") as f:
            f.write(getattr(e, "raw", "") or "")
    except OSError:
        pass
    sys.exit(f"[x] 章节改编输出反复被截断（对半拆到单章也写不完）：{e}\n"
             "    这通常是推理型模型把输出预算烧在了思维链上——请改用非推理模型重试"
             f"（原始输出已存到 {bad}）")


def _halve(items):
    mid = max(1, len(items) // 2)
    return items[:mid], items[mid:]


def _chap_segments(seg, book, style, name_map, total_src, used_titles,
                   api_key, base_url, model, tag):
    """一段章节改编：输出被截断时自动对半拆段重跑（推理型模型会把输出预算烧在思考上）。
    used_titles 跨半段共享：先跑完的一半标题会喂给后一半，避免撞标题。"""
    rng = f"{seg[0].get('chapter')}~{seg[-1].get('chapter')}"
    try:
        res = _call(build_chap_prompt(seg, book, style, name_map, rng, total_src, used_titles),
                        api_key, base_url, model, tag=tag, allow_truncated=True)
        return fix_chapters(res.get("chapters") or [], seg)
    except OutputTruncated as e:
        if len(seg) <= 1:
            _die_truncated(e)
        a, b = _halve(seg)
        print(f"    [!] 第{rng}章输出被截断：对半拆成 {len(a)}+{len(b)} 章两段重试")
        got = _chap_segments(a, book, style, name_map, total_src, used_titles,
                             api_key, base_url, model, tag)
        used_titles.extend(c.get("title") for c in got if c.get("title"))
        return got + _chap_segments(b, book, style, name_map, total_src, used_titles,
                                    api_key, base_url, model, tag)


def _map_segments(batch, chapters, book, style, name_map, used_titles,
                  api_key, base_url, model, tag):
    """一段映射改编：输出被截断时按规划条目对半拆段重跑。"""
    try:
        res = _call(build_map_prompt(batch, chapters, book, style, name_map, used_titles),
                        api_key, base_url, model, tag=tag, allow_truncated=True)
        return fix_by_position(res.get("chapters") or [], len(batch), [p["new"] for p in batch])
    except OutputTruncated as e:
        if len(batch) <= 1:
            _die_truncated(e)
        a, b = _halve(batch)
        print(f"    [!] 新第{batch[0]['new']}~{batch[-1]['new']}章输出被截断："
              f"对半拆成 {len(a)}+{len(b)} 条规划重试")
        got = _map_segments(a, chapters, book, style, name_map, used_titles,
                            api_key, base_url, model, tag)
        used_titles.extend(c.get("title") for c in got if c.get("title"))
        return got + _map_segments(b, chapters, book, style, name_map, used_titles,
                                   api_key, base_url, model, tag)


def _sequel_segments(tail, book, style, k, start, used_titles, api_key, base_url, model, tag):
    """一段续写：输出被截断时按章数对半拆段重跑；后半段以前半段结果为衔接上文。"""
    try:
        res = _call(build_sequel_prompt(tail, book, style, k, start, used_titles),
                        api_key, base_url, model, tag=tag, allow_truncated=True)
        return fix_by_position(res.get("chapters") or [], k, list(range(start, start + k)))
    except OutputTruncated as e:
        if k <= 1:
            _die_truncated(e)
        k1, k2 = k // 2, k - k // 2
        print(f"    [!] 续写 {k} 章输出被截断：拆成 {k1}+{k2} 章两段重试")
        got = _sequel_segments(tail, book, style, k1, start, used_titles,
                               api_key, base_url, model, tag)
        used_titles.extend(c.get("title") for c in got if c.get("title"))
        tail2 = (list(tail) + got)[-3:]
        return got + _sequel_segments(tail2, book, style, k2, start + k1, used_titles,
                                      api_key, base_url, model, tag)


def _used_block(used):
    """已用章题清单（喂给后续批次，减少重复标题）。"""
    used = [str(t).strip() for t in (used or []) if str(t or "").strip()]
    return "、".join(used) if used else "（无）"


def dedupe_titles(chapters):
    """章题兜底去重：分批改编时模型看不到别的批次，仍可能撞标题。
    重复的用本章第一条关键事件补区分词；没有事件就退回章号，保证目录里不出现同名章。"""
    seen = set()
    for c in chapters:
        t = str(c.get("title") or "").strip()
        no = c.get("chapter")
        if not t:
            t = f"第{no}章" if no else "未命名"
        if t in seen:
            suffix = ""
            for e in (c.get("key_events") or c.get("points") or []):
                e = re.sub(r"[\s，。；、,.!?！？：:　]", "", str(e or ""))
                if len(e) >= 2:
                    suffix = e[:8]
                    break
            base = f"{t}·{suffix}" if suffix else t
            cand, n = base, 2
            while cand in seen:
                cand = f"{base}{n}" if suffix else f"{t}（{no or n}）"
                n += 1
            t = cand[:24]
        c["title"] = t
        seen.add(t)
    return chapters


def apply_name_map(chapters, name_map):
    """兜底：模型漏改的旧名按映射表替换（roles/factions 整项换，标题/摘要/场景子串换）。"""
    pairs = [(str(m.get("old") or "").strip(), str(m.get("new") or "").strip())
             for m in name_map if m.get("old") and m.get("new")]
    if not pairs:
        return
    # 长名先替换，避免「陈实」先命中把「陈实之」改坏
    pairs.sort(key=lambda p: -len(p[0]))
    hits = 0
    for ch in chapters:
        for k in ("title", "summary", "scene", "conflict", "hook", "payoff", "setup"):
            v = str(ch.get(k) or "")
            nv = v
            for old, new in pairs:
                if old in nv:
                    nv = nv.replace(old, new)
            if nv != v:
                hits += 1
                ch[k] = nv
        # points（关键事件）会直接作为扩写的分拍依据，必须同步换名，否则正文会把旧名写回去
        pts = ch.get("points")
        if isinstance(pts, list):
            npts = []
            for p in pts:
                s = str(p)
                for old, new in pairs:
                    if old in s:
                        s = s.replace(old, new)
                npts.append(s)
            if npts != [str(p) for p in pts]:
                hits += 1
                ch["points"] = npts
        for k in ("roles", "factions", "items"):
            ch[k] = [next((new for old, new in pairs if str(x).strip() == old), x)
                     for x in (ch.get(k) or [])]
    if hits:
        print(f"[i] 兜底替换：{hits} 个字段残留旧名，已按映射表换成新名")


def _inherit_chapter_meta(got, source_groups):
    """把原著章节的冲突 / 钩子 / 情绪流继承到改编章。

    改编 prompt 只要求模型改写 title/summary/key_events/roles/factions/scene 六件事，
    冲突、钩子类型、情绪主线、峰值、兑现、铺垫这些「写法诊断」不在其中；不继承的话，
    新书 chapters.json 里这些字段全是空，页面回显与签约体检都会缺一大块。
    一条新章覆盖多章原著时：冲突/钩子/类型/情绪/兑现取最后一条（收口那一章），
    峰值取最高，铺垫取最早一条——与本地改编的口径一致。
    """
    for ch, seg in zip(got, source_groups):
        if not isinstance(ch, dict) or not seg:
            continue
        last = seg[-1]
        for k in ("conflict", "hook", "hook_type", "emotion", "payoff"):
            if not str(ch.get(k) or "").strip():
                v = str(last.get(k) or "").strip()
                if v:
                    ch[k] = v
        if not str(ch.get("tension") or "").strip():
            nums = [int(m.group(0)) for c in seg
                    for m in [re.search(r"\d+", str(c.get("tension") or ""))] if m]
            if nums:
                ch["tension"] = max(nums)
        if not str(ch.get("setup") or "").strip():
            ch["setup"] = next((str(c.get("setup") or "").strip() for c in seg
                                if str(c.get("setup") or "").strip()), "")
        # 道具功法：模型没写就继承原著对应章的清单，随后由 apply_name_map 换成新名
        if not ch.get("items"):
            picked = []
            for c in seg:
                for x in (c.get("items") or c.get("key_items") or []):
                    x = str(x).strip()
                    if x and x not in picked:
                        picked.append(x)
            if picked:
                ch["items"] = picked[:6]


def local_adapt(data, target, sequel):
    """无 Key 时的本地改编：不换名、不换题材（那需要创作），只把「章数映射 + 骨架」定下来。

    产出与 AI 版完全同构（decomposed.json / chapters.json），新章的标题、摘要、人物
    都指回原著对应章，页面可直接改；配了 Key 后再跑一次就是正式改编，不会白做。
    """
    chapters = data.get("chapters") or []
    total_src = len(chapters)
    if target != total_src:
        plan = proportional_plan(total_src, target)
    else:
        plan = [{"new": i + 1, "from": i + 1, "to": i + 1} for i in range(total_src)]
    new_ch = []
    seen_src = {}
    for p in plan:
        seg = chapters[max(0, p["from"] - 1):p["to"]] or [{}]
        first, last = seg[0], seg[-1]
        title = first.get("title") or f"第{p['new']}章"
        if len(seg) > 1:
            tail_title = last.get("title") or ""
            if tail_title and tail_title != title:
                title = f"{title}～{tail_title}"
        # target > 源书时一个源章会被拆成多章：本地无法扩写，标注清楚免得误解
        dup = seen_src.get(p["from"], 0)
        seen_src[p["from"]] = dup + 1
        summary = " ".join((c.get("summary") or "") for c in seg)
        if dup:
            title = f"{title}（拆分{dup + 1}·待扩写）"
            summary = "【本地模式：本章由原著同一章拆分而来，待配 Key 后由模型扩写】" + summary
        roles = []
        for c in seg:
            for r in (c.get("roles") or []):
                if r and r not in roles:
                    roles.append(r)
        scenes = [c.get("scene") for c in seg if c.get("scene")]
        new_ch.append({
            "chapter": p["new"],
            "title": title[:40],
            "summary": summary[:260],
            "key_events": [e for c in seg for e in (c.get("key_events") or [])][:4],
            "roles": roles[:6],
            "factions": [],
            "scene": scenes[0] if scenes else "",
            "conflict": last.get("conflict", "") or "",
            "hook": last.get("hook", "") or "",
            # 情绪流：一段多章合成一章时，铺垫取最早的，情绪/峰值/兑现/钩子取最后一条（那是这一段的收口）
            "hook_type": last.get("hook_type", "") or "",
            "emotion": last.get("emotion", "") or "",
            "tension": max([c.get("tension") or 0 for c in seg] or [0]),
            "payoff": last.get("payoff", "") or "",
            "setup": (seg[0].get("setup", "") if seg else "") or "",
            "adapted_from": f"{p['from']}-{p['to']}",
        })
    for k in range(sequel):
        no = target + k + 1
        new_ch.append({
            "chapter": no,
            "title": f"（续写占位）第{no}章",
            "summary": "本地模式无法生成新剧情：此章为占位，配置 API Key 后可让模型续写。",
            "key_events": [], "roles": [], "factions": [],
            "scene": "", "conflict": "", "hook": "",
            "hook_type": "", "emotion": "", "tension": 0, "payoff": "", "setup": "",
        })
    return {
        "book_summary": (data.get("book_summary") or "")[:400],
        "story_bible": dict(data.get("story_bible") or {}),
        # 本地模式不换世界观，开篇诊断沿用原著（章号也会按映射重排，这里只做占位）
        "opening": data.get("opening") or {},
        "characters": list(data.get("characters") or []),
        "factions": list(data.get("factions") or []),
        "items": list(data.get("items") or []),
        "chapters": new_ch,
        "mode": "local",
    }


def _write_outputs(decomposed, out_book, extra=""):
    """落盘新书的 decomposed.json / chapters.json——AI 与本地两条路径共用。"""
    # 落盘前统一清洗复读名 / 合并重复卡 / 同步章节引用
    from entities import sync_document
    view = {"characters": decomposed.get("characters") or [],
            "factions": decomposed.get("factions") or [],
            "items": decomposed.get("items") or [],
            "chapters": decomposed.get("chapters") or []}
    sync_document(view)
    decomposed.update(view)
    new_ch = decomposed.get("chapters") or []
    n_card = len(decomposed.get("characters") or [])
    n_fac = len(decomposed.get("factions") or [])
    n_item = len(decomposed.get("items") or [])
    out_dec = book_decomposed(out_book)
    os.makedirs(os.path.dirname(out_dec), exist_ok=True)
    with open(out_dec, "w", encoding="utf-8") as f:
        json.dump(decomposed, f, ensure_ascii=False, indent=2)
    print(f"[完成] 已写出 {out_dec}（《{out_book}》：{len(new_ch)} 章{extra} / "
          f"{n_card} 个角色 / {n_fac} 个势力 / {n_item} 件道具功法）")

    ch_json = to_chapters_json(decomposed)
    out_ch = book_chapters(out_book)
    os.makedirs(os.path.dirname(out_ch), exist_ok=True)
    with open(out_ch, "w", encoding="utf-8") as f:
        json.dump(ch_json, f, ensure_ascii=False, indent=2)
    print(f"      已写出 {out_ch}（可在「全书设定 / 章节数据」页直接编辑，无需再拆解）")


def write_adapt_report(out_book, src_book, mode, style, source_chapters, output_chapters,
                       target_chapters, sequel_chapters, name_map):
    """落盘《改编差异报告》：只统计结构、命名与 AI 参与情况，不做相似度结论。

    它解决的是「用户拿什么证明自己做了多少改造」的问题：发布前人工复核清单、
    改名数量、章数变化都写清楚；真正的查重/法律判断仍需外部工具与律师。
    """
    pairs = [{"old": str(m.get("old") or ""), "new": str(m.get("new") or "")}
             for m in (name_map or []) if isinstance(m, dict) and m.get("old")]
    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source_book": src_book,
        "output_book": out_book,
        "mode": mode,
        "style": style,
        "source_chapters": source_chapters,
        "output_chapters": output_chapters,
        "target_chapters": target_chapters,
        "sequel_chapters": sequel_chapters,
        "renamed_terms": len(pairs),
        "name_map_sample": pairs[:30],
        "ai_assisted": mode == "ai",
        "aigc_disclosure": "本作品由墨写 AI 工作台辅助改编；发布前请人工改写关键情节与语句，并按发布平台要求披露 AI 参与程度。",
        "notice": "本报告只统计结构与命名变化，不是查重报告，也不构成法律意见；相似度判断请使用专业查重/律师意见。",
        "human_review_checklist": [
            "逐章核对人物动机与关键选择，确保不是原文换名",
            "至少重写主线冲突的解决方式与 30% 以上具体情节",
            "检查地名、门派、物品、功法等专有名词是否全部替换",
            "检查章节标题、开篇与章末钩子是否已重新创作",
            "按平台要求补充 AI 参与程度说明，并保留人工修改记录",
        ],
    }
    path = os.path.join(book_dir(out_book), "adapt_report.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[合规] 改编差异报告：data/{out_book}/adapt_report.json"
          f"（改名 {len(pairs)} 项 · {source_chapters} 章 → {output_chapters} 章）")
    return report


def _rewrite_book_batch(kind, batch, data, style, name_map, rng, total, api_key, base_url, model):
    """单批角色卡 / 势力卡 / 道具功法卡改写（供线程池并发调用）。返回对齐后的新卡片列表。

    4 路并发下偶发 429：这里对限流做一次退避重试（其它错误直接抛，交给上层中止）。
    """
    for attempt in range(3):
        try:
            if kind == "char":
                res = _call(build_cards_prompt(batch, data, style, name_map, rng, total),
                                api_key, base_url, model, tag=f"[角色卡{rng}] ", hint=_BOOK_TRUNC_HINT)
                return _align_rewritten(res.get("characters"), batch)
            if kind == "item":
                res = _call(build_items_prompt(batch, data, style, name_map, rng, total),
                                api_key, base_url, model, tag=f"[道具功法{rng}] ", hint=_BOOK_TRUNC_HINT)
                return _align_rewritten(res.get("items"), batch)
            res = _call(build_factions_prompt(batch, data, style, name_map, rng, total),
                            api_key, base_url, model, tag=f"[势力卡{rng}] ", hint=_BOOK_TRUNC_HINT)
            return _align_rewritten(res.get("factions"), batch)
        except Exception as e:  # noqa
            msg = str(e).lower()
            limited = ("429" in msg or "rate limit" in msg or "too many requests" in msg)
            if not limited or attempt >= 2:
                raise
            wait = 1.5 * (attempt + 1)
            print(f"    [!] 并发请求被限流，{wait:.1f}s 后重试：{str(e)[:120]}")
            time.sleep(wait)


def _rewrite_roster(src_chars, src_facs, src_items, data, style, name_map, api_key, base_url, model,
                    concurrency=BOOK_CALL_CONCURRENCY):
    """角色卡 / 势力卡 / 道具功法卡分批并发改写：统一命名确定后各批互不依赖，按 4 路并发。

    返回 (new_chars, new_facs, new_items, pairs)：顺序与源列表一致；pairs 是模型实际改出的新名字
    （章节改编与跨批引用都靠它对齐）。任一批失败会等其余批次收尾后抛第一个异常，
    不吞错、不写半成品。
    """
    jobs = []
    for i in range(0, len(src_chars), BOOK_CARDS_PER_CALL):
        batch = src_chars[i:i + BOOK_CARDS_PER_CALL]
        jobs.append(("char", i, batch, f"{i + 1}~{i + len(batch)}"))
    for i in range(0, len(src_facs), BOOK_FACTIONS_PER_CALL):
        batch = src_facs[i:i + BOOK_FACTIONS_PER_CALL]
        jobs.append(("fac", i, batch, f"{i + 1}~{i + len(batch)}"))
    for i in range(0, len(src_items), BOOK_ITEMS_PER_CALL):
        batch = src_items[i:i + BOOK_ITEMS_PER_CALL]
        jobs.append(("item", i, batch, f"{i + 1}~{i + len(batch)}"))
    if not jobs:
        return [], [], [], []
    results, errors = {}, []
    with ThreadPoolExecutor(max_workers=max(1, min(concurrency, len(jobs))),
                            thread_name_prefix="adapt-book") as ex:
        futs = {
            ex.submit(_rewrite_book_batch, kind, batch, data, style, name_map, rng,
                      {"char": len(src_chars), "fac": len(src_facs),
                       "item": len(src_items)}[kind],
                      api_key, base_url, model): (kind, i, rng)
            for kind, i, batch, rng in jobs
        }
        for fut in as_completed(futs):
            kind, i, rng = futs[fut]
            try:
                got = fut.result()
            except Exception as e:  # noqa —— 先收齐其余批次，再统一抛出
                errors.append(e)
                continue
            results[(kind, i)] = got
            label = {"char": "角色卡", "fac": "势力卡", "item": "道具功法"}[kind]
            print(f"    [✓] {label} {rng}：{len(got)} 张")
    if errors:
        raise errors[0]
    new_chars, new_facs, new_items = [], [], []
    for k in sorted(results):                 # 按 (kind, 批次起点) 还原原顺序并展平
        bucket = {"char": new_chars, "fac": new_facs, "item": new_items}[k[0]]
        bucket.extend(results[k])
    pairs = []
    for src_list, got_list in ((src_chars, new_chars), (src_facs, new_facs), (src_items, new_items)):
        for src, item in zip(src_list, got_list):
            old = str(src.get("name") or "").strip()
            new = str(item.get("name") or "").strip()
            if old and new and old != new:
                pairs.append({"old": old, "new": new})
    return new_chars, new_facs, new_items, pairs


def main():
    ap = argparse.ArgumentParser(description="去抄袭改编：基于拆解产出换新题材与命名，直接生成新书数据")
    ap.add_argument("--book", required=True, help="源书名（data/<书名>/ 需已有 decomposed.json）")
    ap.add_argument("--out-book", default="", help="新书名（留空 = 由模型生成书名，完成后在页面确认）")
    ap.add_argument("--style", default="", help="改编要求：题材/文风/基调/命名风格")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--base-url", default=None, help="默认读环境变量 DEEPSEEK_BASE_URL")
    ap.add_argument("--api-key", default=None, help="默认读环境变量 DEEPSEEK_API_KEY")
    ap.add_argument("--target-chapters", type=int, default=0,
                    help="新书目标章数（0 = 与源书一致；大于源书 = 扩写，小于源书 = 压缩合并）")
    ap.add_argument("--sequel-chapters", type=int, default=0,
                    help="在原著结局后续写的章数（0 = 不续写），章号接在目标章数之后")
    ap.add_argument("--dry-run", action="store_true", help="只统计调用规模，不调 API")
    ap.add_argument("--local", action="store_true",
                    help="强制本地改编骨架（不调用模型）；未配置 Key 时自动启用")
    args = ap.parse_args()

    if args.target_chapters < 0 or args.sequel_chapters < 0:
        sys.exit("[x] --target-chapters / --sequel-chapters 不能为负数（0 = 不启用）")
    if args.out_book and args.out_book == args.book:
        sys.exit("[x] 新书名不能与源书名相同（会覆盖拆解产出）")
    data = load_source(args.book)
    chapters = data.get("chapters") or []
    total_src = len(chapters)
    target = args.target_chapters if args.target_chapters > 0 else total_src
    sequel = args.sequel_chapters if args.sequel_chapters > 0 else 0
    mapping = target != total_src
    style = args.style.strip() or DEFAULT_STYLE
    if mapping or sequel:
        override = f"（章数覆盖：新书把原著 {total_src} 章改编为 {target} 章"
        if sequel:
            override += f"，另续写 {sequel} 章全新剧情"
        override += f"，共 {target + sequel} 章；「章数保持不变」一类要求以本条为准）"
        style += override
    base_url = resolve_base_url(args.base_url)
    segs = [chapters[i:i + CHAPTERS_PER_CALL] for i in range(0, total_src, CHAPTERS_PER_CALL)]
    plan_calls = 1 if mapping else 0
    chap_calls = (len(segs) if not mapping else
                  max((target + MAP_NEW_PER_CALL - 1) // MAP_NEW_PER_CALL,
                      (total_src + CHAPTERS_PER_CALL - 1) // CHAPTERS_PER_CALL))
    seq_calls = (sequel + SEQUEL_PER_CALL - 1) // SEQUEL_PER_CALL if sequel else 0
    src_chars = [c for c in (data.get("characters") or []) if isinstance(c, dict)]
    src_facs = [f for f in (data.get("factions") or []) if isinstance(f, dict)]
    src_items = [it for it in (data.get("items") or []) if isinstance(it, dict)]
    if not src_items:
        src_items = _items_from_bible(data)
    card_calls = (len(src_chars) + BOOK_CARDS_PER_CALL - 1) // BOOK_CARDS_PER_CALL
    fac_calls = (len(src_facs) + BOOK_FACTIONS_PER_CALL - 1) // BOOK_FACTIONS_PER_CALL
    item_calls = (len(src_items) + BOOK_ITEMS_PER_CALL - 1) // BOOK_ITEMS_PER_CALL
    has_terms = any(str((data.get("story_bible") or {}).get(k) or "").strip()
                    for k in ("places", "items", "terms"))
    book_calls = (card_calls + fac_calls + item_calls + 1
                  + (1 if (src_chars or src_facs or src_items) else 0) + (1 if has_terms else 0))
    n_calls = book_calls + plan_calls + chap_calls + seq_calls

    if args.dry_run:
        print(f"[dry-run] 源书={args.book} → 新书={args.out_book or '（由模型生成）'}｜model={args.model} base_url={base_url}")
        print(f"[dry-run] 书级改编拆成 {book_calls} 次调用：1 次统一命名 + "
              f"{card_calls} 段角色卡（每段 ≤{BOOK_CARDS_PER_CALL} 张） + "
              f"{fac_calls} 段势力卡（每段 ≤{BOOK_FACTIONS_PER_CALL} 张） + "
              f"{item_calls} 段道具功法（每段 ≤{BOOK_ITEMS_PER_CALL} 张） + 1 次总纲"
              + (" + 1 次术语映射" if has_terms else ""))
        parallel = card_calls + fac_calls + item_calls
        if parallel:
            rounds = ((1 if (src_chars or src_facs or src_items) else 0)
                      + -(-parallel // BOOK_CALL_CONCURRENCY) + 1 + (1 if has_terms else 0))
            print(f"[dry-run] 角色/势力/道具分批按 {min(BOOK_CALL_CONCURRENCY, parallel)} 路并发，"
                  f"书级阶段约 {rounds} 轮（串行需要 {book_calls} 轮）")
        if mapping:
            mode = "扩写" if target > total_src else "压缩"
            print(f"[dry-run] 源书 {total_src} 章 → 目标 {target} 章（{mode}）："
                  f"1 次章数规划 + 约 {chap_calls} 段映射改编"
                  f"（每段 ≤{MAP_NEW_PER_CALL} 新章 / 约 ≤{CHAPTERS_PER_CALL} 源章）")
        else:
            print(f"[dry-run] 共 {total_src} 章 → {chap_calls} 段章节改编（每段 ≤{CHAPTERS_PER_CALL} 章）")
        if sequel:
            print(f"[dry-run] 续写 {sequel} 章：{seq_calls} 次调用（每次 ≤{SEQUEL_PER_CALL} 章），章号接在第 {target} 章之后")
        print(f"[dry-run] 改编要求：{style[:100]}")
        return

    api_key = key_or_empty(args.api_key)
    if args.local or not api_key:
        if not args.local:
            print("[!] 未配置 API Key：改用本地改编骨架"
                  "（沿用源书题材与命名，只做章数映射；配好 Key 再跑一次即为正式改编）")
        out_book = _dedup((args.out_book or "").strip() or f"{args.book}·改编", args.book)
        print(f"[OUTPUT_BOOK] {out_book}")
        print(f"    新书名：《{out_book}》（本地模式生成，可随时在页面改）")
        decomposed = local_adapt(data, target, sequel)
        extra = ""
        if mapping or sequel:
            extra = f"（原著 {total_src} 章 → 改编 {target} 章" + (f" + 续写 {sequel} 章" if sequel else "") + "，本地模式）"
        _write_outputs(decomposed, out_book, extra)
        write_adapt_report(out_book, args.book, "local", style, total_src,
                           len(decomposed.get("chapters") or []), target, sequel, [])
        return

    step = 1
    name_map = []

    # 1) 先起一套统一的新名字：后续角色卡 / 势力卡 / 道具功法 / 章节都照这张表，避免各批各起一套
    if src_chars or src_facs or src_items:
        print(f"[{step}/{n_calls}] 书级改编：统一命名方案（{len(src_chars)} 个角色 / "
              f"{len(src_facs)} 个势力 / {len(src_items)} 件道具功法）...")
        nm = _call(build_naming_prompt(src_chars, src_facs, src_items, data, style),
                       api_key, base_url, args.model, tag="[命名] ", hint=_BOOK_TRUNC_HINT)
        name_map = [m for m in (nm.get("name_map") or []) if isinstance(m, dict)]
        print(f"    得到 {len(name_map)} 条新名字")
        step += 1

    # 2) 角色卡 / 势力卡 / 道具功法分批改写：命名表已定，各批互不依赖 → 4 路并发
    parallel_calls = card_calls + fac_calls + item_calls
    if src_chars or src_facs or src_items:
        first, last = step, step + parallel_calls - 1
        span = f"{first}" if first == last else f"{first}-{last}"
        print(f"[{span}/{n_calls}] 书级改编：并行改写角色卡 {card_calls} 段 + 势力卡 {fac_calls} 段"
              f" + 道具功法 {item_calls} 段（{min(BOOK_CALL_CONCURRENCY, parallel_calls)} 路并发）...")
        new_chars, new_facs, new_items, extra_pairs = _rewrite_roster(
            src_chars, src_facs, src_items, data, style, name_map,
            api_key, base_url, args.model)
        name_map.extend(extra_pairs)
        step += parallel_calls
    else:
        new_chars, new_facs, new_items = [], [], []

    name_map = merge_name_map(name_map)
    # 跨批引用（势力归属 / 关系对象 / 道具持有者）统一换新名
    apply_name_map_all(new_chars + new_facs + new_items, name_map)

    # 4) 总纲：书名 / 梗概 / 设定库（此时角色、势力名都已定稿，设定库才能与卡片自洽）
    print(f"[{step}/{n_calls}] 书级改编：书名 / 梗概 / 设定库 ...")
    meta = _call(build_meta_prompt(data, style, new_chars, new_facs),
                     api_key, base_url, args.model, tag="[总纲] ", hint=_BOOK_TRUNC_HINT)
    step += 1

    # 5) 地点 / 物品 / 功法等术语映射（不映射也能跑，但章节里更容易残留旧名）
    if has_terms:
        print(f"[{step}/{n_calls}] 书级改编：地点 / 物品 / 术语映射 ...")
        tm = _call(build_terms_prompt(data, style, meta.get("book_summary") or "",
                                          new_chars, new_facs),
                       api_key, base_url, args.model, tag="[术语] ", hint=_BOOK_TRUNC_HINT)
        known = {m["old"] for m in name_map}   # 角色 / 势力 / 道具已定的名字优先，术语不得覆盖
        name_map = merge_name_map(name_map + [m for m in (tm.get("name_map") or [])
                                              if isinstance(m, dict)
                                              and str(m.get("old") or "").strip() not in known])
        apply_name_map_all(new_chars + new_facs + new_items, name_map)
        step += 1

    book = {
        "book_title": meta.get("book_title") or "",
        "book_summary": meta.get("book_summary") or "",
        "story_bible": meta.get("story_bible") or {},
        "opening": meta.get("opening") or {},
        "characters": new_chars,
        "factions": new_facs,
        "items": new_items,
    }
    n_card = len(new_chars)
    n_fac = len(new_facs)
    n_item = len(new_items)
    print(f"    得到 {len(name_map)} 条命名映射、{n_card} 张新角色卡、"
          f"{n_fac} 张新势力卡、{n_item} 张道具功法卡")

    # 新书名：显式指定 > 模型生成 book_title > 源书名·改编；同名/碰撞自动加后缀
    gen_name = (args.out_book or "").strip() or _safe_name(book.get("book_title")) or f"{args.book}·改编"
    out_book = _dedup(gen_name, args.book)
    print(f"[OUTPUT_BOOK] {out_book}")
    print(f"    新书名：《{out_book}》")

    new_ch = []
    step = book_calls     # 书级改编已走完，章节批次从这里接着编号
    used_titles = []      # 已生成的章题：分批时喂给下一段，避免各批各写一套重复标题
    if mapping:
        step += 1
        print(f"[{step}/{n_calls}] 章数规划：把源书 {total_src} 章映射为新书 {target} 章...")
        res = _call(build_plan_prompt(chapters, style, target),
                        api_key, base_url, args.model, tag="[章数规划] ")
        plan = validate_plan(res.get("plan"), target, total_src)
        if plan is None:
            print("    [!] 规划返回不合规则（条数/覆盖不符），改用按比例映射兜底")
            plan = proportional_plan(total_src, target)
        n_merge = sum(1 for p in plan if p["to"] > p["from"])
        print(f"    规划完成：{target} 条新章，原著 {total_src} 章全覆盖（{n_merge} 条覆盖多章）")
        batches = plan_batches(plan)
        n_calls += len(batches) - chap_calls
        for i, batch in enumerate(batches, 1):
            step += 1
            rng = f"{batch[0]['new']}~{batch[-1]['new']}"
            print(f"[{step}/{n_calls}] 改编章节 新第{rng}章（{len(batch)} 章，按映射）...")
            got = _map_segments(batch, chapters, book, style, name_map, used_titles,
                                api_key, base_url, args.model, tag=f"[映射段{i}] ")
            _inherit_chapter_meta(got, [chapters[p["from"] - 1:p["to"]] for p in batch])
            new_ch.extend(got)
            used_titles.extend(c.get("title") for c in got if c.get("title"))
    else:
        for i, seg in enumerate(segs, 1):
            step += 1
            rng = f"{seg[0].get('chapter')}~{seg[-1].get('chapter')}"
            print(f"[{step}/{n_calls}] 改编章节 第{rng}章（{len(seg)} 章）...")
            got = _chap_segments(seg, book, style, name_map, total_src, used_titles,
                                 api_key, base_url, args.model, tag=f"[章节段{i}] ")
            _inherit_chapter_meta(got, [[c] for c in seg])
            new_ch.extend(got)
            used_titles.extend(c.get("title") for c in got if c.get("title"))

    if sequel:
        for j in range(0, sequel, SEQUEL_PER_CALL):
            step += 1
            k = min(SEQUEL_PER_CALL, sequel - j)
            start = target + j + 1
            print(f"[{step}/{n_calls}] 续写剧情 新第{start}~{start + k - 1}章（{k} 章）...")
            tail = (new_ch or chapters)[-3:]
            new_ch.extend(_sequel_segments(tail, book, style, k, start, used_titles,
                                           api_key, base_url, args.model,
                                           tag=f"[续写{j // SEQUEL_PER_CALL + 1}] "))

    apply_name_map(new_ch, name_map)
    dedupe_titles(new_ch)     # 分批仍可能撞标题：兜底去重，保证目录里没有同名章

    decomposed = {
        "book_summary": book.get("book_summary", ""),
        "story_bible": book.get("story_bible", {}) or {},
        "opening": book.get("opening") or {},
        "characters": book.get("characters") or [],
        "factions": book.get("factions") or [],
        "items": book.get("items") or [],
        "chapters": new_ch,
    }
    extra = ""
    if mapping or sequel:
        extra = f"（原著 {total_src} 章 → 改编 {target} 章" + (f" + 续写 {sequel} 章" if sequel else "") + "）"
    _write_outputs(decomposed, out_book, extra)
    write_adapt_report(out_book, args.book, "ai", style, total_src,
                       len(decomposed.get("chapters") or []), target, sequel, name_map)


if __name__ == "__main__":
    main()
