# -*- coding: utf-8 -*-
"""
正文扩写
========
把每章「骨架」（摘要 / 情节要点 / 出场角色 / 涉及势力 / 场景）连同全书设定，
扩写成**有文学性、不套路**的小说正文。

与 decompose / adapt / review 同源，走 DeepSeek（deepseek_common.chat_text）。

输出：data/<书名>/manuscript/<NNN>.txt（每章一个文件），
可直接在「AI 审查」页用「读入文件」载入，或直接粘到发布平台。

设计要点（针对「编辑质量门槛」）
---------------------------------
workflow.json 里那条旧的本地生成 prompt 是「第 N 条要点 = 第 N 段、恰好 5 段」
的清单式硬约束——这正是 AI 套路文的来源。这里改成：
  · 要点只是「脉络」，自然融成场景流，不必逐条对应分段；
  · 强约束「展示而非告知 / 感官落地 / 角色声音 / 克制 AI 高频词」等文笔要求；
  · 保留设定铁律（人名术语一致、不张冠李戴）与绝对禁止项（编辑口吻、标题等）。
"""

import argparse
import json
import os
import sys

from deepseek_common import (
    key_or_empty, resolve_base_url, chat_text, DEFAULT_MODEL,
)

from story_bible import SB_LABEL
from paths import book_chapters, book_decomposed, book_dir


def system_prompt():
    """实际生效的扩写系统提示词：设置页有覆盖用覆盖，否则用内置默认。"""
    try:
        import studio
        return studio.prompt_override("expand.system") or SYSTEM_PROMPT
    except Exception:  # noqa —— 设置损坏时退回内置默认
        return SYSTEM_PROMPT

# 带进 prompt 的设定字段（只带非空的；标签用 SB_LABEL，缺省回退到 key）
# 与 story_bible.SB_FIELDS 保持一致：新增设定字段时这里也要带上
SB_KEYS = [
    "synopsis", "genre", "world", "power", "person", "style", "audience",
    "mainline", "conflict", "suspense", "subplots", "protagonist",
    "supporting", "antagonist", "places", "items", "terms",
    "timeline", "map", "foreshadow", "taboos",
]


SYSTEM_PROMPT = """你是一位有个人风格的中文小说家，写长篇连载。你的文字要像人写的、有文学质感，而不是机器生成的套路文。

【第一原则】只写小说正文，任何非叙事内容都算失败。

【设定铁律】
1. 人名、门派、势力、地名、功法/道具/术语，必须严格照抄【故事设定】里的【专有名词表】与人物卡，一字不改，不得新增设定里没有的名称。
2. 不得张冠李戴：甲的势力、身份、能力不得写到乙身上。
3. 人物只能做设定里允许的事。

【绝对禁止】
1. 禁止编辑口吻（"这段文字……""本段描写了……"）与任何元说明、禁止复述本指令里的任何要求文字。
2. 禁止标题、章节号、"概括""原概"等提纲字样；禁止 #、##、**、--- 符号。
3. 禁止复述、禁止重复句子或段落。

【文笔要求（这是与普通 AI 生成文本最大的区别，务必做到）】
1. 展示而非告知：用具体的动作、感官细节、可观察的行为去呈现情绪与性格，不要直接下"他很愤怒/她很美"这类结论。
2. 落到感官：视觉/听觉/嗅觉/触觉/味觉，多用可触摸的具体物，少抽象概括。
3. 句子节奏长短交错，避免每段同构；允许短句断行制造停顿，也允许一气呵成的长句。
4. 对话要像真人：带潜台词、被打断、沉默、答非所问；用人物卡里的说话风格与口头禅，但别每句都硬塞。
5. 克制副词与 AI 高频词：少用"只见/突然/仿佛/似乎/不得不/悄然/不由得"等；少破折号强行解释；避免三段式排比。
6. 信息有密度：每句要么推进情节，要么揭示性格，要么埋设，不水字数；宁写细，不空泛。
7. 视角与设定的人称一致；第一人称通篇以"我"为主语。
8. 情绪让读者自己从描写里感受，你不要替读者总结。
9. 节奏与配比：对话与叙述大体四六开，冲突/交手段落用短句推进，抒情段落放慢；不要通篇一个速度。
10. 章末留钩：最后一段落在具体动作、画面、反转或一句带悬念的对白上，让读者想点下一章。

【情节落实】
下面给出本章摘要与若干情节要点，它们是"脉络"而非"提纲"：以它们为骨架，自然融成连贯的场景流，可以按戏剧节奏重新组织顺序、合并或穿插，不必一条对应一段、也不必逐字落实。让事件通过人物的具体选择与冲突自然发生。

【场景与角色】有名有姓的角色只能来自【本章出场角色卡】；剧情必需的龙套（店小二、守卫、路人）可以出现，但不给名字、不承担主线功能。场景限定在本章场景及其直接关联的地点。

【长度】以下方任务里给出的字数要求为准；任务没给时，按要点数量铺开，约 2000 字、5~9 段，段间空一行。宁可写细，不可注水复读，也不要为凑字数重复已经写过的信息。

【结尾】最后一句落在具体画面、动作或新发现上，不要总结式收束。

【写作公式（源自写作公式大全，与上面文笔要求互补）】
1. 对话六式：性格 / 冲突 / 信息 / 试探 / 情感 / 幽默——每段对话至少承担性格、冲突或信息之一，不写纯寒暄；试探与信息对话要有潜台词。
2. 环境描写四式：氛围（时间+地点+天气+细节）/ 天气 / 季节 / 色彩——写景为烘托情绪或暗示走向服务，与情节无关的环境段不写。
3. 节奏控制：快慢交替、强弱冲突交替；高潮按「酝酿→爆发→余韵」推进，爆发之后给读者喘息。
4. 爽点兑现：按题材设计爽点（打脸/逆袭/反转/情感爽/结果爽），压抑与释放成对出现，只铺垫不兑现是大忌。
5. 伏笔呼应：前文埋下的物件、话语、人物，该呼应的及时呼应；新埋的伏笔要具体、可回收。
6. 描写适度：人物/景物/情感描写服务剧情与塑造，有目的性，不为凑字堆砌。
"""

