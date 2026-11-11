# -*- coding: utf-8 -*-
"""逐章概括：输出 80-200 字的章节摘要、核心冲突与钩子。"""

from __future__ import annotations

import json

from pydantic import Field

from ..contracts import SkillContext, StrictModel, call_json, list_of_dicts, text_of
from .base import BaseSkill

SYSTEM = "你是网文编辑，只输出 JSON；概括要具体，不写空话。"
PROMPT = """【技能 chapter_summarize】
书名：{title}
请概括下列章节正文，summary 控制在 80-200 字，并给出核心冲突与章末钩子。
同时回填下列结构化字段；无法确定的留空，不要编造。
输出 JSON：{{"chapters":[{{"chapter_no":1,"title":"","summary":"","conflict":"","hook":"",
"chapter_id":"","scene":"","hook_type":"","emotion":"","tension":5,"payoff":"","setup":"",
"points":[""],"roles":[""],"factions":[""],"items":[""]}}]}}
章节：{material}
"""

FILLER = "这一章把主线矛盾向前推了一步，人物关系出现新的张力，为后续冲突埋下伏笔。"


class ChapterSummarizeInput(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    chapters: list[dict] = Field(default_factory=list)


class SummaryChapter(StrictModel):
    chapter_no: int
    title: str
    summary: str
    conflict: str
    hook: str
    word_count: int = 0
    # 可选结构化字段，与 chapter_write / 工作台字段同名；缺失时为空。
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


class ChapterSummarizeOutput(StrictModel):
    chapters: list[SummaryChapter] = Field(default_factory=list)


def _clip(text: str, minimum: int = 80, maximum: int = 200) -> str:
    text = " ".join(str(text or "").split())
    if len(text) > maximum:
        cut = text[:maximum]
        pos = max(cut.rfind(mark) for mark in "。！？；")
        text = cut[: pos + 1] if pos >= minimum else cut
    while len(text) < minimum:
        text = f"{text} {FILLER}".strip()
    return text[:maximum]


PROMPT_MARKERS = ("【技能", "你是网文", "输出 JSON", "书名：")


def _clean(value: str) -> str:
    value = text_of(value)
    return "" if any(marker in value for marker in PROMPT_MARKERS) else value


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


def _fallback(chapter: dict, index: int) -> SummaryChapter:
    content = _clean(chapter.get("content")) or _clean(chapter.get("summary"))
    number = _int(chapter.get("chapter") or index, index)
    return SummaryChapter(
        chapter_no=number,
        title=text_of(chapter.get("title")) or f"第{index}章",
        summary=_clip(content or FILLER),
        conflict=_clean(chapter.get("conflict"))
        or _clean(chapter.get("summary"))
        or "主角的核心目标遭遇直接阻力。",
        hook=_clean(chapter.get("hook")) or "新的问题被抛出，答案留到下一章。",
        word_count=int(
            chapter.get("word_count")
            or len(text_of(chapter.get("content")))
            or len(content)
        ),
        chapter_id=_clean(chapter.get("chapter_id")) or f"ch-{number:03d}",
        scene=_clean(chapter.get("scene")),
        hook_type=_clean(chapter.get("hook_type")),
        emotion=_clean(chapter.get("emotion")),
        tension=max(0, min(10, _int(chapter.get("tension"))))
        if chapter.get("tension") is not None
        else 0,
        payoff=_clean(chapter.get("payoff")),
        setup=_clean(chapter.get("setup")),
        points=_text_list(chapter.get("points"), chapter.get("key_events"))[:6],
        roles=_text_list(chapter.get("roles"), chapter.get("characters"))[:8],
        factions=_text_list(chapter.get("factions"))[:6],
        items=_text_list(chapter.get("items"))[:6],
    )


class ChapterSummarizeSkill(BaseSkill):
    name = "chapter_summarize"
    version = "1.0.0"
    input_model = ChapterSummarizeInput
    output_model = ChapterSummarizeOutput

    def run(self, payload: ChapterSummarizeInput, ctx: SkillContext) -> ChapterSummarizeOutput:
        chapters = list_of_dicts(payload.chapters)
        if not chapters:
            raise ValueError("chapter_summarize 需要至少 1 章正文")
        material = [
            {
                "chapter": chapter.get("chapter") or index,
                "title": chapter.get("title"),
                "summary": chapter.get("summary"),
                "content": text_of(chapter.get("content"))[:1200],
                "hook": chapter.get("hook") or "",
                "scene": chapter.get("scene") or "",
                "hook_type": chapter.get("hook_type") or "",
                "emotion": chapter.get("emotion") or "",
                "tension": chapter.get("tension") or 0,
                "payoff": chapter.get("payoff") or "",
                "setup": chapter.get("setup") or "",
                "points": chapter.get("points") or [],
                "roles": chapter.get("roles") or [],
                "factions": chapter.get("factions") or [],
                "items": chapter.get("items") or [],
            }
            for index, chapter in enumerate(chapters, 1)
        ]
        data = call_json(
            ctx,
            system=SYSTEM,
            user=PROMPT.format(
                title=payload.title,
                material=json.dumps(material, ensure_ascii=False)[:8000],
            ),
        )
        got = [] if ctx.settings.model_stub else list_of_dicts(data.get("chapters"))
        got_by_no = {
            int(item.get("chapter_no") or item.get("chapter") or i): item
            for i, item in enumerate(got, 1)
        }
        result: list[SummaryChapter] = []
        for index, chapter in enumerate(chapters, 1):
            fallback = _fallback(chapter, index)
            item = got_by_no.get(fallback.chapter_no) or (got[0] if got else {})
            if not text_of(item.get("summary")):
                ctx.log(f"第 {index} 章概括缺失，使用确定性兜底", level="warning")
                result.append(fallback)
                continue
            result.append(
                SummaryChapter(
                    chapter_no=fallback.chapter_no,
                    title=text_of(item.get("title")) or fallback.title,
                    summary=_clip(text_of(item.get("summary"))),
                    conflict=text_of(item.get("conflict")) or fallback.conflict,
                    hook=text_of(item.get("hook")) or fallback.hook,
                    word_count=fallback.word_count,
                    chapter_id=text_of(item.get("chapter_id")) or fallback.chapter_id,
                    scene=text_of(item.get("scene")) or fallback.scene,
                    hook_type=text_of(item.get("hook_type")) or fallback.hook_type,
                    emotion=text_of(item.get("emotion")) or fallback.emotion,
                    tension=max(
                        fallback.tension,
                        min(10, _int(item.get("tension"))),
                    )
                    if item.get("tension") is not None
                    else fallback.tension,
                    payoff=text_of(item.get("payoff")) or fallback.payoff,
                    setup=text_of(item.get("setup")) or fallback.setup,
                    points=_text_list(item.get("points")) or fallback.points,
                    roles=_text_list(item.get("roles")) or fallback.roles,
                    factions=_text_list(item.get("factions")) or fallback.factions,
                    items=_text_list(item.get("items")) or fallback.items,
                )
            )
        ctx.log(f"章节概括完成：{len(result)} 章")
        return ChapterSummarizeOutput(chapters=result)
