# -*- coding: utf-8 -*-
"""Agent 运行 API：题材目录、创建/查询/事件流/取消/恢复/产物下载。

契约固定；新增字段只做追加。所有资源按 account_id 隔离，越权一律 404。
"""

from __future__ import annotations

import json
import time
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from ..agents import ARTIFACT_NAMES, cancel_run, create_run, get_run, pause_run, resume_run, run_to_dict
from ..agents.genres import GENRES, list_genres
from ..db import get_db
from ..deps import AuthContext, get_auth
from ..errors import ApiError
from ..models import AgentRun, AgentRunEvent, AgentRunStep
from ..schemas import (
    AgentCollectionsUpdateRequest,
    AgentCoverRequest,
    AgentInfoUpdateRequest,
    AgentRunCreateRequest,
    AgentResumeRequest,
)
from ..services.audit import write_audit
from ..services.cover import generate_cover, save_uploaded_cover
from ..services.storage import book_slug
from ..worker import enqueue_agent_run

router = APIRouter(tags=["agent"])

SSE_POLL_SECONDS = 0.2
SSE_MAX_TICKS = 300  # 最长保持 60s；客户端可按 since 重新连接


def _store_byok(request: Request, run_id: str) -> None:
    """BYOK 只写 Redis（TTL 1h），不落库、不写日志；worker 从 Redis 取用。"""
    key = (request.headers.get("x-byok-key") or "").strip()
    if not key:
        return
    try:
        request.app.state.redis.setex(f"agent:byok:{run_id}", 3600, key)
    except Exception:  # noqa: BLE001
        pass


@router.get("/genres")
def genres():
    return list_genres()


