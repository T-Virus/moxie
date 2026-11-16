# -*- coding: utf-8 -*-
"""内容体检：只核对设定一致性与敏感/违禁表达，不做签约或商业价值评估。高危命中会让编排引擎暂停。"""

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
    # 内容体检产出：设定一致性、敏感/违禁表达
    consistency_issues: list[str] = Field(default_factory=list)
    compliance_issues: list[str] = Field(default_factory=list)


SYSTEM = "你是网文内容合规审读编辑，只输出 JSON，不做签约或商业价值评估。"

PROMPT = """【技能 review】
书名：{title}　题材：{genre}
目标平台：{platform}　雷区：{taboos}
设定基准（人物/势力/道具以此为准）：
{settings}

只核对下列三类问题，不评价开篇吸引力、爽点节奏、人物动机、复制风险或是否可签约：
1. 设定一致性：人物、势力、道具、称谓与时间线是否与设定基准冲突；章纲与章节概括/正文的覆盖是否一致；
2. 敏感词：低俗、血腥暴力、自伤自残等平台敏感表达；
3. 违禁词：违法违规、赌博、毒品、色情交易、诈骗等明确禁止内容，以及用户列出的雷区。
正常剧情表达不要误报；只有明确违禁才标 high，敏感表达标 medium/low。
输出 JSON：
{{"score":0,
 "risks":[{{"level":"high/medium/low","code":"","message":"","chapter":1}}],
 "suggestions":[""],
 "consistency_issues":[""],
 "compliance_issues":[""]}}

待核对内容：
{material}
"""

FORBIDDEN_WORDS = ("赌博", "毒品", "贩毒", "制毒", "诈骗", "枪支", "爆炸物", "色情交易", "走私")
SENSITIVE_WORDS = ("血腥", "虐杀", "自残", "自杀", "低俗", "粗口")

FALLBACK_SUGGESTIONS = [
    "复核命中词所在段落，按平台规范弱化或替换敏感/违禁表达。",
    "对照设定基准统一人物、势力、道具的名称与立场，避免前后冲突。",
    "把用户雷区加入发布前检查清单，逐章确认没有遗漏。",
]


def _local_risks(payload: ReviewInput) -> list[ReviewRisk]:
    """确定性兜底：只扫敏感/违禁词与用户雷区，不评判作品质量。"""
    risks: list[ReviewRisk] = []
    if not payload.chapters and not payload.outline:
        risks.append(ReviewRisk(level="medium", code="no_material", message="没有可核对的章纲或章节内容"))
        return risks
    taboos = [text_of(item) for item in (payload.positioning or {}).get("taboos") or [] if text_of(item)]
    for index, chapter in enumerate(payload.chapters, 1):
        body = text_of(chapter.get("content")) or text_of(chapter.get("summary"))
        no = int(chapter.get("chapter") or index)
        for word in FORBIDDEN_WORDS:
            if word in body:
                risks.append(
                    ReviewRisk(level="high", code="forbidden_word", message=f"命中违禁表达：{word}", chapter=no)
                )
        for word in SENSITIVE_WORDS:
            if word in body:
                risks.append(
                    ReviewRisk(level="medium", code="sensitive_word", message=f"命中敏感表达：{word}", chapter=no)
                )
        for word in taboos:
            if word in body:
                risks.append(
                    ReviewRisk(level="medium", code="taboo", message=f"命中用户雷区：{word}", chapter=no)
                )
    return risks


def _local_consistency(payload: ReviewInput) -> list[str]:
    """确定性一致性检查：章纲与待核内容的章节覆盖对齐。"""
    issues: list[str] = []
    if not payload.outline:
        return issues
    provided = {int(c.get("chapter") or i) for i, c in enumerate(payload.chapters, 1)}
    planned = {int(c.get("chapter") or i) for i, c in enumerate(payload.outline, 1)}
    missing = sorted(planned - provided)
    if missing:
        issues.append(f"章纲规划了 {len(planned)} 章，待核内容只覆盖 {len(provided)} 章（缺第 {missing[:6]} 章）")
    return issues


class ReviewSkill(BaseSkill):
    name = "review"
    version = "1.0.0"
    input_model = ReviewInput
    output_model = ReviewOutput

    def run(self, payload: ReviewInput, ctx: SkillContext) -> ReviewOutput:
        fallback_risks = _local_risks(payload)
        consistency_fallback = _local_consistency(payload)
        material = {
            "chapters": [
                {
                    "chapter": c.get("chapter") or i,
                    "title": c.get("title"),
                    "content": text_of(c.get("content"))[:1200] or text_of(c.get("summary"))[:300],
                    "hook": c.get("hook") or "",
                }
                for i, c in enumerate(payload.chapters, 1)
            ],
            "outline": [
                {
                    "chapter": c.get("chapter") or i,
                    "title": c.get("title"),
                    "summary": text_of(c.get("summary"))[:300],
                    "key_events": c.get("key_events") or [],
                }
                for i, c in enumerate(payload.outline, 1)
            ][:200],
        }
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
            f"内容体检完成：score={score}，高危={high_risk}，一致性={len(consistency_issues)}，合规={len(compliance_issues)}"
        )
        return ReviewOutput(
            score=score,
            risks=risks[:20],
            suggestions=suggestions,
            high_risk=high_risk,
            consistency_issues=consistency_issues,
            compliance_issues=compliance_issues,
        )
