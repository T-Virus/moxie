# -*- coding: utf-8 -*-
"""本地自动备份 / 回收站
========================
章节数据是整个工作流最贵的一份文件（设定、章节、角色都在里面）。
每次保存前把旧文件复制到 data/<书名>/.backup/，保留最近 KEEP 份；
目录以「.」开头，不会进入数据同步 zip，也不影响产出浏览。

只备份 chapters.json：decomposed.json 是拆解原始产出，重新拆解可再生成；
正文有 manuscript/history，审查报告本身按时间戳留存。
"""

import os
import re
import shutil
import time

from paths import book_chapters, book_dir

KEEP = 20
DIR_NAME = ".backup"
_NAME_RE = re.compile(r"^chapters-\d{8}-\d{6}(?:-\d+)?\.json$")


def _backup_dir(book):
    return os.path.join(book_dir(book), DIR_NAME)


def snapshot(book, reason="save"):
    """保存前快照；返回备份文件名（没有现存文件时返回空串）。"""
    src = book_chapters(book)
    if not book or not os.path.isfile(src):
        return ""
    d = _backup_dir(book)
    os.makedirs(d, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    name = f"chapters-{ts}.json"
    dst = os.path.join(d, name)
    i = 1
    while os.path.exists(dst):          # 同一秒多次保存时追加序号
        dst = os.path.join(d, f"chapters-{ts}-{i}.json")
        name = os.path.basename(dst)
        i += 1
    try:
        shutil.copy2(src, dst)
    except OSError:
        return ""
    _prune(d)
    return name


def _prune(d):
    try:
        files = sorted(f for f in os.listdir(d) if _NAME_RE.match(f))
    except OSError:
        return
    for f in files[:-KEEP]:
        try:
            os.remove(os.path.join(d, f))
        except OSError:
            pass


def list_backups(book):
    """按时间倒序列出可用备份。"""
    d = _backup_dir(book)
    if not book or not os.path.isdir(d):
        return []
    out = []
    try:
        names = [f for f in os.listdir(d) if _NAME_RE.match(f)]
    except OSError:
        return []
    for f in names:
        p = os.path.join(d, f)
        try:
            st = os.stat(p)
        except OSError:
            continue
        out.append({"file": f, "size": st.st_size,
                    "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))})
    return sorted(out, key=lambda x: x["file"], reverse=True)


def restore(book, file):
    """恢复指定备份；恢复前先把当前版本再快照一次（可反悔）。"""
    name = os.path.basename(str(file or ""))
    if not name or not _NAME_RE.match(name):
        raise ValueError("备份文件名不合法")
    src = os.path.join(_backup_dir(book), name)
    if not os.path.isfile(src):
        raise ValueError("该备份不存在或已被清理")
    # 先读进内存：恢复前的快照可能触发清理，把最旧的那份（正好是要恢复的）删掉
    try:
        with open(src, "rb") as f:
            raw = f.read()
    except OSError as e:
        raise ValueError(f"读取备份失败：{e}")
    snapshot(book, "before-restore")
    os.makedirs(os.path.dirname(book_chapters(book)), exist_ok=True)
    with open(book_chapters(book), "wb") as f:
        f.write(raw)
    return name
