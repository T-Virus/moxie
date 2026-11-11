# -*- coding: utf-8 -*-
"""去抄袭改编：复用 `app.prompts.adapt`（src/adapt.py）的本地改编兜底与章节规范化。

真实模型路径会要求同时产出「名称映射 + 改写章节」；无可用输出时退回
`local_adapt`（不换名、只定骨架），并在日志中明确说明。
"""

from __future__ import annotations

import json

from pydantic import Field

from ...prompts import get_adapt_prompt_service
from ..contracts import SkillContext, StrictModel, call_json, list_of_dicts, text_of
from .base import BaseSkill


class AdaptationInput(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    style: str = Field(default="保留题材骨架，换人物、地名与关键设定，避开连续 20 字以上重合")
    requirements: str = ""
    book_summary: str = ""
    story_bible: dict = Field(default_factory=dict)
    characters: list[dict] = Field(default_factory=list)
    factions: list[dict] = Field(default_factory=list)
    items: list[dict] = Field(default_factory=list)
    chapters: list[dict] = Field(default_factory=list)


class AdaptationOutput(StrictModel):
    chapters: list[dict] = Field(default_factory=list)
    name_map: list[dict] = Field(default_factory=list)
    book_summary: str = ""
    story_bible: dict = Field(default_factory=dict)
    characters: list[dict] = Field(default_factory=list)
    factions: list[dict] = Field(default_factory=list)
    items: list[dict] = Field(default_factory=list)
    mode: str = "ai"


SYSTEM = "你是资深网文改编编辑，只输出 JSON。"

PROMPT = """【技能 adaptation】
把参考作品改写为原创新书：更换人名/地名/组织名/关键道具名，保留题材与节奏骨架，
避免与原文出现连续 20 字以上重合。风格要求：{style}
额外要求：{requirements}
输出 JSON：
{{"name_map":[{{"old":"","new":""}}],
 "book_summary":"",
 "story_bible":{{}},
 "characters":[{{"name":"","role":"","stance":"","personality":""}}],
 "factions":[{{"name":"","category":"","stance":""}}],
 "items":[{{"name":"","kind":"","desc":""}}],
 "chapters":[{{"chapter":1,"title":"","summary":"","content":"不少于 400 字正文","key_events":[""],"hook":""}}]}}

参考数据：
{data}
"""


def _synth_content(chapter: dict, index: int) -> str:
    title = text_of(chapter.get("title")) or f"第{index}章"
    summary = text_of(chapter.get("summary")) or "剧情继续推进。"
    events = [text_of(e) for e in (chapter.get("key_events") or []) if text_of(e)]
    hook = text_of(chapter.get("hook"))
    lines = [
        f"{title}",
        "",
        summary,
        "",
        "夜色像一层薄幕压在场景上方，主角没有立刻行动，而是先把眼前的信息重新排了一遍。",
        "他清楚地知道，任何仓促的决定都会把局面推向更坏的方向。",
    ]
    for event in events[:3]:
        lines.append(f"第一个变化出现在「{event}」之后，所有人的判断都被迫改写。")
    lines.extend(
        [
            "他没有等待援手，而是抓住对方犹豫的瞬间，把准备好的筹码推上桌面。",
            "局势在几句交锋内完成逆转，代价也随之出现。",
            f"章末留下新的问题：{hook or '下一步该怎么走，没有人给出答案。'}",
        ]
    )
    return "\n".join(lines)


def _mapping_of(entries: list[dict]) -> list[dict]:
    out = []
    for item in entries:
        old = text_of(item.get("old"))
        new = text_of(item.get("new"))
        if old and new and old != new:
            out.append({"old": old, "new": new})
    return out


def _apply_names(items: list[dict], mapping: list[dict]) -> None:
    if not mapping:
        return
    for item in items:
        name = text_of(item.get("name"))
        for pair in mapping:
            if name == pair["old"]:
                item["name"] = pair["new"]
        for key in ("title", "summary", "content"):
            text = text_of(item.get(key))
            for pair in mapping:
                text = text.replace(pair["old"], pair["new"])
            if text:
                item[key] = text
        if isinstance(item.get("key_events"), list):
            item["key_events"] = [
                _replace_all(str(e), mapping) for e in item["key_events"] if text_of(e)
            ]


def _replace_all(text: str, mapping: list[dict]) -> str:
    for pair in mapping:
        text = text.replace(pair["old"], pair["new"])
    return text


class AdaptationSkill(BaseSkill):
    name = "adaptation"
    version = "1.0.0"
    input_model = AdaptationInput
    output_model = AdaptationOutput

    def run(self, payload: AdaptationInput, ctx: SkillContext) -> AdaptationOutput:
        service = get_adapt_prompt_service(ctx.settings)
        chapters = [c for c in payload.chapters if isinstance(c, dict)]
        source = {
            "book_summary": payload.book_summary,
            "story_bible": payload.story_bible,
            "characters": payload.characters,
            "factions": payload.factions,
            "items": payload.items,
            "chapters": [
                {
                    "chapter": c.get("chapter"),
                    "title": c.get("title"),
                    "summary": c.get("summary"),
                    "key_events": c.get("key_events") or [],
                    "hook": c.get("hook") or "",
                }
                for c in chapters
            ],
        }
        data = call_json(
            ctx,
            system=SYSTEM,
            user=PROMPT.format(
                style=payload.style,
                requirements=payload.requirements or "无",
                data=json.dumps(source, ensure_ascii=False)[:14000],
            ),
        )
        got = list_of_dicts(data.get("chapters"))
        name_map = _mapping_of(list_of_dicts(data.get("name_map")))
        if got:
            got = service.fix_chapters(got, chapters or [{"chapter": i + 1} for i in range(len(got))])
            for index, chapter in enumerate(got, 1):
                chapter["chapter"] = int(chapter.get("chapter") or index)
                chapter["title"] = text_of(chapter.get("title")) or f"第{index}章"
                if not text_of(chapter.get("content")):
                    chapter["content"] = _synth_content(chapter, index)
                chapter["content"] = text_of(chapter.get("content"))
            mode = "ai"
        else:
            ctx.log("模型未返回改编章节，使用 src 本地改编兜底", level="warning")
            local = service.local_adapt(source, max(1, len(chapters)), 0)
            got = [c for c in (local.get("chapters") or []) if isinstance(c, dict)]
            for index, chapter in enumerate(got, 1):
                chapter.setdefault("content", "")
                if not text_of(chapter.get("content")):
                    chapter["content"] = _synth_content(chapter, index)
            mode = "local"

        # 长书场景模型可能只返回前几章（提示词有长度上限）；按源章序补齐骨架，避免丢章
        if chapters and len(got) < len(chapters):
            by_no = {int(item.get("chapter") or index): item for index, item in enumerate(got, 1)}
            filled = []
            for index, source_chapter in enumerate(chapters, 1):
                item = by_no.get(index)
                if item is None:
                    item = {
                        "chapter": index,
                        "title": text_of(source_chapter.get("title")) or f"第{index}章",
                        "summary": text_of(source_chapter.get("summary")),
                        "key_events": source_chapter.get("key_events") or [],
                        "hook": text_of(source_chapter.get("hook")),
                    }
                    item["content"] = _synth_content(item, index)
                filled.append(item)
            ctx.log(f"模型返回 {len(got)} 章，按源章序补齐至 {len(filled)} 章", level="warning")
            got = filled

        story_bible = data.get("story_bible") if isinstance(data.get("story_bible"), dict) else payload.story_bible
        characters = list_of_dicts(data.get("characters")) or payload.characters
        factions = list_of_dicts(data.get("factions")) or payload.factions
        items = list_of_dicts(data.get("items")) or payload.items
        _apply_names(got + characters + factions + items, name_map)
        ctx.log(f"改编完成：{len(got)} 章，名称映射 {len(name_map)} 条，模式 {mode}")
        return AdaptationOutput(
            chapters=got,
            name_map=name_map,
            book_summary=text_of(data.get("book_summary")) or payload.book_summary,
            story_bible=story_bible,
            characters=characters,
            factions=factions,
            items=items,
            mode=mode,
        )
