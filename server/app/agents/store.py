# -*- coding: utf-8 -*-
"""运行记录的持久化辅助：创建/读取/序列化/取消/恢复。

API 只做鉴权与参数校验，业务状态机集中在这里与 engine。
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import utcnow
from ..errors import ApiError
from ..models import AgentRun, AgentRunEvent, AgentRunStep, UsageAggregate
from ..services import subscription as subsvc
from ..services.quota import QuotaService, period_of
from .graph import Graph, get_graph

ARTIFACT_NAMES = (
    "outline.md",
    "volumes.json",
    "chapters.json",
    "chapters_full.json",
    "manuscript.md",
    "chapter_summaries.json",
    "characters.json",
    "factions.json",
    "items.json",
    "story_bible.json",
    "hot_research.json",
    "hot_preview.md",
    "decomposed.json",
)
TERMINAL_STATUSES = {"succeeded", "failed", "canceled"}
RUN_STATUSES = {"queued", "running", "paused", "succeeded", "failed", "canceled"}


def append_event(
    session: Session, run_id: str, stage: str, message: str, *, level: str = "info"
) -> int:
    current = session.scalar(
        select(func.max(AgentRunEvent.seq)).where(AgentRunEvent.run_id == run_id)
    ) or 0
    seq = current + 1
    session.add(
        AgentRunEvent(
            run_id=run_id,
            seq=seq,
            stage=stage[:64],
            level=level,
            message=message[:2000],
            created_at=utcnow(),
        )
    )
    session.flush()
    return seq


def get_run(session: Session, account_id: int, run_id: str) -> AgentRun:
    run = session.scalar(
        select(AgentRun).where(AgentRun.id == run_id, AgentRun.account_id == account_id)
    )
    if run is None:
        raise ApiError(404, "run_not_found", "运行不存在")
    return run


def create_run(
    session: Session,
    *,
    account_id: int,
    mode: str,
    title: str,
    audience: str,
    length: str,
    genre_id: str | None,
    genre_name: str,
    source_key: str | None,
    brief: str | None,
    idempotency_key: str,
    options: dict | None = None,
    now: datetime | None = None,
) -> tuple[AgentRun, bool]:
    """返回 (run, created)。重复幂等键返回已有 run，不重复预占。

    每本书消耗 1 个 books_month 额度（与 /v1/tasks 的拆解口径一致）。
    """
    now = now or utcnow()
    existing = session.scalar(
        select(AgentRun).where(
            AgentRun.account_id == account_id, AgentRun.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        return existing, False

    reservation = QuotaService(session).reserve(account_id, "books_month", 1, now=now)
    run = AgentRun(
        id=str(__import__("uuid").uuid4()),
        account_id=account_id,
        mode=mode,
        title=title,
        audience=audience,
        length=length,
        genre_id=genre_id,
        genre_name=genre_name,
        source_key=source_key,
        brief=brief,
        meta={"options": options} if options else {},
        status="queued",
        progress=0,
        current_stage=get_graph(mode).nodes[0].id,
        idempotency_key=idempotency_key,
        reserved_metric="books_month",
        reserved_quantity=reservation.quantity,
        reserved_plan_quantity=reservation.plan_quantity,
        reserved_pack_items=[dict(item) for item in reservation.pack_items],
        created_at=now,
        started_at=None,
        finished_at=None,
        updated_at=now,
    )
    session.add(run)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(AgentRun).where(
                AgentRun.account_id == account_id, AgentRun.idempotency_key == idempotency_key
            )
        )
        if existing is None:
            raise
        return existing, False

    append_event(session, run.id, "run", f"运行已创建：mode={mode}，预占 books_month=1")
    # 预建节点，便于详情页稳定展示 stages
    for node in get_graph(mode).nodes:
        session.add(
            AgentRunStep(
                run_id=run.id,
                node_key=node.id,
                status="pending",
                attempts=0,
                meta={},
                updated_at=now,
            )
        )
    session.flush()
    return run, True


def run_steps(session: Session, run_id: str) -> dict[str, AgentRunStep]:
    rows = session.scalars(select(AgentRunStep).where(AgentRunStep.run_id == run_id)).all()
    return {row.node_key: row for row in rows}


def _node_rows(steps: dict[str, AgentRunStep], node_id: str) -> list[AgentRunStep]:
    """节点自身 checkpoint + 分章/分段子 checkpoint（key 形如 node:ch:001）。"""
    return [
        row
        for key, row in steps.items()
        if key == node_id or key.startswith(f"{node_id}:")
    ]


def resume_view(run: AgentRun) -> dict:
    return dict(run.meta or {})


def cancel_run(
    session: Session, run: AgentRun, *, now: datetime | None = None
) -> bool:
    """queued/paused 立即取消并释放预占；running 只置协作式标志。"""
    now = now or utcnow()
    if run.status in TERMINAL_STATUSES:
        return False
    if run.status in ("queued", "paused"):
        run.status = "canceled"
        run.cancel_requested = True
        run.finished_at = now
        run.error_code = "canceled"
        run.error_message = "运行已取消"
        QuotaService(session).release(reservation_of(session, run), now=now)
        append_event(session, run.id, "run", "运行已取消，预占额度已释放", level="warning")
        _metrics_canceled(run)
    else:
        run.cancel_requested = True
        append_event(session, run.id, "run", "已请求取消，等待当前节点结束", level="warning")
    run.updated_at = now
    session.flush()
    return True


def pause_run(
    session: Session, run: AgentRun, *, now: datetime | None = None
) -> bool:
    """用户主动停止：queued 立即暂停；running 置协作式标志，层间生效后转 paused。

    与 cancel 不同：不释放额度预占、不置终态，之后可 resume 继续或 cancel 终止。
    """
    now = now or utcnow()
    if run.status in TERMINAL_STATUSES or run.status == "paused":
        return False
    meta = dict(run.meta or {})
    meta["pause_reason"] = "user"
    if run.status == "queued":
        run.status = "paused"
        append_event(session, run.id, "run", "任务已停止，可继续生成或取消任务", level="warning")
    else:
        meta["pause_requested"] = True
        append_event(session, run.id, "run", "已请求停止，等待当前节点结束后暂停", level="warning")
    run.meta = meta
    run.updated_at = now
    session.flush()
    return True


def resume_run(
    session: Session,
    run: AgentRun,
    *,
    approval: bool,
    chapter_no: int | None = None,
    content: str | None = None,
    retry_failed: bool = False,
    now: datetime | None = None,
) -> AgentRun:
    now = now or utcnow()
    if run.status not in ("paused", "failed"):
        raise ApiError(409, "invalid_state", f"只有 paused/failed 状态可以 resume，当前为 {run.status}")

    if run.status == "paused":
        meta = dict(run.meta or {})
        if meta.get("pause_reason") == "user":
            # 用户主动停止的运行：清理暂停标记原样续跑，不经过审查确认
            meta.pop("pause_reason", None)
            meta.pop("pause_requested", None)
            run.meta = meta
        elif approval:
            meta["approved"] = True
            meta.pop("resume_input", None)
        else:
            meta["resume_input"] = {"chapter_no": chapter_no, "content": content}
            # 重新执行 review 节点，其余已完成节点保持 checkpoint
            step = session.get(AgentRunStep, (run.id, "review"))
            if step is not None:
                step.status = "pending"
                step.output = None
                step.error = None
                step.finished_at = None
                step.updated_at = now
        run.meta = meta
    else:
        # 失败单点重跑：重新预占额度，只重置失败节点，已完成节点保留
        if not (retry_failed or approval):
            raise ApiError(409, "invalid_state", "失败运行需显式 retry_failed=true 才能重跑失败节点")
        reservation = QuotaService(session).reserve(run.account_id, run.reserved_metric or "books_month", 1, now=now)
        run.reserved_quantity = reservation.quantity
        run.reserved_plan_quantity = reservation.plan_quantity
        run.reserved_pack_items = [dict(item) for item in reservation.pack_items]
        for step in session.scalars(
            select(AgentRunStep).where(AgentRunStep.run_id == run.id, AgentRunStep.status == "failed")
        ).all():
            step.status = "pending"
            step.output = None
            step.error = None
            step.finished_at = None
            step.updated_at = now
        append_event(session, run.id, "run", "失败运行已重新预占额度，将只重跑失败节点")

    run.status = "queued"
    run.cancel_requested = False
    run.error_code = None
    run.error_message = None
    run.finished_at = None
    run.updated_at = now
    append_event(session, run.id, "run", "运行已恢复，继续执行剩余节点")
    session.flush()
    return run


def reservation_of(session: Session, run: AgentRun):
    from ..services.quota import Reservation

    start, end = period_of(run.created_at)
    metric = run.reserved_metric or "books_month"
    unit = "count"
    sub = subsvc.get_active_subscription(session, run.account_id)
    if sub is not None:
        ent = subsvc.get_entitlements(session, sub.plan_id).get(metric)
        if ent is not None:
            unit = ent.unit
    return Reservation(
        account_id=run.account_id,
        metric=metric,
        quantity=run.reserved_quantity,
        period_start=start,
        period_end=end,
        unit=unit,
        plan_quantity=int(run.reserved_plan_quantity or 0),
        pack_items=tuple(dict(item) for item in (run.reserved_pack_items or [])),
    )


def quota_block(session: Session, run: AgentRun) -> dict:
    metric = run.reserved_metric or "books_month"
    start, _ = period_of(run.created_at)
    limit = 0
    sub = subsvc.get_active_subscription(session, run.account_id)
    if sub is not None:
        ent = subsvc.get_entitlements(session, sub.plan_id).get(metric)
        limit = ent.limit_value if ent else 0
    agg = session.scalar(
        select(UsageAggregate).where(
            UsageAggregate.account_id == run.account_id,
            UsageAggregate.metric == metric,
            UsageAggregate.period_start == start,
        )
    )
    return {
        "metric": metric,
        "limit": limit,
        "used": agg.used if agg else 0,
        "reserved": agg.reserved if agg else 0,
    }


def _volumes_cover(volumes: list, total: int) -> bool:
    if not volumes or total <= 0:
        return False
    expect = 1
    for volume in volumes:
        if not isinstance(volume, dict):
            return False
        try:
            start = int(volume.get("chapter_from") or 0)
            end = int(volume.get("chapter_to") or 0)
        except (TypeError, ValueError):
            return False
        if start != expect or end < start:
            return False
        expect = end + 1
    return expect - 1 == total


def run_to_dict(
    session: Session,
    run: AgentRun,
    *,
    graph: Graph | None = None,
    storage=None,
    include_artifacts: bool = True,
) -> dict:
    graph = graph or get_graph(run.mode)
    steps = run_steps(session, run.id)
    node_rows = {node.id: _node_rows(steps, node.id) for node in graph.nodes}
    stages = []
    current = None
    for node in graph.nodes:
        rows = node_rows[node.id]
        state = "pending"
        if rows:
            if any(row.status == "failed" for row in rows):
                state = "failed"
            elif all(row.status == "done" for row in rows):
                state = "succeeded"
            elif any(row.status in ("running", "done") for row in rows):
                # 分章节点执行到一半（或取消时）仍显示进行中，避免误报「待开始」
                state = "running"
        started = min(
            (row.started_at for row in rows if row.started_at is not None),
            default=None,
        )
        finished = (
            max((row.finished_at for row in rows if row.finished_at is not None), default=None)
            if state == "succeeded"
            else None
        )
        if current is None and state != "succeeded":
            current = node.id
        stages.append(
            {
                "id": node.id,
                "name": node.label,
                "state": state,
                "started_at": started.isoformat() if started else None,
                "finished_at": finished.isoformat() if finished else None,
            }
        )

    outputs = {
        key: (step.output or {})
        for key, step in steps.items()
        if ":" not in key and step.status == "done" and isinstance(step.output, dict)
    }
    # 分章节点（chapter_expand/chapter_summarize）结果同时写在节点级 checkpoint 与
    # ch:NNN 子步骤里；只合并子步骤，避免与节点级输出重复导致章节翻倍。
    for node in graph.nodes:
        if not node.chaptered:
            continue
        rows = sorted(
            (row for row in node_rows[node.id] if row.node_key != node.id),
            key=lambda row: row.node_key,
        )
        merged: list[dict] = []
        for row in rows:
            if isinstance(row.output, dict):
                merged.extend(
                    item for item in (row.output.get("chapters") or []) if isinstance(item, dict)
                )
        if merged:
            outputs[node.id] = {"chapters": merged}
    chapters = (
        (outputs.get("chapter_expand") or {}).get("chapters")
        or (outputs.get("adaptation") or {}).get("chapters")
        or []
    )
    graph_output = outputs.get("character_graph") or {}
    characters = (
        graph_output.get("characters")
        or (outputs.get("outline_decompose") or {}).get("characters")
        or []
    )
    if not characters:
        bible = (outputs.get("outline") or {}).get("story_bible") or {}
        characters = [
            {"name": bible[key]}
            for key in ("protagonist", "supporting", "antagonist")
            if isinstance(bible.get(key), str) and bible[key].strip()
        ]
    factions = (
        graph_output.get("factions")
        or (outputs.get("adaptation") or {}).get("factions")
        or (outputs.get("outline_decompose") or {}).get("factions")
        or []
    )
    items = (
        graph_output.get("items")
        or (outputs.get("adaptation") or {}).get("items")
        or (outputs.get("outline_decompose") or {}).get("items")
        or []
    )
    summaries = (outputs.get("chapter_summarize") or {}).get("chapters") or []
    decomposed = outputs.get("outline_decompose") or {}
    seg_rows = [row for key, row in steps.items() if key.startswith("outline_decompose:seg:")]
    segments_count = int(
        (decomposed.get("segmentation") or {}).get("segments") or len(seg_rows)
    )
    preview = outputs.get("hot_preview") or {}
    chapters_count = len(chapters)
    word_count = sum(
        int(chapter.get("word_count") or len(str(chapter.get("content") or "")))
        for chapter in chapters
    )
    chapter_steps = [
        step
        for key, step in steps.items()
        if ":ch:" in key and step.finished_at is not None
    ]
    updated_at = (
        max(step.finished_at for step in chapter_steps).isoformat()
        if chapter_steps
        else (run.updated_at.isoformat() if run.updated_at else None)
    )
    # 作品信息编辑过的字段以 meta.info 覆盖技能原始产出，未填写时不覆盖
    info = (run.meta or {}).get("info") or {}
    outline_data = outputs.get("outline") or {}
    if info:
        overlay_keys = (
            "author",
            "logline",
            "synopsis",
            "themes",
            "person",
            "style",
            "world",
            "conflict",
            "mainline",
            "selling_points",
            "core_hook",
            "suspense",
            "subplots",
            "beats",
            "protagonist",
            "supporting",
            "antagonist",
            "foreshadow_text",
            "power",
            "places",
            "items_text",
            "terms",
            "timeline",
            "map_text",
            "theme_core",
            "theme_statement",
            "innovation_points",
            "ending_type",
            "ending_state",
            "protagonist_final_fate",
            "comparative_titles",
            "taboos",
            "tone",
            "target_platform",
            "target_reader_age",
            "update_frequency",
            "serialization_pace",
            "content_rating",
        )
        # 旧结构里这些字段在技能产出中叫 foreshadow/items/map，编辑值需要同步写两份
        raw_aliases = {
            "foreshadow_text": "foreshadow",
            "items_text": "items",
            "map_text": "map",
        }
        for key in overlay_keys:
            if key not in info:
                continue
            outline_data[key] = info[key]
            if key in raw_aliases:
                outline_data[raw_aliases[key]] = info[key]

    # 统一字段来源：先把 story_bible 缺失值合并到顶层，再删掉语义重复的别名
    bible = dict(outline_data.get("story_bible") or {})
    for key, value in bible.items():
        if key not in outline_data or outline_data.get(key) in (None, "", [], {}):
            outline_data[key] = value
    if not outline_data.get("synopsis") and outline_data.get("book_summary"):
        outline_data["synopsis"] = outline_data["book_summary"]
    if not outline_data.get("themes") and outline_data.get("theme"):
        outline_data["themes"] = [outline_data["theme"]]
    duplicate_keys = {
        "book_title",
        "status",
        "book_summary",
        "length_class",
        "n_chapters",
        "audience",
        "target_reader_gender",
        "genre_tone",
        "theme",
        "genre",
    }
    for key in duplicate_keys:
        outline_data.pop(key, None)
    outline_data["story_bible"] = {
        key: value
        for key, value in bible.items()
        if key not in outline_data and key not in duplicate_keys
    }
    logline = outline_data.get("logline") or ""
    # 分卷必须覆盖最终写作章数；reference 改编后章数可能偏离大纲，按最终章节重算
    volumes = outline_data.get("volumes") or []
    if chapters and not _volumes_cover(volumes, len(chapters)):
        from .skills.outline import volumes_for_chapters

        volumes = volumes_for_chapters(chapters, run.genre_name)
        outline_data["volumes"] = volumes

    # 人物/势力/道具/卷章概览的手工增删改：整组覆盖，未编辑的集合沿用生成结果
    collections = (run.meta or {}).get("collections") or {}
    if isinstance(collections.get("characters"), list):
        characters = collections["characters"]
    if isinstance(collections.get("factions"), list):
        factions = collections["factions"]
    if isinstance(collections.get("items"), list):
        items = collections["items"]
    if isinstance(collections.get("chapter_summaries"), list):
        summaries = collections["chapter_summaries"]
    if isinstance(collections.get("volumes"), list):
        volumes = collections["volumes"]
        outline_data["volumes"] = volumes

    artifacts = []
    if include_artifacts and storage is not None:
        slug = (run.meta or {}).get("book_slug") or _book_of(run.title)
        prefix = f"{slug}/{run.id}"
        for item in storage.list(prefix):
            name = item.get("name")
            if name not in ARTIFACT_NAMES:
                continue
            artifacts.append(
                {
                    "name": name,
                    "kind": "json" if name.endswith(".json") else "markdown",
                    "size": int(item.get("size") or 0),
                }
            )
        artifacts.sort(key=lambda item: item["name"])

    cover_meta = (run.meta or {}).get("cover") or {}
    cover_url = (
        f"/agent-runs/{run.id}/cover?v={quote(str(cover_meta.get('updated_at') or ''), safe='')}"
        if cover_meta.get("key")
        else None
    )
    # 出参脱敏：只暴露展示所需字段，内部存储 key、生成提示词不下发
    public_cover = {
        key: cover_meta.get(key)
        for key in ("source", "model", "notice", "fmt", "width", "height", "size", "updated_at")
        if cover_meta.get(key) not in (None, "")
    }
    return {
        "run_id": run.id,
        "mode": run.mode,
        "title": run.title,
        "audience": run.audience,
        "length": run.length,
        "genre": {"id": run.genre_id, "name": run.genre_name},
        "options": dict((run.meta or {}).get("options") or {}),
        "status": run.status,
        "status_label": info.get("status") or "连载中",
        "progress": run.progress,
        "stages": stages,
        "current_stage": current
        or run.current_stage
        or (graph.nodes[-1].id if run.status == "succeeded" else None),
        "quota": quota_block(session, run),
        "artifacts": artifacts,
        # AI 封面：有封面时返回需要鉴权的相对路径（客户端带 Bearer 拉取）
        "cover_url": cover_url,
        "cover": public_cover or None,
        # 契约追加：工作台直接渲染章节/角色/势力/大纲，避免为渲染再走一次签名下载。
        # 字段保留技能原始结构（chapter/word_count/personality/stance 等），由客户端做类型映射；
        # 尚未产出时返回空数组/空对象，客户端显示占位而不是报错。
        "chapters": chapters,
        "characters": characters,
        "factions": factions,
        "items": items,
        "chapter_summaries": summaries,
        # 卷章概览中被手工删除的章号（仅隐藏概览，不影响正文）
        "chapter_hidden": list(
            collections.get("chapter_hidden")
            if isinstance(collections.get("chapter_hidden"), list)
            else []
        ),
        # 完整大纲：除固定字段外，把 skill 产出的扩展字段（volumes/hooks/opening…）一并透出，
        # 便于客户端回显全量字段；缺失时仍保持空对象/空数组。
        "outline": {
            **outline_data,
            "logline": logline,
            "story_bible": outline_data.get("story_bible") or {},
            "chapters": outline_data.get("chapters") or [],
        },
        "story_bible": outline_data.get("story_bible") or {},
        "volumes": volumes,
        "summary": {
            "logline": logline,
            "chapters_count": chapters_count,
            "characters_count": len(characters),
            "items_count": len(items),
            "word_count": word_count,
            "segments_count": segments_count,
            "preview_chapters_count": len(preview.get("chapters") or []),
            "updated_at": updated_at,
        },
        "error": (
            {"code": run.error_code, "message": run.error_message or ""}
            if run.error_code and run.status in ("failed", "canceled")
            else None
        ),
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "tokens_total": run.tokens_total,
        "cost_cents": run.cost_cents,
    }


def _book_of(title: str) -> str:
    from ..services.storage import book_slug

    return book_slug(title)


def _metrics_canceled(run: AgentRun) -> None:
    from ..metrics import increment

    increment("moxie_agent_runs_total", status="canceled")
