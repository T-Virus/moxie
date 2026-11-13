# -*- coding: utf-8 -*-
"""应用层加密中间件：解密 JSON 请求、加密 JSON 响应。

豁免：文件上传/下载、封面与产物、第三方支付回调、License、模型网关、
公开密钥接口；SSE 由业务端点逐条加密（中间件只透传）。
"""

from __future__ import annotations

import json
import logging
import re

from starlette.datastructures import Headers

from .services.payload_crypto import (
    PayloadCrypto,
    request_aad,
    response_aad,
)

logger = logging.getLogger("moxie.payload")

_EXEMPT_EXACT = {
    "/v1/crypto/public-key",
    "/v1/uploads",
}
_EXEMPT_PREFIXES = (
    "/v1/downloads",
    "/v1/license",
    "/v1/webhooks",
    "/v1/payments/invoices/callback",
    "/v1/payments/stripe",
    "/v1/gateway",
    "/v1/admin/payments/reconcile/export",
)
_EXEMPT_PATTERNS = (
    re.compile(r"^/v1/agent-runs/[^/]+/cover(?:/upload)?$"),
    re.compile(r"^/v1/agent-runs/[^/]+/artifacts/"),
    re.compile(r"^/v1/agent-runs/[^/]+/export$"),
)
_JSON_TYPES = ("application/json", "application/problem+json")


def encryption_exempt(path: str, method: str) -> bool:
    if method == "OPTIONS":
        return True
    if not path.startswith("/v1"):
        return True
    if path in _EXEMPT_EXACT:
        return True
    if any(path.startswith(prefix) for prefix in _EXEMPT_PREFIXES):
        return True
    if any(pattern.match(path) for pattern in _EXEMPT_PATTERNS):
        return True
    # 离线安装包上传是 multipart 文件流，无法用 JSON 加密体承载，单独豁免；
    # 不豁免列表/删除/download 等 JSON 接口，它们仍按常规加解密。
    if path == "/v1/admin/offline-packages" and method == "POST":
        return True
    return False


def _path_with_query(scope: dict) -> str:
    query = scope.get("query_string", b"").decode("utf-8", "replace")
    path = scope.get("path", "")
    return f"{path}?{query}" if query else path


