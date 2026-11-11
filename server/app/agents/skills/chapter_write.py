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

PROMPT = """【技能 chapter_write】
书名：{title}　题材：{genre}
请把下列章节大纲扩写为可发布正文，正文不少于 600 字，结尾保留钩子。
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


def _synth(
    payload: ChapterWriteInput,
    chapter: dict,
    index: int,
    existing: str,
    *,
    use_existing: bool = True,
) -> str:
    title = text_of(chapter.get("title")) or f"第{index}章"
    summary = _clean(chapter.get("summary")) or "主角被卷入新的冲突。"
    events = [text for text in (_clean(e) for e in (chapter.get("key_events") or [])) if text]
    hook = _clean(chapter.get("hook")) or "答案被留到下一章。"
    if use_existing and len(existing) >= 300 and _clean(existing):
        return existing
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
            "回到住处时，天已经快亮了。他把新得到的线索摊开，发现它们指向同一个方向。",
            f"章末，{hook}",
        ]
    )
    if use_existing and existing and _clean(existing):
        lines.extend(["", existing])
    return "\n".join(lines)


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
            if len(content) < 120:
                content = _synth(
                    payload,
                    chapter,
                    index,
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
