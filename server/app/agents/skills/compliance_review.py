# -*- coding: utf-8 -*-
"""合规体检：只核对敏感/违禁词与用户雷区，不做设定一致性或商业价值评估。
和 consistency_review（设定一致性检查）并发执行，共用 review_merge 聚合。"""

from __future__ import annotations

from pydantic import Field

from ..contracts import SkillContext, StrictModel, call_json, list_of_dicts, text_of
from .base import BaseSkill


FORBIDDEN_WORDS = ("赌博", "毒品", "贩毒", "制毒", "诈骗", "枪支", "爆炸物", "色情交易", "走私")
SENSITIVE_WORDS = ("血腥", "虐杀", "自残", "自杀", "低俗", "粗口")


class ComplianceInput(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    genre_name: str = Field(min_length=1, max_length=60)
    chapters: list[dict] = Field(default_factory=list)
    outline: list[dict] = Field(default_factory=list)
    # 用户雷区与目标平台（来自 positioning）
    positioning: dict = Field(default_factory=dict)


class ComplianceRisk(StrictModel):
    level: str = "medium"
    code: str = ""
    message: str
    chapter: int | None = None


class ComplianceOutput(StrictModel):
    risks: list[ComplianceRisk] = Field(default_factory=list)
    # 给 review_merge 用的扁平格式，兼容原 review 的 compliance_issues
    compliance_issues: list[str] = Field(default_factory=list)
    high_risk: bool = False


SYSTEM = "你是网文内容合规审读编辑，只输出 JSON，不做设定一致性检查。"

PROMPT = """【技能 compliance_review】
书名：{title}　题材：{genre}
目标平台：{platform}　雷区：{taboos}

只核对下列三类合规问题：
1. 违禁词：违法违规、赌博、毒品、色情交易、诈骗、枪支等明确禁止内容；
2. 敏感词：低俗、血腥暴力、自伤自残等平台敏感表达；
3. 用户雷区：用户显式列出的禁止主题。

正常剧情表达不要误报；只有明确违禁才标 high，敏感表达标 medium/low。
输出 JSON：
{{"risks":[{{"level":"high/medium/low","code":"","message":"","chapter":1}}],
 "compliance_issues":["可读的问题描述"]}}

待核材料：
{material}
"""


def _local_risks(payload: ComplianceInput) -> list[ComplianceRisk]:
    """确定性兜底：只扫敏感/违禁词与用户雷区，不评判作品质量。"""
    risks: list[ComplianceRisk] = []
    if not payload.chapters and not payload.outline:
        risks.append(ComplianceRisk(level="medium", code="no_material", message="没有可核对的章纲或章节内容"))
        return risks
    taboos = [text_of(item) for item in (payload.positioning or {}).get("taboos") or [] if text_of(item)]
    for index, chapter in enumerate(payload.chapters, 1):
        body = text_of(chapter.get("content")) or text_of(chapter.get("summary"))
        no = int(chapter.get("chapter") or index)
        for word in FORBIDDEN_WORDS:
            if word in body:
                risks.append(
                    ComplianceRisk(level="high", code="forbidden_word", message=f"命中违禁表达：{word}", chapter=no)
                )
        for word in SENSITIVE_WORDS:
            if word in body:
                risks.append(
                    ComplianceRisk(level="medium", code="sensitive_word", message=f"命中敏感表达：{word}", chapter=no)
                )
        for word in taboos:
            if word in body:
                risks.append(
                    ComplianceRisk(level="medium", code="taboo", message=f"命中用户雷区：{word}", chapter=no)
                )
    return risks


class ComplianceReviewSkill(BaseSkill):
    name = "compliance_review"
    version = "1.0.0"
    input_model = ComplianceInput
    output_model = ComplianceOutput

    def run(self, payload: ComplianceInput, ctx: SkillContext) -> ComplianceOutput:
        fallback_risks = _local_risks(payload)
        material = {
            "chapters": [
                {
                    "chapter": c.get("chapter") or i,
                    "title": c.get("title"),
                    "content": text_of(c.get("content"))[:1200] or text_of(c.get("summary"))[:300],
                    "hook": c.get("hook") or "",
                }
                for i, c in enumerate(payload.chapters, 1)
            ][:100],
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
                material=_json_dumps(material, 12000),
            ),
        )
        risks: list[ComplianceRisk] = []
        for item in list_of_dicts(data.get("risks")):
            level = text_of(item.get("level")).lower()
            message = text_of(item.get("message"))
            if level not in {"high", "medium", "low"} or not message:
                continue
            chapter = item.get("chapter")
            risks.append(
                ComplianceRisk(
                    level=level,
                    code=text_of(item.get("code")) or "model_flag",
                    message=message[:200],
                    chapter=int(chapter) if isinstance(chapter, (int, float)) and int(chapter) > 0 else None,
                )
            )
        risks.extend(fallback_risks)
        compliance_issues = [
            f"[{r.level.upper()}] {r.message}（第 {r.chapter} 章）" if r.chapter else f"[{r.level.upper()}] {r.message}"
            for r in risks
        ][:15]
        high_risk = any(r.level == "high" for r in risks)
        ctx.log(f"合规体检完成：{len(risks)} 条风险，高危={high_risk}")
        return ComplianceOutput(risks=risks[:20], compliance_issues=compliance_issues, high_risk=high_risk)


def _json_dumps(obj, max_len: int = 0) -> str:  # noqa: ANN001
    import json as _json
    s = _json.dumps(obj, ensure_ascii=False)
    if max_len and len(s) > max_len:
        return s[:max_len]
    return s
