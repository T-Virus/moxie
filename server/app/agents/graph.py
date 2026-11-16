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

from .contracts import text_of


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
        "positioning": _state(state, "positioning"),
        "settings": _state(state, "settings"),
    }


def _hot_positioning(run: RunView, state: dict, extra: dict) -> dict:
    """阶段2 定位卡：完全由阶段1 校准结论（月榜 Top10 分析）推导，无用户额外输入。"""
    return {
        "title": run.title,
        "genre_name": run.genre_name,
        "audience": run.audience,
        "length": run.length,
        "research": _state(state, "genre_research"),
    }


def _hot_settings(run: RunView, state: dict, extra: dict) -> dict:
    """阶段3 设定生成：定位卡 + 校准结论 → 世界观/力量体系/金手指/角色/道具。"""
    return {
        "title": run.title,
        "genre_name": run.genre_name,
        "positioning": _state(state, "positioning"),
        "research": _state(state, "genre_research"),
    }


def _hot_publish(run: RunView, state: dict, extra: dict) -> dict:
    """阶段6 发布包：质检通过后产出标签/简介/封面提示词/续写入口。"""
    return {
        "title": run.title,
        "genre_name": run.genre_name,
        "chapters": _state(state, "chapter_expand").get("chapters") or [],
        "outline": _state(state, "outline").get("chapters") or [],
        "positioning": _state(state, "positioning"),
        "settings": _state(state, "settings"),
        "review": _state(state, "review"),
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
    # hot 模式前三章已写正文（见 _expand 的 [:3]），概括只针对其后的章节，来源读大纲剩余章；
    # reference/custom 正文已全覆盖，直接对正文章节（chapter_expand）做概括。
    if run.mode == "hot":
        chapters = list((_state(state, "outline") or {}).get("chapters") or [])[3:]
    else:
        chapters = list((_state(state, "chapter_expand") or {}).get("chapters") or [])
    return {"title": run.title, "chapters": chapters}


def _lore(run: RunView, state: dict, extra: dict) -> dict:
    adapted = _state(state, "adaptation")
    decomposed = _state(state, "outline_decompose")
    settings = _state(state, "settings")
    outline = _state(state, "outline")
    return {
        "title": run.title,
        "genre_name": run.genre_name,
        "story_bible": (
            adapted.get("story_bible")
            or decomposed.get("story_bible")
            or _settings_bible(settings)
            or outline.get("story_bible")
            or {}
        ),
        "characters": (
            adapted.get("characters")
            or decomposed.get("characters")
            or settings.get("characters")
            or []
        ),
        "factions": (
            adapted.get("factions")
            or decomposed.get("factions")
            or settings.get("factions")
            or []
        ),
        "items": adapted.get("items") or decomposed.get("items") or settings.get("items") or [],
        "chapters": _state(state, "chapter_expand").get("chapters") or [],
        "outline": outline.get("chapters") or [],
    }


def _settings_bible(settings: dict) -> dict:
    """把设定包的世界观/力量体系/金手指折叠成 story_bible 形态。"""
    worldview = text_of(settings.get("worldview"))
    if not worldview:
        return {}
    return {
        "world": worldview,
        "power": text_of(settings.get("power_system")),
        "golden_finger": text_of(settings.get("golden_finger")),
    }


def _review_from_expand(run: RunView, state: dict, extra: dict) -> dict:
    chapters = _state(state, "chapter_expand").get("chapters") or []
    chapters = _apply_resume_input(chapters, run, state, extra)
    return {
        "title": run.title,
        "genre_name": run.genre_name,
        "chapters": chapters,
        "outline": _state(state, "outline").get("chapters") or [],
        "positioning": _state(state, "positioning"),
        "settings": _state(state, "settings"),
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
        # 阶段1 题材校准：先对月榜 Top10 做结构化分析，不直接生成
        NodeSpec("genre_research", "genre_research", "题材校准", (), _hot_research),
        # 阶段2 定位卡：用户确认 男/女频、长短篇、目标平台、爽点偏好、雷区
        NodeSpec("positioning", "positioning", "定位卡", ("genre_research",), _hot_positioning),
        # 阶段3 设定生成：世界观/力量体系/势力/金手指 → 派生角色卡与功法道具表
        NodeSpec("settings", "settings_pack", "设定生成", ("positioning",), _hot_settings),
        # 阶段4 大纲拆解：总纲 → 分卷 → 章纲（冲突/反转/伏笔/结尾钩子）
        NodeSpec("outline", "outline", "大纲拆解", ("settings",), _hot_outline),
        # 阶段5 黄金三章：主角在场 + 当下危机 + 未知悬念，去AI化润色
        NodeSpec(
            "chapter_expand",
            "chapter_write",
            "黄金三章",
            ("outline",),
            _expand,
            chaptered=True,
        ),
        NodeSpec("hot_preview", "hot_preview", "前三章概览与节奏诊断", ("chapter_expand", "outline"), _hot_preview),
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
            ("outline", "chapter_expand", "chapter_summarize", "settings"),
            _lore,
        ),
        # 阶段6 质检发布：一致性检查 + 平台合规检查，然后产出发布包
        NodeSpec(
            "review",
            "review",
            "签约体检",
            ("chapter_expand", "outline", "hot_preview", "chapter_summarize", "character_graph"),
            _review_from_expand,
        ),
        NodeSpec(
            "publish",
            "publish_pack",
            "发布包",
            ("review", "chapter_expand", "outline", "positioning", "settings"),
            _hot_publish,
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