@router.post("/agent-runs", status_code=201)
def create_agent_run(
    payload: AgentRunCreateRequest,
    request: Request,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    settings = request.app.state.settings
    if payload.mode == "reference":
        if not (payload.source_key or "").strip():
            raise ApiError(422, "source_key_required", "reference 模式必须提供 source_key")
        if settings.legal_gate_enabled:
            confirmed = request.headers.get("x-rights-confirmed", "").lower() in ("1", "true", "yes")
            if not confirmed:
                raise ApiError(
                    422,
                    "rights_confirmation_required",
                    "参考改编前必须确认已获得参考作品使用权（X-Rights-Confirmed: true）",
                )
        # 延迟导入，避免与 services.tasks ↔ runners 的既有导入顺序形成环
        from ..runners.decompose import validate_source_params

        validate_source_params(
            settings,
            {"source_key": payload.source_key},
            request.app.state.storage,
            account_id=auth.account.id,
            db=db,
        )

    idempotency_key = request.headers.get("idempotency-key") or f"auto:{payload.mode}:{payload.title[:40]}"
    try:
        run, created = create_run(
            db,
            account_id=auth.account.id,
            mode=payload.mode,
            title=payload.title.strip(),
            audience=payload.audience,
            length=payload.length,
            genre_id=payload.genre.id,
            genre_name=payload.genre.name.strip(),
            source_key=payload.source_key,
            brief=payload.brief,
            idempotency_key=idempotency_key,
            options=(
                payload.options.model_dump(exclude_none=True)
                if payload.options is not None
                else None
            ),
        )
    except ApiError as exc:
        if exc.status_code == 402 and exc.code in ("no_active_subscription", "entitlement_missing"):
            raise ApiError(403, "subscription_required", "需要有效订阅后才能创建写作运行") from exc
        raise

    if created:
        write_audit(
            db,
            actor_id=auth.account.id,
            action="agent_run.create",
            request=request,
            target_type="agent_run",
            target_id=run.id,
            meta={"mode": run.mode, "title": run.title, "metric": run.reserved_metric},
        )
    db.commit()
    db.refresh(run)
    _store_byok(request, run.id)
    queued = enqueue_agent_run(settings, run.id) if created else False
    return {
        "run_id": run.id,
        "status": run.status,
        "mode": run.mode,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "created": created,
        "enqueued": queued,
    }


def _genre_condition(value: str):
    """题材既可传 id 也可传中文名；同时命中目录别名时一并匹配。"""
    value = value.strip()
    conditions = [AgentRun.genre_id == value, AgentRun.genre_name == value]
    for item in GENRES:
        if value in (item["id"], item["name"]):
            conditions.extend(
                [AgentRun.genre_id == item["id"], AgentRun.genre_name == item["name"]]
            )
            break
    return or_(*conditions)


@router.get("/agent-runs")
def list_agent_runs(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    mode: Literal["hot", "reference", "custom"] | None = Query(default=None),
    audience: Literal["male", "female"] | None = Query(default=None),
    length: Literal["long", "short"] | None = Query(default=None),
    genre: str | None = Query(default=None, max_length=64),
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    conditions = [AgentRun.account_id == auth.account.id]
    if mode is not None:
        conditions.append(AgentRun.mode == mode)
    if audience is not None:
        conditions.append(AgentRun.audience == audience)
    if length is not None:
        conditions.append(AgentRun.length == length)
    if genre is not None and genre.strip():
        conditions.append(_genre_condition(genre))

    total = (
        db.scalar(select(func.count()).select_from(AgentRun).where(*conditions))
        or 0
    )
    rows = db.scalars(
        select(AgentRun)
        .where(*conditions)
        .order_by(AgentRun.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    items = [
        run_to_dict(db, row, storage=request.app.state.storage, include_artifacts=False)
        for row in rows
    ]
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "next_offset": offset + len(items) if offset + len(items) < total else None,
    }


@router.get("/agent-runs/{run_id}")
def agent_run_detail(
    run_id: str,
    request: Request,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    run = get_run(db, auth.account.id, run_id)
    return run_to_dict(db, run, storage=request.app.state.storage)


@router.patch("/agent-runs/{run_id}")
def update_agent_run_info(
    run_id: str,
    payload: AgentInfoUpdateRequest,
    request: Request,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    """编辑作品信息：必填字段由前端校验，可选字段写入 meta.info 覆盖展示。"""
    run = get_run(db, auth.account.id, run_id)
    if run.status in ("queued", "running"):
        raise ApiError(409, "run_active", "运行中的作品暂不可编辑，请先停止")
    if payload.title is not None and not payload.title.strip():
        raise ApiError(422, "title_required", "书名不能为空")
    if payload.genre is not None and not payload.genre.name.strip():
        raise ApiError(422, "genre_required", "题材不能为空")

    meta = dict(run.meta or {})
    info = dict(meta.get("info") or {})
    changed: list[str] = []

    if payload.title is not None and payload.title.strip() != run.title:
        # 产物按书名分目录；改名后沿用原目录，避免历史产物失联
        meta.setdefault("book_slug", book_slug(run.title))
        run.title = payload.title.strip()
        changed.append("title")
    if payload.audience is not None:
        run.audience = payload.audience
        changed.append("audience")
    if payload.length is not None:
        run.length = payload.length
        changed.append("length")
    if payload.genre is not None:
        run.genre_id = payload.genre.id
        run.genre_name = payload.genre.name.strip()
        changed.append("genre")

    for field in (
        "author",
        "logline",
        "synopsis",
        "person",
        "style",
        "world",
        "conflict",
        "mainline",
        "core_hook",
        "suspense",
        "subplots",
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
        "ending_type",
        "ending_state",
        "protagonist_final_fate",
        "taboos",
        "tone",
        "target_reader_age",
        "update_frequency",
        "serialization_pace",
        "content_rating",
    ):
        value = getattr(payload, field)
        if value is not None:
            info[field] = value.strip()
            changed.append(field)
    for field in (
        "themes",
        "selling_points",
        "beats",
        "innovation_points",
        "comparative_titles",
        "target_platform",
    ):
        value = getattr(payload, field)
        if value is not None:
            limit = 500 if field == "beats" else 12
            info[field] = [item.strip() for item in value if item.strip()][:limit]
            changed.append(field)
    if payload.status_label is not None:
        info["status"] = payload.status_label
        changed.append("status")

    meta["info"] = info
    run.meta = meta
    write_audit(
        db,
        actor_id=auth.account.id,
        action="agent_run.info_update",
        request=request,
        target_type="agent_run",
        target_id=run.id,
        meta={"fields": sorted(set(changed))},
    )
    db.commit()
    db.refresh(run)
    return run_to_dict(db, run, storage=request.app.state.storage)


@router.patch("/agent-runs/{run_id}/collections")
def update_agent_run_collections(
    run_id: str,
    payload: AgentCollectionsUpdateRequest,
    request: Request,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    """人物角色 / 势力阵营 / 道具功法 / 卷章概览的增删改。

    客户端提交整组最新数据，服务端整体覆盖到 meta.collections；
    未提交的集合保持原值，运行中的作品不允许修改。
    """
    run = get_run(db, auth.account.id, run_id)
    if run.status in ("queued", "running"):
        raise ApiError(409, "run_active", "运行中的作品暂不可编辑，请先停止")

    data = payload.model_dump(exclude_none=True)
    if not data:
        raise ApiError(422, "empty_update", "没有需要更新的内容")

    for key, label in (("characters", "角色"), ("factions", "势力"), ("items", "道具")):
        for item in data.get(key) or []:
            if not str(item.get("name") or "").strip():
                raise ApiError(422, "name_required", f"{label}名称不能为空")

    for volume in data.get("volumes") or []:
        try:
            no = int(volume.get("no"))
        except (TypeError, ValueError):
            raise ApiError(422, "volume_no_required", "卷序号必须为正整数")
        if no < 1:
            raise ApiError(422, "volume_no_required", "卷序号必须为正整数")

    for chapter in data.get("chapter_summaries") or []:
        try:
            no = int(chapter.get("no"))
        except (TypeError, ValueError):
            raise ApiError(422, "chapter_no_required", "章号必须为正整数")
        if no < 1:
            raise ApiError(422, "chapter_no_required", "章号必须为正整数")

    if "chapter_hidden" in data:
        hidden: set[int] = set()
        for no in data["chapter_hidden"]:
            try:
                value = int(no)
            except (TypeError, ValueError):
                continue
            if value > 0:
                hidden.add(value)
        data["chapter_hidden"] = sorted(hidden)

    meta = dict(run.meta or {})
    collections = dict(meta.get("collections") or {})
    collections.update(data)
    meta["collections"] = collections
    run.meta = meta
    write_audit(
        db,
        actor_id=auth.account.id,
        action="agent_run.collections_update",
        request=request,
        target_type="agent_run",
        target_id=run.id,
        meta={"fields": sorted(data.keys())},
    )
    db.commit()
    db.refresh(run)
    return run_to_dict(db, run, storage=request.app.state.storage)


@router.post("/agent-runs/{run_id}/cover")
def generate_agent_run_cover(
    run_id: str,
    payload: AgentCoverRequest,
    request: Request,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    """按作品信息生成 AI 封面：模型优先，免费出图兜底，最后本地绘制。"""
    run = get_run(db, auth.account.id, run_id)
    detail = run_to_dict(db, run, include_artifacts=False)
    cover = generate_cover(
        run=run,
        outline=detail.get("outline") or {},
        settings=request.app.state.settings,
        storage=request.app.state.storage,
        prompt=payload.prompt or "",
        style=payload.style,
        layout=payload.layout,
        width=payload.width,
        height=payload.height,
    )
    write_audit(
        db,
        actor_id=auth.account.id,
        action="agent_run.cover",
        request=request,
        target_type="agent_run",
        target_id=run.id,
        meta={"source": cover.get("source"), "fallback": cover.get("fallback")},
    )
    db.commit()
    return {"run_id": run.id, "cover_url": cover["url"], "cover": cover}


@router.post("/agent-runs/{run_id}/cover/upload")
def upload_agent_run_cover(
    run_id: str,
    request: Request,
    file: UploadFile = File(...),
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    """用户上传封面：校验图片后统一转 JPEG，替换当前封面。"""
    settings = request.app.state.settings
    run = get_run(db, auth.account.id, run_id)
    data = file.file.read(settings.cover_upload_max_bytes + 1)
    cover = save_uploaded_cover(
        run=run,
        settings=settings,
        storage=request.app.state.storage,
        data=data,
        original_name=file.filename or "",
    )
    write_audit(
        db,
        actor_id=auth.account.id,
        action="agent_run.cover_upload",
        request=request,
        target_type="agent_run",
        target_id=run.id,
        meta={"size": cover.get("size"), "name": cover.get("original_name")},
    )
    db.commit()
    return {"run_id": run.id, "cover_url": cover["url"], "cover": cover}


@router.get("/agent-runs/{run_id}/cover")
def get_agent_run_cover(
    run_id: str,
    request: Request,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    run = get_run(db, auth.account.id, run_id)
    meta = (run.meta or {}).get("cover") or {}
    key = meta.get("key")
    if not key:
        raise ApiError(404, "cover_not_found", "该作品还没有封面")
    storage = request.app.state.storage
    if not storage.exists(key):
        raise ApiError(404, "cover_not_found", "封面文件不存在，请重新生成")
    data = storage.get_bytes(key)
    ext = meta.get("fmt") or "jpg"
    media_type = {"png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")
    return Response(
        content=data,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=60"},
    )


@router.delete("/agent-runs/{run_id}/cover")
def delete_agent_run_cover(
    run_id: str,
    request: Request,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    run = get_run(db, auth.account.id, run_id)
    meta = (run.meta or {}).get("cover") or {}
    key = meta.get("key")
    if not key:
        return {"run_id": run.id, "deleted": False}
    storage = request.app.state.storage
    if storage.exists(key):
        storage.delete(key)
    run.meta = {name: value for name, value in (run.meta or {}).items() if name != "cover"}
    write_audit(
        db,
        actor_id=auth.account.id,
        action="agent_run.cover_delete",
        request=request,
        target_type="agent_run",
        target_id=run.id,
    )
    db.commit()
    return {"run_id": run.id, "deleted": True}


@router.get("/agent-runs/{run_id}/events")
def agent_run_events(
    run_id: str,
    request: Request,
    since: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    get_run(db, auth.account.id, run_id)
    database = request.app.state.db
    payload_key = getattr(request.state, "payload_key", None)
    crypto = request.app.state.payload_crypto
    sse_encrypted = payload_key is not None
    path_with_query = request.url.path + (f"?{request.url.query}" if request.url.query else "")

    def _frame(payload: dict) -> str:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if sse_encrypted:
            return crypto.encrypt_sse(payload_key, raw, path_with_query)
        return raw.decode("utf-8")

    def _stream():
        last = since
        for _ in range(SSE_MAX_TICKS):
            status = "queued"
            payloads = []
            with database.session() as session:
                run = session.get(AgentRun, run_id)
                if run is None:
                    status = "missing"
                else:
                    status = run.status
                    rows = session.scalars(
                        select(AgentRunEvent)
                        .where(AgentRunEvent.run_id == run_id, AgentRunEvent.seq > last)
                        .order_by(AgentRunEvent.seq.asc())
                        .limit(200)
                    ).all()
                    payloads = [
                        {
                            "seq": row.seq,
                            "stage": row.stage,
                            "level": row.level,
                            "message": row.message,
                            "at": row.created_at.isoformat() if row.created_at else None,
                        }
                        for row in rows
                    ]
            for item in payloads:
                last = item["seq"]
                yield f"data: {_frame(item)}\n\n"
            if status in ("succeeded", "failed", "canceled", "paused", "missing"):
                break
            time.sleep(SSE_POLL_SECONDS)
        yield f"event: end\ndata: {_frame({'status': 'closed', 'since': last})}\n\n"

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    if sse_encrypted:
        headers["X-Payload-Sse"] = "1"
    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers=headers,
    )


@router.post("/agent-runs/{run_id}/cancel")
def cancel_agent_run(
    run_id: str,
    request: Request,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    run = get_run(db, auth.account.id, run_id)
    changed = cancel_run(db, run)
    if changed:
        write_audit(
            db,
            actor_id=auth.account.id,
            action="agent_run.cancel",
            request=request,
            target_type="agent_run",
            target_id=run.id,
        )
    db.commit()
    db.refresh(run)
    return {"run_id": run.id, "status": run.status, "changed": changed}


@router.post("/agent-runs/{run_id}/pause")
def pause_agent_run(
    run_id: str,
    request: Request,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    """停止任务 = 暂停：进入 paused 后可 resume 继续或 cancel 终止。"""
    run = get_run(db, auth.account.id, run_id)
    changed = pause_run(db, run)
    if changed:
        write_audit(
            db,
            actor_id=auth.account.id,
            action="agent_run.pause",
            request=request,
            target_type="agent_run",
            target_id=run.id,
        )
    db.commit()
    db.refresh(run)
    return {"run_id": run.id, "status": run.status, "changed": changed}


@router.post("/agent-runs/{run_id}/resume")
def resume_agent_run(
    run_id: str,
    payload: AgentResumeRequest,
    request: Request,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    run = get_run(db, auth.account.id, run_id)
    resume_run(
        db,
        run,
        approval=payload.approval,
        chapter_no=payload.input.chapter_no if payload.input else None,
        content=payload.input.content if payload.input else None,
        retry_failed=payload.retry_failed,
    )
    write_audit(
        db,
        actor_id=auth.account.id,
        action="agent_run.resume",
        request=request,
        target_type="agent_run",
        target_id=run.id,
        meta={"approval": payload.approval, "retry_failed": payload.retry_failed},
    )
    db.commit()
    db.refresh(run)
    _store_byok(request, run.id)
    enqueue_agent_run(request.app.state.settings, run.id)
    return run_to_dict(db, run, storage=request.app.state.storage)


@router.delete("/agent-runs/{run_id}")
def delete_agent_run(
    run_id: str,
    request: Request,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    """删除作品：清理产物、封面、步骤与事件；运行中的作品需先停止。"""
    run = get_run(db, auth.account.id, run_id)
    if run.status in ("queued", "running"):
        raise ApiError(409, "run_active", "运行中的作品不能删除，请先停止或取消")
    storage = request.app.state.storage
    slug = (run.meta or {}).get("book_slug") or book_slug(run.title)
    for item in storage.list(f"{slug}/{run.id}"):
        key = item.get("key")
        if key:
            storage.delete(key)
    cover_key = ((run.meta or {}).get("cover") or {}).get("key")
    if cover_key and storage.exists(cover_key):
        storage.delete(cover_key)

    title = run.title
    write_audit(
        db,
        actor_id=auth.account.id,
        action="agent_run.delete",
        request=request,
        target_type="agent_run",
        target_id=run.id,
        meta={"title": title, "status": run.status},
    )
    db.execute(delete(AgentRunStep).where(AgentRunStep.run_id == run.id))
    db.execute(delete(AgentRunEvent).where(AgentRunEvent.run_id == run.id))
    db.delete(run)
    db.commit()
    return {"run_id": run_id, "deleted": True, "title": title}


@router.get("/agent-runs/{run_id}/artifacts/{name}")
def agent_run_artifact(
    run_id: str,
    name: str,
    request: Request,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    settings = request.app.state.settings
    run = get_run(db, auth.account.id, run_id)
    if name not in ARTIFACT_NAMES:
        raise ApiError(404, "artifact_not_found", "产物不存在")
    from ..agents.artifacts import prefix_of, read_artifact
    from ..agents.graph import RunView

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
    storage = request.app.state.storage
    try:
        data = read_artifact(storage, view, name)
    except ApiError:
        raise ApiError(404, "artifact_not_found", "产物尚未生成")
    if name.endswith(".json"):
        return data
    key = f"{prefix_of(view)}/{name}"
    size = len(data.encode("utf-8"))
    return {
        "name": name,
        "size": size,
        "url": storage.presign_get(key, expires=settings.artifact_presign_seconds),
        "expires_in": settings.artifact_presign_seconds,
    }


@router.get("/agent-runs/{run_id}/export")
def export_agent_run(
    run_id: str,
    request: Request,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    """整本交付包：正文/章纲/设定/体检/AIGC 声明，一次性打包下载。"""
    from ..services.book_export import build_book_export

    run = get_run(db, auth.account.id, run_id)
    filename, data = build_book_export(db, run, request.app.state.storage)
    ascii_name = f"book-export-{run.id}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{ascii_name}\"; "
                f"filename*=UTF-8''{quote(filename, safe='')}"
            ),
            "Content-Length": str(len(data)),
        },
    )
