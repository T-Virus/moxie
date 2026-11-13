# -*- coding: utf-8 -*-
"""审查提示词的版本化封装（薄封装 `src/review.py`）。

- 审查流水线、模板、句子切分与引用校验全部复用 `src/review.py`；
- 服务端只替换模型调用（走统一网关）与基准数据来源（对象存储 / 任务参数）；
- `PROMPT_VERSION` 写入 tasks.prompt_version 与报告 manifest。
"""

from __future__ import annotations

import importlib
import json
import logging
import sys
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

from ..config import Settings
from ..errors import ApiError

logger = logging.getLogger("moxie.prompts.review")

PROMPT_VERSION = "review-2026-11-v1"

# run_review 是同步流水线，内部通过模块级函数读取基准；替换模块函数需要串行化。
_RUN_LOCK = threading.RLock()


def _load_module(settings: Settings) -> ModuleType | None:
    path = Path(settings.src_path).resolve()
    if not (path / "review.py").is_file():
        return None
    try:
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
        return importlib.import_module("review")
    except Exception as exc:  # noqa: BLE001
        logger.warning("加载 src 审查模块失败：%s", exc)
        return None


@contextmanager
def _baseline_files(module: ModuleType, chapters_doc: dict | None, decomposed_doc: dict | None):
    """把服务端传入的章节/设定数据临时落成 src 期望的文件，再恢复模块函数。"""
    if chapters_doc is None and decomposed_doc is None:
        yield
        return
    with tempfile.TemporaryDirectory(prefix="moxie-review-") as tmp:
        chapters_path = Path(tmp) / "chapters.json"
        decomposed_path = Path(tmp) / "decomposed.json"
        chapters_path.write_text(json.dumps(chapters_doc or {}, ensure_ascii=False), encoding="utf-8")
        decomposed_path.write_text(json.dumps(decomposed_doc or {}, ensure_ascii=False), encoding="utf-8")
        old_chapters = module.book_chapters
        old_decomposed = module.book_decomposed
        module.book_chapters = lambda _book: str(chapters_path)  # noqa: ARG005
        module.book_decomposed = lambda _book: str(decomposed_path)  # noqa: ARG005
        try:
            yield
        finally:
            module.book_chapters = old_chapters
            module.book_decomposed = old_decomposed


class ReviewPromptService:
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
                "review_prompt_source_missing",
                "服务端未挂载 src/review.py，无法执行审查（请把仓库 src/ 只读挂载到 SRC_PATH）",
            )
        return self._module

    @property
    def check_labels(self) -> dict[str, str]:
        return dict(getattr(self.module, "CHECK_LABEL", {}))

    @property
    def all_checks(self) -> list[str]:
        return list(getattr(self.module, "ALL_CHECKS", []))

    @property
    def max_text_chars(self) -> int:
        return int(getattr(self.module, "MAX_TEXT_CHARS", 60_000))

    def render_markdown(self, result: dict) -> str:
        return self.module.render_markdown(result)

    def render_html(self, result: dict) -> str:
        return self.module.render_html(result)

    def make_model_call(
        self, settings: Settings, model: str, api_key: str, byok: bool = False, base_url: str | None = None, on_result=None
    ):
        """构造替换 src `_call` 的函数：走统一网关，失败抛 StepError 让单个检查项降级。"""
        from ..services.model_gateway import complete_sync, parse_json_text

        module = self.module
        step_error = module.StepError

        def call(prompt, _api_key, _base_url, _model):
            messages = []
            system = getattr(module, "SYSTEM_PROMPT", "")
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            try:
                result = complete_sync(
                    settings,
                    messages,
                    model=model,
                    api_key=api_key,
                    byok=byok,
                    expect_json=True,
                    base_url=base_url or None,
                )
            except Exception as exc:  # noqa: BLE001
                raise step_error(f"模型调用失败：{exc}") from exc
            if on_result is not None:
                on_result(result)
            try:
                return parse_json_text(result.text)
            except ValueError as exc:
                raise step_error("模型输出不是合法 JSON（服务端无法解析）") from exc

        return call

    def run_review(
        self,
        *,
        book: str,
        chapter_no,
        chapter_text: str,
        checks: list[str] | None = None,
        model: str,
        api_key: str,
        byok: bool = False,
        base_url: str | None = None,
        on_result=None,
        chapters_doc: dict | None = None,
        decomposed_doc: dict | None = None,
        on_log=None,
        should_stop=None,
        top_n: int | None = None,
        advice_scope: str | None = None,
    ) -> dict:
        module = self.module
        with _RUN_LOCK:
            old_call = module._call
            old_top = getattr(module, "DEFAULT_TOP_N", 5)
            old_scope = getattr(module, "DEFAULT_ADVICE_SCOPE", "ai")
            module._call = self.make_model_call(
                self.settings, model, api_key, byok=byok, base_url=base_url, on_result=on_result
            )
            try:
                with _baseline_files(module, chapters_doc, decomposed_doc):
                    return module.run_review(
                        book,
                        chapter_no,
                        chapter_text,
                        checks=checks,
                        model=model,
                        base_url=None,
                        api_key=api_key or "server",
                        top_n=top_n or old_top,
                        advice_scope=advice_scope or old_scope,
                        on_log=on_log,
                        should_stop=should_stop,
                    )
            finally:
                module._call = old_call


def get_review_prompt_service(settings: Settings) -> ReviewPromptService:
    return ReviewPromptService(settings)
