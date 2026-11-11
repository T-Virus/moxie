# -*- coding: utf-8 -*-
"""SSE 流式 usage 采集：优先取上游真实 usage，缺失时按字符估算并标记 estimated。"""

from __future__ import annotations

import json
from typing import Any


def estimate_tokens(text: str) -> int:
    """粗略 token 估算：CJK 约 1 字 1 token，其它约 4 字符 1 token。"""
    raw = text or ""
    cjk = sum(1 for ch in raw if ord(ch) > 127)
    ascii_chars = len(raw) - cjk
    return max(1, int(cjk + ascii_chars / 4))


class StreamUsageCollector:
    def __init__(self, prompt_text: str = ""):
        self._buffer = b""
        self._output: list[str] = []
        self.usage: dict[str, Any] | None = None
        self.prompt_tokens = estimate_tokens(prompt_text)

    def feed(self, chunk: bytes) -> None:
        self._buffer += chunk
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            self._handle_line(line)

    def finish(self) -> None:
        if self._buffer:
            self._handle_line(self._buffer)
            self._buffer = b""

    def _handle_line(self, raw: bytes) -> None:
        line = raw.decode("utf-8", "ignore").strip()
        if not line or line.startswith(":") or not line.startswith("data:"):
            return
        data = line[5:].strip()
        if data == "[DONE]":
            return
        try:
            payload = json.loads(data)
        except ValueError:
            return
        usage = payload.get("usage")
        if isinstance(usage, dict):
            self.usage = usage
        for choice in payload.get("choices") or []:
            delta = choice.get("delta") or choice.get("message") or {}
            content = delta.get("content")
            if isinstance(content, str):
                self._output.append(content)
            elif isinstance(content, list):
                self._output.extend(str(p.get("text") or "") for p in content if isinstance(p, dict))

    def result(self) -> dict[str, Any]:
        output_text = "".join(self._output)
        if self.usage:
            prompt = int(self.usage.get("prompt_tokens") or 0)
            completion = int(self.usage.get("completion_tokens") or 0)
            total = int(self.usage.get("total_tokens") or (prompt + completion))
            return {
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": total,
                "estimated": False,
            }
        completion = estimate_tokens(output_text)
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": completion,
            "total_tokens": self.prompt_tokens + completion,
            "estimated": True,
        }
