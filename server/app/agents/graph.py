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
from .memory import build_context, from_desktop_index

# 云端正文链默认篇幅：黄金三章。限制 adapt_chapters / managed_chars 额度占用。
# 全本分段调度：options.body_start / body_chapters 可指定窗口（第几章起、写几章），
# 或 options.body_segment（第几段，按 body_chapters 大小切片），逐段串行完成整本；
# 默认值仍是黄金三章，保证未显式配置的 run 行为不变。上限由 Settings 注入 extra。
CLOUD_BODY_CHAPTERS = 3
CLOUD_BODY_MAX_CHAPTERS = 2000


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


def _body_chapters(state: dict) -> list[dict]:
    """规范正文：润色后正文优先，回退到原始写作正文。

    humanizer 在 2026-11-18 进入三图，state["polish"] 含去 AI 味后的章节；
    概括/体检/实体抽取/产物落盘统一读这里，避免发布未润色的初稿。
    """
    for key in ("polish", "chapter_expand", "chapter_write"):
        chapters = [item for item in (_state(state, key).get("chapters") or []) if isinstance(item, dict)]
        if chapters:
            return chapters
    return []


def _hot_research(run: RunView, state: dict, extra: dict) -> dict:
    return {
        "title": run.title,
        "genre_id": run.genre_id,
        "genre_name": run.genre_name,
        "audience": run.audience,
        "length": run.length,
    }


def _hot_outline(run: RunView, state: dict, extra: dict) -> dict:
    # 热门创作输出全书大纲与全部章节概括；正文链已在 outline 之后恢复为
    # chapter_expand（chaptered=True，黄金三章），详见 graphs 中节点声明。
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
    """发布包：三种模式通用导出。

    publish_pack 的 output_model 只保留 tags/blurb/cover_prompt 等包装字段，
    传进来的 chapters 会被裁剪，不落到 state["publish"]。正文产物始终由
    artifacts.write_artifacts 从 state["chapter_expand"] 生成；2026-11-18
    正文链恢复后该 checkpoint 非空，发布包仍只负责包装材料，不含正文。
    """
    return {
        "title": run.title,
        "genre_name": run.genre_name,
        "chapters": [],
        "outline": _state(state, "outline").get("chapters") or [],
        "positioning": _state(state, "positioning"),
        "settings": _state(state, "settings"),
        "review": _state(state, "review_merge"),
    }


