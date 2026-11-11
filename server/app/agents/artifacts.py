# -*- coding: utf-8 -*-
"""运行产物：与 /v1/tasks 相同的 <书名>/<id>/ 前缀，写入现有存储后端。"""

from __future__ import annotations

import json

from ..services.storage import book_slug
from .graph import RunView


def prefix_of(run: RunView) -> str:
    slug = (run.meta or {}).get("book_slug") or book_slug(run.title)
    return f"{slug}/{run.id}"


def render_outline_md(run: RunView, outline: dict) -> str:
    lines = [f"# 《{run.title}》创作大纲", ""]
    if outline.get("logline"):
        lines.extend([f"> {outline['logline']}", ""])
    if outline.get("theme"):
        lines.extend([f"**主题**：{outline['theme']}", ""])
    bible = outline.get("story_bible") or {}
    if bible:
        lines.append("## 设定")
        for key, label in (
            ("synopsis", "简介"),
            ("world", "世界观"),
            ("power", "能力体系"),
            ("protagonist", "主角"),
            ("mainline", "主线"),
        ):
            if bible.get(key):
                lines.append(f"- **{label}**：{bible[key]}")
        lines.append("")
    lines.append("## 分章")
    for chapter in outline.get("chapters") or []:
        lines.append(f"### 第 {chapter.get('chapter')} 章 · {chapter.get('title') or ''}")
        if chapter.get("summary"):
            lines.append(chapter["summary"])
        for event in chapter.get("key_events") or []:
            lines.append(f"- {event}")
        if chapter.get("hook"):
            lines.extend([f"> 钩子：{chapter['hook']}", ""])
        else:
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_hot_preview_md(run: RunView, preview: dict) -> str:
    lines = [f"# 《{run.title}》前三章概览", ""]
    if preview.get("mainline_conflict"):
        lines.extend([f"> 主线冲突：{preview['mainline_conflict']}", ""])
    for chapter in preview.get("chapters") or []:
        lines.append(f"## 第 {chapter.get('chapter')} 章 · {chapter.get('title') or ''}")
        lines.append(chapter.get("synopsis") or "")
        lines.append("")
        if chapter.get("main_conflict"):
            lines.append(f"- **冲突**：{chapter['main_conflict']}")
        names = chapter.get("characters") or []
        if names:
            lines.append(f"- **人物**：{'、'.join(names)}")
        for relation in chapter.get("relations") or []:
            lines.append(
                f"- **关系**：{relation.get('source')} → {relation.get('target')}"
                f"（{relation.get('kind') or '同章出场'}）"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_manuscript_md(run: RunView, chapters: list[dict]) -> str:
    lines = [f"# 《{run.title}》正文", ""]
    for chapter in chapters:
        lines.extend(
            [
                f"# 第{chapter.get('chapter')}章 {chapter.get('title') or ''}".rstrip(),
                "",
                str(chapter.get("content") or "").strip(),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def write_artifacts(storage, run: RunView, state: dict) -> list[dict]:
    """按当前 checkpoint 尽力写产物；已生成的不会被空数据覆盖。"""
    if storage is None:
        return []
    prefix = prefix_of(run)
    written: list[dict] = []

    outline = state.get("outline") or {}
    if outline.get("chapters") or outline.get("logline"):
        storage.put_bytes(
            f"{prefix}/outline.md",
            render_outline_md(run, outline).encode("utf-8"),
            "text/markdown; charset=utf-8",
        )
        written.append({"name": "outline.md"})
        volumes = outline.get("volumes") or []
        if volumes:
            storage.put_json(
                f"{prefix}/volumes.json",
                {"book_title": run.title, "volumes": volumes},
            )
            written.append({"name": "volumes.json"})

    decomposed = state.get("outline_decompose") or {}
    if decomposed.get("chapters"):
        storage.put_json(
            f"{prefix}/decomposed.json",
            {"book_title": run.title, **decomposed},
        )
        written.append({"name": "decomposed.json"})

    chapters = (state.get("chapter_expand") or {}).get("chapters") or (
        (state.get("adaptation") or {}).get("chapters")
    )
    if chapters:
        storage.put_json(
            f"{prefix}/chapters.json",
            {"book_title": run.title, "chapters": chapters},
        )
        written.append({"name": "chapters.json"})
        with_content = [c for c in chapters if str(c.get("content") or "").strip()]
        if with_content:
            storage.put_bytes(
                f"{prefix}/manuscript.md",
                render_manuscript_md(run, with_content).encode("utf-8"),
                "text/markdown; charset=utf-8",
            )
            written.append({"name": "manuscript.md"})
            storage.put_json(
                f"{prefix}/chapters_full.json",
                {
                    "book_title": run.title,
                    "chapters": [
                        {
                            "no": c.get("chapter"),
                            "title": c.get("title") or "",
                            "content": c.get("content") or "",
                        }
                        for c in with_content
                    ],
                },
            )
            written.append({"name": "chapters_full.json"})
        # 分卷按最终写作章数回算，避免 reference 改编后章数变化导致卷区间失真
        volumes = outline.get("volumes") or []
        from .store import _volumes_cover
        from .skills.outline import volumes_for_chapters

        if not _volumes_cover(volumes, len(chapters)):
            storage.put_json(
                f"{prefix}/volumes.json",
                {
                    "book_title": run.title,
                    "volumes": volumes_for_chapters(chapters, run.genre_name),
                },
            )
            if "volumes.json" not in {item["name"] for item in written}:
                written.append({"name": "volumes.json"})

    summaries = (state.get("chapter_summarize") or {}).get("chapters") or []
    if summaries:
        storage.put_json(
            f"{prefix}/chapter_summaries.json",
            {"book_title": run.title, "chapters": summaries},
        )
        written.append({"name": "chapter_summaries.json"})

    graph_state = state.get("character_graph") or {}
    for name, key in (
        ("characters.json", "characters"),
        ("factions.json", "factions"),
        ("items.json", "items"),
    ):
        rows = graph_state.get(key) or []
        if rows:
            storage.put_json(f"{prefix}/{name}", {"book_title": run.title, key: rows})
            written.append({"name": name})
    bible_source = (
        graph_state.get("story_bible")
        or (state.get("adaptation") or {}).get("story_bible")
        or (state.get("outline_decompose") or {}).get("story_bible")
        or (state.get("outline") or {}).get("story_bible")
    )
    if bible_source or graph_state.get("characters"):
        storage.put_json(
            f"{prefix}/story_bible.json",
            {
                "story_bible": bible_source or {},
                "characters": graph_state.get("characters") or (state.get("outline_decompose") or {}).get("characters") or [],
                "factions": graph_state.get("factions") or (state.get("outline_decompose") or {}).get("factions") or [],
                "relations": graph_state.get("relations") or [],
            },
        )
        written.append({"name": "story_bible.json"})

    research = state.get("genre_research") or {}
    preview = state.get("hot_preview") or {}
    if research.get("works") or preview.get("chapters"):
        doc = dict(research)
        if preview.get("chapters"):
            doc["preview"] = preview
        storage.put_json(f"{prefix}/hot_research.json", doc)
        written.append({"name": "hot_research.json"})
    if preview.get("chapters"):
        storage.put_bytes(
            f"{prefix}/hot_preview.md",
            render_hot_preview_md(run, preview).encode("utf-8"),
            "text/markdown; charset=utf-8",
        )
        written.append({"name": "hot_preview.md"})
    return written


def read_artifact(storage, run: RunView, name: str):
    key = f"{prefix_of(run)}/{name}"
    raw = storage.get_bytes(key)
    if name.endswith(".json"):
        return json.loads(raw.decode("utf-8"))
    return raw.decode("utf-8")
