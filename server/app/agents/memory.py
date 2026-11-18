# -*- coding: utf-8 -*-
"""云端跨章记忆检索：桌面 src/memory.py#build_context 的纯函数等价实现。

桌面端把索引落盘成 data/<书>/memory_index.json；云端没有那份文件，改用同一
run 内已产出的章纲章节（每章带 summary / key_events / roles / hook）作为索引
源。算法保持一致：字符 bigram 的 BM25 + 专名命中加权 + 近 N 章顺序脉络，
保证「写第 N 章时能读到前序章节的人名/状态/伏笔」，而不是只沿上一章链式传递。

纯函数、零 I/O、零模型调用：只吃章节字典列表，产出可注入 prompt 的文本块。
素材不足（少于 2 章）时返回空串，调用方不注入，行为与旧版完全一致。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from .entity_ids import entity_id as _entity_id

RECENT_SUMMARIES = 3
INDEX_VERSION = 2   # 与桌面 src/memory.py#INDEX_VERSION 对齐


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item or "").strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _text(value: Any) -> str:
    return str(value or "").strip()


def _chapter_no(item: dict, fallback: int = 0) -> int:
    # 与桌面 src/memory.py#_chapter_no 键顺序对齐（no → chapter_id → chapter → chapter_no）
    for key in ("no", "chapter_id", "chapter", "chapter_no"):
        value = item.get(key)
        if value in (None, ""):
            continue
        match = re.search(r"\d+", str(value))
        if match:
            return int(match.group())
    return fallback


def _bigrams(text: str) -> list[str]:
    compact = re.sub(r"\s+", "", _text(text))
    if len(compact) < 2:
        return [compact] if compact else []
    return [compact[index : index + 2] for index in range(len(compact) - 1)]


def _entry(chapter: dict, index: int) -> dict:
    """把章节字典折算成检索索引条目（与桌面 build_index 的字段对齐）。"""
    content = _text(chapter.get("content"))
    summary = _text(chapter.get("summary"))
    events = _as_list(chapter.get("key_events")) or _as_list(chapter.get("points"))
    nouns = _as_list(chapter.get("roles")) + _as_list(chapter.get("factions")) + _as_list(chapter.get("items"))
    nouns += _as_list(chapter.get("new_characters")) + _as_list(chapter.get("new_items"))
    tf = Counter(_bigrams(" ".join([summary, *events, content[:400]])))
    roles = _as_list(chapter.get("roles"))
    factions = _as_list(chapter.get("factions"))
    items = _as_list(chapter.get("items"))
    return {
        "version": INDEX_VERSION,
        "no": _chapter_no(chapter, index),
        "chapter_id": _text(chapter.get("chapter_id")) or None,
        "title": _text(chapter.get("title")),
        "summary": summary,
        "roles": roles,
        "factions": factions,
        "items": items,
        "role_ids": [_entity_id("char", name) for name in roles],
        "faction_ids": [_entity_id("faction", name) for name in factions],
        "item_ids": [_entity_id("item", name) for name in items],
        "head": content[:220],
        "tail": content[-260:] if content else "",
        "chars": len(content),
        "nouns": list(dict.fromkeys(nouns)),
        "tf": sorted(tf.items(), key=lambda row: -row[1])[:200],
        "tf_total": sum(tf.values()) or 1,
    }


def _bm25_scores(query_tf: Counter, docs: list[dict]) -> dict[int, float]:
    if not docs or not query_tf:
        return {}
    df: Counter = Counter()
    for entry in docs:
        for word, _ in entry.get("tf") or []:
            df[word] += 1
    total = len(docs)
    avgdl = sum(float(entry.get("tf_total") or 1) for entry in docs) / total
    k1, b = 1.5, 0.75
    scores: dict[int, float] = {}
    for entry in docs:
        tf = dict(entry.get("tf") or [])
        length = float(entry.get("tf_total") or 1)
        score = 0.0
        for word, count in query_tf.items():
            if word not in tf:
                continue
            idf = math.log(1 + (total - df[word] + 0.5) / (df[word] + 0.5))
            freq = tf[word]
            score += idf * (freq * (k1 + 1)) / (
                freq + k1 * (1 - b + b * length / max(1, avgdl))
            ) * min(count, 3)
        scores[int(entry["no"])] = score
    return scores


def from_desktop_index(index: dict) -> list[dict]:
    """把桌面 ``memory_index.json`` 的条目折算成云端检索可直接消费的章节列表。

    桌面索引与云端索引字段已对齐（版本 2）：角色/势力/道具名 + 稳定 ID、摘要、
    首尾片段、专名、词频。这里把 dict-of-chapters 还原为有序列表，供
    ``search`` / ``build_context`` 直接用，避免云端对同一批章节重算索引。
    """
    if not isinstance(index, dict):
        return []
    chapters = index.get("chapters")
    if not isinstance(chapters, dict):
        return []
    out: list[dict] = []
    for key, entry in chapters.items():
        if not isinstance(entry, dict):
            continue
        row = dict(entry)
        # 桌面按 "章号" 作 key，确保 no 字段存在（旧索引可能缺 no）
        if not row.get("no"):
            try:
                row["no"] = int(str(key))
            except (TypeError, ValueError):
                continue
        # tf 落盘为 [[word, count], ...]，转回 dict 供 _entry 的 Counter 兼容读取
        tf = row.get("tf")
        if isinstance(tf, list):
            row["tf"] = {str(pair[0]): int(pair[1]) for pair in tf if isinstance(pair, (list, tuple)) and len(pair) == 2}
        out.append(row)
    out.sort(key=lambda item: int(item.get("no") or 0))
    return out


def search(
    chapters: list[dict],
    query: str,
    *,
    exclude_no: int = 0,
    top_k: int = 3,
) -> list[dict]:
    """检索与 query 最相关的章节：BM25(bigram) + 专名命中加权，无正文章降权。"""
    docs = [
        _entry(chapter, index)
        for index, chapter in enumerate(chapters, 1)
        if isinstance(chapter, dict) and _chapter_no(chapter, index) != int(exclude_no or 0)
    ]
    if not docs:
        return []
    query_tf = Counter(_bigrams(query))
    scores = _bm25_scores(query_tf, docs)
    query_nouns = [noun for entry in docs for noun in entry["nouns"] if noun and noun in query]
    query_nouns = list(dict.fromkeys(query_nouns))
    out: list[dict] = []
    for entry in docs:
        hits = [noun for noun in query_nouns if noun in entry["nouns"]]
        score = scores.get(int(entry["no"]), 0.0) + 3.0 * len(hits)
        if not entry["chars"]:
            score *= 0.35
        if score <= 0:
            continue
        out.append(
            {
                "no": entry["no"],
                "title": entry["title"],
                "score": round(score, 2),
                "matched_nouns": hits[:8],
                "summary": entry["summary"],
                "head": entry["head"],
                "tail": entry["tail"],
                "chars": entry["chars"],
            }
        )
    out.sort(key=lambda item: -item["score"])
    return out[: max(1, int(top_k))]


def build_context(
    chapters: list[dict],
    current: dict,
    *,
    top_k: int = 3,
    max_chars: int = 1600,
) -> str:
    """给正文/prompt 用的【前文记忆】块：近 N 章脉络 + 检索出的相关章节。

    chapters 是全书章纲（或已概括章节）的有序列表；current 是本章对象。
    少于 2 章或没有可用素材时返回空串。
    """
    entries = [
        _entry(chapter, index)
        for index, chapter in enumerate(chapters or [], 1)
        if isinstance(chapter, dict)
    ]
    if len(entries) < 2:
        return ""
    number = _chapter_no(current, 0)
    prior = [entry for entry in entries if int(entry["no"]) < number]

    blocks: list[str] = []
    used = 0

    def push(text: str) -> None:
        nonlocal used
        clean = _text(text)
        if not clean or used + len(clean) > max_chars:
            return
        blocks.append(clean)
        used += len(clean)

    recent = [entry for entry in prior if entry["summary"] or entry["chars"]][-RECENT_SUMMARIES:]
    if recent:
        lines = ["最近章节脉络（紧接着本章之前发生的事）："]
        for entry in recent:
            summary = entry["summary"] or entry["tail"][-120:]
            if summary:
                lines.append(f"· 第{entry['no']}章《{entry['title'] or '未命名'}》：{summary[:160]}")
        push("\n".join(lines))

    query = " ".join(
        [
            _text(current.get("title")),
            _text(current.get("summary")),
            " ".join(_as_list(current.get("roles"))),
            _text(current.get("scene")),
            " ".join(_as_list(current.get("key_events")) or _as_list(current.get("points"))),
        ]
    )
    recent_nos = {int(entry["no"]) for entry in recent}
    # 只在前序章节里检索：云端索引来自全书章纲（含未来章），不能把后文当"前文"注入，
    # 否则写第 1 章会看到第 5 章的伏笔回收，既穿帮又破坏悬念。
    hits = [hit for hit in search(prior, query, exclude_no=number, top_k=top_k + 2) if hit["no"] not in recent_nos][:top_k]
    if hits:
        lines = ["相关前文（更早章节里与本章相关的内容，涉及的人名/道具/伏笔必须接得住）："]
        for hit in hits:
            bits = [f"· 第{hit['no']}章《{hit['title'] or '未命名'}》"]
            if hit["matched_nouns"]:
                bits.append("（关联：" + "、".join(hit["matched_nouns"][:5]) + "）")
            if hit["summary"]:
                bits.append("：" + hit["summary"][:150])
            if hit["tail"]:
                bits.append(f"\n  该章结尾：…{hit['tail'][-100:]}")
            lines.append("".join(bits))
        push("\n".join(lines))

    if not blocks:
        return ""
    return (
        "【前文记忆】（仅供保持一致性：人名、状态、伏笔、道具去向必须与此吻合；不要复述其中句子）\n"
        + "\n\n".join(blocks)
    )
