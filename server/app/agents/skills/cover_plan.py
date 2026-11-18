# -*- coding: utf-8 -*-
"""云端封面技能：把 services/cover.py 的提示词组装能力注册为 Agent 技能。

services.cover.generate_cover 需要 storage/session（有副作用），不适合放进
纯函数技能；本技能复用其纯函数 build_prompt，产出可审计的封面方案 checkpoint
（prompt / 风格 / 版式 / 尺寸 / 书名署名裁切检查），由 publish 之后的 cover API
按该方案真正出图。这样封面环节进入三图流程，且技能可离线单测。
"""

from __future__ import annotations

from types import SimpleNamespace

from pydantic import Field

from ..contracts import SkillContext, StrictModel, text_of
from ...services.cover import LAYOUT_KEYS, STYLE_KEYS, build_prompt
from .base import BaseSkill

MAX_SIDE = 4096
MIN_SIDE = 256


class CoverInput(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    genre_name: str = Field(default="", max_length=60)
    author: str = Field(default="", max_length=60)
    outline: dict = Field(default_factory=dict)
    prompt: str = Field(default="", max_length=2000)
    style: str = Field(default="gold", max_length=20)
    layout: str = Field(default="top", max_length=20)
    width: int = Field(default=600, ge=MIN_SIDE, le=MAX_SIDE)
    height: int = Field(default=800, ge=MIN_SIDE, le=MAX_SIDE)


class CropCheck(StrictModel):
    item: str
    ok: bool = True
    note: str = ""


class CoverPlan(StrictModel):
    title: str
    author: str
    prompt: str
    style: str
    layout: str
    width: int
    height: int
    checks: list[CropCheck] = Field(default_factory=list)
    source: str = "services.cover#build_prompt"


class CoverOutput(StrictModel):
    plan: CoverPlan
    ready_for_api: bool = True


def _clamp(value: int, default: int) -> int:
    return max(MIN_SIDE, min(MAX_SIDE, int(value or default)))


def _crop_checks(title: str, author: str, style: str, layout: str) -> list[CropCheck]:
    checks = [
        CropCheck(item="书名不为空", ok=bool(title), note=title[:40]),
        CropCheck(item="署名不为空", ok=bool(author), note=author[:40]),
        CropCheck(item="风格值合法", ok=style in STYLE_KEYS, note=f"style={style}"),
        CropCheck(item="版式值合法", ok=layout in LAYOUT_KEYS, note=f"layout={layout}"),
    ]
    # 书名/署名过长时提示裁切风险；不直接改文本（文本取自 book_meta，由 owner 维护）
    if len(title) > 12:
        checks.append(CropCheck(item="书名长度适配裁切", ok=False, note=f"{len(title)} 字，建议封面主标题不超过 12 字"))
    if len(author) > 8:
        checks.append(CropCheck(item="署名长度适配裁切", ok=False, note=f"{len(author)} 字，建议署名不超过 8 字"))
    return checks


class CoverSkill(BaseSkill):
    name = "cover_plan"
    version = "1.0.0"
    input_model = CoverInput
    output_model = CoverOutput

    def run(self, payload: CoverInput, ctx: SkillContext) -> CoverOutput:
        outline = dict(payload.outline or {})
        # build_prompt 只依赖 run.genre_name 与 outline，用轻量对象避免 ORM 依赖
        run = SimpleNamespace(genre_name=payload.genre_name)
        prompt = build_prompt(run, outline, payload.prompt)
        if not prompt:
            prompt = f"{payload.genre_name or '网文'}小说封面：主角立于冲突现场，电影感构图，竖版 3:4"
        style = payload.style if payload.style in STYLE_KEYS else "gold"
        layout = payload.layout if payload.layout in LAYOUT_KEYS else "top"
        author = text_of(payload.author) or text_of(outline.get("author"))
        checks = _crop_checks(payload.title, author, style, layout)
        plan = CoverPlan(
            title=payload.title,
            author=author,
            prompt=prompt[:1000],
            style=style,
            layout=layout,
            width=_clamp(payload.width, 600),
            height=_clamp(payload.height, 800),
            checks=checks,
        )
        ctx.log(f"封面方案完成：{len(checks)} 项裁切检查，{sum(1 for item in checks if not item.ok)} 项需人工确认")
        return CoverOutput(plan=plan, ready_for_api=True)
