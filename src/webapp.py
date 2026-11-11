# -*- coding: utf-8 -*-
"""
小说连载工作流 · 本地可视化控制台
====================================
只依赖 Python 标准库。启动：

    python webapp.py            # 默认 http://localhost:8765

功能：
  · 只读提供 workflow.json（供前端上下文预算与章节质检要求使用，不再提供编辑 UI）
  · 可视化编辑 chapters.json（全书要素 + 角色池 / 势力池 + 逐章任务）
  · 素材上传（txt/md）或手动粘贴文本，落盘为源文件供拆解使用
  · 运行拆解任务（decompose），实时日志
  · 浏览拆解产出（data/chapters.json、data/decomposed.json 与 output/ 历史批次）
  · AI 审查（review）：对单章正文做「只诊断、不改写」的问题审查，出 Markdown/HTML/JSON 报告

安全约定：
  · 默认只监听 127.0.0.1；手机同 Wi-Fi 调试时可用环境变量 MOBIT_HOST=0.0.0.0 显式开放（无鉴权，勿在不可信网络使用）
  · API Key 不落盘：由前端传入，仅作为子进程环境变量使用
  · 文件读写限制在工作区，上传仅接受 .txt/.md 且不得与程序文件重名
"""

import base64
import io
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import backup as backuplib
import compliance as compliancelib
import cover as coverlib
import entities as entitylib
import guard as guardlib
import history as historylib
import runner
import secure as securelib
import sentinel as sentinellib
import studio as studiolib
import usage as usagelib
from story_bible import (
    compose as compose_story_bible,
    filter_by_roles as filter_story_bible,
    normalize_card,
    normalize_faction,
    parse as parse_story_bible,
    schema as sb_schema,
)
from paths import (
    CHAPTERS,
    DATA_DIR,
    DECOMPOSED,
    FROZEN,
    INPUT_DIR,
    OUTPUT_DIR,
    ROOT,
    SRC_DIR,
    WEB_DIR,
    WORKFLOW,
    book_chapters,
    book_decomposed,
    book_dir,
    ensure_dirs,
)

OUT_DIR = OUTPUT_DIR
HOST, PORT = os.environ.get("MOBIT_HOST", "127.0.0.1"), int(os.environ.get("MOBIT_PORT", "8765"))

RESERVED_PREFIX = ("workflow", "chapters", "decompose", "decomposed", "engine",
                   "review", "webapp", "deepseek_common", "dec_", "source_novel")
MAX_UPLOAD = 50 * 1024 * 1024
# 普通 JSON 请求体上限（需大于 MAX_UPLOAD：上传以 base64 放在 JSON 体内）。
# 本地 127.0.0.1 应用风险低；MOBIT_HOST=0.0.0.0 开放局域网时防 DoS。
MAX_JSON_BODY = 64 * 1024 * 1024
# 数据同步 zip：导出不限（按需打包），导入限制解压后的总体积与文件数，避免解压炸弹
MAX_DATA_IMPORT = 256 * 1024 * 1024
MAX_DATA_FILES = 20000
DATA_ZIP_EXTS = {".json", ".txt", ".md", ".markdown", ".html", ".htm",
                 ".png", ".jpg", ".jpeg", ".webp"}
# 导入 / 导出互斥：避免导出时正读到导入写到一半的目录
DATA_SYNC_LOCK = threading.Lock()

# 子进程任务通道：支持多任务并发，每个任务一条独立记录（独立日志 / 独立子进程 / 独立停止），
# 前端按 id 轮询，切到哪本书、哪个任务，就回显哪个任务的实时日志。
JOBS = {}
JOB_SEQ = [0]
JOB_LOCK = threading.RLock()
MAX_LOG_LINES = 4000
MAX_JOBS_KEPT = 20          # 结束后保留多少个任务，供回看日志 / 失败原因
JOB_LABEL = {"decompose": "拆解大纲", "adapt": "改编全文",
             "storymap": "生成设定图谱", "expand": "批量扩写"}

# ---------------------------------------------------------------- 页内任务（AI 审查 / 正文生成）
# 这两类任务跑在进程内线程里（不像拆解那样启子进程），但同样允许「多条同时跑」：
# 每一章可以各自生成、各自审查，互不阻塞；只有「同一本书 + 同一章 + 同类任务」才互斥，
# 否则两路流会把同一份正文 / 同一份报告写串。
# 每条任务独立 id（r1 / w1 …，子进程任务则是 j1 / j2 …）、独立日志、独立停止标记与结果，
# 任务中心按 id 展示，点进去跳回发起页面（origin）。
# token 是「这一次运行」的身份：释放 / 删除后置空，旧线程的日志与结果就作废丢弃，
# 否则它跑完会把状态改回去，或者把结果写进新任务里。
PAGE_TASKS = {}               # id -> 任务状态
PAGE_SEQ = [0]
PAGE_LOCK = threading.RLock()
MAX_PAGE_LOG = 2000           # 单条页内任务的日志行上限
MAX_PAGE_KEPT = 20            # 结束的页内任务保留条数（供任务中心回看）

# 并发模型（所有任务一套规则，不分通道）：
#   1) 每条任务独立 id / 日志 / 停止标记 / 结果，互不阻塞；
#   2) 只有「会写同一份产出文件」的才互斥（同书同章正文、同书同阶段子进程作业）；
#   3) 所有运行中的任务共用一个并发额度，防止把 API 配额打满。
# 额度只跟「正在跑多少」有关，与任务类型、通道无关——所以生成和审查、子进程和页内线程
# 可以任意混跑，不会因为「别的任务在跑」被 409 挡住。
MAX_RUNNING_TASKS = 8

# ---------------------------------------------------------------- 任务持久化（P0：重启不丢任务）
# 所有任务（子进程 + 页内线程）的状态定期快照到 data/_system/tasks.json：
#   · 服务崩溃 / 关窗 / 系统重启后，任务中心仍能看到「上次跑到哪、为什么断」；
#   · 中断的子进程任务可一键「恢复」：批量扩写自动带 --skip-existing 跳过已成稿章节；
#   · 页内任务（单章生成 / 审查）的产出本来就各自落盘（manuscript / review / expand 快照），
#     恢复的是「记录与日志」，不自动重跑——避免重启后未经确认就烧 API 额度。
TASKS_FILE = os.path.join(DATA_DIR, "_system", "tasks.json")
TASKS_PERSIST_SEC = 2.0


def _job_snapshot(j):
    """子进程任务的可落盘视图（剔除 proc / api_key 等不可序列化与敏感字段）。"""
    return {
        "id": j["id"], "stage": j["stage"], "label": j["label"],
        "book": j["book"], "out_book": j.get("out_book") or "",
        "args": {k: v for k, v in (j.get("args") or {}).items()},
        "queue": [dict(s) for s in (j.get("queue") or [])],
        "running": bool(j["running"]), "code": j["code"], "error": j["error"],
        "stopped": bool(j["stopped"]), "interrupted": bool(j.get("interrupted")),
        "log": list(j["log"][-300:]),
        "created_at": j["created_at"], "finished_at": j["finished_at"],
        "origin": j.get("origin") or "",
    }


def _page_snapshot(t):
    """页内任务的可落盘视图（正文 / 候选体量大，正文快照由 expand_task_ch*.json 负责，这里只存状态）。"""
    return {
        "id": t["id"], "stage": t["stage"], "channel": "page",
        "book": t.get("book") or "", "chapter_no": str(t.get("chapter_no") or ""),
        "title": t.get("title") or "", "origin": t.get("origin") or "",
        "mode": t.get("mode") or "outline", "scope": t.get("scope") or "chapter",
        "running": bool(t["running"]), "code": t.get("code"), "error": t.get("error"),
        "stopped": bool(t.get("stopped")), "interrupted": bool(t.get("interrupted")),
        "log": list(t.get("log", [])[-300:]),
        "started_at": t.get("started_at") or 0, "finished_at": t.get("finished_at") or 0,
    }


def _tasks_persist_loop():
    """每 2 秒把任务表整体落盘一次（有任务才写；失败静默，绝不反噬主服务）。"""
    while True:
        time.sleep(TASKS_PERSIST_SEC)
        try:
            with JOB_LOCK:
                jobs = [_job_snapshot(j) for j in JOBS.values()]
            with PAGE_LOCK:
                pages = [_page_snapshot(t) for t in PAGE_TASKS.values()]
            if not jobs and not pages and not os.path.isfile(TASKS_FILE):
                continue
            os.makedirs(os.path.dirname(TASKS_FILE), exist_ok=True)
            tmp = TASKS_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"jobs": jobs, "pages": pages}, f, ensure_ascii=False)
            os.replace(tmp, TASKS_FILE)
        except Exception:  # noqa
            pass


def _restore_tasks():
    """启动时恢复上次任务表：运行中的一律标记「中断」（进程都死了，线程不可能还活着）。

    中断的子进程任务带 resumable=True：前端任务中心显示「恢复」按钮；
    页内任务恢复记录与日志（供回看失败原因），不提供自动重跑。"""
    data = read_json(TASKS_FILE, {})
    if not isinstance(data, dict):
        return 0
    n = 0
    with JOB_LOCK:
        for s in data.get("jobs") or []:
            if not isinstance(s, dict) or not s.get("id"):
                continue
            jid = s["id"]
            m = re.search(r"\d+", jid)
            if m:
                JOB_SEQ[0] = max(JOB_SEQ[0], int(m.group(0)))
            job = {
                "id": jid, "stage": s.get("stage") or "", "label": s.get("label") or "",
                "book": s.get("book") or "", "out_book": s.get("out_book") or "",
                "args": s.get("args") or {}, "log": list(s.get("log") or []),
                "queue": [], "running": False, "code": s.get("code"),
                "error": s.get("error"), "stopped": bool(s.get("stopped")),
                "proc": None, "api_key": "",
                "created_at": s.get("created_at") or time.time(),
                "finished_at": s.get("finished_at") or 0.0,
                "origin": s.get("origin") or "",
                "interrupted": bool(s.get("interrupted")),
            }
            if s.get("running"):
                job.update(interrupted=True, stopped=True,
                           error="服务重启，任务中断（已完成的章节产出保留在磁盘上）",
                           finished_at=time.time())
                job["log"].append("[!] 服务重启：任务中断。批量扩写可点「恢复」跳过已完成章节继续跑")
            if not job["finished_at"]:
                job["finished_at"] = time.time()
            JOBS[jid] = job
            n += 1
    with PAGE_LOCK:
        for s in data.get("pages") or []:
            if not isinstance(s, dict) or not s.get("id"):
                continue
            tid = s["id"]
            m = re.search(r"\d+", tid)
            if m:
                PAGE_SEQ[0] = max(PAGE_SEQ[0], int(m.group(0)))
            t = {
                "id": tid, "stage": s.get("stage") or "review", "channel": "page",
                "book": s.get("book") or "", "chapter_no": str(s.get("chapter_no") or ""),
                "origin": s.get("origin") or "", "title": s.get("title") or "",
                "running": False, "stop": False,
                "stopped": bool(s.get("stopped")) or bool(s.get("running")),
                "code": s.get("code"),
                "error": s.get("error") or (
                    "服务重启，任务中断" if s.get("running") else None),
                "log": list(s.get("log") or []),
                "text": "", "mode": s.get("mode") or "outline",
                "scope": s.get("scope") or "chapter",
                "multi": False, "versions": [], "recommended": 0,
                "result": None, "files": {}, "token": object(),
                "started_at": s.get("started_at") or 0,
                "finished_at": s.get("finished_at") or time.time(),
                "interrupted": bool(s.get("running")) or bool(s.get("interrupted")),
            }
            if s.get("running"):
                t["log"].append("[!] 服务重启：任务中断（正文 / 报告以磁盘上的成稿为准）")
            PAGE_TASKS[tid] = t
            n += 1
    return n


def running_total():
    """全部通道的运行中任务数（子进程作业 + 页内线程任务）。"""
    with JOB_LOCK:
        n = sum(1 for j in JOBS.values() if j["running"])
    with PAGE_LOCK:
        n += sum(1 for t in PAGE_TASKS.values() if t["running"])
    return n


def book_write_conflict(book, page_write=None):
    """批量扩写（子进程）会写整本书的正文，和页内「正文生成」抢同一批文件：

    同书两者同时在跑，后发起的一方会被覆盖，所以这里互斥。
    page_write=True 表示问「本书是否有页内生成在跑」，False 表示问「本书是否有批量扩写在跑」。"""
    if not book:
        return None
    if page_write:
        with PAGE_LOCK:
            for t in PAGE_TASKS.values():
                if t["stage"] == "write" and t["running"] and t["book"] == book:
                    return t
        return None
    with JOB_LOCK:
        return next((j for j in JOBS.values()
                     if j["running"] and j["stage"] == "expand"
                     and (j["book"] or "").lower() == book.lower()), None)


def page_task_new(stage, book, chapter_no, origin="", **extra):
    """开一条页内任务（stage: review / write），返回它的状态字典。"""
    with PAGE_LOCK:
        PAGE_SEQ[0] += 1
        tid = f"{'r' if stage == 'review' else 'w'}{PAGE_SEQ[0]}"
        t = {
            "id": tid, "stage": stage, "channel": "page",
            "book": book, "chapter_no": str(chapter_no or ""),
            "origin": clean_origin(origin),
            "running": True, "stop": False, "stopped": False,
            "code": None, "error": None, "log": [], "text": "",
            # scope 区分「整章改写」与「选区改写」：两者提示词、落点、候选面板都不同
            "mode": "outline", "scope": "chapter", "multi": False, "versions": [], "recommended": 0,
            "result": None, "files": {}, "token": object(),
            "started_at": time.time(), "finished_at": 0.0,
        }
        t.update(extra)
        PAGE_TASKS[tid] = t
        page_prune()
        return t


def page_task_get(tid):
    with PAGE_LOCK:
        return PAGE_TASKS.get(tid or "")


def page_task_latest(stage, book="", chapter_no=""):
    """找某类页内任务：优先「运行中的」，其次最近结束的；可按书 / 章过滤。
    页面「接管进行中的任务」靠它——只接管本章的，不会把别章的进度显示到当前章。"""
    with PAGE_LOCK:
        cands = [t for t in PAGE_TASKS.values() if t["stage"] == stage]
        if book:
            cands = [t for t in cands if t["book"] == book]
        if chapter_no not in ("", None):
            cands = [t for t in cands if str(t["chapter_no"]) == str(chapter_no)]
        if not cands:
            return None
        run = [t for t in cands if t["running"]]
        return max(run or cands, key=lambda x: x["started_at"])


def page_busy(stage, book, chapter_no):
    """同一本书同一章的同类任务是否还在跑（同一份正文 / 报告不能两路同时写）。"""
    with PAGE_LOCK:
        for t in PAGE_TASKS.values():
            if (t["stage"] == stage and t["running"] and t["book"] == book
                    and str(t["chapter_no"]) == str(chapter_no)):
                return t
    return None


def book_busy(name):
    """本书是否有在跑的任务：子进程任务（拆解/改编/扩写/图谱，源书或产出书命中）
    或页内任务（审查 / 正文生成）。有则返回任务 dict——运行中的任务仍按旧数据写文件，
    此时保存 / 改名会互相覆盖，必须拒绝。"""
    with JOB_LOCK:
        hot = next((j for j in JOBS.values() if j.get("running")
                    and name in (j.get("book"), j.get("out_book"))), None)
    if hot:
        return hot
    with PAGE_LOCK:
        return next((t for t in PAGE_TASKS.values() if t.get("running")
                     and t.get("book") == name), None)


def page_prune():
    """只留最近结束的若干条，运行中的一条不动。"""
    with PAGE_LOCK:
        done = sorted((t for t in PAGE_TASKS.values() if not t["running"]),
                      key=lambda x: x["started_at"])
        for t in done[:-MAX_PAGE_KEPT] if len(done) > MAX_PAGE_KEPT else []:
            PAGE_TASKS.pop(t["id"], None)
            t["token"] = None          # 已被淘汰：万一还有尾线程，写回也一律丢弃


def page_log(t, msg):
    """往某条页内任务的日志追加一行；任务已释放 / 删除（token 置空）后一律丢弃。"""
    if t is None:
        return
    with PAGE_LOCK:
        if t.get("token") is None:
            return
        t["log"].append(msg)
        if len(t["log"]) > MAX_PAGE_LOG:
            del t["log"][:len(t["log"]) - MAX_PAGE_LOG]


# 正文任务名：整章与选区是两种完全不同的动作（一个替换全章、一个只替换选中片段），
# 名字必须能一眼分开，否则任务中心里会出现两条一模一样的「生成正文」。
WRITE_MODE_NAME = {"continue": "续写", "expand": "扩写", "rewrite": "改写", "polish": "润色"}


def page_task_name(t):
    """任务名（动词短语）。审查按实际跑的内容区分：调了模型叫 AI 审查，只跑规则叫程序体检。"""
    title = (t.get("title") or "").strip()
    if title:
        return title
    if t["stage"] == "review":
        return "审查正文"
    mode = (t.get("mode") or "outline").strip()
    if mode == "outline":
        return "生成正文"
    word = WRITE_MODE_NAME.get(mode, mode)
    return f"{word}选区" if t.get("scope") == "selection" else f"整章{word}"


def page_label(t):
    """任务在任务中心里显示的名字：书名在前，「《书》第 N 章 · 做了什么」。"""
    book, ch = t.get("book") or "", str(t.get("chapter_no") or "")
    name = page_task_name(t)
    if book and ch:
        return f"《{book}》第 {ch} 章 · {name}"
    return f"《{book}》 · {name}" if book else name


def page_summary(t):
    """页内任务 → /api/jobs 里的一条任务摘要（与子进程任务同结构）。"""
    if t is None:
        return None
    with PAGE_LOCK:
        err = t.get("error") or ""
        code = t.get("code")
        if t["stage"] == "review":
            code = 1 if (err and not t["running"]) else 0
        return {
            "id": t["id"], "stage": t["stage"], "channel": "page",
            "label": page_label(t), "name": page_task_name(t),
            "mode": t.get("mode") or "", "scope": t.get("scope") or "chapter",
            "book": t.get("book") or "", "chapter_no": str(t.get("chapter_no") or ""),
            "out_book": "",
            "running": bool(t["running"]),
            "code": code if code is not None else 0,
            "error": err, "stopped": bool(t.get("stopped")), "total": len(t["log"]),
            "interrupted": bool(t.get("interrupted")), "resumable": False,
            "created_at": t.get("started_at") or 0,
            "finished_at": t.get("finished_at") or 0,
            "origin": t.get("origin") or "",
        }


def page_public(t, since=0):
    """任务中心右栏：按 id 拉这条页内任务的日志增量。"""
    s = page_summary(t) or {
        "id": (t or {}).get("id", ""), "stage": (t or {}).get("stage", ""),
        "channel": "page", "label": "", "book": "", "chapter_no": "", "out_book": "",
        "running": False, "code": 0, "error": "", "stopped": False, "total": 0,
        "created_at": 0, "finished_at": 0, "origin": "",
    }
    with PAGE_LOCK:
        s["lines"] = t["log"][since:] if t else []
        s["total"] = len(t["log"]) if t else 0
    s["queued"] = []
    return s


def page_stop(t):
    """请求停止（线程在下一个检查点退出）。"""
    with PAGE_LOCK:
        if not t["running"]:
            return False
        t["stop"] = True
    page_log(t, "[!] 已请求停止（当前这一步跑完就退出）")
    return True


def page_release(t):
    """释放：不等这一步跑完立刻解锁（审查用——释放后可以马上切章 / 另起任务）。

    旧线程在下一个检查点自行退出，期间日志与结果全部作废。"""
    with PAGE_LOCK:
        if not t["running"]:
            return False
        t.update(stop=True, stopped=True, running=False,
                 finished_at=time.time(), token=None)
        t["log"].append("[!] 已释放：可以切章 / 发起别的任务了（后台线程会在当前这一步后退出）")
    return True


def page_reset(tid):
    """删掉这条页内任务记录（运行中的调用方已先拦下）。"""
    with PAGE_LOCK:
        t = PAGE_TASKS.pop(tid, None)
        if t is not None:
            t["token"] = None
        return t


def expand_task_file(book, chapter_no=None):
    """每本书「每章」一份正文任务快照：多本书 / 多章同时改时互不覆盖。

    以前是整本一份，切到别的书再回来、或者另一章生成了候选，都会把上一章的候选冲掉。"""
    try:
        n = int(chapter_no or 0)
    except (TypeError, ValueError):
        n = 0
    name = "expand_task_ch%03d.json" % n if n > 0 else "expand_task.json"
    return os.path.join(book_dir(book), name)


def _expand_snapshot(t):
    """这条正文任务的结果快照。

    候选全文、推荐版、选区偏移、生成前正文都要留着：切书 / 切章 / 重启服务后回来，
    候选列表与「采纳」还能原样接着用，不用重新生成一遍。"""
    versions = []
    for v in (t.get("versions") or []):
        if not isinstance(v, dict):
            continue
        text = v.get("text") or ""
        versions.append({"text": text, "note": v.get("note") or "",
                         "chars": v.get("chars") or len(text)})
    return {
        "id": t.get("id") or "",
        "book": t.get("book") or "",
        "chapter_no": t.get("chapter_no"),
        "name": page_task_name(t),
        "mode": t.get("mode") or "outline",
        "scope": t.get("scope") or "chapter",
        "multi": bool(t.get("multi")),
        "code": t.get("code"),
        "error": t.get("error"),
        "stopped": bool(t.get("stopped")),
        "versions": versions,
        "recommended": t.get("recommended") or 0,
        "target": t.get("target") or None,
        "existing": t.get("existing") or "",
        "versions_count": len(versions),
        "chars": len(t.get("text") or ""),
        "started_at": t.get("started_at") or 0,
        "finished_at": t.get("finished_at") or 0,
        "saved_at": time.time(),
    }


def save_expand_state(t):
    """任务结束（完成 / 失败 / 停止）时把最终状态落盘；运行中不写。"""
    with PAGE_LOCK:
        snap = _expand_snapshot(t)
    if not snap["book"]:
        return
    try:
        d = book_dir(snap["book"])
        os.makedirs(d, exist_ok=True)
        with open(expand_task_file(snap["book"], snap["chapter_no"]), "w",
                  encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=2)
    except OSError as e:
        page_log(t, f"[!] 任务快照写入失败（重启后无法恢复本次状态）：{e}")


