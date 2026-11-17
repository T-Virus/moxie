# -*- coding: utf-8 -*-
"""设定一致性体检：只核对人物/势力/道具与设定基准的冲突，章纲与待核内容的覆盖对齐。
和 compliance_review（敏感/违禁词检查）并发执行，共用 review_merge 聚合。"""

from __future__ import annotations

from pydantic import Field

from ..contracts import SkillContext, StrictModel, call_json, list_of_dicts, text_of
from .base import BaseSkill


class ConsistencyInput(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    genre_name: str = Field(min_length=1, max_length=60)
    chapters: list[dict] = Field(default_factory=list)
    outline: list[dict] = Field(default_factory=list)
    positioning: dict = Field(default_factory=dict)
    settings: dict = Field(default_factory=dict)


class ConsistencyIssue(StrictModel):
    kind: str = "coverage"  # coverage | naming | stance | continuity
    chapter: int | None = None
    message: str


class ConsistencyOutput(StrictModel):
    issues: list[ConsistencyIssue] = Field(default_factory=list)
    # 给 review_merge 用的扁平格式，兼容原 review 的 consistency_issues
    consistency_issues: list[str] = Field(default_factory=list)


SYSTEM = "你是网文设定一致性审读编辑，只输出 JSON，不做违禁词/敏感词检查。"

PROMPT = """【技能 consistency_review】
书名：{title}　题材：{genre}
设定基准（以此为准核对人物/势力/道具的名称与立场）：
{settings}

只核对下列两类设定一致性问题，不评判文风、节奏、吸引力：
1. 命名/立场冲突：人物、势力、道具的名称、立场、角色定位是否与设定基准矛盾；
2. 章纲覆盖：章纲规划的章节数与待核内容的覆盖是否一致；

输出 JSON：
{{"issues":[{{"kind":"coverage|naming|stance|continuity","chapter":1,"message":"冲突描述"}}],
 "consistency_issues":["可读的问题描述"]}}

待核材料：
{material}
"""


def _local_consistency(payload: ConsistencyInput) -> list[ConsistencyIssue]:
    """确定性一致性检查：章纲与待核内容的章节覆盖对齐。"""
    issues: list[ConsistencyIssue] = []
    if not payload.outline:
        return issues
    provided = {int(c.get("chapter") or i) for i, c in enumerate(payload.chapters, 1)}
    planned = {int(c.get("chapter") or i) for i, c in enumerate(payload.outline, 1)}
    missing = sorted(planned - provided)
    if missing:
        issues.append(
            ConsistencyIssue(
                kind="coverage",
                message=f"章纲规划了 {len(planned)} 章，待核内容只覆盖 {len(provided)} 章（缺第 {missing[:6]} 章）",
            )
        )
    return issues


class ConsistencyReviewSkill(BaseSkill):
    name = "consistency_review"
    version = "1.0.0"
    input_model = ConsistencyInput
    output_model = ConsistencyOutput

    def run(self, payload: ConsistencyInput, ctx: SkillContext) -> ConsistencyOutput:
        fallback_issues = _local_consistency(payload)
        material = {
            "chapters": [
                {
                    "chapter": c.get("chapter") or i,
                    "title": c.get("title"),
                    "summary": text_of(c.get("summary"))[:300],
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
                settings=_json_dumps(settings_view, 2500) or "未提供设定基准",
                material=_json_dumps(material, 12000),
            ),
        )
        issues: list[ConsistencyIssue] = []
        for item in list_of_dicts(data.get("issues")):
            kind = text_of(item.get("kind")) or "continuity"
            message = text_of(item.get("message"))
            if not message:
                continue
            chapter = item.get("chapter")
            issues.append(
                ConsistencyIssue(
                    kind=kind[:20],
                    chapter=int(chapter) if isinstance(chapter, (int, float)) and int(chapter) > 0 else None,
                    message=message[:300],
                )
            )
        issues.extend(fallback_issues)
        flat = [text_of(item.message) for item in issues if item.message][:15]
        ctx.log(f"设定一致性体检完成：{len(flat)} 个问题")
        return ConsistencyOutput(issues=issues[:20], consistency_issues=flat)


def _json_dumps(obj, max_len: int = 0) -> str:  # noqa: ANN001
    import json as _json
    s = _json.dumps(obj, ensure_ascii=False)
    if max_len and len(s) > max_len:
        return s[:max_len]
    return s