# 文风切换：不同题材/类型对应的写作侧重点（写手感，而非设定）
STYLE_GUIDE = {
    "都市": "当代都市写实：口语化、生活流，少玄虚；对话密集、节奏明快，多用职场/市井细节与感官化的城市意象（地铁、便利店、霓虹）。",
    "玄幻": "东方玄幻史诗：宏大世界观与升级体系，意象雄奇（山海、剑光、灵气）；叙事带传奇感，战斗场面有质感，语言可略凝练豪迈。",
    "古言": "古代言情/权谋：文白之间，辞藻温润不堆砌；重礼节、服饰、节气细节，情绪含蓄留白，对话雅致。",
    "悬疑": "悬疑推理：冷峻克制，信息递进、留白设疑；多用环境与感官细节制造不安，对话精简、暗含机锋。",
    "甜宠": "甜宠言情：轻松甜暖，互动密集、撒糖自然；对话活泼有撩拨感，情绪外放但不腻，少沉重。",
    "爽文": "快节奏爽文：直给、爽点密集，压抑—释放曲线明显；冲突短平快，打脸/逆袭干脆，少铺垫不水。",
}


def _style_block(style, sb):
    """返回【文风要求】指令块；style 为 None / '沿用设定' / 空 时，从设定库 genre/style 字段继承。"""
    s = (style or "").strip()
    if s and s != "沿用设定" and s in STYLE_GUIDE:
        # 设置页可覆盖某个文风的指南文本（提示词模板库）
        try:
            import studio
            guide = studio.prompt_override(f"expand.style.{s}") or STYLE_GUIDE[s]
        except Exception:  # noqa
            guide = STYLE_GUIDE[s]
        return ("\n【文风要求】" + guide +
                "\n（按上述文风写作，但人物、设定、专有名词仍严格服从【故事设定】与【角色卡】。）")
    bits = []
    for k in ("genre", "style"):
        v = sb.get(k) if isinstance(sb, dict) else None
        if v and str(v).strip():
            bits.append(str(v).strip())
    if bits:
        return ("\n【文风要求】延续本书设定基调：" + " / ".join(bits) +
                "；在此基调上保持个人笔触与文学质感。")
    return ""


# ---------------------------------------------------------------- 去 AI 味
# 生成类任务（初稿/续写/扩写）的随行校准：写的时候就避开 AI 腔，而不是事后补救
DE_AI_BRIEF = """【真人表达校准】写作全程同步遵守：不写空洞开场与机械连接词（"首先/其次/与此同时/总而言之"）；
不用三段式排比与四字词堆叠；段末不做总结式收束或情绪升华；句子长短错落，允许克制的不完美；
情绪与状态靠具体动作和感官细节呈现，少用"仿佛/似乎/不由得/悄然"这类万能词。"""

# 改写/润色类任务（整章与选区）的深度校准：以「语言风格编辑 + AI 痕迹清除」标准深度重写
DE_AI_GUIDE = """【去 AI 味 · 真人表达校准】本条任务同时按顶级语言风格编辑与 AI 痕迹清除的标准执行。
在不改变原文情节事实、人物关系与关键信息的前提下：
1. 删：空洞开场；正确但没有信息量的废话；机械连接词；过度完整的排比与对仗；段落末尾的重复总结；虚假的情绪升华；教科书式的说明腔。
2. 调：重新安排句子的长短、停顿节奏、信息出现的顺序与用词密度；长句与碎句交错，允许留白和克制的不完美——真人写作本就如此。
3. 补：只在原有信息范围内，加入符合语境的真实细节（感官、动作、物件）、自然的转折与明确的情绪落点；对话要有潜台词，而不是人物互相解释剧情。
4. 禁：堆砌网络热词；故意口语化卖萌；编造原文没有的情节、设定或人物；把全文改成另一种模板化文风（包括"去 AI 味"之后新的整齐划一）。
5. 自检：任意抽出一段，都不该看出"这是 AI 写的"——没有万能情绪词，没有三段式排比，没有段末小结句。
（改写 = 深度重写，润色 = 轻量打磨：改动幅度按本条任务的要求执行，校准方向不变。）"""