def start_page_thread(t, target, kwargs):
    """启动页内任务线程。任何未捕获异常（含 import 期失败）都必须把任务状态收回，
    否则这条任务会永久 running：任务中心里停不掉、也删不掉，还把同章卡死。"""
    def _run():
        try:
            target(t=t, **kwargs)
        except Exception as e:  # noqa
            # 任务可能已被释放 / 删除（token 置空）：那这条旧线程不该再把状态改回去
            with PAGE_LOCK:
                if t.get("token") is not None:
                    t.update(running=False, code=1, error=f"任务线程异常：{e}",
                             finished_at=time.time())
            page_log(t, f"[x] {e}")
            # 正文任务异常也要落盘：否则重启后这条失败原因就查不到了（审查任务不写这个文件）
            if t.get("stage") == "write":
                try:
                    save_expand_state(t)
                except Exception:  # noqa
                    pass

    th = threading.Thread(target=_run, daemon=True)
    th.start()
    return th


class ExpandStopped(Exception):
    pass


def _local_expand(t, book, ch, sb, characters, factions, ch_no, mode, existing):
    """没有 Key 时的单章生成：产出可编辑的写作骨架（写作清单），不编造正文。

    仍然落盘成 manuscript/NNN.txt，后续审查、导出、统计都能照常跑；
    配好 Key 后重新生成就是正式正文。
    """
    from expand import local_prose
    page_log(t, f"[本地] 未配置 API Key：第 {ch_no} 章生成写作骨架（不调用模型，质量有限）")
    prose = local_prose(ch, sb, characters, factions)
    final = (existing.rstrip() + "\n\n" + prose).strip() \
        if (mode == "continue" and existing.strip()) else prose
    out_dir = os.path.join(book_dir(book), "manuscript")
    os.makedirs(out_dir, exist_ok=True)
    fn = os.path.join(out_dir, f"{int(ch_no):03d}.txt")
    old = ""
    if os.path.isfile(fn):
        try:
            with open(fn, encoding="utf-8", errors="replace") as f:
                old = f.read()
        except OSError:
            pass
        if old and old != final:
            historylib.snapshot(book, ch_no, old, note="本地骨架覆盖前")
    with open(fn, "w", encoding="utf-8") as f:
        f.write(final)
    _record_writing(book, len(old), len(final))
    with PAGE_LOCK:
        t.update(running=False, code=0, text=prose, error=None,
                 stopped=False, finished_at=time.time())
    page_log(t, f"[完成] 第 {ch_no} 章已写入骨架（{len(final)} 字）；"
                "配好 Key 后可用「按大纲生成」覆盖为正式正文")
    save_expand_state(t)


def expand_worker(t, book, ch, sb, characters, factions, ch_no, api_key, base_url, model,
                  temperature, mode="outline", existing="", style=None, n=3,
                  before="", after="", extra_block=""):
    from expand import system_prompt, build_mode_prompt
    from deepseek_common import chat_text_stream

    if not api_key:
        _local_expand(t, book, ch, sb, characters, factions, ch_no, mode, existing)
        return

    usagelib.set_context(stage=resolve_stage_key("expand", t.get("mode"), t.get("scope")),
                         book=book, chapter_no=ch_no)
    mem, mem_note = build_memory_block(book, ch)
    if mem:
        page_log(t, f"[记忆] 已注入{mem_note}（近章摘要 + 相关前文检索）")

    # 整章续写需要字数目标，否则提示词里会出现「约 0~0 字」；outline 不需要
    target = _mode_target(mode, existing) if mode == "continue" else 0
    page_log(t, f"[生成] 《{book}》第 {ch_no} 章｜{page_task_name(t)}"
                f"｜模型 {model}｜温度 {temperature}")

    def on_delta(piece):
        with PAGE_LOCK:
            if t["stop"]:
                raise ExpandStopped()
            t["text"] += piece

    try:
        prose = chat_text_stream(api_key, base_url, model, system_prompt(),
                                 build_mode_prompt(mode, ch, sb, characters, factions, existing,
                                                   target=target, style=style, memory=mem,
                                                   extra_block=extra_block),
                                 timeout=900, temperature=temperature, on_delta=on_delta)
        # 续写：新正文接在原文之后落盘；扩写/改写/大纲：直接覆盖
        final = (existing.rstrip() + "\n\n" + prose).strip() \
            if (mode == "continue" and existing.strip()) else prose
        out_dir = os.path.join(book_dir(book), "manuscript")
        os.makedirs(out_dir, exist_ok=True)
        fn = os.path.join(out_dir, f"{int(ch_no):03d}.txt")
        old = ""
        if os.path.isfile(fn):
            try:
                with open(fn, encoding="utf-8", errors="replace") as f:
                    old = f.read()
            except OSError:
                pass
            if old and old != final:
                historylib.snapshot(book, ch_no, old, note="单章生成覆盖前")
        with open(fn, "w", encoding="utf-8") as f:
            f.write(final)
        _record_writing(book, len(old), len(final))
        with PAGE_LOCK:
            t.update(running=False, code=0, text=prose, error=None,
                     stopped=False, finished_at=time.time())
        page_log(t, f"[完成] 第 {ch_no} 章已写入正文（{len(final)} 字）")
    except ExpandStopped:
        with PAGE_LOCK:
            t.update(running=False, code=None, error=None, stopped=True,
                     finished_at=time.time())
        page_log(t, "[!] 已停止（已生成的内容保留在编辑器里，未写入正文）")
    except Exception as e:  # noqa
        with PAGE_LOCK:
            t.update(running=False, code=1, error=str(e), finished_at=time.time())
        page_log(t, f"[x] {e}")
    save_expand_state(t)


# 续写 / 扩写 / 改写：一次产出三个不同方向版本，前端展示后由用户采纳再写入
# 每个模式的三个侧重方向（让三版之间有可感知的差异）
VERSION_DIRECTIONS = {
    "continue": [
        "推进主线冲突：把场景推向关键转折或危机，节奏紧凑",
        "深挖人物：侧重心理活动与人物关系的变化",
        "铺设悬念：放慢节奏，埋设伏笔与新疑问",
    ],
    "expand": [
        "强化感官与动作：用具体动作、身体感受与细节把叙述展开",
        "扩充对话与互动：增加人物之间的言语交锋与张力",
        "加重环境与氛围：用场景、光线、气味渲染情绪底色",
    ],
    "rewrite": [
        "冷峻克制：删减冗余，句子更短、更直接，留白更多",
        "口语鲜活：以对话驱动，语气更自然生活化",
        "诗意意象：语言更富节奏与意象，情绪更外放",
    ],
    "polish": [
        "通顺顺滑：理顺长句、统一节奏，读起来更流畅",
        "画面补足：把抽象处补成可感细节与动作",
        "去味提纯：打散模板化表达，去掉过度解释",
    ],
}


def _mode_target(mode, existing):
    """本版期望字数：整章 ≈ 2000；选中片段（短文）按比例缩放，避免一段话被续成两千字。
    单句选区（≤120 字）进一步收小，扩写/续写才不会「一句顶一千字」。"""
    n = len(existing.strip())
    tiny = n <= 120
    short = n <= 800
    if mode == "continue":
        if tiny:
            return max(60, min(n * 2, 200))
        return max(300, min(n * 3, 1200)) if short else 2000
    if mode == "expand":
        if tiny:
            return max(120, min(n * 4, 400))
        return max(600, min(n * 2, 6000)) if short else max(1500, min(n * 2, 6000))
    if mode == "rewrite":
        return max(300, n) if not tiny else max(20, n)
    if mode == "polish":
        return max(20, n)          # 润色只做文字打磨，篇幅必须与原文相当
    return 2000


def expand_versions_worker(t, book, ch, sb, characters, factions, ch_no, api_key, base_url,
                           model, temperature, mode, existing, n=3, style=None,
                           before="", after="", extra_block=""):
    from expand import system_prompt, MODE_LABEL, build_mode_prompt, build_selection_prompt
    from deepseek_common import chat_text

    notes = VERSION_DIRECTIONS.get(mode, [])[:n] or [""]
    if len(notes) < n:
        notes += [f"侧重方向 {i + 1}" for i in range(len(notes), n)]

    if not api_key:
        from expand import local_prose
        page_log(t, f"[本地] 未配置 API Key：{n} 个候选都是写作骨架（不调用模型），"
                    "可在编辑器里按骨架推进，或配好 Key 后重新生成")
        versions = []
        for note in notes:
            body = local_prose(ch, sb, characters, factions)
            if note:
                body = f"（本地骨架 · 本版侧重：{note}）\n" + body
            versions.append({"text": body, "note": note, "chars": len(body)})
        with PAGE_LOCK:
            t.update(running=False, code=0, versions=versions, recommended=0,
                     error=None, stopped=False, finished_at=time.time())
        page_log(t, "[完成] 候选已就绪（均为本地骨架，采纳后会写入正文，请自行润色）")
        save_expand_state(t)
        return

    target = _mode_target(mode, existing)
    usagelib.set_context(stage=resolve_stage_key("expand", t.get("mode"), t.get("scope")),
                         book=book, chapter_no=ch_no)
    mem, mem_note = build_memory_block(book, ch)
    if mem:
        page_log(t, f"[记忆] 已注入{mem_note}（近章摘要 + 相关前文检索）")
    with PAGE_LOCK:
        t.update(text="", versions=[], recommended=0, multi=True)
    page_log(t, f"[生成] 《{book}》第 {ch_no} 章｜{page_task_name(t)}"
                f"｜{len(notes)} 个候选｜模型 {model}")
    versions = []
    stopped = False
    for i, note in enumerate(notes):
        with PAGE_LOCK:
            if t["stop"]:
                stopped = True
                break
            t["text"] += f"\n正在生成候选 {i + 1}/{len(notes)}（{MODE_LABEL.get(mode, mode)} · {note}）…\n"
        page_log(t, f"[{i + 1}/{len(notes)}] 正在生成候选 {i + 1}（{note}）")
        try:
            # 带前后文的选区操作走专用提示词，保证单句也能与上下文承接
            if (before or "").strip() or (after or "").strip():
                prompt = build_selection_prompt(mode, ch, sb, characters, factions, existing,
                                                before=before, after=after, target=target,
                                                style=style, memory=mem)
            else:
                prompt = build_mode_prompt(mode, ch, sb, characters, factions, existing,
                                           target=target, style=style, memory=mem,
                                           extra_block=extra_block)
            if note:
                # 每版单独调用：只交代本版方向，不要让模型去"兼顾另外两版"或写对比说明
                prompt += (f"\n\n【本版侧重方向】{note}。整体质量不降，但本版要明显偏向这个方向。"
                           f"只输出这一版正文，不要说明、不要提及其他版本、不要加标题或分隔线。")
            prose = chat_text(api_key, base_url, model, system_prompt(), prompt,
                              timeout=900, temperature=min(1.0, temperature + 0.15))
            versions.append({"text": prose, "note": note, "chars": len(prose)})
            with PAGE_LOCK:
                t["text"] += f"候选 {i + 1} 完成（{len(prose)} 字）\n"
            page_log(t, f"[{i + 1}/{len(notes)}] 候选 {i + 1} 完成（{len(prose)} 字）")
        except Exception as e:  # noqa
            with PAGE_LOCK:
                t["text"] += f"候选 {i + 1} 失败：{e}\n"
            page_log(t, f"[!] 候选 {i + 1} 失败：{e}")
    # 推荐：字数最接近该模式目标长度的版本（质量/长度均衡）
    recommended = 0
    if versions:
        recommended = min(range(len(versions)),
                         key=lambda k: abs(versions[k]["chars"] - target))
    with PAGE_LOCK:
        t.update(running=False, code=0 if versions else 1,
                 versions=versions, recommended=recommended,
                 error=None if versions else "全部候选生成失败",
                 stopped=stopped, finished_at=time.time())
    if versions:
        page_log(t, f"[完成] {len(versions)} 个候选已就绪（推荐第 {recommended + 1} 个），"
                    "到正文页采纳后会写入正文")
    elif stopped:
        page_log(t, "[!] 已停止（未采纳任何候选）")
    else:
        page_log(t, "[x] 全部候选生成失败")
    save_expand_state(t)


