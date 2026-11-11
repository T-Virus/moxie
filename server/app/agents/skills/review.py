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


SYSTEM = "你是网文签约审核编辑，只输出 JSON。"

PROMPT = """【技能 review】
书名：{title}　题材：{genre}
请对下列章节做签约体检：开篇吸引力、节奏、人物动机、逻辑漏洞、复制风险。
输出 JSON：
{{"score":0,
 "risks":[{{"level":"high/medium/low","code":"","message":"","chapter":1}}],
 "suggestions":[""]}}
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


class ReviewSkill(BaseSkill):
    name = "review"
    version = "1.0.0"
    input_model = ReviewInput
    output_model = ReviewOutput

    def run(self, payload: ReviewInput, ctx: SkillContext) -> ReviewOutput:
        fallback_risks = _local_risks(payload)
        material = [
            {
                "chapter": c.get("chapter") or i,
                "title": c.get("title"),
                "content": text_of(c.get("content"))[:1500] or text_of(c.get("summary"))[:300],
                "hook": c.get("hook") or "",
            }
            for i, c in enumerate(payload.chapters, 1)
        ]
        data = call_json(
            ctx,
            system=SYSTEM,
            user=PROMPT.format(
                title=payload.title,
                genre=payload.genre_name,
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
        high_risk = any(r.level == "high" for r in risks)
        score = data.get("score")
        try:
            score = max(0, min(int(score), 100))
        except (TypeError, ValueError):
            score = max(0, 90 - 15 * sum(1 for r in risks if r.level == "medium") - 40 * sum(1 for r in risks if r.level == "high"))
        ctx.log(f"体检完成：score={score}，高危={high_risk}")
        return ReviewOutput(score=score, risks=risks[:20], suggestions=suggestions, high_risk=high_risk)