def deai_brief():
    """生成类任务随行的真人表达校准（可在提示词模板库覆盖：expand.deai_brief）。"""
    try:
        import studio
        return studio.prompt_override("expand.deai_brief") or DE_AI_BRIEF
    except Exception:  # noqa
        return DE_AI_BRIEF


def deai_guide():
    """改写 / 润色类任务的深度去 AI 味校准（可在提示词模板库覆盖：expand.deai）。"""
    try:
        import studio
        return studio.prompt_override("expand.deai") or DE_AI_GUIDE
    except Exception:  # noqa
        return DE_AI_GUIDE


def _craft_note(mode, ch=None):
    """按生成模式追加的写作公式指引（craft.py，源自用户写作设定；可在提示词模板库覆盖 craft.*）。
    第 1 章按大纲生成时自动追加开篇公式指引；craft 缺失时不影响生成主流程。"""
    try:
        import craft
        t = craft.expand_note(mode, first_chapter=_chapter_no(ch or {}, 0) == 1)
        return "\n\n" + t if t else ""
    except Exception:  # noqa
        return ""


# ---------------------------------------------------------------- 工具
def read_json(p, default):
    if not os.path.isfile(p):
        return default
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def as_list(v):
    """把可能是 list / JSON 数组串 / Python repr 串（如 "['陈实']"）/ 逗号分隔串 的值，
    统一归一为字符串列表。容错优先，解析失败就按顿号逗号拆。"""
    import ast
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x).strip()]
    if not isinstance(v, str):
        v = str(v)
    s = v.strip()
    if not s:
        return []
    try:
        val = ast.literal_eval(s)
        if isinstance(val, (list, tuple)):
            return [str(x).strip() for x in val if str(x).strip()]
    except Exception:
        pass
    import re
    quoted = re.findall(r"['\"]([^'\"]+)['\"]", s)
    if quoted:
        return [x.strip() for x in quoted if x.strip()]
    return [x.strip() for x in re.split(r"[、,，]", s) if x.strip()]


def _chapter_no(ch, fallback=1):
    """章号：取字段里第一段数字（「第3章」「3-5」都能认），兼容 int / str。"""
    import re as _re
    for k in ("no", "chapter_id", "chapter", "chapter_no"):
        v = ch.get(k)
        if v is None:
            continue
        m = _re.search(r"\d+", str(v))
        if m:
            n = int(m.group(0))
            if n > 0:
                return n
    return fallback


def _field(ch, *keys, default=""):
    for k in keys:
        v = ch.get(k)
        if isinstance(v, (list, tuple)):
            v = "、".join(str(x) for x in v if str(x).strip()) if v else default
        if v is not None and str(v).strip():
            return str(v)
    return default


def load_book(book):
    ch_data = read_json(book_chapters(book), {})
    dec = read_json(book_decomposed(book), {})
    chapters = ch_data.get("chapters") or dec.get("chapters") or []
    # 设定：chapters.json 里的 story_bible 是用户可能改过的「最新原文」，优先用它；
    # 为空才退回 decomposed.json 的结构化 dict / 角色卡（与 webapp 的单章生成保持同一来源）
    sb, characters, factions = {}, [], []
    raw = ch_data.get("story_bible")
    if isinstance(raw, str) and raw.strip():
        from story_bible import parse as parse_story_bible
        sb, characters, factions = parse_story_bible(raw)
    if not sb and isinstance(dec.get("story_bible"), dict) and dec.get("story_bible"):
        sb = dec.get("story_bible")
    if not characters:
        characters = dec.get("characters") or []
    if not factions:
        factions = dec.get("factions") or []
    return chapters, sb, characters, factions


def _bare(name):
    """去括注 / 装饰符的名字，用于「陈实（主角）」↔「陈实」的宽松匹配。"""
    import re as _re
    s = _re.sub(r"[（(][^）)]*[）)]", "", str(name or ""))
    return _re.sub(r"[《》「」『』“”\"'·\s]", "", s)


def _match_card(name, cards):
    """角色 / 势力按 全等 → 去括注全等 → 互相包含 的顺序匹配，避免漏卡。"""
    raw, bare = str(name or "").strip(), _bare(name)
    if not raw:
        return None
    for c in cards:
        if str(c.get("name", "")).strip() == raw:
            return c
    for c in cards:
        if bare and _bare(c.get("name")) == bare:
            return c
    for c in cards:
        n = _bare(c.get("name"))
        if len(n) >= 2 and (n in bare or bare in n):
            return c
    return None


