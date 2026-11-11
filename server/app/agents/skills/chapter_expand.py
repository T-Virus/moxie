# -*- coding: utf-8 -*-
"""章节扩写：按大纲生成前 N 章正文（默认 3 章，用于开局验证）。"""

from __future__ import annotations

import json

from pydantic import Field

from ..contracts import SkillContext, StrictModel, call_json, list_of_dicts, text_of
from .base import BaseSkill

DEFAULT_COUNT = 3


class ChapterExpandInput(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    genre_name: str = Field(min_length=1, max_length=60)
    count: int = Field(default=DEFAULT_COUNT, ge=1, le=12)
    chapters: list[dict] = Field(default_factory=list)


class ExpandedChapter(StrictModel):
    chapter: int
    title: str
    content: str
    word_count: int = 0


class ChapterExpandOutput(StrictModel):
    chapters: list[ExpandedChapter] = Field(default_factory=list)


SYSTEM = "你是网文写手，只输出 JSON；正文要具体、有动作与冲突，不写大纲式概述。"

PROMPT = """【技能 chapter_expand】
书名：{title}　题材：{genre}
请把下列前 {count} 章大纲扩写为可发布正文，每章不少于 600 字，
结尾保留钩子；不要出现「本章完」之外的元信息。
输出 JSON：{{"chapters":[{{"chapter":1,"title":"","content":""}}]}}
大纲：
{material}
"""


def _synth(payload: ChapterExpandInput, chapter: dict, index: int) -> str:
    title = text_of(chapter.get("title")) or f"第{index}章"
    summary = text_of(chapter.get("summary")) or "主角被卷入新的冲突。"
    events = [text_of(e) for e in (chapter.get("key_events") or []) if text_of(e)]
    hook = text_of(chapter.get("hook")) or "答案被留到下一章。"
    beats = [
        f"{title}",
        "",
        summary,
        "",
        "雨刚停，街道上还积着水。主角站在门口，把手里那张皱巴巴的纸看了第三遍。",
        "纸上的信息不多，却足够让一个原本安稳的夜晚彻底失效。",
    ]
    for event in events[:4]:
        beats.append(f"「{event}」发生后，周围人的态度出现了微妙变化，主角意识到自己已经被推到台前。")
    beats.extend(
        [
            "他没有急着解释，而是先观察谁在回避自己的目光。",
            "真正的对手往往藏在最安静的位置，这一点他吃过亏。",
            "交锋只持续了几个回合。对方以为胜券在握，却忽略了主角早已换掉最关键的那枚筹码。",
            "局面被撕开一道口子，主角付出代价，也拿到了继续往下的资格。",
            f"章末，{hook}",
            "",
            "（本章完）",
        ]
    )
    return "\n".join(beats)


class ChapterExpandSkill(BaseSkill):
    name = "chapter_expand"
    version = "1.0.0"
    input_model = ChapterExpandInput
    output_model = ChapterExpandOutput

    def run(self, payload: ChapterExpandInput, ctx: SkillContext) -> ChapterExpandOutput:
        outline = list_of_dicts(payload.chapters, payload.count + 6)
        if not outline:
            raise ValueError("chapter_expand 需要至少 1 条大纲章节")
        material = [
            {
                "chapter": i,
                "title": c.get("title"),
                "summary": c.get("summary"),
                "key_events": c.get("key_events") or [],
                "hook": c.get("hook") or "",
            }
            for i, c in enumerate(outline[: payload.count], 1)
        ]
        data = call_json(
            ctx,
            system=SYSTEM,
            user=PROMPT.format(
                title=payload.title,
                genre=payload.genre_name,
                count=payload.count,
                material=json.dumps(material, ensure_ascii=False)[:8000],
            ),
        )
        got = list_of_dicts(data.get("chapters"))
        by_no = {int(c.get("chapter") or i): c for i, c in enumerate(got, 1)}
        chapters: list[ExpandedChapter] = []
        for index in range(1, payload.count + 1):
            item = by_no.get(index) or {}
            content = text_of(item.get("content"))
            if not content:
                content = _synth(payload, material[index - 1], index)
                ctx.log(f"第 {index} 章模型正文缺失，使用确定性兜底", level="warning")
            chapters.append(
                ExpandedChapter(
                    chapter=index,
                    title=text_of(item.get("title")) or text_of(material[index - 1].get("title")) or f"第{index}章",
                    content=content,
                    word_count=len(content),
                )
            )
        ctx.log(f"扩写完成：{len(chapters)} 章")
        return ChapterExpandOutput(chapters=chapters)
