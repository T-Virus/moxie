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
    # soft：失败后置 paused 让用户可续跑；fail：直接置 failed（用于不可恢复的前置校验节点）
    # auto（默认）：engine 按 outcome.error_code 自动推断（不可恢复的 code 仍置 failed）
    retry_policy: str = "auto"
    # 分段节点：由引擎按 segmenter 规划逐段执行并写段级 checkpoint
    segmented: bool = False
    # 章级节点：由引擎按 builder 给出的 chapters 逐章执行并写章级 checkpoint
    chaptered: bool = False
    # 主线程串行节点：需要复用引擎 session 查询模型配置，不能放进并发线程池
    serial: bool = False


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
    # 热门创作输出全书大纲与全部章节概括，但正文仍只写黄金三章。
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
        **_outline_options(extra),
        "mode": run.mode,
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


def _publish(run: RunView, state: dict, extra: dict) -> dict:
    """发布包：三种模式通用导出。hot 多带 positioning/settings；reference/custom 这些字段为空 dict。"""
    return {
        "title": run.title,
        "genre_name": run.genre_name,
        "mode": run.mode,
        "chapters": [],
        "outline": _state(state, "outline").get("chapters") or [],
        "positioning": _state(state, "positioning"),
        "settings": _state(state, "settings"),
        "adaptation": _state(state, "adaptation"),
        "review": _state(state, "review_merge"),
    }


def _summarize(run: RunView, state: dict, extra: dict) -> dict:
    """全量章节概括：有正文时用正文，无正文模式直接用章纲生成。

    hot 的正文只覆盖前三章，reference/custom 不写正文，但任务结果必须覆盖全书所有卷章，
    因此以完整章纲为基础合并正文，而不是只截取已写章节。
    """
    outline = list((_state(state, "outline") or {}).get("chapters") or [])
    written = list((_state(state, "chapter_expand") or {}).get("chapters") or [])
    written_by_no = {
        int(item.get("chapter") or index): item
        for index, item in enumerate(written, 1)
        if isinstance(item, dict)
    }
    if not outline:
        return {"title": run.title, "chapters": written}
    merged: list[dict] = []
    for index, item in enumerate(outline, 1):
        if not isinstance(item, dict):
            continue
        number = int(item.get("chapter") or index)
        row = dict(item)
        row["chapter_no"] = number
        body = written_by_no.get(number)
        if body:
            row.update(
                {
                    key: value
                    for key, value in body.items()
                    if value not in (None, "", [], {})
                }
            )
            row["summary"] = text_of(body.get("summary")) or text_of(item.get("summary"))
        merged.append(row)
    return {"title": run.title, "chapters": merged}


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


def _review_input(run: RunView, state: dict, extra: dict) -> dict:
    """review 双路径体检：优先取正文节点的 chapters，没有就用章纲做体检。

    可能的正文来源（按优先级）：
    - chapter_expand：hot 模式黄金三章
    - chapter_write：未来章节节点
    - adaptation：reference 模式改编产出的章节
    - chapter_summarize：兜底——如果上述都没有，用章节概括作为输入
    如果上述都没有，最后退化为只看 outline 章纲。
    """
    outline_chapters = list(_state(state, "outline").get("chapters") or [])
    candidate_nodes = ("chapter_expand", "chapter_write", "adaptation", "chapter_summarize")
    body_chapters: list[dict] | None = None
    for node_key in candidate_nodes:
        chapters = list(_state(state, node_key).get("chapters") or [])
        if chapters:
            body_chapters = chapters
            break
    return {
        "title": run.title,
        "genre_name": run.genre_name,
        "chapters": body_chapters if body_chapters is not None else outline_chapters,
        "outline": outline_chapters,
        "positioning": _state(state, "positioning"),
        "settings": _state(state, "settings"),
    }


def _consistency_input(run: RunView, state: dict, extra: dict) -> dict:
    """consistency_review 输入：只给设定一致性检查需要的字段。"""
    return _review_input(run, state, extra)


