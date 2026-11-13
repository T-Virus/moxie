# -*- coding: utf-8 -*-
"""改编执行器：薄封装 `src/adapt.py` 的模板与规范化，服务端负责编排/断点/取消/产物。

- 提示词与规则 100% 来自 src（服务端不保存明文）；
- 每个书级阶段与章节段都是独立 TaskStep，重跑自动跳过；
- 模型调用统一走 `services.model_gateway`，usage 落 `usage_events` 并计入任务成本；
- 产物写对象存储：source.json / name_map.json / roster.json / book.json / segments/*.json /
  decomposed.json / chapters.json / manifest.json。
"""

from __future__ import annotations

import json
import logging
import threading
from contextlib import contextmanager
from typing import Callable

from ..prompts.adapt import PROMPT_VERSION, get_adapt_prompt_service
from ..services.model_config import resolve_step_model
from ..services.model_gateway import complete_sync, parse_json_text
from ..services.storage import task_prefix

logger = logging.getLogger("moxie.runners.adapt")

# src/adapt.py 通过模块级 `_call` 调用模型；替换模块函数必须串行化同一进程内的改编任务。
_MODULE_LOCK = threading.RLock()


@contextmanager
def _patched_call(service, ctx, model: str, usage: list, call: Callable[[str], str]):
    """把 src 内部的 `_call` 指向统一网关（仅 `_rewrite_roster` 需要）。"""
    module = service.module

    def patched(prompt, _api_key, _base_url, _model, tag="", allow_truncated=False, hint=""):
        return parse_json_text(call(prompt))

    old = module._call
    module._call = patched
    try:
        yield
    finally:
        module._call = old


def _record_usage(ctx, step_key: str, results: list) -> None:
    """把一次步骤内的模型调用聚合为一条 usage_event（幂等键含步骤）。"""
    if not results:
        return
    from ..db import utcnow
    from ..models import UsageEvent

    key = f"task:{ctx.task.id}:usage:{step_key}"
    existing = (
        ctx.session.query(UsageEvent)
        .filter_by(account_id=ctx.task.account_id, idempotency_key=key)
        .one_or_none()
    )
    tokens = sum(r.total_tokens for r in results)
    cost = sum(r.cost_cents for r in results)
    meta = {
        "calls": len(results),
        "cost_cents": cost,
        "route": results[0].route,
        "model": results[0].model,
        "step": step_key,
    }
    if existing is None:
        ctx.session.add(
            UsageEvent(
                account_id=ctx.task.account_id,
                task_id=ctx.task.id,
                metric="model_token",
                quantity=tokens,
                unit="token",
                idempotency_key=key,
                occurred_at=utcnow(),
                meta=meta,
            )
        )
    else:
        existing.quantity = tokens
        existing.meta = {**(existing.meta or {}), **meta}
    ctx.task.cost_actual_cents = int(ctx.task.cost_actual_cents or 0) + cost
    from ..metrics import increment

    increment("moxie_model_calls_total", len(results), route=results[0].route)
    increment("moxie_model_tokens_total", tokens)
    increment("moxie_model_cost_cents_total", cost)
    ctx.session.flush()


def _load_source(ctx, params: dict) -> dict:
    from ..errors import ApiError

    if isinstance(params.get("book_data"), dict):
        return params["book_data"]
    key = params.get("source_key")
    if key and ctx.storage:
        return ctx.storage.get_json(key)
    path = params.get("source_path")
    if path:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    raise ApiError(
        422,
        "adapt_source_missing",
        "改编任务需要 source_key（拆解产物）、source_path 或 book_data",
    )


