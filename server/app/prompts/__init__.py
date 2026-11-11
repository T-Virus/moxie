# -*- coding: utf-8 -*-
"""服务端提示词与规则入口。

提示词只在 worker / 服务端内部使用，不通过任何公开 API 返回。
当前版本复用 `src/decompose.py` 的模板与规则（薄封装，避免两套逻辑漂移）；
服务端部署时把仓库 `src/` 只读挂载进来即可，缺失时使用内置兜底模板。
"""

from .adapt import PROMPT_VERSION as ADAPT_PROMPT_VERSION
from .adapt import AdaptPromptService, get_adapt_prompt_service
from .decompose import PROMPT_VERSION, PromptService, get_prompt_service, prompt_service
from .review import PROMPT_VERSION as REVIEW_PROMPT_VERSION
from .review import ReviewPromptService, get_review_prompt_service

__all__ = [
    "PROMPT_VERSION",
    "PromptService",
    "get_prompt_service",
    "prompt_service",
    "ADAPT_PROMPT_VERSION",
    "AdaptPromptService",
    "get_adapt_prompt_service",
    "REVIEW_PROMPT_VERSION",
    "ReviewPromptService",
    "get_review_prompt_service",
]
