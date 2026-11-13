# -*- coding: utf-8 -*-
"""审查执行器：薄封装 `src/review.py`，章节级断点、取消、产物入对象存储。

输入优先级：
1. `params.chapters`: `[{chapter_no, text}]`（推荐，直接支持多章断点）
2. `params.source_key`: 对象存储里的纯文本，按「第X章」标题切分
3. `params.chapter_no` + `params.text`: 单章

基准数据：
- `params.chapters_doc` / `chapters_key`
- `params.decomposed_doc` / `decomposed_key`
缺省时退回 src 的 `data/<book>/…`（只读挂载）。
"""

from __future__ import annotations

import logging
import re

from ..prompts.review import PROMPT_VERSION, get_review_prompt_service
from ..services.model_config import resolve_step_model
from ..services.storage import task_prefix
from .adapt import _record_usage

logger = logging.getLogger("moxie.runners.review")

_CHAPTER_RE = re.compile(r"^[ \t　]*第[0-9零一二三四五六七八九十百千两]+章[^\n]*$", re.M)


def _split_text(text: str) -> list[dict]:
    marks = [m.start() for m in _CHAPTER_RE.finditer(text)]
    if len(marks) >= 2:
        blocks = [text[marks[i]: marks[i + 1]].strip() for i in range(len(marks) - 1)]
        blocks.append(text[marks[-1]:].strip())
        return [{"chapter_no": i, "text": block} for i, block in enumerate(blocks, 1)]
    return [{"chapter_no": 1, "text": text.strip()}]