class AdaptRunner:
    def _call(self, ctx, service, model: str, prompt: str, usage: list) -> str:
        resolved = resolve_step_model(ctx.session, "adapt", ctx.settings, api_key=ctx.byok_key or None)
        system = service.system_prompt()
        messages = [{"role": "system", "content": system}] if system else []
        messages.append({"role": "user", "content": prompt})
        result = complete_sync(
            ctx.settings,
            messages,
            model=resolved.model,
            api_key=resolved.api_key,
            byok=bool(ctx.byok_key),
            expect_json=True,
            base_url=resolved.base_url or None,
        )
        usage.append(result)
        return result.text

    def run(self, ctx) -> str | None:
        from ..services.tasks import TaskReschedule

        settings = ctx.settings
        params = ctx.task.params or {}
        if settings is None:
            raise RuntimeError("AdaptRunner 需要 settings")
        if ctx.storage is None:
            raise RuntimeError("AdaptRunner 需要 storage")

        service = get_adapt_prompt_service(settings)
        data = _load_source(ctx, params)
        chapters = [c for c in (data.get("chapters") or []) if isinstance(c, dict)]
        if not chapters:
            raise ValueError("源数据没有章节，无法改编")
        total_src = len(chapters)
        target = int(params.get("target_chapters") or 0) or total_src
        if target < 0:
            raise ValueError("target_chapters 不能为负数")
        sequel = int(params.get("sequel_chapters") or 0)
        if sequel < 0:
            raise ValueError("sequel_chapters 不能为负数")
        mapping = target != total_src
        style = str(params.get("style") or "").strip() or service.default_style
        if mapping or sequel:
            override = f"（章数覆盖：新书把原著 {total_src} 章改编为 {target} 章"
            if sequel:
                override += f"，另续写 {sequel} 章全新剧情"
            override += f"，共 {target + sequel} 章；「章数保持不变」一类要求以本条为准）"
            style += override

        out_book = str(params.get("out_book") or "").strip() or f"{params.get('book') or 'book'}·改编"
        book_slug = str(params.get("book") or ctx.task.book_id or "book")
        prefix = task_prefix(book_slug, ctx.task.id)
        ctx.storage.put_json(f"{prefix}/source.json", data)

        resolved = resolve_step_model(ctx.session, "adapt", settings, api_key=ctx.byok_key or None)
        model = resolved.model
        local_mode = bool(params.get("local")) or not (ctx.byok_key or settings.llm_api_key)
        if local_mode:
            return self._run_local(
                ctx, service, data, out_book, prefix, target, sequel, total_src
            )

        src_chars = [c for c in (data.get("characters") or []) if isinstance(c, dict)]
        src_facs = [f for f in (data.get("factions") or []) if isinstance(f, dict)]
        src_items = [i for i in (data.get("items") or []) if isinstance(i, dict)]
        if not src_items:
            src_items = service.items_from_bible(data)
        has_terms = any(
            str((data.get("story_bible") or {}).get(k) or "").strip()
            for k in ("places", "items", "terms")
        )

        name_map: list = []
        new_chars: list = []
        new_facs: list = []
        new_items: list = []

        step = ctx.get_step("book:naming")
        if step is not None and step.status == "done":
            name_map = ctx.storage.get_json(f"{prefix}/name_map.json")["name_map"]
            ctx.log("跳过已完成步骤：统一命名")
        elif src_chars or src_facs or src_items:
            ctx.check_cancel()
            usage: list = []
            with _MODULE_LOCK:
                prompt = service.build_naming_prompt(src_chars, src_facs, src_items, data, style)
                res = parse_json_text(self._call(ctx, service, model, prompt, usage))
            name_map = [m for m in (res.get("name_map") or []) if isinstance(m, dict)]
            _record_usage(ctx, "book:naming", usage)
            ctx.storage.put_json(f"{prefix}/name_map.json", {"name_map": name_map})
            ctx.step("book:naming", output_ref=f"{prefix}/name_map.json", meta={"count": len(name_map)})
            ctx.log(f"统一命名完成：{len(name_map)} 条")

        step = ctx.get_step("book:roster")
        if step is not None and step.status == "done":
            roster = ctx.storage.get_json(f"{prefix}/roster.json")
            new_chars, new_facs, new_items = roster["characters"], roster["factions"], roster["items"]
            name_map = roster.get("name_map") or name_map
            ctx.log("跳过已完成步骤：书级角色卡/势力卡/道具卡")
        elif src_chars or src_facs or src_items:
            ctx.check_cancel()
            usage = []
            with _MODULE_LOCK, _patched_call(
                service, ctx, model, usage, lambda p: self._call(ctx, service, model, p, usage)
            ):
                new_chars, new_facs, new_items, extra_pairs = service.rewrite_roster(
                    src_chars, src_facs, src_items, data, style, name_map, "server", "", model
                )
            name_map = service.merge_name_map(name_map + extra_pairs)
            service.apply_name_map_all(new_chars + new_facs + new_items, name_map)
            _record_usage(ctx, "book:roster", usage)
            ctx.storage.put_json(
                f"{prefix}/roster.json",
                {
                    "characters": new_chars,
                    "factions": new_facs,
                    "items": new_items,
                    "name_map": name_map,
                },
            )
            ctx.step("book:roster", output_ref=f"{prefix}/roster.json")
            ctx.log(f"书级卡片改写完成：{len(new_chars)} 角色 / {len(new_facs)} 势力 / {len(new_items)} 道具")
        else:
            name_map = service.merge_name_map(name_map)

        step = ctx.get_step("book:meta")
        if step is not None and step.status == "done":
            meta = ctx.storage.get_json(f"{prefix}/book.json")
            ctx.log("跳过已完成步骤：书名/梗概/设定库")
        else:
            ctx.check_cancel()
            usage = []
            with _MODULE_LOCK:
                res = parse_json_text(
                    self._call(
                        ctx, service, model, service.build_meta_prompt(data, style, new_chars, new_facs), usage
                    )
                )
            meta = res
            _record_usage(ctx, "book:meta", usage)
            ctx.storage.put_json(f"{prefix}/book.json", meta)
            ctx.step("book:meta", output_ref=f"{prefix}/book.json")
            ctx.log("书名/梗概/设定库完成")

        step = ctx.get_step("book:terms")
        if step is not None and step.status == "done":
            name_map = ctx.storage.get_json(f"{prefix}/name_map.json")["name_map"]
            ctx.log("跳过已完成步骤：术语映射")
        elif has_terms:
            ctx.check_cancel()
            usage = []
            with _MODULE_LOCK:
                tm = parse_json_text(
                    self._call(
                        ctx,
                        service,
                        model,
                        service.build_terms_prompt(
                            data, style, meta.get("book_summary") or "", new_chars, new_facs
                        ),
                        usage,
                    )
                )
            known = {m["old"] for m in name_map}
            name_map = service.merge_name_map(
                name_map
                + [
                    m
                    for m in (tm.get("name_map") or [])
                    if isinstance(m, dict) and str(m.get("old") or "").strip() not in known
                ]
            )
            service.apply_name_map_all(new_chars + new_facs + new_items, name_map)
            _record_usage(ctx, "book:terms", usage)
            ctx.storage.put_json(f"{prefix}/name_map.json", {"name_map": name_map})
            ctx.step("book:terms", output_ref=f"{prefix}/name_map.json")
            ctx.log(f"术语映射完成，共 {len(name_map)} 条")

        book = {
            "book_title": meta.get("book_title") or "",
            "book_summary": meta.get("book_summary") or "",
            "story_bible": meta.get("story_bible") or {},
            "opening": meta.get("opening") or {},
            "characters": new_chars,
            "factions": new_facs,
            "items": new_items,
        }

        if mapping:
            step = ctx.get_step("plan")
            if step is not None and step.status == "done":
                plan = ctx.storage.get_json(f"{prefix}/plan.json")["plan"]
                ctx.log("跳过已完成步骤：章数规划")
            else:
                ctx.check_cancel()
                usage = []
                with _MODULE_LOCK:
                    res = parse_json_text(
                        self._call(ctx, service, model, service.build_plan_prompt(chapters, style, target), usage)
                    )
                plan = service.validate_plan(res.get("plan"), target, total_src)
                if plan is None:
                    plan = service.proportional_plan(total_src, target)
                    ctx.log("章数规划不合规，已使用按比例映射兜底", level="warning")
                _record_usage(ctx, "plan", usage)
                ctx.storage.put_json(f"{prefix}/plan.json", {"plan": plan})
                ctx.step("plan", output_ref=f"{prefix}/plan.json")
            segments = [
                {
                    "key": f"seg:{i:03d}",
                    "file": f"seg-{i:03d}",
                    "batch": batch,
                    "groups": [chapters[p["from"] - 1:p["to"]] for p in batch],
                    "range": f"{batch[0]['new']}~{batch[-1]['new']}",
                }
                for i, batch in enumerate(service.plan_batches(plan), 1)
            ]
        else:
            per_call = int(params.get("chapters_per_call") or service.chapters_per_call)
            if per_call <= 0:
                raise ValueError("chapters_per_call 必须大于 0")
            segments = [
                {
                    "key": f"seg:{i:03d}",
                    "file": f"seg-{i:03d}",
                    "batch": seg,
                    "groups": [[c] for c in seg],
                    "range": f"{seg[0].get('chapter')}~{seg[-1].get('chapter')}",
                }
                for i, seg in enumerate(
                    [chapters[i:i + per_call] for i in range(0, total_src, per_call)],
                    1,
                )
            ]

        new_ch: list[dict] = []
        used_titles: list[str] = []
        processed = 0
        for index, item in enumerate(segments):
            step = ctx.get_step(item["key"])
            if step is not None and step.status == "done":
                saved = ctx.storage.get_json(f"{prefix}/segments/{item['file']}.json")
                new_ch.extend(saved["chapters"])
                used_titles.extend(c.get("title") for c in saved["chapters"] if c.get("title"))
                continue
            ctx.check_cancel()
            usage = []
            with _MODULE_LOCK:
                if mapping:
                    page = parse_json_text(
                        self._call(
                            ctx,
                            service,
                            model,
                            service.build_map_prompt(
                                item["batch"], chapters, book, style, name_map, used_titles
                            ),
                            usage,
                        )
                    )
                    got = service.fix_by_position(
                        page.get("chapters") or [], len(item["batch"]), [p["new"] for p in item["batch"]]
                    )
                else:
                    page = parse_json_text(
                        self._call(
                            ctx,
                            service,
                            model,
                            service.build_chap_prompt(
                                item["batch"],
                                book,
                                style,
                                name_map,
                                item["range"],
                                total_src,
                                used_titles,
                            ),
                            usage,
                        )
                    )
                    got = service.fix_chapters(page.get("chapters") or [], item["batch"])
            service.inherit_chapter_meta(got, item["groups"])
            _record_usage(ctx, item["key"], usage)
            ctx.storage.put_json(f"{prefix}/segments/{item['file']}.json", {"chapters": got})
            ctx.step(item["key"], output_ref=f"{prefix}/segments/{item['file']}.json", meta={"chapters": len(got)})
            new_ch.extend(got)
            used_titles.extend(c.get("title") for c in got if c.get("title"))
            processed += 1
            ctx.log(f"章节段 {item['range']} 完成（{len(got)} 章）")
            if (
                settings.decompose_segment_batch
                and processed >= settings.decompose_segment_batch
                and index < len(segments) - 1
            ):
                ctx.progress(min(95, int((index + 1) * 90 / len(segments))))
                raise TaskReschedule()

        for j in range(0, sequel, service.sequel_per_call):
            key = f"sequel:{j // service.sequel_per_call + 1:03d}"
            file_key = f"sequel-{j // service.sequel_per_call + 1:03d}"
            step = ctx.get_step(key)
            if step is not None and step.status == "done":
                saved = ctx.storage.get_json(f"{prefix}/segments/{file_key}.json")
                new_ch.extend(saved["chapters"])
                used_titles.extend(c.get("title") for c in saved["chapters"] if c.get("title"))
                continue
            ctx.check_cancel()
            k = min(service.sequel_per_call, sequel - j)
            start = target + j + 1
            tail = (new_ch or chapters)[-3:]
            usage = []
            with _MODULE_LOCK:
                res = parse_json_text(
                    self._call(
                        ctx,
                        service,
                        model,
                        service.build_sequel_prompt(tail, book, style, k, start, used_titles),
                        usage,
                    )
                )
            got = service.fix_by_position(res.get("chapters") or [], k, list(range(start, start + k)))
            _record_usage(ctx, key, usage)
            ctx.storage.put_json(f"{prefix}/segments/{file_key}.json", {"chapters": got})
            ctx.step(key, output_ref=f"{prefix}/segments/{file_key}.json", meta={"chapters": len(got)})
            new_ch.extend(got)
            used_titles.extend(c.get("title") for c in got if c.get("title"))
            ctx.log(f"续写第 {start}~{start + k - 1} 章完成")

        return self._write_outputs(
            ctx, service, prefix, book, new_ch, name_map, out_book, total_src, target, sequel, "ai",
            source_chapters=chapters,
        )

    def _run_local(self, ctx, service, data, out_book, prefix, target, sequel, total_src):
        ctx.check_cancel()
        step = ctx.get_step("local")
        if step is not None and step.status == "done":
            decomposed = ctx.storage.get_json(f"{prefix}/decomposed.json")
            ctx.log("跳过已完成步骤：本地改编")
        else:
            decomposed = service.local_adapt(data, target, sequel)
            ctx.storage.put_json(f"{prefix}/decomposed.json", decomposed)
            ctx.step("local", output_ref=f"{prefix}/decomposed.json")
            ctx.log("本地改编完成（未调用模型）")
        return self._write_outputs(
            ctx,
            service,
            prefix,
            decomposed,
            decomposed.get("chapters") or [],
            [],
            out_book,
            total_src,
            target,
            sequel,
            "local",
            source_chapters=data.get("chapters") or [],
        )

    def _write_outputs(
        self, ctx, service, prefix, book, chapters, name_map, out_book, total_src, target, sequel, mode,
        source_chapters=None,
    ) -> str:
        service.apply_name_map(chapters, name_map)
        chapters = service.dedupe_titles(chapters)
        if isinstance(book, dict) and "chapters" in book:
            decomposed = book
        else:
            decomposed = {
                "book_summary": book.get("book_summary", ""),
                "story_bible": book.get("story_bible", {}) or {},
                "opening": book.get("opening") or {},
                "characters": book.get("characters") or [],
                "factions": book.get("factions") or [],
                "items": book.get("items") or [],
            }
        decomposed["chapters"] = chapters
        decomposed["book_title"] = out_book
        chapters_doc = service.to_chapters_json(decomposed)
        chapters_doc["book_title"] = out_book
        manifest = {
            "prompt_version": PROMPT_VERSION,
            "mode": mode,
            "book": out_book,
            "source_chapters": total_src,
            "output_chapters": len(chapters),
            "target_chapters": target,
            "sequel_chapters": sequel,
            "name_map_count": len(name_map),
            "cost_cents": int(ctx.task.cost_actual_cents or 0),
        }

        # 相似度检查：纯本地 n-gram/句级统计，结果作为独立产物并汇总进 manifest
        from ..services.similarity import compare_chapters

        similarity = compare_chapters(
            source_chapters or [],
            chapters,
            n=ctx.settings.similarity_ngram,
            threshold=ctx.settings.similarity_threshold,
            max_paragraphs=ctx.settings.similarity_max_paragraphs,
        )
        ctx.storage.put_json(f"{prefix}/similarity.json", similarity)
        manifest["similarity"] = {
            "artifact": f"{prefix}/similarity.json",
            "overall_overlap_ratio": similarity["overall_overlap_ratio"],
            "chapters_over_threshold": similarity["chapters_over_threshold"],
            "paragraphs_over_threshold": similarity["paragraphs_over_threshold"],
            "flagged": similarity["chapters_over_threshold"] > 0,
        }
        ctx.storage.put_json(f"{prefix}/decomposed.json", decomposed)
        ctx.storage.put_json(f"{prefix}/chapters.json", chapters_doc)
        ctx.storage.put_json(f"{prefix}/manifest.json", manifest)
        ctx.step("outputs", output_ref=f"{prefix}/manifest.json", meta=manifest)
        ctx.log(f"改编产物已写入对象存储：{prefix}")
        return f"{prefix}/manifest.json"
