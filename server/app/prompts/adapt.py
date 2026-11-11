# -*- coding: utf-8 -*-
"""改编提示词的版本化封装（薄封装 `src/adapt.py`，不复制模板与规则）。

- `PROMPT_VERSION` 写入 tasks.prompt_version、产物 manifest，便于回溯与灰度；
- 提示词模板 / 常量 / 规范化函数全部来自 `src/adapt.py`，服务端只负责编排；
- 公开 API 永不返回提示词正文。
"""

from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path
from types import ModuleType

from ..config import Settings
from ..errors import ApiError

logger = logging.getLogger("moxie.prompts.adapt")

PROMPT_VERSION = "adapt-2026-11-v1"


def _load_module(settings: Settings) -> ModuleType | None:
    path = Path(settings.src_path).resolve()
    if not (path / "adapt.py").is_file():
        return None
    try:
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
        return importlib.import_module("adapt")
    except Exception as exc:  # noqa: BLE001
        logger.warning("加载 src 改编模块失败：%s", exc)
        return None


class AdaptPromptService:
    """服务端唯一的改编提示词入口；所有模板与规则都委托给 src/adapt.py。"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.version = PROMPT_VERSION
        self._module: ModuleType | None | bool = False

    @property
    def module(self) -> ModuleType:
        if self._module is False:
            self._module = _load_module(self.settings)
        if self._module is None:
            raise ApiError(
                500,
                "adapt_prompt_source_missing",
                "服务端未挂载 src/adapt.py，无法执行改编（请把仓库 src/ 只读挂载到 SRC_PATH）",
            )
        return self._module

    # ---- 常量 ----
    @property
    def chapters_per_call(self) -> int:
        return int(getattr(self.module, "CHAPTERS_PER_CALL", 20))

    @property
    def map_new_per_call(self) -> int:
        return int(getattr(self.module, "MAP_NEW_PER_CALL", 15))

    @property
    def sequel_per_call(self) -> int:
        return int(getattr(self.module, "SEQUEL_PER_CALL", 10))

    @property
    def default_style(self) -> str:
        return str(getattr(self.module, "DEFAULT_STYLE", "换一个完全不同的题材与文风"))

    def system_prompt(self) -> str | None:
        mod = self.module
        return str(getattr(mod, "SYSTEM_PROMPT", "") or "") or None

    # ---- 模板渲染（只在服务端进程内调用）----
    def build_naming_prompt(self, chars, facs, items, data, style) -> str:
        return self.module.build_naming_prompt(chars, facs, items, data, style)

    def build_meta_prompt(self, data, style, cards, facs) -> str:
        return self.module.build_meta_prompt(data, style, cards, facs)

    def build_terms_prompt(self, data, style, summary, cards, facs) -> str:
        return self.module.build_terms_prompt(data, style, summary, cards, facs)

    def build_plan_prompt(self, chapters, style, target) -> str:
        return self.module.build_plan_prompt(chapters, style, target)

    def build_map_prompt(self, batch, chapters, book, style, name_map, used_titles=None) -> str:
        return self.module.build_map_prompt(batch, chapters, book, style, name_map, used_titles)

    def build_chap_prompt(self, seg, book, style, name_map, rng, total, used_titles=None) -> str:
        return self.module.build_chap_prompt(seg, book, style, name_map, rng, total, used_titles)

    def build_sequel_prompt(self, tail, book, style, k, start, used_titles=None) -> str:
        return self.module.build_sequel_prompt(tail, book, style, k, start, used_titles)

    # ---- 规范化 / 兜底（复用 src）----
    def merge_name_map(self, entries):
        return self.module.merge_name_map(entries)

    def apply_name_map_all(self, items, name_map) -> None:
        self.module.apply_name_map_all(items, name_map)

    def apply_name_map(self, chapters, name_map) -> None:
        self.module.apply_name_map(chapters, name_map)

    def dedupe_titles(self, chapters):
        return self.module.dedupe_titles(chapters)

    def fix_chapters(self, got, seg):
        return self.module.fix_chapters(got, seg)

    def fix_by_position(self, got, expect_n, nums):
        return self.module.fix_by_position(got, expect_n, nums)

    def inherit_chapter_meta(self, got, source_groups) -> None:
        self.module._inherit_chapter_meta(got, source_groups)

    def proportional_plan(self, total_src, n):
        return self.module.proportional_plan(total_src, n)

    def validate_plan(self, plan, n, total_src):
        return self.module.validate_plan(plan, n, total_src)

    def plan_batches(self, plan):
        return self.module.plan_batches(plan)

    def local_adapt(self, data, target, sequel):
        return self.module.local_adapt(data, target, sequel)

    def items_from_bible(self, data):
        return self.module._items_from_bible(data)

    def to_chapters_json(self, decomposed):
        return self.module.to_chapters_json(decomposed)

    def rewrite_roster(
        self,
        src_chars,
        src_facs,
        src_items,
        data,
        style,
        name_map,
        api_key,
        base_url,
        model,
        concurrency=None,
    ):
        kwargs = {"concurrency": concurrency} if concurrency else {}
        return self.module._rewrite_roster(
            src_chars,
            src_facs,
            src_items,
            data,
            style,
            name_map,
            api_key,
            base_url,
            model,
            **kwargs,
        )


def get_adapt_prompt_service(settings: Settings) -> AdaptPromptService:
    return AdaptPromptService(settings)
