# -*- coding: utf-8 -*-
"""稳定实体 ID 与跨端台账归一化（云端副本）。

与桌面 ``src/entity_ids.py`` 内容镜像：纯标准库、零 I/O、零模型调用。
两端用同一算法把「角色/势力/道具/伏笔」从名称映射为内容寻址的稳定 ID，
使桌面 storymap 台账与云端 foreshadow_ledger 可按 ID 交叉比对，而不再依赖
「名称前 10 字模糊匹配」。一致性由 ``../server/tests/test_unified_memory.py``
交叉加载两端模块验证，改动任一副本都必须同步另一份。

设计要点：
- ID 内容寻址：改名不影响语义时 ID 可重算对齐；别名通过 normalize 折叠。
- 台账归一化：桌面 ``chapter`` 语义是「回收章」，云端 ``planted_chapter``
  是「埋设章」，直接按同名字段合并会把回收章当埋设章——此处显式消歧。
- 向后兼容：所有新字段可选，缺失时回退到名称/前 10 字文本匹配。
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any

KINDS = ("char", "faction", "item", "fs")
_PUNCT = re.compile(
    r"[\s·•・,，。.、/\\|:：;；!！?？\"'“”‘’()（）\[\]【】{}<>《》—\-_~]+"
)
_CHAPTER_NO = re.compile(r"第?\s*(\d+)\s*章")


def text_of(value: Any) -> str:
    return str(value or "").strip()


def _to_int(value: Any) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def normalize_name(name: Any) -> str:
    """归一化实体名：NFKC + 去标点/空白 + 折叠 3 连重复字 + ASCII 小写。"""
    raw = unicodedata.normalize("NFKC", text_of(name))
    raw = _PUNCT.sub("", raw)
    raw = re.sub(r"\s+", "", raw)
    raw = re.sub(r"(.)\1{2,}", r"\1", raw)
    return raw.lower()


def stable_id(kind: str, name: Any) -> str:
    """内容寻址稳定 ID：``<kind>:<sha1(normalized)[:12]>``。"""
    normalized = normalize_name(name)
    if not normalized or kind not in KINDS:
        return ""
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
    return f"{kind}:{digest}"


def entity_id(kind: str, name: Any) -> str:
    """角色/势力/道具实体 ID；kind 仅取 char|faction|item。"""
    return stable_id(kind if kind in ("char", "faction", "item") else "char", name)


def foreshadow_id(seed: Any) -> str:
    """伏笔 ID：以埋设线索文本为锚，回收章变化不影响 ID。"""
    return stable_id("fs", seed)


def chapter_of(value: Any) -> int:
    """从 '第 3 章' / 3 / '3' 中取出章号。"""
    raw = text_of(value)
    if not raw:
        return 0
    matched = _CHAPTER_NO.search(raw)
    if matched:
        return int(matched.group(1))
    return _to_int(raw)


def normalize_ledger_row(row: dict, *, source: str = "cloud") -> dict:
    """把桌面/云端伏笔台账归一到同一结构。

    输出：``id / seed / planted_chapter / payoff_chapter / status / source``。
    - 桌面 ``chapter`` 是回收章 → 映射到 payoff_chapter；
    - 云端 ``planted_chapter/payoff_chapter`` 直接采用；
    - 顺序号 ``F{n}`` 不作为稳定 ID，改用 ``fs:<hash>`` 并存 legacy_id。
    """
    row = row if isinstance(row, dict) else {}
    seed = text_of(row.get("seed")) or text_of(row.get("text")) or text_of(row.get("desc"))
    planted = chapter_of(row.get("planted_chapter"))
    payoff = chapter_of(row.get("payoff_chapter"))
    if not planted and source == "desktop":
        # 桌面台账只有回收章（chapter/payoff），没有埋设章，保留 0 表示未知
        planted = 0
    if not payoff:
        payoff = chapter_of(row.get("payoff"))
    if not payoff and source == "desktop":
        payoff = chapter_of(row.get("chapter"))
    raw_id = text_of(row.get("id"))
    stable = foreshadow_id(seed)
    legacy = raw_id if raw_id and stable and raw_id != stable else ""
    return {
        "id": stable or raw_id,
        "legacy_id": legacy,
        "seed": seed,
        "planted_chapter": planted,
        "payoff_chapter": payoff,
        "status": text_of(row.get("status")),
        "source": source,
    }


def normalize_ledger(rows: Any, *, source: str = "cloud", limit: int = 60) -> list[dict]:
    """批量归一化台账，过滤空行并去重（按稳定 ID）。"""
    if not isinstance(rows, list):
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for item in rows[: max(0, int(limit))]:
        if not isinstance(item, dict):
            continue
        row = normalize_ledger_row(item, source=source)
        if not row["seed"]:
            continue
        key = row["id"] or row["seed"]
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out
