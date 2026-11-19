# -*- coding: utf-8 -*-
"""BYOK 自选模型：承载体解析、模型覆盖、SSRF 校验、网关 header 覆盖。"""

from __future__ import annotations

import json

import httpx

from app.services.byok import ByokConfig, byok_from_headers
from app.services.model_config import resolve_step_model


def test_byok_config_str_subclass_and_compat():
    cfg = ByokConfig("sk-x", "gpt-4o", "https://api.openai.com/v1")
    # 本体就是 key（str 子类），现有 api_key=... 调用链无需改动
    assert str(cfg) == "sk-x"
    assert cfg == "sk-x"
    assert cfg.model == "gpt-4o"
    assert cfg.base_url == "https://api.openai.com/v1"

    # JSON 往返
    restored = ByokConfig.from_stored(cfg.to_json())
    assert restored == cfg
    assert restored.model == cfg.model
    assert restored.base_url == cfg.base_url

    # 兼容旧版裸 key
    legacy = ByokConfig.from_stored("sk-legacy")
    assert legacy == "sk-legacy"
    assert legacy.model == "" and legacy.base_url == ""


def test_byok_from_headers():
    class H(dict):
        def get(self, key, default=None):
            return super().get(key, default)

    cfg = byok_from_headers(
        H({"x-byok-key": "sk-1", "x-byok-model": "m", "x-byok-base-url": "https://x.example/v1"})
    )
    assert cfg is not None
    assert str(cfg) == "sk-1" and cfg.model == "m" and cfg.base_url == "https://x.example/v1"

    # 无 key 不启用 BYOK（即使填了 model）
    assert byok_from_headers(H({"x-byok-model": "m"})) is None


def test_resolve_step_model_byok_override(app):
    settings = app.state.settings
    # 无后台配置：BYOK 覆盖 model/base_url
    resolved = resolve_step_model(
        None, "decompose", settings, api_key=ByokConfig("sk-x", "my-model", "https://my.example/v1")
    )
    assert resolved.model == "my-model"
    assert resolved.base_url == "https://my.example/v1"
    assert resolved.api_key == "sk-x"
    assert resolved.source == "byok"

    # 只带 key：model/base_url 回退默认，source 不变
    plain = resolve_step_model(None, "decompose", settings, api_key=ByokConfig("sk-x"))
    assert plain.model == settings.llm_model
    assert plain.base_url == settings.llm_base_url
    assert plain.source == "env"


def test_gateway_byok_model_base_url_override(client, headers, app):
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization")
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "x", "object": "chat.completion", "created": 0, "model": "custom-model", "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})

    from .test_gateway import _install_transport
    _install_transport(app, handler)

    # DNS 在 CI 不可控：patch SSRF 校验为放行（校验本身在独立测试中覆盖）
    import app.services.model_gateway as mg_mod

    original = mg_mod.validate_upstream_base_url
    mg_mod.validate_upstream_base_url = lambda url, **kwargs: url.rstrip("/")
    try:
        resp = client.post(
            "/v1/chat/completions",
            headers={
                **headers,
                "x-byok-key": "sk-custom",
                "x-byok-model": "custom-model",
                "x-byok-base-url": "https://custom.example.com/v1",
            },
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
    finally:
        mg_mod.validate_upstream_base_url = original
    assert resp.status_code == 200, resp.text
    assert captured["authorization"] == "Bearer sk-custom"
    assert captured["url"].startswith("https://custom.example.com/v1/")
    assert captured["body"]["model"] == "custom-model"


def test_gateway_byok_rejects_private_base_url(client, headers, app):
    resp = client.post(
        "/v1/chat/completions",
        headers={
            **headers,
            "x-byok-key": "sk-x",
            "x-byok-base-url": "http://127.0.0.1:9999/v1",
        },
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "unsafe_base_url"