def _card_block(name, cards):
    if not name or not cards:
        return ""
    c = _match_card(name, cards)
    if c is not None:
        parts = [f"· {name}"]
        role = c.get("role") or c.get("定位")
        if role:
            parts.append(f"（{role}）")
        bits = []
        for k in ("personality", "性格", "speech", "说话风格", "catchwords",
                  "常用词", "goal", "动机目标", "relation", "与主角关系",
                  "identity", "身份背景"):
            v = c.get(k)
            if v and str(v).strip():
                bits.append(str(v).strip())
        tail = "；".join(bits)
        line = "".join(parts)
        if tail:
            line += "：" + tail
        return line
    return f"· {name}（设定里未找到对应角色卡，请仅按姓名与摘要合理发挥）"


def _tension_word(n):
    """把 1~10 的张力值翻译成「这一章该怎么使劲」，模型对量化词不敏感，对动作指令敏感。"""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    if n <= 3:
        return "平缓铺垫：靠信息量、生活感与暗线推进，不要硬造冲突"
    if n <= 6:
        return "摩擦升级：矛盾要具体到人、到话、到一次难看的交锋"
    if n <= 9:
        return "正面爆发：允许短句、动作、对话对撞，把憋的那口气放出来"
    return "生死 / 命运级：全章只围绕这一个危机，别的都往后放"


def _flow_block(ch):
    """情绪流段落：拆解时标好的情绪走向、峰值、兑现、铺垫、钩子类型，直接约束这一章怎么写。"""
    emo = _field(ch, "emotion")
    tension = ch.get("tension") or 0
    payoff = _field(ch, "payoff")
    setup = _field(ch, "setup")
    hook = _field(ch, "hook")
    hook_type = _field(ch, "hook_type")
    lines = []
    if emo:
        lines.append(f"情绪走向：{emo}（按这个顺序先压后放，不要一开篇就爽）")
    if tension:
        word = _tension_word(tension)
        lines.append(f"情绪峰值：{tension}/10" + (f"（{word}）" if word else ""))
    if payoff:
        lines.append(f"本章必须兑现：{payoff}（读者等的是这一下，不能只铺垫不给）")
    if setup:
        lines.append(f"本章必须埋下：{setup}（点到即止，不解释用途，不点破）")
    if hook or hook_type:
        tail = f"｜类型＝{hook_type}，最后一句必须落在这个类型上" if hook_type else ""
        lines.append(f"章末钩子：{hook or '（按类型自拟一句）'}{tail}")
    if not lines:
        return "（本章未标注情绪流：请按摘要自行安排「压抑—释放」节奏，并在章末留下钩子）"
    return "\n".join(f"{i+1}. {x}" for i, x in enumerate(lines))


def build_prompt(ch, sb, characters, factions, style=None, memory=""):
    chapter_no = _chapter_no(ch, "?")
    title = _field(ch, "title", default="（未命名）")
    scene = _field(ch, "scene", default="（未指定）")
    summary = _field(ch, "summary", default="（无摘要）")
    # 核心冲突是拆解时单独标的「和谁/什么对抗、因何激化」，摘要里常被写糊，这里单独喂给模型
    conflict = _field(ch, "conflict")
    conflict_line = f"核心冲突：{conflict}\n" if conflict else ""
    pts = as_list(ch.get("points") or ch.get("key_events"))
    points = "\n".join(f"{i+1}. {x}" for i, x in enumerate(pts)) if pts \
        else "（本章没有给出要点：请按【本章摘要】自行拆成 3~5 拍推进）"
    memory = (memory or "").strip()

    # 全书设定（只带非空）
    sb_lines = []
    for k in SB_KEYS:
        v = sb.get(k) if isinstance(sb, dict) else None
        if v and str(v).strip():
            label = SB_LABEL.get(k, k)
            sb_lines.append(f"  {label}：{v}")
    sb_text = "\n".join(sb_lines) if sb_lines else "  （无）"

    # 出场角色卡
    roles = as_list(ch.get("roles"))
    role_lines = [_card_block(r, characters) for r in roles if r and str(r).strip()]
    role_text = "\n".join(role_lines) if role_lines else "  （无，仅按摘要合理发挥）"

    # 涉及势力
    facs = as_list(ch.get("factions"))
    fac_lines = []
    for fn in facs:
        fn = str(fn).strip()
        if not fn:
            continue
        hit = _match_card(fn, factions)
        if hit:
            bits = [str(hit.get(k, "")).strip() for k in
                    ("category", "势力大类", "stance", "立场", "relType", "势力关系", "desc", "简介")
                    if str(hit.get(k, "")).strip()]
            fac_lines.append(f"· {fn}" + ("：" + "；".join(bits) if bits else ""))
        else:
            fac_lines.append(f"· {fn}（设定里未找到对应势力卡）")
    fac_text = "\n".join(fac_lines) if fac_lines else "  （无）"

    # 跨章记忆块（P0：长篇上下文检索注入），空则不占篇幅
    memory_block = ("\n" + memory + "\n") if memory else ""

    return f"""【故事设定（全书）】
{sb_text}

【本章出场角色卡】
{role_text}

【本章涉及势力】
{fac_text}

【本章任务】
章节号：第{chapter_no}章
标题：{title}
场景：{scene}
{conflict_line}
【本章摘要】（主要依据：写什么、落到哪）
{summary}

【情节脉络】（自然融合成场景流，不必逐条对应分段）
{points}

【本章情绪流】（先定情绪再写事：读者记住的是情绪，不是事件）
{_flow_block(ch)}
{memory_block}
【叙事铁律回顾】人名/术语/势力严格照抄上面的设定，不得自造或改名；不得张冠李戴。""" + _style_block(style, sb) + "\n\n" + deai_brief()


