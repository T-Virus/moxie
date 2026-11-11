# -*- coding: utf-8 -*-
"""大纲/正文拆解：复用 `app.prompts.decompose`（其内部薄封装 src/decompose.py）。

输入由编排层从 source_key 指向的上传文件读出并注入，skill 本身不读存储。
"""

from __future__ import annotations

from pydantic import Field

from ...prompts import get_prompt_service
from ..contracts import SkillContext, StrictModel, call_json, list_of_dicts, text_of
from .base import BaseSkill


class OutlineDecomposeInput(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    source_text: str = Field(min_length=1)
    target_chapters: int = Field(default=0, ge=0, le=5000)


class DecomposeChapter(StrictModel):
    chapter: int
    title: str
    summary: str = ""
    key_events: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    factions: list[str] = Field(default_factory=list)
    scene: str = ""
    conflict: str = ""
    hook: str = ""
    tension: int = Field(default=0, ge=0, le=10)


class OutlineDecomposeOutput(StrictModel):
    book_summary: str = ""
    story_bible: dict = Field(default_factory=dict)
    characters: list[dict] = Field(default_factory=list)
    factions: list[dict] = Field(default_factory=list)
    items: list[dict] = Field(default_factory=list)
    chapters: list[DecomposeChapter] = Field(default_factory=list)
    prompt_version: str = ""


SYSTEM = "你是网文拆解编辑，只输出结构化 JSON。"

PROMPT = """【技能 outline_decompose】
请拆解下列参考作品文本，提取全书摘要、设定库、角色、势力、道具与逐章要点。
要求：只输出 JSON，章节号从 1 开始连续编号。
输出结构：
{{"book_summary":"","story_bible":{{"synopsis":"","genre":"","world":"","power":"","mainline":"","protagonist":"","supporting":""}},
 "characters":[{{"name":"","role":"","stance":"","personality":""}}],
 "factions":[{{"name":"","category":"","stance":""}}],
 "items":[{{"name":"","kind":"","desc":""}}],
 "chapters":[{{"chapter":1,"title":"","summary":"","key_events":[""],"roles":[""],"factions":[""],"scene":"","conflict":"","hook":"","tension":7}}]}}

文本：
{text}
"""


def _chapter_number(raw) -> int:  # noqa: ANN001
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 1


def _normalize_chapter(item: dict, index: int) -> DecomposeChapter:
    return DecomposeChapter(
        chapter=_chapter_number(item.get("chapter") or index),
        title=text_of(item.get("title")) or f"第{index}章",
        summary=text_of(item.get("summary")) or text_of((item.get("key_events") or [""])[0]),
        key_events=[text_of(e) for e in (item.get("key_events") or []) if text_of(e)][:8],
        roles=[text_of(r) for r in (item.get("roles") or []) if text_of(r)][:12],
        factions=[text_of(f) for f in (item.get("factions") or []) if text_of(f)][:8],
        scene=text_of(item.get("scene")),
        conflict=text_of(item.get("conflict")),
        hook=text_of(item.get("hook")),
        tension=max(0, min(int(item.get("tension") or 0), 10)),
    )


def _from_decomposed(data: dict, prompt_version: str) -> OutlineDecomposeOutput:
    chapters = [
        _normalize_chapter(item, i)
        for i, item in enumerate(list_of_dicts(data.get("chapters")), 1)
    ]
    return OutlineDecomposeOutput(
        book_summary=text_of(data.get("book_summary")),
        story_bible=data.get("story_bible") if isinstance(data.get("story_bible"), dict) else {},
        characters=list_of_dicts(data.get("characters")),
        factions=list_of_dicts(data.get("factions")),
        items=list_of_dicts(data.get("items")),
        chapters=chapters,
        prompt_version=prompt_version,
    )


class OutlineDecomposeSkill(BaseSkill):
    name = "outline_decompose"
    version = "1.0.0"
    input_model = OutlineDecomposeInput
    output_model = OutlineDecomposeOutput

    def run(self, payload: OutlineDecomposeInput, ctx: SkillContext) -> OutlineDecomposeOutput:
        service = get_prompt_service(ctx.settings)
        text = payload.source_text
        limit = payload.target_chapters or 0
        # 分段由编排层完成（见 agents/segmenter.py）；技能本身不再截断正文。
        # target_chapters 仅用于显式试跑限章，不是整本上限。
        sliced = service.slice_first_chapters(text, limit) if limit else text
        data = call_json(ctx, system=SYSTEM, user=PROMPT.format(text=sliced))
        result = _from_decomposed(data, service.version)
        if not result.chapters:
            ctx.log("模型未返回章节，改用本地拆解兜底", level="warning")
            local = _from_decomposed(service.local_decompose(sliced), service.version)
            if limit:
                local.chapters = local.chapters[:limit]
            result = local
        if limit:
            result.chapters = result.chapters[:limit]
        if not result.book_summary:
            result.book_summary = f"《{payload.title}》参考作品拆解完成，共 {len(result.chapters)} 章。"
        ctx.log(f"拆解完成：{len(result.chapters)} 章")
        return result
