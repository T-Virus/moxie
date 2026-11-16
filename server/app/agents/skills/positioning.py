# -*- coding: utf-8 -*-
"""定位卡：基于阶段1「题材校准」的月榜 Top10 结构化分析，
自动收敛为平台适配方向、题材边界、情绪基调、爽点偏好与雷区。
不依赖用户额外输入，是设定与大纲的定位锚点。
"""

from __future__ import annotations

import json

from pydantic import Field

from ..contracts import SkillContext, StrictModel, call_json, text_of
from .base import BaseSkill


class PositioningInput(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    genre_name: str = Field(min_length=1, max_length=60)
    audience: str = Field(pattern="^(male|female)$")
    length: str = Field(pattern="^(long|short)$")
    research: dict = Field(default_factory=dict)


class PositioningOutput(StrictModel):
    platform: str = ""
    platform_direction: str = ""
    genre_boundary: str = ""
    emotional_tone: str = ""
    highlight_preferences: list[str] = Field(default_factory=list)
    taboos: list[str] = Field(default_factory=list)
    summary: str = ""


SYSTEM = "你是网文策划编辑，只输出 JSON，结论必须具体可执行。"

PROMPT = """【技能 positioning】
书名：{title}　题材：{genre}　读者：{audience}　篇幅：{length}

题材校准结论（月榜 Top10 结构化分析）：
{research}

请完全基于上述榜单分析结论推导本书的「定位卡」：
- platform：根据题材与读者群推断最适配的发布平台（如番茄/起点/晋江），给出明确平台名；
- platform_direction：该平台的读者习惯适配方向，2-3 句，须引用榜单分析的节奏与钩子结论；
- genre_boundary：题材边界，写清楚必写什么、禁写什么，须结合反套路空间结论；
- emotional_tone：情绪基调与爽感配比，须结合冲突密度与开篇节奏结论；
- highlight_preferences：从榜单主流爽点类型中挑出本书主打 2-4 个；
- taboos：从反套路空间与榜单避坑结论推导雷区 2-5 条。
输出 JSON：
{{"platform":"目标平台",
 "platform_direction":"平台适配方向，2-3 句",
 "genre_boundary":"题材边界：必写 / 禁写",
 "emotional_tone":"情绪基调与爽感配比",
 "highlight_preferences":["主打爽点"],
 "taboos":["雷区"],
 "summary":"一句话定位"}}
"""


def _research_dimensions(research: dict) -> dict:
    return {
        "hooks": [text_of(item) for item in (research.get("hooks") or []) if text_of(item)][:6],
        "highlight_types": [
            text_of(item) for item in (research.get("highlight_types") or []) if text_of(item)
        ][:6],
        "conflict_density": text_of(research.get("conflict_density")),
        "opening_pace": text_of(research.get("opening_pace")),
        "anti_cliche": [
            text_of(item) for item in (research.get("anti_cliche") or []) if text_of(item)
        ][:6],
        "takeaways": [text_of(item) for item in (research.get("takeaways") or []) if text_of(item)][:6],
    }


def _fallback(payload: PositioningInput) -> PositioningOutput:
    dims = _research_dimensions(payload.research or {})
    platform = "番茄" if payload.audience == "male" and payload.length == "long" else "通用平台"
    if payload.audience == "female":
        platform = "晋江"
    highlights = dims["highlight_types"] or ["打脸反转", "阶段性升级"]
    anti = dims["anti_cliche"]
    taboos = [f"不{item[:12]}" if not item.startswith("不") else item[:14] for item in anti[:4]]
    taboos = taboos or ["不降智", "不强行误会", "不写纯工具人反派"]
    opening = dims["opening_pace"] or "第一章直入危机，三章内完成第一次兑现"
    density = dims["conflict_density"] or "每章 2-3 个冲突点，章末必有对抗"
    return PositioningOutput(
        platform=platform,
        platform_direction=(
            f"面向{platform}读者：按榜单结论「{opening}」控制开篇，"
            f"「{density}」维持冲突密度，每章结尾留可执行问题。"
        ),
        genre_boundary=(
            f"必写：{payload.genre_name}题材的核心看点与榜单共性钩子；"
            f"禁写：慢热铺垫、与主线无关的设定堆砌；反套路空间：{'；'.join(anti[:2]) or '在套路内做差异化人设'}。"
        ),
        emotional_tone="快节奏、强冲突为骨架，间歇给 1-2 处情绪落点（8:2）",
        highlight_preferences=highlights[:4],
        taboos=taboos,
        summary=(
            f"《{payload.title}》：面向{platform}的{payload.genre_name}作品，"
            f"以「{highlights[0]}」为主要爽点驱动。"
        ),
    )


class PositioningSkill(BaseSkill):
    name = "positioning"
    version = "1.1.0"
    input_model = PositioningInput
    output_model = PositioningOutput

    def run(self, payload: PositioningInput, ctx: SkillContext) -> PositioningOutput:
        fallback = _fallback(payload)
        research_view = _research_dimensions(payload.research)
        data = call_json(
            ctx,
            system=SYSTEM,
            user=PROMPT.format(
                title=payload.title,
                genre=payload.genre_name,
                audience="男频" if payload.audience == "male" else "女频",
                length="长篇" if payload.length == "long" else "短篇",
                research=json.dumps(research_view, ensure_ascii=False)[:3000],
            ),
        )
        platform = text_of(data.get("platform")) or fallback.platform
        result = PositioningOutput(
            platform=platform[:60],
            platform_direction=text_of(data.get("platform_direction")) or fallback.platform_direction,
            genre_boundary=text_of(data.get("genre_boundary")) or fallback.genre_boundary,
            emotional_tone=text_of(data.get("emotional_tone")) or fallback.emotional_tone,
            highlight_preferences=(
                [text_of(item) for item in (data.get("highlight_preferences") or []) if text_of(item)][:6]
                or fallback.highlight_preferences
            ),
            taboos=(
                [text_of(item) for item in (data.get("taboos") or []) if text_of(item)][:8]
                or fallback.taboos
            ),
            summary=text_of(data.get("summary")) or fallback.summary,
        )
        ctx.log(f"定位卡完成：平台={result.platform}（由榜单分析推导）")
        return result
