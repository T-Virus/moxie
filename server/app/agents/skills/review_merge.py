# -*- coding: utf-8 -*-
"""review_merge：纯 builder 驱动的合并节点。builder 已经把 consistency_review 和 compliance_review 的
输出合成一份完整的 ReviewOutput 兼容结构，本 skill 只是 engine 串联 builder→skill 所需的 passthrough。"""

from __future__ import annotations

from pydantic import Field

from ..contracts import StrictModel
from .base import BaseSkill


class ReviewMergeInput(StrictModel):
    title: str = Field(default="")
    genre_name: str = Field(default="")
    score: int = Field(default=0)
    risks: list[dict] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    high_risk: bool = False
    consistency_issues: list[str] = Field(default_factory=list)
    compliance_issues: list[str] = Field(default_factory=list)


class ReviewMergeOutput(ReviewMergeInput):
    pass


class ReviewMergeSkill(BaseSkill):
    name = "review_merge"
    version = "1.0.0"
    input_model = ReviewMergeInput
    output_model = ReviewMergeOutput

    def run(self, payload: ReviewMergeInput, ctx) -> ReviewMergeOutput:  # noqa: ANN001
        # passthrough：builder 已完成合并，这里只做 output_model 契约校验
        return ReviewMergeOutput(**payload.model_dump())
