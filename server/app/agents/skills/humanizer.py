# -*- coding: utf-8 -*-
"""云端润色与去 AI 味技能：把桌面 craft.ai_taste / DE_AI_GUIDE 公式库搬到云端。

只改正文表达，不改设定事实：输出每章润色后的正文 + 命中的 AI 痕迹清单
（万能情绪词、机械连接词、三段式排比、段末小结、解释式对话）。
模型缺字段/失败时用确定性规则兜底，保证可单测、可离线。
"""

from __future__ import annotations

import json
import re

from pydantic import Field

from ..contracts import SkillContext, StrictModel, call_json, list_of_dicts, text_of
from .base import BaseSkill

SYSTEM = "你是网文语言风格编辑，只输出 JSON；在不改情节事实的前提下清除 AI 痕迹。"

PROMPT = """【技能 humanizer】
书名：{title}　题材：{genre}
按以下清单逐章润色，只改表达不改事实：
- 删：空洞开场、机械连接词（首先/其次/与此同时/总而言之）、三段式排比、段末总结式收束、虚假情绪升华；
- 调：长短句交错、节奏错落，允许留白与克制的不完美；
- 补：仅在原有信息内加感官/动作/物件细节，对话带潜台词而非互相解释剧情；
- 禁：网络热词、卖萌、编造新设定人物、把全文改成另一种模板腔。

输出 JSON：{{"chapters":[{{"chapter":1,"title":"","content":"","traces":[{{"kind":"","before":"","after":""}}]}}]}}
章节：{material}
"""

# 每类痕迹的确定性检测regex，键为 kind，值为（说明, 可替换文本）
TRACE_RULES: list[tuple[str, str, re.Pattern]] = [
    ("filler_emotion", "万能情绪词（仿佛/似乎/不由得/悄然）", re.compile(r"仿佛|似乎|不由得|悄然|不禁")),
    ("mechanical_link", "机械连接词（首先/其次/与此同时/总而言之）", re.compile(r"首先|其次|与此同时|总而言之|综上所述")),
    ("parallel_triad", "三段式排比", re.compile(r"(?:不是[^，。]{1,12}，){2}不是")),
    ("summary_tail", "段末总结式收束", re.compile(r"(?:总之|就这样|这一切)[^。]{0,20}。?$")),
    ("explain_dialogue", "解释式对话", re.compile(r"说道[：:][^。\n]{0,40}因为")),
]
TRACE_KINDS = {item[0] for item in TRACE_RULES}

MAX_CHAPTERS = 200
MAX_CONTENT = 24000


class HumanizerInput(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    genre_name: str = Field(default="", max_length=60)
    chapters: list[dict] = Field(default_factory=list)


class Trace(StrictModel):
    kind: str
    note: str
    before: str = ""
    after: str = ""


class PolishedChapter(StrictModel):
    chapter: int
    title: str
    content: str
    word_count: int = 0
    traces: list[Trace] = Field(default_factory=list)
    trace_count: int = 0
    source: str = "model"  # model | fallback | passthrough


class HumanizerOutput(StrictModel):
    chapters: list[PolishedChapter] = Field(default_factory=list)
    total_traces: int = 0
    model_used: bool = False


def _detect(content: str) -> list[Trace]:
    traces: list[Trace] = []
    for kind, note, pattern in TRACE_RULES:
        match = pattern.search(content)
        if match:
            traces.append(Trace(kind=kind, note=note, before=match.group()[:120]))
    return traces[:12]


def _fallback_polish(content: str) -> str:
    """确定性轻量打磨：去万能词、拆机械连接词、删段末小结，不改情节。"""
    text = content
    text = re.sub(r"(?:首先|其次|再次)[，,]\s*", "", text)
    text = re.sub(r"(?:与此同时|总而言之|综上所述)[，,]\s*", "", text)
    text = re.sub(r"(?:仿佛|似乎|不由得|悄然|不禁)", lambda m: {"仿佛": "像", "似乎": "像"}.get(m.group(), ""), text)
    text = re.sub(r"(?:总之|就这样)[^。\n]{0,20}。", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() or content


def _normalize(item: dict, index: int, stub: bool) -> PolishedChapter:
    content = text_of(item.get("content"))
    title = text_of(item.get("title")) or f"第{index}章"
    traces = _detect(content)
    if stub or not text_of(item.get("content")):
        polished = _fallback_polish(content)
        source = "fallback" if content else "passthrough"
        if not traces:
            traces = _detect(polished)
    else:
        polished = content
        source = "model"
    for trace in traces:
        trace.after = _fallback_polish(trace.before)[:120]
    return PolishedChapter(
        chapter=int(item.get("chapter") or index),
        title=title[:80],
        content=polished[:MAX_CONTENT],
        word_count=len(polished),
        traces=traces,
        trace_count=len(traces),
        source=source,
    )


class HumanizerSkill(BaseSkill):
    name = "humanizer"
    version = "1.0.0"
    input_model = HumanizerInput
    output_model = HumanizerOutput

    def run(self, payload: HumanizerInput, ctx: SkillContext) -> HumanizerOutput:
        chapters = list_of_dicts(payload.chapters, MAX_CHAPTERS)
        if not chapters:
            raise ValueError("humanizer 需要至少 1 章正文")
        material = [
            {
                "chapter": index,
                "title": chapter.get("title"),
                "content": text_of(chapter.get("content"))[:2400],
            }
            for index, chapter in enumerate(chapters, 1)
        ]
        data = call_json(
            ctx,
            system=SYSTEM,
            user=PROMPT.format(
                title=payload.title,
                genre=payload.genre_name or "通用",
                material=json.dumps(material, ensure_ascii=False)[:12000],
            ),
        )
        got = [] if ctx.settings.model_stub else list_of_dicts(data.get("chapters"))
        got_by_no = {int(item.get("chapter") or i): item for i, item in enumerate(got, 1)}
        result: list[PolishedChapter] = []
        for index, chapter in enumerate(chapters, 1):
            item = got_by_no.get(index) or {}
            merged = {
                **chapter,
                "content": text_of(item.get("content")) or text_of(chapter.get("content")),
                "title": text_of(item.get("title")) or text_of(chapter.get("title")),
            }
            normalized = _normalize(merged, index, stub=ctx.settings.model_stub)
            for trace in list_of_dicts(item.get("traces")):
                kind = text_of(trace.get("kind"))[:30] or "other"
                normalized.traces.append(
                    Trace(
                        kind=kind,
                        note=text_of(trace.get("note"))[:120] or kind,
                        before=text_of(trace.get("before"))[:120],
                        after=text_of(trace.get("after"))[:120],
                    )
                )
                normalized.trace_count += 1
            result.append(normalized)
        total = sum(chapter.trace_count for chapter in result)
        ctx.log(f"润色完成：{len(result)} 章，清理 {total} 处 AI 痕迹")
        return HumanizerOutput(
            chapters=result,
            total_traces=total,
            model_used=bool(got),
        )
