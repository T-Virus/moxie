# -*- coding: utf-8 -*-
"""
敏感词 / 平台合规预检
=====================
投稿平台（番茄 / 晋江等）的机器审核是网文被驳回的头号原因之一。
本模块做一个**本地、零成本、 deterministic** 的预检：

  · 词表：config/sensitive_words.txt（一行一词，`#` 开头注释，可用「词|级别|类别」
    扩展写法；级别 = 高/中/低，默认中；类别如 政治/色情/暴力/违禁品，默认「通用」）。
  · 扫描：对单章或整本书正文做精确匹配，产出命中词、次数、级别、上下文片段。
  · 定位：返回命中在正文里的起止下标（span），前端可像审查问题一样高亮。

词表随程序带一份基础版（量级示意，用户可自行扩充）；词表是用户数据，
放在 config/ 下随 exe 同级，打包后仍可编辑。
"""

import os
import re

from paths import CONFIG_DIR, book_dir

WORDLIST = os.path.join(CONFIG_DIR, "sensitive_words.txt")

# 首次运行播种的基础词表（只是起步量级，作者在设置页可自行增删）
SEED = """# 敏感词表：一行一词；可选扩展格式「词|级别|类别」，级别=高/中/低
# 这是基础起步词表，请按目标平台（番茄/晋江/起点…）的审核规则自行扩充
枪支|中|违禁品
毒品|高|违禁品
走私|中|违法
赌博|中|违法
恐怖袭击|高|暴力
自杀|中|生命
邪教|高|政治
"""


def load_words():
    """读词表 → [{word, level, category}]；文件不存在时播种基础词表。"""
    if not os.path.isfile(WORDLIST):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(WORDLIST, "w", encoding="utf-8") as f:
                f.write(SEED)
        except OSError:
            pass
    words = []
    try:
        with open(WORDLIST, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = [p.strip() for p in line.split("|")]
                w = parts[0]
                if not w:
                    continue
                level = parts[1] if len(parts) > 1 and parts[1] in ("高", "中", "低") else "中"
                cat = parts[2] if len(parts) > 2 and parts[2] else "通用"
                words.append({"word": w, "level": level, "category": cat})
    except OSError:
        pass
    return words


def save_words(words):
    """整体写回词表（接受 [{word, level, category}] 或纯字符串列表）。"""
    rows, seen = [], set()
    for it in words or []:
        if isinstance(it, str):
            it = {"word": it}
        w = str((it or {}).get("word") or "").strip()
        if not w or w in seen or w.startswith("#"):
            continue
        seen.add(w)
        level = str(it.get("level") or "中")
        level = level if level in ("高", "中", "低") else "中"
        cat = str(it.get("category") or "通用").strip() or "通用"
        rows.append(f"{w}|{level}|{cat}")
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = WORDLIST + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("# 敏感词表：一行一词；可选扩展格式「词|级别|类别」，级别=高/中/低\n")
        f.write("\n".join(rows) + ("\n" if rows else ""))
    os.replace(tmp, WORDLIST)
    return len(rows)


def scan_text(text, words=None, max_hits_per_word=20, ctx=16):
    """扫一段正文 → {hits:[{word, level, category, count, spans:[[s,e]..], samples:[..]}], total}"""
    text = text or ""
    words = words if words is not None else load_words()
    hits = []
    total = 0
    for w in words:
        word = w["word"]
        if not word or word not in text:
            continue
        spans = [m.start() for m in re.finditer(re.escape(word), text)]
        n = len(spans)
        total += n
        samples = []
        for s in spans[:max_hits_per_word]:
            samples.append({
                "span": [s, s + len(word)],
                "context": text[max(0, s - ctx):s] + "【" + word + "】" + text[s + len(word):s + len(word) + ctx],
            })
        hits.append({"word": word, "level": w["level"], "category": w["category"],
                     "count": n, "samples": samples})
    order = {"高": 0, "中": 1, "低": 2}
    hits.sort(key=lambda h: (order.get(h["level"], 1), -h["count"]))
    return {"hits": hits, "total": total,
            "n_high": sum(h["count"] for h in hits if h["level"] == "高"),
            "chars": len(text)}


def scan_chapter(book, no):
    """扫本书某一章成稿。返回 None 表示该章没有正文文件。"""
    p = os.path.join(book_dir(book), "manuscript", "%03d.txt" % int(no))
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return None
    return scan_text(text)


def scan_book(book):
    """扫全书所有成稿 → {chapters: [{no, total, n_high, hits(压缩: word/level/count)}], total, n_high}"""
    d = os.path.join(book_dir(book), "manuscript")
    out, total, n_high = [], 0, 0
    if os.path.isdir(d):
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".txt"):
                continue
            try:
                no = int(fn[:-4])
            except ValueError:
                continue
            r = scan_chapter(book, no)
            if not r:
                continue
            total += r["total"]
            n_high += r["n_high"]
            if r["total"]:
                out.append({"no": no, "total": r["total"], "n_high": r["n_high"],
                            "hits": [{"word": h["word"], "level": h["level"],
                                      "category": h["category"], "count": h["count"]}
                                     for h in r["hits"]]})
    return {"chapters": out, "total": total, "n_high": n_high, "n_chapters_hit": len(out)}
