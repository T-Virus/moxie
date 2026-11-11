# -*- coding: utf-8 -*-
"""Skill 契约：强类型输入/输出 + 受控上下文。

约束：
  · 每个 skill 只依赖入参与上下文，不读写数据库/存储，便于单测；
  · 模型调用统一走 model_gateway（stub 与真实模型同一路径）；
  · 上下文中的 usage 只做本节点归集，由编排引擎落 usage_events。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict

from ..config import Settings
from ..services.model_gateway import ModelResult, complete_sync, parse_json_text


class StrictModel(BaseModel):
    """禁止未知字段，避免技能输入悄悄漂移。"""

    model_config = ConfigDict(extra="forbid")


@dataclass
class SkillContext:
    settings: Settings
    model: str = ""
    api_key: str = ""
    byok: bool = False
    # 本节点内的模型调用结果（线程内独占，引擎汇总结算）
    usage: list[ModelResult] = field(default_factory=list)
    logs: list[tuple[str, str]] = field(default_factory=list)

    def log(self, message: str, level: str = "info") -> None:
        self.logs.append((level, message[:500]))


def call_json(ctx: SkillContext, *, system: str, user: str) -> dict[str, Any]:
    """调用模型并解析 JSON；解析失败返回空 dict，由各 skill 走确定性兜底。"""
    messages = [{"role": "system", "content": system}] if system else []
    messages.append({"role": "user", "content": user})
    result = complete_sync(
        ctx.settings,
        messages,
        model=ctx.model or ctx.settings.llm_model,
        api_key=ctx.api_key or ctx.settings.llm_api_key,
        byok=ctx.byok,
        expect_json=True,
    )
    ctx.usage.append(result)
    try:
        data = parse_json_text(result.text)
    except ValueError:
        ctx.log("模型返回不是合法 JSON，使用确定性兜底", level="warning")
        return {}
    return data if isinstance(data, dict) else {}


def text_of(value: Any) -> str:
    return str(value or "").strip()


def list_of_dicts(value: Any, limit: int | None = None) -> list[dict]:
    if not isinstance(value, list):
        return []
    out = [item for item in value if isinstance(item, dict)]
    return out[:limit] if limit else out
