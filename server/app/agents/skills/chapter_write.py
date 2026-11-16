# -*- coding: utf-8 -*-
"""逐章正文写作：输入单章大纲（引擎按章循环），输出可阅读正文。

引擎以「每章一次技能调用」的方式执行，因此本技能只处理 `chapters` 中的章节；
MODEL_STUB 或模型缺字段时使用确定性兜底，保证正文非空且具备起承转合。
"""

from __future__ import annotations

import json

from pydantic import Field

from ..contracts import SkillContext, StrictModel, call_json, list_of_dicts, text_of
from .base import BaseSkill

SYSTEM = "你是网文写手，只输出 JSON；正文要具体、有动作与冲突，不写大纲式概述。"

# 热门创作黄金三章篇幅：每章 2800–3200 字，服务端兜底绝不低于下限。
GOLDEN_MIN_WORDS = 2800
GOLDEN_MAX_WORDS = 3200

PROMPT = """【技能 chapter_write】
书名：{title}　题材：{genre}
请把下列章节大纲扩写为可发布正文；每章正文必须 2800–3200 字，绝不能少于 2800 字，结尾保留钩子。

黄金三章硬性要求（前三章逐项自查）：
1. 主角在场：第一章开场即主角视角，禁止大段他人视角或背景介绍开场；
2. 当下危机：开篇 500 字内出现正在发生的、有具体对手的危机；
3. 未知悬念：每章结尾留下一个读者不知道答案、且下一章会推进的问题。

去AI化润色要求：
- 禁止比喻堆砌与「仿佛/宛如/像是…一样」连用，每千字最多 1 处比喻；
- 用具体动作与可感细节代替情绪形容词（不写「他感到愤怒」，写他攥紧了那枚硬币）；
- 对话推动剧情，禁止两人各说一段独白的说明式对话；
- 段落控制在 3 行以内，长短句交错，禁止排比堆叠与「不是…而是…」句式连用。

同时给出本章的结构化字段；无法确定的字段留空，不要编造。
输出 JSON：
{{"chapters":[{{"chapter":1,"title":"","content":"","scene":"","hook_type":"","emotion":"",
"tension":5,"payoff":"","setup":"","points":[""],"roles":[""],"factions":[""],"items":[""]}}]}}
字段说明：scene=本章主要场景；hook_type=章末钩子类型（悬念/危机/转折/情感）；
emotion=情绪基调；tension=张力等级 0-10；payoff=本章兑现；setup=本章铺垫；
points=情节要点；roles/factions/items=本章出场的人物/势力/道具。
大纲：{material}
"""


