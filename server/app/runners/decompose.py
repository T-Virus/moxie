# -*- coding: utf-8 -*-
"""拆解 runner：分段 → 逐段拆解 → 合并 → 签约体检 → 产物落存储。

复用 `src/decompose.py` 的分段/提示词/schema 规范化（见 app/prompts），
本文件只做编排、断点、计量与存储，避免复制第二套拆解逻辑。
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import ROOT_DIR, Settings
from ..db import utcnow
from ..errors import ApiError
from ..models import Task, UsageEvent
from ..prompts import get_prompt_service
from ..services.model_config import resolve_step_model
from ..services.model_gateway import complete_sync, parse_json_text
from ..services.storage import book_slug, task_prefix
from ..services.tasks import DefaultRunner, RunContext, TaskReschedule

logger = logging.getLogger("moxie.runner.decompose")

_ALLOWED_SECRET_KEYS = ("byok_key", "api_key", "authorization", "x-byok-key")


def _allowed_roots(settings: Settings) -> list[Path]:
    roots = []
    for item in (settings.task_source_dirs or "").split(","):
        item = item.strip()
        if not item:
            continue
        path = Path(item)
        if not path.is_absolute():
            path = ROOT_DIR / path
        roots.append(path.resolve())
    return roots


def _resolve_source_path(settings: Settings, raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT_DIR / path
    path = path.resolve()
    if not any(path.is_relative_to(root) for root in _allowed_roots(settings)):
        raise ApiError(422, "source_not_allowed", "源文件路径不在允许的目录内")
    if not path.is_file():
        raise ApiError(422, "source_not_found", "源文件不存在")
    if path.stat().st_size > settings.task_max_source_bytes:
        raise ApiError(422, "source_too_large", "源文件超过大小限制")
    return path


def validate_source_params(
    settings: Settings,
    params: dict,
    storage=None,
    *,
    account_id: int | None = None,
    db=None,
) -> None:
    """创建任务时快速失败；不读取正文。

    路径模式（source_path）仅在 `TASK_SOURCE_DIRS` 白名单内可用；
    上传/产物模式（source_key）还要求 key 属于当前账号（跨账号一律 404）。
    """
    for key in _ALLOWED_SECRET_KEYS:
        if key in (params or {}):
            raise ApiError(422, "secret_in_params_forbidden", "请通过 X-BYOK-Key 请求头传递密钥")
    params = params or {}
    if "source_key" in params:
        from ..services.uploads import owns_source_key

        source_key = str(params["source_key"])
        if account_id is not None and not owns_source_key(db, account_id, source_key):
            raise ApiError(404, "source_not_found", "源文件不存在")
        if storage is not None and not storage.exists(source_key):
            raise ApiError(404, "source_not_found", "源文件不存在")
        return
    if "source_path" in params:
        _resolve_source_path(settings, str(params["source_path"]))


def resolve_source_text(settings: Settings, params: dict, storage=None) -> str:
    if "source_key" in params:
        if storage is None:
            raise ApiError(422, "source_not_found", "产物存储未初始化")
        raw = storage.get_bytes(str(params["source_key"]))
    elif "source_path" in params:
        raw = _resolve_source_path(settings, str(params["source_path"])).read_bytes()
    else:
        raise ApiError(422, "source_not_found", "缺少 params.source_path 或 params.source_key")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("gb18030", "replace")


def _chapter_number(ch) -> int | None:
    if isinstance(ch, int):
        return ch
    if isinstance(ch, str):
        import re

        m = re.search(r"\d+", ch)
        return int(m.group()) if m else None
    return None


def _offset_part(part: dict, offset: int) -> dict:
    """把分段结果里的章节号平移到全书序号，避免每段都从 1 开始。"""
    out = dict(part)
    chapters = []
    for i, ch in enumerate(part.get("chapters") or [], 1):
        if not isinstance(ch, dict):
            continue
        ch = dict(ch)
        ch["chapter"] = offset + i
        chapters.append(ch)
    out["chapters"] = chapters
    _ = _chapter_number  # 保留辅助函数给外部复用
    return out


def _subtract(items: list, key: str) -> list[dict]:
    seen, out = set(), []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get(key) or item.get("name") or "").strip()
        if name and name in seen:
            continue
        if name:
            seen.add(name)
        out.append(item)
    return out


def merge_parts(parts: list[dict]) -> dict:
    """本地合并：章节按顺序拼接，卡片按名称去重，设定库取首个非空。"""
    if not parts:
        return {"book_summary": "", "opening": {}, "story_bible": {}, "characters": [], "factions": [], "items": [], "chapters": []}
    merged = {
        "book_summary": next((p.get("book_summary") for p in parts if p.get("book_summary")), ""),
        "opening": next((p.get("opening") for p in parts if p.get("opening")), {}),
        "story_bible": {},
        "characters": _subtract([c for p in parts for c in (p.get("characters") or [])], "name"),
        "factions": _subtract([c for p in parts for c in (p.get("factions") or [])], "name"),
        "items": _subtract([c for p in parts for c in (p.get("items") or [])], "name"),
        "chapters": [c for p in parts for c in (p.get("chapters") or []) if isinstance(c, dict)],
    }
    for part in parts:
        sb = part.get("story_bible")
        if not isinstance(sb, dict):
            continue
        for key, value in sb.items():
            if value and not merged["story_bible"].get(key):
                merged["story_bible"][key] = value
    return merged


class DecomposeRunner:
    """真实拆解执行器；params 中没有源文件时退回骨架 runner（兼容旧测试）。"""

    def run(self, ctx: RunContext) -> str | None:
        params = ctx.task.params or {}
        if not ("source_path" in params or "source_key" in params):
            return DefaultRunner(4).run(ctx)

        settings = ctx.settings or Settings()
        storage = ctx.storage
        if storage is None:
            from ..services.storage import build_storage

            storage = build_storage(settings, session=ctx.session)
        prompt = get_prompt_service(settings)

        mode = str(params.get("mode") or "reference")
        limit = int(params.get("limit") or 0)
        chunk_chars = int(params.get("chunk_chars") or 6000)
        chunk_chapters = int(params.get("chunk_chapters") or 2)
        min_chapters = int(params.get("min_chapters") or 0)
        local = bool(params.get("local"))
        want_raw = bool(params.get("raw"))
        book = str(params.get("book") or ctx.task.book_id or "book")
        prefix = task_prefix(book, ctx.task.id)

        text = resolve_source_text(settings, params, storage)
        text = prompt.slice_first_chapters(text, limit)
        segments = prompt.split_text(text, limit=chunk_chars, max_chapters=chunk_chapters, min_chapters=min_chapters)
        if not segments:
            raise ApiError(422, "source_empty", "源文件没有可拆解内容")
        ctx.log(f"拆解开始：{len(segments)} 段，模式 {mode}，提示词版本 {prompt.version}")
        storage.put_bytes(f"{prefix}/source.txt", text.encode("utf-8"), "text/plain")

        offset = 0
        new_segments = 0
        batch = max(0, int(settings.decompose_segment_batch or 0))
        for index, segment in enumerate(segments, 1):
            ctx.check_cancel()
            step_key = f"seg:{index:03d}"
            step = ctx.get_step(step_key)
            part_key = f"{prefix}/segments/seg-{index:03d}.json"
            if step is not None and step.status == "done":
                if storage.exists(part_key):
                    ctx.log(f"第 {index}/{len(segments)} 段已完成，断点续跑跳过")
                    offset += len((storage.get_json(part_key).get("chapters") or []))
                    continue
                # 步骤在但产物丢失：视为损坏，重跑该段
                ctx.log(f"第 {index} 段产物丢失，重新执行", level="warning")
                ctx.step(step_key, output_ref=None, status="failed", meta={"status": "artifact_missing"})

            chapter_note = f"本段为全书第 {index}/{len(segments)} 段，章节序号从 {offset + 1} 开始。只输出本段内容。"
            part = None
            if local:
                part = prompt.local_decompose(segment)
                result = None
            else:
                rendered = prompt.build_segment_prompt(mode, segment, limit=None, chunk_note=chapter_note)
                messages = []
                system = prompt.system_prompt()
                if system:
                    messages.append({"role": "system", "content": system})
                messages.append({"role": "user", "content": rendered})
                resolved = resolve_step_model(ctx.session, "decompose", settings, api_key=ctx.byok_key or None)
                result = complete_sync(
                    settings,
                    messages,
                    model=resolved.model,
                    api_key=resolved.api_key,
                    byok=bool(ctx.byok_key),
                    expect_json=True,
                    base_url=resolved.base_url or None,
                )
                try:
                    part = parse_json_text(result.text)
                except ValueError as exc:
                    raise ApiError(502, "model_invalid_json", "模型返回不是合法 JSON") from exc

            part = _offset_part(part, offset)
            chapters_in_part = len(part.get("chapters") or [])
            offset += chapters_in_part
            storage.put_json(part_key, part)
            if want_raw and result is not None:
                storage.put_bytes(f"{prefix}/raw/seg-{index:03d}.txt", result.text.encode("utf-8"), "text/plain")

            meta = {
                "index": index,
                "status": "done",
                "input_chars": len(segment),
                "chapters": chapters_in_part,
                "artifact_key": part_key,
            }
            if result is not None:
                meta.update(
                    {
                        "prompt_tokens": result.prompt_tokens,
                        "completion_tokens": result.completion_tokens,
                        "total_tokens": result.total_tokens,
                        "cost_cents": result.cost_cents,
                        "model": result.model,
                        "byok": result.byok,
                        "route": result.route,
                    }
                )
                _record_usage(ctx.session, ctx.task, result, f"seg:{index:03d}", settings)
                ctx.task.cost_actual_cents = (ctx.task.cost_actual_cents or 0) + result.cost_cents
                ctx.log(
                    f"第 {index}/{len(segments)} 段完成：输入 {len(segment)} 字，"
                    f"token {result.total_tokens}，成本 {result.cost_cents} 分"
                )
            else:
                ctx.log(f"第 {index}/{len(segments)} 段完成（本地模式）：输入 {len(segment)} 字")
            ctx.step(step_key, output_ref=part_key, meta=meta)
            new_segments += 1
            ctx.progress(int(5 + index * 80 / max(1, len(segments))))

            if batch and new_segments >= batch:
                remaining = any(
                    (ctx.get_step(f"seg:{i:03d}") is None or ctx.get_step(f"seg:{i:03d}").status != "done")
                    for i in range(index + 1, len(segments) + 1)
                )
                if remaining:
                    ctx.log(f"达到本次批量上限 {batch} 段，让出 worker，剩余段下次继续", level="warning")
                    raise TaskReschedule()

        ctx.check_cancel()
        parts = []
        for index in range(1, len(segments) + 1):
            part_key = f"{prefix}/segments/seg-{index:03d}.json"
            if not storage.exists(part_key):
                raise ApiError(500, "segment_artifact_missing", "分段产物缺失，无法合并")
            parts.append(storage.get_json(part_key))

        merged = self._merge(ctx, settings, prompt, parts, prefix, params)
        chapters_doc = prompt.to_chapters_json(merged)
        chapters_doc["signing_check"] = prompt.signing_check(chapters_doc.get("chapters") or [], chapters_doc.get("opening"))
        chapters_doc["prompt_version"] = prompt.version
        chapters_doc["book"] = book_slug(book)

        decomposed_key = f"{prefix}/decomposed.json"
        chapters_key = f"{prefix}/chapters.json"
        manifest_key = f"{prefix}/manifest.json"
        storage.put_json(decomposed_key, merged)
        storage.put_json(chapters_key, chapters_doc)
        storage.put_json(
            manifest_key,
            {
                "task_id": ctx.task.id,
                "book": book,
                "mode": mode,
                "prompt_version": prompt.version,
                "model": str(params.get("model") or settings.llm_model),
                "stub": settings.model_stub,
                "segments": len(segments),
                "segments_done": len(parts),
                "chapters": len(chapters_doc.get("chapters") or []),
                "total_cost_cents": ctx.task.cost_actual_cents or 0,
                "duration_seconds": int((utcnow() - ctx.task.started_at).total_seconds())
                if ctx.task.started_at
                else None,
                "artifacts": [decomposed_key, chapters_key],
            },
        )
        ctx.step("outputs", output_ref=decomposed_key, meta={"chapters": len(chapters_doc.get("chapters") or [])})
        ctx.progress(99)
        ctx.log(f"拆解完成：{len(parts)} 段，{len(chapters_doc.get('chapters') or [])} 章，产物已写入对象存储")
        return prefix

    def _merge(self, ctx: RunContext, settings: Settings, prompt, parts: list[dict], prefix: str, params: dict) -> dict:
        settings_storage = ctx.storage
        if settings_storage is None:
            from ..services.storage import build_storage

            settings_storage = build_storage(settings, session=ctx.session)
        merge_key = f"{prefix}/merged.json"
        step = ctx.get_step("merge")
        if step is not None and step.status == "done" and settings_storage.exists(merge_key):
            ctx.log("合并结果已存在，断点续跑跳过合并")
            return settings_storage.get_json(merge_key)

        local_merged = merge_parts(parts)
        if len(parts) == 1:
            merged = local_merged
            settings_storage.put_json(merge_key, merged)
            ctx.step("merge", output_ref=merge_key, meta={"segments": 1, "cost_cents": 0})
            return merged

        summaries = "\n".join(
            f"{p.get('book_summary', '')[:120]}" for p in parts if p.get("book_summary")
        )
        cast = "、".join(
            {c.get("name") for p in parts for c in (p.get("characters") or []) if isinstance(c, dict) and c.get("name")}
        )
        ctx.check_cancel()
        try:
            rendered = prompt.build_merge_prompt(parts, summaries, cast)
            resolved = resolve_step_model(ctx.session, "decompose", settings, api_key=ctx.byok_key or None)
            result = complete_sync(
                settings,
                [{"role": "user", "content": rendered}],
                model=resolved.model,
                api_key=resolved.api_key,
                byok=bool(ctx.byok_key),
                expect_json=True,
                base_url=resolved.base_url or None,
            )
            merged_model = parse_json_text(result.text)
            merged = dict(local_merged)
            if merged_model.get("book_summary"):
                merged["book_summary"] = merged_model["book_summary"]
            if isinstance(merged_model.get("story_bible"), dict):
                merged["story_bible"] = {**merged["story_bible"], **merged_model["story_bible"]}
            if merged_model.get("chapters"):
                merged["chapters"] = merged_model["chapters"]
            merged["characters"] = _subtract(
                local_merged["characters"] + (merged_model.get("characters") or []), "name"
            )
            merged["factions"] = _subtract(
                local_merged["factions"] + (merged_model.get("factions") or []), "name"
            )
            merged["items"] = _subtract(local_merged["items"] + (merged_model.get("items") or []), "name")
            _record_usage(ctx.session, ctx.task, result, "merge", settings)
            ctx.task.cost_actual_cents = (ctx.task.cost_actual_cents or 0) + result.cost_cents
            ctx.log(f"合并完成：token {result.total_tokens}，成本 {result.cost_cents} 分")
            meta = {
                "status": "done",
                "segments": len(parts),
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "total_tokens": result.total_tokens,
                "cost_cents": result.cost_cents,
                "model": result.model,
            }
        except (ApiError, ValueError) as exc:
            ctx.log(f"模型合并失败，使用本地合并结果：{exc}", level="warning")
            merged = local_merged
            meta = {"status": "done", "segments": len(parts), "cost_cents": 0, "fallback": "local_merge"}

        settings_storage.put_json(merge_key, merged)
        ctx.step("merge", output_ref=merge_key, meta=meta)
        return merged


def _record_usage(session: Session, task: Task, result, tag: str, settings: Settings) -> None:
    """逐段归集 token/成本；唯一键防重放。"""
    key = f"task:{task.id}:{tag}:model"
    try:
        with session.begin_nested():
            session.add(
                UsageEvent(
                    account_id=task.account_id,
                    task_id=task.id,
                    metric="model_token",
                    quantity=result.total_tokens,
                    unit="token",
                    idempotency_key=key,
                    occurred_at=utcnow(),
                    meta={
                        "model": result.model,
                        "prompt_tokens": result.prompt_tokens,
                        "completion_tokens": result.completion_tokens,
                        "total_tokens": result.total_tokens,
                        "cost_cents": result.cost_cents,
                        "byok": result.byok,
                        "route": result.route,
                    },
                )
            )
            session.flush()
    except IntegrityError:
        logger.info("usage event 已存在，跳过重复归集 task=%s tag=%s", task.id, tag)