def expand_chapter(ch, sb, characters, factions, api_key, base_url, model,
                   temperature=0.7, timeout=900, style=None, memory=""):
    prompt = build_prompt(ch, sb, characters, factions, style=style, memory=memory)
    return chat_text(api_key, base_url, model, system_prompt(), prompt,
                     timeout=timeout, temperature=temperature)


# ---------------------------------------------------------------- 生成模式
MODE_LABEL = {
    "outline": "按大纲生成",
    "continue": "续写",
    "expand": "扩写",
    "rewrite": "改写",
    "polish": "润色",
}


def build_mode_prompt(mode, ch, sb, characters, factions, existing="", target=0, style=None,
                      memory="", extra_block=""):
    """四种生成模式的 user prompt：
    outline 按大纲从零生成；continue 接着已有正文续写；
    expand 把已有正文扩写得更丰满；rewrite 换角度/文风重写。

    target：本版期望字数（调用方按「整章 / 选中片段」给不同量级）；0 表示由本函数按原文长度推算。
    memory：跨章记忆检索块（前文记忆），注入到设定之后、任务之前。
    extra_block：追加到末尾的额外指令块（如「按审查意见修复」清单）。
    """
    base = build_prompt(ch, sb, characters, factions, style, memory=memory)
    extra_block = (extra_block or "").strip()
    existing = (existing or "").strip()

    def _tail(p):
        return p + ("\n\n" + extra_block if extra_block else "")

    if mode == "outline" or not existing:
        return _tail(base + _craft_note("outline", ch))

    if mode == "continue":
        tail = existing[-2000:]          # 只带末尾作衔接上下文，控制 prompt 体积
        head_note = "（因过长只保留末尾部分）" if len(existing) > 2000 else ""
        n = int(target or 2000)
        spread = f"{int(n * 0.8)}~{int(n * 1.2)}"
        return _tail(base + f"""

【已有正文{head_note}】
{tail}

【续写要求】
1. 只写「接下来的内容」：从上文末尾无缝衔接，人物语气、身份、关系与场景、时间自然延续，严格服从【故事设定】与【角色卡】，不OOC、不走形。
2. 只输出新写的正文，禁止重复已有正文的任何句子，禁止编辑口吻与元说明。
3. 【情节脉络】里已经在上文发生过的要点不要重写；先从「上文停下的那一拍」之后接着推进，写完本章剩余要点，保持设定里的主线与冲突走向。
4. 约 {spread} 字，段间空一行；最后一句落在具体画面、动作或新发现上。""" + _craft_note("continue", ch))

    if mode == "expand":
        target = int(target or min(max(1500, len(existing) * 2), 6000))
        return _tail(base + f"""

【已有正文（草稿）】
{existing}

【扩写要求】
1. 忠实原意：保留全部情节走向、人物关系与结局，不得新增设定之外的情节或人物。
2. 把概括性叙述展开成具体可感的场景：用动作、身体感受与五感细节（视觉/听觉/嗅觉/触觉/味觉）落地；遇到环境、氛围类内容，补全具体时空与质感（如雨夜的潮冷与霓虹倒影、战斗的筋骨与兵器声、告白/对峙时的呼吸与距离感）。
3. 把该有人物互动的地方写成真实对话：带潜台词、打断与沉默，可按需要生成争吵、暧昧、谈判、群像互动等不同张力的对白。
4. 篇幅扩写到约 {target} 字（原文约 {len(existing)} 字）；只输出扩写后的完整正文，禁止编辑口吻与元说明。""" + _craft_note("expand", ch))

    if mode == "rewrite":
        return _tail(base + f"""

【已有正文（初稿）】
{existing}

【改写要求】
1. 情节事实、人物、设定、结局一律不变，只换叙事节奏与语言表达重写（即润色 + 改写）。
2. 提升语句通顺度与节奏感，删冗余、补画面感，让阅读更顺、更有质感，但不改变原意与信息量。
3. 降重：同一情节换说法、换句式、换语序，避免与原文出现整句雷同；但不得为降重而改事实或漏掉关键场面。
4. 风格统一：人物说话方式、叙述人称与用语习惯要和【故事设定】里的文风一致，不要突然变成另一种腔调。
5. 篇幅与原文相当（原文约 {len(existing)} 字）；只输出重写后的完整正文，禁止编辑口吻与元说明。

{deai_guide()}""" + _craft_note("rewrite", ch))

    if mode == "polish":
        return _tail(base + f"""

【润色要求】
1. 保留全部内容、情节、人物与设定，只做文字层面的打磨，不增删情节、不改事实。
2. 通顺与节奏：理顺拗口长句，统一句式与段落节奏，让阅读顺滑；删掉重复、啰嗦与凑字数的空泛句。
3. 画面感：把抽象概括换成可感细节，补足必要的感官与动作，但不添油加醋。
4. 风格统一：叙述人称、用语与【故事设定】文风保持一致，人物说话方式贴合角色卡。
5. 篇幅与原文相当（原文约 {len(existing)} 字）；只输出润色后的完整正文，禁止编辑口吻与元说明。

{deai_guide()}""" + _craft_note("polish", ch))

    return _tail(base)


