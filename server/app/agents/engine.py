# -*- coding: utf-8 -*-
"""编排引擎：确定性拓扑执行 + 同层并发 + 节点重试 + checkpoint + 人工介入。

LLM 只出现在 skill 内部与（未来）意图解析；这里绝不根据模型输出改变图结构。
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import utcnow
from ..errors import ApiError
from ..metrics import increment
from ..models import AgentRun, AgentRunStep, AuditLog, UsageEvent
from ..services.model_gateway import ModelResult
from ..services.quota import QuotaService
from .artifacts import prefix_of, write_artifacts
from .contracts import SkillContext
from .graph import Graph, NodeSpec, RunView, get_graph
from .registry import registry
from .segmenter import merge_parts, plan_segments
from .store import TERMINAL_STATUSES, append_event, reservation_of

logger = logging.getLogger("moxie.agents")


@dataclass
class NodeOutcome:
    node_id: str
    output: dict | None
    error: str | None
    attempts: int
    records: list[tuple[int, ModelResult]] = field(default_factory=list)
    logs: list[tuple[str, str]] = field(default_factory=list)
    duration_ms: int = 0
    error_code: str | None = None
    canceled: bool = False


def _segment_key(node_id: str, index: int) -> str:
    return f"{node_id}:seg:{index:03d}"


def _dump(output) -> dict:  # noqa: ANN001
    if hasattr(output, "model_dump"):
        return output.model_dump()
    if isinstance(output, dict):
        return output
    raise TypeError(f"skill 输出必须是 Pydantic 模型或 dict，实际为 {type(output).__name__}")


def _run_node(
    node: NodeSpec,
    view: RunView,
    state: dict,
    extra: dict,
    skill,
    settings: Settings,
    *,
    api_key: str,
    byok: bool,
) -> NodeOutcome:
    attempts = max(1, node.retries + 1)
    records: list[tuple[int, ModelResult]] = []
    logs: list[tuple[str, str]] = []
    error: str | None = None
    error_code: str | None = None
    started = time.perf_counter()
    for attempt in range(1, attempts + 1):
        ctx = SkillContext(
            settings=settings,
            model=settings.llm_model,
            api_key=api_key,
            byok=byok,
        )
        try:
            payload = node.builder(view, state, extra)
            validated = skill.input_model(**payload) if skill.input_model else payload
            output = skill.run(validated, ctx)
            data = _dump(output)
            if skill.output_model:
                skill.output_model(**data)  # 输出契约校验，防止下游拿到脏数据
            records.extend((attempt, item) for item in ctx.usage)
            logs.extend(ctx.logs)
            return NodeOutcome(
                node_id=node.id,
                output=data,
                error=None,
                attempts=attempt,
                records=records,
                logs=logs,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:  # noqa: BLE001 - 节点失败由重试策略收敛
            error = f"{type(exc).__name__}: {exc}"[:240]
            error_code = getattr(exc, "code", None) or error_code
            records.extend((attempt, item) for item in ctx.usage)
            logs.extend(ctx.logs)
            logs.append(("error", f"第 {attempt} 次尝试失败：{error}"))
            logger.warning("agent node failed run=%s node=%s attempt=%s: %s", view.id, node.id, attempt, error)
    return NodeOutcome(
        node_id=node.id,
        output=None,
        error=error or "unknown",
        attempts=attempts,
        records=records,
        logs=logs,
        duration_ms=int((time.perf_counter() - started) * 1000),
        error_code=error_code,
    )


def _run_segmented_node(
    session: Session,
    run: AgentRun,
    node: NodeSpec,
    view: RunView,
    state: dict,
    extra: dict,
    skill,
    settings: Settings,
    *,
    storage,
    api_key: str,
    byok: bool,
) -> NodeOutcome:
    """逐段执行拆解：段级 checkpoint、失败只重试当前段、段级 SSE 事件。

    段结果先落 `segments/seg-NNN.json`，全部完成后再本地合并为全书结果；
    合并结果由引擎写入 `outline_decompose` 节点 checkpoint（decomposed.json 随之落盘）。
    """
    started = time.perf_counter()
    logs: list[tuple[str, str]] = []
    try:
        plan = plan_segments(
            settings,
            extra.get("source_text") or "",
            target_chapters=int(extra.get("target_chapters") or 0),
        )
    except ApiError as exc:
        logs.append(("error", f"分段规划失败：{exc.message}"))
        return NodeOutcome(
            node_id=node.id,
            output=None,
            error=f"{exc.code}: {exc.message}"[:240],
            attempts=1,
            logs=logs,
            duration_ms=int((time.perf_counter() - started) * 1000),
            error_code=exc.code,
        )
    if storage is None:
        return NodeOutcome(
            node_id=node.id,
            output=None,
            error="storage_missing: 产物存储未初始化",
            attempts=1,
            error_code="storage_missing",
        )

    total = plan.count
    prefix = prefix_of(view)
    rows = {
        row.node_key: row
        for row in session.scalars(
            select(AgentRunStep).where(AgentRunStep.run_id == run.id)
        ).all()
    }
    attempts_used = 1
    append_event(
        session,
        run.id,
        node.id,
        f"分段拆解开始：共 {total} 段，{plan.total_chars} 字（{plan.mode} 模式）",
    )
    session.flush()

    for segment in plan.segments:
        session.refresh(run)
        if run.cancel_requested:
            return NodeOutcome(
                node_id=node.id,
                output=None,
                error="canceled",
                attempts=attempts_used,
                logs=logs,
                duration_ms=int((time.perf_counter() - started) * 1000),
                canceled=True,
            )

        index = segment.index
        step_key = _segment_key(node.id, index)
        artifact_key = f"{prefix}/segments/seg-{index:03d}.json"
        row = rows.get(step_key)
        if row is not None and row.status == "done" and storage.exists(artifact_key):
            logs.append(("info", f"第 {index}/{total} 段已完成，断点续跑跳过"))
            append_event(session, run.id, node.id, f"第 {index}/{total} 段已完成，断点续跑跳过")
            continue

        now = utcnow()
        if row is None:
            row = AgentRunStep(
                run_id=run.id,
                node_key=step_key,
                status="pending",
                attempts=0,
                meta={},
                updated_at=now,
            )
            session.add(row)
            rows[step_key] = row
        if row.status == "done":
            logs.append(("warning", f"第 {index} 段产物丢失，重新执行"))
        row.status = "running"
        row.started_at = now
        row.error = None
        row.updated_at = now
        append_event(
            session,
            run.id,
            node.id,
            f"第 {index}/{total} 段开始拆解（{segment.chars} 字）",
        )
        session.flush()

        attempts = max(1, node.retries + 1)
        part: dict | None = None
        last_error: str | None = None
        last_code: str | None = None
        used_attempt = attempts
        for attempt in range(1, attempts + 1):
            attempts_used = max(attempts_used, attempt)
            used_attempt = attempt
            ctx = SkillContext(
                settings=settings,
                model=settings.llm_model,
                api_key=api_key,
                byok=byok,
            )
            try:
                payload = {
                    "title": view.title,
                    "source_text": segment.text,
                    "target_chapters": 0,
                }
                validated = skill.input_model(**payload) if skill.input_model else payload
                output = skill.run(validated, ctx)
                data = _dump(output)
                if skill.output_model:
                    skill.output_model(**data)
                part = data
            except Exception as exc:  # noqa: BLE001 - 只重试当前段
                last_error = f"{type(exc).__name__}: {exc}"[:240]
                last_code = getattr(exc, "code", None) or "segment_failed"
                logger.warning(
                    "agent segment failed run=%s node=%s seg=%s/%s attempt=%s: %s",
                    view.id,
                    node.id,
                    index,
                    total,
                    attempt,
                    last_error,
                )
                logs.append(("error", f"第 {index}/{total} 段第 {attempt} 次失败：{last_error}"))
            finally:
                # 按段即时记账，避免长任务中断后 token/成本丢失
                if ctx.usage:
                    _record_usage(
                        session,
                        run,
                        NodeOutcome(
                            node_id=node.id,
                            output=None,
                            error=None,
                            attempts=attempt,
                            records=[(attempt, item) for item in ctx.usage],
                        ),
                        now=utcnow(),
                        tag=f"{node.id}:seg:{index:03d}",
                    )
            if part is not None:
                logs.extend(ctx.logs)
                break

        finished = utcnow()
        if part is None:
            row.status = "failed"
            row.error = last_error or "unknown"
            row.attempts = used_attempt
            row.finished_at = finished
            row.updated_at = finished
            append_event(
                session,
                run.id,
                node.id,
                f"第 {index}/{total} 段失败：{last_error or 'unknown'}",
                level="error",
            )
            session.flush()
            return NodeOutcome(
                node_id=node.id,
                output=None,
                error=last_error or "unknown",
                attempts=attempts_used,
                logs=logs,
                duration_ms=int((time.perf_counter() - started) * 1000),
                error_code=last_code or "segment_failed",
            )

        part_doc = {
            **part,
            "segment": {"index": index, "total": total, "input_chars": segment.chars},
        }
        storage.put_json(artifact_key, part_doc)
        chapters_in_part = len(part.get("chapters") or [])
        row.status = "done"
        row.output = None
        row.error = None
        row.attempts = used_attempt
        row.finished_at = finished
        row.updated_at = finished
        row.meta = {
            "index": index,
            "total": total,
            "input_chars": segment.chars,
            "chapters": chapters_in_part,
            "artifact_key": artifact_key,
        }
        append_event(
            session,
            run.id,
            node.id,
            f"第 {index}/{total} 段完成：{chapters_in_part} 章，输入 {segment.chars} 字",
        )
        run.progress = min(90, int(5 + 80 * index / total))
        run.updated_at = finished
        session.flush()

    parts = []
    for segment in plan.segments:
        artifact_key = f"{prefix}/segments/seg-{segment.index:03d}.json"
        if not storage.exists(artifact_key):
            return NodeOutcome(
                node_id=node.id,
                output=None,
                error=f"segment_artifact_missing: 第 {segment.index} 段产物缺失",
                attempts=attempts_used,
                logs=logs,
                duration_ms=int((time.perf_counter() - started) * 1000),
                error_code="segment_artifact_missing",
            )
        parts.append(storage.get_json(artifact_key))

    merged = merge_parts(parts)
    merged["segmentation"] = {
        "mode": plan.mode,
        "total_chars": plan.total_chars,
        "segments": total,
        "single_segment": plan.single,
    }
    logs.append(("info", f"合并完成：{total} 段，{len(merged.get('chapters') or [])} 章"))
    append_event(
        session,
        run.id,
        node.id,
        f"分段结果合并完成：{total} 段，{len(merged.get('chapters') or [])} 章",
    )
    session.flush()
    return NodeOutcome(
        node_id=node.id,
        output=merged,
        error=None,
        attempts=attempts_used,
        logs=logs,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def _chapter_key(node_id: str, index: int) -> str:
    return f"{node_id}:ch:{index:03d}"


def _merge_chapter_parts(parts: list[dict]) -> dict:
    merged: dict = {"chapters": []}
    for part in parts:
        merged["chapters"].extend(part.get("chapters") or [])
    return merged


def _run_chaptered_node(
    session: Session,
    run: AgentRun,
    node: NodeSpec,
    view: RunView,
    state: dict,
    extra: dict,
    skill,
    settings: Settings,
    *,
    api_key: str,
    byok: bool,
) -> NodeOutcome:
    """逐章执行：章级 checkpoint、单章失败只重试该章、章级 SSE 与章级记账。

    仅 `chapter_write` 消耗 `adapt_chapters` 与 `managed_chars`；概括节点只读正文。
    """
    started = time.perf_counter()
    logs: list[tuple[str, str]] = []
    try:
        payload = node.builder(view, state, extra)
    except Exception as exc:  # noqa: BLE001 - builder 失败按节点失败收敛
        return NodeOutcome(
            node_id=node.id,
            output=None,
            error=f"{type(exc).__name__}: {exc}"[:240],
            attempts=1,
            logs=logs,
            duration_ms=int((time.perf_counter() - started) * 1000),
            error_code="chapters_missing",
        )
    chapters = [dict(item) for item in (payload.get("chapters") or []) if isinstance(item, dict)]
    total = len(chapters)
    if total == 0:
        logs.append(("error", "没有可执行的章节"))
        return NodeOutcome(
            node_id=node.id,
            output=None,
            error="chapters_missing: 没有可执行的章节",
            attempts=1,
            logs=logs,
            duration_ms=int((time.perf_counter() - started) * 1000),
            error_code="chapters_missing",
        )

    rows = {
        row.node_key: row
        for row in session.scalars(select(AgentRunStep).where(AgentRunStep.run_id == run.id)).all()
    }
    quota = QuotaService(session)
    chapter_reservation = None
    if node.skill == "chapter_write":
        try:
            chapter_reservation = quota.reserve(run.account_id, "adapt_chapters", total)
        except ApiError as exc:
            logs.append(("error", f"章节额度不足：{exc.message}"))
            append_event(session, run.id, node.id, f"章节额度不足：{exc.message}", level="error")
            session.flush()
            return NodeOutcome(
                node_id=node.id,
                output=None,
                error=f"{exc.code}: {exc.message}"[:240],
                attempts=1,
                logs=logs,
                duration_ms=int((time.perf_counter() - started) * 1000),
                error_code=exc.code,
            )
        append_event(session, run.id, node.id, f"章节写作开始：共 {total} 章")
    else:
        append_event(session, run.id, node.id, f"章节处理开始：共 {total} 章")
    session.flush()

    parts: list[dict] = []
    attempts_used = 1
    for index, chapter in enumerate(chapters, 1):
        session.refresh(run)
        if run.cancel_requested:
            if chapter_reservation is not None:
                quota.release(chapter_reservation)
            return NodeOutcome(
                node_id=node.id,
                output=None,
                error="canceled",
                attempts=attempts_used,
                logs=logs,
                duration_ms=int((time.perf_counter() - started) * 1000),
                canceled=True,
            )
        step_key = _chapter_key(node.id, index)
        row = rows.get(step_key)
        if row is not None and row.status == "done" and isinstance(row.output, dict):
            parts.append(row.output)
            logs.append(("info", f"第 {index}/{total} 章已完成，断点续跑跳过"))
            append_event(session, run.id, node.id, f"第 {index}/{total} 章已完成，断点续跑跳过")
            continue
        if row is None:
            row = AgentRunStep(
                run_id=run.id, node_key=step_key, status="pending", attempts=0, meta={}, updated_at=utcnow()
            )
            session.add(row)
            rows[step_key] = row
        row.status = "running"
        row.error = None
        row.meta = {"index": index, "total": total, "title": chapter.get("title") or ""}
        row.updated_at = utcnow()
        append_event(
            session,
            run.id,
            node.id,
            f"第 {index}/{total} 章开始：{chapter.get('title') or f'第{index}章'}",
        )
        session.flush()

        attempts = max(1, node.retries + 1)
        last_error: str | None = None
        last_code: str | None = None
        part: dict | None = None
        used_attempt = 1
        for attempt in range(1, attempts + 1):
            used_attempt = attempt
            ctx = SkillContext(settings=settings, model=settings.llm_model, api_key=api_key, byok=byok)
            try:
                chapter_payload = {**payload, "chapters": [chapter]}
                validated = skill.input_model(**chapter_payload) if skill.input_model else chapter_payload
                output = skill.run(validated, ctx)
                data = _dump(output)
                if skill.output_model:
                    skill.output_model(**data)
                part = data
                attempts_used = max(attempts_used, attempt)
                for uindex, item in enumerate(ctx.usage):
                    _record_usage_item(
                        session,
                        run,
                        item,
                        now=utcnow(),
                        tag=f"{node.id}:ch:{index:03d}",
                        attempt=attempt,
                        index=uindex,
                    )
                logs.extend(ctx.logs)
                break
            except Exception as exc:  # noqa: BLE001 - 单章失败只重试当前章
                last_error = f"{type(exc).__name__}: {exc}"[:240]
                last_code = getattr(exc, "code", None) or last_code
                logs.extend(ctx.logs)
                logs.append(("error", f"第 {index} 章第 {attempt} 次尝试失败：{last_error}"))
                for uindex, item in enumerate(ctx.usage):
                    _record_usage_item(
                        session,
                        run,
                        item,
                        now=utcnow(),
                        tag=f"{node.id}:ch:{index:03d}",
                        attempt=attempt,
                        index=uindex,
                    )
                logger.warning(
                    "agent chapter failed run=%s node=%s chapter=%s attempt=%s: %s",
                    view.id,
                    node.id,
                    index,
                    attempt,
                    last_error,
                )

        if part is None:
            row.status = "failed"
            row.error = last_error or "unknown"
            row.attempts = used_attempt
            row.finished_at = utcnow()
            row.updated_at = row.finished_at
            append_event(
                session,
                run.id,
                node.id,
                f"第 {index}/{total} 章失败：{last_error or 'unknown'}",
                level="error",
            )
            if chapter_reservation is not None:
                quota.release(chapter_reservation)
            session.flush()
            return NodeOutcome(
                node_id=node.id,
                output=None,
                error=last_error or "unknown",
                attempts=attempts_used,
                logs=logs,
                duration_ms=int((time.perf_counter() - started) * 1000),
                error_code=last_code or "chapter_failed",
            )

        content = ""
        written = part.get("chapters") or []
        if written and isinstance(written[0], dict):
            content = str(written[0].get("content") or "")
            if node.skill == "chapter_write":
                written[0]["word_count"] = len(content)
        if node.skill == "chapter_write" and run.account_id is not None:
            try:
                chars = max(len(content), 1)
                res = quota.reserve(run.account_id, "managed_chars", chars)
                committed = quota.commit(
                    res,
                    idempotency_key=f"agent:{run.id}:managed_chars:{node.id}:ch:{index:03d}",
                    task_id=None,
                )
                if not committed:
                    quota.release(res)
            except ApiError as exc:
                row.status = "failed"
                row.error = exc.message
                row.finished_at = utcnow()
                row.updated_at = row.finished_at
                append_event(session, run.id, node.id, f"第 {index} 章字数额度不足：{exc.message}", level="error")
                if chapter_reservation is not None:
                    quota.release(chapter_reservation)
                session.flush()
                return NodeOutcome(
                    node_id=node.id,
                    output=None,
                    error=f"{exc.code}: {exc.message}"[:240],
                    attempts=attempts_used,
                    logs=logs,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    error_code=exc.code,
                )

        row.status = "done"
        row.output = part
        row.error = None
        row.attempts = used_attempt
        row.finished_at = utcnow()
        row.updated_at = row.finished_at
        parts.append(part)
        append_event(
            session,
            run.id,
            node.id,
            (
                f"第 {index}/{total} 章完成：{len(content)} 字"
                if node.skill == "chapter_write"
                else f"第 {index}/{total} 章完成"
            ),
        )
        if node.skill == "chapter_write":
            increment("moxie_agent_chapters_total", mode=run.mode)
            increment("moxie_agent_chapter_chars_total", len(content), mode=run.mode)
        run.progress = min(95, int(5 + 85 * index / total))
        run.updated_at = row.finished_at
        session.flush()

    if chapter_reservation is not None:
        committed = quota.commit(
            chapter_reservation,
            idempotency_key=f"agent:{run.id}:adapt_chapters",
        )
        if not committed:
            quota.release(chapter_reservation)

    merged = _merge_chapter_parts(parts)
    logs.append(("info", f"逐章执行完成：{len(merged['chapters'])} 章"))
    append_event(
        session,
        run.id,
        node.id,
        f"{node.label}完成：{len(merged['chapters'])} 章",
    )
    session.flush()
    return NodeOutcome(
        node_id=node.id,
        output=merged,
        error=None,
        attempts=attempts_used,
        logs=logs,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def execute_agent_run(
    session: Session,
    run: AgentRun,
    *,
    settings: Settings,
    storage=None,
    byok: bool = False,
    api_key: str = "",
    skill_overrides: dict | None = None,
    max_steps: int | None = None,
) -> str:
    """执行（或续跑）一条运行；返回最终状态。调用方负责 commit。"""
    graph = get_graph(run.mode)
    if run.status in TERMINAL_STATUSES:
        return run.status
    if run.status == "paused":
        return "paused"

    now = utcnow()
    if run.cancel_requested:
        _finish_canceled(session, run, now=now)
        return run.status

    run.status = "running"
    run.attempts += 1
    if run.started_at is None:
        run.started_at = now
    run.updated_at = now
    append_event(session, run.id, "run", f"开始执行（第 {run.attempts} 次尝试，mode={run.mode}）")
    increment("moxie_agent_runs_started_total", mode=run.mode)
    session.flush()

    view = RunView(
        id=run.id,
        mode=run.mode,
        title=run.title,
        audience=run.audience,
        length=run.length,
        genre_id=run.genre_id,
        genre_name=run.genre_name,
        source_key=run.source_key,
        brief=run.brief,
        meta=dict(run.meta or {}),
    )
    extra: dict = {
        "target_chapters": 0,
        "resume_input": (run.meta or {}).get("resume_input"),
        "source_text": "",
        "options": dict((run.meta or {}).get("options") or {}),
    }
    if run.mode == "reference":
        source = _load_source(storage, run.source_key)
        if source is None:
            _finish_failed(session, run, code="source_unreadable", message="参考作品源文件不存在或不可读", now=now)
            return run.status
        extra["source_text"] = source
        extra["target_chapters"] = 0

    steps = {
        row.node_key: row
        for row in session.scalars(select(AgentRunStep).where(AgentRunStep.run_id == run.id)).all()
    }
    state = {
        key: row.output
        for key, row in steps.items()
        if row.status == "done" and isinstance(row.output, dict)
    }
    if not steps:
        for node in graph.nodes:
            row = AgentRunStep(run_id=run.id, node_key=node.id, status="pending", attempts=0, meta={}, updated_at=now)
            session.add(row)
            steps[node.id] = row
        session.flush()

    patched = _apply_resume_input(state, steps, extra.get("resume_input"))
    if patched:
        append_event(session, run.id, "review", "已应用人工修改的章节内容，将重新执行体检")
        session.flush()

    quota = QuotaService(session)
    reservation = reservation_of(session, run)
    executed = 0
    overrides = skill_overrides or {}

    for layer in graph.layers():
        session.refresh(run)
        if run.cancel_requested:
            _finish_canceled(session, run, reservation=reservation, now=utcnow())
            return run.status
        meta = dict(run.meta or {})
        if meta.get("pause_requested"):
            # 用户主动停止：清掉标记后置 paused，额度预占保留，可 resume 续跑
            meta.pop("pause_requested", None)
            run.meta = meta
            run.status = "paused"
            run.current_stage = None
            run.updated_at = utcnow()
            append_event(session, run.id, "run", "已按用户请求停止，可继续生成或取消任务", level="warning")
            session.flush()
            return run.status
        pending = [node for node in layer if steps.get(node.id) is None or steps[node.id].status != "done" or node.id not in state]
        if not pending:
            continue
        if max_steps is not None:
            allowed = max_steps - executed
            if allowed <= 0:
                _requeue(session, run, now=utcnow())
                return run.status
            pending = pending[:allowed]

        started = utcnow()
        for node in pending:
            row = steps[node.id]
            row.status = "running"
            row.started_at = started
            row.error = None
            row.updated_at = started
            append_event(session, run.id, node.id, f"{node.label} 开始执行")
        run.current_stage = pending[0].id
        run.updated_at = started
        session.flush()

        def _invoke(node: NodeSpec, _state=state) -> NodeOutcome:
            skill = overrides.get(node.skill) or registry.get(node.skill)
            return _run_node(
                node,
                view,
                _state,
                extra,
                skill,
                settings,
                api_key=api_key,
                byok=byok,
            )

        outcomes: list[NodeOutcome] = []
        # 分段/章级节点在主线程串行执行（需要写子级 checkpoint），其余节点同层并发
        for node in pending:
            if not node.segmented and not node.chaptered:
                continue
            skill = overrides.get(node.skill) or registry.get(node.skill)
            if node.segmented:
                outcomes.append(
                    _run_segmented_node(
                        session,
                        run,
                        node,
                        view,
                        state,
                        extra,
                        skill,
                        settings,
                        storage=storage,
                        api_key=api_key,
                        byok=byok,
                    )
                )
            else:
                outcomes.append(
                    _run_chaptered_node(
                        session,
                        run,
                        node,
                        view,
                        state,
                        extra,
                        skill,
                        settings,
                        api_key=api_key,
                        byok=byok,
                    )
                )
        parallel = [node for node in pending if not node.segmented and not node.chaptered]
        if parallel:
            workers = min(4, len(parallel))
            with ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="agent-node") as pool:
                outcomes.extend(list(pool.map(_invoke, parallel)))

        failed = False
        canceled = False
        failed_code: str | None = None
        failed_message: str | None = None
        finished = utcnow()
        for outcome in outcomes:
            row = steps[outcome.node_id]
            row.attempts = outcome.attempts
            row.finished_at = finished
            row.updated_at = finished
            executed += 1
            _record_usage(session, run, outcome, now=finished)
            if outcome.canceled:
                canceled = True
                row.status = "pending"
                row.output = None
                row.error = "canceled"
                continue
            if outcome.output is not None:
                row.status = "done"
                row.output = outcome.output
                row.error = None
                state[outcome.node_id] = outcome.output
                node = graph.node(outcome.node_id)
                append_event(
                    session,
                    run.id,
                    outcome.node_id,
                    f"{node.label if node else outcome.node_id} 完成（{outcome.duration_ms}ms）",
                )
            else:
                failed = True
                row.status = "failed"
                row.output = None
                row.error = outcome.error
                failed_code = failed_code or outcome.error_code or "stage_failed"
                failed_message = failed_message or outcome.error
                node = graph.node(outcome.node_id)
                append_event(
                    session,
                    run.id,
                    outcome.node_id,
                    f"{node.label if node else outcome.node_id} 失败：{outcome.error}",
                    level="error",
                )
            spec = graph.node(outcome.node_id)
            increment(
                "moxie_skill_calls_total",
                skill=spec.skill if spec else outcome.node_id,
                status="succeeded" if outcome.output is not None else "failed",
            )
            increment(
                "moxie_skill_duration_seconds_total",
                outcome.duration_ms / 1000,
                skill=spec.skill if spec else outcome.node_id,
            )

        if canceled:
            _finish_canceled(session, run, reservation=reservation, now=finished)
            return run.status

        done_count = sum(
            1
            for node in graph.nodes
            if steps.get(node.id) is not None and steps[node.id].status == "done"
        )
        run.progress = min(99, int(done_count * 100 / max(1, len(graph.nodes))))
        run.current_stage = _next_stage(graph, steps)
        run.updated_at = finished
        session.flush()

        try:
            write_artifacts(storage, view, state)
        except Exception as exc:  # noqa: BLE001 - 产物写入失败不应吞掉已完成节点
            append_event(session, run.id, "artifacts", f"产物写入失败：{type(exc).__name__}", level="warning")

        if failed:
            _finish_failed(
                session,
                run,
                code=failed_code or "stage_failed",
                message=(failed_message or f"节点 {_failed_nodes(steps)} 执行失败，请重试该节点或检查模型配置")[:255],
                reservation=reservation,
                now=finished,
            )
            return run.status

    # 审查只记录风险与建议，任何模式都不暂停等待人工确认
    review = state.get("review") or {}
    if review.get("high_risk"):
        run.meta = {
            **dict(run.meta or {}),
            "review_high_risk": True,
            "review_risks": review.get("risks") or [],
            "review_suggestions": review.get("suggestions") or [],
        }
        append_event(
            session,
            run.id,
            "review",
            "体检发现高危问题，已记录风险与修改建议",
            level="warning",
        )

    try:
        write_artifacts(storage, view, state)
    except Exception as exc:  # noqa: BLE001
        append_event(session, run.id, "artifacts", f"产物写入失败：{type(exc).__name__}", level="warning")

    run.status = "succeeded"
    run.progress = 100
    run.current_stage = graph.nodes[-1].id
    run.finished_at = utcnow()
    run.updated_at = run.finished_at
    run.error_code = None
    run.error_message = None
    quota.commit(
        reservation,
        idempotency_key=f"agent:{run.id}:{reservation.metric}",
        meta={"source": "agent_run", "mode": run.mode, "title": run.title},
        now=run.finished_at,
    )
    append_event(session, run.id, "run", "运行完成，额度已结算")
    duration = (run.finished_at - run.started_at).total_seconds() if run.started_at else 0
    increment("moxie_agent_runs_total", status="succeeded", mode=run.mode)
    increment("moxie_agent_run_duration_seconds_total", max(0, int(duration)), mode=run.mode)
    session.add(
        AuditLog(
            actor_id=run.account_id,
            action="agent_run.execute",
            target_type="agent_run",
            target_id=run.id[:36],
            ip=None,
            ua=None,
            meta={
                "mode": run.mode,
                "title": run.title,
                "tokens_total": run.tokens_total,
                "cost_cents": run.cost_cents,
                "duration_seconds": int(duration),
            },
        )
    )
    session.flush()
    return run.status


def _load_source(storage, source_key: str | None) -> str | None:
    if not source_key or storage is None:
        return None
    try:
        raw = storage.get_bytes(source_key)
    except Exception:  # noqa: BLE001 - 由调用方转成明确错误码
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("gb18030", "replace")


def _apply_resume_input(state: dict, steps: dict, resume_input) -> bool:  # noqa: ANN001
    """把 resume 携带的章节改写落到产出节点 checkpoint，保证产物与详情一致。"""
    if not resume_input:
        return False
    chapter_node = "chapter_expand" if "chapter_expand" in state else "adaptation"
    payload = state.get(chapter_node) or {}
    chapters = payload.get("chapters") or []
    chapter_no = resume_input.get("chapter_no")
    content = resume_input.get("content")
    if not chapters or not chapter_no or not content:
        return False
    updated = []
    for chapter in chapters:
        item = dict(chapter)
        if int(item.get("chapter") or 0) == int(chapter_no):
            item["content"] = str(content)
            item["word_count"] = len(str(content))
        updated.append(item)
    payload = {**payload, "chapters": updated}
    state[chapter_node] = payload
    row = steps.get(chapter_node)
    if row is not None:
        row.output = payload
    return True


def _next_stage(graph: Graph, steps: dict) -> str | None:
    for node in graph.nodes:
        row = steps.get(node.id)
        if row is None or row.status != "done":
            return node.id
    return None


def _failed_nodes(steps: dict[str, AgentRunStep]) -> str:
    keys: list[str] = []
    for key, row in steps.items():
        if row.status != "failed":
            continue
        base = key.split(":seg:")[0].split(":ch:")[0]
        if base not in keys:
            keys.append(base)
    return ",".join(keys[:4]) or "unknown"


def _record_usage_item(
    session: Session,
    run: AgentRun,
    result: ModelResult,
    *,
    now,
    tag: str,
    attempt: int,
    index: int,
) -> None:
    event = UsageEvent(
        account_id=run.account_id,
        task_id=None,
        metric="model_token",
        quantity=int(result.total_tokens or 0),
        unit="token",
        idempotency_key=f"agent:{run.id}:{tag}:a{attempt}:{index}"[:200],
        occurred_at=now,
        meta={
            "source": "agent_run",
            "run_id": run.id,
            "node": tag.split(":")[0],
            "segment": tag,
            "model": result.model,
            "route": result.route,
            "byok": bool(result.byok),
            "cost_cents": int(result.cost_cents or 0),
        },
    )
    inserted = False
    try:
        with session.begin_nested():
            session.add(event)
            session.flush()
        inserted = True
    except IntegrityError:
        # 幂等重放：savepoint 回滚，不影响本事务其他改动
        pass
    if inserted:
        run.tokens_total += int(result.total_tokens or 0)
        run.cost_cents += int(result.cost_cents or 0)
        increment("moxie_agent_run_tokens_total", int(result.total_tokens or 0))


def _record_usage(
    session: Session,
    run: AgentRun,
    outcome: NodeOutcome,
    *,
    now,
    tag: str | None = None,
) -> None:
    if not outcome.records:
        return
    scope = tag or outcome.node_id
    for index, (attempt, result) in enumerate(outcome.records):
        _record_usage_item(
            session,
            run,
            result,
            now=now,
            tag=scope,
            attempt=attempt,
            index=index,
        )


def _requeue(session: Session, run: AgentRun, *, now) -> None:
    run.status = "queued"
    run.error_code = None
    run.error_message = None
    run.updated_at = now
    append_event(session, run.id, "run", "本次执行到达批量上限，剩余节点将在下次 worker 执行时续跑", level="warning")
    session.flush()


def _finish_failed(
    session: Session,
    run: AgentRun,
    *,
    code: str,
    message: str,
    reservation=None,
    now=None,
) -> None:
    now = now or utcnow()
    run.status = "failed"
    run.error_code = code
    run.error_message = message[:255]
    run.finished_at = now
    run.updated_at = now
    if reservation is None:
        reservation = reservation_of(session, run)
    QuotaService(session).release(reservation, now=now)
    append_event(session, run.id, "run", f"运行失败：{code} {message}", level="error")
    increment("moxie_agent_runs_total", status="failed", mode=run.mode)
    session.flush()


def _finish_canceled(session: Session, run: AgentRun, *, reservation=None, now=None) -> None:
    now = now or utcnow()
    run.status = "canceled"
    run.cancel_requested = True
    run.error_code = "canceled"
    run.error_message = "运行已取消"
    run.finished_at = now
    run.updated_at = now
    if reservation is None:
        reservation = reservation_of(session, run)
    QuotaService(session).release(reservation, now=now)
    append_event(session, run.id, "run", "运行已取消（节点边界检查点）", level="warning")
    increment("moxie_agent_runs_total", status="canceled", mode=run.mode)
    session.flush()
