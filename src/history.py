# -*- coding: utf-8 -*-
"""
正文版本历史
============
每一章的成稿在「被覆盖之前」自动留快照，可随时回看 / 对比 / 回滚：

    data/<书>/history/<NNN>/index.json     {versions: [{ts, mtime_text, chars, note, file}]}
    data/<书>/history/<NNN>/<时间戳>.txt   快照正文

触发点（都由 webapp / expand 在写文件前调用 snapshot）：
  · 手动保存正文（api/manuscript/save）
  · 单章生成 / 采纳候选落盘
  · 批量扩写（expand.py CLI）
  · 回滚本身（回滚前也留一份，回滚可撤销）

设计约定：
  · 只在「已有内容且新内容不同」时留快照，空覆盖空、同文重写不制造垃圾版本；
  · 每章最多保留 MAX_KEEP 份，最老的自动淘汰；
  · 快照是「覆盖前」的旧文，所以列表里第一份就是最初的稿子，天然按时间正序。
"""

import difflib
import json
import os
import time

from paths import book_dir

MAX_KEEP = 30


def _dir(book, no):
    return os.path.join(book_dir(book), "history", "%03d" % int(no))


def _index_path(book, no):
    return os.path.join(_dir(book, no), "index.json")


def _load_index(book, no):
    try:
        with open(_index_path(book, no), encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("versions"), list):
            return d
    except (OSError, ValueError):
        pass
    return {"versions": []}


def _save_index(book, no, idx):
    os.makedirs(_dir(book, no), exist_ok=True)
    tmp = _index_path(book, no) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _index_path(book, no))


def snapshot(book, no, old_text, note=""):
    """在「旧正文即将被覆盖」时调用，把旧文存档。无旧文 / 无变化时不留版本。

    返回 True 表示留存了一份快照。"""
    old_text = old_text or ""
    if not old_text.strip():
        return False
    d = _dir(book, no)
    idx = _load_index(book, no)
    if idx["versions"]:
        last_file = os.path.join(d, idx["versions"][-1]["file"])
        try:
            with open(last_file, encoding="utf-8") as f:
                if f.read() == old_text:
                    return False          # 与最近一份快照完全相同：不重复留档
        except OSError:
            pass
    os.makedirs(d, exist_ok=True)
    ts = time.time()
    fname = time.strftime("%Y%m%d-%H%M%S", time.localtime(ts)) + ("-%03d" % int((ts % 1) * 1000)) + ".txt"
    with open(os.path.join(d, fname), "w", encoding="utf-8") as f:
        f.write(old_text)
    idx["versions"].append({
        "ts": ts,
        "mtime_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)),
        "chars": len(old_text),
        "note": str(note or "")[:60],
        "file": fname,
    })
    # 淘汰最老的（连文件带索引）
    while len(idx["versions"]) > MAX_KEEP:
        old = idx["versions"].pop(0)
        try:
            os.remove(os.path.join(d, old["file"]))
        except OSError:
            pass
    _save_index(book, no, idx)
    return True


def list_versions(book, no):
    """某章全部版本（新的在前）+ 当前正文信息。返回 None 表示这章从没留过历史。"""
    d = _dir(book, no)
    idx = _load_index(book, no)
    if not idx["versions"]:
        return {"versions": [], "current": None}
    out = []
    for v in reversed(idx["versions"]):
        preview = ""
        try:
            with open(os.path.join(d, v["file"]), encoding="utf-8") as f:
                preview = f.read(80).replace("\n", " ")
        except OSError:
            pass
        out.append({**v, "preview": preview})
    cur = ""
    mp = os.path.join(book_dir(book), "manuscript", "%03d.txt" % int(no))
    try:
        with open(mp, encoding="utf-8", errors="replace") as f:
            cur = f.read()
    except OSError:
        pass
    return {"versions": out,
            "current": {"chars": len(cur), "preview": cur[:80].replace("\n", " ")}}


def read_version(book, no, fname):
    """读某一版全文。fname 只允许是索引里登记过的文件名（防目录穿越）。"""
    idx = _load_index(book, no)
    hit = next((v for v in idx["versions"] if v["file"] == fname), None)
    if not hit:
        return None
    try:
        with open(os.path.join(_dir(book, no), fname), encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def diff_version(book, no, fname):
    """某历史版本 vs 当前正文的统一 diff（行级，difflib）。"""
    old = read_version(book, no, fname)
    if old is None:
        return None
    mp = os.path.join(book_dir(book), "manuscript", "%03d.txt" % int(no))
    try:
        with open(mp, encoding="utf-8", errors="replace") as f:
            cur = f.read()
    except OSError:
        cur = ""
    diff = difflib.unified_diff(
        old.splitlines(), cur.splitlines(),
        fromfile="历史版本 " + fname[:-4], tofile="当前正文", lineterm="", n=2)
    return "\n".join(diff)


def rollback(book, no, fname, note="回滚前自动留存"):
    """把某历史版本恢复为当前正文；当前正文先快照（回滚可再回滚）。
    返回 (ok, message_or_none)。"""
    old = read_version(book, no, fname)
    if old is None:
        return False, "该版本不存在或已被清理"
    mp = os.path.join(book_dir(book), "manuscript", "%03d.txt" % int(no))
    cur = ""
    try:
        with open(mp, encoding="utf-8", errors="replace") as f:
            cur = f.read()
    except OSError:
        pass
    if cur.strip() and cur != old:
        snapshot(book, no, cur, note=note)
    os.makedirs(os.path.dirname(mp), exist_ok=True)
    with open(mp, "w", encoding="utf-8") as f:
        f.write(old)
    return True, None