def _compliance_input(run: RunView, state: dict, extra: dict) -> dict:
    """compliance_review 输入：只给敏感/违禁词检查需要的字段。"""
    base = _review_input(run, state, extra)
    # compliance_review 不需要 settings，但需要 positioning（平台/雷区）
    base.pop("settings", None)
    return base


def _review_merge(run: RunView, state: dict, extra: dict) -> dict:
    """合并 consistency_review + compliance_review 两个子节点的输出。

    产出结构与原 ReviewOutput 兼容，让下游 publish 包和 artifacts 渲染无需改动。
    """
    consistency = _state(state, "consistency_review")
    compliance = _state(state, "compliance_review")
    c_issues = consistency.get("consistency_issues") or []
    c_risks = compliance.get("risks") or []
    c_issues_flat = compliance.get("compliance_issues") or []
    high_risk = bool(compliance.get("high_risk"))
    # 评分：有高危项扣 40，每条 medium 扣 15，每条 consistency issue 扣 10，baseline 90
    score = 90
    score -= 40 * sum(1 for r in c_risks if str(r.get("level", "")).lower() == "high")
    score -= 15 * sum(1 for r in c_risks if str(r.get("level", "")).lower() == "medium")
    score -= 10 * min(len(c_issues), 3)
    score = max(0, min(100, score))
    # suggestions：给一条通用建议
    suggestions: list[str] = []
    if high_risk:
        suggestions.append("存在高危违禁表达，建议先处理高危项再发布。")
    if c_issues:
        suggestions.append("对照设定基准统一人物、势力、道具的名称与立场，避免前后冲突。")
    if c_risks:
        suggestions.append("复核命中敏感词所在段落，按平台规范弱化或替换。")
    if not suggestions:
        suggestions.append("体检通过，建议继续下一章创作。")
    return {
        "title": run.title,
        "genre_name": run.genre_name,
        "score": score,
        "risks": c_risks,
        "suggestions": suggestions,
        "high_risk": high_risk,
        "consistency_issues": c_issues,
        "compliance_issues": c_issues_flat,
    }


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
        "positioning": _state(state, "positioning"),
        "settings": _state(state, "settings"),
        **_outline_options(extra),
        "mode": run.mode,
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
        "positioning": _state(state, "positioning"),
        "settings": _state(state, "settings"),
        **_outline_options(extra),
        "mode": run.mode,
    }


HOT = Graph(
    mode="hot",
    nodes=(
        # 阶段1 题材校准：先对月榜 Top10 做结构化分析，不直接生成
        NodeSpec("genre_research", "genre_research", "题材校准", (), _hot_research),
        # 阶段2 定位卡：由 AI 基于题材校准结论自动推导（主打爽点/情感基调/目标平台），无用户中途介入
        NodeSpec("positioning", "positioning", "定位卡", ("genre_research",), _hot_positioning),
        # 阶段3 设定生成：世界观/力量体系/势力/金手指 → 派生角色卡与功法道具表
        NodeSpec("settings", "settings_pack", "设定生成", ("positioning",), _hot_settings),
        # 阶段4 大纲拆解：总纲 → 分卷 → 章纲（冲突/反转/伏笔/结尾钩子）
        NodeSpec("outline", "outline", "大纲拆解", ("settings",), _hot_outline, serial=True, retry_policy="soft"),
        NodeSpec(
            "chapter_summarize",
            "chapter_summarize",
            "章节概括",
            ("outline",),
            _summarize,
            serial=True,
        ),
        NodeSpec(
            "character_graph",
            "lore_extract",
            "角色/势力/道具功法抽取",
            ("outline", "chapter_summarize", "settings"),
            _lore,
        ),
        # 阶段5 质检发布：consistency + compliance 并发执行，然后 review_merge 聚合
        NodeSpec(
            "consistency_review",
            "consistency_review",
            "设定一致性体检",
            ("outline", "chapter_summarize", "character_graph"),
            _consistency_input,
        ),
        NodeSpec(
            "compliance_review",
            "compliance_review",
            "合规体检",
            ("outline", "chapter_summarize", "character_graph"),
            _compliance_input,
        ),
        NodeSpec(
            "review_merge",
            "review_merge",
            "体检合并",
            ("consistency_review", "compliance_review"),
            _review_merge,
        ),
        NodeSpec(
            "publish",
            "publish_pack",
            "发布包",
            ("review_merge", "outline", "positioning", "settings"),
            _publish,
        ),
    ),
)

