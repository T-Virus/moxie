# -*- coding: utf-8 -*-
"""
跨章记忆检索（长篇上下文）
=================================
问题：长篇连载只靠「上一章前情记忆」链式传递，第 50 章拿不到第 10 章的细节，
链上任何一环断掉就全线漂移（人物状态、道具、伏笔、配角去向）。

方案（纯本地、零模型成本、离线可用）：
  1) 章节索引：每章提取 摘要 / 出场角色 / 场景 / 要点 / 首尾片段 / 命中的专名，
     连同全文字符二元组（bigram）词频，落盘 data/<书>/memory_index.json；
     按文件 mtime 增量重建，只重算变了的章。
  2) 混合检索 = BM25（字符 bigram，中文免分词）+ 专名命中加权
     （角色卡 / 势力卡 / 术语表里出现的名字在正文中命中，是「相关」的强信号）。
  3) 生成前组装【前文记忆】块注入扩写 prompt：
     近 3 章摘要（顺序脉络）+ 检索出的 top_k 章「摘要 + 相关专名 + 结尾片段」。

不做向量检索：本地 exe 场景没有嵌入模型可用，BM25 + 专名加权对中文网文
「人名 / 地名 / 功法道具」的精确召回反而比通用向量更稳。
"""

import json
import math
import os
import re
import time
from collections import Counter

from paths import book_dir, book_chapters, book_decomposed

INDEX_NAME = "memory_index.json"
HEAD_CHARS = 220          # 章首片段（出场状态 / 时间地点）
TAIL_CHARS = 260          # 章尾片段（悬念落点）
RECENT_SUMMARIES = 3      # 无论检索结果如何都带的「近 N 章摘要」


def _read_json(p, default):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _chapter_no(ch, fallback=1):
    for k in ("no", "chapter_id", "chapter", "chapter_no"):
        v = ch.get(k)
        if v is None:
            continue
        m = re.search(r"\d+", str(v))
        if m:
            n = int(m.group(0))
            if n > 0:
                return n
    return fallback


def _as_list(v):
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str) and v.strip():
        return [x.strip() for x in re.split(r"[、,，]", v) if x.strip()]
    return []


def _bigrams(text):
    """字符二元组（去空白与标点）：中文检索的免分词近似。"""
    t = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", text or "")
    return [t[i:i + 2] for i in range(len(t) - 1)]


def _proper_nouns(chapters_meta, book):
    """专名表：角色卡名 + 势力卡名 + 设定里的术语（,、顿号分隔）。"""
    names = set()
    dec = _read_json(book_decomposed(book), {})
    for coll in (dec.get("characters") or [], dec.get("factions") or []):
        if isinstance(coll, dict):
            n = str(coll.get("name") or "").strip()
            if len(n) >= 2:
                names.add(n)
    ch_data = _read_json(book_chapters(book), {})
    raw_sb = ch_data.get("story_bible")
    if isinstance(raw_sb, str) and raw_sb.strip():
        try:
            from story_bible import parse as parse_story_bible
            _f, cards, facs = parse_story_bible(raw_sb)
            for c in list(cards) + list(facs):
                n = str((c or {}).get("name") or "").strip()
                if len(n) >= 2:
                    names.add(n)
            terms = str((_f or {}).get("terms") or "")
            for w in re.split(r"[、,，;；\s]+", terms):
                w = w.strip()
                if 2 <= len(w) <= 12:
                    names.add(w)
        except Exception:  # noqa
            pass
    return sorted(names, key=len, reverse=True)


def _chapter_text(book, no):
    p = os.path.join(book_dir(book), "manuscript", "%03d.txt" % int(no))
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            return f.read(), os.path.getmtime(p)
    except OSError:
        return "", 0.0


