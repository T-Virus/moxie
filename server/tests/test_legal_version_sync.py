# -*- coding: utf-8 -*-
"""法律文本版本单一事实源：client / server / 交付包文档三处版本必须一致。

历史踩坑：client 的 LEGAL_VERSION 与 server 的 legal_terms_version 漂移后，
老客户端注册会被 422 legal_consent_required 拦截，用户完全无法注册。
这里做硬校验，避免再次发生。
"""

from __future__ import annotations

import re
from pathlib import Path

from app.config import Settings

ROOT = Path(__file__).resolve().parents[2]


def _client_version() -> str:
    text = (ROOT / "client" / "src" / "services" / "authApi.ts").read_text(encoding="utf-8")
    match = re.search(r"export const LEGAL_VERSION\s*=\s*'([^']+)'", text)
    assert match, "client/src/services/authApi.ts 未找到 LEGAL_VERSION"
    return match.group(1)


def _doc_version() -> str:
    text = (ROOT / "docs" / "法务与SLA交付包-2026-11.md").read_text(encoding="utf-8")
    match = re.search(r"当前法律文本版本：`([^`]+)`", text)
    assert match, "法务交付包文档未找到『当前法律文本版本』"
    return match.group(1)


def test_legal_version_single_source() -> None:
    server_version = Settings().legal_terms_version
    assert _client_version() == server_version, (
        f"client LEGAL_VERSION={_client_version()} 与 server legal_terms_version={server_version} 不一致"
    )
    assert _doc_version() == server_version, (
        f"交付包文档版本={_doc_version()} 与 server legal_terms_version={server_version} 不一致"
    )
