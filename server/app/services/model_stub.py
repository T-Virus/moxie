# -*- coding: utf-8 -*-
"""确定性假模型：无真实 Key 时也能跑完整拆解链路（测试/本地验收用）。"""

from __future__ import annotations

import json
import re

_CHAP_RE = re.compile(
    r"^[ \t　>#*\-•]*(第[0-9零一二三四五六七八九十百千两]+章[^\n]{0,40}|Chapter\s+\d+[^\n]{0,40})",
    re.M,
)


def _clean_lines(text: str) -> list[str]:
    return [ln.strip(" \t　#>*-•") for ln in text.splitlines() if ln.strip(" \t　#>*-•")]


def _segments(text: str) -> list[str]:
    marks = [m.start() for m in _CHAP_RE.finditer(text)]
    if len(marks) >= 2:
        return [text[marks[i]: marks[i + 1]].strip() for i in range(len(marks) - 1)] + [text[marks[-1]:].strip()]
    if marks:
        return [text[marks[0]:].strip()]
    return [text.strip()]


def _titles(text: str) -> list[str]:
    return [m.group(1).strip() for m in _CHAP_RE.finditer(text)][:8]


def _events(seg: str, max_items: int = 3) -> list[str]:
    lines = [ln for ln in _clean_lines(seg) if len(ln) >= 8 and not _CHAP_RE.match(ln)]
    return [ln[:80] for ln in lines[:max_items]]


def _decompose_json(prompt: str) -> dict:
    """从 prompt 里提取章标题，构造稳定可解析的拆解 JSON。"""
    titles = _titles(prompt)
    if not titles:
        titles = [f"第{i}章" for i in range(1, 4)]
    segs = _segments(prompt)
    chapters = []
    for i, title in enumerate(titles, 1):
        seg = segs[i - 1] if i - 1 < len(segs) else (segs[-1] if segs else "")
        first = " ".join(_clean_lines(seg)[:3])[:200]
        chapters.append(
            {
                "chapter": i,
                "title": title[:40],
                "summary": first or f"{title}：剧情推进。",
                "key_events": _events(seg) or [first[:60] or "推进主线"],
                "roles": ["林默", "苏晚"],
                "factions": ["御兽宗"],
                "items": ["兽核"],
                "scene": "荒野营地",
                "conflict": "主角与追兵对峙",
                "hook": "神秘兽核发光",
                "hook_type": "悬念",
                "emotion": "紧张→压制→反击",
                "tension": 7,
                "payoff": "击退追兵",
                "setup": "兽核来历未明",
                "_chars": len(seg),
            }
        )
    return {
        "book_summary": f"全书围绕主角在异兽世界的成长展开，共 {len(chapters)} 章。",
        "opening": {"event": "主角觉醒", "protagonist": "林默", "goal": "活下来并查明兽核来历"},
        "story_bible": {
            "synopsis": "少年林默在异兽横行的世界觉醒血脉，携带神秘兽核一路成长。",
            "genre": "玄幻",
            "world": "御兽世界",
            "power": "血脉觉醒",
            "person": "第三人称",
            "mainline": "觉醒 → 追兵 → 反击",
            "protagonist": "林默",
            "supporting": "苏晚",
        },
        "characters": [
            {"name": "林默", "role": "主角", "stance": "己方", "personality": "冷静坚韧"},
            {"name": "苏晚", "role": "配角", "stance": "己方", "personality": "果敢"},
        ],
        "factions": [{"name": "御兽宗", "category": "宗门", "stance": "中立"}],
        "items": [{"name": "兽核", "kind": "道具", "desc": "来历不明的黑色兽核"}],
        "chapters": chapters,
    }


def _merge_json(prompt: str) -> dict:
    return {
        "book_summary": "多段拆解合并完成：主角在异兽世界觉醒并逐步反击。",
        "story_bible": {
            "synopsis": "少年携带兽核在御兽世界成长。",
            "genre": "玄幻",
            "mainline": "觉醒 → 追兵 → 反击",
            "protagonist": "林默",
        },
        "characters": [],
        "factions": [],
        "items": [],
        "chapters": [],
    }


def stub_completion(messages: list[dict], model: str, expect_json: bool) -> tuple[dict, dict]:
    """返回 OpenAI 兼容响应与 usage（token 为字符数估算）。"""
    user_text = "\n".join(
        str(m.get("content") or "") for m in messages if m.get("role") in {"user", "system"}
    )
    is_merge = "合并" in user_text[:2000] and "__PARTS__" not in user_text
    if expect_json:
        payload = _merge_json(user_text) if is_merge else _decompose_json(user_text)
        content = json.dumps(payload, ensure_ascii=False)
    else:
        content = f"（测试假模型）收到 {len(user_text)} 字符请求，模型 {model}。"
    prompt_tokens = max(1, len(user_text) // 4)
    completion_tokens = max(1, len(content) // 4)
    data = {
        "id": "stub-chatcmpl",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }
    return data, data["usage"]