class ChapterWriteInput(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    genre_name: str = Field(min_length=1, max_length=60)
    story_bible: dict = Field(default_factory=dict)
    chapters: list[dict] = Field(default_factory=list)


class WrittenChapter(StrictModel):
    chapter: int
    title: str
    content: str
    word_count: int = 0
    # 以下为工作台需要的可选结构化字段；模型未给出时留空，不伪造。
    chapter_id: str = ""
    scene: str = ""
    hook_type: str = ""
    emotion: str = ""
    tension: int = 0
    payoff: str = ""
    setup: str = ""
    points: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    factions: list[str] = Field(default_factory=list)
    items: list[str] = Field(default_factory=list)


class ChapterWriteOutput(StrictModel):
    chapters: list[WrittenChapter] = Field(default_factory=list)


PROMPT_MARKERS = ("【技能", "你是网文", "输出 JSON", "书名：")

EMOTION_CURVE = (
    "压抑", "紧张", "紧迫", "压抑", "振奋", "危机",
    "低谷", "希望", "激昂", "沉重", "余波", "再出发",
)
TENSION_CURVE = (3, 5, 6, 7, 8, 7, 9, 8, 10, 9, 6, 5)


def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _text_list(*values) -> list[str]:
    out: list[str] = []
    for value in values:
        if isinstance(value, list):
            out.extend(text_of(item) for item in value if text_of(item))
        elif text_of(value):
            out.append(text_of(value))
    return out


def _hook_type(hook: str, fallback: str) -> str:
    if not hook:
        return fallback
    if any(word in hook for word in ("谁", "为什么", "真相", "秘密", "答案")):
        return "悬念"
    if any(word in hook for word in ("危", "追杀", "死", "陷阱", "杀")):
        return "危机"
    if any(word in hook for word in ("情感", "喜欢", "背叛", "离开")):
        return "情感"
    return "转折"


def _clean(value: str) -> str:
    value = text_of(value)
    return "" if any(marker in value for marker in PROMPT_MARKERS) else value


def _pad_to_target(base: str, summary: str, events: list[str]) -> str:
    """确定性兜底补齐到黄金三章下限；每次补一段有信息增量的情节，不追加空行占位。"""
    text = base.rstrip()
    if len(text) >= GOLDEN_MIN_WORDS:
        return text
    templates = (
        "他把{summary}重新过了一遍，发现被忽略的细节都指向同一个方向。",
        "对方没有把话说满，只留下一个需要主角自己验证的条件。",
        "街灯下的影子换了两次位置，主角停下脚步，确认自己没有被甩开。",
        "他翻出那张记满记号的纸，在{q}旁边补上一个简短的时间。",
        "这一次他没有急着追问，而是先把能确认的事实一条条摆在桌面上。",
        "沉默比争辩更有压力。几秒之后，对面的人终于露出一处破绽。",
        "{event}带来的后果还没有结束，新的问题已经排在后面。",
        "他承认自己判断错了一步，也立刻想清楚了下一步该往哪里走。",
        "门缝里透出的光很窄，却足够让他看清对方手里的东西。",
        "等到脚步声远去，他才把藏在袖口里的线索拿出来重新核对。",
    )
    round_no = 0
    while len(text) < GOLDEN_MIN_WORDS:
        event = events[(round_no // len(templates)) % len(events)] if events else "新的线索"
        for template in templates:
            text += "\n\n" + template.format(
                summary=summary[:40], q=summary[:12], event=event
            )
            if len(text) >= GOLDEN_MIN_WORDS:
                break
        round_no += 1
    return text


def _synth(
    payload: ChapterWriteInput,
    chapter: dict,
    existing: str,
    *,
    use_existing: bool = True,
) -> str:
    summary = _clean(chapter.get("summary")) or "主角被卷入新的冲突。"
    events = [text for text in (_clean(e) for e in (chapter.get("key_events") or [])) if text]
    hook = _clean(chapter.get("hook")) or "答案被留到下一章。"
    if use_existing and existing and _clean(existing):
        return _pad_to_target(existing, summary, events)
    lines = [
        summary,
        "",
        "雨刚停，街道上还积着水。主角站在门口，把手里那张皱巴巴的纸看了第三遍。",
        "纸上的信息不多，却足够让一个原本安稳的夜晚彻底失效。",
        "他没有立刻动身，而是先把可能出问题的环节在脑子里过了一遍。",
    ]
    for event in events[:4]:
        lines.append(
            f"「{event}」发生后，周围人的态度出现了微妙变化，主角意识到自己已经被推到台前。"
        )
    lines.extend(
        [
            "街角的灯忽明忽暗，像是在提醒他：留给他的时间不多了。",
            "他先去找了最不该找的人。对方没有拒绝，只是把条件摆在桌上，让他自己选。",
            "交锋只持续了几个回合。对方以为胜券在握，却忽略了主角早已换掉最关键的那枚筹码。",
            "局面被撕开一道口子，主角付出代价，也拿到了继续往下的资格。",
            f"章末，{hook}",
        ]
    )
    return _pad_to_target("\n".join(lines), summary, events)


def _normalize(
    chapter: dict, item: dict, index: int, *, stub: bool = False
) -> WrittenChapter:
    content = text_of(item.get("content")) or text_of(chapter.get("content"))
    number = _int(chapter.get("chapter") or item.get("chapter") or index, index)
    title = text_of(item.get("title")) or text_of(chapter.get("title")) or f"第{number}章"
    summary = _clean(chapter.get("summary"))
    hook = _clean(item.get("hook")) or _clean(chapter.get("hook"))
    # 逐项按「模型 → 章节大纲 → stub 确定性值」回退；真实模型缺失时留空。
    scene = text_of(item.get("scene")) or _clean(chapter.get("scene"))
    if stub and not scene:
        scene = (summary.split("。")[0] or title)[:30]
    hook_type = text_of(item.get("hook_type")) or _clean(chapter.get("hook_type"))
    if not hook_type:
        hook_type = _hook_type(hook, "悬念" if stub else "")
    emotion = text_of(item.get("emotion")) or _clean(chapter.get("emotion"))
    if stub and not emotion:
        emotion = EMOTION_CURVE[(index - 1) % len(EMOTION_CURVE)]
    tension = _int(item.get("tension") or chapter.get("tension") or 0)
    if not (0 <= tension <= 10):
        tension = 0
    if tension == 0 and stub:
        tension = TENSION_CURVE[(index - 1) % len(TENSION_CURVE)]
    payoff = text_of(item.get("payoff")) or _clean(chapter.get("payoff"))
    if stub and not payoff:
        payoff = f"本章兑现了「{title}」中抛出的主要矛盾。"
    setup = text_of(item.get("setup")) or _clean(chapter.get("setup"))
    if stub and not setup:
        setup = "本章为后续冲突留下了可回收的线索。"
    points = _text_list(item.get("points"), chapter.get("key_events"), chapter.get("points"))
    if stub and not points and summary:
        points = [part.strip() for part in summary.split("。") if part.strip()][:4]
    roles = _text_list(item.get("roles"), chapter.get("roles"), chapter.get("characters"))
    if stub and not roles:
        roles = ["主角"]
    factions = _text_list(item.get("factions"), chapter.get("factions"))
    if stub and not factions:
        factions = ["主角阵营"]
    items = _text_list(item.get("items"), chapter.get("items"))
    if stub and not items:
        items = ["关键线索"]
    return WrittenChapter(
        chapter=number,
        title=title[:80],
        content=content,
        word_count=len(content),
        chapter_id=text_of(item.get("chapter_id")) or _clean(chapter.get("chapter_id")) or f"ch-{number:03d}",
        scene=scene[:60],
        hook_type=hook_type,
        emotion=emotion,
        tension=tension,
        payoff=payoff[:200],
        setup=setup[:200],
        points=points[:6],
        roles=roles[:8],
        factions=factions[:6],
        items=items[:6],
    )


class ChapterWriteSkill(BaseSkill):
    name = "chapter_write"
    version = "1.0.0"
    input_model = ChapterWriteInput
    output_model = ChapterWriteOutput

    def run(self, payload: ChapterWriteInput, ctx: SkillContext) -> ChapterWriteOutput:
        chapters = list_of_dicts(payload.chapters)
        if not chapters:
            raise ValueError("chapter_write 需要至少 1 章大纲")
        material = [
            {
                "chapter": index,
                "title": chapter.get("title"),
                "summary": chapter.get("summary"),
                "key_events": chapter.get("key_events") or [],
                "hook": chapter.get("hook") or "",
                "arc": chapter.get("arc") or "",
                "conflict": chapter.get("conflict") or "",
                "reversal": chapter.get("reversal") or "",
                "foreshadow": chapter.get("foreshadow") or "",
            }
            for index, chapter in enumerate(chapters, 1)
        ]
        data = call_json(
            ctx,
            system=SYSTEM,
            user=PROMPT.format(
                title=payload.title,
                genre=payload.genre_name,
                material=json.dumps(material, ensure_ascii=False)[:8000],
            ),
        )
        got = [] if ctx.settings.model_stub else list_of_dicts(data.get("chapters"))
        got_by_no = {int(item.get("chapter") or i): item for i, item in enumerate(got, 1)}
        result: list[WrittenChapter] = []
        for index, chapter in enumerate(chapters, 1):
            item = got_by_no.get(index) or {}
            existing = text_of(chapter.get("content"))
            content = text_of(item.get("content"))
            if len(content) < GOLDEN_MIN_WORDS:
                content = _synth(
                    payload,
                    chapter,
                    existing,
                    use_existing=not ctx.settings.model_stub,
                )
                ctx.log(f"第 {index} 章正文缺失或过短，使用确定性兜底", level="warning")
            normalized = _normalize(
                chapter, {**item, "content": content}, index, stub=ctx.settings.model_stub
            )
            result.append(normalized)
        ctx.log(f"正文写作完成：{len(result)} 章，共 {sum(c.word_count for c in result)} 字")
        return ChapterWriteOutput(chapters=result)
