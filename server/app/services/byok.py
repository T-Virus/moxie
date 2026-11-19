# -*- coding: utf-8 -*-
"""BYOK 承载体：用户自带的 Key + 自选模型 / 网关地址。

设计要点：
  · ByokConfig 是 str 子类，值就是 api_key，因此现有所有 `api_key=xxx`
    调用链（engine / runners）无需改动即可继续把 Key 传到模型网关；
  · 额外携带 model / base_url，由 resolve_step_model 统一识别并覆盖；
  · Redis 存 JSON（含 key/model/base_url，TTL 1h，不落库不写日志），
    from_stored 兼容历史的裸 key 字符串。
"""

from __future__ import annotations

import json


class ByokConfig(str):
    """字符串子类：本体是 api_key，附带用户自选的 model / base_url。"""

    model: str
    base_url: str

    def __new__(cls, key: str = "", model: str = "", base_url: str = ""):
        obj = str.__new__(cls, (key or "").strip())
        obj.model = (model or "").strip()
        obj.base_url = (base_url or "").strip()
        return obj

    def to_json(self) -> str:
        return json.dumps(
            {"key": str(self), "model": self.model, "base_url": self.base_url},
            ensure_ascii=False,
        )

    @classmethod
    def from_stored(cls, raw: str | bytes | None) -> "ByokConfig | None":
        """从 Redis 值还原；兼容旧版只存裸 key 的记录。"""
        if not raw:
            return None
        text = raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else str(raw)
        text = (text or "").strip()
        if not text:
            return None
        if text.startswith("{"):
            try:
                data = json.loads(text)
            except (ValueError, TypeError):
                data = None
            if isinstance(data, dict) and data.get("key"):
                return cls(
                    str(data.get("key") or ""),
                    str(data.get("model") or ""),
                    str(data.get("base_url") or ""),
                )
        return cls(text)


def byok_from_headers(headers) -> ByokConfig | None:
    """从请求头组装 BYOK；无 key 直接返回 None（BYOK 必须带 key）。"""
    key = (headers.get("x-byok-key") or "").strip()
    if not key:
        return None
    return ByokConfig(
        key,
        (headers.get("x-byok-model") or "").strip(),
        (headers.get("x-byok-base-url") or "").strip(),
    )
