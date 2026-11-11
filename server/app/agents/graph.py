# -*- coding: utf-8 -*-
"""确定性 DAG：图结构写死在代码里，LLM 只负责节点内部生成与「意图→参数」解析。

拓扑执行规则：
  · 同层节点并发，层间串行；
  · 节点依赖只能来自声明的前驱，输出按 node id 落 checkpoint；
  · 失败按 NodeSpec.retries 重试，耗尽后整条 run 失败。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class RunView:
    """从 ORM 快照出的运行字段，供并发线程内的 builder 安全读取。"""

    id: str
    mode: str
    title: str
    audience: str
    length: str
    genre_id: str | None
    genre_name: str
    source_key: str | None
    brief: str | None
    meta: dict = field(default_factory=dict)


Builder = Callable[[RunView, dict, dict], dict]


@dataclass(frozen=True)
class NodeSpec:
    id: str
    skill: str
    label: str
    depends_on: tuple[str, ...]
    builder: Builder
    retries: int = 1
    # 分段节点：由引擎按 segmenter 规划逐段执行并写段级 checkpoint
    segmented: bool = False
    # 章级节点：由引擎按 builder 给出的 chapters 逐章执行并写章级 checkpoint
    chaptered: bool = False


@dataclass(frozen=True)
class Graph:
    mode: str
    nodes: tuple[NodeSpec, ...]

    def node(self, node_id: str) -> NodeSpec | None:
        return next((item for item in self.nodes if item.id == node_id), None)

    def node_ids(self) -> list[str]:
        return [item.id for item in self.nodes]

    def layers(self) -> list[list[NodeSpec]]:
        """Kahn 分层：同层无依赖关系，可并发执行。"""
        done: set[str] = set()
        remaining = list(self.nodes)
        result: list[list[NodeSpec]] = []
        while remaining:
            layer = [node for node in remaining if all(dep in done for dep in node.depends_on)]
            if not layer:
                raise ValueError(f"图 {self.mode} 存在环或缺失依赖")
            result.append(layer)
            done.update(node.id for node in layer)
            remaining = [node for node in remaining if node.id not in done]
        return result

    def validate(self) -> None:
        ids = self.node_ids()
        if len(ids) != len(set(ids)):
            raise ValueError(f"图 {self.mode} 存在重复节点")
        for node in self.nodes:
            for dep in node.depends_on:
                if dep not in ids:
                    raise ValueError(f"图 {self.mode} 节点 {node.id} 依赖不存在的 {dep}")
        self.layers()


def _state(state: dict, node_id: str) -> dict:
    value = state.get(node_id) or {}
    return value if isinstance(value, dict) else {}


def _hot_research(run: RunView, state: dict, extra: dict) -> dict:
    return {
        "title": run.title,
        "genre_id": run.genre_id,
        "genre_name": run.genre_name,
        "audience": run.audience,
        "length": run.length,
    }


def _hot_outline(run: RunView, state: dict, extra: dict) -> dict:
    return {
        "title": run.title,
        "audience": run.audience,
        "length": run.length,
        "genre_name": run.genre_name,
        "brief": run.brief,
        "research": _state(state, "genre_research"),
        "decomposition": {},
        "adaptation": {},
    }


def _expand(run: RunView, state: dict, extra: dict) -> dict:
    outline = _state(state, "outline")
    chapters = list(outline.get("chapters") or [])
    if run.mode == "hot":
        chapters = chapters[:3]
    return {
        "title": run.title,
        "genre_name": run.genre_name,
        "story_bible": outline.get("story_bible") or {},
        "chapters": chapters,
    }


def _expand_reference(run: RunView, state: dict, extra: dict) -> dict:
    adapted = _state(state, "adaptation")
    outline = _state(state, "outline")
    return {
        "title": run.title,
        "genre_name": run.genre_name,
        "story_bible": adapted.get("story_bible") or outline.get("story_bible") or {},
        "chapters": adapted.get("chapters") or [],
    }


def _summarize(run: RunView, state: dict, extra: dict) -> dict:
    return {
        "title": run.title,
        "chapters": _state(state, "chapter_expand").get("chapters") or [],
    }


def _lore(run: RunView, state: dict, extra: dict) -> dict:
    adapted = _state(state, "adaptation")
    decomposed = _state(state, "outline_decompose")
    outline = _state(state, "outline")
    return {
        "title": run.title,
        "genre_name": run.genre_name,
        "story_bible": (
            adapted.get("story_bible")
            or decomposed.get("story_bible")
            or outline.get("story_bible")
            or {}
        ),
        "characters": adapted.get("characters") or decomposed.get("characters") or [],
        "factions": adapted.get("factions") or decomposed.get("factions") or [],
        "items": adapted.get("items") or decomposed.get("items") or [],
        "chapters": _state(state, "chapter_expand").get("chapters") or [],
        "outline": outline.get("chapters") or [],
    }


def _review_from_expand(run: RunView, state: dict, extra: dict) -> dict:
    chapters = _state(state, "chapter_expand").get("chapters") or []
    chapters = _apply_resume_input(chapters, run, state, extra)
    return {
        "title": run.title,
        "genre_name": run.genre_name,
        "chapters": chapters,
        "outline": _state(state, "outline").get("chapters") or [],
    }


def _hot_preview(run: RunView, state: dict, extra: dict) -> dict:
    outline = _state(state, "outline")
    return {
        "title": run.title,
        "genre_name": run.genre_name,
        "chapters": _state(state, "chapter_expand").get("chapters") or [],
        "outline": outline.get("chapters") or [],
        "story_bible": outline.get("story_bible") or {},
        "research": _state(state, "genre_research"),
    }


def _apply_resume_input(chapters: list[dict], run: RunView, state: dict, extra: dict) -> list[dict]:
    resume_input = (extra.get("resume_input") if extra else None) or {}
    chapter_no = resume_input.get("chapter_no")
    content = resume_input.get("content")
    if not chapter_no or not content:
        return chapters
    patched = []
    for chapter in chapters:
        item = dict(chapter)
        if int(item.get("chapter") or 0) == int(chapter_no):
            item["content"] = str(content)
            item["word_count"] = len(str(content))
        patched.append(item)
    return patched


def _decompose(run: RunView, state: dict, extra: dict) -> dict:
    return {
        "title": run.title,
        "source_text": (extra or {}).get("source_text") or "",
        "target_chapters": int((extra or {}).get("target_chapters") or 0),
    }


def _outline_options(extra: dict) -> dict:
    """创作高级选项：目标章数与续写章数；0 表示沿用模式默认。"""
    options = (extra or {}).get("options") or {}
    return {
        "target_chapters": int(options.get("target_chapters") or 0),
        "sequel_chapters": int(options.get("sequel_chapters") or 0),
    }


def _adaptation(run: RunView, state: dict, extra: dict) -> dict:
    source = _state(state, "outline_decompose")
    payload = {
        "title": run.title,
        "book_summary": source.get("book_summary") or "",
        "story_bible": source.get("story_bible") or {},
        "characters": source.get("characters") or [],
        "factions": source.get("factions") or [],
        "items": source.get("items") or [],
        "chapters": source.get("chapters") or [],
    }
    options = (extra or {}).get("options") or {}
    style = str(options.get("adaptation_style") or "").strip()
    if style:
        payload["style"] = style
    requirements = str(options.get("adaptation_extra") or "").strip()
    if requirements:
        payload["requirements"] = requirements
    return payload


def _reference_outline(run: RunView, state: dict, extra: dict) -> dict:
    return {
        "title": run.title,
        "audience": run.audience,
        "length": run.length,
        "genre_name": run.genre_name,
        "brief": run.brief,
        "research": {},
        "decomposition": _state(state, "outline_decompose"),
        "adaptation": _state(state, "adaptation"),
        **_outline_options(extra),
    }


def _custom_outline(run: RunView, state: dict, extra: dict) -> dict:
    return {
        "title": run.title,
        "audience": run.audience,
        "length": run.length,
        "genre_name": run.genre_name,
        "brief": run.brief,
        "research": {},
        "decomposition": {},
        "adaptation": {},
        **_outline_options(extra),
    }


HOT = Graph(
    mode="hot",
    nodes=(
        NodeSpec("genre_research", "genre_research", "同题材调研", (), _hot_research),
        NodeSpec("outline", "outline", "大纲规划", ("genre_research",), _hot_outline),
        NodeSpec(
            "chapter_expand",
            "chapter_write",
            "前三章正文",
            ("outline",),
            _expand,
            chaptered=True,
        ),
        NodeSpec("hot_preview", "hot_preview", "前三章概览", ("chapter_expand", "outline"), _hot_preview),
        NodeSpec(
            "chapter_summarize",
            "chapter_summarize",
            "章节概括",
            ("chapter_expand",),
            _summarize,
            chaptered=True,
        ),
        NodeSpec(
            "character_graph",
            "lore_extract",
            "角色/势力/道具功法抽取",
            ("outline", "chapter_expand", "chapter_summarize"),
            _lore,
        ),
        NodeSpec(
            "review",
            "review",
            "签约体检",
            ("chapter_expand", "outline", "hot_preview", "chapter_summarize", "character_graph"),
            _review_from_expand,
        ),
    ),
)

REFERENCE = Graph(
    mode="reference",
    nodes=(
        NodeSpec(
            "outline_decompose",
            "outline_decompose",
            "参考作品拆解",
            (),
            _decompose,
            segmented=True,
        ),
        NodeSpec("adaptation", "adaptation", "去抄袭改编", ("outline_decompose",), _adaptation),
        NodeSpec("outline", "outline", "新书大纲", ("adaptation",), _reference_outline),
        NodeSpec(
            "chapter_expand",
            "chapter_write",
            "章节正文",
            ("outline",),
            _expand_reference,
            chaptered=True,
        ),
        NodeSpec(
            "chapter_summarize",
            "chapter_summarize",
            "章节概括",
            ("chapter_expand",),
            _summarize,
            chaptered=True,
        ),
        NodeSpec(
            "character_graph",
            "lore_extract",
            "角色/势力/道具功法抽取",
            ("adaptation", "outline", "chapter_expand", "chapter_summarize"),
            _lore,
        ),
        NodeSpec(
            "review",
            "review",
            "签约体检",
            ("chapter_expand", "outline", "chapter_summarize", "character_graph"),
            _review_from_expand,
        ),
    ),
)

CUSTOM = Graph(
    mode="custom",
    nodes=(
        NodeSpec("outline", "outline", "大纲规划", (), _custom_outline),
        NodeSpec(
            "chapter_expand",
            "chapter_write",
            "章节正文",
            ("outline",),
            _expand,
            chaptered=True,
        ),
        NodeSpec(
            "chapter_summarize",
            "chapter_summarize",
            "章节概括",
            ("chapter_expand",),
            _summarize,
            chaptered=True,
        ),
        NodeSpec(
            "character_graph",
            "lore_extract",
            "角色/势力/道具功法抽取",
            ("outline", "chapter_expand", "chapter_summarize"),
            _lore,
        ),
        NodeSpec(
            "review",
            "review",
            "签约体检",
            ("chapter_expand", "outline", "chapter_summarize", "character_graph"),
            _review_from_expand,
        ),
    ),
)

GRAPHS = {"hot": HOT, "reference": REFERENCE, "custom": CUSTOM}


def get_graph(mode: str) -> Graph:
    graph = GRAPHS.get(mode)
    if graph is None:
        raise KeyError(f"未知写作模式：{mode}")
    return graph


for _graph in GRAPHS.values():
    _graph.validate()
