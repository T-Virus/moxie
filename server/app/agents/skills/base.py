# -*- coding: utf-8 -*-
"""Skill 基类：仅声明契约与版本，执行逻辑由子类实现。"""

from __future__ import annotations

from typing import Any

from ..contracts import SkillContext


class BaseSkill:
    name: str = ""
    version: str = "1.0.0"
    input_model: Any = None
    output_model: Any = None

    def run(self, payload: Any, ctx: SkillContext) -> Any:  # pragma: no cover - 由子类实现
        raise NotImplementedError
