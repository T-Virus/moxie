# -*- coding: utf-8 -*-
"""创作合规留痕
================
拆解 / 改编会直接接触第三方作品，是本产品最大的法律风险点。
这里只做两件事：

  1) 校验前端提交的「权利来源 + 权利确认 + AI 使用知情」三项声明；
  2) 把每次声明追加到 data/_system/compliance.jsonl，形成可追溯的本地审计记录。

不做任何法律判断，也不替代律师意见；目的是把「用户承诺」固化成可查证据，
并阻止未做声明的拆解 / 改编请求直接开跑。
"""

import json
import os
import threading
import time

from paths import DATA_DIR

# 权利来源：自有 / 已授权 / 公版。其他写法一律拒绝，避免「随便勾一下」绕过。
BASES = {
    "own": "自有作品",
    "authorized": "已获授权",
    "public": "公有领域",
}

LOG_PATH = os.path.join(DATA_DIR, "_system", "compliance.jsonl")
_LOCK = threading.Lock()


def validate(ack):
    """校验声明；不合法时抛 ValueError（由 webapp 转成 400）。"""
    if not isinstance(ack, dict):
        raise ValueError("请先完成版权与 AI 使用声明后再开始")
    basis = str(ack.get("basis") or "").strip()
    if basis not in BASES:
        raise ValueError("请选择作品权利来源：自有作品 / 已获授权 / 公有领域")
    if ack.get("rights_confirmed") is not True:
        raise ValueError("请确认你拥有该作品权利、已获授权，或该作品属于公有领域")
    if ack.get("ai_notice_ack") is not True:
        raise ValueError("请确认知悉：AI 产出需人工修改，并按平台要求披露 AI 参与程度")
    return {
        "basis": basis,
        "basis_label": BASES[basis],
        "note": str(ack.get("note") or "").strip()[:500],
    }


def record(stage, ack, source="", book="", out_book=""):
    """追加一条合规声明记录，返回写入的条目。"""
    entry = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "stage": str(stage or ""),
        "source": str(source or ""),
        "book": str(book or ""),
        "out_book": str(out_book or ""),
        "basis": ack.get("basis", ""),
        "basis_label": ack.get("basis_label", ""),
        "note": ack.get("note", ""),
    }
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with _LOCK:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def recent(limit=50):
    """最近若干条声明（给设置页/排查用，不参与业务逻辑）。"""
    if not os.path.isfile(LOG_PATH):
        return []
    out = []
    try:
        with open(LOG_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    return out[-max(1, limit):][::-1]