# ---------------------------------------------------------------- 通用工具
def read_json(path, default):
    """读 JSON：文件缺失或内容损坏都回落默认值，避免一个坏文件让整个接口 500。"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _qint(q, name, default=0):
    """查询参数取整：非法值回默认，避免轮询接口因脏参数 500。"""
    try:
        return int(q.get(name, [""])[0] or default)
    except (TypeError, ValueError):
        return default


def normalize_chapter_no(chapters):
    """统一章号：以可编辑的 no 为准，回写 chapter_id=「第N章」。

    前端章节列表用 no 显示/编辑，而图谱、导出、正文文件名都靠 chapter_id 取章号；
    两处不一致会出现「第 3 章改了序号、正文还写进 003.txt」这类错位，所以保存时对齐一次。
    非数字 chapter_id（如「序章」）保留原样，只补 no。
    """
    for i, c in enumerate(chapters, 1):
        no = to_int(c.get("no"), 0)
        if no <= 0:
            no = to_int(c.get("chapter_id"), 0) or to_int(c.get("id"), 0) or i
        c["no"] = no
        cid = str(c.get("chapter_id") or "").strip()
        if not cid or re.search(r"\d+", cid):
            c["chapter_id"] = f"第{no}章"
    return chapters


def to_int(v, default=0):
    """宽松整数：兼容「12」「第12章」「12-13」，失败回退 default。"""
    m = re.search(r"\d+", str(v if v is not None else ""))
    return int(m.group(0)) if m else default


def chapters_payload(name, data):
    """章节文档的对外视图（GET /api/chapters 与 PUT 保存响应共用，保证回显口径一致）：
    解析设定库文本 → 字段/卡片/势力，规范化词表，再做一遍内存内自洽
    （复读名折叠 + 重复卡合并 + 章节引用同步），只读不写盘。"""
    fields, cards, factions = parse_story_bible(data.get("story_bible", ""))
    # 旧数据 / AI 自由表述 → 9 种立场、6 种阵营；认不出的原样保留，不至于一屏全灰
    for _f in factions:
        normalize_faction(_f)
    # 角色卡：剧情功能 / 九宫格人设倾向 / 对主角态度
    for _c in cards:
        normalize_card(_c)
    # 道具功法：类别收敛到固定词表
    items = [entitylib.normalize_item(dict(it))
             for it in (data.get("items") or []) if isinstance(it, dict)]
    view = {"story_bible_fields": fields, "story_bible_cards": cards,
            "story_bible_factions": factions, "items": items,
            "chapters": data.get("chapters") or []}
    entitylib.sync_document(view)
    data["story_bible_fields"] = fields
    data["story_bible_cards"] = cards
    data["story_bible_factions"] = factions
    data["items"] = items
    data["book"] = name
    return data


def build_storymap_fallback(name):
    """没有 storymap.json 或里面没有地图时，用设定库 + 逐章数据现算一份地图。
    只读不写盘，保证老作品 / 安卓端导入后也能直接看地图。"""
    ch = read_json(book_chapters(name), {})
    chapters = [c for c in (ch.get("chapters") or []) if isinstance(c, dict)]
    fields, cards, factions = parse_story_bible(ch.get("story_bible", "") or "")
    if not chapters:
        return {"levels": ["世界", "区域", "地点"], "regions": [], "scenes": []}
    import storymap as storymaplib
    return storymaplib.fallback_map(fields, chapters, cards, factions)


def sync_storymap_map(name, renames, no_map, valid=None):
    """角色 / 势力 / 道具改名或删除、章节改号后，把 storymap.json 里的地图场景一起同步，
    避免地图上还挂着旧名字、旧章号（地图页下次打开即按新数据回显）。"""
    p = os.path.join(book_dir(name), "storymap.json")
    if not os.path.isfile(p):
        return
    sm = read_json(p, None)
    if not isinstance(sm, dict) or not isinstance(sm.get("map"), dict):
        return
    mp = sm["map"]
    changed = False
    mapping = entitylib._build_mapping(renames or {})
    scenes, dropped = [], False
    for sc in mp.get("scenes") or []:
        if not isinstance(sc, dict):
            continue
        for k in ("characters", "factions", "items"):
            arr = sc.get(k)
            if not isinstance(arr, list):
                continue
            out = []
            for x in arr:
                nv = entitylib.clean_name(mapping.get(str(x).strip(), str(x).strip()))
                if nv and nv not in out:
                    out.append(nv)
            if out != arr:
                sc[k] = out
                changed = True
        if no_map and isinstance(sc.get("chapter"), int):
            nv = no_map.get(sc["chapter"])
            if nv and nv != sc["chapter"]:
                sc["chapter"] = nv
                changed = True
        # 章节被删除后，指向它的场景一并移除，避免留下点不开的死场景
        if valid and isinstance(sc.get("chapter"), int) and sc["chapter"] not in valid:
            dropped = True
            continue
        scenes.append(sc)
    if dropped:
        mp["scenes"] = scenes
        changed = True
    for rg in mp.get("regions") or []:
        if not isinstance(rg, dict) or not isinstance(rg.get("chapters"), list):
            continue
        nums = sorted({no_map.get(x, x) for x in rg["chapters"] if isinstance(x, int)})
        if valid:
            nums = [x for x in nums if x in valid]
        if nums != rg["chapters"]:
            rg["chapters"] = nums
            changed = True
    if changed:
        write_json(p, sm)


# 写 JSON 的临时文件唯一序号：并发写同一文件时各线程用各自 tmp，避免交错写坏
_WRITE_SEQ = [0]


def write_json(path, obj):
    # tmp 文件名带进程/线程/序号，确保并发写者互不干扰；os.replace 仍是原子提交。
    _WRITE_SEQ[0] += 1
    tmp = "{}.tmp.{}.{}.{}".format(path, os.getpid(), threading.get_ident(), _WRITE_SEQ[0])
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def list_sources():
    """input/ 里可作为拆解源的 txt/md。"""
    items = []
    if os.path.isdir(INPUT_DIR):
        for name in sorted(os.listdir(INPUT_DIR)):
            if name.lower().endswith((".md", ".txt")):
                p = os.path.join(INPUT_DIR, name)
                if os.path.isfile(p):
                    items.append({"name": name, "size": os.path.getsize(p)})
    return items


BOOK_BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

# Windows 保留设备名：不能作为目录 / 文件名，否则资源管理器与多数工具无法访问、删除。
# 含 CON.txt 这类带扩展名变体（取首个点号前的主名比对）。
_RESERVED_NAMES = (
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)


def sanitize_book(name):
    """书名清洗：去路径穿越与非法文件名字符；空/超长/保留设备名返回 None。"""
    s = str(name or "").strip().strip(".")
    s = BOOK_BAD_CHARS.sub("_", s)
    s = re.sub(r"\s+", " ", s)
    if not s or s in (".", "..") or len(s) > 80:
        return None
    # Windows 保留设备名（大小写不敏感，含 CON.txt 变体）不可作为目录名
    if s.split(".")[0].lower() in _RESERVED_NAMES:
        return None
    return s


def list_books():
    """data/ 下所有产出过文件的书，按最近修改排序。"""
    books, seen = [], set()
    if os.path.isdir(DATA_DIR):
        for d in sorted(os.listdir(DATA_DIR)):
            p = os.path.join(DATA_DIR, d)
            if not os.path.isdir(p) or d.lower() in seen:
                continue
            ch, dec = book_chapters(d), book_decomposed(d)
            if not (os.path.isfile(ch) or os.path.isfile(dec)):
                continue
            seen.add(d.lower())
            files = [f for f in (ch, dec) if os.path.isfile(f)]
            ch_doc = read_json(ch, {}) if os.path.isfile(ch) else {}
            books.append({
                "name": d,
                "has_chapters": os.path.isfile(ch),
                "has_decomposed": os.path.isfile(dec),
                "n_chapters": len(ch_doc.get("chapters", []) or []),
                "status": str(ch_doc.get("status") or "").strip(),
                "mtime": max(os.path.getmtime(f) for f in files),
            })
    books.sort(key=lambda b: -b["mtime"])
    return books


def resolve_book(q_book):
    """从请求的 book 参数解析书名：单本可缺省。返回 (书名或空串, 错误响应或 None)。"""
    name = sanitize_book(q_book)
    if q_book and not name:
        return None, (400, {"error": f"书名不合法：{q_book}"})
    if name:
        return name, None
    books = list_books()
    if len(books) == 1:
        return books[0]["name"], None
    if not books:
        return "", None
    return None, (400, {"error": "存在多本书，请求必须带 book 参数"})


def book_exists(name):
    """作品是否真实存在（以是否有 chapters.json / decomposed.json 判定）。"""
    if not name:
        return False
    return os.path.isfile(book_chapters(name)) or os.path.isfile(book_decomposed(name))


# ---------------------------------------------------------------- 数据同步（zip）
def any_task_running():
    """是否有任何任务在跑：导入会整体替换作品目录，跑任务时写入会互相覆盖。"""
    with JOB_LOCK:
        if any(j.get("running") for j in JOBS.values()):
            return True
    with PAGE_LOCK:
        return any(t.get("running") for t in PAGE_TASKS.values())


def export_data_zip():
    """把 data/<书名>/ 全部产出打包成 zip，附 manifest.json。

    data/_system（任务记录、用量统计、写作曲线）属于本机状态，不参与跨端同步；
    临时文件与无法导入的扩展名一并跳过，保证「导出 → 另一端导入」永远能原样吃下。
    """
    buf = io.BytesIO()
    books, skipped = [], 0
    with DATA_SYNC_LOCK, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for book in list_books():
            bdir = book_dir(book["name"])
            n = 0
            for dp, dns, fns in os.walk(bdir):
                # 以「.」开头的目录是本机自动备份 / 临时状态，不参与跨端同步
                dns[:] = sorted(d for d in dns if not d.startswith("."))
                for fn in sorted(fns):
                    src = os.path.join(dp, fn)
                    if not os.path.isfile(src):
                        continue
                    if fn.startswith(".") or ".tmp" in fn.lower() \
                            or os.path.splitext(fn)[1].lower() not in DATA_ZIP_EXTS:
                        skipped += 1
                        continue
                    rel = os.path.relpath(src, DATA_DIR).replace(os.sep, "/")
                    z.write(src, rel)
                    n += 1
            books.append({"name": book["name"], "files": n})
        manifest = {
            "app": "墨写", "kind": "mowrite-data", "version": 1,
            "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "books": books, "skipped": skipped,
        }
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
    return buf.getvalue(), manifest


def data_sync_status():
    """数据同步面板的预检：有任务在跑时不应导出 / 导入。"""
    return {"busy": any_task_running(), "books": len(list_books())}


# 导出口令不放在下载 URL 里：先换一张一次性票据，再由下载请求凭票据取口令。
# 票据只存内存、2 分钟过期、用后即焚——避免口令出现在地址栏 / 下载历史里。
_EXPORT_TICKETS = {}
_EXPORT_TICKET_LOCK = threading.Lock()
_EXPORT_TICKET_TTL = 120


def issue_export_ticket(password):
    token = secrets.token_urlsafe(24)
    now = time.time()
    with _EXPORT_TICKET_LOCK:
        for k, (_, exp) in list(_EXPORT_TICKETS.items()):
            if exp < now:
                _EXPORT_TICKETS.pop(k, None)
        _EXPORT_TICKETS[token] = (password, now + _EXPORT_TICKET_TTL)
    return token


def take_export_ticket(token):
    """取走票据里的口令；不存在 / 过期 / 已用过都返回 None。"""
    with _EXPORT_TICKET_LOCK:
        item = _EXPORT_TICKETS.pop(str(token or ""), None)
    if not item or item[1] < time.time():
        return None
    return item[0]


def export_encrypted(password):
    """导出并加密，返回 (加密包字节, manifest, 文件名)。"""
    pwd = securelib.check_password(password)
    raw, manifest = export_data_zip()
    fn = "mowrite-data-" + time.strftime("%Y%m%d-%H%M") + ".mwen"
    return securelib.encrypt(raw, pwd), manifest, fn


def import_data_zip(raw, replace=False):
    """导入入口：与导出互斥，避免读到写了一半的目录。"""
    with DATA_SYNC_LOCK:
        return _import_data_zip(raw, replace)


def _import_data_zip(raw, replace=False):
    """导入数据 zip：逐条校验路径 / 类型，解压到临时目录后再按作品整体替换。

    同名作品会整体覆盖（不是逐文件合并），这样两端数据才是同一份；
    replace=True 时先把现有的作品目录移到 data-backup-<时间>/，可人工回退。
    """
    if not raw:
        raise ValueError("压缩包为空")
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except (zipfile.BadZipFile, OSError):
        raise ValueError("不是合法的 zip 压缩包")
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if not infos:
        raise ValueError("压缩包里没有文件")
    if len(infos) > MAX_DATA_FILES:
        raise ValueError(f"压缩包文件数过多（上限 {MAX_DATA_FILES}）")
    tmp = tempfile.mkdtemp(prefix="mowrite-import-")
    total = 0
    top_map = {}          # 小写名 → 实际作品目录名：Windows 大小写不敏感，必须提前拒绝重名
    try:
        for info in infos:
            name = info.filename.replace("\\", "/")
            if name == "manifest.json":
                continue
            if name.startswith("/") or re.match(r"^[a-zA-Z]:", name) or ".." in name.split("/"):
                raise ValueError(f"压缩包内含非法路径：{name}")
            parts = [p for p in name.split("/") if p]
            if len(parts) < 2 or parts[0].startswith("_"):
                raise ValueError(f"压缩包结构不对（应以作品目录开头）：{name}")
            # 隐藏目录（.backup 等）是本机状态，不接受外部导入，避免覆盖/注入备份
            if any(p.startswith(".") for p in parts[1:]):
                raise ValueError(f"压缩包内含隐藏路径，不允许导入：{name}")
            top = parts[0]
            if sanitize_book(top) != top:
                raise ValueError(f"压缩包里的作品目录名不合法：{top}")
            low = top.lower()
            if top_map.get(low, top) != top:
                raise ValueError(f"压缩包里存在大小写重复的作品目录：{top} 与 {top_map[low]}")
            top_map[low] = top
            if os.path.splitext(name)[1].lower() not in DATA_ZIP_EXTS:
                raise ValueError(f"压缩包内含不支持的文件类型：{name}")
            total += info.file_size
            if total > MAX_DATA_IMPORT:
                raise ValueError(f"解压后体积超过上限（{MAX_DATA_IMPORT // 1024 // 1024}MB）")
            dst = os.path.join(tmp, *parts)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with zf.open(info) as src, open(dst, "wb") as out:
                shutil.copyfileobj(src, out)
        books = sorted(d for d in os.listdir(tmp)
                       if os.path.isdir(os.path.join(tmp, d)))
        if not books:
            if replace:
                raise ValueError("压缩包里没有作品目录，不能做「完全对齐」")
            return {"books": [], "files": 0, "bytes": 0, "backup": ""}
        backup = ""
        if replace and os.path.isdir(DATA_DIR):
            backup = os.path.join(os.path.dirname(DATA_DIR),
                                  "data-backup-" + time.strftime("%Y%m%d-%H%M%S"))
            os.makedirs(backup, exist_ok=True)
            for d in sorted(os.listdir(DATA_DIR)):
                p = os.path.join(DATA_DIR, d)
                if d.startswith("_") or not os.path.isdir(p):
                    continue          # _system 属于本机状态，不进备份也不删除
                shutil.move(p, os.path.join(backup, d))
        os.makedirs(DATA_DIR, exist_ok=True)
        for d in books:
            dst = os.path.join(DATA_DIR, d)
            shutil.rmtree(dst, ignore_errors=True)
            shutil.move(os.path.join(tmp, d), dst)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    _invalidate_outputs()
    return {"books": books, "files": len(infos), "bytes": total, "backup": backup}


def migrate_legacy_data():
    """把旧版单书 data/*.json 一次性迁入 data/<书名>/；幂等，重复启动自动跳过。"""
    legacy = [p for p in (CHAPTERS, DECOMPOSED) if os.path.isfile(p)]
    if not legacy:
        return None
    srcs = list_sources()
    name = "未命名书"
    if len(srcs) == 1:
        name = sanitize_book(os.path.splitext(srcs[0]["name"])[0]) or name
    os.makedirs(book_dir(name), exist_ok=True)
    for p in legacy:
        dst = os.path.join(book_dir(name), os.path.basename(p))
        if os.path.isfile(dst):
            continue   # 目标已存在：不覆盖，保留根文件由用户自行处理
        os.replace(p, dst)
    return name


# ---------- 产出文件清单：只扫描一次 + 短缓存；分页时只对当前页取文件大小 ----------
OUTPUTS_TTL = 3.0            # 秒：列表 / 预览 / 删除会连着请求，避免每次都全盘 listdir
OUTPUTS_MAX_PAGE = 500       # 每页上限，防止前端一次索要上万条又把浏览器撑爆
OUTPUT_PREVIEW_CHARS = 400000  # 预览上限（字符）：超长报告只给前 40 万字 + 下载，避免前端卡死
_out_cache_ts = 0.0        # 上次扫描完成的时间戳；0 表示缓存已失效
_out_cache_items = []      # 扫描结果（不含 size）


def _invalidate_outputs():
    """产出目录有增删后调用（删除文件 / 删书 / 清空），让下次请求重新扫描。"""
    global _out_cache_ts
    _out_cache_ts = 0.0


def _scan_outputs():
    """产出文件清单（不含 size）：data/<书名>/{chapters.json,decomposed.json,review/,manuscript/} + output/<批次>/。

    只做 listdir 与路径拼接，几万个文件也是几十毫秒级；size 留到分页时对当前页按需 stat，
    因此清单再大也不会出现「打开产出页要扫几万次磁盘 + 塞几十 MB JSON 给浏览器」。
    """
    global _out_cache_ts, _out_cache_items
    now = time.time()
    if _out_cache_ts and now - _out_cache_ts < OUTPUTS_TTL:
        return _out_cache_items
    items = []

    def add(name, path, group, book, kind, label):
        items.append({"name": name, "path": path, "group": group, "book": book,
                      "kind": kind, "label": label})

    for b in list_books():
        name = b["name"]
        for f, label in ((book_chapters(name), "章节数据"), (book_decomposed(name), "全书设定")):
            if os.path.isfile(f):
                add(f"{name}/{os.path.basename(f)}",
                    os.path.relpath(f, ROOT).replace("\\", "/"),
                    name, name, "core", label)
        # 设定图谱（storymap.json）也是可单独取用的任务产出，别只在图谱页里能看到
        sm = os.path.join(book_dir(name), "storymap.json")
        if os.path.isfile(sm):
            add(f"{name}/storymap.json", f"data/{name}/storymap.json",
                name, name, "core", "设定图谱（含世界地图）")
        # 改编差异报告（adapt.py 落盘）：只统计结构与命名变化，供发布前人工复核
        rep = os.path.join(book_dir(name), "adapt_report.json")
        if os.path.isfile(rep):
            add(f"{name}/adapt_report.json", f"data/{name}/adapt_report.json",
                name, name, "core", "改编差异报告")
        # AI 审查报告（data/<书名>/review/*）
        d = os.path.join(book_dir(name), "review")
        if os.path.isdir(d):
            for fn in sorted(os.listdir(d), reverse=True):
                if os.path.isfile(os.path.join(d, fn)):
                    add(f"{name}/review/{fn}", f"data/{name}/review/{fn}",
                        name, name, "review", "AI 审查报告")
        # 正文扩写产出（data/<书名>/manuscript/*.txt）
        d = os.path.join(book_dir(name), "manuscript")
        if os.path.isdir(d):
            for fn in sorted(os.listdir(d)):
                if fn.endswith(".txt") and os.path.isfile(os.path.join(d, fn)):
                    add(f"{name}/manuscript/{fn}", f"data/{name}/manuscript/{fn}",
                        name, name, "manuscript", "正文扩写")
    # 旧版单书时代留在根目录的数据
    for f in (CHAPTERS, DECOMPOSED):
        if os.path.isfile(f):
            add(os.path.basename(f), os.path.relpath(f, ROOT).replace("\\", "/"),
                "旧根数据", "", "core", "旧数据")
    # 历史批次（output/<批次>/）：一个批次算一个来源
    if os.path.isdir(OUT_DIR):
        for b in sorted(os.listdir(OUT_DIR), reverse=True):
            d = os.path.join(OUT_DIR, b)
            if not os.path.isdir(d):
                continue
            for fn in sorted(os.listdir(d)):
                if os.path.isfile(os.path.join(d, fn)):
                    add(f"{b}/{fn}", f"output/{b}/{fn}", b, "", "batch", "历史批次")
    _out_cache_items = items
    _out_cache_ts = now
    return _out_cache_items


def _with_size(item):
    out = dict(item)
    try:
        out["size"] = os.path.getsize(os.path.join(ROOT, *item["path"].split("/")))
    except OSError:
        out["size"] = 0
    return out



def query_outputs(q="", group="", book="", kind="", page="0", page_size="100"):
    """按书名 / 类别 / 分组 / 关键词过滤产出清单，page>0 时只返回该页（page<=0 为全量，兼容书内页面）。

    group 即来源：书名（data/<书名>/…）或旧批次名（output/<批次>/…），旧根数据归为「旧根数据」。
    groups 一并返回该范围内的全部来源，前端下拉不必再单独拉一份全量清单。
    页码越界自动回退到末页，删空末页后不会停在空白表格上。
    """
    book, kind, group = (book or "").strip(), (kind or "").strip(), (group or "").strip()
    kl = (q or "").strip().lower()
    items = _scan_outputs()
    scope = [i for i in items
             if (not book or i["book"] == book) and (not kind or i["kind"] == kind)]
    groups = sorted({i["group"] for i in scope})
    rows = [i for i in scope
            if (not group or i["group"] == group)
            and (not kl or kl in i["name"].lower() or kl in i["path"].lower())]
    total = len(rows)
    try:
        page = int(page or 0)
    except (TypeError, ValueError):
        page = 0
    if page <= 0:
        return {"files": [_with_size(i) for i in rows], "total": total, "groups": groups}
    try:
        page_size = int(page_size or 100)
    except (TypeError, ValueError):
        page_size = 100
    page_size = max(1, min(page_size, OUTPUTS_MAX_PAGE))
    page_count = max(1, (total + page_size - 1) // page_size)
    page = min(page, page_count)
    start = (page - 1) * page_size
    return {"files": [_with_size(i) for i in rows[start:start + page_size]],
            "total": total, "page": page, "page_size": page_size,
            "page_count": page_count, "groups": groups}


def book_stats():
    """工作台聚合数据：每本书的章节 / 设定 / 正文 / 审查统计 + 近 7 日码字曲线。"""
    from datetime import date, timedelta

    def _fmt_ts(ts):
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))

    today = date.today()
    out = []
    for b in list_books():
        name = b["name"]
        ch = read_json(book_chapters(name), {}) if b["has_chapters"] else {}
        fields, cards, factions = parse_story_bible(ch.get("story_bible", "") or "")
        chs = ch.get("chapters", []) or []
        # 正文扩写产出：字数统计 + 按文件修改日聚合的近 7 日码字
        mdir = os.path.join(book_dir(name), "review")
        n_reviews = 0
        if os.path.isdir(mdir):
            n_reviews = sum(1 for fn in os.listdir(mdir)
                            if fn.endswith((".json", ".md", ".html"))
                            and os.path.isfile(os.path.join(mdir, fn)))
        mdir = os.path.join(book_dir(name), "manuscript")
        files, per_day = [], {}
        if os.path.isdir(mdir):
            for fn in sorted(os.listdir(mdir)):
                fp = os.path.join(mdir, fn)
                if not (os.path.isfile(fp) and fn.endswith(".txt")):
                    continue
                try:
                    with open(fp, encoding="utf-8", errors="replace") as f:
                        n = len(f.read())
                except OSError:
                    n = 0
                mt = os.path.getmtime(fp)
                files.append({"name": fn, "chars": n, "mtime": _fmt_ts(mt)})
                d = date.fromtimestamp(mt).isoformat()
                per_day[d] = per_day.get(d, 0) + n
        week = [{"date": (today - timedelta(days=i)).isoformat(),
                 "chars": per_day.get((today - timedelta(days=i)).isoformat(), 0)}
                for i in range(6, -1, -1)]
        def _cno(c):
            # 章号优先 no 字段，其次从 chapter_id / id / title 中提取数字（如 "第1章"）
            for k in ("no", "chapter_id", "id", "title"):
                m = re.search(r"\d+", str(c.get(k) or ""))
                if m:
                    return int(m.group())
            return 0
        last_no = max((_cno(c) for c in chs), default=0)
        last_ch = max(chs, key=_cno) if chs else None
        # 作品简介：story_bible.synopsis，为空回退 decomposed.json 的 book_summary（与审查模块同逻辑）
        book_summary = ""
        try:
            with open(book_decomposed(name), encoding="utf-8") as f:
                book_summary = str(json.load(f).get("book_summary") or "").strip()
        except (OSError, ValueError):
            pass
        synopsis = str(fields.get("synopsis") or "").strip() or book_summary
        # 章号 → 成稿信息（文件名 <NNN>.txt），供详情页目录展示每章字数/时间
        ms_by_no = {}
        for f in files:
            stem = f["name"][:-4]
            if not stem.isdigit():
                continue
            # 取成稿首行作为章名（用于详情页目录回显，去掉 Markdown 标题符号）
            first = ""
            try:
                with open(os.path.join(mdir, f["name"]), encoding="utf-8", errors="replace") as ff:
                    for line in ff:
                        s = line.strip().lstrip("#").strip()
                        if s:
                            first = s[:60]
                            break
            except OSError:
                pass
            ms_by_no[str(int(stem))] = {"chars": f["chars"], "mtime": f["mtime"], "title": first}
        out.append({
            **b,
            "title": (chs[0].get("book_title") if chs and isinstance(chs[0], dict) else None)
                     or (ch.get("book_title") or name),
            "n_cards": len(cards), "n_factions": len(factions),
            "n_items": len([it for it in (ch.get("items") or []) if isinstance(it, dict)]),
            "n_chapters": len(chs), "last_chapter_no": last_no,
            "last_chapter_title": (last_ch or {}).get("title") or "",
            "status": str(ch.get("status") or "").strip() or fields.get("status") or "",
            "author": str(ch.get("author") or "").strip(),
            "synopsis": synopsis,
            "has_cover": cover_path(name) is not None,
            "n_manuscripts": len(files), "manuscript_chars": sum(f["chars"] for f in files),
            "ms_by_no": ms_by_no,
            "n_reviews": n_reviews, "week": week,
            "mtime_text": _fmt_ts(b["mtime"]),
        })
    return {"books": out, "sources": len(list_sources())}


COVER_EXTS = ("png", "jpg", "jpeg", "webp")


def cover_path(name):
    """书封面图片路径 data/<书名>/cover.{png,jpg,jpeg,webp}，不存在返回 None。"""
    d = book_dir(name)
    for ext in COVER_EXTS:
        p = os.path.join(d, "cover." + ext)
        if os.path.isfile(p):
            return p
    return None


def save_book_author(name, author):
    """作者名写回 chapters.json：封面、作品详情共用一处，避免前端各存一份。"""
    p = book_chapters(name)
    if not os.path.isfile(p):
        return False
    data = read_json(p, {})
    if not isinstance(data, dict):
        return False
    data["author"] = author
    data.setdefault("chapters", [])
    write_json(p, data)
    return True


def resolve_output(path):
    """只允许读取产出清单里出现过的文件，防目录穿越（清单走 3 秒缓存，预览不再每次全盘扫描）。"""
    p = (path or "").replace("\\", "/")
    # 只可能是 data/、output/ 或旧版根目录数据；其余直接拒绝，别为无效路径触发重扫
    if not p or ".." in p.split("/") or not (p.startswith(("data/", "output/"))
                                             or p in ("chapters.json", "decomposed.json")):
        return None
    if p not in {i["path"] for i in _scan_outputs()}:
        # 缓存期内刚生成的产出（扩写 / 审查刚写完就点预览）：强制重扫一次再判定，
        # 否则会白等 3 秒才能打开新文件
        _invalidate_outputs()
        if p not in {i["path"] for i in _scan_outputs()}:
            return None
    full = os.path.join(ROOT, *p.split("/"))
    return full if os.path.isfile(full) else None


def clear_outputs(dry=False):
    """清空全部产出：删除 data/ 下所有书目录 + output/ 下所有历史批次。dry=True 只统计。"""
    books = ([d for d in os.listdir(DATA_DIR) if os.path.isdir(os.path.join(DATA_DIR, d))]
             if os.path.isdir(DATA_DIR) else [])
    batches = ([b for b in os.listdir(OUT_DIR) if os.path.isdir(os.path.join(OUT_DIR, b))]
               if os.path.isdir(OUT_DIR) else [])
    if not dry:
        for b in batches:
            shutil.rmtree(os.path.join(OUT_DIR, b), ignore_errors=True)
        for d in books:
            shutil.rmtree(os.path.join(DATA_DIR, d), ignore_errors=True)
        _invalidate_outputs()
    return {"batches": len(batches), "books": len(books)}


def safe_source_name(name):
    name = os.path.basename((name or "").strip())
    if not re.fullmatch(r"[^\\/:*?\"<>|\r\n]{1,120}\.(txt|md|markdown)", name, re.I):
        return None
    if name.lower().startswith(RESERVED_PREFIX):
        return None
    return name


# ---------------------------------------------------------------- 命令拼装
def build_cmd(stage, a):
    if stage == "decompose":
        if FROZEN:
            # 打包后没有独立 python：用自身 exe 的子模式跑拆解（desktop_app.py 分发）
            cmd = [sys.executable, "--decompose-child"]
        else:
            cmd = [sys.executable, "-u", os.path.join(SRC_DIR, "decompose.py")]
        cmd += ["--mode", a.get("mode") or "outline"]
        # 页面由前端按「拆解 → 改编」两段分别发起任务，拆解子进程不能自己再串一次改编
        cmd += ["--no-adapt"]
        if a.get("source"):
            cmd += ["--source", a["source"]]
        if a.get("limit"):
            cmd += ["--limit", str(a["limit"])]
        if a.get("max_chars"):
            cmd += ["--max-chars", str(a["max_chars"])]
        if a.get("chunk_chars"):
            cmd += ["--chunk-chars", str(a["chunk_chars"])]
        if a.get("chunk_chapters"):
            cmd += ["--chunk-chapters", str(a["chunk_chapters"])]
        if a.get("model"):
            cmd += ["--model", a["model"]]
        if a.get("base_url"):
            cmd += ["--base-url", a["base_url"]]
        if a.get("dry_run"):
            cmd += ["--dry-run"]   # 试跑不落盘，无需目标书名
        else:
            # 输出目录由服务端决定：显式 book 优先，否则取源文件名 stem
            book = sanitize_book(a.get("book") or "") or \
                (sanitize_book(os.path.splitext(a["source"])[0]) if a.get("source") else None)
            if not book:
                raise ValueError("无法确定目标书名：请选择源文件或在高级选项里指定书名")
            cmd += ["--out-decomposed", f"data/{book}/decomposed.json",
                    "--out-chapters", f"data/{book}/chapters.json"]
        return cmd
    if stage == "adapt":
        book = sanitize_book(a.get("book") or "")
        out_book = sanitize_book(a.get("out_book") or "")   # 可留空：由模型生成书名
        if not book:
            raise ValueError("请选择已拆解的源书")
        if out_book and out_book == book:
            raise ValueError("新书名不能与源书名相同（会覆盖拆解产出）")
        if not os.path.isfile(book_decomposed(book)):
            raise ValueError(f"源书「{book}」没有拆解产出，请先运行拆解")
        if FROZEN:
            cmd = [sys.executable, "--adapt-child"]
        else:
            cmd = [sys.executable, "-u", os.path.join(SRC_DIR, "adapt.py")]
        cmd += ["--book", book]
        if out_book:
            cmd += ["--out-book", out_book]
        if a.get("style"):
            cmd += ["--style", a["style"]]
        for key, flag in (("target_chapters", "--target-chapters"),
                          ("sequel_chapters", "--sequel-chapters")):
            v = a.get(key)
            if v in (None, "", 0):
                continue
            try:
                iv = int(v)
            except (TypeError, ValueError):
                raise ValueError(f"「{'目标章数' if key == 'target_chapters' else '续写章数'}」须为整数：{v!r}")
            if iv > 0:
                cmd += [flag, str(iv)]
        if a.get("model"):
            cmd += ["--model", a["model"]]
        if a.get("base_url"):
            cmd += ["--base-url", a["base_url"]]
        if a.get("dry_run"):
            cmd += ["--dry-run"]
        return cmd
    if stage == "expand":
        book = sanitize_book(a.get("book") or "")
        if not book:
            raise ValueError("请选择书")
        if not os.path.isfile(book_chapters(book)):
            raise ValueError(f"书「{book}」没有章节数据，请先拆解/编辑章节")
        if FROZEN:
            cmd = [sys.executable, "--expand-child"]
        else:
            cmd = [sys.executable, "-u", os.path.join(SRC_DIR, "expand.py")]
        cmd += ["--book", book]
        if a.get("chapters"):
            cmd += ["--chapters", str(a["chapters"])]
        if a.get("skip_existing"):
            cmd += ["--skip-existing"]   # 断点续跑：跳过已有非空成稿的章节
        if a.get("no_memory"):
            cmd += ["--no-memory"]
        if a.get("model"):
            cmd += ["--model", a["model"]]
        if a.get("base_url"):
            cmd += ["--base-url", a["base_url"]]
        if a.get("temperature"):
            cmd += ["--temperature", str(a["temperature"])]
        if a.get("style"):
            cmd += ["--style", str(a["style"])]
        return cmd
    if stage == "storymap":
        # 设定图谱：消费拆解产出，生成人物关系 / 世界观 / 关键道具 / 一致性
        book = sanitize_book(a.get("book") or "")
        if not book:
            raise ValueError("请选择书")
        # 只要有章节数据就能画图（decomposed 缺失时用 chapters.json 兜底）
        if not (os.path.isfile(book_decomposed(book)) or os.path.isfile(book_chapters(book))):
            raise ValueError(f"书「{book}」没有拆解产出，请先拆解")
        if FROZEN:
            cmd = [sys.executable, "--storymap-child"]
        else:
            cmd = [sys.executable, "-u", os.path.join(SRC_DIR, "storymap.py")]
        cmd += ["--book", book]
        if a.get("model"):
            cmd += ["--model", a["model"]]
        if a.get("base_url"):
            cmd += ["--base-url", a["base_url"]]
        if a.get("dry_run"):
            cmd += ["--dry-run"]
        return cmd
    raise ValueError(f"未知任务类型：{stage}（当前支持 decompose：拆解 / adapt：改编 /"
                     f" expand：正文扩写 / storymap：设定图谱）")


# ---------------------------------------------------------------- 任务执行
def clean_origin(raw):
    """任务是在哪个页面发起的（前端上报的 hash 路由）。

    任务中心 / 悬浮条点「打开对应页面」时按它跳回去，而不是一律跳到该阶段的固定页。
    只接受站内相对路径，避免被写成外链或 javascript:。"""
    s = str(raw or "").strip()
    if not s or len(s) > 300:
        return ""
    if not s.startswith("/") or s.startswith("//") or "://" in s:
        return ""
    return s


def job_label(stage, args):
    """任务在任务中心里显示的名字：书名在前，「《书》 · 做了什么」，同一阶段多个任务也能区分。"""
    book = sanitize_book((args or {}).get("book") or "") or ""
    base = JOB_LABEL.get(stage, stage or "任务")
    if stage == "adapt":
        out = sanitize_book((args or {}).get("out_book") or "") or ""
        if book and out:
            return f"《{book}》→《{out}》 · {base}"
    return f"《{book}》 · {base}" if book else base


def job_output_book(job):
    """任务最终会产出的书名：改编是 out_book，其余是 book（供前端跑完自动选中）。"""
    args = job.get("args") or {}
    if job.get("stage") == "adapt":
        return sanitize_book(args.get("out_book") or "") or job.get("book") or ""
    return job.get("book") or ""


def _trim_jobs():
    """只保留最近结束的任务（运行中的永不丢），避免日志占内存。"""
    if len(JOBS) <= MAX_JOBS_KEPT:
        return
    for jid in sorted(JOBS, key=lambda k: JOBS[k]["created_at"]):
        if len(JOBS) <= MAX_JOBS_KEPT:
            break
        if not JOBS[jid]["running"]:
            JOBS.pop(jid, None)


def new_job(stage, args, api_key="", origin=""):
    """登记一个新任务并返回它（调用方随后 spawn）。"""
    with JOB_LOCK:
        JOB_SEQ[0] += 1
        book = sanitize_book((args or {}).get("book") or "") or ""
        job = {
            "id": f"j{JOB_SEQ[0]}", "stage": stage,
            "label": job_label(stage, args) + ("" if api_key else "（本地）"),
            "book": book,
            "out_book": job_output_book({"stage": stage, "args": args, "book": book}),
            "args": args or {}, "log": [], "queue": [], "running": True, "code": None,
            "error": None, "stopped": False, "proc": None, "api_key": api_key,
            "created_at": time.time(), "finished_at": 0.0, "origin": origin or "",
        }
        JOBS[job["id"]] = job
        _trim_jobs()
        return job


def job_public(job, since=0):
    with JOB_LOCK:
        return {
            "id": job["id"], "stage": job["stage"], "label": job["label"],
            "book": job["book"], "out_book": job.get("out_book") or "",
            "running": job["running"], "code": job["code"], "error": job["error"],
            "stopped": job["stopped"], "queued": [s["stage"] for s in job["queue"]],
            "interrupted": bool(job.get("interrupted")),
            "resumable": (not job["running"]) and bool(job.get("interrupted") or job["stopped"]
                                                       or (job["code"] not in (0, None))),
            "total": len(job["log"]), "lines": job["log"][since:],
            "created_at": job["created_at"], "finished_at": job["finished_at"],
            "origin": job.get("origin") or "",
        }


def job_summary(job):
    with JOB_LOCK:
        return {
            "id": job["id"], "stage": job["stage"], "label": job["label"],
            "book": job["book"], "out_book": job.get("out_book") or "",
            "running": job["running"], "code": job["code"], "error": job["error"],
            "stopped": job["stopped"], "total": len(job["log"]),
            "interrupted": bool(job.get("interrupted")),
            # 中断 / 失败 / 被停的批量扩写可恢复（跳过已有成稿续跑）
            "resumable": (not job["running"]) and bool(job.get("interrupted") or job["stopped"]
                                                       or (job["code"] not in (0, None))),
            "created_at": job["created_at"], "finished_at": job["finished_at"],
            "origin": job.get("origin") or "",
        }


def _job_finish(job, code):
    """任务收尾：记退出码、按队列串下一阶段、置结束状态（子进程与进程内共用）。"""
    with JOB_LOCK:
        job["log"].append(f"[{job['stage']}] 退出码 {code}")
        job["code"] = code
        nxt = None
        if code == 0 and job["queue"]:
            nxt = job["queue"].pop(0)
        chained = False
        if nxt:
            try:
                spawn(job, nxt["stage"], nxt.get("args", {}))
                chained = True
            except Exception as e:       # 启动失败必须收尾，否则前端永远停在「运行中」
                job["log"].append(f"[x] 启动下一阶段「{nxt['stage']}」失败：{e}")
                job["code"] = 1
        if not chained:
            job["running"] = False
            job["proc"] = None
            job["finished_at"] = time.time()


def _child_argv(cmd):
    """从 build_cmd 的结果里剥出模块参数（去掉 python、-u、脚本路径 / --xxx-child）。"""
    a = list(cmd[1:])
    if a and a[0] == "-u":
        a.pop(0)
    if a and a[0].startswith("--") and a[0].endswith("-child"):
        a.pop(0)
    elif a and str(a[0]).lower().endswith(".py"):
        a.pop(0)
    return a


def _inproc_line(job, line):
    """进程内任务的日志回调：写入任务日志，并响应「停止」。"""
    with JOB_LOCK:
        job["log"].append(line)
        if len(job["log"]) > MAX_LOG_LINES:
            del job["log"][:len(job["log"]) - MAX_LOG_LINES]
        if line.startswith("[OUTPUT_BOOK] "):
            name = sanitize_book(line.split("]", 1)[1].strip())
            if name:
                job["out_book"] = name
        stopped = bool(job.get("stopped"))
    if stopped:
        # 进程内跑的是普通函数调用，没法 terminate；在下一行日志处抛出即可中断
        raise KeyboardInterrupt("stopped")


def _run_inproc(job, stage, argv, env):
    try:
        code = runner.run_module(stage, argv, env, on_line=lambda ln: _inproc_line(job, ln))
    except BaseException:
        import traceback
        traceback.print_exc()
        code = 1
    _job_finish(job, code)


def pump(job, proc):
    try:
        for line in proc.stdout:
            with JOB_LOCK:
                job["log"].append(line.rstrip("\n"))
                if len(job["log"]) > MAX_LOG_LINES:
                    del job["log"][:len(job["log"]) - MAX_LOG_LINES]
                # 改编任务的新书名由模型生成时，子进程用 [OUTPUT_BOOK] 回传真名：
                # 实时更新任务产出书名，前端「完成后选中新书」才不会指回源书
                if line.startswith("[OUTPUT_BOOK] "):
                    name = sanitize_book(line.split("]", 1)[1].strip())
                    if name:
                        job["out_book"] = name
    finally:
        _job_finish(job, proc.wait())


def spawn(job, stage, args):
    """启动任务（桌面端起子进程，手机端在后台线程里进程内执行）。"""
    cmd = build_cmd(stage, args)
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # 用量统计：子进程里的模型调用按阶段 / 书记账（deepseek_common 读这两个环境变量）
    env["MOBIT_STAGE"] = stage or ""
    env["MOBIT_BOOK"] = job.get("book") or ""
    if job["api_key"]:
        env["DEEPSEEK_API_KEY"] = job["api_key"]
    job["stage"] = stage
    job["label"] = job_label(stage, args)
    job["out_book"] = job_output_book(job)
    job["log"].append(f"$ {' '.join(cmd)}")
    if runner.IN_PROCESS:
        # 手机端：没有独立 python 可执行文件，改为后台线程里调用模块 main()
        job["proc"] = None
        argv = _child_argv(cmd)
        threading.Thread(target=_run_inproc, args=(job, stage, argv, env), daemon=True).start()
        return
    flags = subprocess.CREATE_NO_WINDOW if (FROZEN and sys.platform == "win32") else 0
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", env=env, bufsize=1,
                            creationflags=flags)
    job["proc"] = proc
    threading.Thread(target=pump, args=(job, proc), daemon=True).start()


# ---------------------------------------------------------------- 新增能力（记忆 / 历史 / 码字 / 体检）
def apply_stage_conf(stage, args):
    """分阶段模型绑定：请求没显式带 model / base_url 时，套用设置页里该阶段的绑定。
    显式传参永远优先——页面上的「模型」输入框写了值就听页面的。"""
    conf = studiolib.stage_conf(stage)
    args = dict(args or {})
    if not conf:
        return args
    if not str(args.get("model") or "").strip() and conf.get("model"):
        args["model"] = conf["model"]
    if not str(args.get("base_url") or "").strip() and conf.get("base_url"):
        args["base_url"] = conf["base_url"]
    if args.get("temperature") in (None, "") and conf.get("temperature") not in (None, ""):
        args["temperature"] = conf["temperature"]
    return args


def resolve_stage_key(stage, mode="", scope=""):
    """把「大阶段 + 操作模式 + 作用域」解析成可绑定模型的工序 key。

    例：expand + rewrite + selection → expand_selection；expand + outline → expand_outline。
    这样「选区操作用千问、初稿用 DeepSeek、审查用 ChatGPT」可以各绑各的。"""
    stage = (stage or "").strip()
    if stage != "expand":
        return stage
    if scope == "selection":
        return "expand_selection"
    mode = (mode or "outline").strip().lower()
    key = f"expand_{mode}"
    return key if key in studiolib.BIND_STAGES else "expand_outline"


def build_memory_block(book, ch):
    """跨章记忆检索：组装【前文记忆】块。返回 (文本, 说明)；失败 / 关闭时返回 ("", 原因)。"""
    try:
        mc = studiolib.memory_conf()
        if not mc["enabled"]:
            return "", "记忆检索已在设置中关闭"
        import memory as memlib
        text = memlib.build_context(book, ch, top_k=mc["top_k"], max_chars=mc["max_chars"])
        return text, (f"前文记忆 {len(text)} 字" if text else "暂无可用的前文记忆")
    except Exception as e:  # noqa —— 记忆是增强项，检索失败绝不能挡正文生成
        return "", f"记忆检索失败（已忽略）：{e}"


def format_review_issues(book, chapter_no, limit=12):
    """读该章最近一次审查报告，把问题整理成「必须修复」指令块（审查→改写闭环用）。"""
    saved = load_review_result(book, chapter_no)
    result = (saved or {}).get("result")
    if not result:
        return "", 0
    issues = result.get("issues") or []
    if not issues:
        return "", 0
    order = {"高": 0, "中": 1, "低": 2}
    issues = sorted(issues, key=lambda it: order.get(it.get("severity"), 1))[:limit]
    lines = ["【必须修复的问题】（来自最近一次 AI 审查，逐条落实，不得遗漏；"
             "修复时保持情节事实、人物与设定不变）："]
    for i, it in enumerate(issues, 1):
        label = it.get("type_label") or it.get("type") or "问题"
        sev = it.get("severity") or ""
        quote = (it.get("quote") or "")[:60]
        reason = (it.get("reason") or "")[:120]
        fix = (it.get("fix") or it.get("suggest") or "")
        advice = ((it.get("advice") or {}).get("positive") or "")[:80]
        line = f"{i}. [{label}{('/' + sev) if sev else ''}]"
        if quote:
            line += f"「{quote}」"
        if reason:
            line += f"：{reason}"
        if fix:
            line += f"（改法：{fix}）"
        elif advice:
            line += f"（建议：{advice}）"
        lines.append(line)
    return "\n".join(lines), len(issues)


WRITING_FILE = os.path.join(DATA_DIR, "_system", "writing.json")


def _record_writing(book, old_len, new_len):
    """码字统计：正文保存 / 生成落盘时记「今日新增字数」（只记增量，改写变短不扣）。"""
    delta = int(new_len or 0) - int(old_len or 0)
    if not book or delta <= 0:
        return
    try:
        data = read_json(WRITING_FILE, {})
        if not isinstance(data, dict):
            data = {}
        day = time.strftime("%Y-%m-%d")
        data.setdefault(day, {})
        data[day][book] = int(data[day].get(book) or 0) + delta
        # 只留最近 90 天
        for k in sorted(data.keys())[:-90]:
            data.pop(k, None)
        write_json(WRITING_FILE, data)
    except Exception:  # noqa
        pass


def writing_stats(book=""):
    """码字统计：今日 / 近 7 日新增字数 + 目标进度。目标在设置页（studio.daily_goal）。"""
    from datetime import date, timedelta
    data = read_json(WRITING_FILE, {})
    if not isinstance(data, dict):
        data = {}
    goal = int(studiolib.load().get("daily_goal") or 0)
    today = date.today().isoformat()

    def _day(d):
        row = data.get(d) or {}
        if book:
            return int(row.get(book) or 0)
        return sum(int(v or 0) for v in row.values())

    week = [{"date": (today and (date.today() - timedelta(days=i)).isoformat()),
             "chars": _day((date.today() - timedelta(days=i)).isoformat())}
            for i in range(6, -1, -1)]
    today_chars = _day(today)
    return {"goal": goal, "today": today_chars,
            "progress": (round(today_chars / goal, 3) if goal > 0 else None),
            "week": week,
            "streak": _streak(data, book)}


def _streak(data, book):
    """连续达标天数（有码字就算一天；从今天往回数）。"""
    from datetime import date, timedelta
    n = 0
    d = date.today()
    while True:
        row = data.get(d.isoformat()) or {}
        v = int(row.get(book) or 0) if book else sum(int(x or 0) for x in row.values())
        if v <= 0:
            break
        n += 1
        d -= timedelta(days=1)
        if n > 3650:
            break
    return n


def batch_review_worker(t, mod, book, checks, api_key, model, base_url, incremental, top_n):
    """全书体检：对本书所有已成稿章节逐章跑审查，汇总出一张全书问题清单。

    incremental=True 时跳过「报告比正文新」的章节（体检过的没改过就不用再花钱）。
    每章之间检查停止标记；结果写 data/<书>/review/batch_<时间戳>.json/.md。"""
    import datetime as _dt
    usagelib.set_context(stage="review", book=book)

    def log(m):
        page_log(t, m)

    def stopped():
        with PAGE_LOCK:
            return t.get("token") is None or bool(t["stop"])

    mdir = os.path.join(book_dir(book), "manuscript")
    rdir = os.path.join(book_dir(book), "review")
    files = []
    if os.path.isdir(mdir):
        for fn in sorted(os.listdir(mdir)):
            if fn.endswith(".txt") and fn[:-4].isdigit():
                files.append((int(fn[:-4]), os.path.join(mdir, fn)))
    if not files:
        raise ValueError(f"《{book}》还没有任何成稿章节，请先生成正文")

    chapters_out, n_skip = [], 0
    log(f"[体检] 《{book}》共 {len(files)} 章成稿；检查项：{'、'.join(checks)}")
    for no, fp in files:
        if stopped():
            log("[!] 已停止（已完成的章节结果保留）")
            break
        if incremental:
            slug = review_slug(no)
            try:
                reps = [x for x in os.listdir(rdir)
                        if x.startswith(slug + "_") and x.endswith(".json")] if os.path.isdir(rdir) else []
            except OSError:
                reps = []
            if reps:
                newest = max(os.path.getmtime(os.path.join(rdir, x)) for x in reps)
                if newest >= os.path.getmtime(fp):
                    n_skip += 1
                    log(f"[跳过] 第 {no} 章（已有比正文新的审查报告，增量模式不重跑）")
                    continue
        log(f"[{len(chapters_out) + n_skip + 1}/{len(files)}] 正在体检第 {no} 章…")
        try:
            with open(fp, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as e:
            log(f"[!] 第 {no} 章读取失败：{e}")
            continue
        try:
            usagelib.set_context(stage="review", book=book, chapter_no=no)
            res = mod.run_review(book=book, chapter_no=str(no), chapter_text=text,
                                 checks=checks, model=model or None, base_url=base_url or None,
                                 api_key=api_key or "", top_n=3, advice_scope="ai",
                                 on_log=None, should_stop=stopped)
        except mod.Stopped:
            log("[!] 已停止（已完成的章节结果保留）")
            break
        except Exception as e:  # noqa —— 单章失败不拖垮全书
            log(f"[x] 第 {no} 章体检失败：{e}")
            chapters_out.append({"no": no, "error": str(e)})
            continue
        issues = res.get("issues") or []
        n_high = sum(1 for it in issues if it.get("severity") == "高")
        chapters_out.append({
            "no": no, "chars": (res.get("meta") or {}).get("chars") or len(text),
            "n_issues": len(issues), "n_high": n_high,
            "theme": (res.get("theme") or {}).get("level") or "",
            "top_issues": [{"type": it.get("type_label") or it.get("type"),
                            "severity": it.get("severity") or "",
                            "reason": (it.get("reason") or "")[:120],
                            "quote": (it.get("quote") or "")[:60]}
                           for it in issues[:3]],
        })
        log(f"[✓] 第 {no} 章：{len(issues)} 条问题（高 {n_high}）")

    done = [c for c in chapters_out if not c.get("error")]
    report = {
        "book": book, "ts": time.time(),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "checks": checks, "incremental": bool(incremental),
        "n_chapters": len(files), "n_done": len(done), "n_skipped": n_skip,
        "total_issues": sum(c.get("n_issues") or 0 for c in done),
        "total_high": sum(c.get("n_high") or 0 for c in done),
        "chapters": chapters_out,
    }
    os.makedirs(rdir, exist_ok=True)
    stem = mod.unique_report_stem(rdir, "batch_" + _dt.datetime.now().strftime("%Y%m%d-%H%M%S"))
    jp = os.path.join(rdir, stem + ".json")
    write_json(jp, report)
    lines = [f"# 《{book}》全书体检报告", "",
             f"- 时间：{report['created_at']}", f"- 章节：{len(done)} 章已检 / {n_skip} 章跳过 / 共 {len(files)} 章",
             f"- 问题：共 {report['total_issues']} 条（高严重度 {report['total_high']} 条）", "",
             "| 章节 | 字数 | 问题数 | 高严重度 | 主题偏离 | Top 问题 |", "| --- | --- | --- | --- | --- | --- |"]
    for c in chapters_out:
        if c.get("error"):
            lines.append(f"| 第{c['no']}章 | - | - | - | - | 体检失败：{c['error']} |")
            continue
        top = "；".join(f"[{i['severity']}] {i['reason']}" for i in c.get("top_issues") or []) or "—"
        lines.append(f"| 第{c['no']}章 | {c.get('chars', 0)} | {c['n_issues']} | {c['n_high']} | {c.get('theme') or '—'} | {top} |")
    mp = os.path.join(rdir, stem + ".md")
    with open(mp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with PAGE_LOCK:
        if t.get("token") is not None:
            t.update(result=report, running=False, error=None, stopped=False,
                     finished_at=time.time(),
                     files={"json": os.path.relpath(jp, ROOT).replace("\\", "/"),
                            "md": os.path.relpath(mp, ROOT).replace("\\", "/")})
    log(f"[完成] 全书体检：{len(done)} 章 / 共 {report['total_issues']} 条问题"
        f"（高 {report['total_high']}）；报告已写入 review/{stem}.md")
    _invalidate_outputs()


def latest_batch_report(book):
    """读本书最近一次全书体检报告（供界面打开 / 重启后回看）。"""
    rdir = os.path.join(book_dir(book), "review")
    try:
        names = [n for n in os.listdir(rdir) if n.startswith("batch_") and n.endswith(".json")]
    except OSError:
        return None
    if not names:
        return None
    names.sort(key=lambda n: os.path.getmtime(os.path.join(rdir, n)), reverse=True)
    return read_json(os.path.join(rdir, names[0]), None)


def latest_signing_report(book):
    """读本书最近一次签约预审报告（文件名前缀 signing_，与单章 / 全书体检区分）。"""
    rdir = os.path.join(book_dir(book), "review")
    try:
        names = [n for n in os.listdir(rdir) if n.startswith("signing_") and n.endswith(".json")]
    except OSError:
        return None
    if not names:
        return None
    names.sort(key=lambda n: os.path.getmtime(os.path.join(rdir, n)), reverse=True)
    return read_json(os.path.join(rdir, names[0]), None)


REVIEW_REPORT_KINDS = {"batch": "batch_", "signing": "signing_"}


def list_review_reports(book, kind):
    """作品级报告历史：review/ 下同前缀的报告按时间倒序，带摘要供弹窗的历史列表回显。"""
    prefix = REVIEW_REPORT_KINDS[kind]
    rdir = os.path.join(book_dir(book), "review")
    try:
        names = [n for n in os.listdir(rdir) if n.startswith(prefix) and n.endswith(".json")]
    except OSError:
        return []
    out = []
    for n in names:
        p = os.path.join(rdir, n)
        data = read_json(p, {}) or {}
        ts = os.path.getmtime(p)
        item = {
            "file": n[:-5], "mtime": ts,
            "created_at": str(data.get("created_at") or data.get("created")
                              or time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))),
        }
        if kind == "batch":
            item.update({
                "n_chapters": to_int(data.get("n_chapters"), 0),
                "n_done": to_int(data.get("n_done"), 0),
                "n_skipped": to_int(data.get("n_skipped"), 0),
                "total_issues": to_int(data.get("total_issues"), 0),
                "total_high": to_int(data.get("total_high"), 0),
                "incremental": bool(data.get("incremental")),
            })
        else:
            issues = data.get("issues") or []
            item.update({
                "verdict": str(data.get("verdict") or ""),
                "chars": to_int(data.get("chars"), 0),
                "window_chapters": to_int(data.get("window_chapters"), 0),
                "n_issues": len(issues),
                "n_high": sum(1 for x in issues if str(x.get("sev") or "") == "高"),
            })
        out.append(item)
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return out


def read_review_report(book, kind, stem):
    """读指定历史报告；stem 只接受 review/ 下该前缀的裸文件名，挡住路径穿越。"""
    prefix = REVIEW_REPORT_KINDS[kind]
    s = str(stem or "").strip()
    if not re.fullmatch(re.escape(prefix) + r"[\w.-]+", s) or ".." in s:
        raise ValueError("报告文件名不合法")
    p = os.path.join(book_dir(book), "review", s + ".json")
    if not os.path.isfile(p):
        raise ValueError("报告不存在（可能已被删除或改名）")
    return read_json(p, None)


def signing_worker(t, mod, book, model, base_url, api_key):
    """签约预审线程：跨章扫前 2 万字，写回约定与 review_worker 一致（先验 token 再落盘）。"""
    usagelib.set_context(stage="review", book=book, chapter_no="签约预审")

    def log(msg):
        page_log(t, msg)

    def should_stop():
        with PAGE_LOCK:
            return t.get("token") is None or bool(t["stop"])

    try:
        res = mod.run_signing_precheck(book, model=model, base_url=base_url,
                                       api_key=api_key, on_log=log, should_stop=should_stop)
        with PAGE_LOCK:
            if t.get("token") is None:
                return
        files = mod.save_precheck_reports(book, res)
        with PAGE_LOCK:
            if t.get("token") is None:
                return
            t.update(result=res, files=files, running=False, error=None,
                     stopped=False, finished_at=time.time())
        log("[完成] 预审报告已写出：" + "、".join(files.values()))
    except mod.Stopped:
        with PAGE_LOCK:
            if t.get("token") is None:
                return
            t.update(running=False, error=None, stopped=True, finished_at=time.time())
        log("[!] 已停止（可重新点「签约预审」）")
    except Exception as e:                      # noqa
        with PAGE_LOCK:
            if t.get("token") is None:
                return
            t.update(error=str(e), running=False, stopped=False, finished_at=time.time())
        log(f"[x] {e}")


# ---------------------------------------------------------------- AI 审查
def review_module():
    """延迟导入审查模块（与拆解同源，导入失败只影响审查入口）。

    延迟 + 兜底的目的是——即使审查模块有问题，控制台本身也要能正常起来，
    只在真正点「开始审查」时给出明确原因。"""
    try:
        import review
        return review
    except Exception as e:                      # noqa
        raise ValueError(f"AI 审查模块不可用：{e}")


def review_worker(t, mod, kwargs):
    """后台审查线程：任何写回（日志 / 结果 / 状态）前都先验 token。

    被「释放」或删除后 token 置空，旧线程跑到下一个检查点就退出，输出一律丢弃——
    每条审查各管各的，所以不同章节可以同时审查。"""
    usagelib.set_context(stage="review", book=kwargs.get("book") or "",
                         chapter_no=kwargs.get("chapter_no") or "")

    def log(msg):
        page_log(t, msg)

    def should_stop():
        with PAGE_LOCK:
            return t.get("token") is None or bool(t["stop"])

    try:
        res = mod.run_review(on_log=log, should_stop=should_stop, **kwargs)
        with PAGE_LOCK:
            if t.get("token") is None:      # 已释放：结果直接丢弃，不写盘
                return
        files = mod.save_reports(kwargs["book"], kwargs["chapter_no"], res)
        with PAGE_LOCK:
            if t.get("token") is None:
                return
            t.update(result=res, files=files, running=False, error=None,
                     stopped=False, finished_at=time.time())
        log("[完成] 报告已写出：" + "、".join(files.values()))
    except mod.Stopped:                         # 用户主动停止：不算失败，不弹红
        with PAGE_LOCK:
            if t.get("token") is None:
                return
            t.update(running=False, error=None, stopped=True, finished_at=time.time())
        log("[!] 已停止（可重新点「开始审查」）")
    except Exception as e:                      # noqa
        with PAGE_LOCK:
            if t.get("token") is None:
                return
            t.update(error=str(e), running=False, stopped=False, finished_at=time.time())
        log(f"[x] {e}")


def review_slug(chapter_no):
    """审查报告文件名前缀：ch001 / ch012（与 review.save_reports 一致）。"""
    m = re.search(r"\d+", str(chapter_no or ""))
    return ("ch" + m.group(0).zfill(3)) if m else ""


def load_review_result(book, chapter_no):
    """读 data/<书>/review/ 里该章最近一份报告，组成和 /api/review/job 一样的返回。

    审查报告本来就是落盘的（json/md/html），进程里任务被清理 / 服务重启后
    也应该能接着看，不该让用户重跑一遍。"""
    slug = review_slug(chapter_no)
    if not book or not slug:
        return None
    d = os.path.join(book_dir(book), "review")
    try:
        names = [n for n in os.listdir(d)
                 if n.startswith(slug + "_") and n.endswith(".json")]
    except OSError:
        return None
    if not names:
        return None
    names.sort(key=lambda n: os.path.getmtime(os.path.join(d, n)), reverse=True)
    path = os.path.join(d, names[0])
    result = read_json(path, None)
    if not isinstance(result, dict):
        return None
    stem = names[0][:-len(".json")]
    files = {}
    for ext in ("json", "md", "html"):
        p = os.path.join(d, "%s.%s" % (stem, ext))
        if os.path.isfile(p):
            files[ext] = os.path.relpath(p, ROOT).replace("\\", "/")
    # 字段与 review_state 保持一致（lines/total），前端接管同一套渲染逻辑
    return {"id": "", "running": False, "lines": [], "total": 0, "result": result,
            "error": None, "files": files, "stopped": False,
            "book": book, "chapter_no": str(chapter_no), "saved": True}


def review_state(t, since=0):
    """/api/review/job 的返回：按任务 id 给日志增量 + 结构化结果。"""
    with PAGE_LOCK:
        return {
            "id": t["id"],
            "running": bool(t["running"]),
            "lines": t["log"][since:], "total": len(t["log"]),
            "result": t.get("result"), "error": t.get("error"),
            "files": t.get("files") or {}, "stopped": bool(t.get("stopped")),
            "book": t.get("book") or "", "chapter_no": t.get("chapter_no") or "",
        }


def expand_state(t, since=0):
    """/api/expand/job 的返回：按任务 id 给正文增量 + 本任务的状态。

    text 是流式累计的正文，since 是前端已回显到的字符数，只发增量（几十万字也不卡）。"""
    with PAGE_LOCK:
        started = t.get("started_at") or 0
        finished = t.get("finished_at") or 0
        text = t.get("text") or ""
        return {
            "id": t["id"],
            "running": bool(t["running"]),
            "book": t.get("book") or "",
            "chapter_no": t.get("chapter_no"),
            "mode": t.get("mode") or "outline",
            "scope": t.get("scope") or "chapter",
            "name": page_task_name(t),
            "multi": bool(t.get("multi")),
            "versions": list(t.get("versions") or []),
            "recommended": t.get("recommended", 0),
            "target": t.get("target") or None,
            "existing": t.get("existing") or "",
            "code": t.get("code"), "error": t.get("error"),
            "stopped": bool(t.get("stopped")),
            "started_at": started, "finished_at": finished,
            "elapsed": round((time.time() - started) if (t["running"] and started)
                             else max(0.0, finished - started), 1),
            "text": text[since:], "total": len(text),
        }


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "NovelStudio"
    protocol_version = "HTTP/1.1"  # 现代浏览器需要 keep-alive

    def log_message(self, *a):
        pass

    # ---- helpers
    def _send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        raw = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def _json_body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ValueError("Content-Length 不合法") from None
        if n < 0:
            raise ValueError("Content-Length 不合法") from None
        if n > MAX_JSON_BODY:
            raise ValueError(f"请求体过大（上限 {MAX_JSON_BODY // 1024 // 1024}MB）") from None
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except ValueError:                      # JSON 解析 / UTF-8 解码失败都算请求体错误
            raise ValueError("请求体不是合法 JSON") from None

    def _gate(self):
        """请求准入：爬虫 UA / 限流 / 会话令牌 / 同源校验。命中时直接回响应并返回 True。"""
        verdict = guardlib.request_verdict(
            self.command, urlparse(self.path).path, self.headers,
            self.client_address[0] if self.client_address else "")
        if not verdict:
            return False
        code, body, extra = verdict
        if self.command == "HEAD":
            self.send_response(code)
            self.send_header("Content-Length", "0")
            for k, v in extra.items():
                self.send_header(k, v)
            self.end_headers()
        else:
            self._send(code, body, headers=extra)
        return True

    def _index(self):
        """首页：注入本次运行的会话令牌，写请求靠它区分界面内操作与外部脚本。"""
        for cand in (os.path.join(WEB_DIR, "dist", "index.html"),
                     os.path.join(WEB_DIR, "index.html")):
            if os.path.isfile(cand):
                with open(cand, encoding="utf-8") as f:
                    html = guardlib.inject_token(f.read())
                return self._send(200, html, "text/html; charset=utf-8")
        return self._send(404, {"error": "not found"})

    def _static(self, rel, prefer_dist=False):
        rel = rel.lstrip("/")
        # Vite 构建产物优先：web/dist 下的 index.html / assets/* 覆盖 web/ 下的同名文件
        candidates = []
        if prefer_dist:
            candidates.append(os.path.join(WEB_DIR, "dist", rel))
        candidates.append(os.path.join(WEB_DIR, rel))
        for cand in candidates:
            path = os.path.normpath(cand)
            if path.startswith(WEB_DIR + os.sep) and os.path.isfile(path):
                ctype = ("text/html; charset=utf-8" if path.endswith(".html")
                         else "text/css; charset=utf-8" if path.endswith(".css")
                         else "application/javascript; charset=utf-8" if path.endswith(".js")
                         else "application/json; charset=utf-8" if path.endswith(".json")
                         else "image/svg+xml" if path.endswith(".svg")
                         else "image/png" if path.endswith(".png")
                         else "text/plain; charset=utf-8")
                with open(path, "rb") as f:
                    return self._send(200, f.read(), ctype)
        return self._send(404, {"error": "not found"})

    def do_HEAD(self):
        """预览/检测工具常用 HEAD 探测可用性；返回头信息，不带 body。"""
        if self._gate():
            return
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            path = os.path.join(WEB_DIR, "index.html")
            if os.path.isfile(path):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(os.path.getsize(path)))
                self.end_headers()
                return
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ---- GET
    def do_GET(self):
        if self._gate():
            return
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path in ("/", "/index.html"):
                return self._index()
            if u.path.startswith("/static/"):
                return self._static(u.path[len("/static/"):])
            if u.path == "/api/workflow":
                return self._send(200, read_json(WORKFLOW, {}))
            if u.path == "/api/schema":
                return self._send(200, {**sb_schema(), **entitylib.schema_extra()})
            if u.path == "/api/storymap":
                name = sanitize_book(q.get("book", [""])[0])
                if not name:
                    return self._send(200, {"ok": False, "data": None})
                p = os.path.join(book_dir(name), "storymap.json")
                if not os.path.isfile(p):
                    # 书不存在 → 404；书存在但还没生成图谱 → 维持 ok:false（前端显示空，不报错）
                    if not book_exists(name):
                        return self._send(404, {"error": f"作品不存在：{name}"})
                    return self._send(200, {"ok": False, "data": None})
                data = read_json(p, {})
                if not isinstance(data, dict):
                    data = {}
                # 老图谱没有地图数据时现算一份，前端打开「世界地图」即可用
                if not isinstance(data.get("map"), dict) or not (data["map"].get("regions")):
                    data["map"] = build_storymap_fallback(name)
                return self._send(200, {"ok": True, "data": data})
            if u.path == "/api/map":
                # 世界地图：storymap.json 里的 AI/程序地图优先，缺失时用设定库 + 逐章数据现算
                name = sanitize_book(q.get("book", [""])[0])
                if not name:
                    return self._send(200, {"ok": False, "map": None})
                if not book_exists(name):
                    return self._send(404, {"error": f"作品不存在：{name}"})
                p = os.path.join(book_dir(name), "storymap.json")
                sm = read_json(p, {}) if os.path.isfile(p) else {}
                sm = sm if isinstance(sm, dict) else {}
                mp = sm.get("map") if isinstance(sm.get("map"), dict) else None
                if not mp or not (mp.get("regions")):
                    mp = build_storymap_fallback(name)
                return self._send(200, {"ok": True, "map": mp,
                                        "generated_at": sm.get("generated_at") or "",
                                        "ai": bool(sm.get("ai"))})
            if u.path == "/api/backups":
                # 本地自动备份：只读列表，恢复走 POST /api/backups/restore
                name = sanitize_book(q.get("book", [""])[0])
                if not name or not book_exists(name):
                    return self._send(404, {"error": "作品不存在"})
                return self._send(200, {"ok": True, "files": backuplib.list_backups(name)})
            if u.path == "/api/compliance/log":
                # 合规声明留痕（最近 50 条），仅供本机排查与交付审计
                return self._send(200, {"ok": True, "items": compliancelib.recent(50)})
            if u.path == "/api/storymap/plot":
                # 剧情脉络：优先用「生成图谱」时 AI 写进 storymap.json 的 plot；
                # 没有 AI 产出时，程序从设定库的时间线 / 主线 / 支线 / 伏笔 / 悬念 / 冲突解析。
                name = sanitize_book(q.get("book", [""])[0])
                sm = read_json(os.path.join(book_dir(name), "storymap.json"), {}) if name else {}
                ai_plot = sm.get("plot") if isinstance(sm.get("plot"), dict) else {}
                if ai_plot.get("timeline"):
                    caps = {"timeline": 14, "mainline": 8, "subplots": 10,
                            "foreshadow": 10, "suspense": 6, "conflict": 4}

                    def _clip(k):
                        out = []
                        for s in (ai_plot.get(k) or []):
                            s = str(s or "").strip()
                            if s:
                                out.append(s[:90])
                            if len(out) >= caps[k]:
                                break
                        return out

                    resp = {"ai": bool(sm.get("ai"))}
                    for k in caps:
                        resp[k] = _clip(k)
                    return self._send(200, resp)

                # 程序兜底：解析设定库（设定库里有人工/AI 写好的时间线时同样能用）
                ch = read_json(book_chapters(name), {}) if name else {}
                fields, _cards, _facs = parse_story_bible(ch.get("story_bible", "") or "")

                def _sents(v, cap=52, cap_n=14, sep=r"[；;]"):
                    out = []
                    for s in re.split(sep, str(v or "")):
                        s = s.strip().strip("·。- ")
                        if len(s) >= 4:
                            out.append(s[:cap])
                        if len(out) >= cap_n:
                            break
                    return out

                return self._send(200, {
                    "ai": False,
                    "mainline": _sents(fields.get("mainline"), sep=r"[；。]"),
                    "timeline": _sents(fields.get("timeline")),
                    "subplots": _sents(fields.get("subplots")),
                    "foreshadow": _sents(fields.get("foreshadow")),
                    "suspense": _sents(fields.get("suspense"), cap_n=6, sep=r"[；。]"),
                    "conflict": _sents(fields.get("conflict"), cap_n=4, sep=r"[；。]"),
                })
            if u.path == "/api/books":
                return self._send(200, {"books": list_books()})
            if u.path == "/api/stats":
                return self._send(200, book_stats())
            if u.path == "/api/stats/writing":
                # 码字统计：今日新增 / 近 7 日曲线 / 连击天数 / 日更目标进度
                book = sanitize_book(q.get("book", [""])[0]) or ""
                return self._send(200, writing_stats(book))
            if u.path == "/api/usage":
                # Token 成本与耗时统计：总量 + 按阶段 / 模型 / 书 / 近 N 天
                days = _qint(q, "days", 30) or 30
                days = max(1, min(365, days))
                return self._send(200, usagelib.summary(
                    prices=studiolib.load().get("prices"), days=days))
            if u.path == "/api/studio":
                # 工作台设置：分阶段模型绑定 / 成本单价 / 日更目标 / 记忆检索开关
                d = studiolib.load()
                d["stage_label"] = dict(studiolib.STAGE_LABEL)
                d["provider_presets"] = studiolib.PROVIDER_PRESETS
                return self._send(200, d)
            if u.path == "/api/prompts":
                # 提示词模板库：默认值 + 用户覆盖 + 实际生效值
                try:
                    import prompts as promptlib
                    return self._send(200, {"items": promptlib.registry()})
                except Exception as e:  # noqa
                    return self._send(500, {"error": f"提示词登记失败：{e}"})
            if u.path == "/api/sentinel/words":
                return self._send(200, {"words": sentinellib.load_words()})
            if u.path == "/api/history":
                # 某章正文的版本历史（新的在前）+ 当前正文摘要
                name, err = resolve_book(q.get("book", [""])[0])
                if err:
                    return self._send(*err)
                no = to_int(q.get("no", [""])[0], 0)
                if not name or no <= 0:
                    return self._send(400, {"error": "请提供书名与章节号"})
                return self._send(200, historylib.list_versions(name, no))
            if u.path == "/api/history/text":
                name = sanitize_book(q.get("book", [""])[0]) or ""
                no = to_int(q.get("no", [""])[0], 0)
                fname = os.path.basename(q.get("file", [""])[0] or "")
                text = historylib.read_version(name, no, fname) if name and no and fname else None
                if text is None:
                    return self._send(404, {"error": "该版本不存在或已被清理"})
                return self._send(200, {"text": text, "chars": len(text)})
            if u.path == "/api/history/diff":
                name = sanitize_book(q.get("book", [""])[0]) or ""
                no = to_int(q.get("no", [""])[0], 0)
                fname = os.path.basename(q.get("file", [""])[0] or "")
                diff = historylib.diff_version(name, no, fname) if name and no and fname else None
                if diff is None:
                    return self._send(404, {"error": "该版本不存在或已被清理"})
                return self._send(200, {"diff": diff})
            if u.path == "/api/memory/status":
                # 跨章记忆索引状态：索引了多少章 / 多少章有正文 / 专名数
                name, err = resolve_book(q.get("book", [""])[0])
                if err:
                    return self._send(*err)
                if not name:
                    return self._send(200, {"chapters": 0, "with_text": 0, "nouns": 0})
                import memory as memlib
                return self._send(200, memlib.status(name))
            if u.path == "/api/memory/search":
                # 记忆检索预览：看看「生成这章时 AI 会拿到哪些前文」
                name, err = resolve_book(q.get("book", [""])[0])
                if err:
                    return self._send(*err)
                if not name:
                    return self._send(200, {"hits": []})
                import memory as memlib
                query = q.get("q", [""])[0] or ""
                no = to_int(q.get("chapter_no", [""])[0], 0)
                if not query.strip() and no > 0:
                    chs = read_json(book_chapters(name), {}).get("chapters") or []
                    hit = next((c for c in chs if to_int(c.get("no") or c.get("chapter_id"), 0) == no), None)
                    if hit:
                        query = " ".join([str(hit.get("title") or ""), str(hit.get("summary") or ""),
                                          " ".join(hit.get("roles") or [] if isinstance(hit.get("roles"), list) else []),
                                          str(hit.get("scene") or "")])
                mc = studiolib.memory_conf()
                return self._send(200, {"hits": memlib.search(name, query, exclude_no=no,
                                                              top_k=mc["top_k"] + 3)})
            if u.path == "/api/review/batch":
                # 本书最近一次全书体检报告
                name, err = resolve_book(q.get("book", [""])[0])
                if err:
                    return self._send(*err)
                rep = latest_batch_report(name) if name else None
                return self._send(200, {"report": rep})
            if u.path == "/api/review/signing":
                # 本书最近一次签约预审报告（界面打开时回看）
                name, err = resolve_book(q.get("book", [""])[0])
                if err:
                    return self._send(*err)
                rep = latest_signing_report(name) if name else None
                return self._send(200, {"report": rep})
            if u.path == "/api/review/reports":
                # 作品级报告历史（全书体检 / 签约预审）：每次执行都落一份新报告
                name, err = resolve_book(q.get("book", [""])[0])
                if err:
                    return self._send(*err)
                kind = str(q.get("kind", [""])[0] or "").strip()
                if kind not in REVIEW_REPORT_KINDS:
                    return self._send(400, {"error": "kind 需为 batch / signing"})
                return self._send(200, {"reports": list_review_reports(name, kind) if name else []})
            if u.path == "/api/review/report":
                # 读历史里的某一份报告（弹窗切历史）
                name, err = resolve_book(q.get("book", [""])[0])
                if err:
                    return self._send(*err)
                kind = str(q.get("kind", [""])[0] or "").strip()
                if kind not in REVIEW_REPORT_KINDS:
                    return self._send(400, {"error": "kind 需为 batch / signing"})
                try:
                    rep = read_review_report(name, kind, q.get("file", [""])[0])
                except ValueError as e:
                    return self._send(404, {"error": str(e)})
                return self._send(200, {"report": rep})
            if u.path == "/api/chapters":
                name, err = resolve_book(q.get("book", [""])[0])
                if err:
                    return self._send(*err)
                if name and not book_exists(name):
                    return self._send(404, {"error": f"作品不存在：{name}"})
                data = read_json(book_chapters(name), {}) if name else {}
                if not data:
                    data = {}
                # 读取时做一遍内存内的自洽（复读名折叠 + 重复卡合并 + 章节引用同步 + 词表规范化），
                # 与保存响应共用同一套口径，保证卡片与章节显示的是同一套名字（只读，不写盘）
                return self._send(200, chapters_payload(name, data))
            if u.path == "/api/cover/presets":
                # 平台制式 / 出图模型 / 文字风格 / 版式，前端弹窗一次拉全
                return self._send(200, coverlib.preset_list())
            if u.path == "/api/cover":
                name, err = resolve_book(q.get("book", [""])[0])
                if err:
                    return self._send(*err)
                p = cover_path(name) if name else None
                if not p:
                    return self._send(404, {"error": "no cover"})
                ext = p.rsplit(".", 1)[-1].lower()
                ctype = "image/png" if ext == "png" else \
                        "image/webp" if ext == "webp" else "image/jpeg"
                with open(p, "rb") as f:
                    return self._send(200, f.read(), ctype)
            if u.path == "/api/data/status":
                # 同步面板预检：有任务在跑时先给出可读提示，避免直接点到失败
                return self._send(200, data_sync_status())
            if u.path == "/api/data/export":
                # 数据同步：凭一次性票据取口令，把 data/<书名>/ 全部产出加密后下载
                if any_task_running():
                    return self._send(409, {"error": "有任务正在运行，请等任务结束后再导出"})
                pwd = take_export_ticket(q.get("ticket", [""])[0])
                if pwd is None:
                    return self._send(403, {"error": "导出凭证已失效，请重新导出（会再次要求输入口令）"})
                try:
                    blob, manifest, fn = export_encrypted(pwd)
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
                return self._send(200, blob, "application/octet-stream", {
                    "Content-Disposition": f'attachment; filename="{fn}"',
                    "X-Book-Count": str(len(manifest.get("books") or [])),
                })
            if u.path == "/api/sources":
                return self._send(200, {"sources": list_sources()})
            if u.path == "/api/outputs":
                # 分页：page>=1 只返回该页 + 总条数；不带 page 时全量返回（书内页面已按 book/kind 收窄）
                return self._send(200, query_outputs(
                    q=q.get("q", [""])[0], group=q.get("group", [""])[0],
                    book=q.get("book", [""])[0], kind=q.get("kind", [""])[0],
                    page=q.get("page", ["0"])[0], page_size=q.get("page_size", ["100"])[0]))
            if u.path == "/api/output":
                p = resolve_output(q.get("path", [""])[0])
                if not p:
                    return self._send(404, {"error": "文件不存在或不可读"})
                hdrs = {}
                if q.get("dl", ["0"])[0] == "1":      # 下载：带附件头，文件名走 RFC5987
                    hdrs["Content-Disposition"] = \
                        "attachment; filename*=UTF-8''" + urllib.parse.quote(os.path.basename(p))
                # 预览截断：几十 MB 的报告直接塞进 DOM 会把页面卡死，超出部分提示下载
                with open(p, encoding="utf-8", errors="replace") as f:
                    text = f.read(OUTPUT_PREVIEW_CHARS + 1)
                truncated = len(text) > OUTPUT_PREVIEW_CHARS
                if truncated:
                    text = text[:OUTPUT_PREVIEW_CHARS]
                return self._send(200, {"name": os.path.basename(p), "content": text,
                                        "truncated": truncated, "size": os.path.getsize(p)},
                                  headers=hdrs)
            if u.path == "/api/review/options":
                mod = review_module()
                return self._send(200, {
                    "checks": mod.ALL_CHECKS, "labels": mod.CHECK_LABEL,
                    "no_call": sorted(mod.NO_CALL_CHECKS),
                    "advice_scopes": {k: [mod.TYPE_LABEL[t] for t in v]
                                      for k, v in mod.ADVICE_SCOPES.items()},
                })
            if u.path == "/api/review/baseline":
                name, err = resolve_book(q.get("book", [""])[0])
                if err:
                    return self._send(*err)
                if not name:
                    return self._send(400, {"error": "尚无任何书，请先拆解"})
                b = review_module().load_baseline(name, q.get("chapter_no", [""])[0])
                return self._send(200, {
                    "book": name, "chapter_no": b["chapter_no"],
                    "chapter_id": b["chapter_id"], "title": b["title"],
                    "chapter_summary": b["chapter_summary"],
                    "chapter_points": b["chapter_points"],
                    "chapter_scene": b["chapter_scene"],
                    "chapter_roles": b["chapter_roles"],
                    "chapter_hook": b.get("chapter_hook", ""),
                    "chapter_conflict": b.get("chapter_conflict", ""),
                    "n_prev": len(b.get("prev_chapters") or []),
                    "synopsis_preview": b["synopsis"][:200],
                    "has_synopsis": b["has_synopsis"],
                    "has_chapter_summary": b["has_chapter_summary"],
                    "has_setting": b["has_setting"],
                    "has_timeline": bool((b.get("setting_fields") or {}).get("timeline")),
                    "has_foreshadow": bool((b.get("setting_fields") or {}).get("foreshadow")),
                    "n_cards": b["n_cards"], "n_factions": b["n_factions"],
                    "setting_keys": list((b.get("setting_fields") or {}).keys()),
                    "n_chapters": b["n_chapters"], "notes": b["notes"],
                })
            if u.path == "/api/review/job":
                # 按任务 id 拉这条审查的进度；不传 id 时按「书 + 章」找最近的，
                # 都没有才回退到全局最近一条（兼容旧前端 / 页面刚打开时接进行中的任务）
                since = _qint(q, "since")
                tid = (q.get("id") or [""])[0]
                book = sanitize_book(q.get("book", [""])[0]) if q.get("book") else ""
                ch = (q.get("chapter_no") or [""])[0]
                t = page_task_get(tid) if tid else page_task_latest("review", book or "", ch)
                if t is None:
                    # 进程里已经没有这条任务（切书回来很久 / 服务重启过）：
                    # 直接读 review/ 下该章最近一份报告，审查结论不会白跑一趟
                    saved = load_review_result(book, ch) if (book and ch) else None
                    if saved is not None:
                        return self._send(200, saved)
                    t = {"id": "", "running": False, "log": [], "result": None,
                         "error": None, "files": {}, "stopped": False,
                         "book": "", "chapter_no": ""}
                return self._send(200, review_state(t, since))
            if u.path == "/api/expand/job":
                # 正文生成任务状态：带书 / 章节 / 起止时间，页面切换后可接管进行中的任务，
                # 空闲时返回该书上次任务的落盘快照（last），失败原因不会随页面刷新丢失。
                since = _qint(q, "since")
                book = sanitize_book(q.get("book", [""])[0]) if q.get("book") else ""
                ch = (q.get("chapter_no") or [""])[0]
                tid = (q.get("id") or [""])[0]
                t = page_task_get(tid) if tid else page_task_latest("write", book or "", ch)
                if t is None:
                    payload = {"id": "", "running": False, "book": "", "chapter_no": None,
                               "mode": "outline", "scope": "chapter", "name": "",
                               "multi": False, "versions": [], "recommended": 0,
                               "target": None, "existing": "",
                               "code": None, "error": None,
                               "stopped": False, "started_at": 0, "finished_at": 0,
                               "elapsed": 0, "text": "", "total": 0}
                else:
                    payload = expand_state(t, since)
                last = None
                target_book = payload["book"] or book
                # 本章自己的任务还在跑时不必读快照（前端走「接管进度」分支）；
                # 别的章在跑则照读——那一章的候选与当前章互不相干
                want_ch = payload["chapter_no"] or ch
                running_here = (payload["running"] and payload["book"] == book
                                and str(payload["chapter_no"]) == str(ch or want_ch))
                if target_book and not running_here:
                    if os.path.isdir(book_dir(target_book)):
                        # 先按本章读；老版本只存了「整本一份」的快照时再退回它
                        last = read_json(expand_task_file(target_book, want_ch), None)
                        if not last:
                            last = read_json(expand_task_file(target_book), None)
                payload["last"] = last
                return self._send(200, payload)
            if u.path == "/api/jobs":
                # 任务中心：列出全部任务（新的在前），前端据此显示并跳转到各自页面。
                # 页内任务（审查 / 正文生成）每条一条记录、各自 id，所以能同时列好几条在跑的。
                with JOB_LOCK:
                    jobs = [job_summary(j) for j in JOBS.values()]
                with PAGE_LOCK:
                    for t in PAGE_TASKS.values():
                        s = page_summary(t)
                        if s:
                            jobs.append(s)
                jobs.sort(key=lambda x: x.get("created_at") or 0, reverse=True)
                return self._send(200, {
                    "jobs": jobs, "max_running": MAX_RUNNING_TASKS,
                    "running": sum(1 for j in jobs if j["running"]),
                })
            if u.path == "/api/job":
                # 按 id 轮询某个任务的实时日志；不带 id 时取最近的一个任务（兼容旧前端）
                jid = (q.get("id") or [""])[0]
                since = _qint(q, "since")
                pt = page_task_get(jid)
                if pt is not None:            # 页内任务（审查 / 正文生成）：同样按 id 拉增量日志
                    return self._send(200, page_public(pt, since))
                with JOB_LOCK:
                    job = JOBS.get(jid) if jid else None
                    if job is None and not jid:
                        job = max(JOBS.values(), key=lambda x: x["created_at"], default=None)
                if job is None:
                    if jid:
                        return self._send(404, {"error": f"任务 {jid} 不存在（可能已被清理）"})
                    return self._send(200, {"id": "", "running": False, "stage": None,
                                            "code": None, "queued": [],
                                            "lines": [], "total": 0})
                return self._send(200, job_public(job, since))
            # 未知 API 必须 404：回退到首页会让前端把 HTML 当 JSON 解析，错误难以定位
            if u.path.startswith("/api/"):
                return self._send(404, {"error": "no route"})
            # SPA 静态资源（Vite 构建的 /assets/* 等）兜底；其余未知路径回退到首页
            leaf = u.path.split("/")[-1]
            if u.path.startswith("/assets/") or "." in leaf:
                return self._static(u.path.lstrip("/"), prefer_dist=True)
            return self._static("index.html", prefer_dist=True)
        except Exception as e:  # noqa
            return self._send(500, {"error": str(e)})

    # ---- PUT
    def do_PUT(self):
        if self._gate():
            return
        try:
            body = self._json_body()
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path == "/api/studio":
                # 保存工作台设置（模型档案 / 工序绑定 / 单价 / 日更目标 / 记忆开关），直接返回保存后的完整设置
                return self._send(200, studiolib.save(body))
            if u.path == "/api/prompts":
                # 提示词覆盖：text 非空覆盖，置空恢复默认
                import prompts as promptlib
                return self._send(200, promptlib.set_override(
                    str(body.get("key") or ""), body.get("text")))
            if u.path == "/api/sentinel/words":
                n = sentinellib.save_words(body.get("words") or [])
                return self._send(200, {"ok": True, "count": n})
            if u.path == "/api/chapters":
                if not isinstance(body, dict) or not isinstance(body.get("chapters"), list):
                    return self._send(400, {"error": "chapters 结构不合法（chapters 必须是数组）"})
                if any(not isinstance(c, dict) for c in body["chapters"]):
                    return self._send(400, {"error": "chapters 结构不合法：每个章节必须是对象"})
                name, err = resolve_book(q.get("book", [""])[0])
                if err:
                    return self._send(*err)
                if not name:
                    return self._send(400, {"error": "尚无任何书，请先拆解或指定 book 参数"})
                # 本书还有任务在跑时禁止保存：任务会按旧数据整包回写，两边互相覆盖
                hot = book_busy(name)
                if hot:
                    label = hot.get("label") or hot.get("stage") or hot.get("id") or ""
                    return self._send(409, {"error":
                        f"《{name}》有正在运行的任务（{label}），请等它结束后再修改数据"})
                old = read_json(book_chapters(name), {})
                old_chapters = old.get("chapters") or []
                # 老文档里的实体（卡片存在 story_bible 文本里，道具在顶层 items）
                _of, _oc, _ofa = parse_story_bible(old.get("story_bible", "") or "")
                old_view = {"story_bible_cards": _oc, "story_bible_factions": _ofa,
                            "items": old.get("items") or [], "chapters": old.get("chapters") or []}
                # 批量改名 / 删卡：前端显式给 renames；删除的实体映射成空串，引用随之清空
                renames = body.pop("renames", None)
                renames = renames if isinstance(renames, dict) else {}
                _present = {"characters": isinstance(body.get("story_bible_cards"), list),
                            "factions": isinstance(body.get("story_bible_factions"), list),
                            "items": isinstance(body.get("items"), list)}
                for _kind in ("characters", "factions", "items"):
                    _map = renames.get(_kind)
                    _map = {str(k): str(v or "") for k, v in _map.items()} if isinstance(_map, dict) else {}
                    # 只在该类实体确实随请求提交时才判删除，避免局部保存误删整份名册
                    if _present[_kind]:
                        _got = set(entitylib.entity_names(body, _kind))
                        for _gone in set(entitylib.entity_names(old_view, _kind)) - _got - set(_map):
                            _map[_gone] = ""
                    if _map:
                        renames[_kind] = _map
                    else:
                        renames.pop(_kind, None)
                if renames:
                    entitylib.apply_renames(body, renames)
                # 所有保存都统一过一遍：清洗复读名、合并重复卡、引用去重
                entitylib.sync_document(body)
                body.setdefault("items", old.get("items") or [])
                body["items"] = [entitylib.normalize_item(it)
                                 for it in body.get("items") or [] if isinstance(it, dict)]
                # 前端按字段录入 → 后端整合回生成管线消费的那条 story_bible 字符串
                if isinstance(body.get("story_bible_fields"), dict):
                    body["story_bible"] = compose_story_bible(
                        body["story_bible_fields"], body.get("story_bible_cards") or [],
                        body.get("story_bible_factions") or [])
                body.pop("story_bible_fields", None)
                body.pop("story_bible_cards", None)
                body.pop("story_bible_factions", None)
                body.pop("book", None)
                normalize_chapter_no(body["chapters"])
                # 章节改序号 / 上下移 / 删章后，道具卡「首次出现」等章号引用跟着内容一起走
                _no_map = entitylib.chapter_no_remap(old_chapters, body["chapters"])
                entitylib.apply_chapter_no_map(
                    body, _no_map, {c.get("no") for c in body["chapters"]})
                # 签约数据：opening 旧值保留，signing_check 按编辑后的骨架当场重算（编辑完立刻看到缺口变化）
                try:
                    from decompose import norm_opening as _no, signing_check as _sc
                    body["opening"] = _no(body.get("opening") or old.get("opening"))
                    body["signing_check"] = _sc(body["chapters"], body["opening"])
                except Exception:                   # 拆解模块不可用时旧值原样保留，不丢数据
                    for k in ("opening", "signing_check"):
                        if k not in body and k in old:
                            body[k] = old[k]
                os.makedirs(book_dir(name), exist_ok=True)
                # 覆盖前自动快照旧版本：误改 / 误删章节可从「设置 → 数据同步 → 自动备份」恢复
                try:
                    backuplib.snapshot(name)
                except Exception:
                    pass
                write_json(book_chapters(name), body)
                # 地图场景引用的角色 / 势力 / 道具与章号同步（改名、删卡、改章节序号后保持联动）
                try:
                    sync_storymap_map(name, renames, _no_map,
                                      {c.get("no") for c in body["chapters"]})
                except Exception:               # 地图同步失败不影响主数据保存
                    pass
                # 返回落盘后的完整视图（与 GET 同一口径）：前端直接用它刷新回显，
                # 不必再发一次请求，也不会出现「保存后显示的还是旧名」
                return self._send(200, chapters_payload(
                    name, read_json(book_chapters(name), {})))
            return self._send(404, {"error": "no route"})
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        except Exception as e:  # noqa
            return self._send(500, {"error": str(e)})

    # ---- POST
    def do_POST(self):
        if self._gate():
            return
        try:
            body = self._json_body()
            path = urlparse(self.path).path
            if path == "/api/export":
                # 成稿导出：docx / md / txt，只读取 manuscript，不改数据
                book = sanitize_book(body.get("book") or "")
                fmt = str(body.get("fmt") or "docx").lower()
                if not book:
                    return self._send(400, {"error": "请选择作品"})
                try:
                    import export_book
                    data, fname, ctype = export_book.build(book, fmt)
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
                except Exception as e:                      # noqa
                    return self._send(500, {"error": f"导出失败：{e}"})
                return self._send(200, data, ctype, {
                    "Content-Disposition":
                        "attachment; filename=\"export." + fmt + "\"; "
                        "filename*=UTF-8''" + urllib.parse.quote(fname),
                })
            if path == "/api/upload":
                name = safe_source_name(body.get("name", ""))
                if not name:
                    return self._send(400, {"error": "文件名不合法：仅支持 .txt/.md，且不能与程序文件重名"})
                if body.get("b64"):
                    try:
                        data = base64.b64decode(body["b64"])
                    except ValueError:
                        return self._send(400, {"error": "文件内容不是合法 base64"})
                else:
                    data = (body.get("text") or "").encode("utf-8")
                if not data:
                    return self._send(400, {"error": "内容为空"})
                if len(data) > MAX_UPLOAD:
                    return self._send(413, {"error": f"文件过大（>{MAX_UPLOAD // 1024 // 1024}MB）"})
                with open(os.path.join(INPUT_DIR, name), "wb") as f:
                    f.write(data)
                return self._send(200, {"ok": True, "name": name, "size": len(data)})

            if path == "/api/data/export/prepare":
                # 导出第一步：校验口令并换一张下载票据（口令不进 URL）
                if any_task_running():
                    return self._send(409, {"error": "有任务正在运行，请等任务结束后再导出"})
                try:
                    pwd = securelib.check_password(body.get("password"))
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
                return self._send(200, {"ok": True, "ticket": issue_export_ticket(pwd)})

            if path == "/api/data/export/save":
                # 客户端（pywebview）里没有可靠的下载目录：加密后直接存到 exe 旁边的 exports/
                if any_task_running():
                    return self._send(409, {"error": "有任务正在运行，请等任务结束后再导出"})
                try:
                    blob, manifest, fn = export_encrypted(body.get("password"))
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
                out_dir = os.path.join(os.path.dirname(DATA_DIR), "exports")
                os.makedirs(out_dir, exist_ok=True)
                p = os.path.join(out_dir, fn)
                with open(p, "wb") as f:
                    f.write(blob)
                return self._send(200, {"ok": True, "path": p, "bytes": len(blob),
                                        "books": len(manifest.get("books") or [])})
            if path == "/api/open/path":
                # 桌面端：在资源管理器里打开导出目录，方便拖进聊天窗口发送
                if os.environ.get("MOBIT_ANDROID"):
                    return self._send(400, {"error": "手机端请到「下载 / 墨写」目录查看文件"})
                raw_path = str(body.get("path") or "").strip()
                # 不带 path 时默认打开导出目录（没有就建一个，方便用户先看到位置）
                target = os.path.abspath(raw_path) if raw_path else \
                    os.path.abspath(os.path.join(ROOT, "exports"))
                if not os.path.isdir(target) and not raw_path:
                    try:
                        os.makedirs(target, exist_ok=True)
                    except OSError as e:
                        return self._send(400, {"error": f"导出目录创建失败：{e}"})
                if not target or not os.path.isdir(target):
                    return self._send(400, {"error": "目录不存在，请先导出一次"})
                root = os.path.abspath(ROOT)
                try:
                    inside = os.path.commonpath([root, target]) == root
                except ValueError:
                    inside = False
                if not inside:
                    return self._send(400, {"error": "只能打开工作台目录内的文件夹"})
                try:
                    if os.name == "nt":
                        os.startfile(target)  # noqa: 仅 Windows 有
                    elif sys.platform == "darwin":
                        subprocess.Popen(["open", target])
                    else:
                        subprocess.Popen(["xdg-open", target])
                except Exception as e:  # noqa
                    return self._send(500, {"error": f"打开目录失败：{e}"})
                return self._send(200, {"ok": True, "path": target})
            if path == "/api/backups/restore":
                # 恢复本地自动备份；恢复前会再快照一次当前版本，可反悔
                name = sanitize_book(body.get("book") or "")
                if not name or not book_exists(name):
                    return self._send(404, {"error": "作品不存在"})
                if book_busy(name):
                    return self._send(409, {"error": "该作品还有任务在运行，请结束后再恢复备份"})
                try:
                    f = backuplib.restore(name, body.get("file") or "")
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
                return self._send(200, {"ok": True, "file": f})
            if path == "/api/data/import":
                # 数据同步：导入 zip（base64）。同名作品整体覆盖，replace=True 时先整体备份旧作品目录
                if any_task_running():
                    return self._send(409, {"error": "有任务正在运行，请等任务结束后再导入数据"})
                try:
                    raw = base64.b64decode(body.get("zip") or "")
                except (ValueError, TypeError):
                    return self._send(400, {"error": "压缩包内容不是合法 base64"})
                if not raw:
                    return self._send(400, {"error": "请选择要导入的压缩包"})
                if securelib.is_encrypted(raw):
                    # 加密包：用导出时设置的口令解开；旧版明文 zip 继续兼容
                    try:
                        raw = securelib.decrypt(raw, body.get("password"))
                    except ValueError as e:
                        return self._send(400, {"error": str(e)})
                try:
                    res = import_data_zip(raw, replace=bool(body.get("replace")))
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
                except OSError as e:
                    return self._send(500, {"error": f"写入数据目录失败：{e}"})
                return self._send(200, {"ok": True, **res})

            if path == "/api/cover/translate":
                # 提示词预览：中文 → 英文（本地词表，不调用大模型）
                return self._send(200, coverlib.translate_prompt(body.get("text") or ""))

            if path == "/api/cover/generate":
                # AI 封面：Pollinations 出底图 + 本地排版书名/作者/著，直接落盘为书封面
                name = sanitize_book(body.get("book") or "")
                if not name:
                    return self._send(400, {"error": "书名不合法"})
                author = str(body.get("author") or "").strip()[:40]
                if not author:
                    return self._send(400, {"error": "请填写作者名：封面必须显示「书名 + 作者 + 著」"})
                seed = body.get("seed")
                try:
                    res = coverlib.generate_cover(
                        name,
                        prompt=body.get("prompt") or "",
                        width=body.get("width") or 1400,
                        height=body.get("height") or 2100,
                        title=str(body.get("title") or "").strip()[:60],
                        author=author,
                        model=str(body.get("model") or "flux"),
                        style=str(body.get("style") or "gold"),
                        layout=str(body.get("layout") or "top"),
                        fmt=str(body.get("fmt") or "jpg"),
                        seed=None if seed in (None, "") else seed,
                        reuse_base=bool(body.get("reuse_base")),
                        # 「AI 封面底图」工序绑定的模型档案：有 Key 时优先用它出图，
                        # 模型不支持出图会自动回退 Pollinations / 本地绘制
                        api_key=str(body.get("api_key") or "").strip(),
                        base_url=str(body.get("base_url") or "").strip(),
                        ai_model=str(body.get("ai_model") or "").strip(),
                    )
                except coverlib.CoverError as e:
                    return self._send(400, {"error": str(e)})
                except Exception as e:      # noqa
                    return self._send(500, {"error": f"封面生成失败：{e}"})
                save_book_author(name, author)
                return self._send(200, res)

            if path == "/api/cover":
                # 上传 / 更换书封面：data/<书名>/cover.<ext>，单张，自动清理旧格式
                name = sanitize_book(body.get("book") or "")
                if not name:
                    return self._send(400, {"error": "书名不合法"})
                ext = str(body.get("ext") or "").lower().lstrip(".")
                if ext == "jpeg":
                    ext = "jpg"
                if ext not in ("png", "jpg", "webp"):
                    return self._send(400, {"error": "仅支持 png / jpg / webp 图片"})
                try:
                    data = base64.b64decode(body.get("b64") or "")
                except Exception:
                    data = b""
                if not data:
                    return self._send(400, {"error": "图片内容为空"})
                if len(data) > 5 * 1024 * 1024:
                    return self._send(413, {"error": "图片过大（>5MB）"})
                d = book_dir(name)
                os.makedirs(d, exist_ok=True)
                for e in COVER_EXTS:
                    old = os.path.join(d, "cover." + e)
                    if os.path.isfile(old):
                        try:
                            os.remove(old)
                        except OSError:
                            pass
                with open(os.path.join(d, "cover." + ext), "wb") as f:
                    f.write(data)
                return self._send(200, {"ok": True, "book": name})

            if path == "/api/cover/delete":
                name = sanitize_book(body.get("book") or "")
                if not name:
                    return self._send(400, {"error": "书名不合法"})
                p = cover_path(name)
                if p:
                    try:
                        os.remove(p)
                    except OSError:
                        pass
                return self._send(200, {"ok": True, "book": name})

            if path == "/api/manuscript/save":
                # 保存 / 覆写单章正文：data/<书名>/manuscript/<NNN>.txt
                name = sanitize_book(body.get("book") or "")
                if not name:
                    return self._send(400, {"error": "书名不合法"})
                try:
                    no = int(body.get("no") or 0)
                except (TypeError, ValueError):
                    no = 0
                if not (1 <= no <= 9999):
                    return self._send(400, {"error": "章节号不合法"})
                text = str(body.get("text") or "")
                if len(text) > 200_000:
                    return self._send(413, {"error": "正文过长（>20 万字）"})
                d = os.path.join(book_dir(name), "manuscript")
                os.makedirs(d, exist_ok=True)
                fp = os.path.join(d, f"{no:03d}.txt")
                old = ""
                if os.path.isfile(fp):
                    try:
                        with open(fp, encoding="utf-8", errors="replace") as f:
                            old = f.read()
                    except OSError:
                        pass
                    # 版本历史（P0）：覆盖前留快照，正文改坏了随时回滚
                    if old and old != text:
                        historylib.snapshot(name, no, old, note="手动保存覆盖前")
                with open(fp, "w", encoding="utf-8") as f:
                    f.write(text)
                _record_writing(name, len(old), len(text))
                return self._send(200, {"ok": True, "book": name, "no": no,
                                        "chars": len(text)})

            if path == "/api/source/delete":
                name = safe_source_name(body.get("name", ""))
                if not name:
                    return self._send(400, {"error": "文件名不合法"})
                p = os.path.join(INPUT_DIR, name)
                if not os.path.isfile(p):
                    return self._send(404, {"error": f"源文件不存在：{name}"})
                os.remove(p)
                return self._send(200, {"ok": True, "name": name})

            if path == "/api/output/delete":
                # 删除单个产出文件：路径必须在 _scan_outputs() 白名单内（防目录穿越）
                rel = (body.get("path") or "").replace("\\", "/")
                full = resolve_output(rel)
                if not full:
                    return self._send(400, {"error": "文件不存在或不在产出清单内"})
                os.remove(full)
                parent = os.path.dirname(full)   # 书目录 / 批次目录清空后一并移除
                if parent not in (DATA_DIR, OUT_DIR) and os.path.isdir(parent) and not os.listdir(parent):
                    try:
                        os.rmdir(parent)
                    except OSError:
                        pass
                _invalidate_outputs()
                return self._send(200, {"ok": True, "path": rel})

            if path == "/api/entities/rename":
                # 一键批量改名：让模型按「像真实中文专名」的标准给整份名册重新起名。
                # 只返回映射表，由前端确认后再随 PUT /api/chapters 的 renames 落盘（关联同步在服务端完成）。
                book = sanitize_book(body.get("book") or "")
                kind = str(body.get("kind") or "").strip()
                if kind not in ("characters", "factions", "items"):
                    return self._send(400, {"error": "kind 必须是 characters / factions / items"})
                if not book:
                    return self._send(400, {"error": "请选择作品"})
                ch = read_json(book_chapters(book), {})
                _fields, _cards, _facs = parse_story_bible(ch.get("story_bible", "") or "")
                _items = [it for it in (ch.get("items") or []) if isinstance(it, dict)]
                want = body.get("names")
                want = {str(x).strip() for x in want if str(x).strip()} if isinstance(want, list) else None

                def _row(ent, *keys):
                    name = str(ent.get("name") or "").strip()
                    if not name or (want and name not in want):
                        return ""
                    extra = "｜".join(str(ent.get(k) or "")[:40] for k in keys)
                    return f"{name}｜{extra}" if extra else name

                if kind == "characters":
                    rows = [_row(c, "role", "identity") for c in _cards]
                    label, hint = "角色", "2~4 字、以常见姓氏开头（沈砚、周小满、苏晚）"
                elif kind == "factions":
                    rows = [_row(f, "category", "desc") for f in _facs]
                    label, hint = "势力", "2~10 字、像真实组织 / 门派 / 家族名"
                else:
                    rows = [_row(it, "kind", "effect") for it in _items]
                    label, hint = "道具功法", "2~10 字、具体可辨识、不像通用词"
                rows = [r for r in rows if r]
                if not rows:
                    return self._send(400, {"error": f"没有可改名的{label}"})
                api_key = (body.get("api_key") or os.environ.get("DEEPSEEK_API_KEY", "")).strip()
                if not api_key:
                    return self._send(400, {"error": "未配置 API Key：请先在设置里绑定模型档案"})
                from deepseek_common import DEFAULT_MODEL, chat_json, resolve_base_url
                model = str(body.get("model") or DEFAULT_MODEL)
                base_url = resolve_base_url(body.get("base_url"))
                style = str(body.get("style") or "").strip() or "沿用原著题材与基调"
                prompt = f"""请为下面这份小说{label}名册重新起名。

改编 / 命名要求：
{style}

旧名清单（每行：旧名｜定位 / 类型｜简介摘要）：
{chr(10).join(rows)}

只输出一个 JSON 对象：
{{"name_map": [{{"old": "旧名", "new": "新名"}}]}}

要求：
1. 覆盖清单里的每一个旧名，old 必须逐字一致，不得遗漏或重复。
2. 新名字必须像真实的中文专名：{hint}。
3. 禁止任何复读：同一字连写三次（孟孟孟皇后）、同一词连写两次（慈懿慈懿慈懿太后）一律不许出现；
   禁止谐音梗 / 网络梗 / 搞笑名（邵刻薄、费纸鸢、郝浪、罗密），也不要用身份称呼代替姓名。
4. 新名字彼此不得重名，也不得与旧名相同或只差一个字；不要复用旧名里的字来凑数。
5. 只输出 JSON，不要解释，不要代码块围栏。"""
                try:
                    res = chat_json(api_key, base_url, model,
                                    "你是中文小说命名专家，只输出 JSON。", prompt, retries=2)
                except Exception as e:  # noqa
                    return self._send(400, {"error": f"AI 改名失败：{e}"})
                out, used = [], set()
                for m in (res.get("name_map") or []):
                    if not isinstance(m, dict):
                        continue
                    old = str(m.get("old") or "").strip()
                    new = entitylib.clean_name(m.get("new"), 24)
                    if not old or not new or old == new or old in used or new in used:
                        continue
                    used.add(old)
                    used.add(new)
                    out.append({"old": old, "new": new})
                if not out:
                    return self._send(400, {"error": "模型没有返回可用的新名字，请重试"})
                return self._send(200, {"ok": True, "kind": kind, "name_map": out})

            if path == "/api/book/delete":
                # 删除整本书的产出：data/<书名>/ 目录连同其中全部文件
                name = sanitize_book(body.get("book") or "")
                if not name:
                    return self._send(400, {"error": "书名不合法"})
                d = book_dir(name)
                if not os.path.isdir(d):
                    return self._send(404, {"error": f"书「{name}」不存在"})
                # 任务还在写这本书时禁止删除，否则删掉的目录会被任务重新建出来
                hot = book_busy(name)
                if hot:
                    label = hot.get("label") or hot.get("stage") or hot.get("id") or ""
                    return self._send(409, {"error":
                        f"《{name}》有正在运行的任务（{label}），请先停止再删除"})
                shutil.rmtree(d, ignore_errors=True)
                _invalidate_outputs()
                return self._send(200, {"ok": True, "book": name})

            if path == "/api/batch/delete":
                # 删除一个历史批次：output/<批次>/ 目录（只接受单层目录名，防穿越）
                raw = str(body.get("name") or "").strip()
                name = os.path.basename(raw)
                d = os.path.join(OUT_DIR, name)
                if not name or name in (".", "..") or not os.path.isdir(d):
                    return self._send(404, {"error": "批次不存在"})
                shutil.rmtree(d, ignore_errors=True)
                _invalidate_outputs()
                return self._send(200, {"ok": True, "name": name})

            if path == "/api/book/rename":
                # 作品改名：整本 data/<旧名>/ 目录改名到 data/<新名>/，
                # 并同步书内元数据里的书名（改编书 chapters/decomposed 顶层 book_title、首章 book_title）
                src = sanitize_book(body.get("from") or "")
                dst = sanitize_book(body.get("to") or "")
                if not src or not dst:
                    return self._send(400, {"error": "书名不合法"})
                if src == dst:
                    return self._send(200, {"book": dst})
                sdir, ddir = book_dir(src), book_dir(dst)
                if not os.path.isdir(sdir):
                    return self._send(404, {"error": f"书「{src}」不存在"})
                if os.path.isdir(ddir) and os.listdir(ddir):
                    return self._send(400, {"error": f"目标书名「{dst}」已有产出，换一个"})
                # 有任务在跑时禁止改名：运行中的子进程/页内任务仍按旧路径写文件，
                # 目录被移走后产出会分裂到新旧两个目录
                hot = book_busy(src)
                if hot:
                    label = hot.get("label") or hot.get("stage") or hot.get("id") or ""
                    return self._send(409, {"error":
                        f"《{src}》有正在运行的任务（{label}），请先停止再改名"})
                if os.path.isdir(ddir):
                    os.rmdir(ddir)
                os.replace(sdir, ddir)
                # 目录内的「书目元数据」一起改：chapters / decomposed 的书名，
                # 审查报告顶层 book 字段——否则改成新名后，旧报告与元数据仍写旧书名
                for fn in ("chapters.json", "decomposed.json"):
                    p = os.path.join(ddir, fn)
                    if not os.path.isfile(p):
                        continue
                    doc = read_json(p, {})
                    changed = False
                    for k in ("book_title", "book"):
                        if doc.get(k) == src:
                            doc[k] = dst
                            changed = True
                    chs0 = doc.get("chapters") or []
                    if chs0 and isinstance(chs0[0], dict) and chs0[0].get("book_title"):
                        chs0[0]["book_title"] = dst
                        changed = True
                    if changed:
                        write_json(p, doc)
                rdir = os.path.join(ddir, "review")
                if os.path.isdir(rdir):
                    for fn in os.listdir(rdir):
                        if not fn.lower().endswith(".json"):
                            continue
                        p = os.path.join(rdir, fn)
                        doc = read_json(p, {})
                        if isinstance(doc, dict) and doc.get("book") == src:
                            doc["book"] = dst
                            write_json(p, doc)
                _invalidate_outputs()      # 产出清单按 data/<书名>/ 收集，目录改名后必须重扫
                return self._send(200, {"book": dst})

            if path == "/api/preview_story_bible":
                # 预览用的整合结果，与实际保存走同一套逻辑，保证所见即所得
                text = compose_story_bible(body.get("fields", {}), body.get("cards", []),
                                           body.get("factions", []))
                # 附带按本章 roles / factions 裁剪后的版本，供前端预算面板估算。
                # 始终计算：roles 为空时 filter_by_roles 会退回主要角色卡，
                # 与按章裁剪（story_bible.filter_by_roles）保持同一口径；
                # factions 为空时势力卡全量保留（势力是世界级背景）。
                ch_text = filter_story_bible(text, body.get("roles") or [],
                                             body.get("chapter_factions") or [])
                return self._send(200, {"story_bible": text, "chars": len(text),
                                        "story_bible_chapter": ch_text, "chars_chapter": len(ch_text)})

            if path == "/api/outputs/clear":
                return self._send(200, {"ok": True, **clear_outputs(dry=bool(body.get("dry")))})

            if path == "/api/run":
                api_key = body.get("api_key") or ""
                stages = body.get("stages")
                if not stages:
                    stages = [{"stage": body.get("stage", ""), "args": body.get("args", {})}]
                if (not isinstance(stages, list)
                        or any(not isinstance(s, dict) for s in stages)):
                    return self._send(400, {"error": "stages 结构不合法（必须是对象数组）"})
                for s in stages:  # 预校验，避免跑一半才发现参数错
                    s["args"] = apply_stage_conf(s.get("stage", ""), s.get("args") or {})
                    build_cmd(s.get("stage", ""), s.get("args", {}))
                # 版权与 AI 使用声明：拆解 / 改编是法律风险最高的两步，未声明不允许开跑
                risk_stages = [s for s in stages
                               if s.get("stage") in ("decompose", "adapt")
                               and not (s.get("args") or {}).get("dry_run")]
                ack = None
                if risk_stages:
                    try:
                        ack = compliancelib.validate(body.get("compliance"))
                    except ValueError as e:
                        return self._send(400, {"error": str(e), "code": "compliance_required"})
                first, rest = stages[0], list(stages[1:])
                with JOB_LOCK:
                    # 所有通道共用一个并发额度：只看「正在跑多少」，不看是什么任务
                    if running_total() >= MAX_RUNNING_TASKS:
                        return self._send(429, {
                            "error": f"同时最多运行 {MAX_RUNNING_TASKS} 个任务，"
                                     f"请等其中一个结束或先停止"})
                    # 同一本书同一阶段不并行（会互相覆盖同一批产出文件）；
                    # 别的书、别的阶段都可以同时跑
                    dup = next((j for j in JOBS.values() if j["running"] and
                                j["stage"] == first.get("stage") and
                                j["book"].lower() == (sanitize_book(
                                    first.get("args", {}).get("book") or "") or "").lower()), None)
                    if dup:
                        return self._send(409, {
                            "error": f"《{dup['book']}》的「{JOB_LABEL.get(dup['stage'], dup['stage'])}」"
                                     f"已在运行（任务 {dup['id']}），请等它结束或先停止"})
                    # 批量扩写会写整本书的正文，和页内「正文生成」抢同一批文件：同书互斥
                    if first.get("stage") == "expand":
                        w = book_write_conflict(
                            sanitize_book(first.get("args", {}).get("book") or ""), page_write=True)
                        if w is not None:
                            return self._send(409, {"error":
                                f"《{w['book']}》第 {w['chapter_no']} 章正在页内生成"
                                f"（任务 {w['id']}），批量扩写会覆盖同一批正文，请等它结束"})
                    # 拆解会整份重写目标书的 chapters.json：开跑前先给现有版本留一份快照
                    if first.get("stage") == "decompose":
                        try:
                            backuplib.snapshot(sanitize_book(first.get("args", {}).get("book") or ""))
                        except Exception:
                            pass
                    job = new_job(first["stage"], first.get("args", {}), api_key,
                                  origin=clean_origin(body.get("origin")))
                    job["queue"] = rest
                    try:
                        spawn(job, first["stage"], first.get("args", {}))
                    except Exception as e:   # 例如 python 不在 PATH：不能把任务卡在 running
                        job.update(running=False, code=1, proc=None, queue=[],
                                   finished_at=time.time())
                        job["log"].append(f"[x] 启动失败：{e}")
                        raise ValueError(f"启动任务失败：{e}")
                if ack:
                    try:
                        s0 = risk_stages[0]
                        a0 = s0.get("args") or {}
                        compliancelib.record(
                            s0.get("stage"), ack,
                            source=str(a0.get("source") or ""),
                            book=str(a0.get("book") or ""),
                            out_book=str(a0.get("out_book") or ""))
                    except Exception:      # 留痕失败不影响任务本身
                        pass
                return self._send(200, {"ok": True, "id": job["id"], "stage": job["stage"],
                                        "label": job["label"], "stages": [s["stage"] for s in stages]})

            if path == "/api/job/stop":
                jid = str(body.get("id") or "").strip()
                pt = page_task_get(jid)
                if pt is not None:
                    if pt["stage"] == "review":
                        # 审查任务「停止」= 立即释放：用户点停止就是为了马上切章 / 干别的，
                        # 线程跑完当前这一步会自己退出，输出按 token 作废
                        released = page_release(pt)
                        return self._send(200, {"ok": True, "ids": [jid], "released": released})
                    # 正文生成是流式的：置停止标志后，下一个返回片就会中断并收尾
                    ok = page_stop(pt)
                    return self._send(200, {"ok": True, "ids": [jid], "stopped": ok})
                with JOB_LOCK:
                    if jid:
                        job = JOBS.get(jid)
                        if not job:
                            return self._send(404, {"error": f"任务 {jid} 不存在（可能已被清理）"})
                        targets = [job]
                    else:                      # 不带 id：停掉最近的那个运行中任务
                        targets = [j for j in sorted(JOBS.values(),
                                                     key=lambda x: x["created_at"], reverse=True)
                                   if j["running"]][:1]
                    for job in targets:
                        job["queue"] = []
                        job["stopped"] = True
                        if job["proc"]:
                            try:
                                job["proc"].terminate()
                            except Exception:  # noqa —— 进程可能刚好自己退出了
                                pass
                return self._send(200, {"ok": True, "ids": [j["id"] for j in targets]})

            if path == "/api/job/clear":
                # 清屏：只清空这个任务的日志行，任务状态 / 退出码保留（运行中也可以清，后续行继续追加）
                jid = str(body.get("id") or "").strip()
                pt = page_task_get(jid)
                if pt is not None:
                    with PAGE_LOCK:
                        del pt["log"][:]
                    return self._send(200, {"ok": True, "id": jid})
                with JOB_LOCK:
                    job = JOBS.get(jid)
                    if not job:
                        return self._send(404, {"error": f"任务 {jid} 不存在（可能已被删除）"})
                    del job["log"][:]
                return self._send(200, {"ok": True, "id": jid})

            if path == "/api/job/delete":
                # 删除单个任务：运行中的先拦下，否则子进程会失去日志与停止入口
                jid = str(body.get("id") or "").strip()
                pt = page_task_get(jid)
                if pt is not None:
                    if pt["running"]:
                        what = "审查" if pt["stage"] == "review" else "正文生成"
                        return self._send(409, {"error": f"{what}正在运行，请先停止 / 释放再删除"})
                    page_reset(jid)
                    return self._send(200, {"ok": True, "id": jid})
                with JOB_LOCK:
                    job = JOBS.get(jid)
                    if not job:
                        return self._send(404, {"error": f"任务 {jid} 不存在（可能已被删除）"})
                    if job["running"]:
                        return self._send(409, {"error": "任务正在运行，请先停止再删除"})
                    JOBS.pop(jid, None)
                return self._send(200, {"ok": True, "id": jid})

            if path == "/api/jobs/clear":
                # 清空全部任务：只删已结束的，运行中的必须保留（否则停止入口没了）
                with JOB_LOCK:
                    ids = [k for k, j in JOBS.items() if not j["running"]]
                    for k in ids:
                        JOBS.pop(k, None)
                with PAGE_LOCK:            # 页内任务记录一起清（运行中的保留）
                    done = [t["id"] for t in PAGE_TASKS.values() if not t["running"]]
                for tid in done:
                    page_reset(tid)
                ids.extend(done)
                return self._send(200, {"ok": True, "ids": ids, "removed": len(ids)})

            if path == "/api/job/resume":
                # 断点恢复（P0）：按原参数重新发起该任务；批量扩写自动跳过已有成稿的章节
                jid = str(body.get("id") or "").strip()
                with JOB_LOCK:
                    src = JOBS.get(jid)
                if not src:
                    return self._send(404, {"error": f"任务 {jid} 不存在（可能已被清理）"})
                if src["running"]:
                    return self._send(409, {"error": "任务正在运行，无需恢复"})
                stage = src["stage"]
                args = dict(src.get("args") or {})
                if stage == "expand":
                    args["skip_existing"] = True   # 续跑关键：只补没写成的章节
                if stage not in ("decompose", "adapt", "expand", "storymap"):
                    return self._send(400, {"error": f"该任务类型（{stage}）不支持恢复"})
                api_key = body.get("api_key") or ""   # Key 不落盘：恢复时需重新提供
                try:
                    build_cmd(stage, args)           # 预校验
                except ValueError as e:
                    return self._send(400, {"error": f"无法恢复：{e}"})
                with JOB_LOCK:
                    if running_total() >= MAX_RUNNING_TASKS:
                        return self._send(429, {"error": f"同时最多运行 {MAX_RUNNING_TASKS} 个任务"})
                    dup = next((j for j in JOBS.values() if j["running"] and
                                j["stage"] == stage and
                                j["book"].lower() == (args.get("book") or "").lower()), None)
                    if dup:
                        return self._send(409, {"error": f"《{dup['book']}》同阶段任务已在运行"})
                    job = new_job(stage, args, api_key, origin=src.get("origin") or "")
                    try:
                        spawn(job, stage, args)
                    except Exception as e:
                        job.update(running=False, code=1, proc=None, queue=[],
                                   finished_at=time.time())
                        job["log"].append(f"[x] 启动失败：{e}")
                        raise ValueError(f"启动任务失败：{e}")
                src["interrupted"] = False
                return self._send(200, {"ok": True, "id": job["id"], "stage": stage,
                                        "label": job["label"],
                                        "resumed_from": jid})

            if path == "/api/history/rollback":
                # 回滚到某个历史版本：当前正文先自动快照（回滚本身也可撤销）
                name = sanitize_book(body.get("book") or "")
                no = to_int(body.get("no"), 0)
                fname = os.path.basename(str(body.get("file") or ""))
                if not name or no <= 0 or not fname:
                    return self._send(400, {"error": "参数不完整（book / no / file）"})
                ok, msg = historylib.rollback(name, no, fname)
                if not ok:
                    return self._send(404, {"error": msg or "回滚失败"})
                _invalidate_outputs()
                return self._send(200, {"ok": True, "book": name, "no": no})

            if path == "/api/usage/clear":
                # 用量记录与码字统计一起清（统计页两块都归「统计」，只清一半会让人以为没生效）
                removed = usagelib.clear()
                return self._send(200, {"ok": True, **removed})

            if path == "/api/sentinel/scan":
                # 敏感词预检：单章（no>0）或全书；也可直接扫粘贴的 text
                if (body.get("text") or "").strip():
                    return self._send(200, sentinellib.scan_text(str(body.get("text"))))
                name, err = resolve_book(body.get("book") or "")
                if err:
                    return self._send(*err)
                if not name:
                    return self._send(400, {"error": "请选择作品"})
                no = to_int(body.get("no"), 0)
                if no > 0:
                    r = sentinellib.scan_chapter(name, no)
                    if r is None:
                        return self._send(404, {"error": f"第 {no} 章还没有成稿正文"})
                    r["scope"] = "chapter"
                    r["no"] = no
                    return self._send(200, r)
                r = sentinellib.scan_book(name)
                r["scope"] = "book"
                return self._send(200, r)

            if path == "/api/review/batch":
                # 全书体检（P2）：对全部成稿章节批量跑审查，汇总全书问题清单
                mod = review_module()
                name = sanitize_book(body.get("book") or "")
                if not name:
                    raise ValueError("书名不合法或未选择书")
                checks = [c for c in (body.get("checks") or mod.ALL_CHECKS) if c in mod.CHECK_LABEL]
                if not checks:
                    raise ValueError("没有勾选任何检查项")
                incremental = bool(body.get("incremental", True))
                busy = next((t for t in list(PAGE_TASKS.values())
                             if t["stage"] == "review" and t["running"] and t["book"] == name
                             and not str(t.get("chapter_no") or "")), None)
                if busy:
                    return self._send(409, {"error": f"《{name}》已有一次全书体检在跑（任务 {busy['id']}）"})
                if running_total() >= MAX_RUNNING_TASKS:
                    return self._send(429, {"error":
                        f"同时在跑的任务已有 {MAX_RUNNING_TASKS} 个，请等一些结束再发起"})
                rconf = studiolib.stage_conf("review")
                t = page_task_new("review", name, "", body.get("origin"), title="全书体检")
                page_log(t, f"[体检] 《{name}》全书体检启动"
                            f"（{'增量：只检未审或已改动的章节' if incremental else '全量：所有章节重跑'}）")
                start_page_thread(t, batch_review_worker, {
                    "mod": mod, "book": name, "checks": checks,
                    "api_key": body.get("api_key") or "",
                    "model": (body.get("model") or "").strip() or rconf.get("model") or None,
                    "base_url": (body.get("base_url") or "").strip() or rconf.get("base_url") or None,
                    "incremental": incremental, "top_n": 3,
                })
                return self._send(200, {"ok": True, "id": t["id"], "title": "全书体检"})

            if path == "/api/review/signing":
                # 签约预审：跨章扫前 2 万字（≈前 10 章），只诊断不改写
                mod = review_module()
                name = sanitize_book(body.get("book") or "")
                if not name:
                    raise ValueError("书名不合法或未选择书")
                busy = next((t for t in list(PAGE_TASKS.values())
                             if t["stage"] == "review" and t["running"]
                             and t["book"] == name and t.get("title") == "签约预审"), None)
                if busy:
                    return self._send(409, {"error": f"《{name}》已有一次签约预审在跑（任务 {busy['id']}）"})
                if running_total() >= MAX_RUNNING_TASKS:
                    return self._send(429, {"error":
                        f"同时在跑的任务已有 {MAX_RUNNING_TASKS} 个，请等一些结束再发起"})
                rconf = studiolib.stage_conf("review")
                t = page_task_new("review", name, "", body.get("origin"), title="签约预审")
                page_log(t, f"[预审] 《{name}》签约预审启动：扫前 2 万字（≈前 10 章）")
                start_page_thread(t, signing_worker, {
                    "mod": mod, "book": name,
                    "model": (body.get("model") or "").strip() or rconf.get("model") or None,
                    "base_url": (body.get("base_url") or "").strip() or rconf.get("base_url") or None,
                    "api_key": body.get("api_key") or "",
                })
                return self._send(200, {"ok": True, "id": t["id"], "title": "签约预审"})

            if path == "/api/review/run":
                mod = review_module()
                name = sanitize_book(body.get("book") or "")
                if not name:
                    raise ValueError("书名不合法或未选择书")
                chapter_no = str(body.get("chapter_no") or "").strip()
                if not chapter_no:
                    raise ValueError("请选择 / 填写章节号")
                text = (body.get("chapter_text") or "").strip()
                if not text:
                    raise ValueError("章节正文为空：请粘贴或上传单章正文")
                checks = [c for c in (body.get("checks") or mod.ALL_CHECKS) if c in mod.CHECK_LABEL]
                if not checks:
                    raise ValueError("没有勾选任何检查项")
                # 分阶段模型绑定（P1）：页面没填模型 / 端点时，用设置页里「AI 审查」的绑定
                rconf = studiolib.stage_conf("review")
                try:
                    top_n = int(body.get("top_n") or mod.DEFAULT_TOP_N)
                except (TypeError, ValueError):
                    raise ValueError("Top 问题条数须为整数")
                scope = str(body.get("advice_scope") or mod.DEFAULT_ADVICE_SCOPE)
                if scope not in mod.ADVICE_SCOPES:
                    scope = mod.DEFAULT_ADVICE_SCOPE
                kwargs = {
                    "book": name, "chapter_no": chapter_no, "chapter_text": text,
                    "checks": checks,
                    "model": (body.get("model") or "").strip() or rconf.get("model") or None,
                    "base_url": (body.get("base_url") or "").strip() or rconf.get("base_url") or None,
                    "api_key": body.get("api_key") or "",
                    "top_n": max(1, min(40, top_n)),
                    "advice_scope": scope,
                }
                # 同一本书同一章不做两路审查：结果会写同一份报告，界面上也分不清谁是谁。
                # 别的章 / 别的书互不影响，可以同时跑。
                busy = page_busy("review", name, chapter_no)
                if busy:
                    return self._send(409, {"error":
                        f"《{name}》第 {chapter_no} 章已经有一条审查在跑，请等它结束或先释放"})
                if running_total() >= MAX_RUNNING_TASKS:
                    return self._send(429, {"error":
                        f"同时在跑的任务已有 {MAX_RUNNING_TASKS} 个，请等一些结束再发起"})
                # 任务名要跟实际跑的东西对上：有 Key 且勾了要调模型的检查项才算 AI 审查，
                # 否则只是行文统计 + 错别字规则初筛，叫「程序体检」。
                try:
                    key_ok = bool(mod._resolve_key(kwargs.get("api_key")))
                except Exception:      # 老版本模块没有这个函数
                    key_ok = bool(kwargs.get("api_key"))
                ai_checks = [c for c in checks
                             if c not in getattr(mod, "NO_CALL_CHECKS", {"stats"}) and c != "advice"]
                title = "AI 审查" if (key_ok and ai_checks) else "程序体检"
                t = page_task_new("review", name, chapter_no, body.get("origin"), title=title)
                scope_txt = "、".join(mod.TYPE_LABEL[x] for x in mod.ADVICE_SCOPES[scope])
                page_log(t, f"[审查] 《{name}》{chapter_no}｜检查项："
                            f"{'、'.join(mod.CHECK_LABEL[c] for c in checks)}"
                            f"｜建议范围：{scope_txt}")
                start_page_thread(t, review_worker, {"mod": mod, "kwargs": kwargs})
                return self._send(200, {"ok": True, "checks": checks, "id": t["id"],
                                        "title": title})

            if path in ("/api/review/stop", "/api/review/release"):
                # 按 id 定位这条审查；不带 id 时按「书 + 章」找本章最近的一条
                tid = str(body.get("id") or "").strip()
                t = page_task_get(tid) if tid else None
                if t is None:
                    name = sanitize_book(body.get("book") or "")
                    t = page_task_latest("review", name,
                                         str(body.get("chapter_no") or "").strip())
                if t is None:
                    return self._send(200, {"ok": True, "id": "", "released": False})
                if path == "/api/review/stop":
                    return self._send(200, {"ok": True, "id": t["id"],
                                            "stopped": page_stop(t)})
                # 释放：不等当前这一步跑完，立刻解锁，好让用户切章 / 发起别的生成或审查
                return self._send(200, {"ok": True, "id": t["id"],
                                        "released": page_release(t)})

            if path == "/api/expand/chapter":
                # 单章正文生成：进程内线程 + LLM 流式，正文增量经 /api/expand/job 轮询回显
                name = sanitize_book(body.get("book") or "")
                if not name:
                    raise ValueError("书名不合法或未选择书")
                if not os.path.isfile(book_chapters(name)):
                    raise ValueError(f"书「{name}」没有章节数据，请先拆解/编辑章节")
                from expand import _chapter_no, MODE_LABEL
                from deepseek_common import DEFAULT_MODEL, resolve_base_url

                mode = str(body.get("mode") or "outline").strip().lower()
                if mode not in MODE_LABEL:
                    raise ValueError(f"未知生成模式：{mode}")
                # 文风切换（都市/玄幻/古言/悬疑/甜宠/爽文），留空则沿用设定库
                style = str(body.get("style") or "").strip()
                # 多版本数量（仅非大纲模式生效），默认 3，范围 1~5
                count = to_int(body.get("count"), 3)
                count = max(1, min(5, count))
                # scope=selection 时 text 传的是选中片段，chapter 时是整章正文
                scope = "selection" if str(body.get("scope") or "") == "selection" else "chapter"
                # 续写/扩写/改写需要已有正文（取前端编辑器当前内容，可能是未保存的修改）
                existing = str(body.get("text") or "")
                if mode != "outline" and not existing.strip():
                    if scope == "selection":
                        raise ValueError(f"没有选中内容，无法「{MODE_LABEL[mode]}选区」，请先在正文里选中片段")
                    raise ValueError(f"本章还没有正文，无法「{MODE_LABEL[mode]}」，请先用「按大纲生成」")

                ch_data = read_json(book_chapters(name), {})
                dec = read_json(book_decomposed(name), {})
                chapters = ch_data.get("chapters") or dec.get("chapters") or []
                if not chapters:
                    raise ValueError(f"书「{name}」没有章节数据，请先拆解/编辑章节")
                want = to_int(body.get("chapter_no"), 0)
                if want <= 0:
                    raise ValueError("章节号不合法：请提供正整数（如 12 或「第12章」）")
                idx = next((i for i, c in enumerate(chapters)
                            if _chapter_no(c, i + 1) == want), None)
                if idx is None:
                    raise ValueError(f"书「{name}」里没有第 {want} 章")
                # 设定 / 角色卡 / 势力卡：优先用 UI 编辑后保存的 story_bible（最新），
                # 否则退回拆解产出的 decomposed.json
                raw_sb = ch_data.get("story_bible")
                sb, characters, factions = {}, [], []
                if isinstance(raw_sb, str) and raw_sb.strip():
                    fields, cards, facs = parse_story_bible(raw_sb)
                    sb, characters, factions = dict(fields), list(cards), list(facs)
                # 用户没在 UI 里填设定库（或解析为空）时，退回拆解产出的结构化设定
                if not sb and isinstance(dec.get("story_bible"), dict):
                    sb = dec.get("story_bible") or {}
                characters = characters or [c for c in (dec.get("characters") or [])
                                            if isinstance(c, dict)]
                factions = factions or [f for f in (dec.get("factions") or [])
                                        if isinstance(f, dict)]
                try:
                    temperature = float(body.get("temperature") or 0.7)
                except (TypeError, ValueError):
                    temperature = 0.7
                api_key = (body.get("api_key") or os.environ.get("DEEPSEEK_API_KEY", "")).strip()
                # 审查→改写闭环（P1）：fix_from_review 时把最近审查报告的问题清单
                # 作为「必须修复」指令追加进改写提示词
                extra_block = ""
                if body.get("fix_from_review"):
                    extra_block, n_fix = format_review_issues(name, want)
                    if not extra_block:
                        raise ValueError(f"第 {want} 章没有可用的审查结论：请先在「正文审查」跑一遍")
                    if not existing.strip():
                        raise ValueError("本章还没有正文，无法按审查意见改写")
                    mode = "rewrite"
                # 多模型绑定：选区 / 初稿 / 续写 / 扩写 / 改写 / 润色各查各的工序绑定，
                # 页面没填模型 / 端点时用设置页里对应工序绑定的档案
                # （在 fix_from_review 之后解析：它会把模式强制成 rewrite，应吃「正文改写」的绑定）
                conf = studiolib.stage_conf(resolve_stage_key("expand", mode, scope))
                # 没有 Key 不再拦：worker 会走本地骨架，产出可直接编辑的写作清单
                kwargs = dict(
                    book=name, ch=chapters[idx], sb=sb, characters=characters,
                    factions=factions, ch_no=want, api_key=api_key,
                    # 未指定端点时回落 DeepSeek：否则请求会打到 api.openai.com，正文生成必然失败
                    base_url=resolve_base_url((body.get("base_url") or "").strip()
                                              or conf.get("base_url") or None),
                    model=(body.get("model") or "").strip() or conf.get("model") or DEFAULT_MODEL,
                    temperature=temperature, mode=mode, existing=existing,
                    style=style, n=count,
                    # 选区操作的前后文：单句承接靠它们，整章生成为空串
                    before=str(body.get("before") or "")[:2000],
                    after=str(body.get("after") or "")[:1000],
                    extra_block=extra_block,
                )
                # 只有「同一本书同一章」不能同时生成两路（会互相覆盖同一份正文），
                # 别的章、别的书都可以并行——多任务并发就靠这条规则。
                busy = page_busy("write", name, want)
                if busy:
                    return self._send(409, {"error":
                        f"《{name}》第 {want} 章正在生成，请等它结束或先停止"
                        "（其它章可以直接并发生成）"})
                # 批量扩写会写整本书的正文：同书在跑批量扩写时不接受单章生成（别的书不受影响）
                bulk = book_write_conflict(name, page_write=False)
                if bulk is not None:
                    return self._send(409, {"error":
                        f"《{name}》的批量扩写正在运行（任务 {bulk['id']}），"
                        "它会覆盖整本书的正文，请等它结束再单章生成"})
                if running_total() >= MAX_RUNNING_TASKS:
                    return self._send(429, {"error":
                        f"同时在跑的任务已有 {MAX_RUNNING_TASKS} 个，请等一些结束再发起"})
                # scope 已在上面解析（决定任务名与候选面板落点）
                t = page_task_new("write", name, want, body.get("origin"),
                                  mode=mode, scope=scope, multi=(mode != "outline"),
                                  title=("按审查意见改写" if extra_block else ""))
                # 生成前的正文与选区位置跟着这条任务走：切章 / 切书回来恢复候选时，
                # 还要靠它判断「能不能直接采纳」，以及整章续写要接在哪段原文之后
                with PAGE_LOCK:
                    t["existing"] = existing
                    t["target"] = ({"start": to_int(body.get("sel_start"), 0),
                                    "end": to_int(body.get("sel_end"), 0),
                                    "text": existing,
                                    "before": kwargs["before"],
                                    "after": kwargs["after"]}
                                   if scope == "selection" else None)
                start_page_thread(
                    t, expand_worker if mode == "outline" else expand_versions_worker, kwargs)
                return self._send(200, {"ok": True, "id": t["id"], "chapter_no": want,
                                        "book": name, "mode": mode, "scope": scope,
                                        "name": page_task_name(t)})

            if path == "/api/expand/stop":
                # 按 id 停某一条；不带 id 时按「书 + 章」找本章最近的一条（兼容旧前端）
                tid = str(body.get("id") or "").strip()
                t = page_task_get(tid) if tid else None
                if t is None:
                    name = sanitize_book(body.get("book") or "")
                    t = page_task_latest("write", name,
                                         str(body.get("chapter_no") or "").strip())
                if t is None:
                    return self._send(200, {"ok": True, "id": "", "stopped": False})
                return self._send(200, {"ok": True, "id": t["id"], "stopped": page_stop(t)})
            return self._send(404, {"error": "no route"})
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        except Exception as e:  # noqa
            return self._send(500, {"error": str(e)})


_MAIN_BOOTED = False


def main():
    global _MAIN_BOOTED
    guardlib.enforce()
    ensure_dirs()
    moved = migrate_legacy_data()
    if moved:
        print(f"[迁移] 旧版 data/ 根产出已搬入 data/{moved}/")
    # 同一进程里可能二次启动（手机端启动失败后重启引擎）：任务恢复与落盘线程只做一次，
    # 否则会把内存里正在跑的任务当成「上次会话中断」覆盖掉，也会多开一个落盘线程。
    if not _MAIN_BOOTED:
        _MAIN_BOOTED = True
        # 任务持久化：恢复上次任务表（运行中的标记为「中断」），并开启定期落盘线程
        n_restored = _restore_tasks()
        if n_restored:
            print(f"[任务] 已恢复上次会话的 {n_restored} 条任务记录（中断的任务可在任务中心恢复）")
        threading.Thread(target=_tasks_persist_loop, daemon=True).start()
    # Windows 下 SO_REUSEADDR 允许两个进程同时绑同一端口（旧进程会静默接管请求），必须关；
    # Linux / Android 下它只允许复用 TIME_WAIT 里的旧连接，是「关掉后马上重开」还能绑上
    # 同一端口的前提——关掉会让手机端第二次打开因 Address already in use 起不来服务。
    class Server(ThreadingHTTPServer):
        allow_reuse_address = os.name != "nt"

        def handle_error(self, request, client_address):
            # 浏览器切页 / 关标签会直接断开 keep-alive 连接，这不是服务端故障：
            # 默认实现会把整段 traceback 刷到控制台，把真正的报错淹没掉。
            if isinstance(sys.exc_info()[1], (ConnectionResetError, BrokenPipeError)):
                return
            super().handle_error(request, client_address)

    try:
        srv = Server((HOST, PORT), Handler)
    except OSError as e:
        if os.environ.get("MOBIT_ANDROID"):
            sys.exit(f"[x] 端口 {PORT} 被占用（{e}）")
        sys.exit(f"[x] 端口 {PORT} 已被占用（{e}）。\n"
                 f"    多半是上一次的控制台还在运行：关掉那个窗口，或先执行\n"
                 f"    netstat -ano | findstr :{PORT}   然后 taskkill /PID <pid> /F")
    print(f"小说工作流控制台已启动： http://localhost:{PORT}")
    if HOST not in ("127.0.0.1", "localhost"):
        # 手机端（App / 手机浏览器）要连的就是局域网地址，启动时直接打印出来省得查 ipconfig
        lan_ip = ""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            lan_ip = s.getsockname()[0]
            s.close()
        except Exception:
            pass
        print(f"手机 / 平板与本机同一 Wi-Fi 时，在墨写 App 里填：")
        if lan_ip:
            print(f"    {lan_ip}:{PORT}")
        print(f"    （其他网卡的地址用 ipconfig 查看，端口都是 {PORT}）")
    print("按 Ctrl+C 停止")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