def build_selection_prompt(mode, ch, sb, characters, factions, sel,
                           before="", after="", target=0, style=None, memory=""):
    """选区操作（续写/扩写/改写/润色选中文字）的 user prompt。

    与整章模式的关键差别：带上【选区前文】与【选区后文】，要求生成结果
    与上下文无缝承接——单句选区尤其依赖前后文才能接得自然。
    """
    base = build_prompt(ch, sb, characters, factions, style, memory=memory)
    sel = (sel or "").strip()
    before = (before or "").strip()[-1200:]     # 只带选区前一段作衔接语境
    after = (after or "").strip()[:600]         # 后文是「要接过去」的方向，少量即可
    n = len(sel)
    tiny = n <= 120                             # 单句 / 短语级选区
    target = int(target or max(60, n))
    ctx = f"""
【选区前文（选中文本之前的内容，供衔接参考，不要改写、不要重复）】
{before or "（选区位于本章开头）"}

【选中的原文（要操作的对象）】
{sel}

【选区后文（选中文本之后的内容，供衔接参考，不要改写、不要重复）】
{after or "（选区位于本章结尾）"}"""

    if mode == "continue":
        return base + ctx + f"""

【续写选区要求】
1. 从「选中的原文」末尾无缝续写：接住它的语气、场景与情绪，人物身份关系严格服从【角色卡】。
2. 只写「接下来的一段」：{"选区只有一句话，写 1~3 句即可（约 " + str(max(60, min(target, 200))) + " 字），不要写成大段。" if tiny else "约 " + str(target) + " 字，段间空一行。"}
3. 若提供了【选区后文】：你写的内容之后将插在选区与后文之间，收尾要能自然通向后文的开头，不得与后文重复或矛盾；若选区后没有后文，最后一句落在具体画面或动作上。
4. 只输出新写的正文，禁止重复选区或前后文的句子，禁止编辑口吻与元说明。""" + _craft_note("continue", ch)

    if mode == "expand":
        return base + ctx + f"""

【扩写选区要求】
1. 只扩写【选中的原文】这一段：忠实原意，保留其中全部事实与人物关系，不新增设定之外的情节。
2. 把概括性叙述展开成具体可感的画面：动作、身体感受与五感细节落地；该有对话的地方写成真实对白（带潜台词与打断）。
3. 篇幅扩写到约 {target} 字（{"单句选区展开成一小段即可，约 " + str(max(120, min(target, 400))) + " 字" if tiny else "原文约 " + str(n) + " 字"}）。
4. 开头要能接上【选区前文】的语气，结尾要能顺势连到【选区后文】（或自然收住）；输出将整段替换选区。只输出扩写后的正文，禁止编辑口吻与元说明。""" + _craft_note("expand", ch)

    if mode == "rewrite":
        return base + ctx + f"""

【改写选区要求】
1. 只改写【选中的原文】：情节事实、人物、设定一律不变，换叙事节奏与语言表达重写；同一意思换句式换语序，避免与原文整句雷同。
2. 篇幅与原文相当（原文约 {n} 字{"；单句选区输出 1~2 句即可" if tiny else ""}）。
3. 语气、人称与用语习惯要和【选区前文】【选区后文】浑然一体，替换回去后读起来毫无接缝。只输出改写后的正文，禁止编辑口吻与元说明。

{deai_guide()}""" + _craft_note("rewrite", ch)

    if mode == "polish":
        return base + ctx + f"""

【润色选区要求】
1. 只润色【选中的原文】：保留全部内容与信息，只做文字打磨，不增删情节、不改事实。
2. 理顺拗口处，删冗余字词，把抽象概括换成可感细节；但改动幅度是四种操作里最小的。
3. 篇幅与原文相当（原文约 {n} 字{"；单句选区只调整这一句的表达" if tiny else ""}）。
4. 润色结果要能原样替换回原位置，与【选区前文】【选区后文】语气一致。只输出润色后的正文，禁止编辑口吻与元说明。

{deai_guide()}""" + _craft_note("polish", ch)

    return base + ctx
