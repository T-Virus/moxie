# -*- coding: utf-8 -*-
"""热门写作的前三章概览：每章 150-300 字梗概 + 主线冲突 + 人物关系。

hot 模式不暂停：本技能只产出概览，由编排层按图配置直接进入 succeeded。
"""

from __future__ import annotations

import json

from pydantic import Field

from ..contracts import SkillContext, StrictModel, call_json, list_of_dicts, text_of
from .base import BaseSkill

PREVIEW_COUNT = 3
FILLER = "主角在这一阶段主动作出选择，冲突随之升级，并为下一章留下新的悬念。"


class HotPreviewInput(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    genre_name: str = Field(min_length=1, max_length=60)
    chapters: list[dict] = Field(default_factory=list)
    outline: list[dict] = Field(default_factory=list)
    story_bible: dict = Field(default_factory=dict)
    research: dict = Field(default_factory=dict)


class PreviewRelation(StrictModel):
    source: str
    target: str
    kind: str = "同章出场"


class PreviewChapter(StrictModel):
    chapter: int
    title: str
    synopsis: str
    main_conflict: str = ""
    characters: list[str] = Field(default_factory=list)
    relations: list[PreviewRelation] = Field(default_factory=list)


class HotPreviewOutput(StrictModel):
    chapters: list[PreviewChapter] = Field(default_factory=list)
    mainline_conflict: str = ""
    character_relations: list[PreviewRelation] = Field(default_factory=list)


SYSTEM = "你是网文编辑，只输出 JSON，概览必须具体、可读、不写空话。"

PROMPT = """【技能 hot_preview】
书名：{title}　题材：{genre}
请基于前三章正文与大纲，输出「前三章概览」。
每章 synopsis 控制在 150-300 字，必须包含主线冲突与人物关系。
输出 JSON：
{{"mainline_conflict":"",
 "chapters":[{{"chapter":1,"title":"","synopsis":"","main_conflict":"",
   "characters":[""],"relations":[{{"source":"","target":"","kind":"盟友/对手/亲属"}}]}}],
 "character_relations":[{{"source":"","target":"","kind":""}}]}}
章节：{chapters}
大纲：{outline}
设定：{bible}
"""


def _clip(text: str) -> str:
    text = " ".join(str(text or "").split())
    if len(text) > 300:
        cut = text[:300]
        pos = max(cut.rfind(mark) for mark in "。！？；")
        return cut[: pos + 1] if pos >= 150 else cut
    while len(text) < 150:
        text = f"{text} {FILLER}".strip()
    return text[:300]


def _synopsis(chapter: dict, outline: dict) -> str:
    summary = text_of(outline.get("summary")) or text_of(chapter.get("summary"))
    content = text_of(chapter.get("content"))
    lines = content.splitlines()
    title = text_of(chapter.get("title")) or text_of(outline.get("title"))
    if lines and title and lines[0].strip() == title:
        content = "\n".join(lines[1:])
    body = " ".join(content.split()) or summary
    if summary and summary not in body:
        body = f"{summary} {body}".strip()
    return _clip(body or summary)


def _characters(chapter: dict, outline: dict, bible: dict) -> list[str]:
    names: list[str] = []
    for source in (outline.get("roles"), chapter.get("roles")):
        for name in source or []:
            clean = text_of(name)
            if clean and clean not in names:
                names.append(clean)
    if not names:
        for key in ("protagonist", "supporting", "antagonist"):
            clean = text_of(bible.get(key))
            if clean and clean not in names:
                names.append(clean)
    return names[:6]


def _relations(names: list[str]) -> list[PreviewRelation]:
    if len(names) < 2:
        return []
    return [
        PreviewRelation(source=names[0], target=name, kind="同章出场")
        for name in names[1:5]
    ]


def _fallback(payload: HotPreviewInput) -> HotPreviewOutput:
    outline_by_no = {
        int(item.get("chapter") or index): item
        for index, item in enumerate(list_of_dicts(payload.outline), 1)
    }
    bible = payload.story_bible or {}
    chapters: list[PreviewChapter] = []
    for index, chapter in enumerate(list_of_dicts(payload.chapters)[:PREVIEW_COUNT], 1):
        outline = outline_by_no.get(index) or {}
        names = _characters(chapter, outline, bible)
        conflict = (
            text_of(outline.get("conflict"))
            or text_of(chapter.get("conflict"))
            or text_of(outline.get("hook"))
            or f"主角在{payload.genre_name}世界中与对手正面交锋。"
        )
        chapters.append(
            PreviewChapter(
                chapter=index,
                title=text_of(chapter.get("title")) or text_of(outline.get("title")) or f"第{index}章",
                synopsis=_synopsis(chapter, outline),
                main_conflict=conflict[:120],
                characters=names,
                relations=_relations(names),
            )
        )
    mainline = (
        text_of(bible.get("mainline"))
        or "；".join(item.main_conflict for item in chapters if item.main_conflict)
        or f"《{payload.title}》前三章完成冲突建立、主角选择与阶段兑现。"
    )
    relations: list[PreviewRelation] = []
    for item in chapters:
        for relation in item.relations:
            if all(
                (relation.source, relation.target) != (old.source, old.target)
                for old in relations
            ):
                relations.append(relation)
    return HotPreviewOutput(
        chapters=chapters[:PREVIEW_COUNT],
        mainline_conflict=mainline[:200],
        character_relations=relations[:12],
    )


class HotPreviewSkill(BaseSkill):
    name = "hot_preview"
    version = "1.0.0"
    input_model = HotPreviewInput
    output_model = HotPreviewOutput

    def run(self, payload: HotPreviewInput, ctx: SkillContext) -> HotPreviewOutput:
        fallback = _fallback(payload)
        data = call_json(
            ctx,
            system=SYSTEM,
            user=PROMPT.format(
                title=payload.title,
                genre=payload.genre_name,
                chapters=json.dumps(
                    [
                        {
                            "chapter": c.get("chapter"),
                            "title": c.get("title"),
                            "content": text_of(c.get("content"))[:1600],
                        }
                        for c in payload.chapters[:PREVIEW_COUNT]
                    ],
                    ensure_ascii=False,
                )[:6000],
                outline=json.dumps(list_of_dicts(payload.outline)[:PREVIEW_COUNT], ensure_ascii=False)[:3000],
                bible=json.dumps(payload.story_bible or {}, ensure_ascii=False)[:2000],
            ),
        )
        got = {
            int(item.get("chapter") or index): item
            for index, item in enumerate(list_of_dicts(data.get("chapters")), 1)
        }
        chapters: list[PreviewChapter] = []
        for item in fallback.chapters:
            model_item = got.get(item.chapter) or {}
            synopsis = text_of(model_item.get("synopsis"))
            if len(synopsis) < 150:
                synopsis = item.synopsis
            names = [text_of(name) for name in (model_item.get("characters") or []) if text_of(name)]
            relations = []
            for pair in list_of_dicts(model_item.get("relations")):
                source, target = text_of(pair.get("source")), text_of(pair.get("target"))
                if source and target:
                    relations.append(
                        PreviewRelation(source=source, target=target, kind=text_of(pair.get("kind")) or "同章出场")
                    )
            chapters.append(
                PreviewChapter(
                    chapter=item.chapter,
                    title=text_of(model_item.get("title")) or item.title,
                    synopsis=_clip(synopsis),
                    main_conflict=text_of(model_item.get("main_conflict")) or item.main_conflict,
                    characters=names or item.characters,
                    relations=relations or item.relations,
                )
            )
        mainline = text_of(data.get("mainline_conflict")) or fallback.mainline_conflict
        ctx.log(f"前三章概览完成：{len(chapters)} 章")
        return HotPreviewOutput(
            chapters=chapters[:PREVIEW_COUNT],
            mainline_conflict=mainline[:200],
            character_relations=fallback.character_relations,
        )
