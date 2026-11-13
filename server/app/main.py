# -*- coding: utf-8 -*-
"""FastAPI 应用装配。"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from urllib.parse import quote_plus, unquote_plus

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import func, select

from .api import (
    admin,
    agent_runs,
    artifacts,
    auth,
    billing,
    credits,
    crypto,
    devices,
    downloads,
    gateway,
    license,
    notifications,
    payments,
    presets,
    rankings,
    tasks,
    uploads,
)
from .config import Settings
from .db import Database
from .deps import client_ip
from .errors import install_exception_handlers
from .logging_setup import configure_logging, new_request_id, request_id_ctx, set_trace_id
from .metrics import increment, render as render_metrics
from .models import AgentRun, Task
from .payload_middleware import PayloadCryptoMiddleware
from .redis_client import RateLimiter, build_redis
from .security import LicenseSigner
from .seed import ensure_credit_packs, ensure_plans, ensure_presets
from .services.payload_crypto import PayloadCrypto
from .services.sentry import init_sentry

logger = logging.getLogger("moxie.app")

_DEFAULT_JWT_SECRETS = {"", "dev-only-change-me-in-production", "change-me", "secret", "changeme"}
_DEFAULT_S3_ACCESS_KEYS = {"", "minioadmin"}
_DEFAULT_S3_SECRET_KEYS = {"", "change-me-minio-secret", "minioadmin"}


def validate_production_settings(settings: Settings) -> None:
    """生产启动前校验易被照抄示例的配置；缺失项一次性全部列出。"""
    problems: list[str] = []

    secret = (settings.jwt_secret or "").strip()
    if secret in _DEFAULT_JWT_SECRETS or len(secret) < 32 or "change-me" in secret.lower():
        problems.append("JWT_SECRET 未配置、仍为示例值或长度不足 32 字符")

    origins = [item.strip() for item in settings.cors_allow_origins.split(",") if item.strip()]
    if not origins:
        problems.append("CORS_ALLOW_ORIGINS 不能为空")
    elif "*" in origins:
        problems.append("CORS_ALLOW_ORIGINS 禁止使用通配符 *")

    if not (settings.artifact_signing_secret or "").strip():
        problems.append("ARTIFACT_SIGNING_SECRET 必须显式配置（产物下载签名不可复用 JWT_SECRET）")
    if not (settings.model_key_secret or "").strip():
        problems.append("MODEL_KEY_SECRET 必须显式配置（工序模型 Key 必须加密落库）")

    database_url = (settings.database_url or "").strip()
    default_database_url = Settings.model_fields["database_url"].default
    if database_url == str(default_database_url).strip() or "change-me" in database_url.lower():
        problems.append("DATABASE_URL 必须显式配置为真实连接串，不能沿用默认 SQLite 或示例口令")

    if settings.storage_backend.strip().lower() == "s3":
        if settings.s3_access_key.strip().lower() in _DEFAULT_S3_ACCESS_KEYS:
            problems.append("S3_ACCESS_KEY 不能为空或使用默认 minioadmin")
        if (
            settings.s3_secret_key.strip().lower() in _DEFAULT_S3_SECRET_KEYS
            or "change-me" in settings.s3_secret_key.lower()
        ):
            problems.append("S3_SECRET_KEY 不能为空或使用默认示例值")

    if problems:
        raise RuntimeError("生产环境配置校验失败：\n- " + "\n- ".join(problems))


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.log_level)
    init_sentry(settings)

    # 生产闸门：mock/fake 渠道一律禁止；License / 载荷私钥必须显式配置。
    # 用 is_production 白名单判定，避免 ENV 写成 prod/staging 时闸门被跳过。
    if settings.is_production:
        if settings.payments_mock_enabled or settings.payments_fake_enabled:
            raise RuntimeError("生产环境禁止启用 PAYMENTS_MOCK_ENABLED / PAYMENTS_FAKE_ENABLED")
        if not settings.license_private_key_pem:
            raise RuntimeError("生产环境必须配置 LICENSE_PRIVATE_KEY_PEM（多 worker 禁止临时密钥）")
        if settings.payload_encryption_enabled and not settings.payload_crypto_private_key_pem:
            raise RuntimeError("生产环境必须配置 PAYLOAD_CRYPTO_PRIVATE_KEY_PEM")
        validate_production_settings(settings)

    payload_crypto = PayloadCrypto(
        settings.payload_crypto_private_key_pem or None,
            allow_ephemeral=(
                not settings.is_production
                or not settings.payload_encryption_enabled
            ),
    )

    signer = LicenseSigner(
        settings.license_private_key_pem,
        settings.license_key_id,
        allow_ephemeral=settings.license_allow_ephemeral_key,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = Database(settings)
        if settings.auto_create_tables:
            db.create_all()
        with db.session() as session:
            ensure_plans(session)
            ensure_credit_packs(session, settings.credit_pack_validity_days)
            ensure_presets(session)

        redis_client, backend = build_redis(settings)
        if backend != "redis":
            logger.warning("Redis 使用 fakeredis（队列不可用，限流仅进程内有效）")

        app.state.db = db
        app.state.redis = redis_client
        app.state.redis_backend = backend
        app.state.limiter = RateLimiter(redis_client)
        from .services.storage import build_storage

        app.state.storage = build_storage(settings, db.session_factory)
        app.state.license_signer = signer
        app.state.http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.gateway_timeout_seconds),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
        scheduler_task = None
        scheduler_stop = None
        if settings.scheduler_enabled:
            import threading

            from .scheduler import loop_forever

            scheduler_stop = threading.Event()

            async def _scheduler_loop():
                await asyncio.to_thread(loop_forever, settings, None, scheduler_stop)

            scheduler_task = asyncio.create_task(_scheduler_loop())
            logger.info("内置 scheduler 已启用，间隔 %ss", settings.scheduler_interval_seconds)
        try:
            yield
        finally:
            if scheduler_stop is not None:
                scheduler_stop.set()
            if scheduler_task is not None:
                scheduler_task.cancel()
            await app.state.http_client.aclose()
            try:
                redis_client.close()
            except Exception:  # noqa: BLE001
                pass
            db.dispose()

    expose_docs = (
        settings.docs_enabled
        if settings.docs_enabled is not None
        else not settings.is_production
    )
    app = FastAPI(
        title="墨写服务端 API",
        version="0.1.0",
        description=(
            "第一期骨架：认证 / 设备 / License / 任务 / 模型网关 / 额度 / 订阅支付。"
            "提示词与规则库只在内网 Worker 使用，本 API 不返回任何提示词明文。"
        ),
        lifespan=lifespan,
        docs_url="/docs" if expose_docs else None,
        redoc_url="/redoc" if expose_docs else None,
        openapi_url="/openapi.json" if expose_docs else None,
    )
    app.state.settings = settings
    app.state.license_signer = signer
    app.state.payload_crypto = payload_crypto

    # CORS：仅管理端等显式白名单来源；禁止 "*" + credentials 组合
    origins = [item.strip() for item in settings.cors_allow_origins.split(",") if item.strip()]
    if "*" in origins:
        raise RuntimeError(
            "CORS_ALLOW_ORIGINS 不允许使用 *：请配置明确的来源（默认 http://127.0.0.1:5180）"
        )
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=[
                item.strip().upper()
                for item in settings.cors_allow_methods.split(",")
                if item.strip()
            ],
            allow_headers=[
                item.strip()
                for item in settings.cors_allow_headers.split(",")
                if item.strip()
            ],
            expose_headers=[
                "X-Request-Id",
                "X-Payload-Encrypted",
                "X-Payload-Nonce",
                "X-Payload-Key",
                "X-Payload-Sse",
            ],
            max_age=settings.cors_max_age_seconds,
        )

    install_exception_handlers(app)

    # 全局请求体大小限制：防止超大 body 写入造成资源耗尽 / 非法参数注入。
    # 仅按 Content-Length 头判断（流式分块无该头时交由后续校验），默认 4MB。
    MAX_REQUEST_BODY_BYTES = int(os.environ.get("MOXIE_MAX_BODY_BYTES", 4 * 1024 * 1024))

    @app.middleware("http")
    async def limit_body_size(request: Request, call_next):
        raw = request.headers.get("content-length")
        if raw and raw.isdigit() and int(raw) > MAX_REQUEST_BODY_BYTES:
            return JSONResponse(
                status_code=413,
                content={"error": "payload_too_large", "message": "请求体超过大小限制"},
            )
        # 无 Content-Length（如 Transfer-Encoding: chunked）时 Starlette 不会预读，
        # 攻击者可借此绕过上面的长度判断、持续发送超大 body 耗尽内存。这里包装 receive，
        # 累计读取字节，超过上限立即中断。
        if raw and raw.isdigit():
            return await call_next(request)
        max_bytes = MAX_REQUEST_BODY_BYTES
        received = 0
        original = request._receive

        async def receive_limited():
            nonlocal received
            message = await original()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > max_bytes:
                    raise HTTPException(status_code=413, detail="payload_too_large")
            return message

        request._receive = receive_limited
        return await call_next(request)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = new_request_id(request.headers.get("x-request-id"))
        request.state.request_id = request_id
        token = request_id_ctx.set(request_id)
        set_trace_id(request_id)
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["x-request-id"] = request_id
            return response
        finally:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            logger.info(
                "http_request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": status_code,
                    "dur_ms": elapsed_ms,
                },
            )
            request_id_ctx.reset(token)
            set_trace_id("-")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        # 传输 / UI 边界：统一安全响应头（同源托管前端时同样生效）
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )
        resp.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), camera=(), microphone=(), payment=()",
        )
        # HSTS 仅在真实 HTTPS 下下发，避免本地 HTTP 开发被浏览器缓存导致无法访问
        if request.url.scheme == "https":
            resp.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return resp

    # —— 统一 Query 参数 trim：在 URL 编码层裁剪首尾空白，覆盖所有 handler 的 Query(...)。
    # 签名 / token 类参数不参与裁剪（其值可能是 Base64，以 '+' 或空格编码结尾时裁剪会破坏签名）。
    _NO_TRIM_QUERY_KEYS = {b"sig", b"signature", b"token", b"key", b"code", b"expires"}

    def _trim_query_value(value: bytes) -> bytes:
        """解码后 strip 首尾空白（兼容 %20 与 + 两种空格编码）。

        没有首尾空白时原样返回原始字节，避免无谓地改变编码形式而破坏
        基于原始 query string 的校验逻辑。
        """
        try:
            decoded = unquote_plus(value.decode("ascii"))
        except UnicodeDecodeError:
            return value
        stripped = decoded.strip()
        if stripped == decoded:
            return value
        return quote_plus(stripped, safe="").encode("ascii")

    @app.middleware("http")
    async def trim_query_params(request: Request, call_next):
        raw = request.scope.get("query_string", b"")
        if raw:
            parts = []
            for pair in raw.split(b"&"):
                name, sep, value = pair.partition(b"=")
                if sep and name not in _NO_TRIM_QUERY_KEYS:
                    parts.append(name + b"=" + _trim_query_value(value))
                else:
                    parts.append(pair)
            cleaned = b"&".join(parts)
            if cleaned != raw:
                request.scope["query_string"] = cleaned
                if hasattr(request, "_query_params"):
                    del request._query_params
        return await call_next(request)

    # —— 全局限流兜底：防止单 IP 高频刷接口耗尽资源（DoS）。
    # 认证类接口用更严格阈值；handler 内的业务级限流（登录/注册/上传/网关）仍然保留。
    # 生产环境应由反向代理覆盖 X-Forwarded-For，客户端自带的该头不可信。
    _RL_EXEMPT_PATHS = {
        "/healthz", "/readyz", "/metrics", "/", "/docs", "/openapi.json", "/redoc", "/favicon.ico",
    }

    @app.middleware("http")
    async def global_rate_limit(request: Request, call_next):
        cfg = request.app.state.settings
        if not cfg.rate_limit_enabled:
            return await call_next(request)
        path = request.url.path
        if path in _RL_EXEMPT_PATHS or path.startswith("/docs") or path.startswith("/static"):
            return await call_next(request)
        strict = path.startswith(f"{cfg.api_prefix}/auth/")
        limit = cfg.auth_rate_limit_per_minute if strict else cfg.global_rate_limit_per_minute
        scope = "auth_global" if strict else "global"
        limiter: RateLimiter = request.app.state.limiter
        allowed, retry_after = limiter.check(f"{scope}:{client_ip(request) or '-'}", limit, 60)
        if not allowed:
            increment("moxie_rate_limited_total", scope=scope)
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "rate_limited",
                        "message": "请求过于频繁，请稍后再试",
                        "request_id": getattr(request.state, "request_id", "") or "-",
                    }
                },
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)

    prefix = settings.api_prefix
    app.include_router(admin.health_router)
    app.include_router(crypto.router, prefix=prefix)
    app.include_router(auth.router, prefix=prefix)
    app.include_router(devices.router, prefix=prefix)
    app.include_router(license.router, prefix=prefix)
    app.include_router(tasks.router, prefix=prefix)
    app.include_router(agent_runs.router, prefix=prefix)
    app.include_router(presets.router, prefix=prefix)
    app.include_router(rankings.router, prefix=prefix)
    app.include_router(uploads.router, prefix=prefix)
    app.include_router(artifacts.router, prefix=prefix)
    app.include_router(artifacts.public_router, prefix=prefix)
    app.include_router(billing.router, prefix=prefix)
    app.include_router(credits.router, prefix=prefix)
    app.include_router(notifications.router, prefix=prefix)
    app.include_router(payments.router, prefix=prefix)
    app.include_router(downloads.router, prefix=prefix)
    app.include_router(admin.admin_router, prefix=prefix)
    app.include_router(gateway.router, prefix=prefix)

    @app.get("/metrics", include_in_schema=False)
    def metrics(request: Request):
        if not settings.metrics_enabled:
            return PlainTextResponse("metrics disabled\n", status_code=404)
        # 队列/业务指标不对外公开：配置了 token 就必须匹配；生产未配置则拒绝。
        token = (settings.metrics_token or "").strip()
        if token:
            provided = request.headers.get("x-metrics-token") or request.query_params.get("token") or ""
            if not secrets.compare_digest(provided, token):
                return PlainTextResponse("forbidden\n", status_code=403)
        elif settings.is_production:
            return PlainTextResponse("metrics token not configured\n", status_code=403)
        db: Database = request.app.state.db
        with db.session() as session:
            queue_depth = session.scalar(
                select(func.count()).select_from(Task).where(Task.status.in_({"queued", "running"}))
            ) or 0
            agent_queue_depth = session.scalar(
                select(func.count()).select_from(AgentRun).where(AgentRun.status.in_({"queued", "running"}))
            ) or 0
        return PlainTextResponse(
            render_metrics(
                {
                    "moxie_queue_depth": float(queue_depth),
                    "moxie_agent_queue_depth": float(agent_queue_depth),
                }
            ),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    @app.get("/", include_in_schema=False)
    def root():
        return {
            "name": settings.app_name,
            "version": "0.1.0",
            "docs": "/docs",
            "openapi": "/openapi.json",
            "health": "/healthz",
        }

    # 应用层加密放在最外层：先解密请求体，再交给路由；响应 JSON 统一加密
    # 测试环境默认关闭，避免所有用例都要实现一遍客户端加密
    if settings.payload_encryption_enabled and settings.env != "test":
        app.add_middleware(
            PayloadCryptoMiddleware,
            settings=settings,
            crypto=payload_crypto,
        )

    return app


app = create_app()