def local_prose(ch, sb, characters, factions):
    """无 Key 时的本地骨架稿：把章纲整理成「可编辑的写作清单」，不调用模型。

    不编造正文，但保证章节文件存在、结构完整、可以直接在编辑器里往下写，
    也让后续的审查 / 导出 / 统计等环节有输入可跑。
    """
    no = _chapter_no(ch, 1)
    title = _field(ch, "title") or f"第{no}章"
    scene = _field(ch, "scene") or "（未设定，可补充地点与时间）"
    roles = [r for r in as_list(ch.get("roles")) if r]
    points = [p for p in as_list(ch.get("points")) if p] or [p for p in as_list(ch.get("key_events")) if p]
    summary = _field(ch, "summary")
    conflict = _field(ch, "conflict")
    hook = _field(ch, "hook")
    style = _field(sb, "style") if isinstance(sb, dict) else ""
    label = title if title.startswith("第") else f"第{no}章《{title}》"
    lines = [f"【本地骨架 · 未调用 AI】{label}", ""]
    lines.append(f"场景：{scene}")
    if roles:
        bits = []
        for r in roles:
            c = _match_card(r, characters)
            role = (c.get("role") or c.get("定位") or "") if isinstance(c, dict) else ""
            bits.append(f"{r}（{role}）" if role else r)
        lines.append(f"出场人物：{'、'.join(bits)}")
    if points:
        lines.append("本章要点：")
        lines += [f"  {i}. {p}" for i, p in enumerate(points, 1)]
    if conflict:
        lines.append(f"核心冲突：{conflict}")
    if hook:
        lines.append(f"章末钩子：{hook}")
    # 情绪流也写进骨架：本地没模型，但人照着清单写时，情绪走向和峰值比情节要点更容易被忽略
    emo = _field(ch, "emotion")
    tension = ch.get("tension") or 0
    payoff = _field(ch, "payoff")
    setup = _field(ch, "setup")
    hook_type = _field(ch, "hook_type")
    if emo:
        lines.append(f"情绪走向：{emo}")
    if tension:
        word = _tension_word(tension)
        lines.append(f"情绪峰值：{tension}/10" + (f"（{word}）" if word else ""))
    if payoff:
        lines.append(f"本章兑现：{payoff}")
    if setup:
        lines.append(f"本章铺垫：{setup}")
    if hook_type:
        lines.append(f"钩子类型：{hook_type}")
    if style:
        lines.append(f"沿用文风：{style}")
    if summary:
        lines += ["", "大纲原摘要（改写时参考）：", summary]
    lines += [
        "",
        "—— 以上为写作清单，正文尚未生成 ——",
        "配置 API Key 后，用「按大纲生成」即可把本章扩写成正式正文；",
        "也可以直接在编辑器里照着要点往下写，本文件会自动成为章节正文。",
    ]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description="正文扩写：把章节骨架扩写成有文学性的正文")
    ap.add_argument("--book", required=True, help="书名（data/<书名>/）")
    ap.add_argument("--chapters", default="all",
                    help="要扩写的章号，逗号分隔如 1,3,5；默认 all")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--out", default=None, help="输出目录，默认 data/<书名>/manuscript")
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--style", default="", help="文风：都市/玄幻/古言/悬疑/甜宠/爽文（默认沿用设定）")
    ap.add_argument("--dry-run", action="store_true",
                    help="只打印将要发送的 prompt，不调 API、不落盘")
    ap.add_argument("--local", action="store_true",
                    help="强制本地模式：只生成章节骨架（写作清单），不调用模型；未配置 Key 时自动启用")
    ap.add_argument("--skip-existing", action="store_true",
                    help="断点续跑：已有非空成稿的章节直接跳过（任务中断后重跑用）")
    ap.add_argument("--no-memory", action="store_true",
                    help="关闭跨章记忆检索注入（默认开启：自动带近章摘要 + 相关前文）")
    args = ap.parse_args()

    # 用量统计上下文：批量扩写走的是「正文初稿」工序，账记到 expand_outline 名下
    try:
        import usage
        usage.set_context(stage="expand_outline", book=args.book)
    except Exception:  # noqa
        pass

    chapters, sb, characters, factions = load_book(args.book)
    if not chapters:
        sys.exit(f"[x] 书「{args.book}」没有章节数据（先拆解/编辑章节）")

    # 选章
    if args.chapters.strip().lower() == "all":
        sel = list(range(len(chapters)))
    else:
        want = set()
        for p in args.chapters.split(","):
            p = p.strip()
            if not p:
                continue
            # 支持区间「3-10」「3 - 10」（兼容全角横线/波浪线）与单章「第3章」「3」
            if re.search(r"[-－—–~～]", p):
                ends = [x for x in re.split(r"[-－—–~～]", p) if x.strip()]
                if len(ends) == 2:
                    a, b = "".join(c for c in ends[0] if c.isdigit()), "".join(c for c in ends[1] if c.isdigit())
                    if a and b:
                        a, b = int(a), int(b)
                        if a > b:
                            print(f"[!] 区间 {a}-{b} 起止颠倒，已按 {b}-{a} 处理")
                            a, b = b, a
                        want.update(range(a, b + 1))
                        continue
            n = "".join(c for c in p if c.isdigit())
            if n:
                want.add(int(n))
        sel = [i for i, c in enumerate(chapters) if _chapter_no(c, i + 1) in want]
    if not sel:
        sys.exit(f"[x] 没有匹配到任何章（chapters={args.chapters}）")

    if args.dry_run:
        for i in sel:
            ch = chapters[i]
            print("=" * 70)
            print(f"[dry-run] 第 {_chapter_no(ch, i+1)} 章《{_field(ch, 'title')}》")
            print("-" * 70)
            print(build_prompt(ch, sb, characters, factions, style=args.style or None))
            print()
        print(f"[dry-run] 共 {len(sel)} 章，未调用 API、未落盘。")
        return

    api_key = key_or_empty(args.api_key)
    local = bool(args.local) or not api_key
    base_url = resolve_base_url(args.base_url)
    if local and not args.local:
        print("[!] 未配置 API Key：本次输出「章节骨架（写作清单）」而不是正文；"
              "配好 Key 后重跑同一命令即可补成正式正文")
    out_dir = args.out or os.path.join(book_dir(args.book), "manuscript")
    os.makedirs(out_dir, exist_ok=True)

    # 跨章记忆：默认开启，设置页可关；命令行 --no-memory 也可关
    use_memory = not args.no_memory
    try:
        import studio
        use_memory = use_memory and studio.memory_conf()["enabled"]
    except Exception:  # noqa
        pass
    mc = {}
    if use_memory:
        try:
            import studio as _st
            mc = _st.memory_conf()
        except Exception:  # noqa
            mc = {}

    ok, fail, skipped = 0, 0, 0
    seen_no = set()
    for i in sel:
        ch = chapters[i]
        no = _chapter_no(ch, i + 1)
        if no in seen_no:
            print(f"[!] 章号 {no} 重复（chapters.json 里有重号章节），后者会覆盖前者的成稿文件")
        seen_no.add(no)
        fn = os.path.join(out_dir, f"{no:03d}.txt")
        if args.skip_existing and os.path.isfile(fn) and os.path.getsize(fn) > 0:
            skipped += 1
            print(f"[跳过] 第 {no} 章已有成稿（--skip-existing）")
            continue
        if local:
            prose = local_prose(ch, sb, characters, factions)
        else:
            try:
                mem = ""
                if use_memory:
                    try:
                        import memory as memlib
                        mem = memlib.build_context(args.book, ch,
                                                   top_k=mc.get("top_k", 3),
                                                   max_chars=mc.get("max_chars", 1600))
                    except Exception as e:  # noqa —— 记忆是增强，坏了不挡正文
                        print(f"    [!] 记忆检索失败（忽略，继续生成）：{e}")
                prose = expand_chapter(ch, sb, characters, factions, api_key, base_url,
                                       args.model, temperature=args.temperature,
                                       style=args.style or None, memory=mem)
            except Exception as e:  # noqa
                fail += 1
                print(f"[x] 第 {no} 章失败：{e}")
                continue
        try:
            # 覆盖前留历史快照：写坏了随时能回滚
            if os.path.isfile(fn):
                try:
                    import history
                    with open(fn, encoding="utf-8", errors="replace") as f:
                        history.snapshot(args.book, no, f.read(), note="批量扩写覆盖前")
                except Exception:  # noqa
                    pass
            with open(fn, "w", encoding="utf-8") as f:
                f.write(prose)
        except OSError as e:
            fail += 1
            print(f"[x] 第 {no} 章写盘失败：{e}")
            continue
        ok += 1
        tag = "骨架" if local else "正文"
        print(f"[✓] 第 {no} 章《{_field(ch, 'title')}》→ {fn}（{tag} {len(prose)} 字）")
    print(f"\n完成：成功 {ok} 章，失败 {fail} 章"
          + (f"，跳过已有成稿 {skipped} 章" if skipped else "")
          + f"；输出目录 {out_dir}"
          + ("（本地模式：仅生成骨架）" if local else ""))


if __name__ == "__main__":
    main()