REFERENCE = Graph(
    mode="reference",
    nodes=(
        # Layer 0：positioning（无依赖）和 outline_decompose（无依赖）并发
        NodeSpec("positioning", "positioning", "定位卡", (), _hot_positioning),
        NodeSpec(
            "outline_decompose",
            "outline_decompose",
            "参考作品拆解",
            (),
            _decompose,
            segmented=True,
            retry_policy="soft",
        ),
        # Layer 1：settings 依赖 positioning；adaptation 依赖 outline_decompose（两者并发）
        NodeSpec("settings", "settings_pack", "设定生成", ("positioning",), _hot_settings),
        NodeSpec("adaptation", "adaptation", "去抄袭改编", ("outline_decompose",), _adaptation),
        # Layer 2：outline 依赖 settings + adaptation
        NodeSpec("outline", "outline", "新书大纲", ("settings", "adaptation"), _reference_outline, serial=True, retry_policy="soft"),
        # Layer 3：summarize + lore 并发
        NodeSpec(
            "chapter_summarize",
            "chapter_summarize",
            "章节概括",
            ("outline",),
            _summarize,
            serial=True,
        ),
        NodeSpec(
            "character_graph",
            "lore_extract",
            "角色/势力/道具功法抽取",
            ("settings", "adaptation", "outline", "chapter_summarize"),
            _lore,
        ),
        # Layer 4：consistency + compliance 并发，然后 merge
        NodeSpec(
            "consistency_review",
            "consistency_review",
            "设定一致性体检",
            ("outline", "chapter_summarize", "character_graph"),
            _consistency_input,
        ),
        NodeSpec(
            "compliance_review",
            "compliance_review",
            "合规体检",
            ("outline", "chapter_summarize", "character_graph"),
            _compliance_input,
        ),
        NodeSpec(
            "review_merge",
            "review_merge",
            "体检合并",
            ("consistency_review", "compliance_review"),
            _review_merge,
        ),
        # Layer 5：publish
        NodeSpec(
            "publish",
            "publish_pack",
            "发布包",
            ("review_merge", "outline", "positioning", "settings"),
            _publish,
        ),
    ),
)

CUSTOM = Graph(
    mode="custom",
    nodes=(
        # Layer 0：positioning
        NodeSpec("positioning", "positioning", "定位卡", (), _hot_positioning),
        # Layer 1：settings 依赖 positioning
        NodeSpec("settings", "settings_pack", "设定生成", ("positioning",), _hot_settings),
        # Layer 2：outline 依赖 settings
        NodeSpec("outline", "outline", "大纲规划", ("settings",), _custom_outline, serial=True, retry_policy="soft"),
        # Layer 3：summarize + lore 并发
        NodeSpec(
            "chapter_summarize",
            "chapter_summarize",
            "章节概括",
            ("outline",),
            _summarize,
            serial=True,
        ),
        NodeSpec(
            "character_graph",
            "lore_extract",
            "角色/势力/道具功法抽取",
            ("settings", "outline", "chapter_summarize"),
            _lore,
        ),
        # Layer 4：consistency + compliance 并发，然后 merge
        NodeSpec(
            "consistency_review",
            "consistency_review",
            "设定一致性体检",
            ("outline", "chapter_summarize", "character_graph"),
            _consistency_input,
        ),
        NodeSpec(
            "compliance_review",
            "compliance_review",
            "合规体检",
            ("outline", "chapter_summarize", "character_graph"),
            _compliance_input,
        ),
        NodeSpec(
            "review_merge",
            "review_merge",
            "体检合并",
            ("consistency_review", "compliance_review"),
            _review_merge,
        ),
        # Layer 5：publish
        NodeSpec(
            "publish",
            "publish_pack",
            "发布包",
            ("review_merge", "outline", "positioning", "settings"),
            _publish,
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