def build_index(book, force=False):
    """增量重建章节索引；返回索引 dict（同时落盘）。无章节数据时返回空壳。"""
    ipath = os.path.join(book_dir(book), INDEX_NAME)
    idx = _read_json(ipath, None)
    if not isinstance(idx, dict) or not isinstance(idx.get("chapters"), dict):
        idx = {"built_at": 0.0, "chapters": {}}
        force = True

    ch_data = _read_json(book_chapters(book), {})
    dec = _read_json(book_decomposed(book), {})
    chapters = ch_data.get("chapters") or dec.get("chapters") or []
    ch_mtime = 0.0
    for p in (book_chapters(book), book_decomposed(book)):
        try:
            ch_mtime = max(ch_mtime, os.path.getmtime(p))
        except OSError:
            pass
    meta_dirty = force or ch_mtime > float(idx.get("meta_mtime") or 0)

    nouns = _proper_nouns(chapters, book) if (meta_dirty or not idx.get("nouns")) \
        else (idx.get("nouns") or [])

    live = {}
    for i, c in enumerate(chapters):
        no = _chapter_no(c, i + 1)
        text, mt = _chapter_text(book, no)
        entry = idx["chapters"].get(str(no))
        dirty = (meta_dirty or entry is None
                 or float(entry.get("mtime") or 0) != float(mt)
                 or str(entry.get("summary") or "") != str(c.get("summary") or ""))
        if not dirty:
            live[str(no)] = entry
            continue
        plain = re.sub(r"\s+", "", text)
        hits = [n for n in nouns if n in plain]
        live[str(no)] = {
            "no": no,
            "title": str(c.get("title") or "").strip(),
            "summary": str(c.get("summary") or "").strip(),
            "scene": str(c.get("scene") or "").strip(),
            "roles": _as_list(c.get("roles")),
            "points": [str(p).strip() for p in _as_list(c.get("points") or c.get("key_events"))][:8],
            "chars": len(text),
            "mtime": mt,
            "head": text[:HEAD_CHARS],
            "tail": text[-TAIL_CHARS:] if len(text) > HEAD_CHARS else "",
            "nouns": hits[:40],
            # 词频只留 top 200：索引体积与正文大小解耦（百万字书也就几百 KB）
            "tf": Counter(_bigrams(text)).most_common(200) if text else [],
            "tf_total": max(1, len(_bigrams(text))),
        }
    idx.update({"built_at": time.time(), "meta_mtime": ch_mtime,
                "nouns": nouns, "chapters": live})
    try:
        os.makedirs(book_dir(book), exist_ok=True)
        tmp = ipath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(idx, f, ensure_ascii=False)
        os.replace(tmp, ipath)
    except OSError:
        pass
    return idx


def _bm25_scores(idx, query_tf, docs):
    """轻量 BM25：docs = [(no, entry)]，query_tf = Counter(bigrams)。返回 {no: score}。"""
    if not docs or not query_tf:
        return {}
    # 文档频率（基于各章 tf 表，近似：top200 内的词才算「出现过」）
    df = Counter()
    for _no, e in docs:
        for w, _c in (e.get("tf") or []):
            df[w] += 1
    n_docs = len(docs)
    avgdl = sum(float(e.get("tf_total") or 1) for _n, e in docs) / n_docs
    k1, b = 1.5, 0.75
    scores = {}
    for no, e in docs:
        tf = dict(e.get("tf") or [])
        dl = float(e.get("tf_total") or 1)
        s = 0.0
        for w, qn in query_tf.items():
            if w not in tf:
                continue
            idf = math.log(1 + (n_docs - df[w] + 0.5) / (df[w] + 0.5))
            f = tf[w]
            s += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / max(1, avgdl))) * min(qn, 3)
        scores[no] = s
    return scores


def search(book, query, exclude_no=0, top_k=3):
    """检索与 query 最相关的章节。返回 [{no, title, score, matched_nouns, summary, why}]。"""
    idx = build_index(book)
    docs = [(no, e) for no, e in sorted(idx["chapters"].items(), key=lambda kv: kv[1].get("no", 0))
            if int(e.get("no") or 0) != int(exclude_no or 0)]
    if not docs:
        return []
    qtf = Counter(_bigrams(query or ""))
    scores = _bm25_scores(idx, qtf, docs)
    # 专名命中加权：query 里出现的专名，在章节正文里也命中 → 强相关
    q_nouns = [n for n in (idx.get("nouns") or []) if n and n in (query or "")]
    out = []
    for no, e in docs:
        hits = [n for n in q_nouns if n in (e.get("nouns") or [])]
        s = scores.get(no, 0.0) + 3.0 * len(hits)
        if not e.get("chars"):      # 没有正文的章只有大纲价值，降权
            s *= 0.35
        if s <= 0:
            continue
        out.append({"no": e.get("no"), "title": e.get("title") or "",
                    "score": round(s, 2), "matched_nouns": hits[:8],
                    "summary": e.get("summary") or "",
                    "head": e.get("head") or "", "tail": e.get("tail") or "",
                    "chars": e.get("chars") or 0})
    out.sort(key=lambda x: -x["score"])
    return out[:max(1, int(top_k))]


