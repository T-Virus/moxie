# -*- coding: utf-8 -*-
"""参考写作的分段规划与跨段合并。

设计口径与 `app/runners/decompose.py` 保持一致：
  · 有章回结构时按章切段（默认每段最多 6000 字 / 2 章）；
  · 无章回结构且字数较小（默认 2 万字）视为结构化大纲，整本单段；
  · 切点只落在章首、段落或句末标点，不切断句子；
  · 超过字符/段数上限时显式报错，绝不静默截断。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..config import Settings
from ..errors import ApiError
from ..prompts import get_prompt_service

_CHAP_RE = re.compile(
    r"^[ \t　]*(?:第[0-9零一二三四五六七八九十百千两]+章|Chapter\s+\d+)", re.M
)
_SENTENCE_MARKS = "。！？!?…；;\n"

ALIAS_KEYS = ("aliases", "alias", "aka", "other_names")


@dataclass(frozen=True)
class Segment:
    index: int
    text: str
    chars: int


@dataclass(frozen=True)
class SegmentationPlan:
    segments: tuple[Segment, ...]
    mode: str  # outline | novel
    total_chars: int
    single: bool

    @property
    def count(self) -> int:
        return len(self.segments)


def _text_of(value) -> str:  # noqa: ANN001
    return str(value or "").strip()


def has_chapter_structure(text: str) -> bool:
    """至少出现 2 个章回标题才认为具备章节结构（1 个可能只是正文提到的章节）。"""
    return len(_CHAP_RE.findall(text or "")) >= 2


def _split_on_sentences(text: str, limit: int) -> list[str]:
    """超长单段兜底：优先在句末标点切，其次空白/换行，最后才硬切。"""
    if limit <= 0 or len(text) <= limit:
        return [text]
    out: list[str] = []
    start = 0
    while len(text) - start > limit:
        window = text[start : start + limit]
        cut = max(window.rfind(mark) for mark in _SENTENCE_MARKS)
        if cut <= 0:
            cut = max(window.rfind("\n"), window.rfind(" "), window.rfind("\t"))
        if cut <= 0:
            cut = len(window) - 1
        out.append(text[start : start + cut + 1])
        start += cut + 1
    tail = text[start:]
    if tail:
        out.append(tail)
    return out


def plan_segments(
    settings: Settings,
    text: str,
    *,
    target_chapters: int = 0,
) -> SegmentationPlan:
    """把整本正文/大纲规划成可逐段调用拆解技能的段列表。"""
    raw = str(text or "")
    if not raw.strip():
        raise ApiError(422, "source_empty", "源文件没有可拆解内容")
    if len(raw) > settings.agent_max_source_chars:
        raise ApiError(
            422,
            "source_too_large",
            f"源文件超过单本上限（{len(raw)} 字符 > {settings.agent_max_source_chars} 字符），"
            "请拆分后分批提交；服务端不会截断正文",
        )

    prompt = get_prompt_service(settings)
    if target_chapters > 0:
        raw = prompt.slice_first_chapters(raw, target_chapters)

    structured = has_chapter_structure(raw)
    # 无章回结构且字数较小：视为结构化大纲，整本一段，避免把大纲硬切碎
    if not structured and len(raw) <= settings.agent_outline_single_segment_chars:
        return SegmentationPlan(
            segments=(Segment(1, raw, len(raw)),),
            mode="outline",
            total_chars=len(raw),
            single=True,
        )

    chunks = prompt.split_text(
        raw,
        limit=settings.agent_segment_chars,
        max_chapters=settings.agent_segment_chapters,
        min_chapters=0,
    )
    chunks = [chunk for chunk in chunks if chunk.strip()]
    if not chunks:
        raise ApiError(422, "source_empty", "源文件没有可拆解内容")

    # 单段异常长（例如整本没有换行）时，在句末标点做二次切分，保证不切断句子
    hard_cap = max(settings.agent_segment_chars * 2, 12000)
    expanded: list[str] = []
    for chunk in chunks:
        expanded.extend(_split_on_sentences(chunk, hard_cap))

    if len(expanded) > settings.agent_max_segments:
        raise ApiError(
            422,
            "source_too_many_segments",
            f"按当前阈值需要 {len(expanded)} 段，超过单本段数上限 "
            f"{settings.agent_max_segments} 段；请提高写段阈值或拆分文件",
        )

    segments = tuple(
        Segment(index=index, text=chunk, chars=len(chunk))
        for index, chunk in enumerate(expanded, 1)
    )
    return SegmentationPlan(
        segments=segments,
        mode="novel",
        total_chars=len(raw),
        single=len(segments) == 1,
    )


# ---------- 跨段合并 ----------


def _aliases_of(item: dict) -> list[str]:
    out: list[str] = []
    for key in ALIAS_KEYS:
        value = item.get(key)
        if isinstance(value, list):
            out.extend(_text_of(entry) for entry in value)
        elif _text_of(value):
            out.append(_text_of(value))
    name = _text_of(item.get("name"))
    return [alias for alias in out if alias and alias != name]


def merge_cards(items: list[dict]) -> list[dict]:
    """同名/别名卡片合并：保留首个名称，其他名称与别名写入 aliases。"""
    entries: list[dict] = []
    index: dict[str, int] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        name = _text_of(item.get("name"))
        if not name:
            continue
        aliases = _aliases_of(item)
        keys = [name, *aliases]
        target = next((index[key.casefold()] for key in keys if key.casefold() in index), None)
        if target is None:
            entries.append({"name": name, "aliases": set(), "data": dict(item)})
            target = len(entries) - 1
        entry = entries[target]
        base = entry["data"]
        for key, value in item.items():
            if key == "name" or key in ALIAS_KEYS:
                continue
            if value in (None, "", [], {}):
                continue
            if not base.get(key):
                base[key] = value
        for key in keys:
            index[key.casefold()] = target
        entry["aliases"].update(
            alias
            for alias in keys
            if alias.casefold() != entry["name"].casefold()
        )

    merged: list[dict] = []
    for entry in entries:
        data = dict(entry["data"])
        data["name"] = entry["name"]
        aliases = sorted(entry["aliases"], key=len, reverse=True)
        if aliases:
            data["aliases"] = aliases
        merged.append(data)
    return merged


def _merge_story_bible(parts: list[dict]) -> dict:
    bible: dict = {}
    for part in parts:
        value = part.get("story_bible")
        if not isinstance(value, dict):
            continue
        for key, item in value.items():
            if item and not bible.get(key):
                bible[key] = item
    return bible


def _merge_summary(parts: list[dict]) -> str:
    summaries: list[str] = []
    for part in parts:
        summary = _text_of(part.get("book_summary"))
        if summary and summary not in summaries:
            summaries.append(summary)
    return "；".join(summaries)[:800]


def merge_parts(parts: list[dict]) -> dict:
    """章节按段序拼接并全局重编号，角色/势力/道具跨段去重合并。"""
    if not parts:
        return {
            "book_summary": "",
            "story_bible": {},
            "characters": [],
            "factions": [],
            "items": [],
            "chapters": [],
            "segments": [],
        }

    chapters: list[dict] = []
    for part in parts:
        for chapter in part.get("chapters") or []:
            if not isinstance(chapter, dict):
                continue
            item = dict(chapter)
            item["chapter"] = len(chapters) + 1
            chapters.append(item)

    segments_meta = []
    for part in parts:
        meta = part.get("segment")
        if isinstance(meta, dict):
            segments_meta.append(
                {
                    "index": meta.get("index"),
                    "input_chars": meta.get("input_chars"),
                    "chapters": len(part.get("chapters") or []),
                }
            )

    return {
        "book_summary": _merge_summary(parts),
        "story_bible": _merge_story_bible(parts),
        "characters": merge_cards([card for part in parts for card in (part.get("characters") or [])]),
        "factions": merge_cards([card for part in parts for card in (part.get("factions") or [])]),
        "items": merge_cards([card for part in parts for card in (part.get("items") or [])]),
        "chapters": chapters,
        "segments": segments_meta,
    }
