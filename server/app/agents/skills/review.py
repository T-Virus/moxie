# -*- coding: utf-8 -*-
"""签约体检与改写建议。高危问题会让编排引擎暂停，等待人工介入。"""

from __future__ import annotations

import json

from pydantic import Field

from ..contracts import SkillContext, StrictModel, call_json, list_of_dicts, text_of
from .base import BaseSkill

LEVELS = {"high", "medium", "low"}


class ReviewInput(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    genre_name: str = Field(min_length=1, max_length=60)
    chapters: list[dict] = Field(default_factory=list)
    outline: list[dict] = Field(default_factory=list)
    # 阶段6 质检输入：定位卡（平台/雷区）与设定包（一致性比对基准）
    positioning: dict = Field(default_factory=dict)
    settings: dict = Field(default_factory=dict)


class ReviewRisk(StrictModel):
    level: str = "medium"
    code: str = ""
    message: str
    chapter: int | None = None


class ReviewOutput(StrictModel):
    score: int = Field(default=0, ge=0, le=100)
    risks: list[ReviewRisk] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    high_risk: bool = False
    # 阶段6 附加产出：一致性检查（正文 vs 章纲/设定）与平台合规检查
    consistency_issues: list[str] = Field(default_factory=list)
    compliance_issues: list[str] = Field(default_factory=list)


SYSTEM = "你是网文签约审核编辑，只输出 JSON。"

PROMPT = """【技能 review】
书名：{title}　题材：{genre}
目标平台：{platform}　雷区：{taboos}
设定基准（人物/势力/道具以此为准）：
{settings}

请对下列章节做签约体检，分三部分：
1. 签约体检：开篇吸引力、节奏、人物动机、逻辑漏洞、复制风险；
2. 一致性检查：正文是否落实章纲的冲突/反转/伏笔/结尾钩子，人物、势力、道具与设定基准是否一致；
3. 平台合规检查：按目标平台的红线（低俗、血腥、违规题材、导向问题）与用户雷区逐项排查。
输出 JSON：
{{"score":0,
 "risks":[{{"level":"high/medium/low","code":"","message":"","chapter":1}}],
 "suggestions":[""],
 "consistency_issues":[""],
 "compliance_issues":[""]}}
只有确实存在会导致拒稿的问题才标 high。

章节：
{material}
"""

FALLBACK_SUGGESTIONS = [
    "前三章每章补一个「主角主动做决定」的动作，减少被动推进。",
    "章末钩子写成可执行的问题，而不是情绪感叹。",
    "给对手一个明确目标，让冲突有来有回。",
]


def _local_risks(payload: ReviewInput) -> list[ReviewRisk]:
    risks: list[ReviewRisk] = []
    if not payload.chapters:
        risks.append(ReviewRisk(level="high", code="no_chapters", message="没有可用正文章节，无法进入签约流程"))
        return risks
    for index, chapter in enumerate(payload.chapters, 1):
        body = text_of(chapter.get("content")) or text_of(chapter.get("summary"))
        no = int(chapter.get("chapter") or index)
        if len(body) < 200:
            risks.append(
                ReviewRisk(level="medium", code="thin_chapter", message="章节内容偏薄，开场冲突与人物行动不足", chapter=no)
            )
        if not text_of(chapter.get("hook")):
            risks.append(
                ReviewRisk(level="low", code="weak_hook", message="章末钩子缺失或不可执行", chapter=no)
            )
    return risks


def _local_consistency(payload: ReviewInput) -> list[str]:
    """确定性一致性检查：正文章数与章纲对齐。"""
    issues: list[str] = []
    if not payload.outline:
        return issues
    written = {int(c.get("chapter") or i) for i, c in enumerate(payload.chapters, 1)}
    planned = {int(c.get("chapter") or i) for i, c in enumerate(payload.outline, 1)}
    missing = sorted(planned - written)
    if missing:
        issues.append(f"章纲规划了 {len(planned)} 章，正文只覆盖 {len(written)} 章（缺第 {missing[:6]} 章）")
    return issues


class ReviewSkill(BaseSkill):
    name = "review"
    version = "1.0.0"
    input_model = ReviewInput
    output_model = ReviewOutput

    def run(self, payload: ReviewInput, ctx: SkillContext) -> ReviewOutput:
        fallback_risks = _local_risks(payload)
        consistency_fallback = _local_consistency(payload)
        material = [
            {
                "chapter": c.get("chapter") or i,
                "title": c.get("title"),
                "content": text_of(c.get("content"))[:1500] or text_of(c.get("summary"))[:300],
                "hook": c.get("hook") or "",
            }
            for i, c in enumerate(payload.chapters, 1)
        ]
        positioning = payload.positioning or {}
        settings = payload.settings or {}
        settings_view = {
            key: [
                {k: item.get(k) for k in ("name", "role", "stance", "kind", "category")}
                for item in list_of_dicts(settings.get(key), 6)
            ]
            for key in ("characters", "factions", "items")
            if settings.get(key)
        }
        data = call_json(
            ctx,
            system=SYSTEM,
            user=PROMPT.format(
                title=payload.title,
                genre=payload.genre_name,
                platform=text_of(positioning.get("platform")) or "未指定",
                taboos="、".join(
                    text_of(item) for item in (positioning.get("taboos") or []) if text_of(item)
                ) or "未指定",
                settings=json.dumps(settings_view, ensure_ascii=False)[:2500] or "未提供设定基准",
                material=json.dumps(material, ensure_ascii=False)[:12000],
            ),
        )
        risks: list[ReviewRisk] = []
        for item in list_of_dicts(data.get("risks")):
            level = text_of(item.get("level")).lower()
            message = text_of(item.get("message"))
            if level not in LEVELS or not message:
                continue
            chapter = item.get("chapter")
            risks.append(
                ReviewRisk(
                    level=level,
                    code=text_of(item.get("code")) or "model_flag",
                    message=message[:200],
                    chapter=int(chapter) if isinstance(chapter, (int, float)) and int(chapter) > 0 else None,
                )
            )
        risks.extend(fallback_risks)
        suggestions = [text_of(s) for s in (data.get("suggestions") or []) if text_of(s)][:6] or FALLBACK_SUGGESTIONS
        consistency_issues = [
            text_of(item) for item in (data.get("consistency_issues") or []) if text_of(item)
        ][:10] or consistency_fallback
        compliance_issues = [
            text_of(item) for item in (data.get("compliance_issues") or []) if text_of(item)
        ][:10]
        high_risk = any(r.level == "high" for r in risks)
        score = data.get("score")
        try:
            score = max(0, min(int(score), 100))
        except (TypeError, ValueError):
            score = max(0, 90 - 15 * sum(1 for r in risks if r.level == "medium") - 40 * sum(1 for r in risks if r.level == "high"))
        ctx.log(
            f"体检完成：score={score}，高危={high_risk}，一致性={len(consistency_issues)}，合规={len(compliance_issues)}"
        )
        return ReviewOutput(
            score=score,
            risks=risks[:20],
            suggestions=suggestions,
            high_risk=high_risk,
            consistency_issues=consistency_issues,
            compliance_issues=compliance_issues,
        )