def _summarize(run: RunView, state: dict, extra: dict) -> dict:
    """全量章节概括：黄金三章已有正文时用正文，其余章节用完整章纲生成。

    2026-11-18 正文链恢复后，state["chapter_expand"] 含黄金三章正文；以下合并逻辑
    按章号把正文覆盖到完整章纲上，未写正文的章节仍来自章纲。任务结果需覆盖全书
    所有卷章，因此始终以完整章纲为基础。
    """
    outline = list((_state(state, "outline") or {}).get("chapters") or [])
    outline_data = _state(state, "outline")
    # 章级规划字段：目标字数与叙事视角来自整书大纲，逐章透传给概括技能
    default_words = int(outline_data.get("chapter_words_target") or 0)
    person = text_of(outline_data.get("person"))
    written = _body_chapters(state)
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
        if default_words and not row.get("word_target"):
            row["word_target"] = default_words
        if person and not row.get("pov"):
            row["pov"] = person
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
        "chapters": _body_chapters(state),
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
    - polish：humanizer 润色后的正文（2026-11-18 起三图均有该节点）
    - chapter_expand：黄金三章原始正文
    - chapter_write：历史章节节点
    - adaptation：reference 模式改编产出的章节
    - chapter_summarize：兜底——如果上述都没有，用章节概括作为输入
    如果上述都没有，最后退化为只看 outline 章纲。
    """
    outline_chapters = list(_state(state, "outline").get("chapters") or [])
    candidate_nodes = ("polish", "chapter_expand", "chapter_write", "adaptation", "chapter_summarize")
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


def _body_window(chapters: list[dict], options: dict, extra: dict) -> list[dict]:
    """计算本次 run 的正文窗口（全本分段调度的核心）。

    - 无 options：取前 CLOUD_BODY_CHAPTERS 章（默认黄金三章，行为不变）。
    - ``body_start`` + ``body_chapters``：从第 N 章起写 M 章。
    - ``body_segment``（1-based）+ ``body_chapters``：按窗口大小切第 K 段。
    上限取 extra["body_max_chapters"]（由 Settings 注入），缺省 CLOUD_BODY_MAX_CHAPTERS。
    每章注入稳定的 ``chapter`` 章号，跨段不重编号。
    """
    size = int(extra.get("body_default_chapters") or CLOUD_BODY_CHAPTERS)
    try:
        size = max(1, min(int(options.get("body_chapters") or size), int(extra.get("body_max_chapters") or CLOUD_BODY_MAX_CHAPTERS)))
    except (TypeError, ValueError):
        size = CLOUD_BODY_CHAPTERS
    start = 1
    segment = options.get("body_segment")
    if segment not in (None, ""):
        try:
            start = (max(1, int(segment)) - 1) * size + 1
        except (TypeError, ValueError):
            start = 1
    elif options.get("body_start") not in (None, ""):
        try:
            start = max(1, int(options["body_start"]))
        except (TypeError, ValueError):
            start = 1
    begin_index = max(0, start - 1)
    window = chapters[begin_index : begin_index + size]
    out: list[dict] = []
    for offset, chapter in enumerate(window):
        row = dict(chapter)
        row["chapter"] = int(chapter.get("chapter") or (begin_index + offset + 1))
        out.append(row)
    return out


def _expand(run: RunView, state: dict, extra: dict) -> dict:
    """正文节点 builder：取一个正文窗口（默认黄金三章），注入跨章记忆。

    全本分段调度由 ``options.body_start/body_chapters/body_segment`` 控制窗口；
    前情检索用 build_context 生成，写入 chapter_write.memory_context，
    写第 N 章时能读到前序章节的人名、钩子与已写正文（跨段记忆）。
    """
    outline = _state(state, "outline")
    chapters = [dict(item) for item in (outline.get("chapters") or []) if isinstance(item, dict)]
    options = (extra or {}).get("options") or {}
    # 统一记忆索引：若导入桌面 memory_index.json，用它替代章纲做检索源，
    # 云端与桌面共用同一套稳定 ID / 摘要 / 专名 / 词频，避免两套索引各算各的。
    index_source = chapters
    desktop_index = options.get("desktop_memory_index")
    if isinstance(desktop_index, dict):
        imported = from_desktop_index(desktop_index)
        if imported:
            index_source = imported
    # 跨段记忆：上一分段已写正文作为检索源并入，保证第 2 段能接住第 1 段的人名/伏笔。
    # 同章号时用已写正文覆盖章纲条目（content 含真实专名/结尾），而非跳过。
    prior = [dict(item) for item in (_state(state, "chapter_expand").get("chapters") or []) if isinstance(item, dict)]
    if prior:
        # 若是导入的桌面索引，保持其结构并按需覆盖；否则基于章纲列表
        index_source = [dict(item) for item in index_source]
        pos_of: dict[int, int] = {}
        for pos, item in enumerate(index_source):
            no = int(item.get("no") or item.get("chapter") or 0)
            if no:
                pos_of[no] = pos
        for row in prior:
            no = int(row.get("no") or row.get("chapter") or 0)
            if not no:
                continue
            if no in pos_of and any(str(row.get(k) or "") for k in ("content", "head", "tail")):
                # 合并：保留章纲字段，补入已写正文的 content/summary
                merged = {**index_source[pos_of[no]], **{k: v for k, v in row.items() if v}}
                index_source[pos_of[no]] = merged
            elif no not in pos_of:
                index_source.append(row)
                pos_of[no] = len(index_source) - 1
    selected = _body_window(chapters, options, extra)
    with_memory: list[dict] = []
    for chapter in selected:
        row = dict(chapter)
        # build_context 只看前序章节；此时正文未生成，用章纲概括（或导入的桌面索引/已写正文）做索引源
        row["memory_context"] = build_context(index_source, row)
        with_memory.append(row)
    return {
        "title": run.title,
        "genre_name": run.genre_name,
        "story_bible": outline.get("story_bible") or _settings_bible(_state(state, "settings")),
        "chapters": with_memory,
    }


def _polish(run: RunView, state: dict, extra: dict) -> dict:
    """润色节点 builder：把黄金三章正文交给 humanizer 去 AI 味。"""
    return {
        "title": run.title,
        "genre_name": run.genre_name,
        "chapters": [dict(item) for item in (_state(state, "chapter_expand").get("chapters") or []) if isinstance(item, dict)],
    }


def _continuity(run: RunView, state: dict, extra: dict) -> dict:
    """连续性核查 builder：汇总云端台账与可选导入的桌面台账做交叉比对。"""
    outline = _state(state, "outline")
    options = (extra or {}).get("options") or {}
    return {
        "title": run.title,
        "chapters": [dict(item) for item in (_state(state, "chapter_summarize").get("chapters") or []) if isinstance(item, dict)],
        "outline": [dict(item) for item in (outline.get("chapters") or []) if isinstance(item, dict)],
        "foreshadow_ledger": [dict(item) for item in (outline.get("foreshadow_ledger") or []) if isinstance(item, dict)],
        "desktop_ledger": [dict(item) for item in (options.get("desktop_ledger") or []) if isinstance(item, dict)],
        "settings": _state(state, "settings"),
        "characters": [dict(item) for item in (_state(state, "character_graph").get("characters") or []) if isinstance(item, dict)],
    }


def _cover(run: RunView, state: dict, extra: dict) -> dict:
    """封面方案 builder：从大纲 book_meta / 定位卡取书名署名，交给 cover_plan 技能。"""
    outline = _state(state, "outline")
    positioning = _state(state, "positioning")
    book_meta = {
        **{k: v for k, v in outline.items() if k in ("author", "themes", "story_bible")},
        **(outline.get("book_meta") or {}),
    }
    options = (extra or {}).get("options") or {}
    return {
        "title": run.title,
        "genre_name": run.genre_name,
        "author": text_of(book_meta.get("author")) or text_of((outline.get("story_bible") or {}).get("author")),
        "outline": book_meta,
        "prompt": text_of(options.get("cover_prompt")),
        "style": text_of(options.get("cover_style")) or "gold",
        "layout": text_of(options.get("cover_layout")) or "top",
        "width": int(options.get("cover_width") or 600),
        "height": int(options.get("cover_height") or 800),
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
        # 阶段4.5 正文闭环（2026-11-18 恢复）：黄金三章 → 润色，再进入概括/体检
        NodeSpec(
            "chapter_expand",
            "chapter_write",
            "黄金三章正文",
            ("outline",),
            _expand,
            chaptered=True,
        ),
        NodeSpec("polish", "humanizer", "去 AI 味润色", ("chapter_expand",), _polish),
        NodeSpec(
            "chapter_summarize",
            "chapter_summarize",
            "章节概括",
            ("outline", "chapter_expand", "polish"),
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
        NodeSpec(
            "continuity_check",
            "continuity_check",
            "连续性四维核查表",
            ("outline", "chapter_summarize", "character_graph"),
            _continuity,
        ),
        # 阶段5 质检发布：consistency + compliance 并发执行，然后 review_merge 聚合
        NodeSpec(
            "consistency_review",
            "consistency_review",
            "设定一致性体检",
            ("outline", "chapter_summarize", "character_graph", "continuity_check"),
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
        NodeSpec("cover_plan", "cover_plan", "封面方案", ("outline", "positioning", "settings"), _cover),
        NodeSpec(
            "publish",
            "publish_pack",
            "发布包",
            ("review_merge", "outline", "positioning", "settings", "cover_plan"),
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
        ),
        # Layer 1：settings 依赖 positioning；adaptation 依赖 outline_decompose（两者并发）
        NodeSpec("settings", "settings_pack", "设定生成", ("positioning",), _hot_settings),
        NodeSpec("adaptation", "adaptation", "去抄袭改编", ("outline_decompose",), _adaptation),
        # Layer 2：outline 依赖 settings + adaptation
        NodeSpec("outline", "outline", "新书大纲", ("settings", "adaptation"), _reference_outline, serial=True, retry_policy="soft"),
        # Layer 3：正文闭环 —— 黄金三章 → 润色 → 概括/抽取
        NodeSpec(
            "chapter_expand",
            "chapter_write",
            "黄金三章正文",
            ("outline",),
            _expand,
            chaptered=True,
        ),
        NodeSpec("polish", "humanizer", "去 AI 味润色", ("chapter_expand",), _polish),
        NodeSpec(
            "chapter_summarize",
            "chapter_summarize",
            "章节概括",
            ("outline", "chapter_expand", "polish"),
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
        NodeSpec(
            "continuity_check",
            "continuity_check",
            "连续性四维核查表",
            ("outline", "chapter_summarize", "character_graph"),
            _continuity,
        ),
        # Layer 4：consistency + compliance 并发，然后 merge
        NodeSpec(
            "consistency_review",
            "consistency_review",
            "设定一致性体检",
            ("outline", "chapter_summarize", "character_graph", "continuity_check"),
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
        # Layer 5：封面方案 + publish
        NodeSpec("cover_plan", "cover_plan", "封面方案", ("outline", "positioning", "settings"), _cover),
        NodeSpec(
            "publish",
            "publish_pack",
            "发布包",
            ("review_merge", "outline", "positioning", "settings", "cover_plan"),
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
        # Layer 3：正文闭环 —— 黄金三章 → 润色 → 概括/抽取
        NodeSpec(
            "chapter_expand",
            "chapter_write",
            "黄金三章正文",
            ("outline",),
            _expand,
            chaptered=True,
        ),
        NodeSpec("polish", "humanizer", "去 AI 味润色", ("chapter_expand",), _polish),
        NodeSpec(
            "chapter_summarize",
            "chapter_summarize",
            "章节概括",
            ("outline", "chapter_expand", "polish"),
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
        NodeSpec(
            "continuity_check",
            "continuity_check",
            "连续性四维核查表",
            ("outline", "chapter_summarize", "character_graph"),
            _continuity,
        ),
        # Layer 4：consistency + compliance 并发，然后 merge
        NodeSpec(
            "consistency_review",
            "consistency_review",
            "设定一致性体检",
            ("outline", "chapter_summarize", "character_graph", "continuity_check"),
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
        # Layer 5：封面方案 + publish
        NodeSpec("cover_plan", "cover_plan", "封面方案", ("outline", "positioning", "settings"), _cover),
        NodeSpec(
            "publish",
            "publish_pack",
            "发布包",
            ("review_merge", "outline", "positioning", "settings", "cover_plan"),
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