def build_context(book, ch, top_k=3, max_chars=1600):
    """给扩写 prompt 用的【前文记忆】块：近 N 章摘要 + 检索出的相关章节。
    无足够素材时返回空串（调用方不注入，prompt 与旧行为完全一致）。"""
    idx = build_index(book)
    chapters = idx.get("chapters") or {}
    if len(chapters) < 2:
        return ""
    no = _chapter_no(ch, 0)
    ordered = [e for _k, e in sorted(chapters.items(), key=lambda kv: kv[1].get("no", 0))]
    prev = [e for e in ordered if int(e.get("no") or 0) < no]

    blocks, used = [], 0

    def _push(text):
        nonlocal used
        if not text:
            return
        text = text.strip()
        if not text or used + len(text) > max_chars:
            return
        blocks.append(text)
        used += len(text)

    # 1) 近 N 章摘要：顺序脉络保底（等价于滑窗的近端）
    recent = [e for e in prev if (e.get("summary") or e.get("chars"))][-RECENT_SUMMARIES:]
    if recent:
        lines = ["最近章节脉络（紧接着本章之前发生的事）："]
        for e in recent:
            sm = (e.get("summary") or "").strip() or (e.get("tail") or "")[-120:].strip()
            if sm:
                lines.append(f"· 第{e['no']}章《{e.get('title') or '未命名'}》：{sm[:160]}")
        _push("\n".join(lines))

    # 2) 检索：本章摘要 + 要点 + 角色 + 场景 作为 query
    q = " ".join([str(ch.get("title") or ""), str(ch.get("summary") or ""),
                  " ".join(_as_list(ch.get("roles"))), str(ch.get("scene") or ""),
                  " ".join(_as_list(ch.get("points") or ch.get("key_events")))])
    recent_nos = {int(e.get("no") or 0) for e in recent}
    hits = [h for h in search(book, q, exclude_no=no, top_k=top_k + 2)
            if h["no"] not in recent_nos][:top_k]
    if hits:
        lines = ["相关前文（更早章节里与本章相关的内容，涉及的人名/道具/伏笔必须接得住）："]
        for h in hits:
            bits = [f"· 第{h['no']}章《{h['title'] or '未命名'}》"]
            if h.get("matched_nouns"):
                bits.append("（关联：" + "、".join(h["matched_nouns"][:5]) + "）")
            sm = (h.get("summary") or "").strip()
            if sm:
                bits.append("：" + sm[:150])
            tail = (h.get("tail") or "").strip()
            if tail:
                bits.append(f"\n  该章结尾：…{tail[-100:]}")
            lines.append("".join(bits))
        _push("\n".join(lines))

    if not blocks:
        return ""
    return "【前文记忆】（仅供保持一致性：人名、状态、伏笔、道具去向必须与此吻合；不要复述其中句子）\n" \
           + "\n\n".join(blocks)


def status(book):
    """索引状态（供界面显示）：章数、有正文章数、专名数、重建时间。"""
    ipath = os.path.join(book_dir(book), INDEX_NAME)
    idx = _read_json(ipath, None)
    if not isinstance(idx, dict):
        return {"chapters": 0, "with_text": 0, "nouns": 0, "built_at": 0}
    chs = idx.get("chapters") or {}
    return {"chapters": len(chs),
            "with_text": sum(1 for e in chs.values() if e.get("chars")),
            "nouns": len(idx.get("nouns") or []),
            "built_at": idx.get("built_at") or 0}