class ReviewRunner:
    def run(self, ctx) -> str | None:
        from ..services.tasks import TaskReschedule

        settings = ctx.settings
        params = ctx.task.params or {}
        if settings is None:
            raise RuntimeError("ReviewRunner 需要 settings")
        if ctx.storage is None:
            raise RuntimeError("ReviewRunner 需要 storage")

        service = get_review_prompt_service(settings)
        book = str(params.get("book") or params.get("book_name") or ctx.task.book_id or "book")
        prefix = task_prefix(book, ctx.task.id)
        chapters = self._load_chapters(ctx, params)
        if not chapters:
            raise ValueError("没有可审查的章节文本")

        chapters_doc = self._load_doc(ctx, params, "chapters_doc", "chapters_key")
        decomposed_doc = self._load_doc(ctx, params, "decomposed_doc", "decomposed_key")

        checks = params.get("checks")
        if checks is not None and not isinstance(checks, list):
            raise ValueError("checks 必须是字符串数组")
        top_n = int(params.get("top_n") or 5)
        advice_scope = str(params.get("advice_scope") or "ai")
        resolved = resolve_step_model(ctx.session, "review_run", settings, api_key=ctx.byok_key or None)
        model = resolved.model
        api_key = resolved.api_key
        if not api_key:
            raise ValueError("审查需要模型 Key：请配置服务端 Key 或使用 X-BYOK-Key")

        processed = 0
        results = []
        for index, chapter in enumerate(chapters):
            key = f"chapter:{int(chapter['chapter_no']):03d}"
            file_key = f"chapter-{int(chapter['chapter_no']):03d}"
            step = ctx.get_step(key)
            if step is not None and step.status == "done":
                results.append(ctx.storage.get_json(f"{prefix}/review/{file_key}.json"))
                continue
            ctx.check_cancel()
            usage: list = []

            def on_result(result):
                usage.append(result)

            result = service.run_review(
                book=book,
                chapter_no=chapter["chapter_no"],
                chapter_text=chapter["text"],
                checks=checks,
                model=model,
                api_key=api_key,
                byok=bool(ctx.byok_key),
                base_url=resolved.base_url or None,
                on_result=on_result,
                chapters_doc=chapters_doc,
                decomposed_doc=decomposed_doc,
                on_log=ctx.log,
                should_stop=lambda: (ctx.check_cancel(), False)[1],
                top_n=top_n,
                advice_scope=advice_scope,
            )
            _record_usage(ctx, key, usage)
            result.setdefault("chapter_no", chapter["chapter_no"])
            ctx.storage.put_json(f"{prefix}/review/{file_key}.json", result)
            try:
                ctx.storage.put_bytes(
                    f"{prefix}/review/{file_key}.md",
                    service.render_markdown(result).encode("utf-8"),
                    "text/markdown; charset=utf-8",
                )
                ctx.storage.put_bytes(
                    f"{prefix}/review/{file_key}.html",
                    service.render_html(result).encode("utf-8"),
                    "text/html; charset=utf-8",
                )
            except Exception:  # noqa: BLE001 - 渲染失败不影响 JSON 产物
                logger.warning("审查报告渲染失败 chapter=%s", chapter["chapter_no"], exc_info=True)
            ctx.step(key, output_ref=f"{prefix}/review/{file_key}.json")
            results.append(result)
            processed += 1
            ctx.log(f"章节 {chapter['chapter_no']} 审查完成")
            ctx.progress(min(95, int((index + 1) * 90 / len(chapters))))
            if (
                settings.decompose_segment_batch
                and processed >= settings.decompose_segment_batch
                and index < len(chapters) - 1
            ):
                raise TaskReschedule()

        analyzed = 0
        skipped = 0
        for result in results:
            check_rows = result.get("checks") or []
            analyzed += sum(1 for c in check_rows if not c.get("skipped"))
            skipped += sum(1 for c in check_rows if c.get("skipped"))
        manifest = {
            "prompt_version": PROMPT_VERSION,
            "book": book,
            "chapters": [int(c["chapter_no"]) for c in chapters],
            "reports": len(results),
            "checks_analyzed": analyzed,
            "checks_skipped": skipped,
            "cost_cents": int(ctx.task.cost_actual_cents or 0),
        }

        # 相似度检查：拆解源 vs 改编产出；有源时写 similarity.json 并汇总进体检结果
        source_chapters = self._load_similarity_source(ctx, params)
        if source_chapters:
            from ..services.similarity import compare_chapters

            similarity = compare_chapters(
                source_chapters,
                chapters,
                n=settings.similarity_ngram,
                threshold=settings.similarity_threshold,
                max_paragraphs=settings.similarity_max_paragraphs,
            )
            ctx.storage.put_json(f"{prefix}/review/similarity.json", similarity)
            manifest["similarity"] = {
                "artifact": f"{prefix}/review/similarity.json",
                "overall_overlap_ratio": similarity["overall_overlap_ratio"],
                "chapters_over_threshold": similarity["chapters_over_threshold"],
                "paragraphs_over_threshold": similarity["paragraphs_over_threshold"],
                "flagged": similarity["chapters_over_threshold"] > 0,
            }
        ctx.storage.put_json(f"{prefix}/review/manifest.json", manifest)
        ctx.step("outputs", output_ref=f"{prefix}/review/manifest.json", meta=manifest)
        ctx.log(f"审查产物已写入对象存储：{prefix}/review")
        return f"{prefix}/review/manifest.json"

    def _load_similarity_source(self, ctx, params: dict) -> list[dict]:
        """相似度比较的原文来源：拆解文档优先，其次纯文本 source_key。"""
        decomposed = self._load_doc(ctx, params, "decomposed_doc", "decomposed_key")
        if decomposed and isinstance(decomposed.get("chapters"), list):
            return [c for c in decomposed["chapters"] if isinstance(c, dict)]
        source_key = params.get("source_key")
        if source_key and ctx.storage:
            try:
                text = ctx.storage.get_bytes(str(source_key)).decode("utf-8", "replace")
            except Exception:  # noqa: BLE001 - 源文件缺失不影响审查主流程
                return []
            return _split_text(text)
        return []

    def _load_doc(self, ctx, params: dict, inline_key: str, artifact_key: str) -> dict | None:
        if isinstance(params.get(inline_key), dict):
            return params[inline_key]
        key = params.get(artifact_key)
        if key and ctx.storage:
            return ctx.storage.get_json(key)
        return None

    def _load_chapters(self, ctx, params: dict) -> list[dict]:
        raw = params.get("chapters")
        if isinstance(raw, list):
            out = []
            for item in raw:
                if not isinstance(item, dict):
                    continue
                text = str(item.get("text") or "").strip()
                if text:
                    out.append({"chapter_no": item.get("chapter_no") or len(out) + 1, "text": text})
            return out
        source_key = params.get("source_key")
        if source_key and ctx.storage:
            text = ctx.storage.get_bytes(source_key).decode("utf-8")
            return _split_text(text)
        text = str(params.get("text") or "").strip()
        if text:
            return [
                {
                    "chapter_no": int(params.get("chapter_no") or 1),
                    "text": text,
                }
            ]
        return []
