# -*- coding: utf-8 -*-
"""统一错误响应：不向客户端泄露堆栈。"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger("moxie.api")


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, headers: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "") or "-"


def error_response(request: Request, status_code: int, code: str, message: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "request_id": _request_id(request)}},
        headers=headers,
    )


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return error_response(request, exc.status_code, exc.code, exc.message, exc.headers)

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, exc: HTTPException):
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed"}.get(
            exc.status_code, "http_error"
        )
        return error_response(request, exc.status_code, code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        # 只返回字段路径与原因，不回显整个请求体
        first = exc.errors()[0] if exc.errors() else {"loc": [], "msg": "invalid request"}
        loc = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        message = f"{loc}: {first.get('msg', 'invalid request')}" if loc else "invalid request"
        return error_response(request, 422, "invalid_request", message)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception):
        logger.exception("unhandled error request_id=%s path=%s", _request_id(request), request.url.path)
        return error_response(request, 500, "internal_error", "服务内部错误，请稍后重试")