class PayloadCryptoMiddleware:
    def __init__(self, app, *, settings, crypto: PayloadCrypto) -> None:
        self.app = app
        self.settings = settings
        self.crypto = crypto

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or not self.settings.payload_encryption_enabled:
            return await self.app(scope, receive, send)
        method = scope.get("method", "GET").upper()
        path = scope.get("path", "")
        if encryption_exempt(path, method):
            return await self.app(scope, receive, send)

        headers = Headers(scope=scope)
        key_id = headers.get("x-payload-key")
        client_public = headers.get("x-payload-client")
        required = bool(self.settings.payload_encryption_required)

        if not key_id or not client_public:
            if required:
                return await self._error(
                    send, 400, "payload_encryption_required", "请求必须使用应用层加密"
                )
            return await self.app(scope, receive, send)

        if key_id != self.crypto.key_id:
            return await self._error(
                send, 409, "payload_key_mismatch", "加密密钥已更新，请重新建立会话"
            )

        try:
            key = self.crypto.derive_key(client_public)
        except Exception:  # noqa: BLE001
            return await self._error(send, 400, "payload_key_invalid", "客户端公钥无效")

        body, disconnected = await self._read_body(receive)
        if disconnected:
            return
        if body:
            if headers.get("x-payload-encrypted") != "1":
                if required:
                    return await self._error(
                        send, 400, "payload_encryption_required", "请求体必须加密"
                    )
            else:
                nonce = headers.get("x-payload-nonce") or ""
                if not nonce:
                    return await self._error(
                        send, 400, "payload_nonce_required", "缺少加密随机数"
                    )
                try:
                    body = self.crypto.decrypt(
                        key,
                        nonce,
                        body,
                        request_aad(method, _path_with_query(scope), key_id),
                    )
                except Exception:  # noqa: BLE001
                    return await self._error(
                        send, 400, "payload_decrypt_failed", "请求体解密失败"
                    )

        state = scope.setdefault("state", {})
        state["payload_key"] = key
        state["payload_key_id"] = key_id

        # 下游路由看到的是解密后的 JSON，而不是 octet-stream 密文
        scope["headers"] = [
            (name, value)
            for name, value in scope.get("headers", [])
            if name.lower() not in (b"content-type", b"content-length", b"content-encoding")
        ]
        scope["headers"].extend(
            [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ]
        )

        replayed = False

        async def replay_receive():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            # 后续调用交还给原始 receive：SSE 等长连接依赖它感知真实断连，
            # 不能直接返回 http.disconnect，否则会立即取消流。
            return await receive()

        await self.app(
            scope,
            replay_receive,
            self._wrap_send(send, key, key_id, scope),
        )

    @staticmethod
    async def _read_body(receive) -> tuple[bytes, bool]:
        chunks: list[bytes] = []
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return b"", True
            chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                return b"".join(chunks), False

    def _wrap_send(self, send, key: bytes, key_id: str, scope: dict):
        start_message: dict | None = None
        buffer: list[bytes] = []
        encrypt_response = False

        async def wrapped(message):
            nonlocal start_message, encrypt_response
            if message["type"] == "http.response.start":
                start_message = message
                content_type = (
                    Headers(raw=message.get("headers", [])).get("content-type", "").lower()
                )
                encrypt_response = content_type.split(";")[0].strip() in _JSON_TYPES
                if not encrypt_response:
                    await send(message)
                return

            if message["type"] == "http.response.body":
                if not encrypt_response:
                    await send(message)
                    return
                buffer.append(message.get("body", b""))
                if message.get("more_body", False):
                    return
                body = b"".join(buffer)
                if not body or start_message is None:
                    if start_message is not None:
                        await send(start_message)
                    await send({"type": "http.response.body", "body": b"", "more_body": False})
                    return
                try:
                    nonce, ciphertext = self.crypto.encrypt(
                        key,
                        body,
                        response_aad(
                            scope.get("method", "GET"),
                            _path_with_query(scope),
                            key_id,
                        ),
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("payload response encryption failed")
                    await send(
                        {
                            "type": "http.response.start",
                            "status": 500,
                            "headers": [(b"content-type", b"application/json")],
                        }
                    )
                    await send(
                        {
                            "type": "http.response.body",
                            "body": json.dumps(
                                {"error": {"code": "payload_encrypt_failed", "message": "响应加密失败"}},
                                ensure_ascii=False,
                            ).encode("utf-8"),
                            "more_body": False,
                        }
                    )
                    return
                headers = [
                    (name, value)
                    for name, value in start_message.get("headers", [])
                    if name.lower()
                    not in (b"content-length", b"content-type", b"content-encoding")
                ]
                headers.extend(
                    [
                        (b"content-type", b"application/octet-stream"),
                        (b"content-length", str(len(ciphertext)).encode("ascii")),
                        (b"x-payload-encrypted", b"1"),
                        (b"x-payload-nonce", nonce.encode("ascii")),
                        (b"x-payload-key", key_id.encode("ascii")),
                    ]
                )
                await send(
                    {
                        "type": "http.response.start",
                        "status": start_message.get("status", 200),
                        "headers": headers,
                    }
                )
                await send(
                    {"type": "http.response.body", "body": ciphertext, "more_body": False}
                )
                return

            await send(message)

        return wrapped

    @staticmethod
    async def _error(send, status: int, code: str, message: str) -> None:
        payload = json.dumps(
            {"error": {"code": code, "message": message, "request_id": "-"}},
            ensure_ascii=False,
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(payload)).encode("ascii")),
                    (b"x-request-id", b"-"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": payload, "more_body": False})
