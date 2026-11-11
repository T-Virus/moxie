# -*- coding: utf-8 -*-
"""拆解提示词的版本化封装。

- `PROMPT_VERSION` 写入 tasks.prompt_version 与产物 manifest，便于回溯/灰度。
- 公开 API 永远不会返回提示词正文；本模块只在服务端进程内被调用。
- 优先复用 `src/decompose.py` 的 `build_prompt` / `build_merge_prompt`，
  避免提示词与规则出现第二套副本；`src` 不可用时退回精简内置模板（仅保证流程可跑）。
"""

from __future__ import annotations

import importlib
import json
import logging
import re
import sys
from pathlib import Path
from types import ModuleType

from ..config import Settings

logger = logging.getLogger("moxie.prompts")

PROMPT_VERSION = "decompose-2026-11-v1"

_FALLBACK_SEGMENT = """你是小说结构分析专家。请阅读下面的小说片段，输出严格 JSON。
必须包含字段：book_summary（字符串）、opening（对象）、story_bible（对象）、
characters（数组）、factions（数组）、items（数组）、chapters（数组）。
每个 chapter 至少包含：chapter、title、summary、key_events、roles、scene、conflict、hook、emotion、tension。
不要输出 Markdown，不要解释，只输出 JSON。

__CHUNK_NOTE__

小说片段：
__SOURCE_TEXT__
"""

_FALLBACK_MERGE = """请把下面多段拆解结果合并为一份完整 JSON。
保留 chapters 顺序，合并 characters/factions/items 中同名条目，补全 book_summary 与 story_bible。
只输出 JSON，不要解释。

__PARTS__

已完成的章节摘要：
__SUMMARIES__

已知角色：
__CAST__
"""


def _load_src_module(settings: Settings) -> ModuleType | None:
    """按 SRC_PATH 导入拆解模块；失败时返回 None（走兜底模板）。"""
    path = Path(settings.src_path).resolve()
    if not (path / "decompose.py").is_file():
        return None
    try:
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
        return importlib.import_module("decompose")
    except Exception as exc:  # noqa: BLE001
        logger.warning("加载 src 拆解模块失败，使用服务端兜底提示词：%s", exc)
        return None


class PromptService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.version = PROMPT_VERSION
        self._module: ModuleType | None | bool = False

    @property
    def module(self) -> ModuleType | None:
        if self._module is False:
            self._module = _load_src_module(self.settings)
        return self._module

    # ---- 文本切分：优先复用 src 的章回切分 ----
    def slice_first_chapters(self, text: str, n: int) -> str:
        if n <= 0:
            return text
        mod = self.module
        if mod:
            return mod.slice_first_chapters(text, n)
        marks = [m.start() for m in re.finditer(r"^[ \t　]*(?:第[0-9零一二三四五六七八九十百]+章|Chapter\s+\d+)", text, re.M)]
        return text[: marks[n]] if len(marks) > n else text

    def split_text(self, text: str, limit: int = 0, max_chapters: int = 0, min_chapters: int = 0) -> list[str]:
        mod = self.module
        if mod:
            return mod.split_text(text, limit=limit, max_chapters=max_chapters, min_chapters=min_chapters)
        # 兜底：按章首切分；没有章标时按长度硬切
        marks = [m.start() for m in re.finditer(r"^[ \t　]*(?:第[0-9零一二三四五六七八九十百]+章|Chapter\s+\d+)", text, re.M)]
        if len(marks) >= 2:
            cuts = marks + [len(text)]
            return [text[cuts[i]:cuts[i + 1]] for i in range(len(cuts) - 1) if text[cuts[i]:cuts[i + 1]].strip()]
        if limit and len(text) > limit:
            return [text[i:i + limit] for i in range(0, len(text), limit)]
        return [text]

    # ---- 渲染：只在服务端内部调用 ----
    def build_segment_prompt(self, mode: str, text: str, limit: int | None = None, chunk_note: str = "") -> str:
        mod = self.module
        if mod:
            return mod.build_prompt(mode, text, limit=limit, chunk_note=chunk_note)
        return _FALLBACK_SEGMENT.replace("__CHUNK_NOTE__", chunk_note or "").replace("__SOURCE_TEXT__", text)

    def build_merge_prompt(self, parts: list[dict], summaries: str, cast: str) -> str:
        mod = self.module
        if mod:
            return mod.build_merge_prompt(
                json.dumps(parts, ensure_ascii=False),
                summaries,
                cast,
            )
        return (
            _FALLBACK_MERGE.replace("__PARTS__", json.dumps(parts, ensure_ascii=False))
            .replace("__SUMMARIES__", summaries)
            .replace("__CAST__", cast)
        )

    def system_prompt(self) -> str | None:
        mod = self.module
        return getattr(mod, "SYSTEM_PROMPT", None) if mod else None

    # ---- 结果规范化：优先复用 src，避免字段漂移 ----
    def local_decompose(self, text: str) -> dict:
        mod = self.module
        if mod:
            return mod.local_decompose(text)
        return {
            "book_summary": text[:200],
            "opening": {},
            "story_bible": {"synopsis": text[:300]},
            "characters": [],
            "factions": [],
            "items": [],
            "chapters": [
                {
                    "chapter": 1,
                    "title": "第1章",
                    "summary": text[:200],
                    "key_events": [],
                    "roles": [],
                    "scene": "",
                    "conflict": "",
                    "hook": "",
                    "emotion": "",
                    "tension": 0,
                }
            ],
        }

    def to_chapters_json(self, decomposed: dict, limit: int | None = None) -> dict:
        mod = self.module
        if mod:
            return mod.to_chapters_json(decomposed, limit=limit)
        chapters = decomposed.get("chapters") or []
        return {
            "story_bible": decomposed.get("story_bible") or {},
            "opening": decomposed.get("opening") or {},
            "chapters": chapters,
            "items": decomposed.get("items") or [],
        }

    def signing_check(self, chapters: list[dict], opening: dict | None = None):
        mod = self.module
        if mod and hasattr(mod, "signing_check"):
            return mod.signing_check(chapters, opening)
        return {"ok": True, "issues": []}


prompt_service: PromptService | None = None


def get_prompt_service(settings: Settings) -> PromptService:
    """进程内复用，避免每段都重复 import src。"""
    global prompt_service
    if prompt_service is None or prompt_service.settings is not settings:
        prompt_service = PromptService(settings)
    return prompt_service
